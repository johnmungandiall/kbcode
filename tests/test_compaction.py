from kbcode import compaction
from kbcode.provider import LLMResponse


class _FakeProvider:
    """Minimal stand-in for LLMProvider.complete(), used by compact()'s summarizer."""

    def __init__(self, summary: str = "recap of the middle turns"):
        self.summary = summary
        self.calls = 0

    def complete(self, system, messages, tools):
        self.calls += 1
        return LLMResponse(text=self.summary, tool_calls=[], raw={})


def _user(content):
    return {"role": "user", "content": content}


def _assistant(text="ok"):
    return {"role": "assistant", "text": text, "tool_calls": [], "raw": {}}


def test_estimate_tokens_grows_with_content_length():
    small = [_user("hi")]
    big = [_user("hi " * 1000)]
    assert compaction.estimate_tokens(big) > compaction.estimate_tokens(small)


def test_estimate_tokens_counts_images_as_flat_cost_not_base64_length():
    huge_base64 = "A" * 200_000
    with_image = [{"role": "user", "content": "look", "images": [{"media_type": "image/png", "data": huge_base64}]}]
    without_image = [{"role": "user", "content": "look"}]
    # a screenshot should look like ~1300 tokens, not tens of thousands
    delta = compaction.estimate_tokens(with_image) - compaction.estimate_tokens(without_image)
    assert 1000 < delta < 2000


def test_compact_returns_unchanged_when_not_enough_exchanges():
    messages = [_user("hello"), _assistant("hi there")]
    provider = _FakeProvider()
    new_messages, summary = compaction.compact(messages, provider, keep_head=1, keep_tail=2)
    assert new_messages == messages
    assert summary is None
    assert provider.calls == 0


def test_compact_summarizes_middle_and_preserves_head_and_tail():
    messages = [
        _user("task: build a widget"),
        _assistant("ok, starting"),
        _user("use blue"),
        _assistant("done, blue widget"),
        _user("now add a border"),
        _assistant("added a border"),
        _user("looks great, ship it"),
        _assistant("shipped"),
    ]
    provider = _FakeProvider(summary="user wants a blue widget with a border")
    new_messages, summary = compaction.compact(messages, provider, keep_head=1, keep_tail=2)

    assert summary == "user wants a blue widget with a border"
    assert provider.calls == 1
    # first exchange (head) is untouched
    assert new_messages[0] == messages[0]
    assert new_messages[1] == messages[1]
    # the recap is spliced onto the first kept tail user turn
    tail_start = [i for i, m in enumerate(new_messages) if m["role"] == "user"][-2]
    assert "user wants a blue widget with a border" in new_messages[tail_start]["content"]
    assert "now add a border" in new_messages[tail_start]["content"]
    # the very last exchange is preserved verbatim after the recap
    assert new_messages[-1] == messages[-1]


def test_compact_preserves_user_assistant_alternation():
    messages = [
        _user("t1"), _assistant("a1"),
        _user("t2"), _assistant("a2"),
        _user("t3"), _assistant("a3"),
        _user("t4"), _assistant("a4"),
    ]
    provider = _FakeProvider()
    new_messages, _ = compaction.compact(messages, provider, keep_head=1, keep_tail=2)
    roles = [m["role"] for m in new_messages]
    for i in range(0, len(roles) - 1, 2):
        assert roles[i] == "user"
        assert roles[i + 1] == "assistant"


def test_summarize_failure_does_not_raise():
    class _BrokenProvider:
        def complete(self, system, messages, tools):
            raise RuntimeError("network down")

    summary = compaction._summarize(_BrokenProvider(), "some transcript")
    assert "summary failed" in summary
