# Conventions — how code and notes here are structured.

## Language & style
- Python 3.10+, type hints, dataclasses over dicts for domain objects
- Each module is self-contained (one file = one concern, ~100-400 lines); the
  one exception is `tools/`, split into a package in v1.6.0 (see [[changelog]])
- `from __future__ import annotations` at the top of every module
- Tool methods follow `_tool_<name>(self, inp: dict) -> str` pattern

## Module organization
- Tools register via `_base_schemas` property (`kbcode/tools/core.py:77`) +
  `_tool_*` methods across `kbcode/tools/{file,kb,memory,planning,subagent,web}.py`
- Provider dispatch: `get_provider()` returns `AnthropicProvider` or `OpenAICompatibleProvider` (`kbcode/provider.py:489`) — see [[providers]]
- Mode/subagent definitions: YAML frontmatter between `---` fences + markdown body — see [[modes-subagents]]

## When adding things
- **A new tool:** add its schema to `Tools._base_schemas` *and* a `_tool_<name>`
  method; if it should be restricted, add it to the right group (`READ`/
  `NOTES`/`EDIT`/`EXEC`) in `modes.py`, otherwise it's implicitly available
  everywhere. If it's a **pure read** (no permission prompt / mutation /
  checkpoint / shared SQLite), also set `"parallel_safe": True` on its schema so
  it can batch concurrently (#4.3, see [[tools-and-repair]]). (A schema that
  depends on runtime state, like `run_subagent`, is appended in the `schemas`
  property instead — see [[tools-and-repair]].)
- **A new slash command:** add it to `COMMANDS` in `ui.py` (single source for
  `/help` + autocomplete) and handle it in `repl()` (`repl.py`). Argument
  completion comes from the `arg_options` map passed to `make_input`. Pass any
  command label with `[...]`/`<...>` hints as a `Text` object, not raw markup.
- **A new subagent or mode:** ship a markdown file (`.kbcode/agents/*.md` or
  `.kbcode/modes/*.md`) with `description:`/`tools:` frontmatter — no code
  change needed. A starter `code-explorer` subagent is scaffolded by
  `cli._scaffold` (`kbcode/cli.py:65`).
- **An interactive picker:** reuse `prompt_input.select()` (returns
  `(available, index)`); always handle `available is False` with a
  non-interactive fallback, as `TerminalUI.permission` does.
- **A new provider:** prefer adding a `PRESETS` entry (`kbcode/config.py:26`); only
  write a new `LLMProvider` subclass if it isn't OpenAI-compatible.

## Notes rules
- ≤ 50 lines, `path:line` refs, `[[cross-link]]`, one fact per place
- Cite function/class names as durable anchors (line numbers drift)
- Full KB-maintenance rules (auto-update, drift, runbooks, user map): [[about-kb]]

## Testing
- `pytest` (`tests/`, 23 files) + `ruff` lint, both run in CI (`.github/workflows/ci.yml`)
- No inline-script fallback needed anymore — write a `tests/test_*.py` case

See [[gotchas]] for what breaks if you ignore these, [[architecture]] for the component map.
