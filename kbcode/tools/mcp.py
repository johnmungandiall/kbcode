"""MCP (Model Context Protocol) client — stdio transport, tools only.

A deliberately lean reimplementation of the client side of MCP, the way
``HooksRunner`` reimplements Claude Code's hooks instead of pulling a
framework: spawn each configured server with ``subprocess.Popen``, speak
newline-delimited JSON-RPC 2.0 over its stdin/stdout, and implement just the
three methods kbcode needs — ``initialize``, ``tools/list``, ``tools/call``.

Scope (Phase 1): request-response only. No batching, no server notifications
(``tools/list_changed`` is discarded — new tools appear only after
``/mcp reload``), no resources/prompts/sampling, no HTTP/SSE/OAuth. Server
prerequisites (``npx`` needs Node.js, ``uvx`` needs Python 3.10+) are the
user's to install; kbcode only spawns the command it is given.

Tool names are namespaced ``mcp__<server>__<tool>`` (the Claude Code
convention) so they can never collide with built-ins and stay far from them
in edit-distance for ``_repair()``'s fuzzy match. Dispatch in
``ToolsCore.execute`` forks on the ``mcp__`` prefix (see core.py).
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MCP_PREFIX = "mcp__"
_PROTOCOL_VERSION = "2024-11-05"  # baseline rev every current server accepts


class MCPError(RuntimeError):
    """A server/protocol failure surfaced back to the model as a tool error."""


@dataclass
class MCPServerConfig:
    """One entry of the ``mcpServers`` block in settings.json."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    transport: str = "stdio"
    enabled: bool = True
    timeout: float = 30.0
    trusted: list[str] = field(default_factory=list)
    read_only: bool = False  # every tool is a pure read: skip prompt+checkpoint, parallel-safe


def parse_mcp_configs(raw: dict) -> list[MCPServerConfig]:
    """Turn the merged ``mcpServers`` dict into configs; bad entries are
    logged and skipped, never fatal — a broken settings.json must not take
    the agent down."""
    configs: list[MCPServerConfig] = []
    for name, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            log.warning("mcpServers[%r] is not an object — skipped", name)
            continue
        command = str(entry.get("command") or "").strip()
        if not command:
            log.warning("mcpServers[%r] has no 'command' — skipped", name)
            continue
        if not entry.get("enabled", True):
            continue
        transport = str(entry.get("transport") or "stdio").lower()
        if transport != "stdio":
            log.warning("mcpServers[%r]: transport %r not supported (stdio only) — skipped", name, transport)
            continue
        # `parallel_safe: true` is accepted as an alias for read_only: both
        # assert "this server never mutates", which is the only thing that
        # makes skipping the prompt AND concurrent dispatch safe.
        read_only = bool(entry.get("read_only") or entry.get("parallel_safe"))
        configs.append(
            MCPServerConfig(
                name=str(name),
                command=_expand(command),
                args=[_expand(str(a)) for a in entry.get("args") or []],
                env={str(k): _expand(str(v)) for k, v in (entry.get("env") or {}).items()},
                cwd=_expand(str(entry["cwd"])) if entry.get("cwd") else None,
                transport=transport,
                timeout=float(entry.get("timeout") or 30.0),
                trusted=[str(t) for t in entry.get("trusted") or []],
                read_only=read_only,
            )
        )
    return configs


def _expand(value: str) -> str:
    """Expand ``${VAR}``/``%VAR%`` env references in config strings — same
    courtesy load_config extends to provider keys in .env."""
    return os.path.expandvars(value)


