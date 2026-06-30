"""Press **Esc** to interrupt a running turn (Claude Code style).

While a turn runs, a background daemon thread watches the keyboard; pressing
Esc raises ``KeyboardInterrupt`` in the main thread — which the CLI already
catches to drop back to the prompt. Ctrl-C keeps working too.

Everything is TTY-only and fully guarded: with piped input, no console, or an
unsupported platform, :func:`interrupt_on_escape` is a no-op and the turn runs
normally — so kbcode never breaks because of this.

Note: a synchronous provider call blocked deep in a socket read can only be
interrupted once it returns to Python, so Esc lands between steps / during tool
execution rather than mid-request. (Streaming makes it feel instant.)
"""

from __future__ import annotations

import _thread
import contextlib
import sys
import threading


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
        stop.set()


def _make_watcher():
    """Return ``watch(stop_event)`` for this platform, or None if unsupported."""
    try:  # Windows
        import msvcrt
    except ImportError:
        msvcrt = None
    if msvcrt is not None:
        def watch_windows(stop: threading.Event) -> None:
            while not stop.is_set():
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
