# About the KB — full rules for maintaining this knowledge base.

Read this before you maintain the KB, edit notes, or dispatch a sub-agent.
`CLAUDE.md` holds only the short triggers; the detail lives here.

## Read first
- Before ANY task, open the relevant `kb/` notes to orient — don't grep/scan the
  whole repo first; the KB is the designated entry point, not a fallback.
- If the KB lacks what you need, follow its `path:line` pointers into the code,
  then fold the finding back into the KB.

## Auto-maintain (mandatory)
- Whenever you add, change, move, rename, or delete code/config, update the
  affected `kb/` note(s) in the SAME session, before ending your turn — part of
  "done", not optional. Touch only the notes whose underlying code changed.
- New major feature → add `kb/features/<name>.md`. Refresh the "last indexed"
  marker in `kb/overview.md`. Append a dated one-line entry to `kb/changelog.md`.
- Edit the `kb/` FILES, not `CLAUDE.md` — it stays a stable pointer. Change the KB
  map in `CLAUDE.md` ONLY when a `kb/` file is added or removed.

## No silent drift
- LOCKSTEP SETS: before calling a change done, ask whether the value/name/contract
  you changed lives in MORE THAN ONE place — a version string, an enum mirrored by a
  switch, an allowlist duplicated in build + runtime, a field set on the server and
  parsed on the client, a default repeated in code + docs. Edit one member, then
  search the repo for the OLD value: zero stale hits or you are not done. Record each
  set as an explicit KB invariant ("change X → also change Y, Z, because …") and
  cross-link every member's note.
- CENTRAL TRAPS: a trap you record inside a feature/module note MUST also get a
  one-line stub + `[[gotchas]]` link in the central `kb/gotchas.md` index, or the
  next person won't find it. Read `kb/gotchas.md` first when behavior surprises you.
- RUNBOOKS: a multi-step procedure (cutting a release, deploying, rotating a secret,
  onboarding) needs a `kb/runbooks/<name>.md` listing EVERY file/step/artifact to
  touch, in order — a build/run command list is NOT a runbook. Capture it the first
  time you carry the procedure out.
- VISIBLE UPKEEP: end any turn that changed code/config with a status line — "KB:
  updated <note(s)>" or "KB: no change needed because <reason>" — so the user never
  has to ask whether the KB was updated.

## Sub-agents & skills
- A dispatched sub-agent (Task/Agent) or skill/workflow starts cold. Pass it the
  same rules: read the relevant `kb/` notes FIRST, and update them in the SAME
  session after changing code.
- This KB ships dedicated subagents in `.claude/agents/` (`kb-maintainer`,
  `kb-verify`, `kb-slim`); prefer DELEGATING KB work to them — they auto-trigger
  on the right tasks and already follow these rules.

## User map
- `kb/about-you.md` records durable facts about how the user wants you to work —
  working style, tech preferences, goals, standing rules.
- When the user states or corrects a durable preference, goal, or rule, update
  `kb/about-you.md` the SAME session. Tag each item [confirmed]/[inferred];
  promote [inferred] → [confirmed] only on confirmation.
- Capture lasting habits, not one-off chatter; never store secrets. Prefs that
  apply across ALL the user's projects → also persist to host long-term memory
  (e.g. Claude Code memory) when available.

## How to work
- THINK FIRST: state assumptions; if the request has multiple readings or a
  simpler path exists, say so — don't silently pick.
- SIMPLEST THING: the minimum change that solves it — no speculative features,
  abstractions, or config that wasn't asked for.
- SURGICAL: change only what the task needs; match the surrounding style; don't
  refactor or reformat unrelated code; remove only the orphans YOUR change
  creates, and flag (don't delete) other dead code.
- GOAL-DRIVEN: turn the task into a concrete check and loop until it verifies.

## Pointers & freshness
- PREFER a name-anchored pointer: a markdown link to the file, then the symbol
  in backticks with its line, like `[lib/app.dart](../lib/app.dart)` then
  `` `start()`:<line> `` (a name with no same-line link binds to the note's first
  link / primary file). The NAME is the durable anchor; the line is a hint — so
  the checker can confirm the symbol is still on that line and `--fix` can
  relocate it when code moves. A bare `[file](path):<line>` / `` `path:<line>` ``
  is only existence + range checked. Never a bare filename. (Write illustrative
  examples with a `<line>` placeholder, NOT a real number, so the checker skips them.)
- Release history lives ONLY in `kb/changelog.md`; `kb/overview.md` keeps a
  one-line `last indexed: <date>` and nothing more — don't duplicate history.
- Don't rely on discipline — run `tools/kb-check.sh` (verifies all three pointer
  styles; `--fix` auto-repairs drifted line numbers by the name anchor;
  `--freshness` flags notes older than the code) via the sample
  `tools/hooks/pre-commit` or before release.
- This is also enforced live in Claude Code sessions on THIS repo via
  `.claude/settings.json` hooks: `.claude/hooks/kb_update_reminder.py`
  (PostToolUse on Edit/Write/MultiEdit) nudges once per session after a
  non-KB file changes; `.claude/hooks/kb_drift_check.py` (Stop) blocks
  ending a turn once if `tools/kb-check.sh` reports a broken pointer.

See [[conventions]] for note-writing rules, [[overview]] for the big picture.
