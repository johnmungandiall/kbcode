"""Direct unit tests for ToolsCore._repair() (kbcode/tools/core.py) — the
openclaw-inspired tool-call repair that turns a malformed structured call into
guidance fed back to the model, instead of a hard crash. test_agent.py only
exercises this indirectly through a full agent turn; these tests hit
Tools._repair directly with the range of malformed inputs it needs to handle.
"""

from __future__ import annotations

from kbcode.config import Config
from kbcode.knowledge_base import KnowledgeBase
from kbcode.memory import Memory
from kbcode.permissions import Permissions
from kbcode.tools import Tools


def _make_tools(tmp_path) -> Tools:
    project = tmp_path / "project"
    project.mkdir()
    config = Config(project_dir=project)
    config.ensure_dirs()
    memory = Memory(config.memory_db)
    kb = KnowledgeBase(config.kb_dir)
    perm = Permissions(auto_approve=True)
    return Tools(config, memory, kb, perm)


def test_unknown_tool_with_no_close_match_lists_available_tools(tmp_path):
    tools = _make_tools(tmp_path)
    guidance = tools._repair("delete_everything", {})
    assert guidance is not None
    assert "Unknown tool 'delete_everything'" in guidance
    assert "Did you mean" not in guidance
    assert "read_file" in guidance  # available tools are listed


def test_unknown_tool_with_a_close_match_gets_a_suggestion(tmp_path):
    tools = _make_tools(tmp_path)
    guidance = tools._repair("read_fil", {"path": "a.py"})
    assert guidance is not None
    assert "Did you mean 'read_file'?" in guidance


def test_known_tool_missing_required_argument(tmp_path):
    tools = _make_tools(tmp_path)
    guidance = tools._repair("read_file", {})
    assert guidance is not None
    assert "missing required argument(s): path" in guidance


def test_known_tool_missing_multiple_required_arguments(tmp_path):
    tools = _make_tools(tmp_path)
    guidance = tools._repair("edit_file", {"path": "a.py"})
    assert guidance is not None
    assert "old_string" in guidance
    assert "new_string" in guidance


def test_empty_string_required_argument_counts_as_missing(tmp_path):
    tools = _make_tools(tmp_path)
    guidance = tools._repair("read_file", {"path": ""})
    assert guidance is not None
    assert "path" in guidance


def test_none_required_argument_counts_as_missing(tmp_path):
    tools = _make_tools(tmp_path)
    guidance = tools._repair("read_file", {"path": None})
    assert guidance is not None
    assert "path" in guidance


def test_all_required_arguments_present_returns_none(tmp_path):
    tools = _make_tools(tmp_path)
    assert tools._repair("read_file", {"path": "a.py"}) is None


def test_tool_with_no_required_arguments_returns_none(tmp_path):
    tools = _make_tools(tmp_path)
    assert tools._repair("list_dir", {}) is None


def test_execute_surfaces_repair_guidance_as_a_tool_error(tmp_path):
    tools = _make_tools(tmp_path)
    content, is_error = tools.execute("write_file", {"path": "a.txt"})
    assert is_error is True
    assert "missing required argument(s): content" in content
