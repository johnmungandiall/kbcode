# Glossary — project-specific terms.

- **Normalized message format** — provider-agnostic message shape used by the agent loop (`provider.py:8-15`)
- **Tool-call repair** — two-layer fix: execute-time name/arg repair + parse-time plain-text recovery
- **Promote** — recovering tool calls a model wrote as text into real `tool_calls` (`repair.py:48`)
- **Compaction** — summarizing old chat turns to stay within context window (`compaction.py:104`)
- **Shadow git** — isolated git store for auto pre-edit snapshots (`checkpoints.py:54`)
- **Standing orders** — always-on user instructions prepended to every session (`cli.py:71`)
- **Subagent** — specialist that runs in its own context window and returns a summary (`subagents.py:30`)
- **Mode** — a personality (code/architect/ask/debug) with allowed-tool set (`modes.py:30`)
- **KB pointer** — a `path:line` reference in a kb/ note, machine-checkable (`knowledge_base.py:187`)
- **FTS5** — SQLite full-text search, used by memory for `recall()` with LIKE fallback (`memory.py:48`)

Cross-link [[architecture]] for component locations.
