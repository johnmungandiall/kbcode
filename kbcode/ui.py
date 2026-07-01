"""Terminal look-and-feel — a Claude Code / Hermes style chat surface.

This is the presentation layer. The agent loop talks to a :class:`TerminalUI`
instead of printing directly, so the loop stays about *logic* and this file owns
the *look*: a header banner, markdown-rendered answers, tidy tool-call lines, a
status footer, and a help table.

Everything degrades gracefully — if a value can't be rendered richly we fall
back to plain text, so it stays robust on basic Windows consoles.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .prompt_input import select

_TOOL_ICON = "⏺"
_ARROW = "›"

# The command palette — single source of truth for /help and for the
# "/" autocomplete popup (see prompt_input.py).
COMMANDS = [
    ("/help", "show this help"),
    ("/version", "show the kbcode version"),
    ("/mode [name]", "switch mode: code / architect / ask / debug (no name = list)"),
    ("/provider [name] [model]", "switch provider (no name = list them)"),
    ("/model [id]", "switch model (no id = list this provider's models)"),
    ("/status", "show provider, model, mode and context size"),
    ("/ping", "quick connectivity/auth check for the current provider"),
    ("/open <folder>", "switch to working on another project folder"),
    ("/kb", "list knowledge-base notes"),
    ("/memory", "show recent long-term memory"),
    ("/memory-prune [days]", "remove duplicate memories (and, if given, anything older than [days])"),
    ("/skills", "list learned skills"),
    ("/todo", "show the agent's current task checklist"),
    ("/agents", "list available subagents (.kbcode/agents/)"),
    ("/image [path]", "attach an image (clipboard, or a file) for your next message — also Alt+V"),
    ("/video <path> [question]", "describe a local video (via an auxiliary vision model) for your next message"),
    ("/learn [topic]", "save what we just did as a reusable skill"),
    ("/insights", "show tokens used and estimated cost (this chat + all saved sessions)"),
    ("/cost", "one-line cost summary — model · tokens · $ (see /insights for detail)"),
    ("/kb-check [--fix]", "check (or auto-fix) kb/ path:line pointers"),
    ("/compact", "summarize earlier chat to free up context"),
    ("/rollback", "undo AI edits — pick a checkpoint from a menu (auto-saved before every edit)"),
    ("/sessions [query]", "list past chat sessions for this project, or full-text search them"),
    ("/export [id]", "export a session (current, or by id) as a markdown file"),
    ("/resume [id]", "resume a past session (no id = pick from a list)"),
    ("/reset", "forget this chat (memory + kb are kept; starts a fresh saved session)"),
    ("/exit", "quit"),
]


def _short(value: object, limit: int = 100) -> str:
    text = " ".join(str(value).split())  # collapse whitespace/newlines to one line
    return text if len(text) <= limit else text[:limit] + "…"


def _human_count(n: int) -> str:
    """1234 -> '1.2k', 2_500_000 -> '2.5M'."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return f"{n / 1_000_000:.1f}M".replace(".0M", "M")


def _context_bar(tokens: int, limit: int, segments: int = 5) -> str:
    """A compact ``▓▓░░░ 32%`` indicator (#7.5) — how full the context is
    before auto-compaction kicks in. Empty string when there's no limit to
    measure against (auto-compaction off), so the prompt stays uncluttered.
    """
    if limit <= 0:
        return ""
    pct = min(100, round(tokens / limit * 100))
    filled = round(pct / 100 * segments)
    bar = "▓" * filled + "░" * (segments - filled)
    return f"{bar} {pct}% "


# Each entry turns a tool's raw args into a human (verb, target) pair, like a
# real CLI shows — a dict registry instead of a long if-name-== chain, so
# adding a tool's display line means adding one entry here, not another branch.
# `g(key)` reads a stringified/stripped arg; `full(path)` resolves it to where
# the file actually lives (the model usually passes a bare relative name).
def _describe_read_file(a, g, full):
    return "Read", full(g("path"))


def _describe_write_file(a, g, full):
    return "Write", f"{full(g('path'))}  ({len(str(a.get('content', ''))):,} chars)"


def _describe_edit_file(a, g, full):
    return "Edit", full(g("path"))


def _describe_list_dir(a, g, full):
    return "List", g("path") or "."


def _describe_search_code(a, g, full):
    where = f"  in {g('path')}" if g("path") else ""
    return "Search", f'"{g("pattern")}"{where}'


def _describe_run_command(a, g, full):
    return "Run", "$ " + g("command")


def _describe_kb_read(a, g, full):
    return "KB read", ""


def _describe_kb_search(a, g, full):
    return "KB search", f'"{g("query")}"'


