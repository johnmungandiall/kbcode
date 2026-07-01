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
import time
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


class ProviderError(RuntimeError):
    """A clean, user-facing failure from the model provider.

    The agent/CLI catch this to show a friendly message instead of a raw SDK
    traceback. ``hint`` (when set) tells the user how to fix a hard error, e.g.
    a rejected API key. Transient errors (rate limits, 5xx, network blips) are
    retried automatically first; this is only raised once retries are spent.
    """

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


# How many times to retry a transient provider failure, and the starting
# backoff (seconds), which doubles each attempt: ~1.5s, 3s, 6s.
_MAX_RETRIES = 4
_BACKOFF_BASE = 1.5


def _classify(exc: Exception) -> tuple[bool, str, str | None]:
    """Map an SDK/transport exception to ``(retryable, message, hint)``.

    Works for both the Anthropic and OpenAI SDKs without importing either:
    their HTTP errors expose ``status_code``, and connection/timeout errors
    name themselves clearly. We avoid retrying things the user must fix
    (a bad key, a malformed request)."""
    status = getattr(exc, "status_code", None)
    blob = f"{type(exc).__name__}: {exc}".lower()

    # Authentication / authorization — never retry; the key must be fixed.
    if status in (401, 403) or any(s in blob for s in ("authenticat", "api key", "unauthor", "permission")):
        return (
            False,
            "Authentication failed — the API key was rejected.",
            "Check the key for this provider: run  python -m kbcode model  (or set it in .env).",
        )
    # Rate limited or a server-side error — worth retrying with backoff.
    if status == 429 or (isinstance(status, int) and status >= 500):
        label = "rate limited" if status == 429 else f"server error (HTTP {status})"
        return True, f"Provider is busy — {label}.", None
    # Transport problems (no status code): connection refused, DNS, timeout.
    if any(s in blob for s in ("connection", "timeout", "timed out", "temporarily")):
        return True, "Network problem reaching the provider.", "Check your internet connection."
    # The current model/route has no vision-capable endpoint — surfaced by
    # OpenRouter and others as a plain 400/404 with "image" in the message.
    if "image" in blob and any(s in blob for s in ("endpoint", "support", "multimodal", "vision")):
        return (
            False,
            "This model doesn't support image input.",
            "Switch to a vision-capable model (Claude, GPT-4o, Gemini, ...) with  python -m kbcode model  , or continue without attaching an image.",
        )
    # Bad request (400/404/422) and anything else: don't retry blindly.
    if isinstance(status, int):
        return False, f"Provider rejected the request (HTTP {status}): {exc}", None
    return False, f"Provider error: {exc}", None


def _with_retry(fn, ui=None):
    """Call ``fn`` and retry transient provider failures with exponential
    backoff. Raises :class:`ProviderError` (clean, user-facing) when it finally
    gives up. ``ui`` (optional) gets a yellow "retrying…" notice between tries.

    ``TypeError`` is re-raised untouched so a caller's SDK-version fallback
    (older SDKs reject newer kwargs) still works."""
    delay = _BACKOFF_BASE
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except (ProviderError, TypeError):
            raise
        except Exception as exc:  # noqa: BLE001 - normalize any SDK/transport error
            retryable, message, hint = _classify(exc)
            if not retryable or attempt == _MAX_RETRIES - 1:
                raise ProviderError(message, hint=hint) from exc
            if ui is not None:
                try:
                    ui.notice(
                        f"{message} retrying in {delay:.0f}s "
                        f"({attempt + 1}/{_MAX_RETRIES - 1})…",
                        style="yellow",
                    )
                except Exception:  # noqa: BLE001 - never let a UI hiccup mask the retry
                    pass
            time.sleep(delay)
            delay *= 2
    raise ProviderError("Provider call failed after retries.")  # unreachable


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
    def __init__(self, config: Config, ui=None):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Missing package. Run: pip install -r requirements.txt") from exc
        self.config = config
        self.ui = ui  # optional: receives "retrying…" notices
        self.client = anthropic.Anthropic(api_key=config.api_key or None)

    def _to_native(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m["role"] == "user":
                if m.get("images"):
                    content: list[dict] = []
                    if m["content"]:
                        content.append({"type": "text", "text": m["content"]})
                    for im in m["images"]:
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": im["media_type"],
                                "data": im["data"],
                            },
                        })
                    out.append({"role": "user", "content": content})
                else:
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
                # Transient errors (rate limit / 5xx / network) are retried inside
                # _with_retry; a TypeError means this SDK rejects the kwarg, so it
                # propagates here to fall through to the next, simpler attempt.
                resp = _with_retry(lambda kw=kwargs: self.client.messages.create(**kw), self.ui)
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
    def __init__(self, config: Config, ui=None):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Missing package. Run: pip install -r requirements.txt") from exc
        self.config = config
        self.ui = ui  # optional: receives "retrying…" notices
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
                if m.get("images"):
                    parts: list[dict] = []
                    if m["content"]:
                        parts.append({"type": "text", "text": m["content"]})
                    for im in m["images"]:
                        url = f"data:{im['media_type']};base64,{im['data']}"
                        parts.append({"type": "image_url", "image_url": {"url": url}})
                    out.append({"role": "user", "content": parts})
                else:
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
        resp = _with_retry(
            lambda: self.client.chat.completions.create(
                model=self.config.model,
                messages=native,
                tools=self._tools(tools),
                max_tokens=self.config.max_tokens,
            ),
            self.ui,
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


def get_provider(config: Config, ui=None) -> LLMProvider:
    if config.kind == "anthropic":
        return AnthropicProvider(config, ui)
    return OpenAICompatibleProvider(config, ui)
