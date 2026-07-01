# Gotchas — traps specific to this repo. Read before editing.

## Anthropic SDK kwargs
- `kbcode/provider.py:226-241` — `AnthropicProvider.complete`'s staged `attempts` list tries thinking/effort kwargs with SDK fallbacks (see [[providers]])
- An older SDK rejects newer kwargs via `TypeError`, caught and retried with simpler params — don't let `_with_retry` swallow it, it deliberately re-raises `TypeError`

## Threaded provider calls
- `kbcode/agent.py:104-140` — `Agent._complete()` runs the HTTP request on a daemon thread so Esc works mid-request (see [[providers]])
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
  (`kbcode/agent.py:129`). Two threads writing the terminal at once = the spinner's
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

## Vision-fallback candidate order matters
- `kbcode/vision_fallback.py:43` — `_candidates()` only trusts the active provider's
  own key as an OpenRouter route when `base_url` verifiably contains
  `openrouter.ai`; some presets (`mimo`) alias `key_env` to
  `OPENROUTER_API_KEY` while `KBCODE_BASE_URL` points elsewhere, so trusting
  the env var name alone would silently 401 — see [[vision]]

See [[conventions]] for general rules, [[about-kb]] for how traps get indexed here.
