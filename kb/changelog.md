# Changelog — notable changes, newest first.

The ONLY place release history lives (don't duplicate it in other notes).

## Unreleased

## v1.17.0 (2026-07-02) — flexible edit matching + post-edit lint + output-budget writes
- **Flexible search/replace with multiple strategies** (the Aider idea #3):
  `edit_file`/`edit_files` no longer fail when the model gets indentation
  slightly wrong or adds extra blank lines. New
  [kbcode/tools/edit_strategies.py](../kbcode/tools/edit_strategies.py)
  tries five strategies in order: exact → strip-blanks → indent →
  strip+indent → fuzzy (difflib, ≥70 %). Every strategy checks for
  uniqueness; the strategy name appears in the permission prompt and result.
  See [[edit-strategies]], [[tools-and-repair]].
- **Post-edit syntax check** (the Aider idea): every write_file/edit_file/
  edit_files result now carries a WARNING when the written file no longer
  parses (`lint_text` in the new `kbcode/lint.py` + `_lint_note` in
  tools/file.py) — .py/.json/.toml (+.yaml if PyYAML) via stdlib parsers
  only, no linter subprocess; a note on a successful write, never a failure,
  with an escape clause for deliberate piece-wise writes. See
  [[tools-and-repair]], [[gotchas]].
- **Output-budget-aware writes** ("okko model okkola untadhi"): the system
  prompt now tells the model its per-response output budget up front
  (`Agent._output_budget_note`, from the live model-aware
  `config.max_tokens`) so large files are written in pieces proactively, and
  the truncation repair coaching names concrete numbers ("limit 16,000
  tokens… keep each call under ~24,000 characters" —
  `_split_write_hint`/`_write_call_char_budget`) instead of "comfortably
  small". See [[tools-and-repair]].
- **Broken tool-call JSON no longer 400s the follow-up request** (live MiMo:
  a cut-off 70k-char write_file replayed verbatim → HTTP 400 "unexpected end
  of data", killing the repair round): `_replayable_args` stores the marker
  dict as valid JSON in `raw["tool_calls"]`, and `_sanitize_raw` guards
  pre-fix session payloads on replay. See [[providers]], [[gotchas]].

## v1.16.0 (2026-07-02) — auto mode, type-ahead, thinking display
- **Ask/auto permission modes** (Claude Code's Shift+Tab idea): `/auto` or
  **Shift+Tab** (at the prompt AND mid-turn) toggles; auto = no permission
  prompts, no questions — plus an auto-mode system note, a "convince the
  model" pass (`_auto_continue_feedback`: a turn may not end on a question),
  and builtin subagents **autopilot** (whole task end-to-end, every tool) and
  **fixer** (auto-reviews each editing turn's checkpoint diff and repairs
  defects — `_auto_fix_feedback`). See [[safety]], [[modes-subagents]].
- **Type-ahead while the agent works**: keystrokes echo live under the
  spinner (`TypeAhead` in interrupt.py + `ui.live_note`), Enter queues the
  message, and it's delivered to the model MID-TURN (piggybacked on the last
  tool result) with urgent-now/else-after-task triage; Esc hands unsent text
  back into the next prompt. See [[providers]], [[gotchas]].
- **"Write looks stuck" fixed for real** (Hermes tool-progress idea):
  `stream_tool_hint` no longer prints-and-kills the spinner; new
  `on_tool_args` streaming callback keeps a `writing the call… N chars`
  counter live while big write_file/edit_files arguments stream.
- **Truncated/malformed tool calls repaired properly**: provider
  `_parse_tool_args` marks them (`_malformed_args`/`_args_cut_off` +
  finish_reason=length detection) instead of silently passing `{}`; `_repair`
  explains the real cause and coaches splitting large writes; UI shows a
  yellow "call arrived incomplete → resend" instead of the red
  "missing required argument(s): path, content" spam.
- **Model thinking displayed**: reasoning streams into the spinner
  (`thinking… N chars of reasoning`), collapses to one `🧠 thought…` line per
  step, and `/thoughts` expands the full turn's reasoning
  (Anthropic thinking blocks; DeepSeek `reasoning_content`; OpenRouter `reasoning`).
- **search_code can no longer stall a turn** (live "running… 285s" fixer
  hang): the Python fallback walk now skips the project .gitignore's plain
  top-level dirs (`references/` etc. — `_gitignored_dirs`), and every search
  is capped by `_SEARCH_TIME_BUDGET` (30s) returning partial hits + a
  "narrow with 'path'" note. See [[gotchas]].
- Tests: new `tests/test_auto_mode.py` + search guards; suite now 428 tests,
  ruff clean.

## v1.15.0 (2026-07-02)
- **Replies render as markdown in the terminal** (user request): `stream_chunk`
  no longer prints raw chunks — it feeds a `writing… N chars` progress label
  into the still-live thinking spinner (`_TickingStatus.set_progress`), and
  `Agent.run` shows the complete reply via `ui.assistant_text` (Rich
  `Markdown`) once the response resolves. `stream_newline`/`_stream_open` are
  gone. See [[gotchas]] "Only ONE thread may write the terminal".
- **Fixed "write_file looks stuck" during permission prompts** (user report):
  the mid-turn permission menu was raced by (1) the `tool_running()` spinner's
  ticker redraw painting over it and (2) the Esc watcher thread eating its
  keystrokes (`msvcrt.getwch()`/`stdin.read()` vs the menu, key by key).
  `ui.permission` now stops the spinner and wraps the prompt in the new
  `interrupt.pause_escape_watcher()`. See [[safety]], [[gotchas]].
- **New `/copy [n]`:** copies the last reply's fenced code block (or block n;
  a reply with no blocks = the whole reply) to the system clipboard — the
  terminal's answer to a "copy button". New `kbcode/clipboard.py`
  (`extract_code_blocks` + `copy_to_clipboard`; `clip`/`pbcopy`/`wl-copy`/
  `xclip`/`xsel`, UTF-16 for Windows `clip.exe` so non-ASCII survives).

## v1.14.0 (2026-07-02)
- 2026-07-02 — **`KBCODE_MAX_STEPS=0` / `KBCODE_MAX_COMMANDS=0` now mean
  UNLIMITED** (that runaway guard is disabled): the agent loop switches to
  `itertools.count()` and the `run_command` cap check is skipped. The emergency
  context stop and `_SUBAGENT_MAX_STEPS` are unchanged. Documented in
  `.env.example` + README. See [[config]], [[safety]], [[gotchas]].
- **KB pointer check hardened** (from a live GrokProxy session that burned a
  ~150k-token turn on false drift): `0.0.0.0:8000`-style IP:port and URL
  host:port matches are no longer treated as `path:line`; check/fix now walk
  kb/ SUBFOLDERS too; relocation is case-insensitive with snake_case-first
  anchor priority. See [[context-management]], [[gotchas]].
- **Note versioning:** content-changing `kb_write` snapshots the old note into
  `kb/.history/`; new `/kb-undo <note>` restores it.
- **/init now refreshes the live system prompt** (via `cli._system_prompt`)
  so freshly built notes apply without a restart; banner also shows the
  `kb built / not built — /init` flag.
- **Budget-aware tool results:** `Agent._fit_to_budget()` caps one tool result
  at half the remaining pre-compaction budget (8k-char floor).
- **Session-line secret masking:** `SessionRecorder._write()` redacts every
  serialized JSONL line — covers secrets echoed in the model's own reply/raw
  blocks. See [[safety]].
- **System prompt teaches native MCP:** "install an MCP server" now points the
  model at `.kbcode/settings.json` `mcpServers` (+ `/mcp reload`), not IDE
  configs like `.cursor/mcp.json`.
- IMPROVEMENTS.md refreshed against v1.13.0 reality (open items only).

## v1.13.0 (2026-07-02)
- **First-run onboarding + `/init`:** new `/init` chat command scans the project
  (canned `_BUILD_KB_PROMPT`) and fills the kb/ notes with real facts; while the
  KB is still untouched templates (`KnowledgeBase.is_scaffold()`), the REPL prints
  a "type /init" hint at startup and after `/open`. Bare `init` in chat now points
  at `/init`. Closes IMPROVEMENTS.md 5.1. See [[context-management]].
- **KB built/not-built flag:** `is_scaffold()` is surfaced as `kb built` /
  `kb not built — /init` in `/status` and at the top of `/kb`.
- **Folder-awareness:** the system prompt now stamps a `## Project folder`
  section (absolute path + folder name, `build_system_prompt(project_dir=...)`)
  so the model always knows which project it is inside. See [[tools-and-repair]].
- **KB reminder is per-turn:** the "update the affected kb/ note" nudge after a
  code edit now fires once per TURN (was once per session), so long sessions
  keep the KB in sync. See [[context-management]].

## v1.12.1 (2026-07-02)
- Scaffold templates (`_TEMPLATES["overview"]` + `AGENT_MD_TEMPLATE`) now warn
  that an unbuilt KB does NOT mean an empty project — check real files
  (repo_map / list) first. Fixes a live MiMo session that declared a real
  project "empty" after seeing only fresh templates. See [[context-management]].

## v1.12.0 (2026-07-02)
- **New tools:** `fetch_url` (read a web page/API via stdlib urllib, HTML→text,
  no API key, parallel_safe) and `check_task`; `run_command` gained
  `background: true` (returns a `bg-N` task id at once, poll/kill via
  `check_task`, survivors killed at exit). See [[tools-and-repair]].
- **Parallel subagents by default:** `Memory` is now thread-safe (RLock +
  `check_same_thread=False`), `recall` is `parallel_safe`, and the default
  `tools: read` subagent set qualifies for concurrent `run_subagent` dispatch
  (`_SUBAGENT_PARALLEL_EXTRAS` tolerates `manage_todos`). See [[modes-subagents]].
- **Compaction pass 0:** `_trim_old_tool_results()` shrinks bulky old tool
  outputs for free (no LLM call) before any summarizing; if that alone lands
  under `threshold * 0.8` the summary passes are skipped. See [[context-management]].
- `repo_map` added to the READ tool group (was missing — ask/architect modes
  couldn't use it); `EXEC` now = `run_command` + `check_task`.

## v1.11.1 (2026-07-02)
- **run_command can no longer hang forever.** Output now goes to temp files
  instead of pipes (a grandchild like a relaunched `explorer.exe` inheriting
  pipe handles used to block the EOF read indefinitely — seen live at 3142s
  despite `timeout=180`), `stdin` is `DEVNULL`, and on timeout the whole
  process tree is killed (`taskkill /F /T` / `os.killpg`) with partial output
  still returned. See [[safety]], [[gotchas]].
- **`~/.kbcode` now exists from the first run.** `main()` creates it at
  startup, and `upsert_env_value()` creates missing parent folders — the `kb
  model` wizard used to crash writing the API key to a not-yet-existing
  `~/.kbcode/.env` on a fresh install.
- README: new "🗑️ Uninstall" section (package / global data / per-project
  leftovers, in that order).

## v1.11.0 (2026-07-02)
- Thinking now supports `off` — use `/thinking off` or `KBCODE_THINKING=off` (also accepts `none`/`disable`). When off, no reasoning/thinking blocks are sent to Claude or OpenAI reasoning models.
- Banner now shows current tuning settings on the right: `temp`, `thinking`, and `max_tokens` (fills the previously empty panel area).
- Temperature input is now restricted to 0–1 range with 0.01 steps (`/temperature 0.01`, `0.5`, etc.). Values are rounded to 2 decimals and displayed as e.g. `0.00` / `0.50`.
- `/maxtokens` and model-aware `max_tokens` from previous work.

## v1.10.0 (2026-07-02)
- `max_tokens` now automatically follows the model (`get_default_max_tokens` in config.py). Different sensible output limits for Claude 4/Sonnet, GPT-4o/o-series, DeepSeek, Gemini, etc. (fallback 16000). Setting `KBCODE_MAX_TOKENS` or settings.json `"max_tokens"` pins it. `/model` switches now auto-adjust max_tokens (unless pinned). New `/maxtokens <n>|auto` command + shown in `/status`. `persist_global_tuning` also covers max_tokens.
- **MCP support (stdio, tools only)** — new `kbcode/tools/mcp.py`: a lean
  newline-JSON-RPC stdio client (no SDK, no new deps;
  `initialize`/`tools/list`/`tools/call` only) + `MCPManager`. Servers come
  from a Claude Code-compatible `mcpServers` block in settings.json, merged PER
  SERVER across home→launch→project (the only deep-merged settings key). Tools
  appear as `mcp__server__tool` in `Tools.schemas` (repair + parallel_safe work
  for free); dispatch forks on the prefix into `_execute_mcp` — permission
  prompt by default, checkpoint before mutating calls, redaction on results;
  `read_only`/`trusted` config relaxes per server/tool. `/mcp [reload]`
  command, startup notice, `/status` line; `Agent.close()` stops servers (no
  leak across `/provider` rebuilds) with an atexit backstop.
  `tools/list_changed` notifications are discarded — reload to pick up changed
  tool sets. Tests: `tests/test_mcp.py` end-to-end against
  `tests/fake_mcp_server.py`. See [[mcp]].
  Follow-up fix: an `mcpServers` block added mid-session did nothing — servers
  only started at launch and `/mcp` said "no MCP servers configured" until
  restart. `/mcp reload` now re-reads the merged block from disk (new
  `load_mcp_servers()` helper, also used by `load_config`) and bootstraps the
  manager if none existed.
- **Anthropic prompt caching now covers the conversation, not just
  system+tools** — `_add_cache_breakpoints()` marks the newest 3 user-role
  native messages with `cache_control`, so each tool round-trip re-reads the
  prior history from cache (~0.1x input price) instead of full price; this was
  the dominant cost of long agentic turns. `_usage()` folds the API's separate
  cache-token counts back into `input_tokens` so /cost stays comparable.
  Anthropic provider only. Tests: `tests/test_provider_caching.py`.
- **Streaming now shows tool names as they're composed** — new `on_tool`
  callback on `provider.stream()` (both providers) feeds
  `ui.stream_tool_hint()`, printing a dim `⏺ <name> …` line the moment a tool
  call starts streaming, so long tool-heavy responses no longer look frozen.
  The Anthropic stream switched from `text_stream` to event iteration for this.
- **New `/diff [n]` command** — show the working tree vs a checkpoint (no `n` =
  newest) without leaving the REPL; same shadow-git plumbing as `/rollback
  diff`, now one obvious command.
- **Per-project runtime state moved to `~/.kbcode/projects/<slug>/`** (Claude
  Code's `~/.claude/projects` layout) — memory.db, sessions/, the checkpoints/
  shadow repo, input history, and kbcode.log no longer land in the project's
  `.kbcode/` (they used to show up as ~80 untracked files in the host project's
  git). New `Config.state_dir` + `project_slug()`; a project carrying a legacy
  `.kbcode/memory.db` keeps its local dir so nothing is lost. The project
  `.kbcode/` is now config-only (settings.json, standing-orders.md, agents/,
  modes/, prompts/, .env) and self-hides via an auto-written `*` .gitignore
  (`_ensure_self_ignore`). New `KBCODE_HOME` env var overrides `~/.kbcode`
  (used by the new autouse fixture in `tests/conftest.py`); documented in
  README + .env.example.
- **Runaway-loop guards are now tunable** — the per-message step cap and the
  per-turn `run_command` cap moved to `Config.max_steps` /
  `Config.max_commands_per_turn`, overridable via `KBCODE_MAX_STEPS` /
  `KBCODE_MAX_COMMANDS` in `.env`. Both stop messages now name the cap and say
  how to raise it. Defaults unchanged.
- **Model autocomplete is now instant across sessions** — model lists are cached
  to `~/.kbcode/models/<provider>.json` (24h TTL). On the first keystroke,
  autocomplete reads the disk cache so there's no network delay.
- **Autocomplete UX improved** — current provider/model shows a `● current`
  marker in the popup so you can see at a glance what's active.
- **`/model` now persists** — switching models from the REPL saves to the
  global `~/.kbcode/settings.json` (cross-project default), same as
  `/provider`. Before this fix, `/model` changes were lost on restart.
- **`/provider` and `/model` save cross-project** — they now write only to
  global `~/.kbcode`, not to the project `.kbcode`. That way switching in one
  project becomes your default everywhere, while a project explicitly configured
  via `kb model` still keeps its own override.
- **`kb model` selection actually sticks** — it now correctly persists so the
  immediately following `kb` shows/uses the chosen provider+model. It writes
  the choice to both global and the project's `.kbcode/settings.json`; when a
  project `.env` had `KBCODE_PROVIDER` etc pins it updates them too (otherwise
  env vars would silently win).

## v1.9.12
- Release prep + polish:
  - Added unit tests covering the new high-level `tool_result` summaries (search/read/list/repo_map) and long-pattern truncation in `_describe_tool`.
  - Fixed stale version strings across docs (overview intro, README badge, KB pointers) for release hygiene.
  - Direct execution verification + import smoke of UI/agent/tools for the recent changes.
- **UX (from 1.9.11 carried)**: Agent activity log is now user-friendly: clean counts instead of raw internal code/match lines. Paths relative, patterns truncated. Users can finally tell what the agent is doing (e.g. `Search ... ↳ 7 matches`, `Read some_file.py:<line>+ ↳ 42 lines`).

## v1.9.11
- `read_file` now supports `offset` (1-based) + `limit` for reading slices of large files. Range reads use efficient line-by-line streaming (no full file load) to avoid the old shell-chunking pattern (`powershell Get-Content | Select -Skip`). Still respects context budget and preserves original line numbers in output. Directly addresses step-limit issues on huge files (e.g. 2000+ line main.dart). UI display updated, tests added.
- **UX: agent actions are now understandable at a glance**. Tool result lines no longer leak raw code snippets or match lines (`↳ def foo()...`). `search_code`/`read_file`/`list_dir` etc. now render high-level counts ("12 matches", "87 lines", "3 entries"). Long search patterns are truncated. Paths prefer relative (cleaner logs on Windows). The visible activity trace (`⏺ Search ... ↳ N matches`) now clearly communicates what the agent is exploring without exposing internal data.
- Updated documentation in tools-and-repair.md, changelog, and overview.

## v1.9.10
- **Further exploration improvements**:
  - `search_code` now supports `limit` parameter (default 50) to prevent dumping too many results that lead to more loops.
  - `repo_map` significantly improved: prefers ripgrep (rg) when available for faster and more accurate symbol extraction, limits to ~5 symbols per file for clean output, better fallback.
  - `code-explorer` subagent now explicitly includes `repo_map` and stronger instructions.
  - More examples and emphasis in core system prompt for scoped, efficient searches (e.g., broker comparisons).
  - Updated documentation in gotchas and tools-and-repair.

- Previous anti-loop and interrupt fixes from 1.9.9 carried forward.

## v1.9.9
- **Prevent search/exploration loops + better Esc handling** — updated prompts
  and tool descriptions to force efficient exploration: always start with
  `repo_map` (scoped), use `search_code` with `path` to narrow (e.g. specific
  broker subdirs), batch multiple scoped searches, and stop/summarize as soon
  as the pattern is found. No more repetitive "search ... in broker/xxx" loops.
  - Improved interrupt handling in `Agent.run` so Esc (KeyboardInterrupt)
    always prints a clean "interrupted." notice + accurate `_turn_summary`
    with actions so far (fixes weird "reversed/reset progress" display on
    interrupt).

## v1.9.8
- **New `edit_files` tool** — perform multiple precise search/replace edits
  across files in a single call (with one combined permission prompt showing
  diffs). Inspired by Zed's strong multi-file AI editing after cloning and
  studying the reference repo.
  - Updated EDIT mode group and system prompts to leverage it for coordinated
    changes.

## v1.9.7
- **New `repo_map` tool** — added a structural codebase map tool (inspired by
  Aider's excellent repository map after studying the cloned reference).
  Returns key files, classes, functions, and signatures to help the agent
  understand large projects efficiently without reading every file.
  - Updated system prompt and `code-explorer` subagent to use `repo_map`
    first for smarter, faster exploration.
  - Tool is parallel-safe and works well with batching.

## v1.9.6
- **Auto-compaction now works better** — default raised from 12k to 80k tokens
  (more sensible for modern large-context models like Claude/Gemini). Also
  loads "compact_tokens" from .kbcode/settings.json (env var still wins if set).
  Auto now triggers for realistic conversation sizes instead of too early or
  never. Also added proactive check before each model call in long turns.

## v1.9.5
- **Better `kb update` on Windows** — added clear guidance when running `kb update`.
  If the update fails with "file is being used by another process" (common on
  Windows because `kb.exe` is locked while the command runs), it now prints
  instructions to close the window and retry in a fresh Command Prompt, plus
  a ready-to-paste manual pip command. This helps users successfully get
  the latest version.

## v1.9.4
- **Cursor-like speed improvements** (make kbcode feel much faster):
  - `_PARALLEL_MAX_WORKERS` increased 8 → 16 (more concurrent reads).
  - Added explicit "batch many tools together in one response" rule to the
    core system prompt so the model uses parallelism aggressively.
  - Rewrote the `code-explorer` subagent to be a fast parallel explorer
    (strongly tells it to call 4-10 tools at once, Cursor-style).
  - Documentation updated.

  Result: fewer slow LLM round-trips during exploration and reading. Works
  best with fast models (Claude, Gemini Flash, etc.).

## v1.9.3
- **Parallel reads inside subagents + faster code-explorer** — subagents now
  batch consecutive `parallel_safe` tools (`read_file` + `list_dir` + `search_code`
  etc.) using `_run_subagent_parallel_batch`, the same way the main loop does.
  Updated default `.kbcode/agents/code-explorer.md` to use a narrow parallel-safe
  tool list and explicit instructions to request multiple reads together. This
  greatly reduces LLM round-trips for exploration tasks on slow models.
  Documentation updated in [[modes-subagents]] and `subagents.py`.
- **Higher `run_command` safety cap** (`kbcode/tools/file.py`) — raised
  `_MAX_COMMANDS_PER_TURN` from 10 to 25 so realistic build/check/fix
  workflows ("flutter analyze", multi-step verification, logs + retries, etc.)
  no longer immediately hit the "runaway loop guard" and force an early turn
  wrap-up. The guard and the "wrap up and continue in next message" message
  remain for true loops. Tests now import the constant to avoid drift; README
  and [[gotchas]] updated. (User-visible fix → version bump per rules.)

## v1.9.1
- **`kbcode update` now actually delivers new code** (`kbcode/cli.py`
  `_self_update`) — the old command ran a bare `pip install --upgrade
  git+URL`, which pip treats as "already satisfied" (a silent no-op) whenever
  `__version__` is unchanged, so any fix pushed to GitHub without a version
  bump never reached installed users even though the update "succeeded". They
  stayed on stale code while a dev running `python -m kbcode` from the updated
  source tree saw the fix — the classic "works from source, broken when
  installed" report. Now runs two pip steps: a normal `--upgrade` (to pick up
  new/bumped deps) then `--upgrade --force-reinstall --no-deps --no-cache-dir`
  on kbcode itself so the current GitHub HEAD is rebuilt every time regardless
  of the version string. README's "Update & version" section documents a
  one-time manual `--force-reinstall` for users stuck on ≤ 1.9.0 (whose old
  update command can't self-heal until they bump past the no-op). See
  [[cheatsheet]].

## v1.9.0
- **System prompt now stamps the current date/time** (`kbcode/prompts.py`) —
  `build_system_prompt()` injects a `## Current date & time` section
  (`datetime.now()`, injectable via a `now:` kwarg for tests) telling the
  model its training data can be stale and to use `web_search` instead of
  guessing for news/current-events/recent-version/price questions. Fixes the
  model composing search queries with a guessed, wrong-year date. See
  [[tools-and-repair]].
- **Configurable hooks timeout** (`kbcode/hooks.py`) — `HooksRunner`'s
  per-command `subprocess` timeout (30s default) can now be overridden via a
  `"timeout"` key in the `"hooks"` block of `.kbcode/settings.json` (e.g.
  `"hooks": {"timeout": 60, "PreToolUse": [...]}`); an explicit constructor
  arg still wins (used by tests). No caller changes needed since
  `ToolsCore.__init__` already builds `HooksRunner(config.hooks, self.root)`
  without passing a timeout. See [[safety]].
- **Concurrent `run_subagent` dispatch** (#4.3 extension, `kbcode/agent.py`) —
  a run of 2+ consecutive `run_subagent` calls now dispatches concurrently
  (same `ThreadPoolExecutor`/`_PARALLEL_MAX_WORKERS` mechanism as the
  existing read-only-tool batching), but only when every targeted subagent's
  `tools:` frontmatter is a subset of the schema-declared `parallel_safe`
  tool set (`Agent._subagent_parallel_safe`) — the default `tools: read`
  does not qualify. `Agent._record_usage()` is now lock-guarded
  (`Agent._usage_lock`) since usage can be recorded from multiple subagent
  pool threads at once; `_run_subagent()` gained a thread-local quiet flag
  (`Agent._quiet_subagents`) so its inline UI output is suppressed when
  running inside a parallel batch, byte-for-byte unchanged on the normal
  sequential path. No new tool, no schema change, no LLM call added. See
  [[tools-and-repair]], [[modes-subagents]].
- **Hooks system** (`kbcode/hooks.py`, the Claude Code idea) —
  PreToolUse/PostToolUse/Stop tool-call interception via a `"hooks"` key in
  `.kbcode/settings.json`, reimplementing Claude Code's public documented
  hooks contract (JSON-over-stdin, exit-code protocol: 0 allow / 2 block /
  other non-fatal) from scratch. `ToolsCore` builds a `HooksRunner` per
  project; `Agent._dispatch_tool()` wraps every tool call (6 call sites as
  of the concurrent-subagent extension above, including subagent
  delegation) with Pre/PostToolUse, and `Agent._stop_hook_feedback()` lets a
  `Stop` hook veto ending a turn. See [[safety]].

## v1.8.0
- **`web_search` tool** (`kbcode/tools/web.py`) — the Hermes web-search idea,
  right-sized to one backend instead of its multi-provider plugin registry.
  DuckDuckGo search via the free `ddgs` package, no API key needed.
  Read-only/`parallel_safe`, available in every mode's `READ` group. A
  throwaway single-worker thread pool enforces a hard 20s timeout since
  `ddgs` can't be cancelled mid-call (see [[gotchas]]). `ddgs>=9.0` is now a
  hard dependency.

## v1.7.0
Three review-driven improvements (none is a bug fix; the "bug" findings they came
with were verified false against the code):
- **#6 parallel-safe tools are now schema-declared.** Each pure-read tool carries
  `"parallel_safe": True` (`tools/schemas.py`); `Agent` reads the set via
  `ToolsCore.parallel_safe_tools` instead of a hardcoded list, so a new read-only
  tool can't silently run sequential. `AnthropicProvider._api_tools` strips the
  flag before the request (OpenAI path already rebuilds tools).
- **#5 diagnostic file log.** `logs.py` `setup_logging()` writes a quiet rotating
  log at `.kbcode/kbcode.log` (`KBCODE_LOG_LEVEL`, default INFO; off/none = none).
  Wired in `cli.py`; silent swallow points (checkpoints, compaction, tool errors)
  now log with `exc_info`.
- **#9 file-path autocomplete** for `/open`/`/image`/`/video` (`PATH_COMMANDS` +
  `_path_completions` in `prompt_input.py`), on top of slash-command completion.

## KB audit — 2026-07-01
`tools/kb-check.sh --fix`/`--freshness` reported 0 broken/stale/drift (133
pointers). Manual spot-check of ~60 `Name (path:line)` pointers (name-match not
covered by the checker for that style) found one real miss: `architecture.md`
named `_repl()` where the function is `repl()` — fixed. Added `wizard.py` to
the component list (existed in code, missing from the map) and documented the
new `.claude/hooks/kb_*.py` enforcement hooks in `about-kb.md` (committed this
session, undocumented). No other drift found.

## v1.6.3
- Fix "agent freezes for minutes" on slow/stalled providers (esp. MiMo + a
  subagent making many calls): the SDK clients were built with no request
  timeout, so a stalled call inherited the SDK's ~600s default. Added
  `Config.request_timeout` (default 120s, `KBCODE_REQUEST_TIMEOUT`, 0 = off),
  passed to both provider clients via `LLMProvider._client_kwargs()`; the
  resulting timeout is transient so `_with_retry` backs off and retries.
- Fix "can't type after a reply" (intermittent, Windows-visible): the Esc
  watcher (`interrupt_on_escape`) only signalled its daemon thread at turn end
  without joining it, so the watcher kept reading the console and raced the next
  prompt for stdin, eating the first keystrokes (POSIX: could leave cbreak). Now
  it `thread.join()`s before returning. Also made `_TickingStatus.stop()`
  lock-guarded so the worker + main thread can't tear the spinner's Rich `Live`
  down at once. Regression test: `tests/test_interrupt.py`.

## v1.6.2
- Fix streamed replies rendering as shredded line-fragments (only the tail of
  each line survived — hit tables and plain prose alike). The thinking spinner
  is a Rich `Live` region redrawn from a background ticker thread; leaving it
  live while reply text streamed in from the provider worker thread meant two
  threads wrote the terminal at once and the spinner's redraw stomped each
  half-printed line. `ui.stream_chunk` now stops the spinner on the first token
  (`_TickingStatus.stop`, idempotent + thread-safe) so only one writer remains.

## v1.6.1
- Fix packaging: `pyproject.toml` only declared the top-level `kbcode`
  package, so the `tools/` subpackage (split out of `tools.py` in v1.6.0)
  was silently missing from every `pip install`, making `kbcode`/`kb` crash
  on launch with `ModuleNotFoundError: No module named 'kbcode.tools'`.
  Switched to `[tool.setuptools.packages.find]` so all `kbcode*` subpackages
  are always included.

## v1.6.0
- pytest suite (~211 tests) + GitHub Actions CI across Python 3.10/3.12 on
  Ubuntu/Windows.
- Streaming responses for both Anthropic and OpenAI-compatible providers
  (`provider.py` `stream()`).
- Safety rails: dangerous-command blocklist, per-turn `run_command` limit,
  system-path write warnings, colored diff previews before
  `write_file`/`edit_file`/`kb_write`.
- `kb_search`, memory kind filtering + `/memory-prune`, session full-text
  search + `/export`, `/cost`, `/ping`, an Ollama preset.
- Parallel execution for read-only tool calls, a context-aware step budget,
  token-budget-aware file reads, ripgrep-accelerated search, cached KB reads,
  batched checkpoints.
- Custom prompt fragments (`.kbcode/prompts/`), redaction audit counts,
  persistent command history, multi-line input.
- `tools.py` split into a `tools/` package; `cli.py` split into
  `cli.py` + `repl.py` + `wizard.py`.
- System prompt now tells the model to answer broad "read/explain the
  codebase" requests from `kb_read()`/`list()` instead of opening every
  source file in one turn (fixes a mid-turn emergency-stop on such prompts).

## v1.5.0
- Tool-execution spinner (`ui.tool_running()`) — a running command no longer
  looks stalled between the `⏺ Run …` line and its result.
- Every spinner (`thinking`/`tool_running`/`working`) now ticks up its own
  elapsed seconds live, plus a `(total …s)` counter that keeps running across
  the whole turn instead of resetting per step (`ui._TickingStatus`,
  `Agent.run` calls `ui.turn_started()`).
- `Read` tool-call lines now show the full resolved path, matching
  `Write`/`Edit` (`ui._describe_tool`).

## v1.4.2
- Knowledge base scaffolded with full project notes.
- See `kbcode/__init__.py:9`.
