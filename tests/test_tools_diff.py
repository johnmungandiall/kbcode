"""Covers IMPROVEMENTS.md #7.2: write_file/edit_file should show a diff in
the permission prompt, not just a byte count — so approval reflects what
will actually change.
"""

from __future__ import annotations

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


def test_write_file_new_file_has_no_diff(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools._tool_write_file({"path": "new.txt", "content": "hello"})
    _tool, detail = perm.calls[0]
    assert "@@" not in detail  # no unified-diff hunk marker for a brand-new file


def test_write_file_overwrite_shows_diff(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    (tools.root / "existing.txt").write_text("old line\n", encoding="utf-8")
    tools._tool_write_file({"path": "existing.txt", "content": "new line\n"})
    _tool, detail = perm.calls[0]
    assert "-old line" in detail
    assert "+new line" in detail


def test_write_file_overwrite_with_identical_content_has_no_diff(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    (tools.root / "same.txt").write_text("unchanged\n", encoding="utf-8")
    tools._tool_write_file({"path": "same.txt", "content": "unchanged\n"})
    _tool, detail = perm.calls[0]
    assert "@@" not in detail


def test_edit_file_shows_diff_of_the_change(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    (tools.root / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    tools._tool_edit_file({"path": "mod.py", "old_string": "return 1", "new_string": "return 2"})
    _tool, detail = perm.calls[0]
    assert "-    return 1" in detail
    assert "+    return 2" in detail


def test_edit_file_denied_permission_does_not_write(tmp_path):
    perm = _RecordingPermissions(allow=False)
    tools = _make_tools(tmp_path, perm)
    target = tools.root / "mod.py"
    target.write_text("def foo():\n    return 1\n", encoding="utf-8")
    try:
        tools._tool_edit_file({"path": "mod.py", "old_string": "return 1", "new_string": "return 2"})
        assert False, "expected PermissionError"
    except PermissionError:
        pass
    assert target.read_text(encoding="utf-8") == "def foo():\n    return 1\n"


def test_diff_is_truncated_for_very_large_changes(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    old_lines = "\n".join(f"line {i}" for i in range(2000))
    new_lines = "\n".join(f"changed {i}" for i in range(2000))
    (tools.root / "big.txt").write_text(old_lines, encoding="utf-8")
    tools._tool_write_file({"path": "big.txt", "content": new_lines})
    _tool, detail = perm.calls[0]
    assert "[...diff truncated...]" in detail
