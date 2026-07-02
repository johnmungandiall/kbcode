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


class _FakeToolCall:
    def __init__(self, id_):
        self.id = id_
        self.name = "search_code"
        self.input = {"pattern": "x"}


def _runaway_single_exchange(pairs: int) -> list[dict]:
    """One user turn followed by `pairs` (assistant tool_call, tool_results)
    rounds — the shape of a turn that hit the step limit. Exactly what the old
    exchange-level compaction could not shrink."""
    messages: list[dict] = [_user("search the whole project for expiry handling")]
    for i in range(pairs):
        messages.append({"role": "assistant", "text": "", "tool_calls": [_FakeToolCall(f"c{i}")], "raw": {}})
        messages.append(
            {"role": "tool_results", "results": [{"id": f"c{i}", "content": "big match output " * 40, "is_error": False}]}
        )
    return messages


def test_compact_shrinks_a_single_runaway_exchange():
    messages = _runaway_single_exchange(pairs=20)
    provider = _FakeProvider(summary="ran 20 searches across the project")
    before = compaction.estimate_tokens(messages)

    new_messages, summary = compaction.compact(messages, provider)

    assert summary == "ran 20 searches across the project"
    assert provider.calls == 1
    assert compaction.estimate_tokens(new_messages) < before  # actually reduced
    # the user turn survives, with the recap folded in
    assert new_messages[0]["role"] == "user"
    assert "search the whole project" in new_messages[0]["content"]
    assert "ran 20 searches across the project" in new_messages[0]["content"]
    # the most recent work is kept verbatim
    assert new_messages[-1] == messages[-1]


def test_runaway_compaction_preserves_alternation_and_tool_pairing():
    messages = _runaway_single_exchange(pairs=20)
    new_messages, _ = compaction.compact(messages, _FakeProvider())

    # the kept tail must start on an assistant turn (valid right after the user
    # turn — never a dangling tool_results)
    assert new_messages[1]["role"] == "assistant"
    # every tool_results is immediately preceded by an assistant that made a
    # tool call (no orphaned results after dropping the middle pairs)
    for i, m in enumerate(new_messages):
        if m["role"] == "tool_results":
            assert new_messages[i - 1]["role"] == "assistant"
            assert new_messages[i - 1]["tool_calls"]


def test_compact_leaves_small_last_exchange_untouched():
    # a normal short last exchange must not be summarized away
    messages = _runaway_single_exchange(pairs=2)  # only 4 body messages
    new_messages, summary = compaction.compact(messages, _FakeProvider())
    assert new_messages == messages
    assert summary is None


def test_summarize_failure_does_not_raise():
    class _BrokenProvider:
        def complete(self, system, messages, tools):
            raise RuntimeError("network down")

    summary = compaction._summarize(_BrokenProvider(), "some transcript")
    assert "summary failed" in summary


# --- pass 0: trim old tool outputs (no LLM call) ---------------------------


def _exchanges_with_bulky_tool_output(n_exchanges: int, bulk_chars: int = 5000) -> list[dict]:
    messages: list[dict] = []
    for i in range(n_exchanges):
        messages.append(_user(f"task {i}"))
        messages.append({"role": "assistant", "text": "", "tool_calls": [_FakeToolCall(f"c{i}")], "raw": {}})
        messages.append(
            {"role": "tool_results", "results": [{"id": f"c{i}", "content": "x" * bulk_chars, "is_error": False}]}
        )
        messages.append(_assistant(f"done {i}"))
    return messages


def test_trim_shrinks_old_tool_results_but_protects_the_tail():
    messages = _exchanges_with_bulky_tool_output(4)
    new_messages, trimmed = compaction._trim_old_tool_results(messages, keep_tail=2)

    assert trimmed == 2  # the two old exchanges' bulky results
    # old results are trimmed with the marker...
    assert "kbcode trimmed" in new_messages[2]["results"][0]["content"]
    assert len(new_messages[2]["results"][0]["content"]) < 1000
    # ...the protected tail is byte-identical
    assert new_messages[-6:] == messages[-6:]
    # the input list was not mutated (session transcripts keep the originals)
    assert len(messages[2]["results"][0]["content"]) == 5000
    # nothing added/removed/reordered → pairing + alternation trivially intact
    assert [m["role"] for m in new_messages] == [m["role"] for m in messages]


def test_trim_alone_satisfying_threshold_skips_the_llm_summary():
    messages = _exchanges_with_bulky_tool_output(4)
    provider = _FakeProvider()
    threshold = compaction.estimate_tokens(messages)  # trimming will land well under

    new_messages, summary = compaction.compact(messages, provider, threshold=threshold)

    assert provider.calls == 0  # pass 0 was enough — no model round-trip
    assert "trimmed 2 old tool outputs" in summary
    assert compaction.estimate_tokens(new_messages) < threshold


def test_trim_feeds_into_summary_passes_when_still_over_threshold():
    messages = _exchanges_with_bulky_tool_output(6)
    provider = _FakeProvider(summary="recap")

    new_messages, summary = compaction.compact(messages, provider, threshold=1)

    assert provider.calls >= 1  # still over the (absurdly low) threshold → summarized
    assert "trimmed" in summary and "recap" in summary
    assert compaction.estimate_tokens(new_messages) < compaction.estimate_tokens(messages)


def test_trim_ignores_small_results_and_empty_history():
    small = [_user("t"), {"role": "tool_results", "results": [{"id": "c", "content": "tiny", "is_error": False}]}]
    unchanged, trimmed = compaction._trim_old_tool_results(small, keep_tail=0)
    assert trimmed == 0 and unchanged == small
    assert compaction._trim_old_tool_results([], keep_tail=2) == ([], 0)
