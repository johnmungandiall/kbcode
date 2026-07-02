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
from datetime import datetime
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
# `0.0.0.0:8000` / `127.0.0.1:8080` are IP:port, not file:line — a "path" made
# only of digits and dots is never a real file. Without this guard the drift
# check cried wolf on a note that documented server addresses, and the model
# burned a huge turn "fixing" notes that were fine.
_IP_LIKE_RE = re.compile(r"[\d.]+")


def _is_pointer_candidate(raw_path: str) -> bool:
    """True if a _POINTER_RE match plausibly names a repo file."""
    if any(part in raw_path for part in _PLACEHOLDER_PARTS):
        return False
    if "://" in raw_path or raw_path.startswith("//"):  # a URL (or its host part after `http:`), not a repo path
        return False
    return not _IP_LIKE_RE.fullmatch(raw_path.lstrip("/"))

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

    def _all_note_files(self) -> list:
        """Every note under kb/, INCLUDING subfolders (e.g. kb/features/), but
        skipping dot-folders like kb/.history — used by the pointer check/fix
        so notes organized into subfolders aren't silently skipped."""
        return sorted(
            p
            for p in self.kb_dir.rglob("*.md")
            if not any(part.startswith(".") for part in p.relative_to(self.kb_dir).parts)
        )

    def _note_label(self, p) -> str:
        """`kb/overview.md` or `kb/features/mcp.md` — the display name for a note path."""
        return f"kb/{p.relative_to(self.kb_dir).as_posix()}"

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
        # Note versioning: an overwrite that CHANGES content first snapshots the
        # old version into kb/.history/ so a bad kb_write can be undone with
        # /kb-undo (files have /rollback; notes get this). Dot-folder, so
        # list_notes()/read_all()/the pointer check never see the backups.
        if p.exists():
            old = p.read_text(encoding="utf-8", errors="replace")
            if old != content:
                hist = self.kb_dir / ".history"
                hist.mkdir(exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")  # %f: two writes in the same second must not share a backup name
                (hist / f"{p.stem}.{stamp}.md").write_text(old, encoding="utf-8")
        p.write_text(content, encoding="utf-8")
        self._joined_cache = None
        return f"wrote kb/{p.name}"

    def restore_note(self, name: str) -> str | None:
        """Undo the last content-changing write to a note: restore its most
        recent kb/.history/ snapshot (consuming it). Returns the restored
        note's display name, or None if there is no backup to restore."""
        p = self.kb_dir / self._safe(name)
        hist = self.kb_dir / ".history"
        backups = sorted(hist.glob(f"{p.stem}.*.md")) if hist.is_dir() else []
        if not backups:
            return None
        latest = backups[-1]
        # Write directly (not via write_note) so restoring doesn't snapshot the
        # bad content back into history — a second /kb-undo then steps one
        # version further back instead of toggling.
        p.write_text(latest.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        self._joined_cache = None
        latest.unlink()
        return f"kb/{p.name}"

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
        for note in self._all_note_files():
            text = note.read_text(encoding="utf-8", errors="replace")
            for m in _POINTER_RE.finditer(text):
                raw_path, raw_line = m.group(1), m.group(2)
                # `http://host.name:8080/...` — a host:port inside a URL is not
                # a file:line ref, even when the host part isn't numeric.
                if "://" in text[max(0, m.start() - 8) : m.start()]:
                    continue
                if not _is_pointer_candidate(raw_path):
                    continue
                target = (project_dir / raw_path.replace("\\", "/")).resolve()
                where = f"{self._note_label(note)}: {raw_path}:{raw_line}"
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

        for note in self._all_note_files():
            text = note.read_text(encoding="utf-8", errors="replace")

            def repl(m: re.Match, _note=note) -> str:
                raw_path, raw_line = m.group(1), m.group(2)
                if "://" in text[max(0, m.start() - 8) : m.start()]:
                    return m.group(0)  # host:port inside a URL, not a file:line
                if not _is_pointer_candidate(raw_path):
                    return m.group(0)
                target = (project_dir / raw_path.replace("\\", "/")).resolve()
                where = f"{self._note_label(_note)}: {raw_path}:{raw_line}"
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
        """Code-symbol tokens on a note line, best candidates first.

        Ordering matters: `_snake_case` names and explicit calls (`name(`) are
        far more likely to be THE symbol the pointer means than a bare
        capitalized word (prose like "Related" or a class name mentioned in
        passing) — the fixer once relocated `_record_usage` to `class Agent:`
        because "Related" and "Agent" came first. See [[gotchas]].
        """
        strong: list[str] = []  # snake_case or explicitly called on this line
        weak: list[str] = []  # merely capitalized words
        for tok in _IDENT_RE.findall(context):
            if tok in raw_path or len(tok) < 3:
                continue
            if "_" in tok or (tok + "(") in context:
                if tok not in strong:
                    strong.append(tok)
            elif tok != tok.lower() and tok not in weak:
                weak.append(tok)
        return strong + weak

    @staticmethod
    def _relocate(lines: list[str], anchors: list[str], current: int) -> int | None:
        """Where an anchor now lives (1-based), or None if not confident.

        Returns ``current`` unchanged if the pointed-at line still holds an
        anchor (case-insensitive — a note may say `Promote` for `def promote`).
        Otherwise tries every anchor at the DEFINITION stage before falling
        back to calls, then bare mentions — so a strong anchor's `def` wins
        over a weak anchor's stray mention (see _anchors' ordering rationale).
        """
        if not anchors:
            return current if 1 <= current <= len(lines) else None
        lower_lines = [line.lower() for line in lines]
        lower_anchors = [a.lower() for a in anchors]
        if 1 <= current <= len(lines) and any(a in lower_lines[current - 1] for a in lower_anchors):
            return current
        for stage in ("def", "call", "mention"):
            for anchor in lower_anchors:
                if stage == "def":
                    hits = [
                        i + 1
                        for i, line in enumerate(lower_lines)
                        if anchor in line and _DEF_RE.search(lines[i])
                    ]
                elif stage == "call":
                    hits = [i + 1 for i, line in enumerate(lower_lines) if (anchor + "(") in line]
                else:
                    hits = [i + 1 for i, line in enumerate(lower_lines) if anchor in line]
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
