# Config — precedence, presets, paths, project retargeting.

## Precedence
`load_config()` (`kbcode/config.py:484`) resolves provider/model/base_url , temperature, thinking (incl. 'off'), max_tokens (model-aware auto) and the API
key (via `.env`) as: **env vars > the project's `.kbcode`/.env > the launch
folder's > the global `~/.kbcode` (`global_dir()`, `kbcode/config.py:220`) > preset
defaults**. `.env` files are loaded highest-priority-first since `load_dotenv`
never overrides an already-set value; `settings.json` is merged the opposite
way (low->high, `kbcode/config.py:400-408`). The launch-folder and global fallbacks are
what let you configure kbcode once. `python -m kbcode model` now writes the
provider/model to both the global `~/.kbcode/settings.json` (future default)
and the current project's `.kbcode/settings.json` (so the next `kb` here picks
it up immediately). Keys go only to global `.env`. If a project `.env` pins
via `KBCODE_PROVIDER` etc, the wizard updates those pins so the choice sticks.
`PRESETS` (`kbcode/config.py:40`) is the source of truth for built-in providers
(anthropic, openai, gemini, deepseek, openrouter, mimo, ollama, custom).

**Exception to the shallow merge: `mcpServers`.** MCP server definitions are
merged PER SERVER across home → launch → project (a union, higher scope wins
per server name — `load_mcp_servers()`, `kbcode/config.py:238`, carried as
`Config.mcp`, `kbcode/config.py:119`), unlike every other settings key where
the higher-priority file's whole value replaces the lower one. The helper is
separate from `load_config` so `/mcp reload` can re-read it mid-session.
Claude Code-compatible shape; fields and semantics in [[mcp]], the trap in
[[gotchas]].

## Where files live (config vs runtime state)
The project's `.kbcode/` holds **config only** (settings.json, standing-orders.md,
agents/, modes/, prompts/, .env) and self-hides from the host project's git:
`_ensure_self_ignore()` (`kbcode/config.py:207`) drops a `*` .gitignore inside it
(only if absent — a user-customized one is left alone; OSError swallowed), called
from `ensure_dirs()` (`kbcode/config.py:182`) and `save_settings()`
(`kbcode/config.py:248`). **Machine-local runtime state** — `memory_db`,
`sessions_dir`, `checkpoints_dir`, `history_file`, kbcode.log — hangs off
`Config.state_dir` (`kbcode/config.py:131`): `~/.kbcode/projects/<slug>/`,
mirroring Claude Code's `~/.claude/projects/`, so launching kbcode never dumps
runtime files into the project working tree. `project_slug()`
(`kbcode/config.py:230`) encodes the resolved absolute path — every
non-alphanumeric char becomes `-`. `KBCODE_HOME` overrides `~/.kbcode` entirely
(read in `global_dir()`; the autouse fixture in `tests/conftest.py` sets it
per-test). Legacy fallback: if `<project>/.kbcode/memory.db` exists, `state_dir`
stays the project-local `.kbcode` so old projects lose nothing — see [[gotchas]].

## Tuning knobs (int env vars, via `_int()`)
`KBCODE_MAX_TOKENS`, `KBCODE_COMPACT_TOKENS` (0 disables auto-compaction), and
`KBCODE_REQUEST_TIMEOUT` — the per-request HTTP timeout in seconds
(`DEFAULT_REQUEST_TIMEOUT = 120`, `kbcode/config.py:29`). Without it the SDK
default (~600s) lets a stalled model freeze the whole turn for ten minutes —
especially visible when a subagent makes many calls. `Config.request_timeout`
(`kbcode/config.py:114`) flows into both provider clients via
`LLMProvider._client_kwargs()` (see [[providers]]); set `KBCODE_REQUEST_TIMEOUT=0`
to opt out and restore the SDK default.

`KBCODE_MAX_STEPS` / `KBCODE_MAX_COMMANDS` — the per-turn runaway-loop guards
(`DEFAULT_MAX_STEPS = 50` / `DEFAULT_MAX_COMMANDS = 25`, `kbcode/config.py:34-35`),
carried as `Config.max_steps` / `Config.max_commands_per_turn`
(`kbcode/config.py:115-116`). `max_steps` caps tool round-trips per user message
(`Agent.__init__`'s `max_steps` arg, passed from `kbcode/cli.py:165`);
`max_commands_per_turn` caps `run_command` calls per turn (read in
`_tool_run_command`, `kbcode/tools/file.py:381`). Hitting either pauses the turn
safely — "continue" resumes — see [[gotchas]] for why real tasks hit them.

You can also set "compact_tokens" in .kbcode/settings.json (or global
~/.kbcode/settings.json) so auto-compaction kicks in at the right size for
your model (e.g. 80000 for large-context models). Env var always wins.

Temperature (range 0-1), thinking and max_tokens are loaded preferring env → settings.json →
auto (for max_tokens). `KBCODE_MAX_TOKENS` (or settings `"max_tokens"`) pins a
fixed value. Otherwise `get_default_max_tokens(model)` chooses based on the model
id (see `kbcode/config.py`).

Live commands: `/temperature <0|0.01|...|1>|none`, `/thinking off|low|...|high`, `/maxtokens <n>|auto`.
`/thinking off` disables reasoning entirely (no effort passed to provider).
Thinking accepts off | low | medium | normal | high (normal→medium; stored as-is).
Pinned values (and auto state for max_tokens) are saved via `persist_global_tuning`.
See [[providers]] for how they reach the API calls.

`KBCODE_LOG_LEVEL` (a *string*, not an `_int()` knob; default `INFO`) drives the
diagnostic file log — `setup_logging(config.state_dir)` (`kbcode/logs.py`, called
from `kbcode/cli.py:399` right after `load_config`) attaches a rotating handler
at `~/.kbcode/projects/<slug>/kbcode.log` (the state dir) to the `kbcode`
logger. `DEBUG` = full traces for bug reports; `off`/`none`/`0` = write nothing.
It's separate from `TerminalUI` on-screen output and never raises (unwritable
path → no log, run continues). Modules log via `logging.getLogger(__name__)`.

## Project retargeting
`Config` (`kbcode/config.py:101`) derives every path (`kbcode_dir`, `kb_dir`,
`state_dir`, `memory_db`, `agent_md`, `settings_file`, ...) as a
property off `project_dir` — so the project can be retargeted live. The CLI
picks it via `-C`/`--dir`/`--project` (`_take_dir`, `kbcode/cli.py:259`) or
`init <path>`. In-chat `/open <folder>` (`kbcode/repl.py:566`) mutates
`config.project_dir` (`kbcode/repl.py:575`) then rebuilds `kb`, `memory`, and the
agent — re-scaffolding the new folder, keeping the same provider/model/key. A
REPL guard catches the common slip of typing the terminal-only `init`/`model`
as a chat message and points at `/open` instead.

See [[architecture]] for where `Config` sits in the CLI -> Agent -> Provider ->
Tools flow, [[cheatsheet]] for the exact commands.
