"""Subagents — the Claude Code / claude-kb idea: delegate a self-contained job
to a specialist that runs in its OWN context window and reports back a summary.

A subagent is a name + description + system instructions + an allowed-tool set
(reusing the same tool groups as modes). The main agent calls the ``run_subagent``
tool; :meth:`Agent._run_subagent` runs a short bounded loop with the subagent's
instructions and tools, then hands the final text back. Heavy exploration stays
out of the main session's context this way.

Define them as markdown files in ``.kbcode/agents/*.md``::

    ---
    description: Explore the codebase and report the key files for a task.
    tools: read
    ---
    You are a code explorer. Trace the feature, then return a tight summary...

The agent's name is the filename (``code-explorer.md`` -> ``code-explorer``).

If the model asks for several ``run_subagent`` calls in one turn, they run
concurrently (#4.3 extension) instead of one-at-a-time — when every targeted
subagent's ``tools:`` list stays within the schema-declared parallel-safe
tools (``read_file``, ``list_dir``, ``search_code``, ``repo_map``,
``kb_read``, ``kb_search``, ``web_search``, ``fetch_url``, ``recall`` — see
``tools/schemas.py``) plus the tolerated ``manage_todos``. The default
``tools: read`` shown above therefore QUALIFIES: Memory serializes its
SQLite access behind a lock (so ``recall`` is parallel-safe), and
``manage_todos``'s whole-list replacement is atomic. Any write/exec tool, or
``tools:`` omitted entirely via ``None`` ("every tool"), keeps a subagent
sequential. See :meth:`Agent._subagent_parallel_safe`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .modes import _parse_tools


@dataclass(frozen=True)
class Subagent:
    name: str
    description: str
    instructions: str
    tools: frozenset[str] | None  # allowed tool names; None = every tool

    def allows(self, tool: str) -> bool:
        return self.tools is None or tool in self.tools


def builtin_subagents() -> dict[str, Subagent]:
    """Always-available subagents, baked in so every project has them without
    re-scaffolding (a ``.kbcode/agents/<same-name>.md`` file overrides them).

    - ``autopilot`` — takes a whole task end-to-end without asking the user
      anything; gets every tool. In auto permission mode (see permissions.py)
      nothing prompts, so it effectively runs with full permissions.
    - ``fixer`` — reviews work that was just done and repairs any mistakes it
      finds. Agent.run auto-dispatches it after editing turns in auto mode
      (see Agent._auto_fix_feedback), and the model can call it any time.
    """
    autopilot = Subagent(
        name="autopilot",
        description="Complete a whole task end-to-end autonomously — plans, edits, runs and verifies without asking the user anything.",
        instructions=(
            "You are the autopilot subagent. Finish the given task COMPLETELY on your own:\n"
            "- Never ask the user questions or wait for confirmation; make the best decision and proceed.\n"
            "- Plan briefly, make the changes, then VERIFY them (run tests or the code you touched).\n"
            "- If something fails, fix it and re-verify before finishing.\n"
            "- Return a short summary: what you changed, what you verified, anything left over."
        ),
        tools=None,  # every tool
    )
    fixer = Subagent(
        name="fixer",
        description="Reviews changes that were just made, finds mistakes (syntax errors, broken imports, failing checks) and fixes them.",
        instructions=(
            "You are the fixer subagent. You are given a description (often a diff) of changes "
            "that were just made. Your ONLY job is to find and repair mistakes in them:\n"
            "- Read the touched files; check syntax, imports, obvious logic slips, and broken references.\n"
            "- Run cheap, fast checks where possible (a linter, a targeted test, compiling the file).\n"
            "- Fix ONLY real defects — do not restyle, refactor, or expand scope.\n"
            "- If everything is fine, say so in one line. Otherwise fix, re-check, and summarize what you repaired."
        ),
        tools=None,  # needs read + write + run to actually repair things
    )
    return {autopilot.name: autopilot, fixer.name: fixer}


def load_subagents(agents_dir: Path) -> dict[str, Subagent]:
    """Load subagent definitions from ``.kbcode/agents/*.md`` (malformed = skipped)."""
    agents: dict[str, Subagent] = {}
    if not agents_dir.is_dir():
        return agents
    for path in sorted(agents_dir.glob("*.md")):
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
        agents[name] = Subagent(
            name=name,
            description=meta.get("description", f"subagent ({name})"),
            instructions=body.strip() or f"You are the '{name}' subagent.",
            # Default to read-only when unspecified — safer for delegated work.
            tools=_parse_tools(meta.get("tools", "read")),
        )
    return agents
