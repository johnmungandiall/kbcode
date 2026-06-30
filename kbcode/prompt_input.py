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


def select(options: list[str], header: str | None = None) -> tuple[bool, int | None]:
    """An arrow-key selectable menu (Claude Code style), built on prompt_toolkit.

    Returns ``(available, index)``:
      - ``(False, None)`` → can't show a menu here (no TTY / lib missing); the
        caller should fall back to a typed prompt.
      - ``(True, i)``     → the user chose option ``i``.
      - ``(True, None)``  → the user cancelled (Esc / Ctrl-C).

    Move with ↑/↓ (or j/k), pick with Enter, or press the option's number.
    The menu renders inline and erases itself on exit, leaving only the result.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty() or not options:
        return False, None
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.styles import Style
    except Exception:  # noqa: BLE001 - prompt_toolkit missing or broken
        return False, None

    state = {"i": 0}
    n = len(options)

    def fragments():
        out: list[tuple[str, str]] = []
        if header:
            out.append(("class:hdr", header + "\n"))
        for i, label in enumerate(options):
            if i == state["i"]:
                out.append(("class:sel", f" ❯ {i + 1}. {label}\n"))
            else:
                out.append(("class:opt", f"   {i + 1}. {label}\n"))
        return out

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    @kb.add("c-p")
    def _up(_e):
        state["i"] = (state["i"] - 1) % n

    @kb.add("down")
    @kb.add("j")
    @kb.add("c-n")
    def _down(_e):
        state["i"] = (state["i"] + 1) % n

    @kb.add("enter")
    def _pick(e):
        e.app.exit(result=state["i"])

    @kb.add("c-c")
    @kb.add("escape")
    def _cancel(e):
        e.app.exit(result=None)

    for num in range(1, min(n, 9) + 1):
        @kb.add(str(num))
        def _num(e, num=num):
            e.app.exit(result=num - 1)

    style = Style.from_dict({"sel": "bold cyan", "opt": "", "hdr": "#888888"})
    try:
        app = Application(
            layout=Layout(HSplit([Window(FormattedTextControl(fragments), always_hide_cursor=True)])),
            key_bindings=kb,
            style=style,
            full_screen=False,
            mouse_support=False,
        )
        return True, app.run()
    except Exception:  # noqa: BLE001 - any terminal/console issue → let caller fall back
        return False, None


def make_input(commands: list[tuple[str, str]], arg_options: dict[str, list[str]] | None = None):
    """Return an input object with ``.read(prompt_html)`` and ``.pop_images()``, or None.

    Besides slash-command autocomplete, this binds **Alt+V** to attach an image
    from the clipboard to the next message (for vision-capable models). Attached
    images wait in a buffer shown in the bottom toolbar; ``pop_images()`` returns
    and clears them — the caller sends them with the user's next turn.
    """
    if not sys.stdin.isatty():
        return None  # piped / non-interactive: let the caller use plain input
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.application import run_in_terminal
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.key_binding import KeyBindings
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

    images: list[dict] = []  # pending attachments, drained by pop_images()
    kb = KeyBindings()

    @kb.add("escape", "v")  # Alt+V (terminals send Esc then 'v')
    def _attach_image(event):
        from .images import grab_clipboard_image

        img = grab_clipboard_image()
        if img:
            images.append(img)
            event.app.invalidate()  # refresh the bottom toolbar count
        else:
            run_in_terminal(
                lambda: print(
                    "  (no image on the clipboard — copy an image first; "
                    "clipboard paste needs Pillow: pip install Pillow)"
                )
            )

    def _toolbar():
        if images:
            return HTML(f" 📎 {len(images)} image(s) attached — sent with your next message")
        return HTML(" tip: <b>Alt+V</b> attaches an image from your clipboard")

    session = PromptSession(
        completer=_SlashCompleter(),
        complete_while_typing=True,
        key_bindings=kb,
        bottom_toolbar=_toolbar,
    )

    class _Input:
        def read(self, prompt_html: str) -> str:
            raw = session.prompt(HTML(prompt_html))
            # Strip any stray BOM/control chars some shells inject.
            return "".join(c for c in raw if c.isprintable()).strip()

        def pop_images(self) -> list[dict]:
            out = list(images)
            images.clear()
            return out

    return _Input()
