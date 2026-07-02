"""Background commands: run_command(background=true) + check_task in
kbcode/tools/file.py — start, poll, kill, and exit-time cleanup."""

from __future__ import annotations

import sys
import time

import pytest

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


def _wait_for_finish(tools: Tools, task_id: str, timeout: float = 15.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = tools._tool_check_task({"task_id": task_id})
        if "finished" in out:
            return out
        time.sleep(0.2)
    pytest.fail(f"background task {task_id} never finished: {out}")


def test_background_command_returns_task_id_and_output_lands(tmp_path):
    tools = _make_tools(tmp_path)
    cmd = f'"{sys.executable}" -c "print(\'bg hello\')"'

    out = tools._tool_run_command({"command": cmd, "background": True})

    assert "Started background task bg-1" in out
    assert "check_task" in out
    done = _wait_for_finish(tools, "bg-1")
    assert "exit code 0" in done
    assert "bg hello" in done


def test_check_task_reports_running_then_kill_stops_it(tmp_path):
    tools = _make_tools(tmp_path)
    cmd = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    tools._tool_run_command({"command": cmd, "background": True})

    status = tools._tool_check_task({"task_id": "bg-1"})
    assert "running (pid" in status

    killed = tools._tool_check_task({"task_id": "bg-1", "kill": True})
    assert "killed" in killed
    # After the kill it is no longer running.
    assert tools.bg_tasks["bg-1"]["proc"].poll() is not None


def test_check_task_unknown_id_lists_known_tasks(tmp_path):
    tools = _make_tools(tmp_path)
    with pytest.raises(ValueError, match="Unknown task 'bg-9'"):
        tools._tool_check_task({"task_id": "bg-9"})


def test_background_still_gated_by_permission(tmp_path):
    tools = _make_tools(tmp_path)
    tools.perm = Permissions(auto_approve=False)
    tools.perm.check = lambda tool, detail: False  # deny
    with pytest.raises(PermissionError):
        tools._tool_run_command({"command": "echo hi", "background": True})
    assert tools.bg_tasks == {}


def test_stop_background_tasks_kills_survivors(tmp_path):
    tools = _make_tools(tmp_path)
    cmd = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    tools._tool_run_command({"command": cmd, "background": True})
    assert tools.bg_tasks["bg-1"]["proc"].poll() is None

    stopped = tools.stop_background_tasks()

    assert stopped == 1
    tools.bg_tasks["bg-1"]["proc"].wait(timeout=10)
    # A second call finds nothing left to stop.
    assert tools.stop_background_tasks() == 0
