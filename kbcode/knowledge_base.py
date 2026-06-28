"""The token-cheap knowledge base (the "claude-kb" idea).

A folder of short markdown notes describing the project. Loaded once per
session into the system prompt so the agent understands the codebase
without re-reading every file each time.
"""

from __future__ import annotations

from pathlib import Path

AGENT_MD_TEMPLATE = """# AGENT.md

This file is loaded every session. Keep it short — it points the agent at
the knowledge base instead of making it re-scan the whole repo.

## How to work here
1. Read the notes in `kb/` first to understand the project.
2. When you change code, update the affected `kb/` note in the same turn.
3. Save reusable how-tos as skills, and important decisions to memory.

## Knowledge base
The `kb/` folder holds short notes (overview, architecture, conventions,
gotchas). Each note stays under ~50 lines and uses `path:line` pointers
instead of pasting whole files.
"""

OVERVIEW_TEMPLATE = """# Overview

_What is this project?_ (fill this in — one short paragraph)

## Key entry points
- `path/to/main` — what it does

## How to run
- (command to run / build / test)

> Tip: ask kbcode to "build the knowledge base for this project" and it
> will scan the code and fill these notes in for you.
"""


class KnowledgeBase:
    def __init__(self, kb_dir: Path):
        self.kb_dir = kb_dir
        self.kb_dir.mkdir(parents=True, exist_ok=True)

    def list_notes(self) -> list[str]:
        return sorted(p.name for p in self.kb_dir.glob("*.md"))

    def read_all(self, max_chars: int = 20000) -> str:
        parts: list[str] = []
        for p in sorted(self.kb_dir.glob("*.md")):
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            parts.append(f"### kb/{p.name}\n{text}")
        joined = "\n\n".join(parts)
        if len(joined) > max_chars:
            joined = joined[:max_chars] + "\n\n[...knowledge base truncated...]"
        return joined

    def read_note(self, name: str) -> str | None:
        p = self.kb_dir / self._safe(name)
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None

    def write_note(self, name: str, content: str) -> str:
        p = self.kb_dir / self._safe(name)
        p.write_text(content, encoding="utf-8")
        return f"wrote kb/{p.name}"

    def scaffold(self) -> None:
        """Create starter notes if the KB is empty."""
        if not self.list_notes():
            self.write_note("overview", OVERVIEW_TEMPLATE)

    @staticmethod
    def _safe(name: str) -> str:
        name = name.strip().replace("\\", "/").split("/")[-1]
        if not name:
            name = "note"
        if not name.endswith(".md"):
            name += ".md"
        return name
