# Context management — compaction, the product's own kb/ feature, KB hooks.

Context stays cheap two ways. Note: this describes **kbcode the product's**
built-in knowledge-base feature (`knowledge_base.py`) for its end users — the
same mechanism this repo's own `kb/` tree (what you're reading now) dogfoods.

## Compaction
When `estimate_tokens(messages)` (`kbcode/compaction.py:49`) crosses
`compact_threshold`, `compact()` (`kbcode/compaction.py:241`) runs **three
passes** and returns `(messages, None)` only if none reduced anything:
0. `_trim_old_tool_results()` (`kbcode/compaction.py:82`) — free, no LLM call:
   truncate tool_results over ~800 chars to their first `_TRIM_KEEP_CHARS`
   (600) + a "[... kbcode trimmed N chars ...]" marker, everywhere EXCEPT the
   last `keep_tail` exchanges. Never mutates the input list (transcripts keep
   the originals). `compact()` takes a `threshold` kwarg (passed by
   `compact_now`, = `compact_threshold`); if trimming alone lands the estimate
   under `threshold * 0.8`, the summarize passes are skipped entirely — no
   model round-trip.
1. `_compact_exchanges()` (`kbcode/compaction.py:156`) — the original strategy:
   summarize the *middle exchanges* into one recap (`_summarize`,
   `kbcode/compaction.py:125`, `_render`, `kbcode/compaction.py:125`) spliced onto the
   first kept tail turn, protecting the first + last exchanges.
2. `_compact_within_last_exchange()` (`kbcode/compaction.py:194`) — shrink a single
   runaway exchange from the inside (one user turn + many assistant/tool_results
   pairs, e.g. a turn that hit the step limit). Pass 1 *can't* touch this — it
   always protects the most recent exchange, which is the bloated one — so
   before this pass `/compact` looked dead after a step-limit stop. Keeps the
   user turn + last `keep_tail_msgs` (8) messages, summarizes the churn between,
   folds the recap into the user turn. Cuts on an assistant boundary and drops
   only whole (assistant, tool_results) pairs, preserving tool-id pairing +
   alternation (see [[providers]], [[gotchas]]).

Upstream of all passes, `Agent._fit_to_budget()` (called from
`_dispatch_tool`) caps any single tool result at half the tokens left before
auto-compaction (~4 chars/token, 8k-char floor) — one huge read/search can't
blow the window in a single step.

All passes preserve the alternation invariant (pass 0 trivially — nothing is
added, removed, or reordered). Auto-triggered in
`Agent._maybe_compact()` (`kbcode/agent.py:863`) and mid-turn by
`_compact_mid_turn_or_stop()` (`kbcode/agent.py:508`); manual via `/compact` ->
`Agent.compact_now()` (`kbcode/agent.py:883`).

## Knowledge base (product feature)
`KnowledgeBase` (`kbcode/knowledge_base.py:175`) holds `kb/` notes loaded into the
system prompt (`kbcode/prompts.py:43` `build_system_prompt`) so the agent doesn't
re-scan files; `read_all()` (`kbcode/knowledge_base.py:205`). `check_pointers()`
(`/kb-check`) and `fix_pointers()` (`/kb-check --fix`) walk ALL notes including
subfolders via `_all_note_files()` (dot-folders like `.history` skipped) and
skip non-file matches — `_is_pointer_candidate()` rejects placeholders, URLs,
and IP:port / host:port shapes like `0.0.0.0:8000` (a live session once burned
a ~150k-token turn "fixing" that false drift). Relocation anchors on code
symbols from the note line: `_anchors` orders snake_case/called tokens before
bare capitalized words, and `_relocate` matches case-insensitively, trying
every anchor at the definition stage before calls, then bare mentions.
Note versioning: a content-changing `write_note()` first snapshots the old
version into `kb/.history/`; `/kb-undo <note>` -> `restore_note()` puts it back
(repeat to step further back).
Scaffolded starter templates (`_TEMPLATES` + `AGENT_MD_TEMPLATE`) open with an
explicit "unbuilt KB ≠ empty project" warning so a model seeing fresh templates
checks the real files (repo_map / list) instead of declaring the project empty.
Onboarding: `is_scaffold()` (`kbcode/knowledge_base.py:282`) is True while every
note is still an untouched template; the REPL then prints a "type /init" hint at
startup and after `/open` (`_kb_hint_if_unbuilt`, `kbcode/repl.py:221`), and the
`/init` chat command runs the canned `_BUILD_KB_PROMPT` (`kbcode/repl.py:206`)
that scans the code and fills the notes in, then refreshes the LIVE agent's
system prompt via `cli._system_prompt()` (split out of `_build_agent`) so the
new notes take effect without a restart. `is_scaffold()` doubles as the
built/not-built flag surfaced in the banner, `/status` (`kb built` /
`not built — /init`) and at the top of `/kb`.

## KB lifecycle hooks (agent.py — baked-in default, no `.claude/settings.json`
equivalent inside kbcode itself)
`Agent._with_kb_reminder()` (`kbcode/agent.py:564`) is the PostToolUse equivalent —
after a successful `write_file`/`edit_file` outside `kb/`/`.kbcode/`/`.git/`/
`node_modules/` and the top-level docs, it appends a once-per-TURN reminder
(`_kb_reminder_done`, reset in `run()` like the drift flags, `kbcode/agent.py:115`)
nudging the model to update the matching note — so every code-editing turn gets
the nudge, not just the first one of the session. `Agent._kb_drift_feedback()` (`kbcode/agent.py:591`) is the Stop
equivalent — when the model tries to end a turn that touched files
(`_kb_touched_this_run`, `kbcode/agent.py:116`), it runs `check_pointers()` and, on
drift, feeds the broken pointers back as one more `user` turn instead of
returning; guarded by `_kb_drift_checked` (`kbcode/agent.py:117`) so it nudges at most
once per turn.

See [[sessions]] for how compaction interacts with session replay,
[[architecture]] for the big picture.
