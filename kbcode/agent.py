"""The agent loop (the Claude Code idea): ask the model, run the tools it
requests, feed results back, repeat until it's done.

The loop is provider-agnostic — it only uses the normalized message format
from provider.py, so the same loop drives Claude or any OpenAI-compatible
model (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, ...). All presentation goes
through a TerminalUI (see ui.py), so this file stays about logic, not looks.
"""

from __future__ import annotations

from .compaction import compact, estimate_tokens
from .provider import LLMProvider
from .tools import Tools
from .ui import TerminalUI

_MAX_STEPS = 50  # safety cap on tool round-trips per user message


class Agent:
    def __init__(
        self,
        system: str,
        provider: LLMProvider,
        tools: Tools,
        compact_threshold: int = 0,
        ui: TerminalUI | None = None,
    ):
        self.system = system
        self.provider = provider
        self.tools = tools
        self.compact_threshold = compact_threshold  # tokens; 0 disables auto-compaction
        self.ui = ui or TerminalUI()
        self.messages: list[dict] = []

    def run(self, user_input: str) -> None:
        self._maybe_compact()
        self.messages.append({"role": "user", "content": user_input})

        for _ in range(_MAX_STEPS):
            with self.ui.thinking():
                resp = self.provider.complete(self.system, self.messages, self.tools.schemas)

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
                content, is_error = self.tools.execute(call.name, dict(call.input))
                self.ui.tool_result(content, is_error)
                results.append({"id": call.id, "content": content, "is_error": is_error})
            self.messages.append({"role": "tool_results", "results": results})

        self.ui.notice("Stopped: hit the step limit for one request.", style="yellow")

    def context_tokens(self) -> int:
        return estimate_tokens(self.messages)

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
