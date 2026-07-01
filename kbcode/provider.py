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
from typing import Callable, TypeVar

from .config import Config

_T = TypeVar("_T")


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


def _with_retry(fn: Callable[[], _T], ui=None) -> _T:
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
    def _client_kwargs(self) -> dict:
        """Shared constructor kwargs for the underlying SDK client. Adds an
        explicit request timeout so a stalled model can't freeze the agent for
        the SDK's ~10-minute default; 0 (KBCODE_REQUEST_TIMEOUT=0) opts out and
        restores that default. Both the Anthropic and OpenAI SDK clients accept
        a ``timeout`` kwarg (seconds)."""
        timeout = getattr(self.config, "request_timeout", 0)
        return {"timeout": timeout} if timeout and timeout > 0 else {}

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        raise NotImplementedError

    def stream(self, system: str, messages: list[dict], tools: list[dict], on_text=None) -> LLMResponse:
        """Token-by-token variant of complete() (#3.1/#7.1). Default falls back
        to complete() and delivers the whole text as one chunk, so a provider
        that hasn't implemented true streaming still works — just without the
        incremental display. Subclasses override for real streaming."""
        resp = self.complete(system, messages, tools)
        if on_text and resp.text:
            on_text(resp.text)
        return resp

    def list_models(self) -> list[str]:
        """Return the model ids this provider/key can use (best effort)."""
        return []


# --------------------------------------------------------------------------
# Anthropic (Claude)
# --------------------------------------------------------------------------
class AnthropicProvider(LLMProvider):
    def __init__(self, config: Config, ui=None):
        self.config = config
        self.ui = ui  # optional: receives "retrying…" notices
        self._client = None  # built lazily so `import anthropic` isn't paid at startup

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("Missing package. Run: pip install -r requirements.txt") from exc
            self._client = anthropic.Anthropic(
                api_key=self.config.api_key or None,
                **self._client_kwargs(),
            )
        return self._client

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

    @staticmethod
    def _api_tools(tools: list[dict]) -> list[dict]:
        """Keep only the keys the Anthropic tools API accepts. kbcode carries
        extra per-tool metadata on the schema (e.g. ``parallel_safe``, #4.3);
        forwarding an unknown key here would make the API reject the request."""
        return [
            {"name": t["name"], "description": t.get("description", ""), "input_schema": t["input_schema"]}
            for t in tools
        ]

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        native = self._to_native(messages)
        system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        base = dict(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system_blocks,
            messages=native,
            tools=self._api_tools(tools),
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

    def stream(self, system: str, messages: list[dict], tools: list[dict], on_text=None) -> LLMResponse:
        native = self._to_native(messages)
        system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        base = dict(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system_blocks,
            messages=native,
            tools=self._api_tools(tools),
        )
        attempts = [
            {**base, "thinking": {"type": "adaptive"}, "output_config": {"effort": self.config.effort}},
            {**base, "thinking": {"type": "adaptive"}},
            base,
        ]

        def do_stream(kwargs):
            with self.client.messages.stream(**kwargs) as stream_ctx:
                for chunk in stream_ctx.text_stream:
                    if on_text and chunk:
                        on_text(chunk)
                return stream_ctx.get_final_message()

        last_exc: Exception | None = None
        final = None
        for kwargs in attempts:
            try:
                final = _with_retry(lambda kw=kwargs: do_stream(kw), self.ui)
                break
            except TypeError as exc:  # SDK too old for this kwarg
                last_exc = exc
        if final is None:
            raise last_exc  # type: ignore[misc]

        text = "".join(b.text for b in final.content if getattr(b, "type", None) == "text")
        tool_calls = [
            ToolCall(b.id, b.name, dict(b.input))
            for b in final.content
            if getattr(b, "type", None) == "tool_use"
        ]
        u = getattr(final, "usage", None)
        usage = {
            "input_tokens": getattr(u, "input_tokens", 0) or 0,
            "output_tokens": getattr(u, "output_tokens", 0) or 0,
        } if u else None
        return LLMResponse(text=text, tool_calls=tool_calls, raw=final.content, usage=usage)

    def list_models(self) -> list[str]:
        return [m.id for m in self.client.models.list()]


# --------------------------------------------------------------------------
# OpenAI-compatible (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, custom)
# --------------------------------------------------------------------------
class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, config: Config, ui=None):
        self.config = config
        self.ui = ui  # optional: receives "retrying…" notices
        self._client = None  # built lazily so `from openai import OpenAI` isn't paid at startup

    @property
    def client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("Missing package. Run: pip install -r requirements.txt") from exc
            self._client = OpenAI(
                api_key=self.config.api_key or "missing",
                base_url=self.config.base_url,
                **self._client_kwargs(),
            )
        return self._client

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

    def stream(self, system: str, messages: list[dict], tools: list[dict], on_text=None) -> LLMResponse:
        native = self._to_native(system, messages)

        def do_stream():
            resp_stream = self.client.chat.completions.create(
                model=self.config.model,
                messages=native,
                tools=self._tools(tools),
                max_tokens=self.config.max_tokens,
                stream=True,
            )
            text_parts: list[str] = []
            tool_acc: dict[int, dict] = {}
            usage = None
            for chunk in resp_stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = chunk_usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    text_parts.append(delta.content)
                    if on_text:
                        on_text(delta.content)
                for tc in getattr(delta, "tool_calls", None) or []:
                    acc = tool_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        acc["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            acc["name"] += tc.function.name
                        if tc.function.arguments:
                            acc["arguments"] += tc.function.arguments
            return "".join(text_parts), tool_acc, usage

        text, tool_acc, u = _with_retry(do_stream, self.ui)

        tool_calls: list[ToolCall] = []
        raw_tool_calls: list[dict] = []
        for idx in sorted(tool_acc):
            acc = tool_acc[idx]
            try:
                args = json.loads(acc["arguments"] or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append(ToolCall(acc["id"], acc["name"], args))
            raw_tool_calls.append(
                {
                    "id": acc["id"],
                    "type": "function",
                    "function": {"name": acc["name"], "arguments": acc["arguments"]},
                }
            )

        raw: dict = {"role": "assistant", "content": text or ""}
        if raw_tool_calls:
            raw["tool_calls"] = raw_tool_calls
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
