"""Covers IMPROVEMENTS.md #7.5 (context usage bar in the prompt) plus a few
other pure-ish helpers in ui.py that are easy to test directly.
"""

from __future__ import annotations

import io
import threading

from rich.console import Console

from kbcode.ui import TerminalUI, _context_bar, _describe_tool, _human_count


def _silent_ui() -> TerminalUI:
    """A UI whose console writes nowhere real, so spinner/stream tests don't
    spew control codes into pytest output."""
    return TerminalUI(Console(file=io.StringIO(), force_terminal=False))


def test_human_count_formats_small_numbers_plain():
    assert _human_count(0) == "0"
    assert _human_count(999) == "999"


def test_human_count_formats_thousands():
    assert _human_count(1500) == "1.5k"
    assert _human_count(1000) == "1k"


def test_human_count_formats_millions():
    assert _human_count(2_500_000) == "2.5M"


def test_context_bar_empty_when_no_limit():
    assert _context_bar(500, 0) == ""


def test_context_bar_shows_percentage_and_fills_proportionally():
    bar = _context_bar(50, 100, segments=5)
    assert "50%" in bar
    assert bar.count("▓") == 3 or bar.count("▓") == 2  # round(2.5) can go either way
    assert bar.count("▓") + bar.count("░") == 5


def test_context_bar_caps_at_100_percent():
    bar = _context_bar(999, 100, segments=5)
    assert "100%" in bar
    assert bar.count("▓") == 5


def test_context_bar_empty_usage_is_all_unfilled():
    bar = _context_bar(0, 100, segments=5)
    assert "0%" in bar
    assert bar.count("▓") == 0


def test_prompt_includes_context_bar_when_limit_given():
    ui = TerminalUI()
    text = ui.prompt("code", tokens=50, limit=100)
    assert "50%" in text
    assert "you" in text


def test_prompt_omits_context_bar_when_limit_is_zero():
    ui = TerminalUI()
    text = ui.prompt("code", tokens=50, limit=0)
    assert "%" not in text


def test_prompt_html_includes_context_bar_when_limit_given():
    ui = TerminalUI()
    text = ui.prompt_html("code", tokens=80, limit=100)
    assert "80%" in text


def test_describe_tool_kb_search():
    verb, target = _describe_tool("kb_search", {"query": "widget"})
    assert verb == "KB search"
    assert "widget" in target


def test_describe_tool_write_file_shows_char_count():
    verb, target = _describe_tool("write_file", {"path": "a.py", "content": "hello"})
    assert verb == "Write"
    assert "5 chars" in target


def test_describe_tool_run_command_shows_dollar_prefix():
    verb, target = _describe_tool("run_command", {"command": "pytest -q"})
    assert verb == "Run"
    assert target == "$ pytest -q"


def test_describe_tool_manage_todos_pluralizes():
    verb, target = _describe_tool("manage_todos", {"todos": [{"task": "a", "status": "pending"}]})
    assert verb == "Plan"
    assert target == "1 item"
    verb, target = _describe_tool("manage_todos", {"todos": []})
    assert target == "0 items"


def test_describe_tool_unknown_falls_back_to_name_and_short_args():
    verb, target = _describe_tool("some_future_tool", {"x": 1})
    assert verb == "some_future_tool"
    assert "x" in target


# -- streaming vs. the thinking spinner --------------------------------------
# The spinner is a Rich Live region refreshed from a background ticker thread.
# If it's still live while raw text streams in, the two racing writers shred the
# reply into trailing fragments. stream_chunk() must stop the spinner on the
# first real token so only one thread writes the terminal from then on.

def test_stream_chunk_stops_active_spinner_on_first_token():
    ui = _silent_ui()
    with ui.thinking() as status:
        assert ui._active_status is status
        ui.stream_chunk("hello")
        assert ui._active_status is None
        assert status._stopped is True


def test_ticking_status_stop_is_idempotent():
    ui = _silent_ui()
    status = ui.thinking()
    with status:
        status.stop()
        status.stop()  # a second stop (e.g. via __exit__) must not blow up
    assert status._stopped is True


def test_stream_chunk_is_a_noop_without_an_active_spinner():
    ui = _silent_ui()
    ui.stream_chunk("")          # empty chunk: nothing to do, no active status
    ui.stream_chunk("plain")     # real text, no spinner running: must not crash
    assert ui._active_status is None


def test_stream_chunk_from_worker_thread_stops_spinner():
    # The provider streams on_text from a worker thread while the main thread
    # waits — mirror that: stop the spinner from a *different* thread than the
    # one that started it, and make sure it tears down without deadlocking.
    ui = _silent_ui()
    with ui.thinking():
        done = threading.Event()

        def stream():
            ui.stream_chunk("from-worker")
            done.set()

        threading.Thread(target=stream, daemon=True).start()
        assert done.wait(2.0), "streaming worker deadlocked stopping the spinner"
        assert ui._active_status is None
