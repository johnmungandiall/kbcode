"""Interactive input line with slash-command autocomplete (Claude Code style).

When you type ``/`` a live popup menu of commands appears; arrow keys + Tab/Enter
pick one. After ``/provider`` it suggests provider names too.

This uses `prompt_toolkit`. If it isn't installed, or stdin isn't an interactive
terminal (e.g. piped input), :func:`make_input` returns ``None`` and the caller
falls back to the plain reader — so kbcode never breaks because of this.
"""

from __future__ import annotations

import sys


def suggest(
    text: str,
    commands: list[tuple[str, str]],
    arg_options: dict[str, list[str]] | None = None,
) -> list[tuple[str, str, str]]:
    """Pure matching logic (no prompt_toolkit) — easy to test.

    Returns a list of ``(insert, display, meta)`` for the current input ``text``.
    Empty list means "no popup" (e.g. the user is typing a normal request).
    ``arg_options`` maps a command (e.g. ``/provider``) to the values to suggest
    for its first argument.
    """
    arg_options = arg_options or {}
    if not text.startswith("/"):
        return []

    # Still typing the command word (no space yet) → command names + descriptions.
    if " " not in text:
        out: list[tuple[str, str, str]] = []
        for cmd, desc in commands:
            name = cmd.split(" ", 1)[0]
            if name.startswith(text):
                out.append((name, cmd, desc))
        return out

    # Past the command word → argument completion for commands that have options.
    head, _, _ = text.partition(" ")
    word = text.split(" ")[-1]
    options = arg_options.get(head, [])
    return [(name, name, "") for name in options if name.startswith(word)]


def make_input(commands: list[tuple[str, str]], arg_options: dict[str, list[str]] | None = None):
    """Return an input object with a ``.read(prompt_html)`` method, or None."""
    if not sys.stdin.isatty():
        return None  # piped / non-interactive: let the caller use plain input
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.formatted_text import HTML
    except Exception:  # noqa: BLE001 - prompt_toolkit missing or broken
        return None

    class _SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            # Replace whatever the user has typed of the current word.
            word = text if " " not in text else text.split(" ")[-1]
            for insert, display, meta in suggest(text, commands, arg_options):
                yield Completion(
                    insert,
                    start_position=-len(word),
                    display=display,
                    display_meta=meta,
                )

    session = PromptSession(completer=_SlashCompleter(), complete_while_typing=True)

    class _Input:
        def read(self, prompt_html: str) -> str:
            raw = session.prompt(HTML(prompt_html))
            # Strip any stray BOM/control chars some shells inject.
            return "".join(c for c in raw if c.isprintable()).strip()

    return _Input()
