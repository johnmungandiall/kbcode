"""File and shell-command tools — the "hands" (Claude Code idea): read/write/
edit files, list directories, search code, and run commands.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from ..redact import redact_terminal_output_with_count, redact_with_count

# Directories we never scan when searching code.
_SKIP_DIRS = {".git", ".kbcode", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
_MAX_READ_CHARS = 60000
_MIN_READ_CHARS = 2000  # never truncate a read this aggressively, even under context pressure

# Production safety rail (the Hermes file_safety idea): files the agent must
# never write to or edit. Secrets, VCS/agent internals — the user can still
# change these by hand, the agent just won't clobber them. _resolve already
# confines paths to the project root; this guards what's *inside* it.
_PROTECTED_DIRS = {".git", ".ssh"}  # off-limits anywhere in the path
_PROTECTED_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".npmrc", ".pypirc", ".netrc"}
_PROTECTED_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".keystore"}
_KBCODE_STATE = {"memory.db", "settings.json"}  # only protected under .kbcode/
_ENV_TEMPLATE_TAILS = {"example", "sample", "template", "dist", "defaults"}  # .env.example is fine

# Absolute-path prefixes that are almost certainly OS/system directories, not
# project files. This is a *warning*, not a block — _resolve() honors absolute
# paths by design (kbcode isn't sandboxed to the project root) — it just makes
# the existing write_file/edit_file permission prompt harder to miss for these.
_SYSTEM_PATH_PREFIXES = (
    "/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc", "/lib", "/lib64",
    "/system", "/library",  # macOS
    "c:/windows", "c:/program files", "c:/program files (x86)", "c:/programdata",
)

# Safety rail (#6.1/#6.4): a runaway loop firing dozens of shell commands in one
# turn, or an outright destructive one, should be caught before it runs.
_MAX_COMMANDS_PER_TURN = 25
_DANGEROUS_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+(-\w*r\w*f\w*|-\w*f\w*r\w*)\s+/(\s|$)"),  # rm -rf /
    re.compile(r"\brm\s+(-\w*r\w*f\w*|-\w*f\w*r\w*)\s+/\*"),  # rm -rf /*
    re.compile(r"\brm\s+(-\w*r\w*f\w*|-\w*f\w*r\w*)\s+~(\s|/|$)"),  # rm -rf ~
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),  # fork bomb
    re.compile(r"\bmkfs\.\w+\b"),
    re.compile(r"\bdd\s+.*\bof=/dev/(disk|sd|hd|nvme)"),
    re.compile(r">\s*/dev/(sda|sdb|nvme\d*n\d*|disk\d*)\b"),
    re.compile(r"\bchmod\s+-R\s+000\s+/"),
    re.compile(r"\bchmod\s+-R\s+777\s+/(\s|$)"),
    re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE),  # Windows `format C:`
    re.compile(r"\bRemove-Item\b.*-Recurse.*-Force\b.*[/\\]\s*$", re.IGNORECASE),
]


class FileToolsMixin:
    """read_file/write_file/edit_file/list_dir/search_code/run_command.

    Composed into the ``Tools`` facade alongside ``ToolsCore`` (which
    supplies ``self.root``/``self.perm``/``self.checkpoints``/etc.) and the
    other tool-category mixins — see ``tools/__init__.py``.
    """

    def _read_limit(self) -> int:
        """How many chars a single read_file result may return.

        Fixed by default; Agent narrows ``context_budget_chars`` as the
        conversation nears its compaction threshold (#4.2), so one huge file
        read can't single-handedly blow past the context budget. Never goes
        below ``_MIN_READ_CHARS`` — a read that's truncated to uselessness
        isn't a real budget saving.
        """
        if self.context_budget_chars is None:
            return _MAX_READ_CHARS
        return max(_MIN_READ_CHARS, min(_MAX_READ_CHARS, self.context_budget_chars))

    @staticmethod
    def _is_system_path(p: Path) -> bool:
        low = str(p).replace("\\", "/").lower()
        return any(low.startswith(prefix) for prefix in _SYSTEM_PATH_PREFIXES)

    @staticmethod
    def _is_dangerous_command(command: str) -> bool:
        return any(pattern.search(command) for pattern in _DANGEROUS_COMMAND_PATTERNS)

    def _protected_reason(self, p: Path) -> str | None:
        """Return *why* writing to ``p`` is refused (a safety rail), or None if
        it's fine. Checked against the full resolved path, not just relative to
        the project root, since ``p`` may now be anywhere on disk."""
        parts = p.parts
        if any(part in _PROTECTED_DIRS for part in parts):
            hit = next(part for part in parts if part in _PROTECTED_DIRS)
            return f"inside the protected '{hit}/' directory"
        if p.name in _KBCODE_STATE and ".kbcode" in parts:
            return "kbcode's own state file"
        if p.name in _PROTECTED_NAMES:
            return "a credentials file"
        if p.suffix.lower() in _PROTECTED_SUFFIXES:
            return "a private key / certificate"
        low = p.name.lower()
        if low == ".env":
            return "an environment/secrets file"
        if low.startswith(".env."):
            tail = low.split(".", 2)[2] if low.count(".") >= 2 else ""
            if tail not in _ENV_TEMPLATE_TAILS:
                return "an environment/secrets file"
        return None

    # --- file tools ----------------------------------------------------
    def _tool_read_file(self, inp: dict) -> str:
        """Return the file as ``line\\ttext``.

        Supports optional 'offset' (1-based) and 'limit' (line count) for
        reading only a slice of large files. The char budget still applies to
        the final returned text (range reads are preferred for huge files).
        Original line numbers are preserved in the output.

        When a range is requested, lines are read incrementally without loading
        the entire file (avoids OOM / waste on giant files + Skip 1950 style reads).
        """
        p = self._resolve(inp["path"])
        if not p.exists():
            raise ValueError(f"No such file: {inp['path']}")

        offset = inp.get("offset")
        line_limit = inp.get("limit")  # lines to read, not char limit
        char_limit = self._read_limit()

        if offset is not None or line_limit is not None:
            # Efficient range read: stream lines, skip prefix, stop early.
            # This directly solves the previous "powershell Get-Content -Skip 1950" pattern.
            start_line = max(1, (offset or 1))
            max_lines = line_limit if line_limit is not None else None

            numbered_parts = []
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    for i, raw in enumerate(f, 1):
                        if i < start_line:
                            continue
                        if max_lines is not None and len(numbered_parts) >= max_lines:
                            break
                        line = raw.rstrip("\n\r")
                        numbered_parts.append(f"{i}\t{line}")
            except OSError as exc:
                raise ValueError(f"Failed to read {inp['path']}: {exc}") from exc

            out = "\n".join(numbered_parts)
        else:
            # Full file path (kept for small files and simplicity)
            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            out = "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines))

        # Apply char budget truncation (on the produced output)
        truncated = False
        if len(out) > char_limit:
            out = out[:char_limit] + "\n[...file truncated...]"
            truncated = True

        out, redacted = redact_with_count(out, code_file=True)
        return self._note_redactions(out, redacted)

    def _tool_write_file(self, inp: dict) -> str:
        """Create/overwrite a file, after the protected-path check and a permission prompt."""
        p = self._resolve(inp["path"])
        n = len(inp["content"])
        reason = self._protected_reason(p)
        if reason:
            raise ValueError(
                f"Refused: {p} is {reason}, which kbcode won't write automatically. "
                "Edit it yourself if you really need to."
            )
        # Show the full resolved path (not the model's bare relative name) so the
        # user always knows exactly where the file lands — and what they're approving.
        # Flag it when that's outside the project, since it's easy to miss otherwise.
        detail = f"write {p} ({n} chars)"
        if self._is_outside_project(p):
            detail += " -- OUTSIDE the project folder"
        if self._is_system_path(p):
            detail += " -- !! looks like an OS/system directory !!"
        if p.is_file():
            try:
                old = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                old = None
            if old is not None and old != inp["content"]:
                detail += "\n" + self._unified_diff(old, inp["content"], f"{p} (current)", f"{p} (new)")
        if not self.perm.check("write_file", detail):
            raise PermissionError("User denied permission to write the file.")
        self.checkpoints.ensure_checkpoint("before write_file")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inp["content"], encoding="utf-8")
        return f"wrote {p} ({n} chars)"

    def _tool_edit_file(self, inp: dict) -> str:
        """Replace one exact occurrence of old_string with new_string in an existing file."""
        p = self._resolve(inp["path"])
        reason = self._protected_reason(p)
        if reason:
            raise ValueError(
                f"Refused: {p} is {reason}, which kbcode won't edit automatically. "
                "Edit it yourself if you really need to."
            )
        if not p.exists():
            raise ValueError(f"No such file: {inp['path']}")
        text = p.read_text(encoding="utf-8", errors="replace")
        count = text.count(inp["old_string"])
        if count == 0:
            raise ValueError("old_string not found in file.")
        if count > 1:
            raise ValueError(f"old_string appears {count} times; make it unique.")
        new_text = text.replace(inp["old_string"], inp["new_string"], 1)
        detail = f"edit {p}"
        if self._is_outside_project(p):
            detail += " -- OUTSIDE the project folder"
        if self._is_system_path(p):
            detail += " -- !! looks like an OS/system directory !!"
        detail += "\n" + self._unified_diff(text, new_text, f"{p} (current)", f"{p} (new)")
        if not self.perm.check("edit_file", detail):
            raise PermissionError("User denied permission to edit the file.")
        self.checkpoints.ensure_checkpoint("before edit_file")
        p.write_text(new_text, encoding="utf-8")
        return f"edited {p}"

    def _tool_edit_files(self, inp: dict) -> str:
        """Apply multiple precise edits across files. Each requires unique old_string.
        Provides a single permission prompt summary. Inspired by coordinated multi-file
        AI edits in advanced editors."""
        edits = inp.get("edits", [])
        if not edits:
            return "No edits provided."

        summaries = []
        protected_errors = []

        for edit in edits:
            path = edit["path"]
            old = edit["old_string"]
            new = edit["new_string"]

            p = self._resolve(path)
            reason = self._protected_reason(p)
            if reason:
                protected_errors.append(f"{p} is {reason}")
                continue

            if not p.exists():
                protected_errors.append(f"No such file: {path}")
                continue

            text = p.read_text(encoding="utf-8", errors="replace")
            count = text.count(old)
            if count == 0:
                protected_errors.append(f"old_string not found in {path}")
                continue
            if count > 1:
                protected_errors.append(f"old_string appears {count} times in {path}; must be unique")
                continue

            new_text = text.replace(old, new, 1)
            diff = self._unified_diff(text, new_text, f"{p} (current)", f"{p} (new)")
            outside = " (outside project)" if self._is_outside_project(p) else ""
            summaries.append(f"edit {p}{outside}:\n{diff}")

        if protected_errors:
            return "Some edits blocked:\n" + "\n".join(protected_errors)

        if not summaries:
            return "No valid edits."

        # Single permission prompt for the batch
        detail = "Apply the following edits:\n\n" + "\n\n".join(summaries)
        if not self.perm.check("edit_files", detail):
            raise PermissionError("User denied permission for the batch edits.")

        self.checkpoints.ensure_checkpoint("before edit_files")

        results = []
        for edit in edits:
            path = edit["path"]
            old = edit["old_string"]
            new = edit["new_string"]
            p = self._resolve(path)
            text = p.read_text(encoding="utf-8", errors="replace")
            new_text = text.replace(old, new, 1)
            p.write_text(new_text, encoding="utf-8")
            results.append(f"edited {p}")

        return "\n".join(results)

    def _tool_list_dir(self, inp: dict) -> str:
        """List a directory's immediate entries (dirs suffixed with /), skipping _SKIP_DIRS."""
        p = self._resolve(inp.get("path", "."))
        if not p.is_dir():
            raise ValueError(f"Not a directory: {inp.get('path', '.')}")
        entries = []
        for item in sorted(p.iterdir()):
            if item.name in _SKIP_DIRS:
                continue
            entries.append(item.name + ("/" if item.is_dir() else ""))
        return "\n".join(entries) or "(empty)"

    def _ripgrep_available(self) -> bool:
        if self._rg_available is None:
            self._rg_available = shutil.which("rg") is not None
        return self._rg_available

    def _rg_candidate_files(self, pattern: str, base: Path) -> list[Path] | None:
        """Files under ``base`` that ripgrep says contain ``pattern`` (#10.3)
        — a fast, gitignore-aware pre-filter so a full-repo search doesn't
        walk every file in Python. Returns None (meaning "fall back to a full
        walk") when ``rg`` isn't installed, times out, or errors — e.g. on a
        regex ripgrep's engine doesn't accept, even though Python's ``re``
        does — so a scan never fails just because the fast path couldn't run.
        """
        if not self._ripgrep_available():
            return None
        try:
            proc = subprocess.run(
                ["rg", "--files-with-matches", "--no-messages", "-e", pattern, str(base)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode not in (0, 1):  # 0 = matches, 1 = no matches, 2+ = rg itself errored
            return None
        files: list[Path] = []
        for line in proc.stdout.splitlines():
            p = Path(line)
            if not any(part in _SKIP_DIRS for part in p.parts):
                files.append(p)
        return files

    def _walk_files(self, base: Path):
        """The pre-ripgrep fallback file listing: every file under base, skipping _SKIP_DIRS."""
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                yield Path(dirpath) / fn

    def _tool_search_code(self, inp: dict) -> str:
        """Regex-search the project (ripgrep-accelerated when available). Supports 'path' for scoping and 'limit' (default 50, max 100) to keep results manageable and avoid loops."""
        pattern = inp["pattern"]
        regex = re.compile(pattern)
        base = self._resolve(inp.get("path", "."))
        limit = min(inp.get("limit", 50), 100)
        candidates = self._rg_candidate_files(pattern, base)
        files = candidates if candidates is not None else self._walk_files(base)

        hits: list[str] = []
        redacted = 0
        for fp in files:
            try:
                with fp.open("r", encoding="utf-8", errors="strict") as fh:
                    for i, line in enumerate(fh, 1):
                        if regex.search(line):
                            rel = self._display_path(fp)
                            snippet, n = redact_with_count(line.rstrip()[:200], code_file=True)
                            redacted += n
                            hits.append(f"{rel}:{i}: {snippet}")
                            if len(hits) >= limit:
                                return self._note_redactions(
                                    "\n".join(hits) + f"\n[...stopped at {limit} matches...]", redacted
                                )
            except (UnicodeDecodeError, OSError):
                continue  # skip binary/unreadable files
        return self._note_redactions("\n".join(hits) or "(no matches)", redacted)

    def _tool_run_command(self, inp: dict) -> str:
        """Run a shell command in the project root, gated by rate limit, danger check, and permission."""
        command = inp["command"]
        self._run_command_count += 1
        if self._run_command_count > _MAX_COMMANDS_PER_TURN:
            raise ValueError(
                f"Refused: hit the safety limit of {_MAX_COMMANDS_PER_TURN} run_command calls in "
                "one turn (a runaway loop guard). Wrap up this turn and continue in the next message "
                "if you genuinely need more."
            )
        if self._is_dangerous_command(command):
            raise ValueError(
                f"Refused: '{command}' matches a pattern kbcode treats as destructive "
                "(e.g. wiping a filesystem root, a fork bomb, formatting a drive). "
                "Run it yourself in a terminal if you really mean it."
            )
        if not self.perm.check("run_command", f"$ {command}"):
            raise PermissionError("User denied permission to run the command.")
        self.checkpoints.ensure_checkpoint("before run_command")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return "Command timed out after 180s."
        out, n1 = redact_terminal_output_with_count((proc.stdout or "")[-8000:], command)
        err, n2 = redact_terminal_output_with_count((proc.stderr or "")[-4000:], command)
        result = f"exit code: {proc.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
        return self._note_redactions(result, n1 + n2)

    def _tool_repo_map(self, inp: dict) -> str:
        """Return a concise structural map of key symbols (classes, functions, etc.)
        across the project or a subdirectory. Inspired by advanced repo mapping
        techniques (like Aider) to help understand large codebases cheaply.
        Limits to ~5 symbols per file for readability."""
        base = self._resolve(inp.get("path", "."))
        if not base.is_dir():
            base = base.parent if base.parent.exists() else self.root

        symbols = []
        max_symbols = 300
        max_per_file = 5
        files_scanned = 0

        # Prefer ripgrep for speed and accuracy if available
        if self._ripgrep_available():
            try:
                # Search for common definition patterns
                rg_cmd = ["rg", "--no-heading", "-n", "-e", r"^\s*(def |class |async def |function |func |const \w+\s*=|let \w+\s*=)", str(base), "--glob", "!*.min.*", "--max-columns", "150"]
                proc = subprocess.run(rg_cmd, capture_output=True, text=True, timeout=30)
                if proc.returncode in (0, 1):
                    lines = proc.stdout.strip().splitlines()
                    per_file = {}
                    for line in lines:
                        if ":" not in line:
                            continue
                        parts = line.split(":", 2)
                        if len(parts) < 3:
                            continue
                        fpath, lineno, content = parts[0], parts[1], parts[2].strip()[:150]
                        rel = self._display_path(Path(fpath))
                        if rel not in per_file:
                            per_file[rel] = []
                        if len(per_file[rel]) < max_per_file:
                            per_file[rel].append(f"{rel}:{lineno}: {content}")
                            symbols.append(f"{rel}:{lineno}: {content}")
                            if len(symbols) >= max_symbols:
                                break
                    files_scanned = len(per_file)
                    if symbols:
                        header = f"Repository map (rg-based, {files_scanned} files, limited to {max_per_file} symbols/file):\n"
                        return header + "\n".join(symbols[:max_symbols])
            except Exception:
                pass  # fallback to python

        # Fallback: python walk
        for fp in self._walk_files(base):
            files_scanned += 1
            if len(symbols) >= max_symbols:
                break
            per_file_count = 0
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")[:30000]
                rel = self._display_path(fp)
                for i, line in enumerate(text.splitlines(), 1):
                    if per_file_count >= max_per_file:
                        break
                    s = line.strip()
                    if not s or s.startswith(("#", "//", "/*", "*")):
                        continue
                    if any(kw in s for kw in ("def ", "class ", "function ", "async def ", "func ", "const ", "let ", "var ")):
                        snippet = s[:150]
                        symbols.append(f"{rel}:{i}: {snippet}")
                        per_file_count += 1
                        if len(symbols) >= max_symbols:
                            break
            except (UnicodeDecodeError, OSError, PermissionError):
                continue

        if not symbols:
            return "(no code symbols found — try a specific path or ensure project has source files)"

        header = f"Repository map ({files_scanned} files scanned, ~{max_per_file} symbols per file):\n"
        footer = "\n[...truncated...]" if len(symbols) >= max_symbols else ""
        return header + "\n".join(symbols) + footer
