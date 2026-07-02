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
   `kbcode/compaction.py:146`, `_render`, `kbcode/compaction.py:125`) spliced onto the
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

All passes preserve the alternation invariant (pass 0 trivially — nothing is
added, removed, or reordered). Auto-triggered in
`Agent._maybe_compact()` (`kbcode/agent.py:839`) and mid-turn by
`_compact_mid_turn_or_stop()` (`kbcode/agent.py:484`); manual via `/compact` ->
`Agent.compact_now()` (`kbcode/agent.py:859`).

## Knowledge base (product feature)
`KnowledgeBase` (`kbcode/knowledge_base.py:153`) holds `kb/` notes loaded into the
system prompt (`kbcode/prompts.py:42` `build_system_prompt`) so the agent doesn't
re-scan files; `read_all()` (`kbcode/knowledge_base.py:169`). `check_pointers()`
(`kbcode/knowledge_base.py:217`, `/kb-check`) resolves every `path:line` reference and
flags missing files / stale lines; placeholder examples are skipped.
`fix_pointers()` (`kbcode/knowledge_base.py:243`, `/kb-check --fix`) relocates a
drifted pointer by the code symbol named on the same note line (`_anchors`,
`kbcode/knowledge_base.py:291`; `_relocate`, `kbcode/knowledge_base.py:303` — prefer a unique
definition line, then a unique call, then a unique mention).

## KB lifecycle hooks (agent.py — baked-in default, no `.claude/settings.json`
equivalent inside kbcode itself)
`Agent._with_kb_reminder()` (`kbcode/agent.py:540`) is the PostToolUse equivalent —
after a successful `write_file`/`edit_file` outside `kb/`/`.kbcode/`/`.git/`/
`node_modules/` and the top-level docs, it appends a once-per-session reminder
(`_kb_reminder_done`, set `kbcode/agent.py:114`) nudging the model to update the
matching note. `Agent._kb_drift_feedback()` (`kbcode/agent.py:567`) is the Stop
equivalent — when the model tries to end a turn that touched files
(`_kb_touched_this_run`, `kbcode/agent.py:115`), it runs `check_pointers()` and, on
drift, feeds the broken pointers back as one more `user` turn instead of
returning; guarded by `_kb_drift_checked` (`kbcode/agent.py:116`) so it nudges at most
once per turn.

See [[sessions]] for how compaction interacts with session replay,
[[architecture]] for the big picture.
