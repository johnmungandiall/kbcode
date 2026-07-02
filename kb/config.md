# Config — provider presets, settings loading, and persistence.

## Provider presets
Defined in `PRESETS` dict in [config.py](../kbcode/config.py) `PRESETS:32` — 8 built-in:
anthropic, openai, openrouter, deepseek, gemini, mimo, ollama, custom.
Each has `kind`, `base_url`, `key_env`, `model`.

## Settings loading
`load_config()` at [config.py](../kbcode/config.py) `load_config:290` merges settings
from 3 levels: `~/.kbcode` → launch-dir `.kbcode` → project `.kbcode` (last wins).
Env vars (`KBCODE_PROVIDER`, `KBCODE_MODEL`, etc.) beat all settings files.

## Persistence
- `persist_choice()` ([config.py](../kbcode/config.py) `persist_choice:203`) — saves to
  BOTH global `~/.kbcode` AND project `.kbcode/settings.json`. Used by `kb model` wizard.
- `persist_global_choice()` ([config.py](../kbcode/config.py) `persist_global_choice:233`) —
  saves to global `~/.kbcode` ONLY. Used by REPL `/provider` and `/model` commands
  so switching in one project becomes the default for all projects (cross-project
  default). Project-level `.kbcode/settings.json` from an explicit `kb model` still
  takes precedence over the global default.

## Model list cache
`~/.kbcode/models/<provider>.json` — persisted model lists with 24h TTL.
- `save_model_cache(provider, models)` at [config.py](../kbcode/config.py) `save_model_cache:276`
- `load_model_cache(provider)` at [config.py](../kbcode/config.py) `load_model_cache:268`
  returns None if missing or stale (>24h).

Used by `_model_completion_sources` in [[repl]] for instant autocomplete across sessions.

See [[architecture]], [[repl]].
