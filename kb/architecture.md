# Architecture — the main pieces and how they fit.

A single Python package (`kbcode/`) with one module per concern. The flow is:
CLI → Config → Agent loop ↔ Provider ↔ Tools → project files. The design goal is
**provider-agnostic**: one agent loop drives Claude or any OpenAI-compatible
model unchanged (see [[providers]]).

## Components

- `cli.py` — entry point + chat REPL + slash commands + `-C` / `init` / `/open`
- `wizard.py` — `model_wizard()`, the `kbcode model` provider/key/model setup flow
- `agent.py` — the agent loop (`Agent.run`), subagent delegation, `/insights`
- `provider.py` — `AnthropicProvider` + `OpenAICompatibleProvider` behind `LLMProvider` ABC ([[providers]])
- `tools/` — package (was `tools.py` pre-v1.6.0): `core.py` (`Tools`, `_repair`, `_resolve`), `file.py` (read/write/edit/list/search/run + background tasks `check_task`/`stop_background_tasks` + `_protected_reason`), `edit_strategies.py` (multi-strategy search/replace for edit_file: exact → strip-blanks → indent → fuzzy, [[edit-strategies]]), `kb.py`, `memory.py`, `planning.py`, `subagent.py`, `web.py` (`web_search` + `fetch_url`, [[gotchas]]), `mcp.py` (stdio MCP client + `MCPManager`, [[mcp]]), `schemas.py` ([[tools-and-repair]])
- `config.py` — `Config` dataclass, `load_config()`, provider presets, `~/.kbcode` settings; per-project runtime state lives in `Config.state_dir` = `~/.kbcode/projects/<slug>/`, project `.kbcode/` is config-only + self-gitignored ([[config]])
- `modes.py` — `Mode` dataclass + 4 builtins + custom mode loader from `.kbcode/modes/` ([[modes-subagents]])
- `subagents.py` — `Subagent` loader from `.kbcode/agents/*.md` + `builtin_subagents()` (autopilot, fixer) ([[modes-subagents]])
- `knowledge_base.py` — `KnowledgeBase` class, scaffold templates, `check_pointers()` + `fix_pointers()` ([[context-management]])
- `memory.py` — `Memory` class (SQLite, thread-safe: RLock + `check_same_thread=False` so parallel batches/subagents can `recall`), `remember`/`recall`/`save_skill`
- `prompts.py` — `build_system_prompt()` assembles system message from base + current date/time + standing orders + AGENT.md + kb + skills + memories
- `sessions.py` — `SessionRecorder` (JSONL per chat), `list_sessions`, `load_session`, `lifetime_stats` ([[sessions]])
- `compaction.py` — `compact()`: free trim of old tool outputs (pass 0), then summarizes old turns to stay within context window ([[context-management]])
- `repair.py` — `promote()` recovers tool calls written as plain text ([[tools-and-repair]])
- `pricing.py` — per-model USD cost tables for `/insights`
- `permissions.py` — approval gating (Yes/Always/No menu) + ask/auto permission MODES (Shift+Tab / `/auto`; auto = no prompts, no questions, autopilot/fixer builtin subagents) ([[safety]])
- `checkpoints.py` — shadow git store for auto pre-edit snapshots + `/rollback` ([[safety]])
- `hooks.py` — `HooksRunner`, user-scriptable PreToolUse/PostToolUse/Stop hooks from `settings.json` ([[safety]])
- `ui.py` — `TerminalUI` (Rich-based banner with provider+settings on right, markdown, tool lines, menus). Banner now shows current temp / thinking / max_tokens on the right side (in the previously empty area). Tool activity now uses clean high-level summaries (e.g. "Search ... → 5 matches", relative paths) so users can follow what the agent is doing without seeing raw code in the log.
- `prompt_input.py` — `/` autocomplete (commands + file-path completion for `/open`/`/image`/`/video` via `PATH_COMMANDS`; `/provider`/`/model` complete live model ids, fetched once per provider on `ThreadedCompleter`'s background thread and cached — `_model_completion_sources`, `kbcode/repl.py:97`) + arrow-key menus (prompt_toolkit)
- `logs.py` — `setup_logging(state_dir)`: quiet rotating file log at `~/.kbcode/projects/<slug>/kbcode.log` for field debugging (`KBCODE_LOG_LEVEL`, [[config]])
- `images.py` / `videos.py` / `vision_fallback.py` — clipboard/file image + video loading, auxiliary vision model fallback ([[vision]])
- `redact.py` — regex secret redaction for tool output ([[safety]])
- `interrupt.py` — Esc key interrupt watcher (Windows + POSIX) + `TypeAhead` (keep typing while the agent works: Enter queues the line, delivered to the model mid-turn) + mid-turn Shift+Tab mode toggle ([[providers]], [[safety]])

## Data / control flow
1. `main()` (`kbcode/cli.py:383`) → `load_config()` → `_build_agent()` → `repl()` (`kbcode/repl.py:251`)
2. User types a message → `Agent.run()` (`kbcode/agent.py:285`) → `Agent._complete()` (`kbcode/agent.py:162`) calls provider
3. Provider returns text + tool_calls → agent loop dispatches through `Agent._dispatch_tool()` (`kbcode/agent.py:237`), which runs `PreToolUse`/`PostToolUse` hooks around `Tools.execute()` (`kbcode/tools/core.py:102`) — built-ins via `_tool_<name>` methods, `mcp__*` names via the MCP fork ([[mcp]]) — see [[safety]]
4. Tool results appended → user messages typed mid-turn are piggybacked onto the last result (`_deliver_user_notes`, `kbcode/agent.py:689`) → loop repeats until no more tool_calls
5. Turn-end passes: KB drift check → Stop hook → auto-mode "don't ask, continue" nudge + fixer double-check ([[safety]])
6. Session recorded via `SessionRecorder`, auto-compacted when context grows

## Key invariant
`Agent.messages` is normalized, never a provider's native shape (`raw` replays
the native payload losslessly). Round-trip + alternating-turns must hold after
any message-list surgery (compaction, subagent delegation) — see [[providers]].

## Deep dives
[[providers]] · [[vision]] · [[modes-subagents]] · [[sessions]] · [[config]] ·
[[context-management]] · [[tools-and-repair]] · [[safety]] · [[mcp]]

See [[overview]] for setup, [[conventions]] for structure rules, [[about-kb]]
for how this KB is maintained.
