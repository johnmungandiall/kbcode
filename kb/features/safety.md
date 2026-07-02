# Safety — secret redaction, checkpoints, permissions.

## Runaway-loop guards (tunable)
Two per-turn caps stop a looping model from burning tokens forever: the agent
loop's step cap (`Agent.max_steps`, from `Config.max_steps` /
`KBCODE_MAX_STEPS`, default 50) and the `run_command` cap
(`Config.max_commands_per_turn` / `KBCODE_MAX_COMMANDS`, default 25, enforced
in `_tool_run_command`, `kbcode/tools/file.py:381`). Both end the turn safely —
the user says "continue" to resume. Details and history: [[gotchas]], [[config]].

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
`Checkpoints` (`kbcode/checkpoints.py:58`) auto-snapshots the project into a hidden
shadow git repo (`~/.kbcode/projects/<slug>/checkpoints/` — the project's
`Config.state_dir`, outside the working tree — own `GIT_DIR`/`GIT_WORK_TREE`/
`GIT_INDEX_FILE`, never touches the real `.git`) right before the first
mutating tool call of a turn. `ensure_checkpoint()` (`kbcode/checkpoints.py:134`)
dedups to once per turn (reset via `new_turn()`, `kbcode/checkpoints.py:68`, mirroring
the KB-hook reset in [[context-management]]); no-ops if `git` isn't on PATH or
nothing changed. `.kbcode/`, `.git/`, `.env*` are excluded via `info/exclude`
(`_EXCLUDES`, `kbcode/checkpoints.py:33`), same spirit as redaction. `/rollback`
(`repl._rollback_menu`, `kbcode/repl.py:38`) opens an arrow-key picker built on
`prompt_input.select()`; a restore (`restore()`, `kbcode/checkpoints.py:202`) is
itself preceded by a safety snapshot. Deliberately **not** a cross-project
dedup store with size caps/pruning — one project, one store, no auto-
maintenance; deleting the `checkpoints/` folder is always safe.

## Permissions
`Permissions` (`kbcode/permissions.py:10`) hold an `always_allow` set and call
`ui.permission(tool, detail)` (`kbcode/ui.py:396`), which renders a context panel then
offers a selectable Yes/Always/No menu via `prompt_input.select()`, falling
back to a typed `y/N/a` prompt (`_permission_typed`, `kbcode/ui.py:422`) when no menu
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
[...]}`. `Config.hooks` (`kbcode/config.py:118`) carries it through the same
settings merge as everything else (`load_config()`,
`kbcode/config.py:365`) — no new file or precedence rule.

`HooksRunner.run()` (`kbcode/hooks.py:51`) looks up `config[event]`, matches
each entry's `matcher` against the tool name (plain equality, or `"*"`/empty
= match-all), and for each matching `{"type": "command", ...}` runs the
command via `subprocess.run(shell=True, cwd=root, timeout=self.timeout)`
(`_run_one()`, `kbcode/hooks.py:85`) with a JSON payload (`hook_event_name`,
`tool_name`, `tool_input`, `tool_output`, `is_error`) piped to stdin.
Exit-code contract: `0` = allow silently; `2` = block, stderr becomes
`HookOutcome.message` (fed back to the model on PreToolUse, appended as a
note on PostToolUse/Stop); anything else is non-fatal (logged, run
continues). A broken hook — missing binary, timeout, crash — is swallowed,
never crashes the agent loop (see [[gotchas]]).

`self.timeout` (`HooksRunner.__init__`, `kbcode/hooks.py:43`) defaults to
30s (`_TIMEOUT`) but is now configurable per project: an explicit
constructor `timeout` arg wins (used by tests); otherwise it reads
`config.get("timeout", _TIMEOUT)`, so `.kbcode/settings.json` can set
`"hooks": {"timeout": N, "PreToolUse": [...], ...}` to change the timeout
for every hook command in that project.

`ToolsCore.__init__` builds `self.hooks = HooksRunner(config.hooks,
self.root)` (`kbcode/tools/core.py:31`) right next to `self.checkpoints` —
no timeout arg passed, so it always picks up the settings-driven value.
`Agent._dispatch_tool()` (`kbcode/agent.py:197`) wraps one tool call: runs
`PreToolUse` (blocks without calling the tool if `HookOutcome.blocked`),
then `self.tools.execute()`, then `PostToolUse` (appends
`HookOutcome.message` to the result content if present). Every call site
that used to call `self.tools.execute()` directly now goes through
`_dispatch_tool()` instead — the sequential path in `Agent.run()`
(`kbcode/agent.py:338`), the parallel-batch `ThreadPoolExecutor.submit` in
`_run_parallel_batch()` (`kbcode/agent.py:360`), the plain-text-recovered
path in `_run_promoted()` (`kbcode/agent.py:468`), two sites inside
`_run_subagent()` (`kbcode/agent.py:677` and `:719`), and — #4.3 extension,
see [[tools-and-repair]] — `_quiet_dispatch()` (`kbcode/agent.py:428`), used
by concurrent `run_subagent` batches — so a configured hook sees every tool
call, including ones made by a delegated subagent, sequential or parallel.
`Agent._stop_hook_feedback()` (`kbcode/agent.py:556`) runs the `Stop` event
once per turn (gated by `self._stop_hook_checked`, reset in `run()` alongside
`self._kb_drift_checked`) right after the KB-drift check — a configured
`Stop` hook can veto ending the turn (e.g. to demand a missing test run),
and the agent feeds `HookOutcome.message` back as a nudge to continue. This
general, user-scriptable hooks system is distinct from the baked-in
KB-lifecycle pseudo-hooks (`_KB_WRITE_TOOLS`, `kbcode/agent.py:67`) that
mirror claude-kb's PostToolUse/Stop behavior but aren't configurable.

## MCP calls ride the same rails
Every `mcp__server__tool` call goes through `ToolsCore._execute_mcp()`
(`kbcode/tools/core.py:116`): permission prompt by default (side-effects are
opaque, like `run_command`), `ensure_checkpoint("before MCP tool: ...")`
before anything that may mutate, and the result through
`redact_terminal_output_with_count` + `_note_redactions` — MCP servers can
return file content or command output. Server config can relax this:
`read_only: true` skips prompt+checkpoint (and marks the tools
`parallel_safe`); `trusted: ["tool"]` skips only the prompt. MCP servers run
with the user's full privileges (no sandbox — same trust model as hooks and
`run_command`), and PreToolUse/PostToolUse hooks fire for them for free
since `_dispatch_tool` matches by tool name. Full picture: [[mcp]].

See [[tools-and-repair]] for what gets gated through these, [[gotchas]] for the
protected-files list and the hooks trust model.
