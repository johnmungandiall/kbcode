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
concurrently (#4.3 extension) instead of one-at-a-time — but ONLY when every
targeted subagent's ``tools:`` list is an explicit, narrow subset of the
schema-declared parallel-safe tools (``read_file``, ``list_dir``,
``search_code``, ``kb_read``, ``kb_search``, ``web_search`` — see
``tools/schemas.py``). The default ``tools: read`` shown above does NOT
qualify, since it also includes ``recall``/``manage_todos``, which touch
state that isn't thread-safe to share. Narrow a subagent's ``tools:`` to
just the read-only tools it needs (e.g. ``tools: read_file, search_code``)
to make it eligible for concurrent dispatch; see
:meth:`Agent._subagent_parallel_safe`.
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
