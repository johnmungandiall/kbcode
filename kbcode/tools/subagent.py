"""The delegate-to-a-subagent tool (the Claude Code idea): run_subagent."""

from __future__ import annotations


class SubagentToolsMixin:
    def _tool_run_subagent(self, inp: dict) -> str:
        """Delegate to a named subagent via the callback the Agent wired up; raises on its error."""
        if self.delegate is None or not self.subagents:
            raise ValueError("No subagents are configured (.kbcode/agents/).")
        content, is_error = self.delegate(inp["agent"], inp["task"])
        if is_error:
            raise ValueError(content)
        return content
