# Safety — secret redaction, checkpoints, permissions.

## Secret redaction (Hermes idea)
`redact.py` masks live credentials — API key prefixes (`sk-`, `ghp_`, `AKIA`,
...), `Authorization` headers, private key blocks, DB connection-string
passwords, JWTs — out of anything a tool hands back to the model.
`redact_terminal_output()` (`kbcode/redact.py:182`) wraps `run_command`'s stdout/
stderr (env-dump commands like `env`/`printenv`, detected by
`is_env_dump_command()`, `kbcode/redact.py:152`, additionally get `KEY=value`/JSON-
field passes that are otherwise skipped via `code_file=True` to avoid mangling
source like `MAX_TOKENS=100`); `read_file`/`search_code` redact with
`code_file=True` too (`redact_with_count()`, `kbcode/redact.py:86`). On by default;
`KBCODE_REDACT_SECRETS=false` opts out (`_REDACT_ENABLED`, `kbcode/redact.py:20`).

## Checkpoints (right-sized Hermes port)
`Checkpoints` (`kbcode/checkpoints.py:53`) auto-snapshots the project into a hidden
shadow git repo (`.kbcode/checkpoints/`, own `GIT_DIR`/`GIT_WORK_TREE`/
`GIT_INDEX_FILE` — never touches the real `.git`) right before the first
mutating tool call of a turn. `ensure_checkpoint()` (`kbcode/checkpoints.py:129`)
dedups to once per turn (reset via `new_turn()`, `kbcode/checkpoints.py:63`, mirroring
the KB-hook reset in [[context-management]]); no-ops if `git` isn't on PATH or
nothing changed. `.kbcode/`, `.git/`, `.env*` are excluded via `info/exclude`
(`_EXCLUDES`, `kbcode/checkpoints.py:28`), same spirit as redaction. `/rollback`
(`repl._rollback_menu`, `kbcode/repl.py:36`) opens an arrow-key picker built on
`prompt_input.select()`; a restore (`restore()`, `kbcode/checkpoints.py:196`) is
itself preceded by a safety snapshot. Deliberately **not** a cross-project
dedup store with size caps/pruning — one project, one store, no auto-
maintenance; deleting `.kbcode/checkpoints/` is always safe.

## Permissions
`Permissions` (`kbcode/permissions.py:10`) hold an `always_allow` set and call
`ui.permission(tool, detail)` (`kbcode/ui.py:318`), which renders a context panel then
offers a selectable Yes/Always/No menu via `prompt_input.select()`, falling
back to a typed `y/N/a` prompt (`_permission_typed`, `kbcode/ui.py:344`) when no menu
is available. `Permissions(ui=None)` keeps an ASCII-only `_plain()` path
(`kbcode/permissions.py:26`) for headless use.

See [[tools-and-repair]] for what gets gated through these, [[gotchas]] for the
protected-files list.
