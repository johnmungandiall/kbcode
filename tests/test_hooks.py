"""Covers hooks.py: the Claude-Code-style PreToolUse/PostToolUse/Stop hook
protocol (JSON on stdin, exit-code contract) — see kbcode/hooks.py.
"""

from __future__ import annotations

import sys

from kbcode.hooks import HooksRunner


def _write_script(tmp_path, body: str) -> str:
    """Write a tiny python hook script and return a shell command that runs it
    with the current interpreter (avoids shell-quoting differences across
    Windows/POSIX)."""
    script = tmp_path / "hook.py"
    script.write_text(body, encoding="utf-8")
    return f'"{sys.executable}" "{script}"'


def test_no_hooks_configured_allows(tmp_path):
    runner = HooksRunner({}, tmp_path)
    outcome = runner.run("PreToolUse", "run_command", {"command": "echo hi"})
    assert outcome.blocked is False


def test_exit_code_0_allows(tmp_path):
    cmd = _write_script(tmp_path, "import sys; sys.exit(0)")
    config = {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}
    runner = HooksRunner(config, tmp_path)
    outcome = runner.run("PreToolUse", "run_command", {"command": "echo hi"})
    assert outcome.blocked is False


def test_exit_code_2_blocks_with_stderr_message(tmp_path):
    cmd = _write_script(
        tmp_path,
        "import sys; sys.stderr.write('nope, use rg instead'); sys.exit(2)",
    )
    config = {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}
    runner = HooksRunner(config, tmp_path)
    outcome = runner.run("PreToolUse", "run_command", {"command": "grep foo"})
    assert outcome.blocked is True
    assert "nope, use rg instead" in outcome.message


def test_nonzero_non_two_exit_code_is_non_fatal(tmp_path):
    cmd = _write_script(tmp_path, "import sys; sys.stderr.write('warn only'); sys.exit(1)")
    config = {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}
    runner = HooksRunner(config, tmp_path)
    outcome = runner.run("PreToolUse", "run_command", {"command": "echo hi"})
    assert outcome.blocked is False


def test_matcher_only_matches_named_tool(tmp_path):
    cmd = _write_script(tmp_path, "import sys; sys.exit(2)")
    config = {"PreToolUse": [{"matcher": "run_command", "hooks": [{"type": "command", "command": cmd}]}]}
    runner = HooksRunner(config, tmp_path)
    assert runner.run("PreToolUse", "write_file", {}).blocked is False
    assert runner.run("PreToolUse", "run_command", {}).blocked is True


def test_matcher_wildcard_matches_every_tool(tmp_path):
    cmd = _write_script(tmp_path, "import sys; sys.exit(2)")
    config = {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}
    runner = HooksRunner(config, tmp_path)
    assert runner.run("PreToolUse", "write_file", {}).blocked is True
    assert runner.run("PreToolUse", "run_command", {}).blocked is True


def test_different_event_name_does_not_fire(tmp_path):
    cmd = _write_script(tmp_path, "import sys; sys.exit(2)")
    config = {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}
    runner = HooksRunner(config, tmp_path)
    assert runner.run("PostToolUse", "run_command", {}).blocked is False


def test_missing_command_does_not_crash(tmp_path):
    config = {
        "PreToolUse": [
            {"matcher": "*", "hooks": [{"type": "command", "command": "this-binary-does-not-exist-xyz"}]}
        ]
    }
    runner = HooksRunner(config, tmp_path)
    outcome = runner.run("PreToolUse", "run_command", {})
    assert outcome.blocked is False


def test_timeout_does_not_crash(tmp_path):
    cmd = _write_script(tmp_path, "import time; time.sleep(5)")
    config = {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}
    runner = HooksRunner(config, tmp_path, timeout=1)
    outcome = runner.run("PreToolUse", "run_command", {})
    assert outcome.blocked is False


def test_hook_receives_tool_name_and_input_as_json_on_stdin(tmp_path):
    cmd = _write_script(
        tmp_path,
        "import sys, json\n"
        "d = json.load(sys.stdin)\n"
        "sys.stderr.write(d['tool_name'] + ':' + d['tool_input']['path'])\n"
        "sys.exit(2)\n",
    )
    config = {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}
    runner = HooksRunner(config, tmp_path)
    outcome = runner.run("PreToolUse", "write_file", {"path": "a.txt"})
    assert outcome.message == "write_file:a.txt"
