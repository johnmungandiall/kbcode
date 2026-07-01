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

from . import vision_fallback
from .compaction import compact, estimate_tokens
from .modes import DEFAULT_MODE, Mode, builtin_modes
from .pricing import estimate_cost
from .provider import LLMProvider, ProviderError
from .repair import promote
from .subagents import Subagent
from .tools import Tools
from .ui import TerminalUI

_MAX_STEPS = 50  # safety cap on tool round-trips per user message
_SUBAGENT_MAX_STEPS = 30  # a delegated task gets its own, smaller budget

# KB lifecycle hooks (the claude-kb idea): kbcode has no external hook-config
# file, so the two hooks claude-kb installs into .claude/settings.json —
# PostToolUse (remind to update kb/ after an edit) and Stop (block once on kb/
# drift) — are baked in here as default agent-loop behavior instead.
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
        # KB lifecycle hooks state: the reminder fires once per session (like
        # claude-kb's session-scoped marker file); the drift check resets every
        # turn (see run()).
        self._kb_reminder_done = False
        self._kb_touched_this_run = False
        self._kb_drift_checked = False
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

    def _complete(self, system: str, messages: list[dict], schemas: list[dict]):
        """Call the provider off the main thread so Esc / Ctrl-C stay responsive.

        A blocking HTTP request holds the socket deep in C, so a pending
        KeyboardInterrupt (raised by the Esc watcher or Ctrl-C) isn't delivered
        until the read returns — which is why Esc felt dead while "thinking…".
        Here the request runs in a daemon worker while the main thread waits in
        short Python-level polls, so the interrupt lands within ~50 ms. The
        orphaned worker just finishes and its result is dropped.
        """
        box: dict = {}
        done = threading.Event()

        def work() -> None:
            try:
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
        before = dict(self.usage)
        actions = 0
        self._kb_touched_this_run = False
        self._kb_drift_checked = False
        self.tools.checkpoints.new_turn()

        for _ in range(_MAX_STEPS):
            try:
                with self.ui.thinking():
                    resp = self._complete(
                        self._system_for_mode(), self.messages, self._mode_schemas()
                    )
            except ProviderError as exc:
                if self._try_vision_fallback(exc):
                    continue
                raise
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
                promoted, cleaned = promote(resp.text, {s["name"] for s in self._mode_schemas()})
                if promoted:
                    if cleaned:
                        self.ui.assistant_text(cleaned)
                    actions += self._run_promoted(promoted)
                    continue
                self.ui.assistant_text(resp.text)
                if self._kb_drift_feedback():
                    continue
                self._turn_summary(start, actions, before)
                return

            self.ui.assistant_text(resp.text)

            results = []
            for call in resp.tool_calls:
                actions += 1
                self.ui.tool_call(call.name, dict(call.input))
                if not self.mode.allows(call.name):
                    content, is_error = (
                        f"Tool '{call.name}' is not available in {self.mode.name} mode. "
                        f"Switch to a mode that allows it (e.g. /mode code) or use a read-only tool.",
                        True,
                    )
                else:
                    content, is_error = self.tools.execute(call.name, dict(call.input))
                self.ui.tool_result(content, is_error)
                content = self._with_kb_reminder(call.name, dict(call.input), content, is_error)
                results.append({"id": call.id, "content": content, "is_error": is_error})
            self._append({"role": "tool_results", "results": results})

        self.ui.notice("Stopped: hit the step limit for one request.", style="yellow")
        self._turn_summary(start, actions, before)

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
                content, is_error = self.tools.execute(name, dict(args))
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

    def _run_subagent(self, name: str, task: str) -> tuple[str, bool]:
        """Run a delegated task in its own context window; return (summary, is_error)."""
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
                        self.ui.tool_call(f"{name}:{tname}", dict(targs))
                        if not sub.allows(tname):
                            content, is_error = (
                                f"Tool '{tname}' is not allowed for the '{name}' subagent.",
                                True,
                            )
                        else:
                            content, is_error = self.tools.execute(tname, dict(targs))
                        self.ui.tool_result(content, is_error)
                        feedback.append(f"\n## {tname} [{'error' if is_error else 'ok'}]\n{content}")
                    messages.append({"role": "user", "content": "\n".join(feedback)})
                    continue
                self.ui.notice(f"↳ subagent '{name}' done.", style="cyan")
                return resp.text or "(subagent returned no text)", False

            results = []
            for call in resp.tool_calls:
                self.ui.tool_call(f"{name}:{call.name}", dict(call.input))
                if call.name == "run_subagent":
                    content, is_error = "Subagents cannot spawn other subagents.", True
                elif not sub.allows(call.name):
                    content, is_error = (
                        f"Tool '{call.name}' is not allowed for the '{name}' subagent.",
                        True,
                    )
                else:
                    content, is_error = self.tools.execute(call.name, dict(call.input))
                self.ui.tool_result(content, is_error)
                results.append({"id": call.id, "content": content, "is_error": is_error})
            messages.append({"role": "tool_results", "results": results})

        return f"Subagent '{name}' hit its step limit before finishing.", True

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
