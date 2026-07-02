# Overview

**kbcode** is a terminal-based AI coding agent (v1.13.0) that blends five ideas
(cloned for study, gitignored, into `references/`):
1. **Hands** (Claude Code) — reads/writes files, runs commands
2. **Memory + skills** (Hermes) — persistent SQLite memory across sessions
3. **Knowledge base** (claude-kb) — token-cheap `kb/` notes about the project
4. **Modes** (Kilo Code) — code/architect/ask/debug personalities with tool guardrails
5. **Tool-call repair** (openclaw) — fixes malformed calls from weaker models

Works with Claude (Anthropic SDK) and any OpenAI-compatible model (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, Ollama, custom).
Can also connect to external **MCP servers** (stdio, tools only) and expose
their tools as built-ins — see [[mcp]].

## Key entry points
- `kbcode/cli.py:381` — `main()` entry point, parses args, dispatches to wizard/init/REPL
- `kbcode/repl.py:222` — `repl()` the interactive chat loop
- `kbcode/agent.py:78` — `Agent` class, the core tool-using loop
- `kbcode/tools/core.py:26 — `ToolsCore`/`Tools`, all tool implementations + schemas

See [[architecture]] for the full component map and its "Deep dives" links into
the `kb/features/` notes.

## How to run
- `pip install -e .` (editable dev install) or `pip install git+https://github.com/johnmungandiall/kbcode.git`
- `kbcode init` then `kbcode model` then `kbcode` (or `kb`)
- Tests: `pytest` (30 files under `tests/`, CI in `.github/workflows/ci.yml`)

See [[cheatsheet]] for the full command list.

## Version
- `kbcode/__init__.py:9` — `__version__ = "1.13.0"`; release history in [[changelog]]

last indexed: 2026-07-02 (unreleased: KBCODE_MAX_STEPS/KBCODE_MAX_COMMANDS 0 = unlimited)

See [[architecture]] for how the pieces fit, [[conventions]] for structure rules,
[[about-kb]] for KB-maintenance rules, [[about-you]] for user preferences.
