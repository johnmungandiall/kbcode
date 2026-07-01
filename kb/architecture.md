# Architecture — the main pieces and how they fit.

A single Python package (`kbcode/`) with one module per concern. The flow is:
CLI → Config → Agent loop ↔ Provider ↔ Tools → project files.

## Components

- `cli.py` — entry point + chat REPL + slash commands + `-C` / `init` / `/open`
- `agent.py` — the agent loop (`Agent.run`), subagent delegation, `/insights`
- `provider.py` — `AnthropicProvider` + `OpenAICompatibleProvider` behind `LLMProvider` ABC
- `tools.py` — 12 tools (read/write/edit/list/search/run + kb/memory/todos/subagent)
- `config.py` — `Config` dataclass, `load_config()`, provider presets, `~/.kbcode` settings
- `modes.py` — `Mode` dataclass + 4 builtins + custom mode loader from `.kbcode/modes/`
- `subagents.py` — `Subagent` loader from `.kbcode/agents/*.md`
- `knowledge_base.py` — `KnowledgeBase` class, scaffold templates, `check_pointers()` + `fix_pointers()`
- `memory.py` — `Memory` class (SQLite), `remember`/`recall`/`save_skill`
- `prompts.py` — `build_system_prompt()` assembles system message from base + standing orders + AGENT.md + kb + skills + memories
- `sessions.py` — `SessionRecorder` (JSONL per chat), `list_sessions`, `load_session`, `lifetime_stats`
- `compaction.py` — `compact()` summarizes old turns to stay within context window
- `repair.py` — `promote()` recovers tool calls written as plain text
- `pricing.py` — per-model USD cost tables for `/insights`
- `permissions.py` — approval gating (Yes/Always/No menu)
- `checkpoints.py` — shadow git store for auto pre-edit snapshots + `/rollback`
- `ui.py` — `TerminalUI` (Rich-based banner, markdown, tool lines, menus)
- `prompt_input.py` — `/` autocomplete + arrow-key menus (prompt_toolkit)
- `images.py` — clipboard/file image loading + base64 encoding
- `videos.py` — video file loading for auxiliary vision fallback
- `vision_fallback.py` — describes images/video with a separate vision model
- `redact.py` — regex secret redaction for tool output
- `interrupt.py` — Esc key interrupt watcher (Windows + POSIX)

## Data / control flow
1. `main()` → `load_config()` → `_build_agent()` → `_repl()`
2. User types a message → `Agent.run()` → `Agent._complete()` calls provider
3. Provider returns text + tool_calls → agent loop dispatches to `Tools.execute()`
4. Tool results appended → loop repeats until no more tool_calls
5. Session recorded via `SessionRecorder`, auto-compacted when context grows

See [[overview]] for setup; [[conventions]] for structure rules.
