# Gotchas — traps specific to this repo. Read before editing.

## Anthropic SDK kwargs
- `kbcode/provider.py:214-231` — `AnthropicProvider.complete`'s staged `attempts` list tries thinking/effort kwargs with SDK fallbacks (see [[providers]])
- An older SDK rejects newer kwargs via `TypeError`, caught and retried with simpler params — don't let `_with_retry` swallow it, it deliberately re-raises `TypeError`

## Threaded provider calls
- `kbcode/agent.py:102-138` — `Agent._complete()` runs the HTTP request on a daemon thread so Esc works mid-request (see [[providers]])
- Don't assume `KeyboardInterrupt` is only raised between Python statements

## Session replay requires matching provider
- `kbcode/cli.py:144-158` — `_resume_agent` restores the recorded provider/model from session meta
- If the recorded provider isn't configured, it falls back to the current one with a warning

## JSON serialization of SDK objects
- `kbcode/sessions.py:58-86` — `_jsonable()` handles pydantic models, dataclasses, and plain types
- New Anthropic SDK content-block shapes need `model_dump(mode="json")` fallback

## Tool-call repair is two layers
- `kbcode/tools/core.py:94-111` — `_repair()` fixes name typos + missing required args (execute-time)
- `kbcode/repair.py:48` — `promote()` recovers tool calls written as plain text (parse-time)
- Both layers only work for names the mode/subagent actually offers — see [[tools-and-repair]], [[modes-subagents]]

## Protected files
- `kbcode/tools/file.py:88-109` — `_protected_reason()` refuses writes to `.git/`, `.ssh/`, `.env`, secrets
- `.env.example` and `.gitignore` are explicitly allowed — see [[safety]]

## Compaction token estimate
- `kbcode/compaction.py:44-61` — `estimate_tokens()` uses ~4 chars/token + flat 1300/image
- This is rough; don't rely on exact counts — see [[context-management]]

## `tools.py` no longer exists
- Split into the `kbcode/tools/` package in v1.6.0 ([[changelog]]); a stray
  `kbcode/tools.py:<line>` pointer anywhere in this KB is drift — fix it to the
  actual submodule (`core.py`/`file.py`/`kb.py`/`memory.py`/`planning.py`/
  `subagent.py`/`schemas.py`)

## Vision-fallback candidate order matters
- `kbcode/vision_fallback.py:43` — `_candidates()` only trusts the active provider's
  own key as an OpenRouter route when `base_url` verifiably contains
  `openrouter.ai`; some presets (`mimo`) alias `key_env` to
  `OPENROUTER_API_KEY` while `KBCODE_BASE_URL` points elsewhere, so trusting
  the env var name alone would silently 401 — see [[vision]]

See [[conventions]] for general rules, [[about-kb]] for how traps get indexed here.
