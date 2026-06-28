"""The token-cheap knowledge base (the "claude-kb" idea).

A folder of short markdown notes describing the project. Loaded once per
session into the system prompt so the agent understands the codebase without
re-reading every file each time.

The note set and rules are modelled on claude-kb:
  - one note per concern (overview, architecture, conventions, gotchas, ...);
  - each note stays short (~50 lines), bullets over prose, one fact per place;
  - reference code as `path:line` so it can be machine-checked (see
    :meth:`KnowledgeBase.check_pointers`);
  - cross-link notes with ``[[other-note]]``;
  - ``about-you.md`` maps the USER (style, tech, goals), not the code.
"""

from __future__ import annotations

import re
from pathlib import Path

AGENT_MD_TEMPLATE = """# AGENT.md

Loaded every session. Keep it short — it points the agent at the knowledge
base in `kb/` instead of making it re-scan the whole repo.

## How to work here
1. Read the `kb/` notes first to understand the project (cheaper than reading code).
2. When you change code, update the affected `kb/` note in the SAME turn.
3. Record user preferences in `kb/about-you.md`; durable decisions go to memory.
4. Save reusable how-tos as skills after finishing something non-trivial.

## Knowledge base rules (keep notes cheap and trustworthy)
- One note per concern; each stays under ~50 lines. Bullets/tables, not code dumps.
- One fact lives in ONE place; cross-link related notes with `[[other-note]]`.
- Cite code as `path:line` from the repo root (e.g. `kbcode/agent.py:31`) so
  `/kb-check` can verify it. Name the function/class too — the name is the
  durable anchor, the line is a hint that can drift.
- Start each note with a one-line summary of what it covers.
- `kb/overview.md` keeps a one-line `last indexed: <date>`; release history lives
  only in a changelog note, never duplicated.

## Notes map
- `kb/overview.md` — what this project is and how to run it.
- `kb/architecture.md` — the main pieces and how they fit.
- `kb/conventions.md` — how code/notes here are structured.
- `kb/gotchas.md` — traps to know before editing.
- `kb/glossary.md` — project-specific terms.
- `kb/about-you.md` — the USER: style, tech, goals, rules.
"""

_TEMPLATES: dict[str, str] = {
    "overview": """# Overview — what this project is and how to run it.

last indexed: (fill in date)

_One short paragraph: what is this project and who is it for?_

## Key entry points
- `path/to/main` — what it does

## How to run
- (command to build / run / test)

> Tip: ask kbcode to "build the knowledge base for this project" and it will
> scan the code and fill these notes in for you. See [[architecture]].
""",
    "architecture": """# Architecture — the main pieces and how they fit.

_One line: the shape of the system (e.g. CLI → core → storage)._

## Components
- `path/to/module` — responsibility (one line). Entry: `path/to/file.py:NN`.

## Data / control flow
- step 1 → step 2 → step 3

See [[overview]] for how to run; [[conventions]] for structure rules.
""",
    "conventions": """# Conventions — how code and notes here are structured.

- Language / style: (e.g. Python, type hints, small functions).
- Naming: (modules, tests, configs).
- Notes: ≤ 50 lines, `path:line` refs, `[[cross-link]]`, one fact per place.

See [[gotchas]] for what breaks if you ignore these.
""",
    "gotchas": """# Gotchas — traps specific to this repo. Read before editing.

- (Non-obvious thing that bites newcomers, and how to avoid it.)

Cite the code that proves each trap as `path:line` so [[conventions]] checks pass.
""",
    "glossary": """# Glossary — project-specific terms.

- **Term** — what it means here (one line).

Cross-link the note that owns each concept, e.g. [[architecture]].
""",
    "about-you": """# About you — the USER this agent works for. Not about the code.

Tag each item [confirmed] (you told me) or [inferred] (my guess).

## Style
- How you like answers / explanations.

## Tech
- Languages, tools, and stacks you use.

## Goals
- What you're trying to build.

## Rules
- Hard preferences I must always follow.
""",
}

# A pointer like `kbcode/agent.py:31` or a markdown link `(kbcode/agent.py#L31)`.
_POINTER_RE = re.compile(r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+)[:#]L?(\d+)")
# Placeholder examples in the templates use these — don't flag them as real refs.
_PLACEHOLDER_PARTS = ("path/to", "path.ext", "<line>", "name(")


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
        """Create the starter note set if the KB is empty."""
        if self.list_notes():
            return
        for name, body in _TEMPLATES.items():
            self.write_note(name, body)

    def check_pointers(self, project_dir: Path) -> list[str]:
        """Verify every `path:line` reference in the notes still resolves.

        Returns a list of human-readable problems (missing file, or a line
        number past the end of the file). Empty list means all good. This is
        claude-kb's integrity check: notes are only cheap if their pointers
        stay true. Placeholder examples in the templates are skipped.
        """
        problems: list[str] = []
        for note in self.kb_dir.glob("*.md"):
            text = note.read_text(encoding="utf-8", errors="replace")
            for raw_path, raw_line in _POINTER_RE.findall(text):
                if any(part in raw_path for part in _PLACEHOLDER_PARTS):
                    continue
                if "://" in raw_path:  # a URL, not a repo path
                    continue
                target = (project_dir / raw_path.replace("\\", "/")).resolve()
                where = f"kb/{note.name}: {raw_path}:{raw_line}"
                if not target.is_file():
                    problems.append(f"{where} -> file not found")
                    continue
                line_count = sum(1 for _ in target.open("r", encoding="utf-8", errors="replace"))
                if int(raw_line) > line_count:
                    problems.append(f"{where} -> only {line_count} lines (pointer is stale)")
        return problems

    @staticmethod
    def _safe(name: str) -> str:
        name = name.strip().replace("\\", "/").split("/")[-1]
        if not name:
            name = "note"
        if not name.endswith(".md"):
            name += ".md"
        return name
