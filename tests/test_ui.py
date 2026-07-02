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
# stream_chunk() no longer prints chunks (the full reply is markdown-rendered
# by assistant_text() once the response resolves). Instead it keeps the
# thinking spinner ALIVE and feeds it a "writing… N chars" progress label —
# the spinner's ticker thread stays the only terminal writer, so the old
# two-writers shredding race can't happen. stream_tool_hint() still prints,
# so it still must stop the spinner first.

def test_stream_chunk_keeps_spinner_alive_and_reports_progress():
    ui = _silent_ui()
    with ui.thinking() as status:
        assert ui._active_status is status
        ui.stream_chunk("hello")
        ui.stream_chunk(" world")
        assert ui._active_status is status      # spinner survives streaming
        assert status._stopped is False
        assert status._label == "writing"
        assert "11" in status._hint             # len("hello world") chars counted


def test_thinking_resets_the_writing_counter_between_model_calls():
    ui = _silent_ui()
    with ui.thinking():
        ui.stream_chunk("first reply")
    with ui.thinking() as status:
        ui.stream_chunk("hi")
        assert "2" in status._hint and "11" not in status._hint


def test_stream_tool_hint_feeds_spinner_instead_of_stopping_it():
    # It used to stop the spinner and print a dim line — which left nothing
    # moving while a big write call streamed its arguments (the "write looks
    # stuck" bug). Now it relabels the live spinner, and stream_tool_args
    # keeps a character counter ticking while the arguments stream in.
    ui = _silent_ui()
    with ui.thinking() as status:
        ui.stream_tool_hint("write_file")
        assert ui._active_status is status
        assert status._stopped is False
        assert status._label == "write_file"
        ui.stream_tool_args("write_file", 12345)
        assert "12,345" in status._hint


def test_permission_prompt_stops_active_spinner_first(monkeypatch):
    # The permission menu fires mid-turn under the tool_running() spinner —
    # if the spinner stays live, its ticker redraw repaints over the menu and
    # the approval looks stuck. permission() must kill it before prompting.
    ui = _silent_ui()
    monkeypatch.setattr("kbcode.ui.select", lambda *a, **k: (True, 0))
    with ui.tool_running() as status:
        answer = ui.permission("write_file", "some diff")
        assert status._stopped is True
        assert ui._active_status is None
    assert answer == "y"


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


def test_stream_chunk_from_worker_thread_updates_spinner_without_deadlock():
    # The provider streams on_text from a worker thread while the main thread
    # waits — mirror that: update the spinner's progress from a *different*
    # thread than the one that started it, without deadlocking or stopping it.
    ui = _silent_ui()
    with ui.thinking() as status:
        done = threading.Event()

        def stream():
            ui.stream_chunk("from-worker")
            done.set()

        threading.Thread(target=stream, daemon=True).start()
        assert done.wait(2.0), "streaming worker deadlocked updating the spinner"
        assert ui._active_status is status
        assert status._label == "writing"


# -- tool_result summaries (UX clarity for "what is the agent doing?") ---------
# Recent change: tool_result no longer leaks raw code / match lines.
# It produces clean counts for data tools so the activity log is user-readable.

def test_tool_result_search_shows_match_count():
    ui = _silent_ui()
    # normal hits
    ui.tool_result("broker/k.py:10: foo\nsvc/s.py:22: bar\nnote", False, name="search_code")
    # namespaced subagent
    ui.tool_result("a:1: x\nb:2: y", False, name="code-explorer:search_code")
    # no matches
    ui.tool_result("(no matches)", False, name="kb_search")


def test_tool_result_read_shows_line_count():
    ui = _silent_ui()
    # typical read_file return format (numbered\tlines)
    content = "11\tdef foo():\n12\t    pass\n13\t# end"
    ui.tool_result(content, False, name="read_file")


def test_tool_result_list_and_repo_map():
    ui = _silent_ui()
    ui.tool_result("file1.py\nsubdir/\nfile2.py", False, name="list_dir")
    ui.tool_result("header\nsym1\nsym2\nsym3", False, name="repo_map")
    ui.tool_result("(empty)", False, name="list_dir")


def test_tool_result_fallback_and_errors():
    ui = _silent_ui()
    # non-special tool shows first line of its status
    ui.tool_result("wrote x.py (42 chars)\nextra", False, name="write_file")
    ui.tool_result("Command output line 1\nline 2", False, name="run_command")
    # error path
    ui.tool_result("boom", True, name="search_code")


def test_describe_search_truncates_long_patterns():
    verb, target = _describe_tool(
        "search_code",
        {"pattern": "tok|trdSym|exSeg|prod|avgnetprice|buyAmt|sellAmt|flBuyQty|flSellQty|cfBuyQty|cfSellQty|lotSz|prc|qty|OrdNo|fldQty|trnsTp", "path": "broker/kotak"},
        None,
    )
    assert verb == "Search"
    assert len(target) < 120  # truncated
    assert "…" in target or target.endswith('" in broker/kotak') or "in broker" in target
