"""Prompt-cache breakpoints on the Anthropic path.

The system-prompt breakpoint already covered tools+system (render order is
tools -> system -> messages); these tests lock in the message-level
breakpoints: the newest user-role native messages get one cache_control
marker on their last content block, assistant ``raw`` blocks are never
touched, and markers never accumulate into the stored normalized messages
(the API rejects more than 4 breakpoints per request).
"""

from __future__ import annotations

from pathlib import Path

from kbcode.config import Config
from kbcode.provider import AnthropicProvider


def _provider() -> AnthropicProvider:
    return AnthropicProvider(Config(project_dir=Path("."), model="m", max_tokens=10))


def _normalized_convo() -> list[dict]:
    return [
        {"role": "user", "content": "read a.py"},
        {"role": "assistant", "text": "", "tool_calls": [], "raw": [{"type": "text", "text": "ok"}]},
        {
            "role": "tool_results",
            "results": [
                {"id": "tu_1", "content": "file contents", "is_error": False},
                {"id": "tu_2", "content": "more", "is_error": False},
            ],
        },
        {"role": "user", "content": "now edit it"},
    ]


def _count_markers(native: list[dict]) -> int:
    n = 0
    for m in native:
        if isinstance(m["content"], list):
            n += sum(1 for b in m["content"] if isinstance(b, dict) and "cache_control" in b)
    return n


def test_breakpoints_mark_last_block_of_newest_user_messages():
    p = _provider()
    native = p._add_cache_breakpoints(p._to_native(_normalized_convo()))
    # The trailing user text message is converted to a marked text block...
    last = native[-1]
    assert last["role"] == "user"
    assert last["content"][-1] == {
        "type": "text", "text": "now edit it", "cache_control": {"type": "ephemeral"},
    }
    # ...the tool_results user message gets a marker on its LAST block only...
    tool_results = native[2]
    assert tool_results["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in tool_results["content"][0]
    # ...and the oldest user message uses up the third (last) breakpoint.
    assert native[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert _count_markers(native) == 3


def test_breakpoints_never_touch_assistant_raw():
    p = _provider()
    msgs = _normalized_convo()
    native = p._add_cache_breakpoints(p._to_native(msgs))
    assert native[1]["role"] == "assistant"
    assert all("cache_control" not in b for b in native[1]["content"])
    # The stored raw blocks are replayed losslessly on the next request.
    assert msgs[1]["raw"] == [{"type": "text", "text": "ok"}]


def test_breakpoints_cap_at_three_and_pick_the_newest():
    p = _provider()
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(6)]
    native = p._add_cache_breakpoints(p._to_native(msgs))
    assert _count_markers(native) == 3
    # newest three marked, oldest three untouched (still plain strings)
    for m in native[:3]:
        assert isinstance(m["content"], str)
    for m in native[3:]:
        assert m["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_breakpoints_never_accumulate_into_stored_messages():
    # Agent.messages is normalized state reused for every request; if markers
    # leaked into it, requests would eventually carry >4 breakpoints (an API
    # error). _to_native builds user-role dicts fresh, so a second request
    # sees exactly the same marker count as the first.
    p = _provider()
    msgs = _normalized_convo()
    first = p._add_cache_breakpoints(p._to_native(msgs))
    second = p._add_cache_breakpoints(p._to_native(msgs))
    assert _count_markers(first) == _count_markers(second) == 3
    assert "cache_control" not in repr(msgs)


def test_breakpoints_skip_empty_user_messages():
    p = _provider()
    msgs = [
        {"role": "user", "content": "real question"},
        {"role": "user", "content": "   "},  # empty text block would be an API error
    ]
    native = p._add_cache_breakpoints(p._to_native(msgs))
    assert isinstance(native[1]["content"], str)  # left alone
    assert native[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
