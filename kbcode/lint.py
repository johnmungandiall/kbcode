"""Post-edit syntax check (the Aider idea): right after write_file/edit_file/
edit_files lands, cheaply verify the file still PARSES and hand any error back
to the model inside the tool result — so a bad edit is fixed in the very next
step instead of surfacing later when the code runs. Deliberately syntax-level
only: pure-stdlib parsers, no external linter subprocesses, so it is
dependency-free, instant, and hang-proof. A lint problem is a NOTE appended to
a successful write, never a failure — the file was already written.
"""

from __future__ import annotations

import json
from pathlib import Path


def lint_text(path: Path | str, text: str) -> str | None:
    """Return a short parse-error description for the would-be file content,
    or None when it parses — or when the file type has no checker (only types
    with a stdlib/importable parser are checked; everything else passes)."""
    checker = _CHECKERS.get(Path(path).suffix.lower())
    if checker is None:
        return None
    try:
        return checker(str(path), text)
    except Exception:
        # A misbehaving checker must never taint the write result itself.
        return None


def _context(text: str, lineno: int, around: int = 1) -> str:
    """The offending line marked with █, with `around` lines each side."""
    lines = text.splitlines()
    if not 1 <= lineno <= len(lines):
        return ""
    start = max(1, lineno - around)
    end = min(len(lines), lineno + around)
    out = []
    for i in range(start, end + 1):
        marker = "█" if i == lineno else " "
        out.append(f"{i:>5}{marker} {lines[i - 1][:200]}")
    return "\n".join(out)


def _check_python(name: str, text: str) -> str | None:
    try:
        compile(text, name, "exec")
    except SyntaxError as e:
        lineno = e.lineno or 0
        msg = f"Python syntax error at line {lineno}: {e.msg}"
        ctx = _context(text, lineno)
        return f"{msg}\n{ctx}" if ctx else msg
    return None


def _check_json(name: str, text: str) -> str | None:
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        msg = f"JSON parse error at line {e.lineno}, column {e.colno}: {e.msg}"
        ctx = _context(text, e.lineno)
        return f"{msg}\n{ctx}" if ctx else msg
    return None


def _check_toml(name: str, text: str) -> str | None:
    try:
        import tomllib
    except ImportError:  # Python < 3.11
        return None
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return f"TOML parse error: {e}"
    return None


def _check_yaml(name: str, text: str) -> str | None:
    try:
        import yaml
    except ImportError:  # PyYAML is optional; skip rather than guess
        return None
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as e:
        return f"YAML parse error: {e}"
    return None


_CHECKERS = {
    ".py": _check_python,
    ".pyw": _check_python,
    ".json": _check_json,
    ".toml": _check_toml,
    ".yaml": _check_yaml,
    ".yml": _check_yaml,
}
