# Conventions — how code and notes here are structured.

## Language & style
- Python 3.10+, type hints, dataclasses over dicts for domain objects
- Each module is self-contained (one file = one concern, ~100-400 lines)
- `from __future__ import annotations` at the top of every module
- Tool methods follow `_tool_<name>(self, inp: dict) -> str` pattern

## Module organization
- Tools register via `_base_schemas` property + `_tool_*` methods (`tools.py:92`)
- Provider dispatch: `get_provider()` returns `AnthropicProvider` or `OpenAICompatibleProvider` (`provider.py:330`)
- Mode/subagent definitions: YAML frontmatter between `---` fences + markdown body

## Notes rules
- ≤ 50 lines, `path:line` refs, `[[cross-link]]`, one fact per place
- Cite function/class names as durable anchors (line numbers drift)

## Testing
- No formal test suite in the repo

See [[gotchas]] for what breaks if you ignore these.
