"""Press **Esc** to interrupt a running turn (Claude Code style).

While a turn runs, a background daemon thread watches the keyboard; pressing
Esc raises ``KeyboardInterrupt`` in the main thread — which the CLI already
catches to drop back to the prompt. Ctrl-C keeps working too.

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
def interrupt_on_escape(enabled: bool = True):
    """Context manager: while active, Esc interrupts the main thread."""
    if not enabled or not sys.stdin.isatty():
        yield
        return
    watcher = _make_watcher()
    if watcher is None:  # unsupported terminal/platform
        yield
        return
    stop = threading.Event()
    thread = threading.Thread(target=watcher, args=(stop,), daemon=True)
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
    """Return ``watch(stop_event)`` for this platform, or None if unsupported."""
    try:  # Windows
        import msvcrt
    except ImportError:
        msvcrt = None
    if msvcrt is not None:
        def watch_windows(stop: threading.Event) -> None:
            while not stop.is_set():
                if _paused.is_set():  # a prompt owns the keyboard right now
                    stop.wait(0.05)
                    continue
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch == "\x1b" and not stop.is_set():  # Esc
                        _thread.interrupt_main()
                        return
                else:
                    stop.wait(0.05)
        return watch_windows

    try:  # POSIX
        import select
        import termios
        import tty
    except ImportError:
        return None

    def watch_posix(stop: threading.Event) -> None:
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
                    continue
                # A lone Esc interrupts; \x1b followed by more bytes is an arrow
                # / function key escape sequence — drain it and ignore.
                more, _, _ = select.select([sys.stdin], [], [], 0.0)
                if more:
                    sys.stdin.read(1)
                    continue
                if not stop.is_set():
                    _thread.interrupt_main()
                    return
        finally:
            with contextlib.suppress(Exception):
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return watch_posix
