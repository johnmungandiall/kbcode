"""Post-edit syntax check (kbcode/lint.py + the _lint_note hook in
kbcode/tools/file.py): a write/edit that leaves a file unparseable gets a
WARNING appended to the tool result — including the piece-wise-write escape
clause — while parseable writes stay untouched. Unit-level lint_text coverage
plus the write_file/edit_file/edit_files integration.
"""

from __future__ import annotations

from kbcode.config import Config
from kbcode.knowledge_base import KnowledgeBase
from kbcode.lint import lint_text
from kbcode.memory import Memory
from kbcode.tools import Tools


class _AllowPermissions:
    def check(self, tool: str, detail: str) -> bool:
        return True


def _make_tools(tmp_path) -> Tools:
    project = tmp_path / "project"
    project.mkdir()
    config = Config(project_dir=project)
    config.ensure_dirs()
    return Tools(config, Memory(config.memory_db), KnowledgeBase(config.kb_dir), _AllowPermissions())


# --- lint_text ------------------------------------------------------------


def test_valid_python_passes():
    assert lint_text("a.py", "def f():\n    return 1\n") is None


def test_broken_python_names_the_line_and_marks_it():
    err = lint_text("a.py", "def f():\n    return (1\n")
    assert err is not None
    assert "Python syntax error" in err
    assert "█" in err


def test_broken_json_names_line_and_column():
    err = lint_text("cfg.json", '{"a": 1,}')
    assert err is not None
    assert "JSON parse error at line 1" in err


def test_valid_json_passes():
    assert lint_text("cfg.json", '{"a": 1}') is None


def test_broken_toml_is_reported():
    err = lint_text("cfg.toml", "a = ")
    assert err is not None
    assert "TOML parse error" in err


def test_unchecked_file_types_always_pass():
    assert lint_text("notes.txt", "just {{{ prose") is None
    assert lint_text("page.html", "<div>") is None


# --- the tool-result hook ---------------------------------------------------


def test_write_file_appends_warning_for_broken_python(tmp_path):
    tools = _make_tools(tmp_path)
    out = tools._tool_write_file({"path": "bad.py", "content": "def f(:\n    pass\n"})
    assert out.startswith("wrote ")
    assert "WARNING" in out
    assert "Python syntax error" in out
    # The escape clause for deliberate piece-wise writes (output-budget rules).
    assert "writing it in pieces" in out


def test_write_file_stays_clean_for_valid_python(tmp_path):
    tools = _make_tools(tmp_path)
    out = tools._tool_write_file({"path": "good.py", "content": "x = 1\n"})
    assert "WARNING" not in out


def test_edit_file_warns_when_the_edit_breaks_parsing(tmp_path):
    tools = _make_tools(tmp_path)
    (tools.root / "mod.py").write_text("x = 1\n", encoding="utf-8")
    out = tools._tool_edit_file({"path": "mod.py", "old_string": "x = 1", "new_string": "x = (1"})
    assert "WARNING" in out
    # The write itself still landed — lint is a note, not a failure.
    assert (tools.root / "mod.py").read_text(encoding="utf-8") == "x = (1\n"


def test_edit_files_warns_per_broken_file_only(tmp_path):
    tools = _make_tools(tmp_path)
    (tools.root / "ok.py").write_text("a = 1\n", encoding="utf-8")
    (tools.root / "bad.py").write_text("b = 2\n", encoding="utf-8")
    out = tools._tool_edit_files(
        {
            "edits": [
                {"path": "ok.py", "old_string": "a = 1", "new_string": "a = 2"},
                {"path": "bad.py", "old_string": "b = 2", "new_string": "b = ("},
            ]
        }
    )
    lines = out.splitlines()
    assert lines[0].startswith("edited ") and "ok.py" in lines[0]
    assert "WARNING" not in lines[0]
    assert "WARNING" in out  # the bad.py entry carries it
