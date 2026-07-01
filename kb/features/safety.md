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
`Checkpoints` (`kbcode/checkpoints.py:56`) auto-snapshots the project into a hidden
shadow git repo (`.kbcode/checkpoints/`, own `GIT_DIR`/`GIT_WORK_TREE`/
`GIT_INDEX_FILE` — never touches the real `.git`) right before the first
mutating tool call of a turn. `ensure_checkpoint()` (`kbcode/checkpoints.py:132`)
dedups to once per turn (reset via `new_turn()`, `kbcode/checkpoints.py:66`, mirroring
the KB-hook reset in [[context-management]]); no-ops if `git` isn't on PATH or
nothing changed. `.kbcode/`, `.git/`, `.env*` are excluded via `info/exclude`
(`_EXCLUDES`, `kbcode/checkpoints.py:31`), same spirit as redaction. `/rollback`
(`repl._rollback_menu`, `kbcode/repl.py:36`) opens an arrow-key picker built on
`prompt_input.select()`; a restore (`restore()`, `kbcode/checkpoints.py:200`) is
itself preceded by a safety snapshot. Deliberately **not** a cross-project
dedup store with size caps/pruning — one project, one store, no auto-
maintenance; deleting `.kbcode/checkpoints/` is always safe.

## Permissions
`Permissions` (`kbcode/permissions.py:10`) hold an `always_allow` set and call
`ui.permission(tool, detail)` (`kbcode/ui.py:341`), which renders a context panel then
offers a selectable Yes/Always/No menu via `prompt_input.select()`, falling
back to a typed `y/N/a` prompt (`_permission_typed`, `kbcode/ui.py:367`) when no menu
is available. `Permissions(ui=None)` keeps an ASCII-only `_plain()` path
(`kbcode/permissions.py:26`) for headless use.

## Hooks (Claude Code idea — PreToolUse/PostToolUse/Stop)
`HooksRunner` (`kbcode/hooks.py:40`) reimplements Claude Code's public,
documented hooks contract (code.claude.com/docs/en/hooks) from scratch — same
event names/JSON shape/exit codes, not copied from any proprietary source —
so a hook script written for real Claude Code works here unchanged. Config
comes from a `"hooks"` key in `.kbcode/settings.json`, shaped exactly like
Claude Code's own: `{"PreToolUse": [{"matcher": "run_command", "hooks":
[{"type": "command", "command": "..."}]}], "PostToolUse": [...], "Stop":
[...]}`. `Config.hooks` (`kbcode/config.py:108`) carries it through the same
settings merge as everything else (`load_config()`,
`kbcode/config.py:252`) — no new file or precedence rule.

`HooksRunner.run()` (`kbcode/hooks.py:48`) looks up `config[event]`, matches
each entry's `matcher` against the tool name (plain equality, or `"*"`/empty
= match-all), and for each matching `{"type": "command", ...}` runs the
command via `subprocess.run(shell=True, cwd=root, timeout=30)`
(`_run_one()`, `kbcode/hooks.py:82`) with a JSON payload (`hook_event_name`,
`tool_name`, `tool_input`, `tool_output`, `is_error`) piped to stdin.
Exit-code contract: `0` = allow silently; `2` = block, stderr becomes
`HookOutcome.message` (fed back to the model on PreToolUse, appended as a
note on PostToolUse/Stop); anything else is non-fatal (logged, run
continues). A broken hook — missing binary, timeout, crash — is swallowed,
never crashes the agent loop (see [[gotchas]]).

`ToolsCore.__init__` builds `self.hooks = HooksRunner(config.hooks,
self.root)` (`kbcode/tools/core.py:31`) right next to `self.checkpoints`.
`Agent._dispatch_tool()` (`kbcode/agent.py:178`) wraps one tool call: runs
`PreToolUse` (blocks without calling the tool if `HookOutcome.blocked`),
then `self.tools.execute()`, then `PostToolUse` (appends
`HookOutcome.message` to the result content if present). Every call site
that used to call `self.tools.execute()` directly now goes through
`_dispatch_tool()` instead — five in total: the sequential path in
`Agent.run()` (`kbcode/agent.py:301`), the parallel-batch
`ThreadPoolExecutor.submit` in `_run_parallel_batch()`
(`kbcode/agent.py:328`), the plain-text-recovered path in `_run_promoted()`
(`kbcode/agent.py:398`), and two sites inside `_run_subagent()`
(`kbcode/agent.py:550` and `:570`) — so a configured hook sees every tool
call, including ones made by a delegated subagent. `Agent._stop_hook_feedback()`
(`kbcode/agent.py:459`) runs the `Stop` event once per turn (gated by
`self._stop_hook_checked`, reset in `run()` alongside `self._kb_drift_checked`)
right after the KB-drift check — a configured `Stop` hook can veto ending
the turn (e.g. to demand a missing test run), and the agent feeds
`HookOutcome.message` back as a nudge to continue. This general,
user-scriptable hooks system is distinct from the baked-in KB-lifecycle
pseudo-hooks (`_KB_WRITE_TOOLS`, `kbcode/agent.py:53-58`) that mirror
claude-kb's PostToolUse/Stop behavior but aren't configurable.

See [[tools-and-repair]] for what gets gated through these, [[gotchas]] for the
protected-files list and the hooks trust model.
