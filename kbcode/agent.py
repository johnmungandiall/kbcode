"""The agent loop (the Claude Code idea): ask the model, run the tools it
requests, feed results back, repeat until it's done.

The loop is provider-agnostic — it only uses the normalized message format
from provider.py, so the same loop drives Claude or any OpenAI-compatible
model (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, ...). All presentation goes
through a TerminalUI (see ui.py), so this file stays about logic, not looks.
"""

from __future__ import annotations

from .compaction import compact, estimate_tokens
from .modes import DEFAULT_MODE, Mode, builtin_modes
from .pricing import estimate_cost
from .provider import LLMProvider
from .subagents import Subagent
from .tools import Tools
from .ui import TerminalUI

_MAX_STEPS = 50  # safety cap on tool round-trips per user message
_SUBAGENT_MAX_STEPS = 30  # a delegated task gets its own, smaller budget


class Agent:
    def __init__(
        self,
        system: str,
        provider: LLMProvider,
        tools: Tools,
        compact_threshold: int = 0,
        ui: TerminalUI | None = None,
        modes: dict[str, Mode] | None = None,
        subagents: dict[str, Subagent] | None = None,
    ):
        self.system = system
        self.provider = provider
        self.tools = tools
        self.compact_threshold = compact_threshold  # tokens; 0 disables auto-compaction
        self.ui = ui or TerminalUI()
        self.modes = modes or builtin_modes()
        self.mode = self.modes[DEFAULT_MODE]
        self.messages: list[dict] = []
        # Cumulative token spend this run, for /insights.
        self.usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
        # Subagent delegation (Claude Code idea): expose it to the tools layer.
        self.subagents = subagents or {}
        self.tools.subagents = self.subagents
        self.tools.delegate = self._run_subagent

    def set_mode(self, name: str) -> bool:
        mode = self.modes.get(name)
        if mode is None:
            return False
        self.mode = mode
        return True

    def _system_for_mode(self) -> str:
        return f"{self.system}\n\n## Current mode: {self.mode.name}\n{self.mode.instructions}"

    def _mode_schemas(self) -> list[dict]:
        return [s for s in self.tools.schemas if self.mode.allows(s["name"])]

    def run(self, user_input: str) -> None:
        self._maybe_compact()
        self.messages.append({"role": "user", "content": user_input})

        for _ in range(_MAX_STEPS):
            with self.ui.thinking():
                resp = self.provider.complete(
                    self._system_for_mode(), self.messages, self._mode_schemas()
                )
            self._record_usage(resp.usage)

            self.messages.append(
                {
                    "role": "assistant",
                    "text": resp.text,
                    "tool_calls": resp.tool_calls,
                    "raw": resp.raw,
                }
            )
            self.ui.assistant_text(resp.text)

            if not resp.tool_calls:
                return

            results = []
            for call in resp.tool_calls:
                self.ui.tool_call(call.name, dict(call.input))
                if not self.mode.allows(call.name):
                    content, is_error = (
                        f"Tool '{call.name}' is not available in {self.mode.name} mode. "
                        f"Switch to a mode that allows it (e.g. /mode code) or use a read-only tool.",
                        True,
                    )
                else:
                    content, is_error = self.tools.execute(call.name, dict(call.input))
                self.ui.tool_result(content, is_error)
                results.append({"id": call.id, "content": content, "is_error": is_error})
            self.messages.append({"role": "tool_results", "results": results})

        self.ui.notice("Stopped: hit the step limit for one request.", style="yellow")

    def context_tokens(self) -> int:
        return estimate_tokens(self.messages)

    def _record_usage(self, usage: dict | None) -> None:
        self.usage["requests"] += 1
        if usage:
            self.usage["input_tokens"] += usage.get("input_tokens", 0)
            self.usage["output_tokens"] += usage.get("output_tokens", 0)

    def insights(self) -> dict:
        """Usage/cost summary for this run (Hermes' /insights, adapted)."""
        u = self.usage
        total = u["input_tokens"] + u["output_tokens"]
        return {
            "model": self.provider.config.model if hasattr(self.provider, "config") else "?",
            "requests": u["requests"],
            "input_tokens": u["input_tokens"],
            "output_tokens": u["output_tokens"],
            "total_tokens": total,
            "context_tokens": self.context_tokens(),
            "cost": estimate_cost(
                getattr(getattr(self.provider, "config", None), "model", ""),
                u["input_tokens"],
                u["output_tokens"],
            ),
        }

    def _run_subagent(self, name: str, task: str) -> tuple[str, bool]:
        """Run a delegated task in its own context window; return (summary, is_error)."""
        sub = self.subagents.get(name)
        if sub is None:
            avail = ", ".join(self.subagents) or "(none defined)"
            return f"Unknown subagent '{name}'. Available: {avail}.", True

        system = f"{self.system}\n\n## You are the '{name}' subagent\n{sub.instructions}"
        schemas = [
            s for s in self.tools.schemas
            if s["name"] != "run_subagent" and sub.allows(s["name"])
        ]
        messages: list[dict] = [{"role": "user", "content": task}]
        self.ui.notice(f"↳ delegating to subagent '{name}'…", style="cyan")

        for _ in range(_SUBAGENT_MAX_STEPS):
            resp = self.provider.complete(system, messages, schemas)
            self._record_usage(resp.usage)
            messages.append(
                {"role": "assistant", "text": resp.text, "tool_calls": resp.tool_calls, "raw": resp.raw}
            )
            if not resp.tool_calls:
                self.ui.notice(f"↳ subagent '{name}' done.", style="cyan")
                return resp.text or "(subagent returned no text)", False

            results = []
            for call in resp.tool_calls:
                self.ui.tool_call(f"{name}:{call.name}", dict(call.input))
                if call.name == "run_subagent":
                    content, is_error = "Subagents cannot spawn other subagents.", True
                elif not sub.allows(call.name):
                    content, is_error = (
                        f"Tool '{call.name}' is not allowed for the '{name}' subagent.",
                        True,
                    )
                else:
                    content, is_error = self.tools.execute(call.name, dict(call.input))
                self.ui.tool_result(content, is_error)
                results.append({"id": call.id, "content": content, "is_error": is_error})
            messages.append({"role": "tool_results", "results": results})

        return f"Subagent '{name}' hit its step limit before finishing.", True

    def reset(self) -> None:
        self.messages.clear()

    def _maybe_compact(self) -> None:
        """Auto-summarize old turns once the transcript crosses the threshold."""
        if self.compact_threshold <= 0:
            return
        if estimate_tokens(self.messages) < self.compact_threshold:
            return
        self.compact_now(announce="auto")

    def compact_now(self, announce: str = "manual") -> bool:
        """Summarize the middle of the conversation. Returns True if it compacted."""
        before = estimate_tokens(self.messages)
        with self.ui.working("🗜️  summarizing earlier conversation…"):
            new_messages, summary = compact(self.messages, self.provider)
        if summary is None:
            if announce == "manual":
                self.ui.notice("Not enough conversation to compact yet.")
            return False
        self.messages = new_messages
        after = estimate_tokens(self.messages)
        self.ui.notice(f"🗜️  compacted earlier conversation (~{before:,} → ~{after:,} tokens).")
        return True
