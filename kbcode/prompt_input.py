"""Interactive input line with slash-command autocomplete (Claude Code style).

When you type ``/`` a live popup menu of commands appears; arrow keys + Tab/Enter
pick one. After ``/provider`` it suggests provider names, then that provider's
model ids for the second argument (fetched live, in the background).

This uses `prompt_toolkit`. If it isn't installed, or stdin isn't an interactive
terminal (e.g. piped input), :func:`make_input` returns ``None`` and the caller
falls back to the plain reader — so kbcode never breaks because of this.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Slash commands whose first argument is a filesystem path — these get live
# file/folder completion (Tab through directories) on top of the command menu.
PATH_COMMANDS = frozenset({"/open", "/cd", "/image", "/img", "/video"})


def _path_completions(word: str, limit: int = 40) -> list[tuple[str, str, str]]:
    """Filesystem completions for a partially-typed path (the current word).

    Returns ``(insert, display, meta)`` triples: ``insert``/``display`` is the
    path to put back (directories get a trailing separator so you can keep
    drilling in), ``meta`` marks ``'dir'``/``'file'``. Hidden entries surface
    only once the user types the leading dot. Never raises — an unreadable or
    missing directory just yields nothing.
    """
    head, tail = os.path.split(word)
    scan = os.path.expanduser(head) if head else "."
    try:
        names = sorted(os.listdir(scan))
    except OSError:
        return []
    out: list[tuple[str, str, str]] = []
    for name in names:
        if name.startswith(".") and not tail.startswith("."):
            continue
        if not name.startswith(tail):
            continue
        full = os.path.join(head, name) if head else name
        is_dir = os.path.isdir(os.path.join(scan, name))
        if is_dir:
            full += os.sep
        out.append((full, full, "dir" if is_dir else "file"))
        if len(out) >= limit:
            break
    return out


def suggest(
    text: str,
    commands: list[tuple[str, str]],
    arg_options: dict | None = None,
    path_commands: frozenset[str] | set[str] | None = None,
) -> list[tuple[str, str, str]]:
    """Pure matching logic (no prompt_toolkit) — easy to test.

    Returns a list of ``(insert, display, meta)`` for the current input ``text``.
    Empty list means "no popup" (e.g. the user is typing a normal request).
    ``arg_options`` maps a command (e.g. ``/provider``) to the values to suggest:
    a plain list applies to the first argument only, while a callable receives
    all words after the command (last one partial) and returns the candidates
    for that last word — so suggestions can depend on the earlier arguments
    (e.g. ``/provider deepseek <model>``). ``path_commands`` (defaults to
    :data:`PATH_COMMANDS`) names commands whose first argument gets filesystem
    path completion.
    """
    arg_options = arg_options or {}
    if path_commands is None:
        path_commands = PATH_COMMANDS
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
    parts = text.split(" ")
    word = parts[-1]
    options = arg_options.get(head)
    if callable(options):
        try:
            candidates = options(parts[1:])
        except Exception:  # noqa: BLE001 - a completion source must never break typing
            candidates = []
    elif len(parts) == 2:  # a static list completes the first argument only
        candidates = options or []
    else:
        candidates = []
    out = []
    for c in candidates:
        if isinstance(c, tuple):
            name, meta = c
        else:
            name, meta = c, ""
        if name.startswith(word):
            out.append((name, name, meta))
    # File-path completion, but only while typing the *first* argument (parts ==
    # [command, partial-path]) — later words (e.g. /video's question) aren't paths.
    if head in path_commands and len(parts) == 2:
        out += _path_completions(word)
    return out


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


def make_input(
    commands: list[tuple[str, str]],
    arg_options: dict[str, list[str]] | None = None,
    history_file: Path | None = None,
    on_shift_tab=None,
    status_note=None,
):
    """Return an input object with ``.read(prompt_html)`` and ``.pop_images()``, or None.

    Besides slash-command autocomplete, this binds **Alt+V** to attach an image
    from the clipboard to the next message (for vision-capable models). Attached
    images wait in a buffer shown in the bottom toolbar; ``pop_images()`` returns
    and clears them — the caller sends them with the user's next turn.

    ``on_shift_tab``, if given, is called (no args) when the user presses
    **Shift+Tab** at the prompt — the REPL uses it to cycle the ask/auto
    permission mode, Claude Code style. ``status_note``, if given, is a
    callable returning a short plain-text state line (e.g. the current
    permission mode) shown at the start of the bottom toolbar.

    ``history_file``, if given, persists input history there across sessions
    (up-arrow recalls prompts from earlier runs, not just this one).
    """
    if not sys.stdin.isatty():
        return None  # piped / non-interactive: let the caller use plain input
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.application import run_in_terminal
        from prompt_toolkit.completion import Completer, Completion, ThreadedCompleter
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:  # noqa: BLE001 - prompt_toolkit missing or broken
        return None

    history = None
    if history_file is not None:
        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history = FileHistory(str(history_file))
        except OSError:  # unwritable location — fall back to in-memory history
            history = None

    class _SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            # Replace whatever the user has typed of the current word.
            word = text if " " not in text else text.split(" ")[-1]
            for insert, display, meta in suggest(text, commands, arg_options, PATH_COMMANDS):
                yield Completion(
                    insert,
                    start_position=-len(word),
                    display=display,
                    display_meta=meta,
                )

    images: list[dict] = []  # pending attachments, drained by pop_images()
    kb = KeyBindings()

    def _attach_image(event):
        from .images import grab_clipboard_image

        img = grab_clipboard_image()
        if img:
            images.append(img)
            n = len(images)
            # Print a visible confirmation (not just the toolbar) so it's obvious
            # the hotkey fired — then refresh the toolbar count.
            run_in_terminal(
                lambda: print(f"  📎 image attached ({n}) — type your question and press Enter.")
            )
            event.app.invalidate()
        else:
            run_in_terminal(
                lambda: print(
                    "  (no image on the clipboard — copy an image first, "
                    "or use /image <path>. Clipboard paste needs Pillow: pip install Pillow)"
                )
            )

    # Alt+V (terminals deliver Alt as an Esc prefix). Bind a few variants so it
    # fires across Windows consoles / shift state; /image is the guaranteed path.
    kb.add("escape", "v")(_attach_image)
    kb.add("escape", "V")(_attach_image)

    if on_shift_tab is not None:
        @kb.add("s-tab")
        def _cycle_mode(event):
            try:
                on_shift_tab()
            except Exception:  # noqa: BLE001 - a mode toggle must never break typing
                return
            event.app.invalidate()  # redraw the toolbar with the new mode

    def _toolbar():
        note = ""
        if status_note is not None:
            try:
                text = status_note() or ""
            except Exception:  # noqa: BLE001 - a status source must never break typing
                text = ""
            if text:
                note = f" {text} · "
        if images:
            return HTML(f"{note} 📎 {len(images)} image(s) attached — sent with your next message")
        return HTML(f"{note} tip: <b>Alt+V</b> attaches an image · <b>Shift+Tab</b> toggles auto mode")

    session = PromptSession(
        # Threaded: callable arg_options may fetch model lists over the network
        # on first use — run them off the UI thread so typing never freezes.
        completer=ThreadedCompleter(_SlashCompleter()),
        complete_while_typing=True,
        key_bindings=kb,
        bottom_toolbar=_toolbar,
        history=history,
    )

    class _Input:
        def read(self, prompt_html: str, default: str = "") -> str:
            # ``default`` prefills the line (editable) — used to hand back text
            # the user typed mid-turn when the turn was interrupted.
            raw = session.prompt(HTML(prompt_html), default=default)
            # Strip any stray BOM/control chars some shells inject.
            return "".join(c for c in raw if c.isprintable()).strip()

        def pop_images(self) -> list[dict]:
            out = list(images)
            images.clear()
            return out

    return _Input()
