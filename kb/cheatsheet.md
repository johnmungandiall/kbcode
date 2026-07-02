# Cheatsheet — commands and snippets you reach for most.

## Run / build / test
- `pip install -e .` — editable dev install; `[project.scripts]` puts both
  `kbcode` and the shorter `kb` alias on PATH (equivalent to `python -m kbcode`)
- `kbcode` or `kb` — start interactive chat
- `kbcode "do something"` — one-shot task (`-y`/`--yes` auto-approves writes/commands)
- `kbcode -C "<path>"` — work on a different project without `cd` (folder must exist)
- `kbcode model` — setup wizard (provider + key + model); auto-fetches model
  list; persists to global (~/.kbcode) **and** current project's .kbcode/settings.json
  (and updates KBCODE_* pins in an existing project .env so selection applies)
- `kbcode init` — scaffold project (AGENT.md + kb/ + .kbcode/ — config only,
  self-gitignored; runtime state — memory db, sessions, checkpoints, history,
  log — lives in `~/.kbcode/projects/<slug>/`; `KBCODE_HOME` overrides `~/.kbcode`)
- `kbcode -c` — continue most recent saved session
- `kbcode --resume` — pick from past sessions
- `kbcode update` — upgrade from GitHub (`_self_update`, `kbcode/cli.py:50`)
- `kbcode --version` — show version; single source is `kbcode.__version__`
  (`kbcode/__init__.py:9`) — a release = bump it, then tag `vX.Y.Z` + push
- For maximum speed (Cursor-like): use a fast model + give narrow tasks.
  kbcode now aggressively batches parallel reads (16 workers + prompt rules).
- `pytest` — run the test suite (`tests/`, 30 files + conftest.py); `python -m py_compile
  kbcode/*.py` for a fast syntax-only check

## Windows / PowerShell (this is the dev environment)
- Set `PYTHONIOENCODING=utf-8` before running anything that prints the UI —
  the terminal uses emoji/box-drawing chars the default cp1252 console can't
  encode (raw `print()` breaks; output through `rich` is fine)
- Running `python -m kbcode` from another directory needs `PYTHONPATH` pointed
  at the repo root (the package isn't installed there)

## Chat commands (type in chat)
- `/mode code|architect|ask|debug` — switch personality
- `/provider <name>` — switch model provider
- `/model <id>` — switch model
- `/status` — provider, model, mode, context size
- `/todo` — show task checklist
- `/kb` — list kb/ notes
- `/mcp [reload]` — list connected MCP servers & tools; reload re-reads
  settings.json + reconnects (needed after adding a server mid-session, [[mcp]])
- `/kb-check [--fix]` — verify/repair kb/ pointers
- `/insights` — token/cost usage
- `/compact` — summarize old turns
- `/rollback` — undo edits from checkpoint
- `/diff [n]` — working tree vs checkpoint (no n = newest)
- `/sessions` / `/resume` — session history
- `/image [path]` or Alt+V — attach image
- `/video <path>` — describe video via vision fallback

See [[conventions]] "When adding things" for how to add a tool/provider/mode/
subagent/slash-command. [[overview]] has first-time setup, [[gotchas]] has what
to avoid.
