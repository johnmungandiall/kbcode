"""Tools dispatch core — schema aggregation, tool-call repair, and helpers
shared across more than one tool category (file, kb, memory, planning,
subagent — see the sibling modules in this package).
"""

from __future__ import annotations

import difflib
import json
import logging
from pathlib import Path

from ..checkpoints import Checkpoints
from ..config import Config
from ..hooks import HooksRunner
from ..knowledge_base import KnowledgeBase
from ..memory import Memory
from ..permissions import Permissions
from ..redact import redact_terminal_output_with_count
from .mcp import MCP_PREFIX, MCPManager
from .schemas import BASE_SCHEMAS

log = logging.getLogger(__name__)


class ToolsCore:
    def __init__(self, config: Config, memory: Memory, kb: KnowledgeBase, perm: Permissions):
        self.config = config
        self.root = config.project_dir.resolve()
        self.memory = memory
        self.kb = kb
        self.perm = perm
        self.checkpoints = Checkpoints(self.root, config.checkpoints_dir)
        self.hooks = HooksRunner(config.hooks, self.root)
        self.todos: list[dict] = []  # the agent's task checklist for the current job
        # Subagent delegation is wired up by the Agent (see agent.py).
        self.subagents: dict = {}
        self.delegate = None  # callable(name, task) -> (summary, is_error)
        # MCP servers are started (or not) by _build_agent (cli.py), which
        # attaches the manager here; None = no MCP configured.
        self.mcp: MCPManager | None = None
        self._run_command_count = 0  # per-turn safety rail, reset by new_turn()
        # Background commands (run_command background=true): task id -> record
        # with the Popen handle + output file paths. Lives across turns; the
        # processes are killed at exit via stop_background_tasks() (file.py).
        self.bg_tasks: dict[str, dict] = {}
        self._bg_seq = 0  # monotonically increasing suffix for task ids
        # Set per-turn by Agent as context fills up (#4.2); None = fixed default.
        self.context_budget_chars: int | None = None
        self._rg_available: bool | None = None  # cached shutil.which("rg") check

    def new_turn(self) -> None:
        """Reset per-turn counters. Mirrors Checkpoints.new_turn(); call once
        per user message (see Agent.run)."""
        self._run_command_count = 0

    # --- schema sent to the model -------------------------------------
    @property
    def schemas(self) -> list[dict]:
        base = self._base_schemas
        if self.mcp is not None:
            base = base + self.mcp.schemas()
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
        return BASE_SCHEMAS

    @property
    def parallel_safe_tools(self) -> set[str]:
        """Names of tools safe to run concurrently (#4.3), read straight off the
        per-tool ``parallel_safe`` flag in the schemas — the single source of
        truth (see schemas.py). Agent uses this instead of a hardcoded set, so a
        new read-only tool opts in just by carrying the flag."""
        return {s["name"] for s in self.schemas if s.get("parallel_safe")}

    # --- dispatch ------------------------------------------------------
    def execute(self, name: str, inp: dict) -> tuple[str, bool]:
        # Tool-call repair (the openclaw idea): instead of failing hard on a
        # malformed call, hand the model a precise correction so it can retry.
        guidance = self._repair(name, inp)
        if guidance is not None:
            return guidance, True

        if name.startswith(MCP_PREFIX):
            return self._execute_mcp(name, inp)

        method = getattr(self, f"_tool_{name}", None)
        try:
            return method(inp), False
        except PermissionError as exc:
            return str(exc), True
        except Exception as exc:  # noqa: BLE001 - surface error back to the model
            log.debug("tool %r raised %s", name, exc, exc_info=True)
            return f"Error: {exc}", True

    def _execute_mcp(self, name: str, inp: dict) -> tuple[str, bool]:
        """Dispatch a namespaced ``mcp__server__tool`` call through the same
        safety rails as built-ins: permission prompt (side-effects are
        opaque, so default-prompt like run_command), a checkpoint before
        anything that may mutate, and redaction on the result — MCP servers
        can return file content or command output. ``read_only`` servers
        skip prompt+checkpoint; ``trusted`` tools skip only the prompt."""
        mgr = self.mcp
        if mgr is None:  # unreachable via _repair, but never crash on it
            return "No MCP servers are configured.", True
        if not mgr.is_read_only(name):
            if not mgr.is_trusted(name):
                detail = f"{name}({json.dumps(inp, default=str)[:300]})"
                if not self.perm.check(name, detail):
                    return "User denied permission to run this MCP tool.", True
            self.checkpoints.ensure_checkpoint(f"before MCP tool: {name}")
        result, is_error = mgr.call(name, inp)
        result, redacted = redact_terminal_output_with_count(result)
        return self._note_redactions(result, redacted), is_error

    def _schema_for(self, name: str) -> dict | None:
        return next((s for s in self.schemas if s["name"] == name), None)

    _SPLIT_WRITE_HINT = (
        " If you are writing a lot of content, do NOT send it all in one call: "
        "write_file the first portion, then extend the file with edit_file "
        "(replace the current ending with ending + next portion), keeping each "
        "call comfortably small."
    )

    def _repair(self, name: str, inp: dict) -> str | None:
        """Return a correction message if the call is unusable, else None."""
        names = [s["name"] for s in self.schemas]

        if name not in names:
            close = difflib.get_close_matches(name, names, n=1, cutoff=0.6)
            hint = f" Did you mean '{close[0]}'?" if close else ""
            return f"Unknown tool '{name}'.{hint} Available tools: {', '.join(names)}."

        write_hint = self._SPLIT_WRITE_HINT if name in ("write_file", "edit_file", "edit_files") else ""

        # Markers set by provider._parse_tool_args: the arguments JSON never
        # made it here intact (malformed, or cut off by the max_tokens limit).
        # Explain the real cause instead of a bare "missing arguments" error.
        if "_malformed_args" in inp or "_args_cut_off" in inp:
            reason = (
                "your response hit the output-token limit mid-call, so the arguments JSON was cut off"
                if inp.get("_args_cut_off")
                else "the arguments were not valid JSON"
            )
            return (
                f"Tool '{name}' arrived with unusable arguments — {reason}. Nothing was "
                f"executed and nothing was damaged. Call it again with complete, valid "
                f"JSON arguments.{write_hint}"
            )

        schema = self._schema_for(name) or {}
        required = schema.get("input_schema", {}).get("required", [])
        missing = [r for r in required if r not in inp or inp[r] in (None, "")]
        if missing:
            return (
                f"Tool '{name}' is missing required argument(s): {', '.join(missing)}. "
                f"It requires: {', '.join(required)}. Call it again with those filled in."
                f"{write_hint}"
            )
        return None

    # --- helpers shared by more than one tool category -----------------
    def _resolve(self, path: str) -> Path:
        """Resolve a tool-supplied path. Relative paths are anchored to the
        project root; absolute paths are honored as given — kbcode is not
        confined to the project folder, so ``_protected_reason`` (file.py) is
        the only thing standing between a tool call and the rest of the disk."""
        candidate = Path(path)
        return (candidate if candidate.is_absolute() else self.root / candidate).resolve()

    def _is_outside_project(self, p: Path) -> bool:
        return self.root not in p.parents and p != self.root

    def _display_path(self, p: Path):
        """A path for display in tool output: relative to the project root
        when it lives inside the project, absolute otherwise. kbcode isn't
        sandboxed to the project folder (see ``_resolve``), so search/list
        results can point outside it — and ``Path.relative_to`` raises
        ``ValueError`` ('... is not in the subpath of ...') on a path that
        isn't under ``root``, which would otherwise abort the whole tool."""
        try:
            return p.relative_to(self.root)
        except ValueError:
            return p

    @staticmethod
    def _unified_diff(old: str, new: str, fromfile: str, tofile: str, max_chars: int = 4000) -> str:
        """A capped unified diff for a permission prompt (#7.2) — shown so the
        user approves what will actually change, not just a byte count."""
        diff = "\n".join(
            difflib.unified_diff(
                old.splitlines(), new.splitlines(), fromfile=fromfile, tofile=tofile, lineterm=""
            )
        )
        if len(diff) > max_chars:
            diff = diff[:max_chars] + "\n[...diff truncated...]"
        return diff

    @staticmethod
    def _note_redactions(content: str, count: int) -> str:
        """Append an audit note when redact.py masked something (the Hermes
        idea): the model/user learn secrets were caught, without seeing them."""
        if not count:
            return content
        return f"{content}\n\n[kbcode redacted {count} likely secret{'s' if count != 1 else ''} from this output]"
