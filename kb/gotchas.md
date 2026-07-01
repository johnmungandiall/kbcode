# Gotchas — traps specific to this repo. Read before editing.

## Anthropic SDK kwargs
- `kbcode/provider.py:226-241` — `AnthropicProvider.complete`'s staged `attempts` list tries thinking/effort kwargs with SDK fallbacks (see [[providers]])
- An older SDK rejects newer kwargs via `TypeError`, caught and retried with simpler params — don't let `_with_retry` swallow it, it deliberately re-raises `TypeError`

## Threaded provider calls
- `kbcode/agent.py:124-162` — `Agent._complete()` runs the HTTP request on a daemon thread so Esc works mid-request (see [[providers]])
- Don't assume `KeyboardInterrupt` is only raised between Python statements

## Session replay requires matching provider
- `kbcode/cli.py:148-162` — `_resume_agent` restores the recorded provider/model from session meta
- If the recorded provider isn't configured, it falls back to the current one with a warning

## JSON serialization of SDK objects
- `kbcode/sessions.py:58-86` — `_jsonable()` handles pydantic models, dataclasses, and plain types
- New Anthropic SDK content-block shapes need `model_dump(mode="json")` fallback

## Tool-call repair is two layers
- `kbcode/tools/core.py:106-123` — `_repair()` fixes name typos + missing required args (execute-time)
- `kbcode/repair.py:48` — `promote()` recovers tool calls written as plain text (parse-time)
- Both layers only work for names the mode/subagent actually offers — see [[tools-and-repair]], [[modes-subagents]]

## Protected files
- `kbcode/tools/file.py:88-109` — `_protected_reason()` refuses writes to `.git/`, `.ssh/`, `.env`, secrets
- `.env.example` and `.gitignore` are explicitly allowed — see [[safety]]

## Compaction token estimate
- `kbcode/compaction.py:47-64` — `estimate_tokens()` uses ~4 chars/token + flat 1300/image
- This is rough; don't rely on exact counts — see [[context-management]]

## `tools.py` no longer exists
- Split into the `kbcode/tools/` package in v1.6.0 ([[changelog]]); a stray
  `kbcode/tools.py:<line>` pointer anywhere in this KB is drift — fix it to the
  actual submodule (`core.py`/`file.py`/`kb.py`/`memory.py`/`planning.py`/
  `subagent.py`/`schemas.py`)

## Streamed text must stop the thinking spinner first
- The thinking()/working() spinner is a Rich `Live` region redrawn every 100ms by a
  background ticker thread (`_TickingStatus._tick`, `kbcode/ui.py:226`). Streamed
  reply text arrives via `on_text` on the *provider worker thread*
  (`kbcode/agent.py:148`). Two threads writing the terminal at once = the spinner's
  redraw stomps the half-printed line, shredding any multi-line reply into trailing
  fragments (was true for tables AND plain prose).
- Fix: `stream_chunk` (`kbcode/ui.py:415`) calls `_active_status.stop()`
  (`kbcode/ui.py:239`) on the first token, so from then on only the worker thread
  prints. Don't re-introduce a spinner that stays live during streaming.
- `stop()` is called from BOTH the worker thread (via `stream_chunk`) and the main
  thread (the `with thinking()` exit), so its check-and-tear-down is guarded by
  `self._stop_lock` — without it both callers can pass the `_stopped` check and
  tear the Rich `Live` down twice at once, corrupting the terminal. Keep it locked.
- Replies are still streamed raw, not markdown-rendered — `assistant_text`'s
  `Markdown()` (`kbcode/ui.py:407`) is not used on the streaming path.

## The Esc watcher must be JOINED at turn end, not just signalled
- `interrupt_on_escape()` (`kbcode/interrupt.py:26`) runs a daemon thread that reads
  the console (Windows `msvcrt.getwch`) / holds the tty in cbreak (POSIX). Its
  `finally` does `stop.set()` **and** `thread.join(timeout=0.5)` (`kbcode/interrupt.py:47-48`).
- The join is load-bearing: without it the watcher outlives the turn and races the
  *next* prompt for stdin — stealing the user's first keystrokes so they "can't type
  after a reply" (intermittent, ~50ms poll window), or leaving POSIX in cbreak. Don't
  drop the join back to a bare `stop.set()`. Regression test: `tests/test_interrupt.py`.

