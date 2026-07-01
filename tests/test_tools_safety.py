"""Covers IMPROVEMENTS.md #6.1 (dangerous-command guard), #6.3 (system-path
warning), and #6.4 (per-turn run_command rate limit).
"""

from __future__ import annotations

import os
from pathlib import Path

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


# --- dangerous-command guard ------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        "sudo rm -rf ~",
        ":(){ :|:& };:",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "chmod -R 777 /",
        "format C:",
    ],
)
def test_dangerous_commands_are_refused_without_prompting(tmp_path, command):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    with pytest.raises(ValueError, match="destructive"):
        tools._tool_run_command({"command": command})
    assert perm.calls == []  # refused before ever asking permission


def test_ordinary_commands_are_not_flagged_as_dangerous(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    out = tools._tool_run_command({"command": "echo hello"})
    assert "hello" in out
    assert len(perm.calls) == 1


def test_execute_surfaces_dangerous_command_as_tool_error(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    content, is_error = tools.execute("run_command", {"command": "rm -rf /"})
    assert is_error is True
    assert "destructive" in content


# --- per-turn rate limit -----------------------------------------------------


def test_run_command_rate_limit_allows_up_to_the_cap(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    for _ in range(10):
        out = tools._tool_run_command({"command": "echo hi"})
        assert "exit code: 0" in out


def test_run_command_rate_limit_blocks_beyond_the_cap(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    for _ in range(10):
        tools._tool_run_command({"command": "echo hi"})
    with pytest.raises(ValueError, match="safety limit"):
        tools._tool_run_command({"command": "echo hi"})


def test_run_command_rate_limit_resets_on_new_turn(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    for _ in range(10):
        tools._tool_run_command({"command": "echo hi"})
    tools.new_turn()
    out = tools._tool_run_command({"command": "echo hi"})  # doesn't raise
    assert "exit code: 0" in out


# --- system-path warning ------------------------------------------------


def test_is_system_path_flags_windows_dirs():
    assert Tools._is_system_path(Path("C:/Windows/System32/evil.dll"))
    assert Tools._is_system_path(Path("C:/Program Files/App/x.exe"))


def test_is_system_path_flags_posix_dirs():
    assert Tools._is_system_path(Path("/etc/passwd"))
    assert Tools._is_system_path(Path("/usr/bin/ls"))


def test_is_system_path_does_not_flag_project_paths():
    assert not Tools._is_system_path(Path("/home/user/project/file.py"))
    assert not Tools._is_system_path(Path("D:/AI Agents development/kb-code/file.py"))


def test_write_file_warns_when_target_is_a_system_path(tmp_path):
    perm = _RecordingPermissions(allow=False)  # deny -> nothing is actually written
    tools = _make_tools(tmp_path, perm)
    target = "C:/Windows/Temp/should-not-write.txt" if os.name == "nt" else "/etc/should-not-write.txt"
    with pytest.raises(PermissionError):
        tools._tool_write_file({"path": target, "content": "x"})
    assert len(perm.calls) == 1
    _tool, detail = perm.calls[0]
    assert "system directory" in detail.lower()


def test_write_file_no_system_warning_for_ordinary_project_path(tmp_path):
    perm = _RecordingPermissions(allow=True)
    tools = _make_tools(tmp_path, perm)
    tools._tool_write_file({"path": "notes.txt", "content": "hi"})
    assert len(perm.calls) == 1
    _tool, detail = perm.calls[0]
    assert "system directory" not in detail.lower()
