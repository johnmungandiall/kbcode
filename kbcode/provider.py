"""LLM providers — talk to any model behind one interface.

The agent speaks a small *normalized* message format and never sees a
provider's native shape. Each provider translates that format to/from its
own API. This is the Hermes "use any model" idea: Claude, OpenAI, Gemini,
DeepSeek, OpenRouter, MiMo, ... all plug in here.

Normalized message items (produced/consumed by the agent):
  {"role": "user", "content": "<text>"}
  {"role": "assistant", "text": "<text>", "tool_calls": [ToolCall...], "raw": <native>}
  {"role": "tool_results", "results": [{"id", "content", "is_error"}]}

The "raw" field holds the provider's own assistant payload so it can be
replayed losslessly (e.g. Claude's thinking blocks, OpenAI's tool_calls).
A session uses one provider, so "raw" is always that provider's shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .config import Config


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    raw: object  # native assistant payload, stored back on the normalized message
    usage: dict | None = None  # {"input_tokens": int, "output_tokens": int} when reported


class LLMProvider:
    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        raise NotImplementedError

    def list_models(self) -> list[str]:
        """Return the model ids this provider/key can use (best effort)."""
        return []


# --------------------------------------------------------------------------
# Anthropic (Claude)
# --------------------------------------------------------------------------
class AnthropicProvider(LLMProvider):
    def __init__(self, config: Config):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Missing package. Run: pip install -r requirements.txt") from exc
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.api_key or None)

    def _to_native(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                out.append({"role": "assistant", "content": m["raw"]})
            elif m["role"] == "tool_results":
                blocks = [
                    {
                        "type": "tool_result",
                        "tool_use_id": r["id"],
                        "content": r["content"],
                        "is_error": r["is_error"],
                    }
                    for r in m["results"]
                ]
                out.append({"role": "user", "content": blocks})
        return out

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        native = self._to_native(messages)
        system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        base = dict(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system_blocks,
            messages=native,
            tools=tools,
        )
        attempts = [
            {**base, "thinking": {"type": "adaptive"}, "output_config": {"effort": self.config.effort}},
            {**base, "thinking": {"type": "adaptive"}},
            base,
        ]
        last_exc: Exception | None = None
        resp = None
        for kwargs in attempts:
            try:
                resp = self.client.messages.create(**kwargs)
                break
            except TypeError as exc:  # SDK too old for this kwarg
                last_exc = exc
        if resp is None:
            raise last_exc  # type: ignore[misc]

        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
        tool_calls = [
            ToolCall(b.id, b.name, dict(b.input))
            for b in resp.content
            if getattr(b, "type", None) == "tool_use"
        ]
        u = getattr(resp, "usage", None)
        usage = {
            "input_tokens": getattr(u, "input_tokens", 0) or 0,
            "output_tokens": getattr(u, "output_tokens", 0) or 0,
        } if u else None
        return LLMResponse(text=text, tool_calls=tool_calls, raw=resp.content, usage=usage)

    def list_models(self) -> list[str]:
        return [m.id for m in self.client.models.list()]


# --------------------------------------------------------------------------
# OpenAI-compatible (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, custom)
# --------------------------------------------------------------------------
class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, config: Config):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Missing package. Run: pip install -r requirements.txt") from exc
        self.config = config
        self.client = OpenAI(api_key=config.api_key or "missing", base_url=config.base_url)

    @staticmethod
    def _tools(tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    def _to_native(self, system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                out.append(m["raw"])  # native assistant message dict
            elif m["role"] == "tool_results":
                for r in m["results"]:
                    out.append(
                        {"role": "tool", "tool_call_id": r["id"], "content": str(r["content"])}
                    )
        return out

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        native = self._to_native(system, messages)
        resp = self.client.chat.completions.create(
            model=self.config.model,
            messages=native,
            tools=self._tools(tools),
            max_tokens=self.config.max_tokens,
        )
        msg = resp.choices[0].message
        text = msg.content or ""

        tool_calls: list[ToolCall] = []
        raw_tool_calls: list[dict] = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append(ToolCall(tc.id, tc.function.name, args))
            raw_tool_calls.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
            )

        raw: dict = {"role": "assistant", "content": msg.content or ""}
        if raw_tool_calls:
            raw["tool_calls"] = raw_tool_calls
        u = getattr(resp, "usage", None)
        usage = {
            "input_tokens": getattr(u, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(u, "completion_tokens", 0) or 0,
        } if u else None
        return LLMResponse(text=text, tool_calls=tool_calls, raw=raw, usage=usage)

    def list_models(self) -> list[str]:
        return [m.id for m in self.client.models.list().data]


def get_provider(config: Config) -> LLMProvider:
    if config.kind == "anthropic":
        return AnthropicProvider(config)
    return OpenAICompatibleProvider(config)
