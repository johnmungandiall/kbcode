"""Covers IMPROVEMENTS.md #8.1 (session search) and #8.2 (session export)."""

from __future__ import annotations

from kbcode.provider import ToolCall
from kbcode.sessions import SessionRecorder, export_markdown, search_sessions


def _make_session(sessions_dir, project_dir, provider="anthropic", model="claude-x") -> SessionRecorder:
    return SessionRecorder(sessions_dir, project_dir, provider, model, "code")


# --- search_sessions ---------------------------------------------------


def test_search_finds_session_mentioning_the_query(tmp_path):
    sessions_dir = tmp_path / "sessions"
    rec = _make_session(sessions_dir, tmp_path)
    rec.append({"role": "user", "content": "help me fix the widget renderer"})
    rec.append({"role": "assistant", "text": "sure, looking now", "tool_calls": [], "raw": {}})

    other = _make_session(sessions_dir, tmp_path)
    other.append({"role": "user", "content": "totally unrelated question"})

    hits = search_sessions(sessions_dir, "widget")
    assert len(hits) == 1
    assert hits[0]["id"] == rec.id
    assert "widget" in hits[0]["snippet"].lower()


def test_search_is_case_insensitive(tmp_path):
    sessions_dir = tmp_path / "sessions"
    rec = _make_session(sessions_dir, tmp_path)
    rec.append({"role": "user", "content": "Fix the WIDGET please"})
    hits = search_sessions(sessions_dir, "widget")
    assert len(hits) == 1


def test_search_no_matches_returns_empty(tmp_path):
    sessions_dir = tmp_path / "sessions"
    rec = _make_session(sessions_dir, tmp_path)
    rec.append({"role": "user", "content": "hello there"})
    assert search_sessions(sessions_dir, "nonexistent-term") == []


def test_search_empty_query_returns_empty(tmp_path):
    sessions_dir = tmp_path / "sessions"
    _make_session(sessions_dir, tmp_path)
    assert search_sessions(sessions_dir, "") == []
    assert search_sessions(sessions_dir, "   ") == []


def test_search_missing_sessions_dir_returns_empty(tmp_path):
    assert search_sessions(tmp_path / "does-not-exist", "anything") == []


def test_search_results_sorted_most_recent_first(tmp_path):
    sessions_dir = tmp_path / "sessions"
    first = _make_session(sessions_dir, tmp_path)
    first.append({"role": "user", "content": "widget one"})
    second = _make_session(sessions_dir, tmp_path)
    second.append({"role": "user", "content": "widget two"})

    hits = search_sessions(sessions_dir, "widget")
    assert {h["id"] for h in hits} == {first.id, second.id}
    assert hits == sorted(hits, key=lambda r: r["started_at"], reverse=True)


# --- export_markdown -----------------------------------------------------


def test_export_markdown_includes_header_and_messages(tmp_path):
    sessions_dir = tmp_path / "sessions"
    rec = _make_session(sessions_dir, tmp_path, provider="anthropic", model="claude-opus")
    rec.append({"role": "user", "content": "please read main.py"})
    rec.append(
        {
            "role": "assistant",
            "text": "reading it now",
            "tool_calls": [ToolCall(id="1", name="read_file", input={"path": "main.py"})],
            "raw": {},
        }
    )
    rec.append({"role": "tool_results", "results": [{"id": "1", "content": "1\tprint('hi')", "is_error": False}]})

    md = export_markdown(rec.path)
    assert f"# kbcode session {rec.id}" in md
    assert "anthropic / claude-opus" in md
    assert "please read main.py" in md
    assert "reading it now" in md
    assert "called `read_file(" in md
    assert "print('hi')" in md
    assert "[tool result: ok]" in md


def test_export_markdown_flags_error_tool_results(tmp_path):
    sessions_dir = tmp_path / "sessions"
    rec = _make_session(sessions_dir, tmp_path)
    rec.append({"role": "user", "content": "run it"})
    rec.append({"role": "tool_results", "results": [{"id": "1", "content": "boom", "is_error": True}]})
    md = export_markdown(rec.path)
    assert "[tool result: error]" in md
    assert "boom" in md
