"""Terminal look-and-feel — a Claude Code / Hermes style chat surface.

This is the presentation layer. The agent loop talks to a :class:`TerminalUI`
instead of printing directly, so the loop stays about *logic* and this file owns
the *look*: a header banner, markdown-rendered answers, tidy tool-call lines, a
status footer, and a help table.

Everything degrades gracefully — if a value can't be rendered richly we fall
back to plain text, so it stays robust on basic Windows consoles.
"""

from __future__ import annotations

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
    ("/open <folder>", "switch to working on another project folder"),
    ("/kb", "list knowledge-base notes"),
    ("/memory", "show recent long-term memory"),
    ("/skills", "list learned skills"),
    ("/todo", "show the agent's current task checklist"),
    ("/agents", "list available subagents (.kbcode/agents/)"),
    ("/image [path]", "attach an image (clipboard, or a file) for your next message — also Alt+V"),
    ("/learn [topic]", "save what we just did as a reusable skill"),
    ("/insights", "show tokens used and estimated cost (this chat + all saved sessions)"),
    ("/kb-check [--fix]", "check (or auto-fix) kb/ path:line pointers"),
    ("/compact", "summarize earlier chat to free up context"),
    ("/rollback", "undo AI edits — pick a checkpoint from a menu (auto-saved before every edit)"),
    ("/sessions", "list past chat sessions for this project"),
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


def _describe_tool(name: str, args: dict, root: Path | None = None) -> tuple[str, str]:
    """Turn a raw tool call into a human verb + target, like a real CLI shows."""
    a = args or {}

    def g(key: str) -> str:
        return str(a.get(key, "")).strip()

    def full(path: str) -> str:
        """Resolve a path to its full location so the user sees *where* a file
        lands (the model usually passes a bare relative name). Reads/search keep
        the short form; only writes/edits use this."""
        if not path or root is None:
            return path
        try:
            p = Path(path)
            return str((p if p.is_absolute() else root / p).resolve())
        except (OSError, ValueError):
            return path

    if name == "read_file":
        return "Read", g("path")
    if name == "write_file":
        return "Write", f"{full(g('path'))}  ({len(str(a.get('content', ''))):,} chars)"
    if name == "edit_file":
        return "Edit", full(g("path"))
    if name == "list_dir":
        return "List", g("path") or "."
    if name == "search_code":
        where = f"  in {g('path')}" if g("path") else ""
        return "Search", f'"{g("pattern")}"{where}'
    if name == "run_command":
        return "Run", "$ " + g("command")
    if name == "kb_read":
        return "KB read", ""
    if name == "kb_write":
        return "KB write", g("name")
    if name == "remember":
        return "Remember", g("key") or _short(g("content"), 60)
    if name == "recall":
        return "Recall", f'"{g("query")}"'
    if name == "save_skill":
        return "Save skill", g("name")
    if name == "manage_todos":
        n = len(a.get("todos") or [])
        return "Plan", f"{n} item{'s' if n != 1 else ''}"
    if name == "run_subagent":
        return "Delegate", f"→ {g('agent')}: {_short(g('task'), 60)}"
    return name, (_short(a) if a else "")


class TerminalUI:
    """All terminal output flows through here so the style stays consistent."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        # Project root, so file tool-lines can show *where* a file actually is.
        # Set by the CLI when an agent is built / a project is opened.
        self.root: Path | None = None

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
        body.add_row(Text("your local AI coding agent", style="dim italic"))
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

    def prompt(self, mode: str = "code") -> str:
        tag = "" if mode == "code" else f"[cyan]({mode})[/cyan] "
        return f"\n{tag}[bold green]you {_ARROW}[/bold green] "

    def prompt_html(self, mode: str = "code") -> str:
        tag = "" if mode == "code" else f"<ansicyan>({mode})</ansicyan> "
        return f"\n{tag}<ansigreen><b>you ›</b></ansigreen> "

    def help(self) -> None:
        desc = dict(COMMANDS)
        groups = [
            ("session", ["/help", "/version", "/status", "/open <folder>", "/insights", "/compact", "/rollback", "/sessions", "/resume [id]", "/reset", "/exit"]),
            ("knowledge & memory", ["/kb", "/kb-check [--fix]", "/memory", "/skills", "/learn [topic]"]),
            ("planning & agents", ["/todo", "/agents", "/image [path]"]),
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
        return self.console.status(
            "[dim]thinking…[/dim]  [dim italic](Esc to interrupt)[/dim italic]", spinner="dots"
        )

    def working(self, label: str):
        return self.console.status(f"[dim]{label}[/dim]", spinner="dots")

    def assistant_text(self, text: str) -> None:
        if not text.strip():
            return
        try:
            self.console.print(Markdown(text))
        except Exception:  # noqa: BLE001 - never let rendering crash a reply
            self.console.print(text)

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
