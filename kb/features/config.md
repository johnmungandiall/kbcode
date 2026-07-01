# Config — precedence, presets, project retargeting.

## Precedence
`load_config()` (`kbcode/config.py:195`) resolves provider/model/base_url and the API
key (via `.env`) as: **env vars > the project's `.kbcode`/.env > the launch
folder's > the global `~/.kbcode` (`global_dir()`, `kbcode/config.py:174`) > preset
defaults**. `.env` files are loaded highest-priority-first since `load_dotenv`
never overrides an already-set value; `settings.json` is merged the opposite
way (low->high, `kbcode/config.py:216-220`). The launch-folder and global fallbacks are
what let you configure kbcode once (`python -m kbcode model`, which saves to
`~/.kbcode`) and then `-C` it at any project without re-entering the key there.
`PRESETS` (`kbcode/config.py:26`) is the source of truth for built-in providers
(anthropic, openai, gemini, deepseek, openrouter, mimo, ollama, custom).

## Project retargeting
`Config` (`kbcode/config.py:87`) derives every path (`kbcode_dir`, `kb_dir`,
`memory_db`, `agent_md`, `settings_file`, `standing_orders_file`, ...) as a
property off `project_dir` — so the project can be retargeted live. The CLI
picks it via `-C`/`--dir`/`--project` (`_take_dir`, `kbcode/cli.py:226`) or
`init <path>`. In-chat `/open <folder>` (`kbcode/repl.py:444`) mutates
`config.project_dir` (`kbcode/repl.py:453`) then rebuilds `kb`, `memory`, and the
agent — re-scaffolding the new folder, keeping the same provider/model/key. A
REPL guard catches the common slip of typing the terminal-only `init`/`model`
as a chat message and points at `/open` instead.

See [[architecture]] for where `Config` sits in the CLI -> Agent -> Provider ->
Tools flow, [[cheatsheet]] for the exact commands.
