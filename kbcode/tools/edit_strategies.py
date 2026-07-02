"""Flexible search/replace with multiple strategies (the Aider idea).

When an ``edit_file`` / ``edit_files`` exact match fails — often because the model
gets indentation slightly wrong or adds extra blank lines — this module tries a
sequence of progressively more lenient strategies before giving up.

Strategy order (decreasing strictness):
  1. **exact**          — the current behavior; strict string equality
  2. **strip-blanks**   — strip leading/trailing blank lines, then exact
  3. **indent**         — normalize indentation (relative indent), then exact
  4. **strip+indent**   — both of the above combined
  5. **fuzzy**          — difflib line-based similarity (requires ≥70 % match)

Each strategy returns ``(new_file_text, strategy_name)`` or raises ``ValueError``.
"""

from __future__ import annotations

import difflib
from typing import Callable


def _leading_ws(line: str) -> int:
    """Number of leading whitespace characters."""
    return len(line) - len(line.lstrip())


# ── public entry point ──────────────────────────────────────────────────────


def try_edit(file_text: str, old: str, new: str) -> tuple[str, str]:
    """Apply an edit, trying strategies in order.

    Returns ``(new_file_text, strategy_name)`` on success.
    Raises ``ValueError`` if every strategy fails.
    """
    errors: list[str] = []

    for name, func in _STRATEGIES:
        try:
            result = func(file_text, old, new)
            return result, name
        except ValueError as exc:
            errors.append(f"  {name}: {exc}")

    raise ValueError("All edit strategies failed:\n" + "\n".join(errors))


# ── strategies ──────────────────────────────────────────────────────────────


def _try_exact(file_text: str, old: str, new: str) -> str:
    """Exact string match — the current behaviour."""
    count = file_text.count(old)
    if count == 0:
        raise ValueError("old_string not found")
    if count > 1:
        raise ValueError(f"appears {count} times; must be unique")
    return file_text.replace(old, new, 1)


def _try_strip_blanks(file_text: str, old: str, new: str) -> str:
    """Strip leading / trailing blank lines from *both* old and new, then exact."""
    old_lines = old.splitlines(True)
    new_lines = new.splitlines(True)

    # Strip leading blank lines in lockstep
    while old_lines and old_lines[0].strip() == "":
        old_lines.pop(0)
        if new_lines and new_lines[0].strip() == "":
            new_lines.pop(0)

    # Strip trailing blank lines in lockstep
    while old_lines and old_lines[-1].strip() == "":
        old_lines.pop()
        if new_lines and new_lines[-1].strip() == "":
            new_lines.pop()

    old_s = "".join(old_lines)
    new_s = "".join(new_lines)

    if old_s == old:
        raise ValueError("no blank lines to strip")

    count = file_text.count(old_s)
    if count == 0:
        raise ValueError("not found after stripping blanks")
    if count > 1:
        raise ValueError(f"appears {count} times after stripping blanks")

    return file_text.replace(old_s, new_s, 1)


