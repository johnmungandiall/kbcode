# Cheatsheet — commands and snippets you reach for most.

## Run / build / test
- `pip install -e .` — editable dev install
- `kbcode` or `kb` — start interactive chat
- `kbcode "do something"` — one-shot task
- `kbcode model` — setup wizard (provider + key + model)
- `kbcode init` — scaffold project (AGENT.md + kb/ + .kbcode/)
- `kbcode -c` — continue most recent saved session
- `kbcode --resume` — pick from past sessions
- `kbcode update` — upgrade from GitHub
- `kbcode --version` — show version

## Chat commands (type in chat)
- `/mode code|architect|ask|debug` — switch personality
- `/provider <name>` — switch model provider
- `/model <id>` — switch model
- `/status` — provider, model, mode, context size
- `/todo` — show task checklist
- `/kb` — list kb/ notes
- `/kb-check [--fix]` — verify/repair kb/ pointers
- `/insights` — token/cost usage
- `/compact` — summarize old turns
- `/rollback` — undo edits from checkpoint
- `/sessions` / `/resume` — session history
- `/image [path]` or Alt+V — attach image
- `/video <path>` — describe video via vision fallback

## Common tasks
- Add a tool → `tools.py` (schema in `_base_schemas` + `_tool_<name>` method)
- Add a provider → `provider.py` (new `LLMProvider` subclass + update `get_provider()`)
- Add a mode → `.kbcode/modes/<name>.md` with frontmatter
- Add a subagent → `.kbcode/agents/<name>.md` with frontmatter

See [[overview]] for first-time setup and [[gotchas]] for what to avoid.
