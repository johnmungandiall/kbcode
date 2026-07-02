# MCP — Model Context Protocol support (Phase 1: stdio, tools only)

A deliberately lean reimplementation of the MCP client (no SDK, no new deps).
Spawns configured servers with `subprocess.Popen`, speaks newline-delimited
JSON-RPC 2.0 over stdin/stdout. Only `initialize`, `tools/list`, `tools/call`.

## Architecture

[`kbcode/tools/mcp.py`](../kbcode/tools/mcp.py) — `MCPClient` (one per server) + `MCPManager` (orchestrator)

- `MCPClient` (`kbcode/tools/mcp.py:104`) — subprocess lifecycle, per-client lock, reader thread
- `MCPManager` (`kbcode/tools/mcp.py:265`) — owns all clients, namespaces tools as `mcp__server__tool`
- `MCPServerConfig` (`kbcode/tools/mcp.py:43`) — parsed from `mcpServers` block in settings.json
- Dispatch: `ToolsCore.execute()` (`kbcode/tools/core.py:109`) forks on `mcp__` prefix → `_execute_mcp()`
- Config merge: `load_mcp_servers()` (`kbcode/config.py:325`) — per-server union home→launch→project

## Tool namespacing

`mcp__<server>__<tool>` — the Claude Code convention. Cannot collide with built-ins and
far from them in edit-distance for `_repair()`'s fuzzy match.

## Safety rails (`kbcode/tools/core.py:121`)

| Condition | Permission prompt | Checkpoint | Redaction |
|---|---|---|---|
| Mutating, untrusted | Yes | Yes | Yes |
| `trusted` tool | No | Yes | Yes |
| `read_only` server | No | No | Yes |

`read_only` servers also get `parallel_safe: True` in schemas (concurrent dispatch).

## Config (`kbcode/config.py:325`)

`mcpServers` is the only settings key that merges **per server** across
home→launch→project (other keys do shallow whole-value override). Merged by
`load_mcp_servers()`, called at startup and by `/mcp reload`.

## `/mcp` command (`kbcode/repl.py:295`)

- `/mcp` — list connected servers and their tools
- `/mcp reload` — re-read settings.json, reconnect (needed after adding servers mid-session)

## Limitations (Phase 1 scope)

- Stdio transport only (no HTTP/SSE)
- Tools only (no resources, prompts, sampling)
- No authentication (OAuth, API keys in env block are user-managed)
- `tools/list_changed` notifications discarded — `/mcp reload` is the only refresh path
- Content flattening: only `text` and `resource` blocks; images/etc. produce a marker

## Testing

`tests/test_mcp.py` — 13 tests against `tests/fake_mcp_server.py` (a real stdio subprocess).
Config parsing, E2E tool calls, failure tolerance, safety rails (permission/checkpoint/redaction),
read_only/trusted, reload, and config merge.

See [[architecture]] for component map, [[safety]] for hooks/checkpoints/redaction,
[[config]] for settings.json merge rules.
