# Gotchas — traps specific to this repo. Read before editing.

## Anthropic SDK kwargs
- `agent.py:198-215` — `Agent._complete` tries thinking/effort kwargs with SDK fallbacks
- An older SDK rejects newer kwargs via `TypeError`, caught and retried with simpler params

## Threaded provider calls
- `agent.py:88-105` — `_complete()` runs the HTTP request on a daemon thread so Esc works mid-request
- Don't assume `KeyboardInterrupt` is only raised between Python statements

## Session replay requires matching provider
- `cli.py:144-158` — `_resume_agent` restores the recorded provider/model from session meta
- If the recorded provider isn't configured, it falls back to the current one with a warning

## JSON serialization of SDK objects
- `sessions.py:58-86` — `_jsonable()` handles pydantic models, dataclasses, and plain types
- New Anthropic SDK content-block shapes need `model_dump(mode="json")` fallback

## Tool-call repair is two layers
- `tools.py:281-298` — `_repair()` fixes name typos + missing required args (execute-time)
- `repair.py:48` — `promote()` recovers tool calls written as plain text (parse-time)

## Protected files
- `tools.py:312-333` — `_protected_reason()` refuses writes to `.git/`, `.ssh/`, `.env`, secrets
- `.env.example` and `.gitignore` are explicitly allowed

## Compaction token estimate
- `compaction.py:44-61` — `estimate_tokens()` uses ~4 chars/token + flat 1300/image
- This is rough; don't rely on exact counts

See [[conventions]] for general rules.
