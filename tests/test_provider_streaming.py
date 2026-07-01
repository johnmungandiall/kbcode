"""Covers IMPROVEMENTS.md #3.1/#7.1 (streaming responses) with mocked SDK
clients — no live API key needed, so this runs in CI. Verified once against
the real Xiaomi MiMo (OpenAI-compatible) endpoint by hand; these tests lock
the chunk-accumulation logic in permanently.
"""

from __future__ import annotations

import types
from pathlib import Path

from kbcode.config import Config
from kbcode.provider import AnthropicProvider, OpenAICompatibleProvider


def _config(**overrides) -> Config:
    base = dict(project_dir=Path("."), model="test-model", max_tokens=100)
    base.update(overrides)
    return Config(**base)


# --- LLMProvider default stream() fallback --------------------------------


def test_default_stream_falls_back_to_complete_and_delivers_one_chunk():
    from kbcode.provider import LLMProvider, LLMResponse

    class _Basic(LLMProvider):
        def complete(self, system, messages, tools):
            return LLMResponse(text="hello world", tool_calls=[], raw={})

    chunks = []
    resp = _Basic().stream("sys", [], [], on_text=chunks.append)
    assert chunks == ["hello world"]
    assert resp.text == "hello world"


def test_default_stream_skips_on_text_for_empty_response():
    from kbcode.provider import LLMProvider, LLMResponse

    class _Empty(LLMProvider):
        def complete(self, system, messages, tools):
            return LLMResponse(text="", tool_calls=[], raw={})

    chunks = []
    _Empty().stream("sys", [], [], on_text=chunks.append)
    assert chunks == []


# --- OpenAICompatibleProvider.stream() -------------------------------------


def _chunk(content=None, tool_call_deltas=None, usage=None):
    delta = types.SimpleNamespace(content=content, tool_calls=tool_call_deltas)
    choice = types.SimpleNamespace(delta=delta)
    return types.SimpleNamespace(choices=[choice], usage=usage)


def _tc_delta(index, id=None, name=None, arguments=None):
    fn = types.SimpleNamespace(name=name, arguments=arguments) if (name is not None or arguments is not None) else None
    return types.SimpleNamespace(index=index, id=id, function=fn)


class _FakeOpenAIClient:
    def __init__(self, chunks):
        self.chunks = chunks
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        assert kwargs["stream"] is True
        return iter(self.chunks)


def _openai_provider(chunks) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider(_config())
    provider._client = _FakeOpenAIClient(chunks)
    return provider


def test_openai_stream_delivers_text_chunks_incrementally():
    chunks = [_chunk(content="Hello, "), _chunk(content="world!")]
    provider = _openai_provider(chunks)
    seen = []
    resp = provider.stream("sys", [{"role": "user", "content": "hi"}], [], on_text=seen.append)
    assert seen == ["Hello, ", "world!"]
    assert resp.text == "Hello, world!"
    assert resp.tool_calls == []


def test_openai_stream_accumulates_tool_call_arguments_across_chunks():
    chunks = [
        _chunk(tool_call_deltas=[_tc_delta(0, id="call_1", name="read_file", arguments="")]),
        _chunk(tool_call_deltas=[_tc_delta(0, arguments='{"path"')]),
        _chunk(tool_call_deltas=[_tc_delta(0, arguments=': "a.py"}')]),
    ]
    provider = _openai_provider(chunks)
    resp = provider.stream("sys", [{"role": "user", "content": "read a.py"}], [])
    assert len(resp.tool_calls) == 1
    call = resp.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "read_file"
    assert call.input == {"path": "a.py"}
    assert resp.raw["tool_calls"][0]["function"]["arguments"] == '{"path": "a.py"}'


def test_openai_stream_extracts_usage_from_final_chunk():
    usage = types.SimpleNamespace(prompt_tokens=12, completion_tokens=7)
    chunks = [_chunk(content="hi"), _chunk(content=None, usage=usage)]
    provider = _openai_provider(chunks)
    resp = provider.stream("sys", [{"role": "user", "content": "hi"}], [])
    assert resp.usage == {"input_tokens": 12, "output_tokens": 7}


def test_openai_stream_malformed_arguments_json_falls_back_to_empty_dict():
    chunks = [_chunk(tool_call_deltas=[_tc_delta(0, id="call_1", name="x", arguments="not json")])]
    provider = _openai_provider(chunks)
    resp = provider.stream("sys", [], [])
    assert resp.tool_calls[0].input == {}


# --- AnthropicProvider.stream() --------------------------------------------


class _FakeAnthropicStreamCtx:
    def __init__(self, text_chunks, final_message):
        self.text_stream = iter(text_chunks)
        self._final = final_message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._final


class _FakeAnthropicClient:
    def __init__(self, text_chunks, final_message):
        self._ctx = _FakeAnthropicStreamCtx(text_chunks, final_message)
        self.messages = types.SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        return self._ctx


def _content_block(type_, **kw):
    return types.SimpleNamespace(type=type_, **kw)


def test_anthropic_stream_delivers_text_and_final_message():
    final = types.SimpleNamespace(
        content=[_content_block("text", text="Hello world")],
        usage=types.SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    provider = AnthropicProvider(_config())
    provider._client = _FakeAnthropicClient(["Hello ", "world"], final)

    seen = []
    resp = provider.stream("sys", [{"role": "user", "content": "hi"}], [], on_text=seen.append)

    assert seen == ["Hello ", "world"]
    assert resp.text == "Hello world"
    assert resp.usage == {"input_tokens": 10, "output_tokens": 5}
    assert resp.tool_calls == []


def test_anthropic_stream_extracts_tool_use_blocks():
    final = types.SimpleNamespace(
        content=[
            _content_block("text", text=""),
            _content_block("tool_use", id="tu_1", name="read_file", input={"path": "a.py"}),
        ],
        usage=None,
    )
    provider = AnthropicProvider(_config())
    provider._client = _FakeAnthropicClient([], final)

    resp = provider.stream("sys", [{"role": "user", "content": "read a.py"}], [])

    assert resp.tool_calls[0].name == "read_file"
    assert resp.tool_calls[0].input == {"path": "a.py"}
    assert resp.usage is None