def _describe_kb_write(a, g, full):
    return "KB write", g("name")


def _describe_remember(a, g, full):
    return "Remember", g("key") or _short(g("content"), 60)


def _describe_recall(a, g, full):
    return "Recall", f'"{g("query")}"'


def _describe_save_skill(a, g, full):
    return "Save skill", g("name")


def _describe_manage_todos(a, g, full):
    n = len(a.get("todos") or [])
    return "Plan", f"{n} item{'s' if n != 1 else ''}"


def _describe_run_subagent(a, g, full):
    return "Delegate", f"→ {g('agent')}: {_short(g('task'), 60)}"


def _describe_web_search(a, g, full):
    return "Web search", f'"{g("query")}"'


_TOOL_DESCRIBERS = {
    "read_file": _describe_read_file,
    "write_file": _describe_write_file,
    "edit_file": _describe_edit_file,
    "edit_files": "edit multiple files",
    "list_dir": _describe_list_dir,
    "search_code": _describe_search_code,
    "repo_map": "get codebase structure map",
    "run_command": _describe_run_command,
    "kb_read": _describe_kb_read,
    "kb_search": _describe_kb_search,
    "kb_write": _describe_kb_write,
    "remember": _describe_remember,
    "recall": _describe_recall,
    "save_skill": _describe_save_skill,
    "manage_todos": _describe_manage_todos,
    "run_subagent": _describe_run_subagent,
    "web_search": _describe_web_search,
}


def _describe_tool(name: str, args: dict, root: Path | None = None) -> tuple[str, str]:
    """Turn a raw tool call into a human verb + target, like a real CLI shows."""
    a = args or {}

    def g(key: str) -> str:
        return str(a.get(key, "")).strip()

    def full(path: str) -> str:
        """Resolve a path to its full location so the user sees *where* a file
        actually is (the model usually passes a bare relative name)."""
        if not path or root is None:
            return path
        try:
            p = Path(path)
            return str((p if p.is_absolute() else root / p).resolve())
        except (OSError, ValueError):
            return path

    describer = _TOOL_DESCRIBERS.get(name)
    if describer is None:
        return name, (_short(a) if a else "")
    return describer(a, g, full)


class _TickingStatus:
    """A :meth:`Console.status` spinner whose label counts up in seconds.

    A plain spinner still animates once a second or two of blocking work has
    passed, but nothing on screen shows *how long* it's been running — which
    is exactly what makes a slow tool call or model turn look stalled. A
    background ticker thread updates the status text every 100ms so the
    elapsed time itself is the "still alive" signal.
    """

    def __init__(self, console: Console, label: str, hint: str = "", total_start: float | None = None, ui: TerminalUI | None = None):
        self._ui = ui
        self._label = label
        self._hint = hint
        self._total_start = total_start
        self._start = 0.0
        self._status = console.status(self._render(0.0), spinner="dots")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stopped = False
        self._stop_lock = threading.Lock()  # so worker + main thread can't tear down at once

    def _render(self, elapsed: float) -> str:
        text = f"[dim]{self._label}… {elapsed:.1f}s[/dim]"
        if self._total_start is not None:
            total = time.perf_counter() - self._total_start
            text += f"  [dim](total {total:.1f}s)[/dim]"
        if self._hint:
            text += f"  [dim italic]{self._hint}[/dim italic]"
        return text

    def _tick(self) -> None:
        while not self._stop.wait(0.1):
            self._status.update(self._render(time.perf_counter() - self._start))

    def __enter__(self):
        self._start = time.perf_counter()
        self._status.__enter__()
        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()
        if self._ui is not None:
            self._ui._active_status = self
        return self

    def stop(self) -> None:
        """Tear down the spinner + ticker thread. Idempotent and safe to call
        from any thread, so the streaming-text callback — which runs on the
        provider worker thread — can end the spinner the instant the first
        token arrives. If it didn't, the ticker's Rich ``Live`` redraw (every
        100ms) would race the raw streamed prints and shred the reply into
        trailing line-fragments (see [[gotchas]] streaming note)."""
        with self._stop_lock:  # check-and-tear-down must be atomic across threads
            if self._stopped:
                return
            self._stopped = True
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=0.2)
            self._status.__exit__(None, None, None)
            if self._ui is not None and self._ui._active_status is self:
                self._ui._active_status = None

    def __exit__(self, *exc):
        self.stop()
        return False


