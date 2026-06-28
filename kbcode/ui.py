"""Terminal look-and-feel — a Claude Code / Hermes style chat surface.

This is the presentation layer. The agent loop talks to a :class:`TerminalUI`
instead of printing directly, so the loop stays about *logic* and this file owns
the *look*: a header banner, markdown-rendered answers, tidy tool-call lines, a
status footer, and a help table.

Everything degrades gracefully — if a value can't be rendered richly we fall
back to plain text, so it stays robust on basic Windows consoles.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_TOOL_ICON = "⏺"
_ARROW = "›"

_COMMANDS = [
    ("/help", "show this help"),
    ("/provider [name] [model]", "switch provider (no name = list them)"),
    ("/model [id]", "switch model (no id = list this provider's models)"),
    ("/status", "show provider, model and context size"),
    ("/kb", "list knowledge-base notes"),
    ("/kb-check", "check kb/ path:line pointers still resolve"),
    ("/memory", "show recent long-term memory"),
    ("/skills", "list learned skills"),
    ("/compact", "summarize earlier chat to free up context"),
    ("/reset", "forget this chat (memory + kb are kept)"),
    ("/exit", "quit"),
]


def _short(value: object, limit: int = 100) -> str:
    text = " ".join(str(value).split())  # collapse whitespace/newlines to one line
    return text if len(text) <= limit else text[:limit] + "…"


class TerminalUI:
    """All terminal output flows through here so the style stays consistent."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    # -- chrome ---------------------------------------------------------
    def banner(self, provider: str, model: str, cwd: Path) -> None:
        info = Table.grid(padding=(0, 2))
        info.add_column(justify="right", style="dim")
        info.add_column(style="bold")
        info.add_row("provider", provider)
        info.add_row("model", model)
        info.add_row("folder", str(cwd))

        body = Table.grid(padding=(0, 0))
        body.add_row(Text("your local AI coding agent", style="dim italic"))
        body.add_row("")
        body.add_row(info)
        body.add_row("")
        body.add_row(Text("/help for commands  ·  /exit to quit", style="dim"))

        self.console.print(
            Panel(body, title="[bold cyan]kbcode[/bold cyan]", border_style="cyan", padding=(1, 2))
        )

    def prompt(self) -> str:
        return f"\n[bold green]you {_ARROW}[/bold green] "

    def help(self) -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold cyan", overflow="fold")
        table.add_column(style="white", overflow="fold")
        for cmd, desc in _COMMANDS:
            table.add_row(cmd, desc)
        self.console.print(Panel(table, title="commands", border_style="dim", padding=(1, 1)))
        self.console.print("[dim]Anything else is sent to the agent as a request.[/dim]")

    def status_line(self, provider: str, model: str, tokens: int) -> None:
        self.console.print(
            Text.assemble(
                ("provider ", "dim"), (provider, "bold"),
                ("   model ", "dim"), (model, "bold"),
                ("   context ", "dim"), (f"~{tokens:,} tokens", "bold"),
            )
        )

    # -- agent turn output ---------------------------------------------
    def thinking(self):
        return self.console.status("[dim]thinking…[/dim]", spinner="dots")

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
        rendered = _short(args) if args else ""
        self.console.print(
            Text.assemble((f"{_TOOL_ICON} ", "cyan"), (name, "bold cyan"), (f"  {rendered}", "dim"))
        )

    def tool_result(self, content: object, is_error: bool) -> None:
        style = "red" if is_error else "green dim"
        marker = "  ✗ " if is_error else "  ↳ "
        self.console.print(Text(marker + _short(content, 160), style=style))

    # -- misc -----------------------------------------------------------
    def notice(self, msg: str, style: str = "dim") -> None:
        self.console.print(f"[{style}]{msg}[/{style}]")

    def error(self, msg: str) -> None:
        self.console.print(f"[red]Error:[/red] {msg}")

    def print(self, *args, **kwargs) -> None:
        self.console.print(*args, **kwargs)
