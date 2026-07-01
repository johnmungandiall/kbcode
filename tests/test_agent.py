"""Mock-provider integration tests for the agent loop: tool dispatch, the
plain-text tool-call repair path, and auto-compaction — the three behaviors
IMPROVEMENTS.md #1.2 asks for. A FakeProvider stands in for the real SDKs so
these run offline and instantly.
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from kbcode.agent import _MAX_PROMOTED_RECOVERIES, Agent
from kbcode.config import Config
from kbcode.knowledge_base import KnowledgeBase
from kbcode.memory import Memory
from kbcode.permissions import Permissions
from kbcode.provider import LLMResponse, ToolCall
from kbcode.subagents import Subagent
from kbcode.tools import Tools
from kbcode.ui import TerminalUI


class FakeProvider:
    """Scripted provider: pops queued responses for real turns; auto-answers
    the compaction summarizer (identified by its empty tool-schema list)."""

    def __init__(self, responses: list[LLMResponse], summary: str = "recap of earlier work"):
        self.responses = list(responses)
        self.summary = summary
        self.calls: list[dict] = []
        self.stream_call_count = 0

    def complete(self, system, messages, tools):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        if not tools:  # compaction.py always calls with tools=[]
            return LLMResponse(text=self.summary, tool_calls=[], raw={})
        if not self.responses:
            raise AssertionError("FakeProvider ran out of scripted responses")
        return self.responses.pop(0)

    def stream(self, system, messages, tools, on_text=None):
        # Mirrors LLMProvider's default stream() fallback: deliver the whole
        # text as one chunk, so the real agent-loop streaming call site still
        # exercises normally against this fake.
        self.stream_call_count += 1
        resp = self.complete(system, messages, tools)
        if on_text and resp.text:
            on_text(resp.text)
        return resp


class _KeyedProvider:
    """Like FakeProvider, but for tests that dispatch >1 subagent concurrently:
    FakeProvider's plain `responses.pop(0)` queue isn't safe to share across
    threads, and even if it were, pop order between racing threads is
    nondeterministic. This instead replies based on which subagent's system
    prompt is asking (a plain dict lookup, not a shared mutable queue), so
    each subagent gets its own deterministic scripted answer regardless of
    thread interleaving. Calls whose system prompt matches none of the
    subagent keys (i.e. the main agent's own turns) pop from `main_replies`,
    which only the single main thread ever touches.
    """

    def __init__(self, subagent_replies: dict[str, LLMResponse], main_replies: list[LLMResponse]):
        self.subagent_replies = subagent_replies
        self.main_replies = list(main_replies)
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def complete(self, system, messages, tools):
        with self._lock:
            self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        for key, resp in self.subagent_replies.items():
            if key in system:
                return resp
        return self.main_replies.pop(0)

    def stream(self, system, messages, tools, on_text=None):
        resp = self.complete(system, messages, tools)
        if on_text and resp.text:
            on_text(resp.text)
        return resp


def _call(name: str, args: dict) -> ToolCall:
    return ToolCall(id=str(uuid.uuid4()), name=name, input=args)


def _final(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], raw={})


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def _assistant(text: str = "ok") -> dict:
    return {"role": "assistant", "text": text, "tool_calls": [], "raw": {}}


def _make_agent(tmp_path, provider, compact_threshold: int = 0, hooks: dict | None = None) -> tuple[Agent, Tools]:
    project = tmp_path / "project"
    project.mkdir()
    config = Config(project_dir=project, compact_threshold=compact_threshold, hooks=hooks or {})
    config.ensure_dirs()
    memory = Memory(config.memory_db)
    kb = KnowledgeBase(config.kb_dir)
    perm = Permissions(auto_approve=True)  # skip interactive approval prompts
    tools = Tools(config, memory, kb, perm)
    ui = TerminalUI()
    agent = Agent("You are a helpful coding agent.", provider, tools, compact_threshold=compact_threshold, ui=ui)
    return agent, tools


# --- tool dispatch ------------------------------------------------------


def test_structured_tool_call_writes_file_and_completes(tmp_path):
    provider = FakeProvider(
        [
            LLMResponse(
                text="Writing the file now.",
                tool_calls=[_call("write_file", {"path": "hello.txt", "content": "hi there"})],
                raw={},
            ),
            _final("Done, I created hello.txt."),
        ]
    )
    agent, tools = _make_agent(tmp_path, provider)
    agent.run("create hello.txt with 'hi there'")

    written = tools.root / "hello.txt"
    assert written.read_text(encoding="utf-8") == "hi there"
    # two model turns: the tool-call turn and the final answer
    assert len(provider.calls) == 2
    # tool results were fed back as a tool_results message
    assert any(m["role"] == "tool_results" for m in agent.messages)


def test_unknown_tool_gets_repair_guidance_not_a_crash(tmp_path):
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[_call("delete_file", {"path": "x"})], raw={}),
            _final("ok, giving up on that"),
        ]
    )
    agent, _tools = _make_agent(tmp_path, provider)
    agent.run("delete a file")

    tool_results = [m for m in agent.messages if m["role"] == "tool_results"]
    assert len(tool_results) == 1
    result = tool_results[0]["results"][0]
    assert result["is_error"] is True
    assert "Unknown tool" in result["content"]


def test_disallowed_tool_in_current_mode_is_blocked(tmp_path):
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[_call("write_file", {"path": "x.txt", "content": "y"})], raw={}),
            _final("noted, read-only"),
        ]
    )
    agent, tools = _make_agent(tmp_path, provider)
    assert agent.set_mode("ask")  # read-only built-in mode
    agent.run("please write a file")

    assert not (tools.root / "x.txt").exists()
    tool_results = [m for m in agent.messages if m["role"] == "tool_results"]
    result = tool_results[0]["results"][0]
    assert result["is_error"] is True
    assert "not available in ask mode" in result["content"]


# --- streaming (#3.1/#7.1) --------------------------------------------------


def test_run_uses_the_streaming_entry_point(tmp_path):
    provider = FakeProvider([_final("hi there")])
    agent, _tools = _make_agent(tmp_path, provider)
    agent.run("hello")
    assert provider.stream_call_count == 1


def test_run_streams_text_through_ui_stream_chunk(tmp_path, monkeypatch):
    provider = FakeProvider([_final("streamed answer")])
    agent, _tools = _make_agent(tmp_path, provider)
    seen: list[str] = []
    monkeypatch.setattr(agent.ui, "stream_chunk", lambda t: seen.append(t))
    agent.run("say something")
    assert "".join(seen) == "streamed answer"


def test_run_calls_stream_newline_only_when_text_was_streamed(tmp_path, monkeypatch):
    provider = FakeProvider(
        [LLMResponse(text="", tool_calls=[_call("read_file", {"path": "a.txt"})], raw={}), _final("done")]
    )
    agent, tools = _make_agent(tmp_path, provider)
    (tools.root / "a.txt").write_text("x", encoding="utf-8")
    newline_calls = []
    monkeypatch.setattr(agent.ui, "stream_newline", lambda: newline_calls.append(1))
    agent.run("read the file")
    # first response had empty text (tool-call only) -> no newline for that step;
    # second response ("done") had text -> one newline.
    assert newline_calls == [1]


def test_complete_without_on_text_does_not_stream(tmp_path):
    provider = FakeProvider([_final("hi")])
    agent, _tools = _make_agent(tmp_path, provider)
    resp = agent._complete("sys", [{"role": "user", "content": "hi"}], [{"name": "dummy"}])
    assert provider.stream_call_count == 0
    assert resp.text == "hi"


def test_complete_with_on_text_streams(tmp_path):
    provider = FakeProvider([_final("hi")])
    agent, _tools = _make_agent(tmp_path, provider)
    seen: list[str] = []
    resp = agent._complete(
        "sys", [{"role": "user", "content": "hi"}], [{"name": "dummy"}], on_text=seen.append
    )
    assert provider.stream_call_count == 1
    assert seen == ["hi"]
    assert resp.text == "hi"


def test_subagent_delegate_does_not_stream(tmp_path):
    provider = FakeProvider([_final("subagent answer")])
    agent, _tools = _make_agent(tmp_path, provider)
    sub = Subagent(name="helper", description="test helper", instructions="Answer briefly.", tools=None)
    summary, is_error = agent._run_subagent("helper", "do a thing")
    # not registered -> should fail fast without ever touching the provider
    assert is_error is True
    assert provider.stream_call_count == 0

    agent.subagents["helper"] = sub
    summary, is_error = agent._run_subagent("helper", "do a thing")
    assert is_error is False
    assert summary == "subagent answer"
    assert provider.stream_call_count == 0  # subagents never stream


# --- promoted (plain-text) tool calls ------------------------------------


def test_plain_text_tool_call_is_promoted_and_executed(tmp_path):
    plain_text_call = '[write_file]\n{"path": "note.txt", "content": "from plain text"}'
    provider = FakeProvider(
        [
            LLMResponse(text=plain_text_call, tool_calls=[], raw={}),
            _final("Wrote it."),
        ]
    )
    agent, tools = _make_agent(tmp_path, provider)
    agent.run("write note.txt")

    written = tools.root / "note.txt"
    assert written.read_text(encoding="utf-8") == "from plain text"
    # the promoted result comes back as a plain user turn (no native tool id)
    feedback = [m for m in agent.messages if m["role"] == "user" and "wrote those tool calls as plain text" in m["content"]]
    assert len(feedback) == 1


def test_repeated_plain_text_tool_calls_give_up_after_max_recoveries(tmp_path):
    plain_text_call = '[list_dir]\n{"path": "."}'
    # the model never switches to the real tool-call interface
    responses = [LLMResponse(text=plain_text_call, tool_calls=[], raw={}) for _ in range(10)]
    provider = FakeProvider(responses)
    agent, _tools = _make_agent(tmp_path, provider)
    agent.run("please list files")

    # _MAX_PROMOTED_RECOVERIES successful recoveries, then one more response
    # that hits the cap and ends the turn instead of looping to _MAX_STEPS.
    assert len(provider.calls) == _MAX_PROMOTED_RECOVERIES + 1
    feedback = [
        m for m in agent.messages
        if m["role"] == "user" and "wrote those tool calls as plain text" in m.get("content", "")
    ]
    assert len(feedback) == _MAX_PROMOTED_RECOVERIES


def test_plain_prose_with_no_tool_shape_is_not_promoted(tmp_path):
    provider = FakeProvider([_final("Just a plain answer, no tools needed.")])
    agent, _tools = _make_agent(tmp_path, provider)
    agent.run("what is 2+2?")

    assert len(provider.calls) == 1
    assert not any(
        m["role"] == "user" and "wrote those tool calls as plain text" in m.get("content", "")
        for m in agent.messages
    )


# --- auto-compaction ------------------------------------------------------


def test_compaction_triggers_once_threshold_and_history_are_enough(tmp_path):
    # 5 scripted turns, each a plain final answer (no tools) so every turn
    # ends in exactly one user + one assistant message.
    provider = FakeProvider([_final(f"answer {i}") for i in range(5)])
    agent, _tools = _make_agent(tmp_path, provider, compact_threshold=1)

    for i in range(5):
        agent.run(f"question {i}")

    # compact() needs keep_head(1) + keep_tail(2) + 1 = 4 prior exchanges
    # before it will fire; the 5th run() call is the first one that has that
    # many already in self.messages, so its _maybe_compact() should compact.
    recapped = [
        m for m in agent.messages
        if m["role"] == "user" and "Recap of earlier conversation" in m["content"]
    ]
    assert len(recapped) == 1
    assert "recap of earlier work" in recapped[0]["content"]


def test_compaction_does_not_trigger_below_threshold(tmp_path):
    provider = FakeProvider([_final(f"answer {i}") for i in range(3)])
    agent, _tools = _make_agent(tmp_path, provider, compact_threshold=1_000_000)

    for i in range(3):
        agent.run(f"question {i}")

    assert not any("Recap of earlier conversation" in m.get("content", "") for m in agent.messages if m["role"] == "user")


# --- context-aware step budget (mid-turn compaction / emergency stop) ----


def test_compacts_mid_turn_when_threshold_crossed_and_history_available(tmp_path):
    provider = FakeProvider([], summary="short recap")
    agent, _tools = _make_agent(tmp_path, provider, compact_threshold=100)
    for i in range(4):  # enough exchanges for compact()'s defaults (needs >= 4)
        agent.messages.append(_user(f"question {i}"))
        agent.messages.append(_assistant(f"answer {i}"))

    stopped = agent._compact_mid_turn_or_stop(time.perf_counter(), 0, dict(agent.usage))

    assert stopped is False  # compaction brought it back under the emergency multiplier
    assert any(
        "Recap of earlier conversation" in m.get("content", "")
        for m in agent.messages if m["role"] == "user"
    )


def test_stops_turn_when_no_history_to_compact_and_still_over_threshold(tmp_path):
    provider = FakeProvider([])
    agent, _tools = _make_agent(tmp_path, provider, compact_threshold=10)
    # A single huge in-progress exchange — nothing compact() can summarize away
    # (it needs several prior exchanges), so compaction can't help here.
    agent.messages.append(_user("question " + "x" * 5000))

    stopped = agent._compact_mid_turn_or_stop(time.perf_counter(), 0, dict(agent.usage))

    assert stopped is True


def test_mid_turn_check_is_a_noop_below_threshold(tmp_path):
    provider = FakeProvider([])
    agent, _tools = _make_agent(tmp_path, provider, compact_threshold=1_000_000)
    agent.messages.append(_user("small question"))
    assert agent._compact_mid_turn_or_stop(time.perf_counter(), 0, dict(agent.usage)) is False


# --- parallel tool calls (#4.3) --------------------------------------------


def test_multiple_read_calls_run_as_a_parallel_batch(tmp_path):
    provider = FakeProvider(
        [
            LLMResponse(
                text="reading both files",
                tool_calls=[
                    _call("read_file", {"path": "a.txt"}),
                    _call("read_file", {"path": "b.txt"}),
                ],
                raw={},
            ),
            _final("both read"),
        ]
    )
    agent, tools = _make_agent(tmp_path, provider)
    (tools.root / "a.txt").write_text("content A", encoding="utf-8")
    (tools.root / "b.txt").write_text("content B", encoding="utf-8")

    agent.run("read both files")

    tool_results = [m for m in agent.messages if m["role"] == "tool_results"]
    assert len(tool_results) == 1
    results = tool_results[0]["results"]
    assert len(results) == 2
    contents = [r["content"] for r in results]
    assert any("content A" in c for c in contents)
    assert any("content B" in c for c in contents)
    assert all(not r["is_error"] for r in results)


def test_mixed_batch_runs_reads_in_parallel_and_write_sequentially(tmp_path):
    provider = FakeProvider(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    _call("read_file", {"path": "a.txt"}),
                    _call("read_file", {"path": "b.txt"}),
                    _call("write_file", {"path": "c.txt", "content": "written"}),
                ],
                raw={},
            ),
            _final("done"),
        ]
    )
    agent, tools = _make_agent(tmp_path, provider)
    (tools.root / "a.txt").write_text("A", encoding="utf-8")
    (tools.root / "b.txt").write_text("B", encoding="utf-8")

    agent.run("do stuff")

    assert (tools.root / "c.txt").read_text(encoding="utf-8") == "written"
    tool_results = [m for m in agent.messages if m["role"] == "tool_results"][0]["results"]
    assert len(tool_results) == 3
    assert all(not r["is_error"] for r in tool_results)


def test_parallel_batch_respects_mode_restrictions(tmp_path):
    from kbcode.modes import Mode

    provider = FakeProvider(
        [
            LLMResponse(
                text="",
                tool_calls=[_call("read_file", {"path": "a.txt"}), _call("list_dir", {"path": "."})],
                raw={},
            ),
            _final("done"),
        ]
    )
    agent, tools = _make_agent(tmp_path, provider)
    (tools.root / "a.txt").write_text("A", encoding="utf-8")
    restricted = Mode("restricted", "test", "test", frozenset({"read_file"}))
    agent.modes["restricted"] = restricted
    assert agent.set_mode("restricted")

    agent.run("go")

    tool_results = [m for m in agent.messages if m["role"] == "tool_results"][0]["results"]
    errors = [r for r in tool_results if r["is_error"]]
    oks = [r for r in tool_results if not r["is_error"]]
    assert len(errors) == 1
    assert len(oks) == 1
    assert "not available in restricted mode" in errors[0]["content"]


def test_single_parallel_safe_call_still_works(tmp_path):
    # a lone read_file (no adjacent parallel-safe call) takes the sequential
    # path, but must behave identically.
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[_call("read_file", {"path": "a.txt"})], raw={}),
            _final("done"),
        ]
    )
    agent, tools = _make_agent(tmp_path, provider)
    (tools.root / "a.txt").write_text("solo content", encoding="utf-8")

    agent.run("read it")

    tool_results = [m for m in agent.messages if m["role"] == "tool_results"][0]["results"]
    assert len(tool_results) == 1
    assert "solo content" in tool_results[0]["content"]


def test_parallel_safe_tools_derived_from_schema_flag(tmp_path):
    # #6: the parallel set is read off each tool's `parallel_safe` schema flag,
    # not a hardcoded list — so it can't drift from the actual read-only tools.
    provider = FakeProvider([])
    _agent, tools = _make_agent(tmp_path, provider)
    assert tools.parallel_safe_tools == {
        "read_file", "list_dir", "search_code", "kb_read", "kb_search", "web_search",
    }
    flagged = {s["name"] for s in tools.schemas if s.get("parallel_safe")}
    assert tools.parallel_safe_tools == flagged
    # mutating tools (write/run) must never be marked safe.
    assert "write_file" not in tools.parallel_safe_tools
    assert "run_command" not in tools.parallel_safe_tools


# --- concurrent run_subagent dispatch (#4.3 extension) ---------------------


def test_parallel_subagent_batch_dispatches_concurrently_with_correct_ordering(tmp_path):
    outer = LLMResponse(
        text="",
        tool_calls=[
            _call("run_subagent", {"agent": "a", "task": "task a"}),
            _call("run_subagent", {"agent": "b", "task": "task b"}),
        ],
        raw={},
    )
    provider = _KeyedProvider(
        subagent_replies={
            "'a' subagent": _final("answer from a"),
            "'b' subagent": _final("answer from b"),
        },
        main_replies=[outer, _final("done")],
    )
    agent, tools = _make_agent(tmp_path, provider)
    agent.subagents["a"] = Subagent(
        name="a", description="a", instructions="Answer briefly.", tools=frozenset({"read_file"})
    )
    agent.subagents["b"] = Subagent(
        name="b", description="b", instructions="Answer briefly.", tools=frozenset({"read_file"})
    )

    agent.run("delegate to both")

    tool_results = [m for m in agent.messages if m["role"] == "tool_results"][0]["results"]
    assert len(tool_results) == 2
    assert [r["is_error"] for r in tool_results] == [False, False]
    # results must line up with the ORIGINAL call order/ids, not swapped —
    # this is the regression the outcomes-dict-keyed-by-call.id pattern guards.
    assert tool_results[0]["id"] == outer.tool_calls[0].id
    assert tool_results[1]["id"] == outer.tool_calls[1].id
    assert tool_results[0]["content"] == "answer from a"
    assert tool_results[1]["content"] == "answer from b"


def test_mixed_eligibility_subagent_batch_falls_back_to_sequential(tmp_path, monkeypatch):
    outer = LLMResponse(
        text="",
        tool_calls=[
            _call("run_subagent", {"agent": "safe", "task": "t1"}),
            _call("run_subagent", {"agent": "unsafe", "task": "t2"}),
        ],
        raw={},
    )
    provider = FakeProvider([outer, _final("safe answer"), _final("unsafe answer"), _final("done")])
    agent, tools = _make_agent(tmp_path, provider)
    agent.subagents["safe"] = Subagent(
        name="safe", description="", instructions="Answer briefly.", tools=frozenset({"read_file"})
    )
    agent.subagents["unsafe"] = Subagent(
        name="unsafe", description="", instructions="Answer briefly.", tools=None  # every tool
    )

    def _boom(self, calls):
        raise AssertionError("should not batch when a targeted subagent isn't parallel-safe")

    monkeypatch.setattr(Agent, "_run_subagents_parallel_batch", _boom)

    agent.run("delegate to both")

    tool_results = [m for m in agent.messages if m["role"] == "tool_results"][0]["results"]
    assert len(tool_results) == 2
    assert [r["is_error"] for r in tool_results] == [False, False]


def test_subagent_parallel_safe_edge_cases(tmp_path):
    from kbcode.modes import READ

    provider = FakeProvider([])
    agent, tools = _make_agent(tmp_path, provider)
    safe_set = tools.parallel_safe_tools

    assert agent._subagent_parallel_safe("does-not-exist") is False

    agent.subagents["none_tools"] = Subagent(name="none_tools", description="", instructions="x", tools=None)
    assert agent._subagent_parallel_safe("none_tools") is False

    agent.subagents["default_read"] = Subagent(
        name="default_read", description="", instructions="x", tools=frozenset(READ)
    )
    assert agent._subagent_parallel_safe("default_read") is False  # includes recall/manage_todos

    agent.subagents["narrow"] = Subagent(
        name="narrow", description="", instructions="x", tools=frozenset({"read_file", "search_code"})
    )
    assert agent._subagent_parallel_safe("narrow") is True

    agent.subagents["exact"] = Subagent(name="exact", description="", instructions="x", tools=frozenset(safe_set))
    assert agent._subagent_parallel_safe("exact") is True

    agent.subagents["mixed"] = Subagent(
        name="mixed", description="", instructions="x", tools=frozenset({"read_file", "write_file"})
    )
    assert agent._subagent_parallel_safe("mixed") is False


def test_record_usage_thread_safe_under_concurrency(tmp_path):
    provider = FakeProvider([])
    agent, _tools = _make_agent(tmp_path, provider)

    n = 50
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(agent._record_usage, {"input_tokens": 1, "output_tokens": 2}) for _ in range(n)
        ]
        for f in futures:
            f.result()

    assert agent.usage["requests"] == n
    assert agent.usage["input_tokens"] == n
    assert agent.usage["output_tokens"] == 2 * n


# --- token-budget-aware tool results (#4.2) --------------------------------


def test_update_read_budget_is_none_when_compaction_disabled(tmp_path):
    provider = FakeProvider([])
    agent, tools = _make_agent(tmp_path, provider, compact_threshold=0)
    agent.messages.append(_user("hello"))
    agent._update_read_budget()
    assert tools.context_budget_chars is None


def test_update_read_budget_shrinks_as_messages_grow(tmp_path):
    provider = FakeProvider([])
    agent, tools = _make_agent(tmp_path, provider, compact_threshold=1000)
    agent._update_read_budget()
    empty_budget = tools.context_budget_chars

    agent.messages.append(_user("x" * 2000))
    agent._update_read_budget()
    fuller_budget = tools.context_budget_chars

    assert empty_budget is not None and fuller_budget is not None
    assert fuller_budget < empty_budget


def test_update_read_budget_never_goes_negative(tmp_path):
    provider = FakeProvider([])
    agent, tools = _make_agent(tmp_path, provider, compact_threshold=10)
    agent.messages.append(_user("x" * 5000))  # already far past the threshold
    agent._update_read_budget()
    assert tools.context_budget_chars == 0


def test_disabled_compaction_never_triggers(tmp_path):
    provider = FakeProvider([_final(f"answer {i}") for i in range(5)])
    agent, _tools = _make_agent(tmp_path, provider, compact_threshold=0)

    for i in range(5):
        agent.run(f"question {i}")

    assert not any("Recap of earlier conversation" in m.get("content", "") for m in agent.messages if m["role"] == "user")


# --- hooks (PreToolUse/PostToolUse/Stop, see kbcode/hooks.py) --------------


def _blocking_hook_command(tmp_path, message: str) -> str:
    script = tmp_path / "block_hook.py"
    script.write_text(f"import sys; sys.stderr.write({message!r}); sys.exit(2)", encoding="utf-8")
    return f'"{sys.executable}" "{script}"'


def test_pretooluse_hook_blocks_call_without_running_the_tool(tmp_path):
    cmd = _blocking_hook_command(tmp_path, "blocked: no writes allowed")
    hooks = {"PreToolUse": [{"matcher": "write_file", "hooks": [{"type": "command", "command": cmd}]}]}
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[_call("write_file", {"path": "hello.txt", "content": "hi"})], raw={}),
            _final("ok, I won't write it."),
        ]
    )
    agent, tools = _make_agent(tmp_path, provider, hooks=hooks)
    agent.run("create hello.txt")

    assert not (tools.root / "hello.txt").exists()
    tool_results = [m for m in agent.messages if m["role"] == "tool_results"]
    result = tool_results[0]["results"][0]
    assert result["is_error"] is True
    assert "blocked: no writes allowed" in result["content"]


def test_no_hooks_configured_leaves_tool_dispatch_unaffected(tmp_path):
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[_call("write_file", {"path": "hello.txt", "content": "hi"})], raw={}),
            _final("done."),
        ]
    )
    agent, tools = _make_agent(tmp_path, provider)
    agent.run("create hello.txt")
    assert (tools.root / "hello.txt").read_text(encoding="utf-8") == "hi"
