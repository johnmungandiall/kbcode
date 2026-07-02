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
- Uninstall: `pip uninstall kbcode`, then delete `~/.kbcode` (or `KBCODE_HOME`)
  for global data; per-project AGENT.md/kb//.kbcode/ are optional leftovers
  (README "🗑️ Uninstall" section has the full plan)
- `kbcode --version` — show version; single source is `kbcode.__version__`
  (`kbcode/__init__.py:9`) — a release = bump it, then tag `vX.Y.Z` + push
- For maximum speed (Cursor-like): use a fast model + give narrow tasks.
  kbcode now aggressively batches parallel reads (16 workers + prompt rules).
- `pytest` — run the test suite (`tests/`, 34 files + conftest.py); `python -m compileall -q kbcode`
  for a fast syntax-only check (glob-free — `py_compile kbcode/*.py` breaks on
  Windows PowerShell, which doesn't expand `*`)

## Windows / PowerShell (this is the dev environment)
- Set `PYTHONIOENCODING=utf-8` before running anything that prints the UI —
  the terminal uses emoji/box-drawing chars the default cp1252 console can't
  encode (raw `print()` breaks; output through `rich` is fine)
- Running `python -m kbcode` from another directory needs `PYTHONPATH` pointed
  at the repo root (the package isn't installed there)

## Chat commands (type in chat)
- `/init` — scan the project's code and build/refresh the kb/ knowledge base
  (a fresh-templates KB also prints a startup hint pointing here)
- `/mode code|architect|ask|debug` — switch personality
- `/provider <name>` — switch model provider
- `/model <id>` — switch model
- `/temperature <0|0.01|...|1>|none` — adjust sampling temp (0.00 to 1.00 in 0.01 steps)
- `/thinking off|low|medium|normal|high` — set reasoning level or 'off' to disable (normal=medium)
- `/maxtokens <n>|auto` — set or auto max output tokens based on model
- `/auto` (or **Shift+Tab**, works mid-turn too) — toggle ask/auto permission
  mode: auto = no prompts, no questions; autopilot/fixer builtin subagents ([[safety]])
- `/thoughts` — expand the last turn's model reasoning (collapsed 🧠 line by default)
- `/status` — provider, model, mode, context size
- `/todo` — show task checklist
- `/kb` — list kb/ notes
- `/mcp [reload]` — list connected MCP servers & tools; reload re-reads
  settings.json + reconnects (needed after adding a server mid-session, [[mcp]])
- `/kb-check [--fix]` — verify/repair kb/ pointers
- `/kb-undo <note>` — restore a kb/ note from its last pre-overwrite backup
- `/insights` — token/cost usage
- `/compact` — summarize old turns
- `/rollback` — undo edits from checkpoint
- `/diff [n]` — working tree vs checkpoint (no n = newest)
- `/sessions` / `/resume` — session history
- `/copy [n]` — copy the last reply's code block (or block n; no blocks = whole
  reply) to the system clipboard (`kbcode/clipboard.py`)
- `/image [path]` or Alt+V — attach image
- `/video <path>` — describe video via vision fallback

See [[conventions]] "When adding things" for how to add a tool/provider/mode/
subagent/slash-command. [[overview]] has first-time setup, [[gotchas]] has what
to avoid.
