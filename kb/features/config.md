# Config — precedence, presets, project retargeting.

## Precedence
`load_config()` (`kbcode/config.py:322`) resolves provider/model/base_url and the API
key (via `.env`) as: **env vars > the project's `.kbcode`/.env > the launch
folder's > the global `~/.kbcode` (`global_dir()`, `kbcode/config.py:191`) > preset
defaults**. `.env` files are loaded highest-priority-first since `load_dotenv`
never overrides an already-set value; `settings.json` is merged the opposite
way (low->high, `kbcode/config.py:344-347`). The launch-folder and global fallbacks are
what let you configure kbcode once. `python -m kbcode model` now writes the
provider/model to both the global `~/.kbcode/settings.json` (future default)
and the current project's `.kbcode/settings.json` (so the next `kb` here picks
it up immediately). Keys go only to global `.env`. If a project `.env` pins
via `KBCODE_PROVIDER` etc, the wizard updates those pins so the choice sticks.
`PRESETS` (`kbcode/config.py:39`) is the source of truth for built-in providers
(anthropic, openai, gemini, deepseek, openrouter, mimo, ollama, custom).

## Tuning knobs (int env vars, via `_int()`)
`KBCODE_MAX_TOKENS`, `KBCODE_COMPACT_TOKENS` (0 disables auto-compaction), and
`KBCODE_REQUEST_TIMEOUT` — the per-request HTTP timeout in seconds
(`DEFAULT_REQUEST_TIMEOUT = 120`, `kbcode/config.py:28`). Without it the SDK
default (~600s) lets a stalled model freeze the whole turn for ten minutes —
especially visible when a subagent makes many calls. `Config.request_timeout`
(`kbcode/config.py:113`) flows into both provider clients via
`LLMProvider._client_kwargs()` (see [[providers]]); set `KBCODE_REQUEST_TIMEOUT=0`
to opt out and restore the SDK default.

`KBCODE_MAX_STEPS` / `KBCODE_MAX_COMMANDS` — the per-turn runaway-loop guards
(`DEFAULT_MAX_STEPS = 50` / `DEFAULT_MAX_COMMANDS = 25`, `kbcode/config.py:33-34`),
carried as `Config.max_steps` / `Config.max_commands_per_turn`
(`kbcode/config.py:114-115`). `max_steps` caps tool round-trips per user message
(`Agent.__init__`'s `max_steps` arg, passed from `kbcode/cli.py:165`);
`max_commands_per_turn` caps `run_command` calls per turn (read in
`_tool_run_command`, `kbcode/tools/file.py:381`). Hitting either pauses the turn
safely — "continue" resumes — see [[gotchas]] for why real tasks hit them.

You can also set "compact_tokens" in .kbcode/settings.json (or global
~/.kbcode/settings.json) so auto-compaction kicks in at the right size for
your model (e.g. 80000 for large-context models). Env var always wins.

`KBCODE_LOG_LEVEL` (a *string*, not an `_int()` knob; default `INFO`) drives the
diagnostic file log — `setup_logging()` (`kbcode/logs.py`, called from
`kbcode/cli.py` right after `load_config`) attaches a rotating handler at
`<project>/.kbcode/kbcode.log` to the `kbcode` logger. `DEBUG` = full traces for
bug reports; `off`/`none`/`0` = write nothing. It's separate from `TerminalUI`
on-screen output and never raises (unwritable path → no log, run continues).
Modules log via the standard `logging.getLogger(__name__)`.

## Project retargeting
`Config` (`kbcode/config.py:100`) derives every path (`kbcode_dir`, `kb_dir`,
`memory_db`, `agent_md`, `settings_file`, `standing_orders_file`, ...) as a
property off `project_dir` — so the project can be retargeted live. The CLI
picks it via `-C`/`--dir`/`--project` (`_take_dir`, `kbcode/cli.py:228`) or
`init <path>`. In-chat `/open <folder>` (`kbcode/repl.py:483`) mutates
`config.project_dir` (`kbcode/repl.py:492`) then rebuilds `kb`, `memory`, and the
agent — re-scaffolding the new folder, keeping the same provider/model/key. A
REPL guard catches the common slip of typing the terminal-only `init`/`model`
as a chat message and points at `/open` instead.

See [[architecture]] for where `Config` sits in the CLI -> Agent -> Provider ->
Tools flow, [[cheatsheet]] for the exact commands.
