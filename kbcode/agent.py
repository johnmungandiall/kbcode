"""The agent loop (the Claude Code idea): ask the model, run the tools it
requests, feed results back, repeat until it's done.

The loop is provider-agnostic — it only uses the normalized message format
from provider.py, so the same loop drives Claude or any OpenAI-compatible
model (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, ...).
"""

from __future__ import annotations

from rich.console import Console

from .provider import LLMProvider
from .tools import Tools

console = Console()

_MAX_STEPS = 50  # safety cap on tool round-trips per user message


class Agent:
    def __init__(self, system: str, provider: LLMProvider, tools: Tools):
        self.system = system
        self.provider = provider
        self.tools = tools
        self.messages: list[dict] = []

    def run(self, user_input: str) -> None:
        self.messages.append({"role": "user", "content": user_input})

        for _ in range(_MAX_STEPS):
            with console.status("[dim]thinking...[/dim]", spinner="dots"):
                resp = self.provider.complete(self.system, self.messages, self.tools.schemas)

            self.messages.append(
                {
                    "role": "assistant",
                    "text": resp.text,
                    "tool_calls": resp.tool_calls,
                    "raw": resp.raw,
                }
            )
            if resp.text.strip():
                console.print(resp.text)

            if not resp.tool_calls:
                return

            results = []
            for call in resp.tool_calls:
                console.print(f"[cyan]· {call.name}[/cyan] [dim]{_short(call.input)}[/dim]")
                content, is_error = self.tools.execute(call.name, dict(call.input))
                results.append({"id": call.id, "content": content, "is_error": is_error})
            self.messages.append({"role": "tool_results", "results": results})

        console.print("[yellow]Stopped: hit the step limit for one request.[/yellow]")

    def reset(self) -> None:
        self.messages.clear()


def _short(value: object, limit: int = 80) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"
