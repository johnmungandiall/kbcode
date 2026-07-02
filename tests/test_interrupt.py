"""interrupt_on_escape must fully stop its keyboard watcher before returning.

If it only signalled the watcher (without joining), the daemon thread would
still be reading the console when the *next* prompt starts — racing it for
stdin and eating the user's first keystrokes ("can't type after a reply").
"""

from __future__ import annotations

import threading

from kbcode import interrupt


class _FakeStdin:
    def isatty(self) -> bool:
        return True


def test_watcher_thread_is_joined_before_returning(monkeypatch):
    monkeypatch.setattr(interrupt.sys, "stdin", _FakeStdin())

    started = threading.Event()
    captured: dict[str, threading.Thread] = {}

    def fake_make_watcher():
        def watch(stop: threading.Event, typeahead=None, on_shift_tab=None) -> None:
            captured["thread"] = threading.current_thread()
            started.set()
            while not stop.is_set():  # mirror the real ~50ms poll loop
                stop.wait(0.02)
        return watch

    monkeypatch.setattr(interrupt, "_make_watcher", fake_make_watcher)

    with interrupt.interrupt_on_escape():
        assert started.wait(1.0), "watcher never started"

    # Back at the prompt now: the watcher must already be gone, not lingering
    # and competing for stdin.
    assert captured["thread"].is_alive() is False


def test_pause_escape_watcher_sets_and_clears_the_pause_flag():
    assert interrupt._paused.is_set() is False
    with interrupt.pause_escape_watcher():
        assert interrupt._paused.is_set() is True
    assert interrupt._paused.is_set() is False


def test_pause_escape_watcher_clears_the_flag_even_on_error():
    try:
        with interrupt.pause_escape_watcher():
            raise RuntimeError("prompt blew up")
    except RuntimeError:
        pass
    assert interrupt._paused.is_set() is False


def test_no_op_when_stdin_not_a_tty(monkeypatch):
    class _NotTTY:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(interrupt.sys, "stdin", _NotTTY())
    calls = {"made": False}

    def fake_make_watcher():
        calls["made"] = True
        return lambda stop: None

    monkeypatch.setattr(interrupt, "_make_watcher", fake_make_watcher)
    with interrupt.interrupt_on_escape():
        pass
    assert calls["made"] is False  # never even builds a watcher without a TTY