class MCPClient:
    """One connected stdio server. All requests are serialized through a
    per-client lock: interleaved writes from parallel-safe dispatch threads
    would corrupt the newline-delimited stream (see plan §2.4)."""

    def __init__(self, cfg: MCPServerConfig):
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.server_info: dict = {}
        self._id = 0
        self._lock = threading.Lock()  # serializes request/response per server
        self._write_lock = threading.Lock()  # reader thread also writes (ping replies)
        self._responses: queue.Queue[dict] = queue.Queue()

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        """Spawn the server and run the initialize handshake. Raises on any
        failure — the manager catches, warns, and skips this server."""
        argv = [shutil.which(self.cfg.command) or self.cfg.command, *self.cfg.args]
        env = os.environ.copy()
        env.update(self.cfg.env)
        kwargs: dict = {}
        if sys.platform == "win32":  # no console window flash per server
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cfg.cwd,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
            **kwargs,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        result = self._request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "kbcode", "version": _kbcode_version()},
            },
        )
        self.server_info = result.get("serverInfo") or {}
        self._notify("notifications/initialized")

    def stop(self) -> None:
        """Terminate the subprocess. Idempotent, never raises."""
        proc, self.proc = self.proc, None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass

    # -- MCP methods ------------------------------------------------------
    def list_tools(self) -> list[dict]:
        """All tools the server advertises (follows ``nextCursor`` pages)."""
        tools: list[dict] = []
        cursor: str | None = None
        while True:
            result = self._request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, tool: str, args: dict) -> tuple[str, bool]:
        result = self._request("tools/call", {"name": tool, "arguments": args or {}})
        return _flatten_content(result.get("content") or []), bool(result.get("isError"))

    # -- JSON-RPC plumbing ------------------------------------------------
    def _request(self, method: str, params: dict) -> dict:
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                raise MCPError(f"MCP server '{self.cfg.name}' is not running")
            self._id += 1
            rid = self._id
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            deadline = self.cfg.timeout
            while True:
                try:
                    msg = self._responses.get(timeout=deadline)
                except queue.Empty:
                    raise MCPError(
                        f"MCP server '{self.cfg.name}' did not answer '{method}' within {self.cfg.timeout:g}s"
                    ) from None
                if msg.get("id") != rid:
                    continue  # stale reply from an earlier timed-out request
                if "error" in msg:
                    err = msg["error"] or {}
                    raise MCPError(f"MCP server '{self.cfg.name}': {err.get('message') or err}")
                return msg.get("result") or {}

    def _notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def _send(self, msg: dict) -> None:
        proc = self.proc
        if proc is None or proc.stdin is None:
            raise MCPError(f"MCP server '{self.cfg.name}' is not running")
        try:
            with self._write_lock:
                proc.stdin.write(json.dumps(msg) + "\n")
                proc.stdin.flush()
        except OSError as exc:
            raise MCPError(f"MCP server '{self.cfg.name}' pipe closed: {exc}") from exc

    def _read_stdout(self) -> None:
        """Reader thread: responses go to the queue; server->client requests
        get a minimal answer (ping) or a method-not-found error; notifications
        (tools/list_changed etc.) are discarded — Phase 1 has no live refresh,
        the user runs /mcp reload."""
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                log.debug("mcp[%s] non-JSON stdout line: %r", self.cfg.name, line[:200])
                continue
            if not isinstance(msg, dict):
                continue
            if "method" in msg and "id" in msg:  # request from the server
                reply: dict = {"jsonrpc": "2.0", "id": msg["id"]}
                if msg["method"] == "ping":
                    reply["result"] = {}
                else:
                    reply["error"] = {"code": -32601, "message": "kbcode: method not supported"}
                try:
                    self._send(reply)
                except MCPError:
                    return
            elif "method" in msg:  # notification — discarded (see docstring)
                log.debug("mcp[%s] notification ignored: %s", self.cfg.name, msg["method"])
            else:
                self._responses.put(msg)

    def _drain_stderr(self) -> None:
        """Keep the server's stderr pipe from filling up (which would block
        it); its log lines go to kbcode's debug log."""
        proc = self.proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            log.debug("mcp[%s] stderr: %s", self.cfg.name, line.rstrip())


