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

from .checkpoints import Checkpoints
from .config import Config
from .knowledge_base import KnowledgeBase
from .memory import Memory
from .permissions import Permissions
from .redact import redact_sensitive_text, redact_terminal_output

# Directories we never scan when searching code.
_SKIP_DIRS = {".git", ".kbcode", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
_MAX_READ_CHARS = 60000

# Production safety rail (the Hermes file_safety idea): files the agent must
# never write to or edit. Secrets, VCS/agent internals — the user can still
# change these by hand, the agent just won't clobber them. _resolve already
# confines paths to the project root; this guards what's *inside* it.
_PROTECTED_DIRS = {".git", ".ssh"}  # off-limits anywhere in the path
_PROTECTED_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".npmrc", ".pypirc", ".netrc"}
_PROTECTED_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".keystore"}
_KBCODE_STATE = {"memory.db", "settings.json"}  # only protected under .kbcode/
_ENV_TEMPLATE_TAILS = {"example", "sample", "template", "dist", "defaults"}  # .env.example is fine

_TODO_MARKS = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}


def format_todos(todos: list[dict]) -> str:
    """Render a todo checklist as plain text (for tool results and /todo)."""
    if not todos:
        return "(no todos yet)"
    return "\n".join(f"{_TODO_MARKS.get(t['status'], '[ ]')} {t['task']}" for t in todos)


