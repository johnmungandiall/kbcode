"""Covers IMPROVEMENTS.md #6.2: tool output should note *how many* secrets
were redacted (without revealing them), not mask silently.
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


def test_read_file_notes_redaction_count(tmp_path):
    tools = _make_tools(tmp_path)
    secret_file = tools.root / "secrets.txt"
    secret_file.write_text("API_KEY=sk-" + "a" * 24, encoding="utf-8")

    out = tools._tool_read_file({"path": "secrets.txt"})
    assert "sk-" + "a" * 24 not in out
    assert "[kbcode redacted 1 likely secret from this output]" in out


def test_read_file_no_note_when_nothing_redacted(tmp_path):
    tools = _make_tools(tmp_path)
    clean_file = tools.root / "clean.txt"
    clean_file.write_text("just some ordinary text", encoding="utf-8")

    out = tools._tool_read_file({"path": "clean.txt"})
    assert "kbcode redacted" not in out


def test_search_code_notes_redaction_count(tmp_path):
    tools = _make_tools(tmp_path)
    (tools.root / "config.py").write_text("TOKEN = 'ghp_" + "b" * 24 + "'\n", encoding="utf-8")

    out = tools._tool_search_code({"pattern": "TOKEN"})
    assert "ghp_" + "b" * 24 not in out
    assert "[kbcode redacted 1 likely secret from this output]" in out


def test_run_command_notes_redaction_count(tmp_path):
    tools = _make_tools(tmp_path)
    secret = "sk-" + "c" * 24
    out = tools._tool_run_command({"command": f"echo {secret}"})
    assert secret not in out
    assert "kbcode redacted" in out


def test_run_command_no_note_for_clean_output(tmp_path):
    tools = _make_tools(tmp_path)
    out = tools._tool_run_command({"command": "echo hello"})
    assert "kbcode redacted" not in out
