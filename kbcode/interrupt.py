"""Keyboard control while a turn runs (Claude Code style).

While a turn runs, a background daemon thread watches the keyboard:

- **Esc** interrupts the turn — it raises ``KeyboardInterrupt`` in the main
  thread, which the CLI already catches to drop back to the prompt. Ctrl-C
  keeps working too.
- **Any other typing** goes into a :class:`TypeAhead` buffer (when the caller
  provides one): the user can keep writing their next message while the agent
  works; **Enter** queues the line and the REPL runs it after this turn —
  exactly like typing while Claude Code is busy.
- **Shift+Tab** fires an optional callback (the REPL uses it to flip the
  ask/auto permission mode mid-turn — see permissions.py).

Everything is TTY-only and fully guarded: with piped input, no console, or an
unsupported platform, :func:`interrupt_on_escape` is a no-op and the turn runs
normally — so kbcode never breaks because of this.

Esc works mid-request too: ``Agent._complete`` runs the blocking provider call
on a daemon worker and waits for it in short Python-level polls, so a pending
``KeyboardInterrupt`` is delivered within ~50 ms instead of waiting for the
socket read to return.
"""

from __future__ import annotations

import _thread
import contextlib
import sys
import threading

# While set, the watcher stops reading the keyboard entirely. An interactive
# prompt shown MID-TURN (the permission menu / typed y-N-a fallback) otherwise
# races the watcher for every keystroke — msvcrt.getwch()/stdin.read() on the
# watcher thread eats arrows, Enter, or the y/n itself, so the menu randomly
# doesn't respond and the whole agent looks stuck on a write.
_paused = threading.Event()


class TypeAhead:
    """Collects what the user types while a turn runs.

    The watcher thread feeds keystrokes in; the live spinner polls
    :meth:`snapshot` (every ~100ms redraw) to echo the buffer, and the REPL
    drains completed lines with :meth:`pop_lines` after the turn — they run
    as the next message(s). Thread-safe: watcher writes, main thread reads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffer: list[str] = []
        self._lines: list[str] = []

    def feed(self, ch: str) -> None:
        """One keystroke from the watcher: Enter queues the buffer as a line,
        backspace edits, anything printable is appended, the rest is ignored."""
        with self._lock:
            if ch in ("\r", "\n"):
                line = "".join(self._buffer).strip()
                self._buffer.clear()
                if line:
                    self._lines.append(line)
            elif ch in ("\x08", "\x7f"):  # backspace (Windows / POSIX)
                if self._buffer:
                    self._buffer.pop()
            elif ch.isprintable():
                self._buffer.append(ch)

    def snapshot(self) -> tuple[str, int]:
        """(current partial buffer, queued line count) — for the live echo."""
        with self._lock:
            return "".join(self._buffer), len(self._lines)

    def pop_lines(self) -> list[str]:
        """Drain the queued (Enter-committed) lines."""
        with self._lock:
            out = self._lines[:]
            self._lines.clear()
            return out

    def take_all_text(self) -> str:
        """Drain EVERYTHING (queued lines + partial buffer) as one text blob —
        used after an interrupt so nothing typed runs unasked; the REPL puts
        it back into the next prompt for editing instead."""
        with self._lock:
            parts = self._lines[:]
            tail = "".join(self._buffer).strip()
            self._lines.clear()
            self._buffer.clear()
            if tail:
                parts.append(tail)
            return "\n".join(parts)


@contextlib.contextmanager
def pause_escape_watcher():
    """While active, the Esc watcher leaves the keyboard alone so an
    interactive prompt receives every key. No-op when no watcher is running."""
    _paused.set()
    try:
        yield
    finally:
        _paused.clear()


@contextlib.contextmanager
def interrupt_on_escape(enabled: bool = True, typeahead: TypeAhead | None = None, on_shift_tab=None):
    """Context manager: while active, Esc interrupts the main thread.

    ``typeahead`` (optional) receives every other keystroke so the user can
    compose their next message while the turn runs; ``on_shift_tab``
    (optional, no-arg callable) fires when Shift+Tab is pressed mid-turn.
    """
    if not enabled or not sys.stdin.isatty():
        yield
        return
    watcher = _make_watcher()
    if watcher is None:  # unsupported terminal/platform
        yield
        return
    stop = threading.Event()
    thread = threading.Thread(target=watcher, args=(stop, typeahead, on_shift_tab), daemon=True)
    thread.start()
    try:
        yield
    finally:
        # Join, don't just signal: the watcher reads the console (Windows
        # msvcrt.getwch) / holds the tty in cbreak mode (POSIX). If we returned
        # while it's still alive, it would race the *next* prompt for stdin —
        # stealing the first keystrokes so the user "can't type" after a reply,
        # or leaving the terminal in cbreak. Its loop wakes every ~50ms, so a
        # short join reliably lets it exit and release the terminal first.
        stop.set()
        thread.join(timeout=0.5)


def _make_watcher():
    """Return ``watch(stop_event, typeahead, on_shift_tab)`` for this
    platform, or None if unsupported."""
    try:  # Windows
        import msvcrt
    except ImportError:
        msvcrt = None
    if msvcrt is not None:
        def watch_windows(stop: threading.Event, typeahead: TypeAhead | None, on_shift_tab) -> None:
            while not stop.is_set():
                if _paused.is_set():  # a prompt owns the keyboard right now
                    stop.wait(0.05)
                    continue
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch == "\x1b" and not stop.is_set():  # Esc
                        _thread.interrupt_main()
                        return
                    if ch in ("\x00", "\xe0"):  # extended key: arrows, F-keys, Shift+Tab
                        code = msvcrt.getwch() if msvcrt.kbhit() else ""
                        if code == "\x0f" and on_shift_tab is not None:  # Shift+Tab
                            with contextlib.suppress(Exception):
                                on_shift_tab()
                        continue
                    if typeahead is not None:
                        typeahead.feed(ch)
                else:
                    stop.wait(0.05)
        return watch_windows

    try:  # POSIX
        import select
        import termios
        import tty
    except ImportError:
        return None

    def watch_posix(stop: threading.Event, typeahead: TypeAhead | None, on_shift_tab) -> None:
        fd = sys.stdin.fileno()
        try:
            old = termios.tcgetattr(fd)
        except (termios.error, ValueError):
            return
        try:
            tty.setcbreak(fd)
            while not stop.is_set():
                if _paused.is_set():  # a prompt owns the keyboard right now
                    stop.wait(0.05)
                    continue
                ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                if not ready:
                    continue
                ch = sys.stdin.read(1)
                if ch != "\x1b":
                    if typeahead is not None:
                        typeahead.feed(ch)
                    continue
                # A lone Esc interrupts; \x1b followed by more bytes is an
                # escape sequence — drain it fully. "[Z" is Shift+Tab; other
                # sequences (arrows, F-keys) are ignored.
                seq = ""
                while True:
                    more, _, _ = select.select([sys.stdin], [], [], 0.0)
                    if not more:
                        break
                    seq += sys.stdin.read(1)
                if not seq:
                    if not stop.is_set():
                        _thread.interrupt_main()
                        return
                elif seq == "[Z" and on_shift_tab is not None:
                    with contextlib.suppress(Exception):
                        on_shift_tab()
        finally:
            with contextlib.suppress(Exception):
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return watch_posix
