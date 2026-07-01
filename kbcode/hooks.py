"""User-scriptable tool interception (the Claude Code idea).

Real Claude Code lets a project configure ``PreToolUse``/``PostToolUse``/
``Stop`` hooks in ``settings.json``: small commands that get the tool call as
JSON on stdin and gate it via exit code (documented at
code.claude.com/docs/en/hooks). That's a public protocol, not proprietary
code, so this module reimplements the same contract from scratch — same event
names, same JSON shape, same exit-code meanings — so a hook script written for
real Claude Code works here unchanged.

Exit-code contract:
  0 -> allow, continue silently.
  2 -> block; stderr is the message fed back to the model (PreToolUse) or
       appended as a note (PostToolUse/Stop).
  anything else -> non-fatal; stderr is surfaced to the user only, run continues.

A broken hook (missing command, timeout, crash) must never take down the
agent loop, so all of that is swallowed as a non-fatal warning.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_TIMEOUT = 30


@dataclass
class HookOutcome:
    blocked: bool = False
    message: str | None = None


class HooksRunner:
    """Runs the ``hooks`` block of settings.json for one project."""

    def __init__(self, config: dict, root: Path, timeout: int | None = None):
        self.config = config or {}
        self.root = root
        # explicit ``timeout`` arg wins; otherwise settings.json can set
        # ``"hooks": {"timeout": N, "PreToolUse": [...]}`` to override the
        # default for every hook command in this project.
        self.timeout = timeout if timeout is not None else int(self.config.get("timeout", _TIMEOUT))

    def run(
        self,
        event: str,
        tool_name: str,
        tool_input: dict,
        tool_output: str | None = None,
        is_error: bool | None = None,
    ) -> HookOutcome:
        entries = self.config.get(event) or []
        if not entries:
            return HookOutcome()

        payload = json.dumps(
            {
                "hook_event_name": event,
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_output,
                "is_error": is_error,
            }
        )

        for entry in entries:
            matcher = entry.get("matcher") or "*"
            if matcher not in ("*", "", tool_name):
                continue
            for hook in entry.get("hooks", []):
                if hook.get("type") != "command" or not hook.get("command"):
                    continue
                outcome = self._run_one(hook["command"], payload)
                if outcome.blocked:
                    return outcome
        return HookOutcome()

    def _run_one(self, command: str, payload: str) -> HookOutcome:
        try:
            proc = subprocess.run(
                command,
                input=payload,
                shell=True,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.debug("hook command %r failed: %s", command, exc)
            return HookOutcome()

        if proc.returncode == 2:
            return HookOutcome(blocked=True, message=proc.stderr.strip() or "Blocked by hook.")
        if proc.returncode != 0 and proc.stderr.strip():
            log.debug("hook command %r exited %s: %s", command, proc.returncode, proc.stderr.strip())
        return HookOutcome()
