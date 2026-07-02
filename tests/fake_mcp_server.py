"""A tiny MCP server speaking newline-delimited JSON-RPC over stdio, for
end-to-end tests of kbcode/tools/mcp.py — no dependencies, run with
``python tests/fake_mcp_server.py``.

Tools: ``echo`` (returns "echo: <text>"), ``boom`` (isError=True),
``secretive`` (returns a fake API key so redaction can be asserted).
"""

import json
import sys

TOOLS = [
    {
        "name": "echo",
        "description": "Echo text back",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "boom",
        "description": "Always fails",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "secretive",
        "description": "Returns output containing a secret",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def call(name: str, args: dict) -> dict:
    if name == "echo":
        return {"content": [{"type": "text", "text": "echo: " + str(args.get("text", ""))}], "isError": False}
    if name == "boom":
        return {"content": [{"type": "text", "text": "kaboom"}], "isError": True}
    if name == "secretive":
        return {
            "content": [{"type": "text", "text": "token=sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij-AAAAAAAA"}],
            "isError": False,
        }
    return {"content": [{"type": "text", "text": f"no such tool {name}"}], "isError": True}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        mid = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            send({
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": msg.get("params", {}).get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake", "version": "1.0"},
                },
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            send({"jsonrpc": "2.0", "id": mid, "result": call(params.get("name"), params.get("arguments") or {})})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}})


if __name__ == "__main__":
    main()