class Tools:
    def __init__(self, config: Config, memory: Memory, kb: KnowledgeBase, perm: Permissions):
        self.config = config
        self.root = config.project_dir.resolve()
        self.memory = memory
        self.kb = kb
        self.perm = perm
        self.checkpoints = Checkpoints(self.root, config.checkpoints_dir)
        self.todos: list[dict] = []  # the agent's task checklist for the current job
        # Subagent delegation is wired up by the Agent (see agent.py).
        self.subagents: dict = {}
        self.delegate = None  # callable(name, task) -> (summary, is_error)

    # --- schema sent to the model -------------------------------------
    @property
    def schemas(self) -> list[dict]:
        base = self._base_schemas
        if self.subagents and self.delegate is not None:
            return base + [self._subagent_schema()]
        return base

    def _subagent_schema(self) -> dict:
        roster = "\n".join(f"- {n}: {s.description}" for n, s in self.subagents.items())
        return {
            "name": "run_subagent",
            "description": (
                "Delegate a self-contained task to a specialist subagent that works in its "
                "OWN context window and returns just a summary — use it for heavy exploration "
                "or research so your own context stays lean. Available subagents:\n" + roster
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Which subagent to use, by name."},
                    "task": {
                        "type": "string",
                        "description": "A complete, standalone instruction; the subagent sees only this.",
                    },
                },
                "required": ["agent", "task"],
            },
        }

    @property
    def _base_schemas(self) -> list[dict]:
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
            {
                "name": "manage_todos",
                "description": (
                    "Plan and track a multi-step task with a checklist. Pass the FULL list "
                    "each call — it replaces the previous one. Keep exactly one item "
                    "'in_progress', mark items 'done' as you finish, and add new ones as they "
                    "come up. Use this for any job of 3+ steps so progress stays visible."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",
                            "description": "The complete checklist, in order.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "task": {"type": "string"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["pending", "in_progress", "done"],
                                    },
                                },
                                "required": ["task", "status"],
                            },
                        }
                    },
                    "required": ["todos"],
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

    def _protected_reason(self, p: Path) -> str | None:
        """Return *why* writing to ``p`` is refused (a safety rail), or None if
        it's fine. ``p`` is already resolved and confined to the project root."""
        try:
            parts = p.relative_to(self.root).parts
        except ValueError:
            return None  # outside the root is already handled by _resolve
        if any(part in _PROTECTED_DIRS for part in parts):
            hit = next(part for part in parts if part in _PROTECTED_DIRS)
            return f"inside the protected '{hit}/' directory"
        if p.name in _KBCODE_STATE and ".kbcode" in parts:
            return "kbcode's own state file"
        if p.name in _PROTECTED_NAMES:
            return "a credentials file"
        if p.suffix.lower() in _PROTECTED_SUFFIXES:
            return "a private key / certificate"
        low = p.name.lower()
        if low == ".env":
            return "an environment/secrets file"
        if low.startswith(".env."):
            tail = low.split(".", 2)[2] if low.count(".") >= 2 else ""
            if tail not in _ENV_TEMPLATE_TAILS:
                return "an environment/secrets file"
        return None

    # --- file tools ----------------------------------------------------
    def _tool_read_file(self, inp: dict) -> str:
        p = self._resolve(inp["path"])
        if not p.exists():
            raise ValueError(f"No such file: {inp['path']}")
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > _MAX_READ_CHARS:
            text = text[:_MAX_READ_CHARS] + "\n[...file truncated...]"
        text = redact_sensitive_text(text, code_file=True)
        lines = text.splitlines()
        return "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines))

    def _tool_write_file(self, inp: dict) -> str:
        p = self._resolve(inp["path"])
        n = len(inp["content"])
        reason = self._protected_reason(p)
        if reason:
            raise ValueError(
                f"Refused: {p} is {reason}, which kbcode won't write automatically. "
                "Edit it yourself if you really need to."
            )
        # Show the full resolved path (not the model's bare relative name) so the
        # user always knows exactly where the file lands — and what they're approving.
        if not self.perm.check("write_file", f"write {p} ({n} chars)"):
            raise PermissionError("User denied permission to write the file.")
        self.checkpoints.ensure_checkpoint("before write_file")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inp["content"], encoding="utf-8")
        return f"wrote {p} ({n} chars)"

    def _tool_edit_file(self, inp: dict) -> str:
        p = self._resolve(inp["path"])
        reason = self._protected_reason(p)
        if reason:
            raise ValueError(
                f"Refused: {p} is {reason}, which kbcode won't edit automatically. "
                "Edit it yourself if you really need to."
            )
        if not p.exists():
            raise ValueError(f"No such file: {inp['path']}")
        text = p.read_text(encoding="utf-8", errors="replace")
        count = text.count(inp["old_string"])
        if count == 0:
            raise ValueError("old_string not found in file.")
        if count > 1:
            raise ValueError(f"old_string appears {count} times; make it unique.")
        if not self.perm.check("edit_file", f"edit {p}"):
            raise PermissionError("User denied permission to edit the file.")
        self.checkpoints.ensure_checkpoint("before edit_file")
        p.write_text(text.replace(inp["old_string"], inp["new_string"], 1), encoding="utf-8")
        return f"edited {p}"

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
                                snippet = redact_sensitive_text(line.rstrip()[:200], code_file=True)
                                hits.append(f"{rel}:{i}: {snippet}")
                                if len(hits) >= 100:
                                    return "\n".join(hits) + "\n[...stopped at 100 matches...]"
                except (UnicodeDecodeError, OSError):
                    continue  # skip binary/unreadable files
        return "\n".join(hits) or "(no matches)"

    def _tool_run_command(self, inp: dict) -> str:
        command = inp["command"]
        if not self.perm.check("run_command", f"$ {command}"):
            raise PermissionError("User denied permission to run the command.")
        self.checkpoints.ensure_checkpoint("before run_command")
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
        out = redact_terminal_output((proc.stdout or "")[-8000:], command)
        err = redact_terminal_output((proc.stderr or "")[-4000:], command)
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

    # --- planning ------------------------------------------------------
    def _tool_manage_todos(self, inp: dict) -> str:
        cleaned: list[dict] = []
        for item in inp.get("todos") or []:
            task = str(item.get("task", "")).strip()
            if not task:
                continue
            status = str(item.get("status", "pending")).strip().lower()
            if status not in _TODO_MARKS:
                status = "pending"
            cleaned.append({"task": task, "status": status})
        self.todos = cleaned
        return "Updated checklist:\n" + format_todos(cleaned)

    def _tool_run_subagent(self, inp: dict) -> str:
        if self.delegate is None or not self.subagents:
            raise ValueError("No subagents are configured (.kbcode/agents/).")
        content, is_error = self.delegate(inp["agent"], inp["task"])
        if is_error:
            raise ValueError(content)
        return content
