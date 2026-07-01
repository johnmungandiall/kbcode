# Overview

**kbcode** is a terminal-based AI coding agent (v1.4.2) that blends five ideas:
1. **Hands** (Claude Code) — reads/writes files, runs commands
2. **Memory + skills** (Hermes) — persistent SQLite memory across sessions
3. **Knowledge base** (claude-kb) — token-cheap `kb/` notes about the project
4. **Modes** (Kilo Code) — code/architect/ask/debug personalities with tool guardrails
5. **Tool-call repair** (openclaw) — fixes malformed calls from weaker models

Works with Claude (Anthropic SDK) and any OpenAI-compatible model (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, custom).

## Key entry points
- `kbcode/cli.py:797` — `main()` entry point, parses args, dispatches to wizard/init/REPL
- `kbcode/cli.py:380` — `_repl()` the interactive chat loop
- `kbcode/agent.py:37` — `Agent` class, the core tool-using loop
- `kbcode/tools.py:48` — `Tools` class, all tool implementations + schemas

## How to run
- `pip install -e .` (editable dev install) or `pip install git+https://github.com/johnmungandiall/kbcode.git`
- `kbcode init` then `kbcode model` then `kbcode` (or `kb`)
- Tests: no test suite found in repo

## Version
- `kbcode/__init__.py:9` — `__version__ = "1.4.2"`

See [[architecture]] for how the pieces fit, [[conventions]] for structure rules.
