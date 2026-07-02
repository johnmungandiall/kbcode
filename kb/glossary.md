# Glossary — project-specific terms.

- **Normalized message format** — provider-agnostic message shape used by the agent loop (`kbcode/agent.py:4`) — see [[providers]]
- **Tool-call repair** — two-layer fix: execute-time name/arg repair + parse-time plain-text recovery — see [[tools-and-repair]]
- **Promote** — recovering tool calls a model wrote as text into real `tool_calls` (`def promote`, `kbcode/repair.py:48`)
- **Compaction** — summarizing old chat turns to stay within context window (`kbcode/compaction.py:156`) — see [[context-management]]
- **Shadow git** — isolated git store for auto pre-edit snapshots (`kbcode/checkpoints.py:58`) — see [[safety]]
- **Standing orders** — always-on user instructions prepended to every session (`kbcode/cli.py:113` `_STANDING_ORDERS_TEMPLATE`) — see [[modes-subagents]]
- **Subagent** — specialist that runs in its own context window and returns a summary (`kbcode/subagents.py:75`) — see [[modes-subagents]]
- **Mode** — a personality (code/architect/ask/debug) with allowed-tool set (`kbcode/modes.py:33`) — see [[modes-subagents]]
- **KB pointer** — a `path:line` reference in a kb/ note, machine-checkable (`_POINTER_RE`, `kbcode/knowledge_base.py:150`) — see [[about-kb]]
- **FTS5** — SQLite full-text search, used by memory for `recall()` with LIKE fallback (`kbcode/memory.py:86`)
- **MCP tool** — an external server's tool exposed as `mcp__<server>__<tool>` via the stdio client (`kbcode/tools/mcp.py:104`) — see [[mcp]]
- **read_only / trusted (MCP)** — per-server config relaxing the safety rails: whole server is pure-read (no prompt/checkpoint, parallel-safe) / listed tools skip only the prompt — see [[mcp]], [[safety]]

Cross-link [[architecture]] for component locations, [[conventions]] for style rules.
