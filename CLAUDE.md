# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`kbcode` is a small, self-contained AI coding agent that runs in the terminal. It is itself built by blending ideas from five reference agents (cloned, for study only, into the gitignored `references/`): Claude Code (agentic loop + tools), Hermes (persistent memory/skills + context compaction), claude-kb (token-cheap `kb/` notes + `path:line` pointer checking), Kilo Code (modes), and openclaw (tool-call repair). When extending kbcode, the working assumption is that new capability comes from one of those concepts.

## Commands

- Install deps: `python -m pip install -r requirements.txt`
- Run the chat REPL: `python -m kbcode`
- One-shot task: `python -m kbcode "do the thing"` (add `-y` / `--yes` to auto-approve writes and commands)
- Work on a different project: `python -m kbcode -C "<path>"` (`-C`/`--dir`/`--project` set the project root; the agent's tools are confined to it, so this is how you target another repo without `cd`). The folder must exist.
- Scaffold a project: `python -m kbcode init` (creates `AGENT.md`, the `kb/` note set, `.kbcode/`) — accepts a path: `python -m kbcode init "<path>"`, or `python -m kbcode -C "<path>" init`.
- Configure provider/model interactively: `python -m kbcode model` (picks provider, takes a key, **auto-fetches** the model list, saves to `.kbcode/settings.json` + `.env`)
- There is **no test suite**. The de-facto check is byte-compilation: `python -m py_compile kbcode/*.py`. Logic is verified with throwaway inline scripts (construct `Tools`/`Agent`/`suggest()` and assert), not a framework.

### Windows / PowerShell notes (this is the dev environment)
- Set `PYTHONIOENCODING=utf-8` before running anything that prints the UI. The terminal uses emoji and em/box-drawing characters; the default cp1252 console raises `UnicodeEncodeError` on them. Output that flows through `rich` is usually fine; raw `print()` of those chars is not (which is why pointer-checker messages use ASCII `->`).
- Running `python -m kbcode` from another directory needs `PYTHONPATH` pointed at the repo root (the package isn't installed).

## Architecture — the big picture

The design goal is **provider-agnostic**: one agent loop drives Claude or any OpenAI-compatible model unchanged. Understanding the codebase means understanding how three things interact — the normalized message format, the provider translation layer, and the per-turn mode application.

### Normalized messages + the `raw` replay field (provider.py ↔ agent.py)
`Agent.messages` is a list of **normalized** items, never a provider's native shape:
- `{"role": "user", "content": str}`
- `{"role": "assistant", "text", "tool_calls": [ToolCall], "raw": <native>}`
- `{"role": "tool_results", "results": [{"id", "content", "is_error"}]}`

Each provider (`AnthropicProvider`, `OpenAICompatibleProvider`) translates this to/from its own API in `_to_native`, and stores the model's own assistant payload back in `raw` so the next request replays it **losslessly** (Claude thinking blocks vs OpenAI `tool_calls` differ structurally). A session uses exactly one provider, so `raw` is always that provider's shape. **Invariant to preserve:** the normalized↔native translation must round-trip, and user/assistant turns must stay alternating after any message-list surgery (see compaction).

`get_provider(config)` dispatches on `config.kind` (`"anthropic"` vs `"openai"`). Every non-Claude provider — OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, custom — is the *same* `OpenAICompatibleProvider` with a different `base_url`. Anthropic calls use a staged-fallback (`thinking`/`output_config` → `thinking` → plain) that catches `TypeError` for older SDKs.

### Modes apply per turn (modes.py + agent.py)
A `Mode` pairs instruction text with an allowed-tool set. `Agent.run` rebuilds two things on **every** model call from the current mode: `_system_for_mode()` (base system prompt + mode instructions) and `_mode_schemas()` (tool schemas filtered to what the mode allows). Enforcement is two-layer: disallowed tools are never shown to the model, *and* `run()` guards at execute time. Built-ins: `code`/`debug` (all tools), `architect` (read + notes), `ask` (read-only). Custom modes load from `.kbcode/modes/*.md`.

### Config precedence (config.py)
`load_config` resolves provider/model/base_url as **env vars > `.kbcode/settings.json` > preset defaults**. `PRESETS` is the source of truth for built-in providers. `Config` derives all paths (`kbcode_dir`, `kb_dir`, `memory_db`, `agent_md`, `settings_file`) from `project_dir`.

### Context stays cheap two ways
- **Compaction (compaction.py):** when `estimate_tokens(messages)` crosses `compact_threshold`, the middle exchanges are summarized into one recap spliced onto the first kept tail turn, protecting the first + last exchanges and preserving alternation. Auto in `Agent.run`; manual via `/compact`.
- **Knowledge base (knowledge_base.py):** `kb/` holds short notes loaded into the system prompt so the agent doesn't re-scan files. `check_pointers()` (`/kb-check`) resolves every `path:line` reference and flags missing files / stale line numbers; placeholder examples are skipped.

### Tools, repair, and the UI seam
- `Tools.execute` runs a `_repair()` step first (openclaw idea): unknown tool name → closest match via `difflib` + the tool list; missing required args → names them. This lets weaker models self-correct instead of hard-failing. Path access is confined to the project root via `_resolve()`. `write_file`/`edit_file`/`run_command` gate through `Permissions`.
- All terminal output goes through `TerminalUI` (ui.py) — the loop never calls `console.print` directly. `prompt_input.py` adds the `/` autocomplete popup via `prompt_toolkit`, but only on a TTY; `make_input` returns `None` (→ plain reader) when piped or when the lib is missing, so tests and pipes never break.

## When adding things

- **A new tool:** add its schema to `Tools.schemas` *and* a `_tool_<name>` method; if it should be restricted, add it to the right group (`READ`/`NOTES`/`EDIT`/`EXEC`) in modes.py, otherwise it's implicitly available everywhere.
- **A new slash command:** add it to `COMMANDS` in ui.py (single source for both `/help` and the autocomplete popup) and handle it in `_repl` (cli.py). Argument completion comes from the `arg_options` map passed to `make_input`.
- **A new provider:** prefer adding a `PRESETS` entry; only write a new `LLMProvider` subclass if it isn't OpenAI-compatible.

## Boundaries

- `references/` is cloned third-party source for studying concepts — **gitignored, not part of the product**. Never import from it or ship its code.
- `.kbcode/` (memory db, settings) and `.env` are gitignored, per-machine/secret. The README and `.env.example` document every provider and tuning env var.
