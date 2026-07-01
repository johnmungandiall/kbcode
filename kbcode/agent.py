"""The agent loop (the Claude Code idea): ask the model, run the tools it
requests, feed results back, repeat until it's done.

The loop is provider-agnostic — it only uses the normalized message format
from provider.py, so the same loop drives Claude or any OpenAI-compatible
model (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, ...). All presentation goes
through a TerminalUI (see ui.py), so this file stays about logic, not looks.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import vision_fallback
from .compaction import compact, estimate_tokens
from .modes import DEFAULT_MODE, Mode, builtin_modes
from .pricing import estimate_cost
from .provider import LLMProvider, LLMResponse, ProviderError
from .repair import promote
from .subagents import Subagent
from .tools import Tools
from .ui import TerminalUI

_MAX_STEPS = 50  # safety cap on tool round-trips per user message
_SUBAGENT_MAX_STEPS = 30  # a delegated task gets its own, smaller budget
_MAX_PROMOTED_RECOVERIES = 3  # give up auto-repairing plain-text tool calls after this many/turn

# Context-aware step budget (#4.5): _maybe_compact() only runs once, at the
# start of run() — a single turn with many tool round-trips can still grow
# past compact_threshold before the next turn ever checks again. So the loop
# re-checks after every tool round-trip and compacts mid-turn if needed. If
# even that doesn't help (there isn't enough *history* to summarize — it's
# this turn's own tool output that's large), stop early rather than march
# toward a context-window overflow; _EMERGENCY_STOP_MULTIPLIER sets how much
# further past the threshold that's allowed to happen first.
_EMERGENCY_STOP_MULTIPLIER = 3

# Parallel tool calls (#4.3): only tools that are pure reads (no permission
# prompt, no file mutation, no checkpoint, no shared SQLite connection) are
# safe to run off the main thread. write_file/edit_file/run_command/kb_write/
# remember/recall/save_skill/manage_todos all stay sequential — either
# because ordering matters (edit then run the tests it affects) or because
# they touch state (Permissions' interactive prompt, Checkpoints' once-per-
# turn git snapshot, Memory's sqlite3 connection) that isn't thread-safe to
# share across a pool. WHICH tools are safe is no longer listed here: each
# tool declares `parallel_safe` in its schema (tools/schemas.py) and the set
# is read via self.tools.parallel_safe_tools, so adding a read-only tool
# can't silently fall back to sequential.
#
# run_subagent is a conditional exception: a run of consecutive run_subagent
# calls runs concurrently too, but ONLY when every targeted subagent's own
# `tools:` frontmatter is a subset of that same parallel_safe set (see
# Agent._subagent_parallel_safe / _run_subagents_parallel_batch below) — the
# default `tools: read` does NOT qualify (it includes recall/manage_todos,
# which touch Memory's connection / todos state), so a subagent must be
# authored with an explicit, narrow tool list to opt in. Anything broader
# (any write/exec tool, or `tools: None` = every tool) stays sequential.
_PARALLEL_MAX_WORKERS = 16

# KB lifecycle hooks (the claude-kb idea): distinct from the general,
# user-configurable PreToolUse/PostToolUse/Stop hooks in hooks.py — these two
# are baked-in default agent-loop behavior (not scriptable) that mirror the
# two hooks claude-kb installs into .claude/settings.json: PostToolUse
# (remind to update kb/ after an edit) and Stop (block once on kb/ drift).
_KB_WRITE_TOOLS = {"write_file", "edit_file"}
_KB_REMINDER_SKIP_DIRS = ("/kb/", "/.kbcode/", "/.git/", "/node_modules/")
_KB_REMINDER_SKIP_NAMES = {"agent.md", "memory.md", "readme.md"}


class Agent:
    def __init__(
        self,
        system: str,
        provider: LLMProvider,
        tools: Tools,
        compact_threshold: int = 0,
        ui: TerminalUI | None = None,
        modes: dict[str, Mode] | None = None,
        subagents: dict[str, Subagent] | None = None,
    ):
        self.system = system
        self.provider = provider
        self.tools = tools
        self.compact_threshold = compact_threshold  # tokens; 0 disables auto-compaction
        self.ui = ui or TerminalUI()
        self.modes = modes or builtin_modes()
        self.mode = self.modes[DEFAULT_MODE]
        self.messages: list[dict] = []
        # Persisted transcript for --continue / --resume / /sessions (set by
        # the CLI right after construction, since it needs self.mode.name).
        self.session = None
        # Cumulative token spend this run, for /insights.
        self.usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
        # _record_usage can now be called from multiple subagent threads at
        # once (#4.3 extension — see _run_subagents_parallel_batch).
        self._usage_lock = threading.Lock()
        # Set (per pool worker thread only) by _quiet_dispatch while a
        # subagent runs inside a parallel batch, so _run_subagent suppresses
        # its own inline UI output there — Rich's Live-backed spinner isn't
        # safe to have two open at once. Unset (falsy) on the main thread.
        self._quiet_subagents = threading.local()
        # KB lifecycle hooks state: the reminder fires once per session (like
        # claude-kb's session-scoped marker file); the drift check resets every
        # turn (see run()).
        self._kb_reminder_done = False
        self._kb_touched_this_run = False
        self._kb_drift_checked = False
        # Stop hook state (Claude Code idea): checked once per turn, reset in run().
        self._stop_hook_checked = False
        # Subagent delegation (Claude Code idea): expose it to the tools layer.
        self.subagents = subagents or {}
        self.tools.subagents = self.subagents
        self.tools.delegate = self._run_subagent

    def set_mode(self, name: str) -> bool:
        mode = self.modes.get(name)
        if mode is None:
            return False
        self.mode = mode
        return True

    def _complete(self, system: str, messages: list[dict], schemas: list[dict], on_text=None) -> LLMResponse:
        """Call the provider off the main thread so Esc / Ctrl-C stay responsive.

        A blocking HTTP request holds the socket deep in C, so a pending
        KeyboardInterrupt (raised by the Esc watcher or Ctrl-C) isn't delivered
        until the read returns — which is why Esc felt dead while "thinking…".
        Here the request runs in a daemon worker while the main thread waits in
        short Python-level polls, so the interrupt lands within ~50 ms. The
        orphaned worker just finishes and its result is dropped.

        ``on_text``, if given, switches to the provider's streaming call
        (#3.1/#7.1) and is invoked with each text chunk *from the worker
        thread* as it arrives. Rich's Console has its own internal lock so
        individual prints stay atomic, but the thinking() spinner is a
        Live region redrawn from its own ticker thread — two threads writing
        the terminal at once shred the streamed line. So ui.stream_chunk stops
        the spinner on the first token; after that only the worker thread
        prints. Left as None (the default): one blocking call, spinner intact.
        """
        box: dict = {}
        done = threading.Event()

        def work() -> None:
            try:
                if on_text is not None:
                    box["resp"] = self.provider.stream(system, messages, schemas, on_text=on_text)
                else:
                    box["resp"] = self.provider.complete(system, messages, schemas)
            except BaseException as exc:  # carried over and re-raised on the main thread
                box["err"] = exc
            finally:
                done.set()

        threading.Thread(target=work, daemon=True).start()
        while not done.wait(0.05):
            pass
        if "err" in box:
            raise box["err"]
        return box["resp"]

    def _try_vision_fallback(self, exc: ProviderError) -> bool:
        """When the active model can't accept the attached image (see
        provider._classify's vision hint), describe it with an auxiliary
        vision model instead of failing the turn outright (the Hermes
        auxiliary-vision idea). Mutates the pending user message in place so
        the image isn't resent — and doesn't fail the same way again — on any
        later turn. Returns True if the caller should retry the request.
        """
        if "doesn't support image input" not in str(exc):
            return False
        last = self.messages[-1] if self.messages else None
        if not last or last.get("role") != "user" or not last.get("images"):
            return False
        cfg = getattr(self.provider, "config", None)
        with self.ui.working("describing image with an auxiliary vision model…"):
            description = vision_fallback.describe_images(last["images"], last.get("content") or "", config=cfg)
        if not description:
            return False
        self.ui.notice(
            "This model can't see images directly — described it with an "
            "auxiliary vision model instead.",
            style="yellow",
        )
        note = (
            "\n\n[Image attached — described by an auxiliary vision model, "
            f"since the active model doesn't support image input]\n{description}"
        )
        last["content"] = (last.get("content") or "") + note
        del last["images"]
        return True

    def _dispatch_tool(self, name: str, args: dict) -> tuple[str, bool]:
        """Run one tool call through PreToolUse/PostToolUse hooks (the Claude
        Code idea) around the actual execution — see hooks.py. Every call site
        that would otherwise call ``self.tools.execute`` directly goes through
        here instead, so a configured hook sees every tool call, including
        ones made by a delegated subagent."""
        pre = self.tools.hooks.run("PreToolUse", name, args)
        if pre.blocked:
            return pre.message or f"Tool '{name}' blocked by a PreToolUse hook.", True
        content, is_error = self.tools.execute(name, args)
        post = self.tools.hooks.run("PostToolUse", name, args, tool_output=content, is_error=is_error)
        if post.message:
            content = f"{content}\n\n[hook: {post.message}]"
        return content, is_error

    def _append(self, message: dict) -> None:
        self.messages.append(message)
        if self.session:
            self.session.append(message)

    def _system_for_mode(self) -> str:
        return f"{self.system}\n\n## Current mode: {self.mode.name}\n{self.mode.instructions}"

    def _mode_schemas(self) -> list[dict]:
        return [s for s in self.tools.schemas if self.mode.allows(s["name"])]

    def run(self, user_input: str, images: list[dict] | None = None) -> None:
        self._maybe_compact()
        msg: dict = {"role": "user", "content": user_input}
        if images:  # vision attachments (Alt+V / /image) — see images.py
            msg["images"] = images
        self._append(msg)

        start = time.perf_counter()
        self.ui.turn_started()  # so every spinner this turn can also show a running total
        before = dict(self.usage)
        actions = 0
        promoted_recoveries = 0
        self._kb_touched_this_run = False
        self._kb_drift_checked = False
        self._stop_hook_checked = False
        self.tools.checkpoints.new_turn()
        self.tools.new_turn()

        try:
            for _ in range(_MAX_STEPS):
                self._update_read_budget()
                # Proactive auto-compact before each model call (in case previous
                # tool results or text pushed us over without a mid-turn check yet).
                if self.compact_threshold > 0 and estimate_tokens(self.messages) >= self.compact_threshold:
                    self.compact_now(announce="auto")
                try:
                    with self.ui.thinking():
                        resp = self._complete(
                            self._system_for_mode(), self.messages, self._mode_schemas(),
                            on_text=self.ui.stream_chunk,
                        )
                except ProviderError as exc:
                    if self._try_vision_fallback(exc):
                        continue
                    raise
                if resp.text.strip():
                    self.ui.stream_newline()  # chunks printed raw, with no trailing newline
                self._record_usage(resp.usage)

                self._append(
                    {
                        "role": "assistant",
                        "text": resp.text,
                        "tool_calls": resp.tool_calls,
                        "raw": resp.raw,
                    }
                )

                if not resp.tool_calls:
                    # Note: promoted/cleaned text was already streamed above (raw,
                    # tool-call markup and all) — it isn't re-shown here, since
                    # streaming already showed *something* and re-rendering the
                    # cleaned version would just duplicate it.
                    promoted, _cleaned = promote(resp.text, {s["name"] for s in self._mode_schemas()})
                    if promoted:
                        if promoted_recoveries >= _MAX_PROMOTED_RECOVERIES:
                            self.ui.notice(
                                f"Model kept writing tool calls as plain text after "
                                f"{_MAX_PROMOTED_RECOVERIES} auto-repairs this turn — giving up and "
                                "ending the turn instead of looping further.",
                                style="yellow",
                            )
                            self._turn_summary(start, actions, before)
                            return
                        promoted_recoveries += 1
                        actions += self._run_promoted(promoted)
                        continue
                    if self._kb_drift_feedback():
                        continue
                    if self._stop_hook_feedback():
                        continue
                    self._turn_summary(start, actions, before)
                    return

                # Any preamble text (e.g. "let me check that file") was already
                # streamed above, before the tool calls themselves execute.

                results = []
                calls = resp.tool_calls
                parallel_safe = self.tools.parallel_safe_tools
                i = 0
                while i < len(calls):
                    call = calls[i]
                    if call.name in parallel_safe and i + 1 < len(calls) and calls[i + 1].name in parallel_safe:
                        j = i + 1
                        while j < len(calls) and calls[j].name in parallel_safe:
                            j += 1
                        batch = calls[i:j]
                        results.extend(self._run_parallel_batch(batch))
                        actions += len(batch)
                        i = j
                        continue
                    if (
                        self._is_parallel_subagent_call(call)
                        and i + 1 < len(calls)
                        and self._is_parallel_subagent_call(calls[i + 1])
                    ):
                        j = i + 1
                        while j < len(calls) and self._is_parallel_subagent_call(calls[j]):
                            j += 1
                        batch = calls[i:j]
                        results.extend(self._run_subagents_parallel_batch(batch))
                        actions += len(batch)
                        i = j
                        continue
                    actions += 1
                    self.ui.tool_call(call.name, dict(call.input))
                    if not self.mode.allows(call.name):
                        content, is_error = (
                            f"Tool '{call.name}' is not available in {self.mode.name} mode. "
                            f"Switch to a mode that allows it (e.g. /mode code) or use a read-only tool.",
                            True,
                        )
                    else:
                        with self.ui.tool_running():
                            content, is_error = self._dispatch_tool(call.name, dict(call.input))
                    self.ui.tool_result(content, is_error)
                    content = self._with_kb_reminder(call.name, dict(call.input), content, is_error)
                    results.append({"id": call.id, "content": content, "is_error": is_error})
                    i += 1
                self._append({"role": "tool_results", "results": results})

                if self._compact_mid_turn_or_stop(start, actions, before):
                    return

            self.ui.notice("Stopped: hit the step limit for one request.", style="yellow")
            self._turn_summary(start, actions, before)
        except KeyboardInterrupt:
            self.ui.notice("interrupted.", style="yellow")
            self._turn_summary(start, actions, before)
            raise

    def _run_parallel_batch(self, calls: list) -> list[dict]:
        """Run a run of consecutive read-only tool calls concurrently (#4.3).

        Parallelism only speeds up the *work* — the call/result lines are
        still rendered sequentially afterward, in the model's original order,
        since rich's spinner/console isn't built for concurrent renders.
        """
        allowed = [c for c in calls if self.mode.allows(c.name)]
        outcomes: dict[str, tuple[str, bool]] = {}
        if allowed:
            label = f"running {len(allowed)} tools in parallel"
            with self.ui.working(label):
                with ThreadPoolExecutor(max_workers=min(_PARALLEL_MAX_WORKERS, len(allowed))) as pool:
                    future_to_call = {
                        pool.submit(self._dispatch_tool, c.name, dict(c.input)): c for c in allowed
                    }
                    for future, call in future_to_call.items():
                        outcomes[call.id] = future.result()

        results = []
        for call in calls:
            self.ui.tool_call(call.name, dict(call.input))
            if call.id in outcomes:
                content, is_error = outcomes[call.id]
            else:
                content, is_error = (
                    f"Tool '{call.name}' is not available in {self.mode.name} mode. "
                    f"Switch to a mode that allows it (e.g. /mode code) or use a read-only tool.",
                    True,
                )
            self.ui.tool_result(content, is_error)
            content = self._with_kb_reminder(call.name, dict(call.input), content, is_error)
            results.append({"id": call.id, "content": content, "is_error": is_error})
        return results

    def _quiet_dispatch(self, call) -> tuple[str, bool]:
        """Run one tool call with _run_subagent's inline UI output suppressed
        (see the _quiet_subagents thread-local) — used only inside
        _run_subagents_parallel_batch's pool, so per-call notices/spinners
        don't interleave or fight over TerminalUI's shared status region
        across threads."""
        self._quiet_subagents.on = True
        try:
            return self._dispatch_tool(call.name, dict(call.input))
        finally:
            self._quiet_subagents.on = False

    def _run_subagents_parallel_batch(self, calls: list) -> list[dict]:
        """Run a run of consecutive run_subagent calls concurrently, when
        every one targets a subagent whose tools are a subset of
        parallel_safe_tools (#4.3 extension — see _subagent_parallel_safe).

        Mirrors _run_parallel_batch: parallelize the work, render call/result
        lines afterward in the original order. Still goes through
        _dispatch_tool (not _run_subagent directly), so PreToolUse/PostToolUse
        hooks fire exactly as they do for a sequential run_subagent call.
        """
        allowed = [c for c in calls if self.mode.allows(c.name)]
        outcomes: dict[str, tuple[str, bool]] = {}
        if allowed:
            label = f"delegating to {len(allowed)} subagents in parallel"
            with self.ui.working(label):
                with ThreadPoolExecutor(max_workers=min(_PARALLEL_MAX_WORKERS, len(allowed))) as pool:
                    future_to_call = {
                        pool.submit(self._quiet_dispatch, c): c for c in allowed
                    }
                    for future, call in future_to_call.items():
                        outcomes[call.id] = future.result()

        results = []
        for call in calls:
            agent_name = call.input.get("agent", "?")
            self.ui.notice(f"↳ delegating to subagent '{agent_name}'…", style="cyan")
            self.ui.tool_call(call.name, dict(call.input))
            if call.id in outcomes:
                content, is_error = outcomes[call.id]
            else:
                content, is_error = (
                    f"Tool '{call.name}' is not available in {self.mode.name} mode.",
                    True,
                )
            self.ui.tool_result(content, is_error)
            self.ui.notice(f"↳ subagent '{agent_name}' done.", style="cyan")
            results.append({"id": call.id, "content": content, "is_error": is_error})
        return results

    def _compact_mid_turn_or_stop(self, start: float, actions: int, before: dict) -> bool:
        """Re-check context size after a tool round-trip (not just at the start
        of run()), since a single turn's own tool output can grow past
        compact_threshold before the next turn ever looks again. Compacts if
        that helps; ends the turn early if it doesn't. Returns True if the
        turn was ended.
        """
        if self.compact_threshold <= 0:
            return False
        if estimate_tokens(self.messages) < self.compact_threshold:
            return False
        self.compact_now(announce="auto")
        if estimate_tokens(self.messages) < self.compact_threshold * _EMERGENCY_STOP_MULTIPLIER:
            return False
        self.ui.notice(
            "Stopped: this turn's own tool output grew too large even after compacting "
            "earlier history. Ask a narrower question, or continue in a fresh message.",
            style="yellow",
        )
        self._turn_summary(start, actions, before)
        return True

    def _run_promoted(self, promoted: list[tuple[str, dict]]) -> int:
        """Run tool calls the model wrote as plain text, then feed results back.

        We don't have provider-native tool ids for these (the model never used
        the tool interface), so the results go back as a plain ``user`` turn —
        which keeps the message list valid for replay on any provider — with a
        nudge to use the proper format next time. Returns the action count.
        """
        self.ui.notice(
            "recovered tool call(s) the model wrote as plain text — "
            "running them and nudging it back to the proper format.",
            style="yellow",
        )
        feedback = [
            "Note: you wrote those tool calls as plain text instead of using the "
            "tool-call interface. I ran them for you this time — please use the "
            "proper tool-call format from now on. Results:"
        ]
        for name, args in promoted:
            self.ui.tool_call(name, dict(args))
            if not self.mode.allows(name):
                content, is_error = (
                    f"Tool '{name}' is not available in {self.mode.name} mode.",
                    True,
                )
            else:
                with self.ui.tool_running():
                    content, is_error = self._dispatch_tool(name, dict(args))
            self.ui.tool_result(content, is_error)
            content = self._with_kb_reminder(name, dict(args), content, is_error)
            feedback.append(f"\n## {name} [{'error' if is_error else 'ok'}]\n{content}")
        self._append({"role": "user", "content": "\n".join(feedback)})
        return len(promoted)

    def _with_kb_reminder(self, name: str, args: dict, content: str, is_error: bool) -> str:
        """PostToolUse idea (claude-kb): after a successful edit outside kb/,
        remind the model (once per session) to keep the affected kb/ note in
        sync — instead of relying on it to remember the auto-maintain rule."""
        if is_error or name not in _KB_WRITE_TOOLS:
            return content
        path_arg = args.get("path")
        if not path_arg:
            return content
        # Track "touched" independently of whether the reminder already fired
        # this session — the drift check (below) must still run every turn.
        self._kb_touched_this_run = True
        if self._kb_reminder_done:
            return content
        norm = "/" + path_arg.replace("\\", "/").lower().lstrip("/")
        base = norm.rsplit("/", 1)[-1]
        if any(d in norm for d in _KB_REMINDER_SKIP_DIRS) or base in _KB_REMINDER_SKIP_NAMES:
            return content
        self._kb_reminder_done = True
        reminder = (
            f"[kb reminder] You just changed `{path_arg}`. Before finishing this turn, "
            "update the affected kb/ note(s) — refresh any path:line pointers and changed "
            "behavior — so the knowledge base doesn't drift from the code."
        )
        self.ui.notice(reminder, style="yellow")
        return f"{content}\n\n{reminder}"

    def _kb_drift_feedback(self) -> bool:
        """Stop idea (claude-kb): before a turn that touched files actually
        ends, verify kb/ pointers still resolve. Nudges back into the loop
        ONCE per turn on drift (never loops, and never fires on turns that
        didn't touch files) so the model fixes it before finishing.
        """
        if self._kb_drift_checked or not self._kb_touched_this_run:
            return False
        self._kb_drift_checked = True
        problems = self.tools.kb.check_pointers(self.tools.root)
        if not problems:
            return False
        detail = "\n".join(f"- {p}" for p in problems)
        self.ui.notice("kb/ drift detected before finishing — asking the model to fix it.", style="yellow")
        self._append(
            {
                "role": "user",
                "content": (
                    "KB drift detected before you finish: some kb/ pointers no longer resolve.\n"
                    f"{detail}\n"
                    "Fix the affected kb/ note(s) now (or run kb tools to relocate the pointer), "
                    "then finish."
                ),
            }
        )
        return True

    def _stop_hook_feedback(self) -> bool:
        """Stop hook (the Claude Code idea): let a configured script veto
        ending the turn — e.g. to demand a missing test run. Fires once per
        turn (never loops) even if the hook keeps blocking.
        """
        if self._stop_hook_checked:
            return False
        self._stop_hook_checked = True
        outcome = self.tools.hooks.run("Stop", "Stop", {})
        if not outcome.blocked:
            return False
        self.ui.notice("Stop hook blocked the turn from ending — asking the model to continue.", style="yellow")
        self._append(
            {"role": "user", "content": outcome.message or "Continue: a Stop hook blocked ending this turn."}
        )
        return True

    def _turn_summary(self, start: float, actions: int, before: dict) -> None:
        self.ui.turn_summary(
            time.perf_counter() - start,
            actions,
            self.usage["input_tokens"] - before["input_tokens"],
            self.usage["output_tokens"] - before["output_tokens"],
        )
        if self.session:
            self.session.record_usage(dict(self.usage))

    def context_tokens(self) -> int:
        return estimate_tokens(self.messages)

    def _record_usage(self, usage: dict | None) -> None:
        with self._usage_lock:
            self.usage["requests"] += 1
            if usage:
                self.usage["input_tokens"] += usage.get("input_tokens", 0)
                self.usage["output_tokens"] += usage.get("output_tokens", 0)

    def insights(self) -> dict:
        """Usage/cost summary for this run (Hermes' /insights, adapted)."""
        u = self.usage
        total = u["input_tokens"] + u["output_tokens"]
        return {
            "model": self.provider.config.model if hasattr(self.provider, "config") else "?",
            "requests": u["requests"],
            "input_tokens": u["input_tokens"],
            "output_tokens": u["output_tokens"],
            "total_tokens": total,
            "context_tokens": self.context_tokens(),
            "cost": estimate_cost(
                getattr(getattr(self.provider, "config", None), "model", ""),
                u["input_tokens"],
                u["output_tokens"],
            ),
        }

    def _subagent_parallel_safe(self, name: str) -> bool:
        """A subagent is eligible for concurrent dispatch (#4.3 extension) only
        if it's authored with an explicit, narrow ``tools:`` list that is a
        subset of the schema-declared parallel_safe set (tools/schemas.py) —
        NOT the mode-level READ group, which also includes recall/manage_todos
        (Memory's sqlite3 connection / todos state aren't thread-safe to
        share). The default ``tools: read`` frontmatter does NOT qualify; an
        author must deliberately narrow it (e.g. ``tools: read_file,
        search_code, kb_read``) to opt in. Unknown subagent name or
        ``tools: None`` ("every tool") is never eligible."""
        sub = self.subagents.get(name)
        if sub is None or sub.tools is None:
            return False
        return sub.tools <= self.tools.parallel_safe_tools

    def _is_parallel_subagent_call(self, call) -> bool:
        return call.name == "run_subagent" and self._subagent_parallel_safe(
            call.input.get("agent", "")
        )

    def _run_subagent(self, name: str, task: str) -> tuple[str, bool]:
        """Run a delegated task in its own context window; return (summary, is_error).

        When called from inside a parallel subagent batch (see
        _run_subagents_parallel_batch / _quiet_dispatch), the per-thread
        _quiet_subagents flag is set, so this suppresses its own inline UI
        output — Rich's Live-backed spinner isn't safe to have two open at
        once — and the caller renders a summary afterward instead.
        """
        quiet = getattr(self._quiet_subagents, "on", False)
        sub = self.subagents.get(name)
        if sub is None:
            avail = ", ".join(self.subagents) or "(none defined)"
            return f"Unknown subagent '{name}'. Available: {avail}.", True

        system = f"{self.system}\n\n## You are the '{name}' subagent\n{sub.instructions}"
        schemas = [
            s for s in self.tools.schemas
            if s["name"] != "run_subagent" and sub.allows(s["name"])
        ]
        messages: list[dict] = [{"role": "user", "content": task}]
        if not quiet:
            self.ui.notice(f"↳ delegating to subagent '{name}'…", style="cyan")

        for _ in range(_SUBAGENT_MAX_STEPS):
            resp = self._complete(system, messages, schemas)
            self._record_usage(resp.usage)
            messages.append(
                {"role": "assistant", "text": resp.text, "tool_calls": resp.tool_calls, "raw": resp.raw}
            )
            if not resp.tool_calls:
                promoted, _ = promote(resp.text, {s["name"] for s in schemas})
                if promoted:
                    feedback = [
                        "Note: you wrote those tool calls as plain text. I ran them "
                        "for you — please use the proper tool-call format. Results:"
                    ]
                    for tname, targs in promoted:
                        if not quiet:
                            self.ui.tool_call(f"{name}:{tname}", dict(targs))
                        if not sub.allows(tname):
                            content, is_error = (
                                f"Tool '{tname}' is not allowed for the '{name}' subagent.",
                                True,
                            )
                        elif quiet:
                            content, is_error = self._dispatch_tool(tname, dict(targs))
                        else:
                            with self.ui.tool_running():
                                content, is_error = self._dispatch_tool(tname, dict(targs))
                        if not quiet:
                            self.ui.tool_result(content, is_error)
                        feedback.append(f"\n## {tname} [{'error' if is_error else 'ok'}]\n{content}")
                    messages.append({"role": "user", "content": "\n".join(feedback)})
                    continue
                if not quiet:
                    self.ui.notice(f"↳ subagent '{name}' done.", style="cyan")
                return resp.text or "(subagent returned no text)", False

            results = []
            calls = resp.tool_calls
            parallel_safe = self.tools.parallel_safe_tools
            i = 0
            while i < len(calls):
                call = calls[i]
                # A run of 2+ consecutive read-safe calls runs concurrently —
                # the same #4.3 batch Agent.run does at the top level, now
                # scoped to a subagent turn too (via _run_subagent_parallel_batch).
                # Critical for slow models: a code-explorer can now read many
                # files/directories in one model round-trip instead of one-by-one.
                # See also the narrow tools: list + instructions in code-explorer.md.
                if call.name in parallel_safe and i + 1 < len(calls) and calls[i + 1].name in parallel_safe:
                    j = i + 1
                    while j < len(calls) and calls[j].name in parallel_safe:
                        j += 1
                    results.extend(self._run_subagent_parallel_batch(sub, name, calls[i:j], quiet))
                    i = j
                    continue
                if not quiet:
                    self.ui.tool_call(f"{name}:{call.name}", dict(call.input))
                if call.name == "run_subagent":
                    content, is_error = "Subagents cannot spawn other subagents.", True
                elif not sub.allows(call.name):
                    content, is_error = (
                        f"Tool '{call.name}' is not allowed for the '{name}' subagent.",
                        True,
                    )
                elif quiet:
                    content, is_error = self._dispatch_tool(call.name, dict(call.input))
                else:
                    with self.ui.tool_running():
                        content, is_error = self._dispatch_tool(call.name, dict(call.input))
                if not quiet:
                    self.ui.tool_result(content, is_error)
                results.append({"id": call.id, "content": content, "is_error": is_error})
                i += 1
            messages.append({"role": "tool_results", "results": results})

        return f"Subagent '{name}' hit its step limit before finishing.", True

    def _run_subagent_parallel_batch(self, sub: Subagent, name: str, calls: list, quiet: bool) -> list[dict]:
        """Run a run of consecutive read-safe tool calls from *inside* a
        subagent concurrently — the same #4.3 batch _run_parallel_batch does
        at the top level, scoped to one subagent turn. Only parallel_safe
        tools reach here (no writes / Memory / todos touched off-thread), so
        it carries the same thread-safety guarantee. Call/result lines render
        afterward in the model's original order.

        When ``quiet`` (this subagent is itself running inside a parallel
        subagent batch — see _run_subagents_parallel_batch), it must NOT open
        its own ui.working() spinner: a second Rich Live region can't coexist
        with the parent batch's. It runs the pool silently instead, like the
        rest of the quiet path.
        """
        allowed = [c for c in calls if sub.allows(c.name)]
        outcomes: dict[str, tuple[str, bool]] = {}
        if allowed:
            def _pool() -> None:
                with ThreadPoolExecutor(max_workers=min(_PARALLEL_MAX_WORKERS, len(allowed))) as pool:
                    future_to_call = {
                        pool.submit(self._dispatch_tool, c.name, dict(c.input)): c for c in allowed
                    }
                    for future, call in future_to_call.items():
                        outcomes[call.id] = future.result()

            if quiet:
                _pool()
            else:
                with self.ui.working(f"{name}: running {len(allowed)} reads in parallel"):
                    _pool()

        results = []
        for call in calls:
            if not quiet:
                self.ui.tool_call(f"{name}:{call.name}", dict(call.input))
            if call.id in outcomes:
                content, is_error = outcomes[call.id]
            else:
                content, is_error = (
                    f"Tool '{call.name}' is not allowed for the '{name}' subagent.",
                    True,
                )
            if not quiet:
                self.ui.tool_result(content, is_error)
            results.append({"id": call.id, "content": content, "is_error": is_error})
        return results

    def reset(self) -> None:
        self.messages.clear()
        self._kb_reminder_done = False
        if self.session:
            self.session.reset_marker()

    def close(self) -> None:
        """Flush a final usage snapshot to the transcript. Call once at process
        exit (and before replacing this Agent with a freshly built one)."""
        if self.session:
            self.session.record_usage(dict(self.usage))

    def _maybe_compact(self) -> None:
        """Auto-summarize old turns once the transcript crosses the threshold."""
        if self.compact_threshold <= 0:
            return
        if estimate_tokens(self.messages) < self.compact_threshold:
            return
        self.compact_now(announce="auto")

    def _update_read_budget(self) -> None:
        """Narrow read_file's result size as context fills up (#4.2), instead
        of always allowing the fixed default — so one huge file read can't
        single-handedly blow past the compaction threshold. No-op (fixed
        default) when auto-compaction is off, since there's no budget to speak of.
        """
        if self.compact_threshold <= 0:
            self.tools.context_budget_chars = None
            return
        remaining_tokens = max(0, self.compact_threshold - estimate_tokens(self.messages))
        self.tools.context_budget_chars = remaining_tokens * 4  # ~4 chars/token, matches estimate_tokens

    def compact_now(self, announce: str = "manual") -> bool:
        """Summarize the middle of the conversation. Returns True if it compacted."""
        before = estimate_tokens(self.messages)
        with self.ui.working("🗜️  summarizing earlier conversation…"):
            new_messages, summary = compact(self.messages, self.provider)
        if summary is None:
            if announce == "manual":
                self.ui.notice("Not enough conversation to compact yet.")
            return False
        self.messages = new_messages
        after = estimate_tokens(self.messages)
        self.ui.notice(f"🗜️  compacted earlier conversation (~{before:,} → ~{after:,} tokens).")
        return True
