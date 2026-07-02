"""Happy-path and error-path coverage for the core file tools in
kbcode/tools/file.py (read_file/write_file/edit_file/list_dir) — the "hands"
of the agent. Dangerous-command/system-path/rate-limit guards are covered in
test_tools_safety.py, diffs in test_tools_diff.py, redaction counts in
test_tools_redaction.py, and search_code in test_tools_search.py; this file
fills in the plain behavior those don't touch.
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


# --- read_file ----------------------------------------------------------


def test_read_file_returns_line_numbered_content(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    (tools.root / "a.py").write_text("first\nsecond\nthird", encoding="utf-8")

    out = tools._tool_read_file({"path": "a.py"})

    assert out == "1\tfirst\n2\tsecond\n3\tthird"


def test_read_file_missing_file_raises(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    with pytest.raises(ValueError, match="No such file"):
        tools._tool_read_file({"path": "nope.txt"})


# --- write_file: protected paths -----------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".git/config",
        "id_rsa",
        "server.pem",
        ".kbcode/settings.json",
    ],
)
def test_write_file_refuses_protected_paths_without_prompting(tmp_path, path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    with pytest.raises(ValueError, match="Refused"):
        tools._tool_write_file({"path": path, "content": "x"})
    assert perm.calls == []  # never even asked


def test_write_file_allows_env_example(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools._tool_write_file({"path": ".env.example", "content": "KEY=\n"})
    assert (tools.root / ".env.example").read_text(encoding="utf-8") == "KEY=\n"


def test_write_file_returns_confirmation_with_char_count(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    out = tools._tool_write_file({"path": "notes.txt", "content": "hello"})
    assert "notes.txt" in out
    assert "(5 chars)" in out
    assert (tools.root / "notes.txt").read_text(encoding="utf-8") == "hello"


# --- edit_file ------------------------------------------------------------


def test_edit_file_old_string_not_found_raises(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    (tools.root / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not found"):
        tools._tool_edit_file({"path": "a.py", "old_string": "return 2", "new_string": "return 3"})


def test_edit_file_ambiguous_old_string_raises_with_count(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    (tools.root / "a.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="appears 2 times"):
        tools._tool_edit_file({"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"})


def test_edit_file_missing_file_raises(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    with pytest.raises(ValueError, match="No such file"):
        tools._tool_edit_file({"path": "nope.py", "old_string": "a", "new_string": "b"})


def test_edit_file_applies_the_replacement_and_confirms(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    target = tools.root / "a.py"
    target.write_text("def foo():\n    return 1\n", encoding="utf-8")

    out = tools._tool_edit_file({"path": "a.py", "old_string": "return 1", "new_string": "return 2"})

    assert "edited" in out
    assert target.read_text(encoding="utf-8") == "def foo():\n    return 2\n"


# --- list_dir --------------------------------------------------------------


def test_list_dir_lists_files_and_suffixes_directories(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    (tools.root / "listing").mkdir()
    (tools.root / "listing" / "b.txt").write_text("x", encoding="utf-8")
    (tools.root / "listing" / "a.txt").write_text("x", encoding="utf-8")
    (tools.root / "listing" / "sub").mkdir()

    out = tools._tool_list_dir({"path": "listing"})

    assert out.splitlines() == ["a.txt", "b.txt", "sub/"]


def test_list_dir_skips_internal_directories(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    (tools.root / "listing").mkdir()
    (tools.root / "listing" / ".git").mkdir()
    (tools.root / "listing" / "__pycache__").mkdir()
    (tools.root / "listing" / "node_modules").mkdir()
    (tools.root / "listing" / "real.py").write_text("x", encoding="utf-8")

    out = tools._tool_list_dir({"path": "listing"})

    assert out == "real.py"


def test_list_dir_empty_directory(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    (tools.root / "empty").mkdir()

    out = tools._tool_list_dir({"path": "empty"})

    assert out == "(empty)"


def test_list_dir_defaults_to_project_root(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    (tools.root / "only.txt").write_text("x", encoding="utf-8")

    out = tools._tool_list_dir({})

    # ensure_dirs() already created project/kb/, so the root listing (default
    # path ".") includes it alongside the file we just added.
    assert out.splitlines() == ["kb/", "only.txt"]


def test_list_dir_on_a_file_raises(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    (tools.root / "a.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Not a directory"):
        tools._tool_list_dir({"path": "a.txt"})


# --- read_file with offset/limit (range reads for large files) ------------

def test_read_file_with_offset_and_limit(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    content = "\n".join(f"line{i}" for i in range(1, 21))  # 20 lines
    (tools.root / "big.py").write_text(content, encoding="utf-8")

    out = tools._tool_read_file({"path": "big.py", "offset": 5, "limit": 3})

    # Should show original line numbers
    assert "5\tline5" in out
    assert "6\tline6" in out
    assert "7\tline7" in out
    assert "4\t" not in out
    assert "8\t" not in out


def test_read_file_offset_only(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    content = "\n".join(f"L{i}" for i in range(1, 11))
    (tools.root / "f.txt").write_text(content, encoding="utf-8")

    out = tools._tool_read_file({"path": "f.txt", "offset": 8})

    lines = out.splitlines()
    assert lines[0].startswith("8\tL8")
    assert lines[-1].startswith("10\tL10")


def test_read_file_limit_only(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    content = "\n".join(f"row{i}" for i in range(1, 21))
    (tools.root / "data.txt").write_text(content, encoding="utf-8")

    out = tools._tool_read_file({"path": "data.txt", "limit": 4})

    lines = out.splitlines()
    assert len(lines) == 4
    assert lines[0].startswith("1\trow1")
    assert lines[3].startswith("4\trow4")


def test_read_file_offset_beyond_end(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    (tools.root / "short.txt").write_text("a\nb\nc", encoding="utf-8")

    out = tools._tool_read_file({"path": "short.txt", "offset": 100, "limit": 5})

    # Should return empty or just marker, but not crash
    assert out.strip() == "" or "[...truncated...]" in out or "100\t" not in out


def test_read_file_range_respects_budget(tmp_path):
    """Range read output is still capped by the char budget — floored at
    _MIN_READ_CHARS (2000), so a tighter budget can't truncate a read to
    uselessness."""
    tools = _make_tools(tmp_path, _RecordingPermissions())
    # 20 lines of 200 chars ≈ 4000 chars — well over the 2000-char floor.
    lines = ["x" * 200 for _ in range(20)]
    (tools.root / "large.txt").write_text("\n".join(lines), encoding="utf-8")

    tools.context_budget_chars = 300  # floored up to _MIN_READ_CHARS
    out = tools._tool_read_file({"path": "large.txt", "offset": 2, "limit": 18})

    assert "[...file truncated...]" in out
    # Should have started from original line 2
    assert out.startswith("2\t")


def test_read_file_range_and_full_have_consistent_line_numbers(tmp_path):
    perm = _RecordingPermissions()
    tools = _make_tools(tmp_path, perm)
    (tools.root / "nums.txt").write_text("one\ntwo\nthree\nfour\nfive", encoding="utf-8")

    full = tools._tool_read_file({"path": "nums.txt"})
    part = tools._tool_read_file({"path": "nums.txt", "offset": 3, "limit": 2})

    assert "3\tthree" in part
    assert "4\tfour" in part
    # Full file also has correct numbers
    assert full.splitlines()[2].startswith("3\tthree")
