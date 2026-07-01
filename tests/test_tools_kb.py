"""Covers IMPROVEMENTS.md #5.2: kb_write should show a diff and ask before
overwriting a note with different content — but stay frictionless for the
routine case (a brand new note, or rewriting identical content), since the
agent is nudged to update kb/ notes on nearly every turn.
"""

from __future__ import annotations

import pytest

from kbcode.config import Config
from kbcode.knowledge_base import KnowledgeBase
from kbcode.memory import Memory
from kbcode.tools import Tools


class _RecordingPermissions:
    def __init__(self, allow: bool = True):
        self.allow = allow
        self.calls: list[tuple[str, str]] = []

    def check(self, tool: str, detail: str) -> bool:
        self.calls.append((tool, detail))
        return self.allow


def _make_tools(tmp_path, perm) -> Tools:
    project = tmp_path / "project"
    project.mkdir()
    config = Config(project_dir=project)
    config.ensure_dirs()
    memory = Memory(config.memory_db)
    kb = KnowledgeBase(config.kb_dir)
    return Tools(config, memory, kb, perm)


def test_new_note_writes_without_asking_permission(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools._tool_kb_write({"name": "notes", "content": "first version"})
    assert perm.calls == []
    assert tools.kb.read_note("notes") == "first version"


def test_rewriting_identical_content_does_not_ask(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools._tool_kb_write({"name": "notes", "content": "same"})
    perm.calls.clear()
    tools._tool_kb_write({"name": "notes", "content": "same"})
    assert perm.calls == []


def test_overwriting_different_content_asks_and_shows_a_diff(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools._tool_kb_write({"name": "notes", "content": "old line"})
    tools._tool_kb_write({"name": "notes", "content": "new line"})

    assert len(perm.calls) == 1
    tool, detail = perm.calls[0]
    assert tool == "kb_write"
    assert "-old line" in detail
    assert "+new line" in detail
    assert tools.kb.read_note("notes") == "new line"


def test_denied_overwrite_raises_and_keeps_old_content(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools._tool_kb_write({"name": "notes", "content": "old line"})

    perm.allow = False
    with pytest.raises(PermissionError):
        tools._tool_kb_write({"name": "notes", "content": "new line"})
    assert tools.kb.read_note("notes") == "old line"


def test_kb_write_flags_a_broken_pointer_immediately(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    out = tools._tool_kb_write({"name": "notes", "content": "See `nope.py:10` for details."})
    assert "[pointer check]" in out
    assert "file not found" in out


def test_kb_write_says_nothing_when_pointers_are_fine(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    (tools.root / "mod.py").write_text("line1\nline2\n", encoding="utf-8")
    out = tools._tool_kb_write({"name": "notes", "content": "See `mod.py:1` for details."})
    assert "[pointer check]" not in out


def test_kb_write_pointer_check_is_scoped_to_the_written_note(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools._tool_kb_write({"name": "broken", "content": "See `nope.py:1`."})
    # writing an unrelated, clean note shouldn't get flagged for broken.md's problem
    out = tools._tool_kb_write({"name": "clean", "content": "nothing to point at"})
    assert "[pointer check]" not in out


def test_kb_search_finds_a_note(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools._tool_kb_write({"name": "architecture", "content": "The Widget lives here."})
    out = tools._tool_kb_search({"query": "widget"})
    assert "kb/architecture.md" in out
    assert "Widget" in out


def test_kb_search_no_matches(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    out = tools._tool_kb_search({"query": "nonexistent-term"})
    assert out == "(no matches)"


def test_remember_and_recall_kind_filter(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools.execute("remember", {"content": "fixed the login bug", "kind": "bug"})
    tools.execute("remember", {"content": "decided on SQLite", "kind": "decision"})

    out, is_error = tools.execute("recall", {"query": "the", "kind": "bug"})
    assert is_error is False
    assert "[bug]" in out
    assert "login bug" in out
    assert "decided on SQLite" not in out


def test_remember_invalid_kind_falls_back_to_note(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools.execute("remember", {"content": "something", "kind": "not-a-real-kind"})
    out, _ = tools.execute("recall", {"query": "something"})
    assert "[note]" in out


def test_execute_surfaces_denied_kb_write_as_tool_error(tmp_path):
    perm = _RecordingPermissions(allow=False)
    tools = _make_tools(tmp_path, perm)
    content, is_error = tools.execute("kb_write", {"name": "notes", "content": "x"})
    assert is_error is False  # brand new note — no permission needed
    perm.allow = False
    content, is_error = tools.execute("kb_write", {"name": "notes", "content": "y"})
    assert is_error is True
    assert "denied" in content.lower()
