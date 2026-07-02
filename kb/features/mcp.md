# MCP — external tool servers over stdio (tools only, Phase 1).

## What it is
kbcode can connect to MCP (Model Context Protocol) servers and expose their
tools to the model as if built-in. The client is a lean reimplementation
(the `HooksRunner` approach — no SDK, no new deps): `kbcode/tools/mcp.py`
spawns each server with `subprocess.Popen` and speaks newline-delimited
JSON-RPC 2.0, implementing just `initialize` / `tools/list` / `tools/call`
(`MCPClient`, `kbcode/tools/mcp.py:104`). **Scope: local stdio servers,
request-response only** — no HTTP/SSE/OAuth, no resources/prompts/sampling,
no notifications (`tools/list_changed` is discarded; a changed tool set is
invisible until `/mcp reload`). Prerequisites are the user's: `npx ...`
servers need Node.js, `uvx ...` needs Python 3.10+ — kbcode only spawns the
command it's given.

## Config
`mcpServers` block in `.kbcode/settings.json` (Claude Code/Cursor-compatible
shape), parsed by `parse_mcp_configs()` (`kbcode/tools/mcp.py:59`) into
`MCPServerConfig` (`kbcode/tools/mcp.py:44`). Per-server fields: `command`
(required), `args`, `env`, `cwd`, `transport` (stdio only), `enabled`,
`timeout` (s, default 30), `trusted` (list of bare tool names to
auto-approve), `read_only` (`parallel_safe` is accepted as an alias). Values
get `${VAR}` env expansion. Bad/disabled/non-stdio entries are logged and
skipped. Loaded via `load_mcp_servers()` (`kbcode/config.py:325`) — a
**per-server deep merge** across home → launch → project, unlike every other
settings key (whole-value shallow override), so a project can add one server
without hiding home-level ones; carried as `Config.mcp`
(`kbcode/config.py:204`). See [[config]], [[gotchas]].

## Lifecycle
`_build_agent` (`kbcode/cli.py:148`) starts every server when `config.mcp`
is non-empty, attaches the `MCPManager` (`kbcode/tools/mcp.py:265`) to
`Tools.mcp`, registers `atexit` stop as a crash backstop, and prints
"MCP: git (7 tools), ...". A server that fails to start warns and is
skipped — never fatal (`start_all`). Normal shutdown is `Agent.close()`
(`kbcode/agent.py:784`) → `stop_all()` (idempotent) — `/exit`, `/provider`
and `/open` all pass through it, so rebuilt agents don't leak old server
subprocesses. `tools/list` runs once at startup and is cached. **Startup only
starts what settings.json held at launch** — `/mcp reload`
(`kbcode/repl.py:282`) re-reads the merged block via `load_mcp_servers()` and
passes fresh configs to `MCPManager.reload()`, bootstrapping a manager if
none was attached, so a server added mid-session works without restarting
kbcode.

## Naming & dispatch
Tools are namespaced `mcp__<server>__<tool>` (`MCP_PREFIX`,
`kbcode/tools/mcp.py:35`) — collision-proof against built-ins and far in
edit-distance so `_repair()`'s difflib match never "corrects" across the
namespace boundary; repair works on MCP names for free once schemas are in.
`ToolsCore.schemas` appends `mcp.schemas()` (`kbcode/tools/core.py:57`);
`execute()` forks on the prefix (`kbcode/tools/core.py:104`) into
`_execute_mcp()` (`kbcode/tools/core.py:116`). Requests are serialized by a
per-client lock — parallel-safe dispatch threads would otherwise interleave
writes on one stdin pipe.

## Safety rails (all reused, see [[safety]])
`_execute_mcp` runs: permission prompt (default, like run_command — MCP
side-effects are opaque) → `checkpoints.ensure_checkpoint` before anything
that may mutate → result through `redact_terminal_output_with_count` +
`_note_redactions`. `read_only: true` server ⇒ skip prompt+checkpoint AND
schemas carry `parallel_safe: True` (concurrent read batching picks them
up); `trusted: [tool]` ⇒ skip only the prompt, checkpoint still taken.
PreToolUse/PostToolUse hooks fire for free (generic by tool name). MCP
servers run with full user privileges — the permission gate is the backstop.

## Modes, subagents, UI
Full modes (`code`, `debug`) see MCP tools automatically; restricted modes
only if the frontmatter lists explicit `mcp__server__tool` names
(`_parse_tools` accepts explicit names, `kbcode/modes.py:98`). Default
`tools: read` subagents never see them. `/mcp` lists servers+tools,
`/mcp reload` reconnects (`kbcode/repl.py:281`); `/status` appends an MCP
line; activity lines fall back to a generic `MCP server:tool` describer
(`kbcode/ui.py:244`). Tests: `tests/test_mcp.py` end-to-end against
`tests/fake_mcp_server.py`, a real stdio subprocess.

See [[tools-and-repair]] for the dispatch seam, [[gotchas]] for the traps
(namespace, merge, stale tool cache).