class TerminalUI:
    """All terminal output flows through here so the style stays consistent."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        # Project root, so file tool-lines can show *where* a file actually is.
        # Set by the CLI when an agent is built / a project is opened.
        self.root: Path | None = None
        # Set by turn_started() — lets every spinner in this turn also show a
        # running grand total, so the total keeps counting across separate
        # thinking / tool-running spinners instead of resetting each time.
        self._turn_start: float | None = None
        # The spinner currently on screen, if any. stream_chunk() stops it the
        # moment real text starts arriving so the spinner's background redraw
        # can't race the streamed prints (see _TickingStatus.stop).
        self._active_status: _TickingStatus | None = None

    def turn_started(self) -> None:
        """Mark the start of a new agent turn (call once per user turn)."""
        self._turn_start = time.perf_counter()

    # -- chrome ---------------------------------------------------------
    def banner(self, provider: str, model: str, cwd: Path, mode: str = "code") -> None:
        info = Table.grid(padding=(0, 2))
        info.add_column(justify="right", style="dim")
        info.add_column(style="bold")
        info.add_row("provider", provider)
        info.add_row("model", model)
        info.add_row("mode", mode)
        info.add_row("folder", str(cwd))

        body = Table.grid(padding=(0, 0))
        body.add_row(Text("kbcode by John Mungandi", style="dim italic"))
        body.add_row("")
        body.add_row(info)
        body.add_row("")
        body.add_row(Text("/help for commands  ·  /exit to quit", style="dim"))

        self.console.print(
            Panel(
                body,
                title=f"[bold cyan]kbcode[/bold cyan] [dim]v{__version__}[/dim]",
                border_style="cyan",
                padding=(1, 2),
            )
        )

    def prompt(self, mode: str = "code", tokens: int = 0, limit: int = 0) -> str:
        tag = "" if mode == "code" else f"[cyan]({mode})[/cyan] "
        bar = _context_bar(tokens, limit)
        ctx = f"[dim]{bar}[/dim]" if bar else ""
        return f"\n{ctx}{tag}[bold green]you {_ARROW}[/bold green] "

    def prompt_html(self, mode: str = "code", tokens: int = 0, limit: int = 0) -> str:
        tag = "" if mode == "code" else f"<ansicyan>({mode})</ansicyan> "
        bar = _context_bar(tokens, limit)
        ctx = f"<ansigray>{bar}</ansigray>" if bar else ""
        return f"\n{ctx}{tag}<ansigreen><b>you ›</b></ansigreen> "

    def help(self) -> None:
        desc = dict(COMMANDS)
        groups = [
            ("session", ["/help", "/version", "/status", "/ping", "/open <folder>", "/insights", "/cost", "/compact", "/rollback", "/sessions [query]", "/export [id]", "/resume [id]", "/reset", "/exit"]),
            ("knowledge & memory", ["/kb", "/kb-check [--fix]", "/memory", "/memory-prune [days]", "/skills", "/learn [topic]"]),
            ("planning & agents", ["/todo", "/agents", "/image [path]", "/video <path> [question]"]),
            ("models & modes", ["/mode [name]", "/provider [name] [model]", "/model [id]"]),
        ]
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left", overflow="fold")
        table.add_column(overflow="fold")
        for gi, (title, cmds) in enumerate(groups):
            if gi:
                table.add_row("", "")
            table.add_row(Text(title.upper(), style="bold dim"), "")
            for cmd in cmds:
                if cmd in desc:
                    # Use Text (not markup) so '[name]' / '[--fix]' render literally.
                    table.add_row(Text(cmd, style="bold cyan"), Text(desc[cmd], style="white"))
        self.console.print(Panel(table, title="commands", border_style="dim", padding=(1, 1)))
        self.console.print("[dim]Anything else you type is sent to the agent as a request.[/dim]")

    def permission(self, tool: str, detail: str) -> str:
        """Ask for approval via a selectable menu (Claude Code style).

        Returns 'y' (allow once) / 'a' (allow for the session) / 'n' (deny).
        Falls back to a typed y/N/a prompt when no interactive menu is available.
        """
        body = Text()
        body.append(f"{tool}\n", style="bold yellow")
        for line in (detail.splitlines() or [detail]):
            body.append(line + "\n", style="white")
        self.console.print(
            Panel(body, title="⚠  permission needed", border_style="yellow", padding=(0, 1))
        )

        labels = ["Yes", f"Yes, and don't ask again for {tool} this session", "No"]
        codes = ["y", "a", "n"]
        available, idx = select(labels, header="  ↑/↓ then Enter (or press 1/2/3):")
        if not available:
            return self._permission_typed()
        if idx is None:  # Esc / Ctrl-C
            self.console.print("  ✗ No", style="red")
            return "n"
        chosen = codes[idx]
        self.console.print(f"  → {labels[idx]}", style="green" if chosen != "n" else "red")
        return chosen

    def _permission_typed(self) -> str:
        try:
            ans = self.console.input(
                "  allow?  [green]y[/green]es / [red]N[/red]o / [cyan]a[/cyan]lways  › "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "n"
        if ans in ("a", "always"):
            return "a"
        return "y" if ans in ("y", "yes") else "n"

    def status_line(self, provider: str, model: str, mode: str, tokens: int, limit: int = 0) -> None:
        ctx = f"~{_human_count(tokens)} tokens"
        if limit > 0:
            pct = min(100, round(tokens / limit * 100))
            filled = round(pct / 10)
            ctx += f"  [{'█' * filled}{'░' * (10 - filled)}] {pct}% before auto-compact"
        self.console.print(
            Text.assemble(
                ("provider ", "dim"), (provider, "bold"),
                ("   model ", "dim"), (model, "bold"),
                ("   mode ", "dim"), (mode, "bold"),
                ("   context ", "dim"), (ctx, "bold"),
            )
        )

    # -- agent turn output ---------------------------------------------
    def thinking(self):
        return _TickingStatus(self.console, "thinking", "(Esc to interrupt)", self._turn_start, ui=self)

    def working(self, label: str):
        return _TickingStatus(self.console, label.rstrip("… "), total_start=self._turn_start, ui=self)

    def tool_running(self):
        """Spinner shown while a tool call is actually executing, so a slow
        command (e.g. a long ``run_command``) never looks like it stalled."""
        return _TickingStatus(self.console, "running", "(Esc to interrupt)", self._turn_start, ui=self)

    def assistant_text(self, text: str) -> None:
        if not text.strip():
            return
        try:
            self.console.print(Markdown(text))
        except Exception:  # noqa: BLE001 - never let rendering crash a reply
            self.console.print(text)

    def stream_chunk(self, text: str) -> None:
        """Print one streamed text chunk as it arrives (#3.1/#7.1) — raw, not
        markdown-rendered (there's no way to safely re-parse markdown from a
        partial chunk).

        The first chunk stops any live thinking()/working() spinner first. The
        spinner is a Rich ``Live`` region refreshed from a background ticker
        thread; leaving it running while these partial-line prints stream in
        lets the two threads race, and the spinner's redraw shreds the reply
        into trailing fragments. Once real text is flowing it's also the
        liveness signal the spinner was standing in for, so dropping it is the
        right call, not just a workaround.
        """
        if not text:
            return
        if self._active_status is not None:
            self._active_status.stop()
        self.console.print(text, end="", markup=False, highlight=False)

    def stream_newline(self) -> None:
        """End a streamed response — chunks have no trailing newline of their own."""
        self.console.print()

    def tool_call(self, name: str, args: dict) -> None:
        # Subagent inner calls arrive as "agent-name:tool" — nest them visually.
        prefix = ""
        if ":" in name:
            head, _, sub = name.partition(":")
            if sub:
                prefix, name = head, sub
        verb, detail = _describe_tool(name, args, self.root)
        lead = "  " if prefix else ""
        parts = [(lead, ""), (f"{_TOOL_ICON} ", "cyan")]
        if prefix:
            parts.append((f"{prefix} ", "dim cyan"))
        parts.append((verb, "bold cyan"))
        if detail:
            parts.append((f"  {detail}", "dim"))
        self.console.print(Text.assemble(*parts))

    def tool_result(self, content: object, is_error: bool) -> None:
        text = str(content).strip()
        first = text.splitlines()[0] if text else ""
        if is_error:
            self.console.print(Text("    ✗ " + _short(first, 160), style="red"))
            return
        extra = text.count("\n")
        summary = _short(first, 160) or "(done)"
        if extra:
            summary += f"   +{extra} more line{'s' if extra != 1 else ''}"
        self.console.print(Text("    ↳ " + summary, style="green dim"))

    def turn_summary(self, elapsed: float, actions: int, in_tokens: int, out_tokens: int) -> None:
        bits = []
        if actions:
            bits.append(f"{actions} action{'s' if actions != 1 else ''}")
        tok = in_tokens + out_tokens
        if tok:
            bits.append(f"~{_human_count(tok)} tokens")
        bits.append(f"{elapsed:.1f}s")
        self.console.print(Text("  " + "  ·  ".join(bits), style="dim italic"))

    def todos(self, items: list[dict]) -> None:
        if not items:
            self.notice("No todos yet.")
            return
        styles = {"pending": "white", "in_progress": "bold yellow", "done": "green dim"}
        marks = {"pending": "○", "in_progress": "◐", "done": "●"}
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="center")
        table.add_column(overflow="fold")
        for t in items:
            status = t.get("status", "pending")
            cell = Text(t["task"], style=styles.get(status, "white"))
            if status == "done":
                cell.stylize("strike")
            table.add_row(marks.get(status, "○"), cell)
        self.console.print(Panel(table, title="todos", border_style="dim", padding=(0, 1)))

    def insights(self, data: dict, lifetime: dict | None = None) -> None:
        info = Table.grid(padding=(0, 2))
        info.add_column(justify="right", style="dim")
        info.add_column(style="bold")
        info.add_row("model", str(data.get("model", "?")))
        info.add_row("requests", f"{data.get('requests', 0):,}")
        info.add_row("input tokens", f"{data.get('input_tokens', 0):,}")
        info.add_row("output tokens", f"{data.get('output_tokens', 0):,}")
        info.add_row("total tokens", f"{data.get('total_tokens', 0):,}")
        info.add_row("context now", f"~{data.get('context_tokens', 0):,}")
        cost = data.get("cost")
        info.add_row("est. cost", f"${cost:.4f}" if cost is not None else "unknown model")
        self.console.print(Panel(info, title="insights (this chat)", border_style="dim", padding=(1, 1)))

        if lifetime and lifetime.get("sessions"):
            hist = Table.grid(padding=(0, 2))
            hist.add_column(justify="right", style="dim")
            hist.add_column(style="bold")
            hist.add_row("saved sessions", f"{lifetime['sessions']:,}")
            hist.add_row("total turns", f"{lifetime.get('turns', 0):,}")
            hist.add_row("total tokens", f"{lifetime.get('total_tokens', 0):,}")
            lcost = lifetime.get("cost")
            hist.add_row("est. cost (all-time)", f"${lcost:.4f}" if lcost is not None else "unknown model(s)")
            self.console.print(Panel(hist, title="insights (all saved sessions)", border_style="dim", padding=(1, 1)))

    def cost(self, data: dict) -> None:
        """One-line `/cost` alias for the verbose `/insights` panel."""
        model = data.get("model", "?")
        total = data.get("total_tokens", 0)
        cost = data.get("cost")
        cost_str = f"${cost:.4f}" if cost is not None else "unknown model"
        self.notice(f"{model} · {total:,} tokens · {cost_str}", style="bold")

    def sessions(self, rows: list[dict], current_id: str | None = None) -> None:
        if not rows:
            self.notice("No saved sessions yet for this project.")
            return
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", style="dim")
        table.add_column(style="bold cyan")
        table.add_column(style="dim")
        table.add_column(overflow="fold")
        table.add_column(justify="right", style="dim")
        for i, r in enumerate(rows, 1):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["started_at"])) if r["started_at"] else "?"
            mark = "●" if r["id"] == current_id else " "
            turns = r["turns"]
            table.add_row(
                f"{mark}{i}.", r["id"], when,
                r["title"] or "(no messages yet)",
                f"{turns} turn{'s' if turns != 1 else ''}",
            )
        self.console.print(Panel(table, title="sessions", border_style="dim", padding=(1, 1)))
        self.console.print("[dim]resume with  /resume <n or id>[/dim]")

    def session_search_results(self, rows: list[dict], query: str) -> None:
        """`/sessions <query>` (#8.1) — full-text hits, each with a snippet of
        the matching line instead of the /sessions listing's turn count."""
        if not rows:
            self.notice(f'No saved sessions mention "{query}".')
            return
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", style="dim")
        table.add_column(style="bold cyan")
        table.add_column(style="dim")
        table.add_column(overflow="fold")
        for i, r in enumerate(rows, 1):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["started_at"])) if r["started_at"] else "?"
            table.add_row(f"{i}.", r["id"], when, r.get("snippet", ""))
        self.console.print(Panel(table, title=f'sessions mentioning "{query}"', border_style="dim", padding=(1, 1)))
        self.console.print("[dim]resume with  /resume <n or id>[/dim]")

    def agents(self, items: dict) -> None:
        if not items:
            self.notice("No subagents defined. Add .kbcode/agents/<name>.md to create one.")
            return
        for name, sub in items.items():
            self.console.print(
                Text.assemble(("  ⤷ ", "cyan"), (name, "bold cyan"), (f" — {sub.description}", "dim"))
            )

    # -- misc -----------------------------------------------------------
    def notice(self, msg: str, style: str = "dim") -> None:
        self.console.print(f"[{style}]{msg}[/{style}]")

    def error(self, msg: str) -> None:
        self.console.print(f"[red]Error:[/red] {msg}")

    def print(self, *args, **kwargs) -> None:
        self.console.print(*args, **kwargs)