def _try_indent(file_text: str, old: str, new: str) -> str:
    """Normalise indentation — strip the common leading whitespace from every
    line, then exact-match; the new text inherits the file's indentation at the
    match site so the edit is transparent to the rest of the file."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    file_lines = file_text.splitlines()

    # --- compute common indent of *old* (relative indentation) ---
    o_non_empty = [l for l in old_lines if l.strip()]
    if not o_non_empty:
        raise ValueError("old_string is all blank")
    old_min = min(_leading_ws(l) for l in o_non_empty)

    # Build the "ideal" relative form of the old block (lines without the
    # common indent, anchored so the first non-empty line starts at column 0).
    old_rel_lines = [
        l[old_min:] if l.strip() else l.lstrip() for l in old_lines
    ]

    # --- scan the file for a region whose *stripped* lines match ---
    old_stripped = [l.lstrip() for l in old_rel_lines]

    match_index = -1
    for i in range(len(file_lines) - len(old_lines) + 1):
        candidate = file_lines[i : i + len(old_lines)]
        if [l.lstrip() for l in candidate] != old_stripped:
            continue
        if match_index != -1:
            raise ValueError(
                "ambiguous — appears multiple times after normalising indentation; "
                "make old_string more specific"
            )
        match_index = i

    if match_index == -1:
        raise ValueError("not found after normalising indentation")

    i = match_index
    candidate = file_lines[i : i + len(old_lines)]

    # Compute the indent delta for each line so the new
    # block slides by the same amount.
    result_lines: list[str] = []
    for j, nl in enumerate(new_lines):
        nl_ws = _leading_ws(nl) if nl.strip() else 0
        # The *old* line's canonical indent in this file slice.
        file_ws = (
            _leading_ws(candidate[min(j, len(candidate) - 1)])
            if j < len(candidate) and candidate[j].strip()
            else old_min
        )
        old_ws = (
            _leading_ws(old_lines[min(j, len(old_lines) - 1)])
            if j < len(old_lines) and old_lines[j].strip()
            else old_min
        )
        delta = file_ws - old_ws
        new_ws = max(0, nl_ws + delta)
        result_lines.append(" " * new_ws + nl.lstrip() if nl.strip() else nl)

    return "\n".join(
        file_lines[:i] + result_lines + file_lines[i + len(old_lines) :]
    )

    raise ValueError("not found after normalising indentation")


def _try_strip_indent(file_text: str, old: str, new: str) -> str:
    """Strip blanks AND normalise indentation, then exact match."""
    # First strip blanks from both
    old_lines = old.splitlines(True)
    new_lines = new.splitlines(True)
    while old_lines and old_lines[0].strip() == "":
        old_lines.pop(0)
        if new_lines and new_lines[0].strip() == "":
            new_lines.pop(0)
    while old_lines and old_lines[-1].strip() == "":
        old_lines.pop()
        if new_lines and new_lines[-1].strip() == "":
            new_lines.pop()

    old_s = "".join(old_lines)
    new_s = "".join(new_lines)

    if old_s == old:
        raise ValueError("no blanks to strip — skipping combined strip+indent")

    # Then try indent-flexible match on the stripped pair
    return _try_indent(file_text, old_s, new_s)


def _try_fuzzy(file_text: str, old: str, new: str) -> str:
    """Line-based fuzzy match via difflib.

    Splits both old and file into lines, strips each line, then finds the
    longest contiguous region whose stripped lines are ≥70 % identical to
    old's stripped lines.  That region is replaced wholesale with *new*.
    Requires a *unique* best match — if multiple regions tie at the same
    score the edit is ambiguous.
    """
    old_lines = old.splitlines()
    new_lines = new.splitlines(True)  # preserve new's line-endings
    file_lines = file_text.splitlines(True)  # preserve file's line-endings

    if not old_lines:
        raise ValueError("old_string is empty")

    old_stripped = [l.strip() for l in old_lines]

    best_match = -1
    best_score = 0.0
    tie_count = 0

    for i in range(len(file_lines) - len(old_lines) + 1):
        file_slice = [l.strip() for l in file_lines[i : i + len(old_lines)]]
        matches = sum(1 for a, b in zip(file_slice, old_stripped) if a == b)
        score = matches / len(old_stripped)
        if score > best_score:
            best_score = score
            best_match = i
            tie_count = 1
        elif score == best_score and score > 0:
            tie_count += 1

    if tie_count > 1:
        raise ValueError(f"ambiguous — {tie_count} regions with {best_score:.0%} similarity; make old_string more specific")

    if best_score < 0.7:
        raise ValueError(f"best fuzzy match only {best_score:.0%} similar (need ≥70 %)")

    # Replace the matched region
    result = "".join(
        file_lines[:best_match]
        + list(new_lines)
        + file_lines[best_match + len(old_lines) :]
    )
    return result


# ── ordered strategy registry ───────────────────────────────────────────────

_STRATEGIES: list[tuple[str, "StrategyFunc"]] = [
    ("exact", _try_exact),
    ("strip-blanks", _try_strip_blanks),
    ("indent", _try_indent),
    ("strip+indent", _try_strip_indent),
    ("fuzzy", _try_fuzzy),
]

StrategyFunc = Callable[[str, str, str], str]  # (file_text, old, new) -> new_text


# ── convenience: single-strategy runner for batch edits ────────────────────

def try_single_strategy(
    file_text: str, old: str, new: str
) -> str:
    """Run the FIRST successful strategy and return new text.

    Raises ``ValueError`` if none succeed.  This is the thin wrapper used by
    ``edit_files`` batch mode so each edit can fall back independently.
    """
    result, _name = try_edit(file_text, old, new)
    return result
