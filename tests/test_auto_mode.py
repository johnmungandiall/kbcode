"""Auto permission mode + its supporting cast: the ask/auto toggle, the
builtin autopilot/fixer subagents, mid-turn type-ahead delivery, the
"convince the model to continue" nudge, and the malformed-tool-call markers.
"""

from __future__ import annotations

import uuid

from kbcode.agent import Agent
from kbcode.config import Config
from kbcode.interrupt import TypeAhead
from kbcode.knowledge_base import KnowledgeBase
from kbcode.memory import Memory
from kbcode.permissions import Permissions
from kbcode.provider import LLMResponse, ToolCall, _parse_tool_args
from kbcode.subagents import builtin_subagents
from kbcode.tools import Tools
from kbcode.ui import TerminalUI


class FakeProvider:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, system, messages, tools):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        if not tools:  # compaction summarizer
            return LLMResponse(text="recap", tool_calls=[], raw={})
        return self.responses.pop(0)

    def stream(self, system, messages, tools, on_text=None, on_tool=None, on_tool_args=None, on_thinking=None):
        resp = self.complete(system, messages, tools)
        if on_text and resp.text:
            on_text(resp.text)
        return resp


def _call(name: str, args: dict) -> ToolCall:
    return ToolCall(id=str(uuid.uuid4()), name=name, input=args)


def _final(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], raw={})


def _make_agent(tmp_path, provider, *, auto: bool = True, subagents=None) -> tuple[Agent, Tools]:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    config = Config(project_dir=project, hooks={})
    config.ensure_dirs()
    memory = Memory(config.memory_db)
    kb = KnowledgeBase(config.kb_dir)
    perm = Permissions(auto_approve=auto)
    tools = Tools(config, memory, kb, perm)
    agent = Agent("system prompt.", provider, tools, ui=TerminalUI(), subagents=subagents)
    return agent, tools


# --- Permissions.toggle_mode ------------------------------------------------


def test_permissions_toggle_flips_between_ask_and_auto():
    perm = Permissions()
    assert perm.mode == "ask"
    assert perm.toggle_mode() == "auto"
    assert perm.auto_approve is True
    assert perm.check("write_file", "anything") is True  # never prompts in auto
    assert perm.toggle_mode() == "ask"
    assert perm.auto_approve is False


# --- builtin subagents --------------------------------------------------------


def test_builtin_subagents_include_autopilot_and_fixer_with_every_tool():
    subs = builtin_subagents()
    assert set(subs) == {"autopilot", "fixer"}
    assert subs["autopilot"].tools is None  # every tool
    assert subs["fixer"].tools is None
    assert subs["autopilot"].allows("run_command")


# --- auto-mode system note ----------------------------------------------------


def test_system_prompt_carries_auto_note_only_in_auto_mode(tmp_path):
    agent, tools = _make_agent(tmp_path, FakeProvider([]), auto=True)
    assert "Auto mode (active)" in agent._system_for_mode()
    tools.perm.auto_approve = False
    assert "Auto mode (active)" not in agent._system_for_mode()


# --- TypeAhead ----------------------------------------------------------------


def test_typeahead_collects_lines_and_edits_with_backspace():
    ta = TypeAhead()
    for ch in "fix bugX":
        ta.feed(ch)
    ta.feed("\x08")  # backspace the X
    assert ta.snapshot() == ("fix bug", 0)
    ta.feed("\r")
    assert ta.snapshot() == ("", 1)
    assert ta.pop_lines() == ["fix bug"]
    assert ta.pop_lines() == []


def test_typeahead_take_all_text_drains_lines_and_partial_buffer():
    ta = TypeAhead()
    for ch in "first":
        ta.feed(ch)
    ta.feed("\n")
    for ch in "second half":
        ta.feed(ch)
    assert ta.take_all_text() == "first\nsecond half"
    assert ta.snapshot() == ("", 0)


# --- mid-turn delivery ----------------------------------------------------------


def test_user_notes_are_delivered_on_the_last_tool_result(tmp_path):
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[_call("list_dir", {"path": "."})], raw={}),
            _final("all done."),
        ]
    )
    agent, _ = _make_agent(tmp_path, provider)
    agent.poll_user_notes = lambda: ["also update the README"]
    agent.run("do something")
    tool_results = [m for m in agent.messages if m.get("role") == "tool_results"]
    content = tool_results[-1]["results"][-1]["content"]
    assert "also update the README" in content
    assert "urgent" in content


# --- convince-the-model nudge -----------------------------------------------------


def test_auto_mode_pushes_back_when_the_model_asks_a_question(tmp_path):
    provider = FakeProvider([_final("Shall I proceed with the change?"), _final("Done.")])
    agent, _ = _make_agent(tmp_path, provider, auto=True)
    agent.run("refactor the module")
    # The nudge went back in as a user message and the model was called again.
    nudges = [m for m in agent.messages if m.get("role") == "user" and "AUTO mode" in str(m.get("content", ""))]
    assert len(nudges) == 1
    assert len(provider.calls) == 2


def test_ask_mode_does_not_push_back_on_questions(tmp_path):
    provider = FakeProvider([_final("Shall I proceed with the change?")])
    agent, _ = _make_agent(tmp_path, provider, auto=False)
    agent.run("refactor the module")
    assert len(provider.calls) == 1  # turn just ends


# --- auto-fix (fixer subagent) ------------------------------------------------------


def test_auto_fix_runs_fixer_after_an_editing_turn_in_auto_mode(tmp_path):
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[_call("write_file", {"path": "a.txt", "content": "hi"})], raw={}),
            _final("File written."),
            _final("Everything looks correct."),  # the fixer subagent's own reply
            _final("Wrapped up."),  # main model reacting to the fixer report
        ]
    )
    agent, _ = _make_agent(tmp_path, provider, auto=True, subagents=builtin_subagents())
    agent.run("write a.txt")
    fixer_reports = [
        m for m in agent.messages
        if m.get("role") == "user" and "[fixer subagent report" in str(m.get("content", ""))
    ]
    assert len(fixer_reports) == 1


def test_auto_fix_stays_quiet_in_ask_mode(tmp_path):
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[_call("write_file", {"path": "a.txt", "content": "hi"})], raw={}),
            _final("File written."),
        ]
    )
    # auto=True perms would prompt in ask mode; use auto=False but pre-allow the tool.
    agent, tools = _make_agent(tmp_path, provider, auto=False, subagents=builtin_subagents())
    tools.perm.always_allow.add("write_file")
    agent.run("write a.txt")
    assert not any("[fixer subagent report" in str(m.get("content", "")) for m in agent.messages)


# --- malformed / truncated tool-call args ----------------------------------------------


def test_parse_tool_args_marks_malformed_and_cut_off_json():
    assert _parse_tool_args('{"path": "a.py"}') == {"path": "a.py"}
    assert _parse_tool_args("not json") == {"_malformed_args": "not json"}
    cut = _parse_tool_args('{"path": "a.py", "content": "abc', truncated=True)
    assert cut["_args_cut_off"] is True
    assert _parse_tool_args("", truncated=True) == {"_args_cut_off": True}


def test_repair_explains_cut_off_write_calls_and_coaches_splitting(tmp_path):
    agent, tools = _make_agent(tmp_path, FakeProvider([]))
    msg, is_error = tools.execute("write_file", {"_malformed_args": '{"path": "x', "_args_cut_off": True})
    assert is_error
    assert "cut off" in msg
    assert "comfortably small" in msg  # the split-the-write coaching
    msg2, is_error2 = tools.execute("write_file", {})
    assert is_error2
    assert "missing required argument" in msg2
