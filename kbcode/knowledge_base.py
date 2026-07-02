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
5. Fresh template notes in `kb/` mean the KB is unbuilt — NOT that the project
   is empty. Check the real files (repo_map / list) before describing the project.

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
- `kb/cheatsheet.md` — the commands/snippets you reach for most.
- `kb/changelog.md` — notable changes, newest first (the only place history lives).
- `kb/about-you.md` — the USER: style, tech, goals, rules.
"""

_TEMPLATES: dict[str, str] = {
    "overview": """# Overview — what this project is and how to run it.

> STARTER TEMPLATE — these kb/ notes haven't been filled in yet. That does
> NOT mean the project is empty: the folder may already hold a full codebase.
> Check the real files (repo_map / list) before describing the project, and
> offer to build the knowledge base from the actual code.

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
    "cheatsheet": """# Cheatsheet — the commands and snippets you reach for most.

Copy-paste ready. Group by task; keep each line runnable.

## Run / build / test
- `command` — what it does

## Common tasks
- (task) -> `command`

See [[overview]] for first-time setup and [[gotchas]] for what to avoid.
""",
    "changelog": """# Changelog — notable changes, newest first.

The ONLY place release history lives (don't duplicate it in other notes).
One line per change that future-you or the agent should know about.

## Unreleased
- (what changed) - why it matters. See [[architecture]].

## (date) - first version
- Initial knowledge base scaffolded.
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

# For auto-fix: pull code-symbol-looking tokens off the note line, and spot
# definition lines in the target file (the durable anchor a line number drifts from).
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEF_RE = re.compile(r"\b(?:def|class|function|func|fn|interface|type|struct)\b")


class KnowledgeBase:
    def __init__(self, kb_dir: Path):
        self.kb_dir = kb_dir
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        # Cache of the joined (untruncated) notes, invalidated by write_note()
        # (#10.2) — read_all() can be called more than once per process (the
        # kb_read tool, plus the initial system-prompt build) without re-globbing
        # and re-reading every note from disk each time. Trade-off: a note
        # edited on disk by something other than this KnowledgeBase instance
        # (e.g. by hand in another editor, mid-session) won't be picked up
        # until the next write_note() call clears the cache.
        self._joined_cache: str | None = None

    def list_notes(self) -> list[str]:
        return sorted(p.name for p in self.kb_dir.glob("*.md"))

    def read_all(self, max_chars: int = 20000) -> str:
        if self._joined_cache is None:
            parts: list[str] = []
            for p in sorted(self.kb_dir.glob("*.md")):
                text = p.read_text(encoding="utf-8", errors="replace").strip()
                parts.append(f"### kb/{p.name}\n{text}")
            self._joined_cache = "\n\n".join(parts)
        joined = self._joined_cache
        if len(joined) > max_chars:
            joined = joined[:max_chars] + "\n\n[...knowledge base truncated...]"
        return joined

    def search(self, query: str, max_results: int = 20) -> list[str]:
        """Find notes mentioning ``query`` (case-insensitive substring) without
        reading the whole knowledge base — cheaper than ``read_all()`` once the
        KB has grown past a handful of notes. Returns ``kb/<note>.md:N: line``
        hits, in note-file order.
        """
        needle = query.strip().lower()
        if not needle:
            return []
        hits: list[str] = []
        for p in sorted(self.kb_dir.glob("*.md")):
            text = p.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if needle in line.lower():
                    hits.append(f"kb/{p.name}:{i}: {line.strip()}")
                    if len(hits) >= max_results:
                        return hits
        return hits

    def read_note(self, name: str) -> str | None:
        p = self.kb_dir / self._safe(name)
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None

    def write_note(self, name: str, content: str) -> str:
        p = self.kb_dir / self._safe(name)
        p.write_text(content, encoding="utf-8")
        self._joined_cache = None
        return f"wrote kb/{p.name}"

    def scaffold(self) -> None:
        """Create the starter note set if the KB is empty."""
        if self.list_notes():
            return
        for name, body in _TEMPLATES.items():
            self.write_note(name, body)

    def is_scaffold(self) -> bool:
        """True while the KB is unbuilt — no notes yet, or every note is still
        an untouched starter template. One customized or extra note -> False.
        Drives the first-run "/init to build the knowledge base" hint."""
        notes = self.list_notes()
        if not notes:
            return True
        for filename in notes:
            template = _TEMPLATES.get(filename[:-3])  # "overview.md" -> "overview"
            if template is None or self.read_note(filename) != template:
                return False
        return True

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

    def fix_pointers(self, project_dir: Path) -> tuple[list[str], list[str]]:
        """Auto-repair drifted `path:line` pointers (claude-kb's ``--fix``).

        For each pointer whose line has moved, use the code symbol named on the
        same note line as the durable anchor: find where that symbol now lives in
        the file and rewrite the line number. Returns ``(fixed, unresolved)`` —
        what was repaired, and what still needs a human (missing file, or a
        pointer with no symbol to relocate by).
        """
        fixed: list[str] = []
        unresolved: list[str] = []

        for note in self.kb_dir.glob("*.md"):
            text = note.read_text(encoding="utf-8", errors="replace")

            def repl(m: re.Match, _note=note) -> str:
                raw_path, raw_line = m.group(1), m.group(2)
                if any(part in raw_path for part in _PLACEHOLDER_PARTS) or "://" in raw_path:
                    return m.group(0)
                target = (project_dir / raw_path.replace("\\", "/")).resolve()
                where = f"kb/{_note.name}: {raw_path}:{raw_line}"
                if not target.is_file():
                    unresolved.append(f"{where} -> file not found")
                    return m.group(0)
                lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
                start = text.rfind("\n", 0, m.start()) + 1
                end = text.find("\n", m.end())
                context = text[start : len(text) if end < 0 else end]
                anchors = self._anchors(context, raw_path)
                cur = int(raw_line)
                new = self._relocate(lines, anchors, cur)
                if new is None:
                    if cur > len(lines):
                        unresolved.append(
                            f"{where} -> only {len(lines)} lines; name the function/class so it can relocate"
                        )
                    return m.group(0)
                if new != cur:
                    fixed.append(f"{where} -> line {new}")
                    return m.group(0)[: -len(raw_line)] + str(new)
                return m.group(0)

            new_text = _POINTER_RE.sub(repl, text)
            if new_text != text:
                note.write_text(new_text, encoding="utf-8")
        return fixed, unresolved

    @staticmethod
    def _anchors(context: str, raw_path: str) -> list[str]:
        """Code-symbol tokens on a note line, best candidates first."""
        out: list[str] = []
        for tok in _IDENT_RE.findall(context):
            if tok in raw_path or len(tok) < 3:
                continue
            looks_like_symbol = "_" in tok or tok != tok.lower() or (tok + "(") in context
            if looks_like_symbol and tok not in out:
                out.append(tok)
        return out

    @staticmethod
    def _relocate(lines: list[str], anchors: list[str], current: int) -> int | None:
        """Where an anchor now lives (1-based), or None if not confident.

        Returns ``current`` unchanged if the pointed-at line still holds the
        anchor. Otherwise prefers a unique definition line, then a unique call,
        then a unique mention.
        """
        if not anchors:
            return current if 1 <= current <= len(lines) else None
        if 1 <= current <= len(lines) and any(a in lines[current - 1] for a in anchors):
            return current
        for anchor in anchors:
            defs = [i + 1 for i, line in enumerate(lines) if anchor in line and _DEF_RE.search(line)]
            if len(defs) == 1:
                return defs[0]
            calls = [i + 1 for i, line in enumerate(lines) if (anchor + "(") in line]
            if len(calls) == 1:
                return calls[0]
            hits = [i + 1 for i, line in enumerate(lines) if anchor in line]
            if len(hits) == 1:
                return hits[0]
        return None

    @staticmethod
    def _safe(name: str) -> str:
        name = name.strip().replace("\\", "/").split("/")[-1]
        if not name:
            name = "note"
        if not name.endswith(".md"):
            name += ".md"
        return name