## Tool-schema metadata must be stripped before the API
- Schemas may carry kbcode-only keys (currently `parallel_safe`, #4.3) that the
  model tool APIs reject as unknown. The OpenAI path is safe (it rebuilds each
  tool in `_tools`), but `AnthropicProvider` otherwise forwards `tools` verbatim
  — so `complete`/`stream` route through `_api_tools` (`kbcode/provider.py`),
  which keeps only name/description/`input_schema`.
- Add a new schema-level metadata key → confirm it's dropped for Anthropic
  (extend `_api_tools`), or Claude requests 400. See [[providers]], [[tools-and-repair]].

## web_search uses a throwaway thread pool, not a shared one
- `kbcode/tools/web.py:39` — `_tool_web_search` can't cancel a blocking `ddgs`
  call on timeout, and `ddgs`'s own per-request timeout doesn't bound its
  internal multi-engine retry loop. A shared pool would let one hung search
  serialize every later search behind it.
- Fix: a fresh single-worker `ThreadPoolExecutor` per call, with
  `shutdown(wait=False, cancel_futures=True)` in `finally` so the hung worker
  thread is abandoned (leaked, not killed — Python can't kill threads) instead
  of blocking the tool call. Don't switch this to a shared/module-level pool.

## Hook commands run with full shell privileges, unsandboxed
- `kbcode/hooks.py:85` — `HooksRunner._run_one()` runs a configured hook's
  `command` via `subprocess.run(shell=True, ...)` — same trust model as
  Claude Code's own hooks. A malicious or careless hook script in
  `.kbcode/settings.json` can do anything a shell can do (no allowlist, no
  sandbox). See [[safety]].

## `_run_subagent`'s inline UI calls must stay quiet-flag-gated
- `kbcode/agent.py:615` — `_run_subagent()` is used both sequentially (main
  thread, normal path) and concurrently, one call per pool worker thread, from
  `_run_subagents_parallel_batch()` (`kbcode/agent.py:391`) via
  `_quiet_dispatch()` (`kbcode/agent.py:379`), which sets the per-thread
  `Agent._quiet_subagents.on` flag. Every inline `ui.notice`/`ui.tool_call`/
  `ui.tool_result`/`ui.tool_running()` call inside `_run_subagent()` checks
  `quiet` first — TerminalUI's Rich `Live`-backed spinner isn't safe to have
  two open at once, so an unguarded UI call added later will corrupt the
  terminal when multiple subagents run in parallel. If you add a new inline
  UI call inside `_run_subagent()`, gate it on `quiet` too. See
  [[tools-and-repair]], [[modes-subagents]].
- Related: `Agent._record_usage()` (`kbcode/agent.py:570`) is guarded by
  `Agent._usage_lock` since #4.3's `run_subagent` extension can call it from
  multiple threads at once — don't reintroduce an unguarded `self.usage[...]`
  mutation elsewhere.
- Inside subagents, consecutive parallel-safe reads are now batched too
  (`_run_subagent_parallel_batch`, up to 16 workers). To get Cursor-like speed,
  explorer subagents must declare narrow parallel-only `tools:` lists and be
  strongly instructed to batch many reads per LLM response (see updated
  `code-explorer.md` and [[modes-subagents]]). The system prompt now tells the
  main agent the same rule.

## Displaying a path relative to root breaks outside the project
- `kbcode/tools/file.py:255` — `_tool_search_code` formats each hit through
  `self._display_path(fp)` (`kbcode/tools/core.py:139`), **not** a raw
  `fp.relative_to(self.root)`. kbcode isn't sandboxed to the project folder
  (`_resolve` honors absolute paths, see [[tools-and-repair]] and
  [[kbcode-write-anywhere]] intent), so a search/list base can point outside
  `root`. `Path.relative_to(self.root)` raises `ValueError` ('... is not in the
  subpath of ...') on a file that isn't under `root` — and that ValueError is
  **not** caught by search's `except (UnicodeDecodeError, OSError)`, so it aborts
  the whole tool on the first hit (this is what broke every search against a
  parent/sibling project). `_display_path` returns relative-when-inside,
  absolute-otherwise. Any new tool that displays a resolved path must use it,
  never a bare `relative_to`. Regression test: `tests/test_tools_search.py`
  (`test_search_code_outside_project_shows_absolute_path`).

## Compaction must shrink the *last* exchange too, not just the middle
- `kbcode/compaction.py:146` — `_compact_within_last_exchange()` is the second
  pass of `compact()`. The first pass (`_compact_exchanges`) summarizes whole
  *middle* exchanges and always protects the most recent one — but a turn that
  runs many tool round-trips and hits the step limit (`_MAX_STEPS`,
  `kbcode/agent.py:26`) is a **single** exchange (one user turn + ~50
  assistant/tool_results pairs). Pass 1 can't touch it, so `/compact`
  (`Agent.compact_now`) and mid-turn auto-compaction did nothing after a
  step-limit stop — the classic "`/compact` is broken" report.
- The within-exchange cut MUST land on an assistant boundary and drop only
  whole (assistant, tool_results) pairs, or you orphan a `tool_results` (a
  provider 400: every tool_use needs its matching tool_result, see
  [[providers]]). Don't "simplify" it into a raw slice. Regression tests:
  `tests/test_compaction.py` (`test_compact_shrinks_a_single_runaway_exchange`,
  `test_runaway_compaction_preserves_alternation_and_tool_pairing`).
- Note the step limit itself is a flat cap: `actions` can read *above*
  `_MAX_STEPS` in the "hit the step limit" notice because a parallel batch adds
  `len(batch)` per loop iteration (`kbcode/agent.py:305`), and the turn-summary
  "~N tokens" is *cumulative* usage across the turn's API calls, not the context
  size. See [[context-management]].

## Avoiding search/exploration loops
- When doing comparisons across directories (e.g. similar functions in broker/kotak vs broker/zerodha), the agent must start with `repo_map` (scoped to subdirs) then use `search_code` with the `path` argument for narrow, targeted searches. Batch different scoped searches in one step. Stop and summarize as soon as the pattern is found — do not repeat similar searches. Updated BASE_SYSTEM, search_code description, and code-explorer instructions enforce this (see prompts.py and schemas.py). This prevents the repetitive search loops that previously caused long-running or "stuck" turns.

## run_command per-turn limit (runaway guard)
- `kbcode/tools/file.py:42` — `_MAX_COMMANDS_PER_TURN = 25` (raised from 10) is a
  safety rail inside `_tool_run_command`. It increments a per-turn counter (reset
  in `ToolsCore.new_turn`, called at start of every `Agent.run`). Exceeding it
  raises the exact message the user saw: "Refused: hit the safety limit of 25
  run_command calls in one turn (a runaway loop guard)..."
- Intended to stop infinite `ls` / `echo` / pointless loops. Real tasks (e.g.
  "check for compilation errors", analyze + build + targeted checks + logs +
  retries) legitimately need more than a tiny budget inside one user message.
  When hit, the model is told to wrap up the turn; user can continue in next
  message. The count is shared with any `run_subagent` (they use the same
  `Tools` instance). Related to (and can combine with) the `_MAX_STEPS` cap.
  See [[safety]], [[tools-and-repair]].

## Vision-fallback candidate order matters
- `kbcode/vision_fallback.py:43` — `_candidates()` only trusts the active provider's
  own key as an OpenRouter route when `base_url` verifiably contains
  `openrouter.ai`; some presets (`mimo`) alias `key_env` to
  `OPENROUTER_API_KEY` while `KBCODE_BASE_URL` points elsewhere, so trusting
  the env var name alone would silently 401 — see [[vision]]

## `kbcode update` needs force-reinstall; bump `__version__` every release
- `kbcode/cli.py:47` — `_self_update()` installs from a moving git branch, not a
  pinned commit. A bare `pip install --upgrade git+URL` is a **silent no-op**
  when `__version__` is unchanged: pip sees the same version already installed
  and skips, so a fix pushed to GitHub without a version bump never reaches
  installed users (they stay stale while `python -m kbcode` from source shows
  the fix — "works from source, broken when installed"). Two guards, keep both:
  (1) `_self_update` runs a second `--force-reinstall --no-deps --no-cache-dir`
  step so HEAD is rebuilt regardless of version; (2) **always bump
  `kbcode/__init__.py` `__version__` in the same commit as any user-facing fix**
  so even the OLD update command upgrades. Fixed in v1.9.1 ([[changelog]]).
- Same family as the v1.6.1 packaging trap — see [[changelog]].

See [[conventions]] for general rules, [[about-kb]] for how traps get indexed here.
