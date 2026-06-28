"""The agent's tools — the "hands" (Claude Code idea), plus tools that wire
in memory (Hermes) and the knowledge base (claude-kb).

Each tool has a JSON schema (so Claude knows how to call it) and a Python
method named ``_tool_<name>`` that runs it. ``execute`` returns
``(content, is_error)`` so the agent can feed results back to the model.
"""

from __future__ import annotations

import difflib
import os
import re
import subprocess
from pathlib import Path

from .config import Config
from .knowledge_base import KnowledgeBase
from .memory import Memory
from .permissions import Permissions

# Directories we never scan when searching code.
_SKIP_DIRS = {".git", ".kbcode", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
_MAX_READ_CHARS = 60000


class Tools:
    def __init__(self, config: Config, memory: Memory, kb: KnowledgeBase, perm: Permissions):
        self.config = config
        self.root = config.project_dir.resolve()
        self.memory = memory
        self.kb = kb
        self.perm = perm

    # --- schema sent to the model -------------------------------------
    @property
    def schemas(self) -> list[dict]:
        return [
            {
                "name": "read_file",
                "description": "Read a text file from the project. Use this before editing a file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Path relative to the project root."}},
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Create or overwrite a file with new content. Use for new files or full rewrites.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Replace an exact snippet in a file with new text. old_string must appear exactly once.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            },
            {
                "name": "list_dir",
                "description": "List files and folders in a directory (defaults to the project root).",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Directory, relative to root. Optional."}},
                },
            },
            {
                "name": "search_code",
                "description": "Search the project for a regular expression. Returns matching path:line: text.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string", "description": "Subdirectory to search. Optional."},
                    },
                    "required": ["pattern"],
                },
            },
            {
                "name": "run_command",
                "description": "Run a shell command in the project root. Use for tests, builds, git, installs. Needs user approval.",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
            {
                "name": "kb_read",
                "description": "Read the whole knowledge base (kb/ notes). Do this first to understand the project cheaply.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "kb_write",
                "description": "Create or update a knowledge-base note (kb/<name>.md). Keep notes short; use path:line pointers.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Note name, e.g. 'architecture'."},
                        "content": {"type": "string"},
                    },
                    "required": ["name", "content"],
                },
            },
            {
                "name": "remember",
                "description": "Save a fact or decision to long-term memory so future sessions recall it. Call when you learn something durable.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "key": {"type": "string", "description": "Optional short label."},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "recall",
                "description": "Search long-term memory for relevant past facts before starting a task.",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "save_skill",
                "description": "Record a reusable how-to after finishing a non-trivial task, so you can repeat it later.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "steps": {"type": "string", "description": "The steps, as markdown."},
                    },
                    "required": ["name", "description", "steps"],
                },
            },
        ]

    # --- dispatch ------------------------------------------------------
    def execute(self, name: str, inp: dict) -> tuple[str, bool]:
        # Tool-call repair (the openclaw idea): instead of failing hard on a
        # malformed call, hand the model a precise correction so it can retry.
        guidance = self._repair(name, inp)
        if guidance is not None:
            return guidance, True

        method = getattr(self, f"_tool_{name}", None)
        try:
            return method(inp), False
        except PermissionError as exc:
            return str(exc), True
        except Exception as exc:  # noqa: BLE001 - surface error back to the model
            return f"Error: {exc}", True

    def _schema_for(self, name: str) -> dict | None:
        return next((s for s in self.schemas if s["name"] == name), None)

    def _repair(self, name: str, inp: dict) -> str | None:
        """Return a correction message if the call is unusable, else None."""
        names = [s["name"] for s in self.schemas]

        if name not in names:
            close = difflib.get_close_matches(name, names, n=1, cutoff=0.6)
            hint = f" Did you mean '{close[0]}'?" if close else ""
            return f"Unknown tool '{name}'.{hint} Available tools: {', '.join(names)}."

        schema = self._schema_for(name) or {}
        required = schema.get("input_schema", {}).get("required", [])
        missing = [r for r in required if r not in inp or inp[r] in (None, "")]
        if missing:
            return (
                f"Tool '{name}' is missing required argument(s): {', '.join(missing)}. "
                f"It requires: {', '.join(required)}. Call it again with those filled in."
            )
        return None

    # --- helpers -------------------------------------------------------
    def _resolve(self, path: str) -> Path:
        candidate = Path(path)
        p = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError(f"Path escapes the project root: {path}")
        return p

    # --- file tools ----------------------------------------------------
    def _tool_read_file(self, inp: dict) -> str:
        p = self._resolve(inp["path"])
        if not p.exists():
            raise ValueError(f"No such file: {inp['path']}")
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > _MAX_READ_CHARS:
            text = text[:_MAX_READ_CHARS] + "\n[...file truncated...]"
        lines = text.splitlines()
        return "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines))

    def _tool_write_file(self, inp: dict) -> str:
        p = self._resolve(inp["path"])
        if not self.perm.check("write_file", f"write {inp['path']} ({len(inp['content'])} chars)"):
            raise PermissionError("User denied permission to write the file.")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inp["content"], encoding="utf-8")
        return f"wrote {inp['path']} ({len(inp['content'])} chars)"

    def _tool_edit_file(self, inp: dict) -> str:
        p = self._resolve(inp["path"])
        if not p.exists():
            raise ValueError(f"No such file: {inp['path']}")
        text = p.read_text(encoding="utf-8", errors="replace")
        count = text.count(inp["old_string"])
        if count == 0:
            raise ValueError("old_string not found in file.")
        if count > 1:
            raise ValueError(f"old_string appears {count} times; make it unique.")
        if not self.perm.check("edit_file", f"edit {inp['path']}"):
            raise PermissionError("User denied permission to edit the file.")
        p.write_text(text.replace(inp["old_string"], inp["new_string"], 1), encoding="utf-8")
        return f"edited {inp['path']}"

    def _tool_list_dir(self, inp: dict) -> str:
        p = self._resolve(inp.get("path", "."))
        if not p.is_dir():
            raise ValueError(f"Not a directory: {inp.get('path', '.')}")
        entries = []
        for item in sorted(p.iterdir()):
            if item.name in _SKIP_DIRS:
                continue
            entries.append(item.name + ("/" if item.is_dir() else ""))
        return "\n".join(entries) or "(empty)"

    def _tool_search_code(self, inp: dict) -> str:
        regex = re.compile(inp["pattern"])
        base = self._resolve(inp.get("path", "."))
        hits: list[str] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                fp = Path(dirpath) / fn
                try:
                    with fp.open("r", encoding="utf-8", errors="strict") as fh:
                        for i, line in enumerate(fh, 1):
                            if regex.search(line):
                                rel = fp.relative_to(self.root)
                                hits.append(f"{rel}:{i}: {line.rstrip()[:200]}")
                                if len(hits) >= 100:
                                    return "\n".join(hits) + "\n[...stopped at 100 matches...]"
                except (UnicodeDecodeError, OSError):
                    continue  # skip binary/unreadable files
        return "\n".join(hits) or "(no matches)"

    def _tool_run_command(self, inp: dict) -> str:
        command = inp["command"]
        if not self.perm.check("run_command", f"$ {command}"):
            raise PermissionError("User denied permission to run the command.")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return "Command timed out after 180s."
        out = (proc.stdout or "")[-8000:]
        err = (proc.stderr or "")[-4000:]
        return f"exit code: {proc.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"

    # --- knowledge base ------------------------------------------------
    def _tool_kb_read(self, _inp: dict) -> str:
        return self.kb.read_all() or "(knowledge base is empty)"

    def _tool_kb_write(self, inp: dict) -> str:
        return self.kb.write_note(inp["name"], inp["content"])

    # --- memory --------------------------------------------------------
    def _tool_remember(self, inp: dict) -> str:
        return self.memory.remember(inp["content"], key=inp.get("key"))

    def _tool_recall(self, inp: dict) -> str:
        rows = self.memory.recall(inp["query"])
        if not rows:
            return "(nothing relevant in memory)"
        return "\n".join(f"- {r['content']}" for r in rows)

    def _tool_save_skill(self, inp: dict) -> str:
        return self.memory.save_skill(inp["name"], inp["description"], inp["steps"])
