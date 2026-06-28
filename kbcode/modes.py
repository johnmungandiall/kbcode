"""Modes — the Kilo Code idea: one agent, several focused personalities.

A *mode* pairs a short instruction with a set of allowed tools, so you can give
the agent a job and the right guardrails at once:

  - **code**      full access — implement and edit (default).
  - **architect** read-only on code; plans first, can write notes/memory.
  - **ask**       pure read-only Q&A; never edits files or runs commands.
  - **debug**     full access, but isolate the root cause before fixing.

Switch with ``/mode <name>`` in the chat. You can add your own modes as markdown
files in ``.kbcode/modes/`` (see :func:`load_custom_modes`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Tool groups (names match Tools.schemas in tools.py).
# manage_todos is planning-only (no file/command side effects), so it lives in
# READ — the baseline every mode allows, including read-only ask/architect.
READ = {"read_file", "list_dir", "search_code", "kb_read", "recall", "manage_todos"}
NOTES = {"kb_write", "remember", "save_skill"}  # knowledge/memory writes — no code or commands
EDIT = {"write_file", "edit_file"}
EXEC = {"run_command"}


@dataclass(frozen=True)
class Mode:
    name: str
    description: str
    instructions: str
    tools: frozenset[str] | None  # allowed tool names; None = every tool

    def allows(self, tool: str) -> bool:
        return self.tools is None or tool in self.tools


_BUILTINS = [
    Mode(
        "code",
        "Implement and edit code with full tool access (default).",
        "You are in CODE mode: make the change directly — read, edit, and create "
        "files and run tests/commands as needed. Prefer small, verified steps.",
        None,
    ),
    Mode(
        "architect",
        "Plan and design first; read-only on code (can write notes).",
        "You are in ARCHITECT mode: investigate the codebase and produce a clear, "
        "step-by-step plan BEFORE any code is written. You cannot edit source files "
        "or run commands here — when the plan is ready, record it (kb_write/remember "
        "if useful) and tell the user to run /mode code to build it.",
        frozenset(READ | NOTES),
    ),
    Mode(
        "ask",
        "Answer questions about the project. Read-only; never edits or runs anything.",
        "You are in ASK mode: answer questions about the project using only "
        "read-only tools. You must not edit files, write notes, or run commands. "
        "If the user wants changes, tell them to switch to /mode code.",
        frozenset(READ),
    ),
    Mode(
        "debug",
        "Diagnose the root cause first, then apply a minimal fix (full access).",
        "You are in DEBUG mode: reproduce and isolate the root cause first — read "
        "code, search, and run diagnostics — state the cause plainly, THEN apply the "
        "smallest fix that addresses it. Don't guess-patch before you've localized it.",
        None,
    ),
]

DEFAULT_MODE = "code"


def builtin_modes() -> dict[str, Mode]:
    return {m.name: m for m in _BUILTINS}


def _parse_tools(value: str) -> frozenset[str] | None:
    """Turn a frontmatter 'tools:' value into an allowed-tool set (or None=all)."""
    value = value.strip().lower()
    if value in ("", "all", "*"):
        return None
    if value in ("read-only", "readonly", "read"):
        return frozenset(READ)
    groups = {"read": READ, "notes": NOTES, "edit": EDIT, "exec": EXEC}
    allowed: set[str] = set()
    for token in value.replace(",", " ").split():
        if token in groups:
            allowed |= groups[token]
        else:
            allowed.add(token)  # an explicit tool name
    return frozenset(allowed)


def load_custom_modes(modes_dir: Path) -> dict[str, Mode]:
    """Load extra modes from ``.kbcode/modes/*.md``.

    Each file uses a tiny ``key: value`` frontmatter between ``---`` fences and a
    markdown body that becomes the instructions::

        ---
        description: Write docs only
        tools: read, notes
        ---
        You are the docs writer. Improve README and kb/ notes...

    The mode's name is the filename (``docs-writer.md`` → ``docs-writer``). Unknown
    or malformed files are skipped, never fatal.
    """
    modes: dict[str, Mode] = {}
    if not modes_dir.is_dir():
        return modes
    for path in sorted(modes_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta: dict[str, str] = {}
        body = text
        if text.startswith("---"):
            _, _, rest = text.partition("---")
            front, sep, body = rest.partition("---")
            if sep:
                for line in front.splitlines():
                    key, colon, val = line.partition(":")
                    if colon:
                        meta[key.strip().lower()] = val.strip()
        name = path.stem.strip()
        if not name:
            continue
        modes[name] = Mode(
            name=name,
            description=meta.get("description", f"custom mode ({name})"),
            instructions=body.strip() or f"You are the '{name}' custom mode.",
            tools=_parse_tools(meta.get("tools", "all")),
        )
    return modes


def load_modes(modes_dir: Path) -> dict[str, Mode]:
    """Built-in modes plus any custom ones (custom can override by name)."""
    modes = builtin_modes()
    modes.update(load_custom_modes(modes_dir))
    return modes