class MCPManager:
    """Owns every connected server; the single seam ToolsCore talks to."""

    def __init__(self) -> None:
        self.clients: dict[str, MCPClient] = {}
        self._configs: list[MCPServerConfig] = []
        self._tools: dict[str, tuple[MCPClient, str]] = {}  # namespaced -> (client, bare tool)
        self._schemas: list[dict] = []

    # -- lifecycle ------------------------------------------------------
    def start_all(self, configs: list[MCPServerConfig], warn=None) -> None:
        """Start every enabled server; a failure warns and skips that server,
        never crashes the agent."""
        self._configs = configs
        for cfg in configs:
            client = MCPClient(cfg)
            try:
                client.start()
                tools = client.list_tools()
            except Exception as exc:  # noqa: BLE001 - any startup failure is non-fatal
                client.stop()
                message = f"MCP server '{cfg.name}' failed to start: {exc} — skipped"
                log.warning(message)
                if warn is not None:
                    warn(message)
                continue
            self.clients[cfg.name] = client
            for tool in tools:
                bare = str(tool.get("name") or "")
                if not bare:
                    continue
                namespaced = f"{MCP_PREFIX}{cfg.name}__{bare}"
                schema = {
                    "name": namespaced,
                    "description": f"[MCP:{cfg.name}] {tool.get('description') or bare}",
                    "input_schema": tool.get("inputSchema") or {"type": "object", "properties": {}},
                }
                if cfg.read_only:
                    schema["parallel_safe"] = True
                self._tools[namespaced] = (client, bare)
                self._schemas.append(schema)

    def stop_all(self) -> None:
        """Idempotent shutdown — registered atexit AND run from Agent.close()."""
        for client in self.clients.values():
            client.stop()
        self.clients.clear()
        self._tools.clear()
        self._schemas.clear()

    def reload(self, configs: list[MCPServerConfig] | None = None, warn=None) -> None:
        """Reconnect everything and re-list tools — the only way a server's
        changed tool set becomes visible (list_changed is discarded). Pass
        fresh ``configs`` to also pick up settings.json edits made
        mid-session (the /mcp reload path does)."""
        configs = self._configs if configs is None else configs
        self.stop_all()
        self.start_all(configs, warn=warn)

    # -- queries ----------------------------------------------------------
    def schemas(self) -> list[dict]:
        return list(self._schemas)

    def owns(self, name: str) -> bool:
        return name in self._tools

    def is_read_only(self, name: str) -> bool:
        client_tool = self._tools.get(name)
        return client_tool is not None and client_tool[0].cfg.read_only

    def is_trusted(self, name: str) -> bool:
        """Auto-approved: read-only server, or the bare tool name is listed
        in the server's ``trusted`` config. Mutating trusted tools still get
        a checkpoint (see ToolsCore._execute_mcp)."""
        client_tool = self._tools.get(name)
        if client_tool is None:
            return False
        client, bare = client_tool
        return client.cfg.read_only or bare in client.cfg.trusted

    def summary(self) -> list[tuple[str, int]]:
        """(server, tool count) pairs for the startup notice / /mcp / /status."""
        counts: dict[str, int] = {name: 0 for name in self.clients}
        for client, _bare in self._tools.values():
            counts[client.cfg.name] = counts.get(client.cfg.name, 0) + 1
        return sorted(counts.items())

    def tools_for(self, server: str) -> list[str]:
        return sorted(bare for c, bare in self._tools.values() if c.cfg.name == server)

    # -- dispatch ---------------------------------------------------------
    def call(self, name: str, args: dict) -> tuple[str, bool]:
        client_tool = self._tools.get(name)
        if client_tool is None:
            return f"Unknown MCP tool '{name}'. Run /mcp to see what's connected.", True
        client, bare = client_tool
        try:
            return client.call_tool(bare, args)
        except MCPError as exc:
            return str(exc), True
        except Exception as exc:  # noqa: BLE001 - surface, never crash the loop
            log.debug("mcp call %r raised %s", name, exc, exc_info=True)
            return f"MCP error: {exc}", True


def _flatten_content(blocks: list) -> str:
    """MCP ``content`` blocks -> plain text for the model. Non-text blocks
    degrade to a marker instead of dropping silently."""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text") or ""))
        elif kind == "resource":
            resource = block.get("resource") or {}
            parts.append(str(resource.get("text") or f"[resource: {resource.get('uri', '?')}]"))
        else:
            parts.append(f"[{kind or 'unknown'} block omitted]")
    return "\n".join(p for p in parts if p)


def _kbcode_version() -> str:
    try:
        from .. import __version__

        return __version__
    except Exception:  # noqa: BLE001 - version string is cosmetic here
        return "0"
