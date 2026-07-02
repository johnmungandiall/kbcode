# REPL — the interactive chat loop.

`repl()` at [repl.py](../kbcode/repl.py) `repl:212` — reads lines, dispatches
slash commands, runs agent turns.

## Model autocomplete
`_model_completion_sources()` at [repl.py](../kbcode/repl.py) `_model_completion_sources:85`
builds two callables for `/provider` and `/model` autocomplete:
- **Disk cache first**: `~/.kbcode/models/<provider>.json` (24h TTL) — autocomplete
  is instant even offline. Falls back to live `list_models()` which updates the cache.
- **Tuple metadata**: callables now return `(name, meta)` tuples so the current
  provider/model shows a `● current` marker in the autocomplete popup.

## Persistence from REPL
`/provider` and `/model` now use `persist_global_choice()` — saves only to
`~/.kbcode/settings.json`, NOT to project `.kbcode/settings.json`. This means
switching in one project becomes the default for all projects, while a project
explicitly configured via `kb model` still keeps its overrides.

See [[config]], [[architecture]].
