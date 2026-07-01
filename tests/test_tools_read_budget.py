"""Covers IMPROVEMENTS.md #4.2: read_file's truncation limit should shrink as
the conversation nears its compaction budget, instead of always allowing a
fixed 60K chars.
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


def test_read_limit_defaults_to_fixed_cap_when_no_budget_set(tmp_path):
    tools = _make_tools(tmp_path)
    assert tools.context_budget_chars is None
    assert tools._read_limit() == 60000


def test_read_limit_never_goes_below_the_floor(tmp_path):
    tools = _make_tools(tmp_path)
    tools.context_budget_chars = 10  # a near-zero budget
    assert tools._read_limit() == 2000  # _MIN_READ_CHARS


def test_read_limit_never_exceeds_the_fixed_cap(tmp_path):
    tools = _make_tools(tmp_path)
    tools.context_budget_chars = 10_000_000  # plenty of headroom
    assert tools._read_limit() == 60000


def test_read_limit_passes_through_a_mid_range_budget(tmp_path):
    tools = _make_tools(tmp_path)
    tools.context_budget_chars = 5000
    assert tools._read_limit() == 5000


def test_read_file_truncates_to_the_current_budget(tmp_path):
    tools = _make_tools(tmp_path)
    big_file = tools.root / "big.txt"
    big_file.write_text("x" * 10000, encoding="utf-8")

    tools.context_budget_chars = 3000
    out = tools._tool_read_file({"path": "big.txt"})
    assert "[...file truncated...]" in out
    assert len(out) < 3200  # limit + a little slack for line numbers/markers
