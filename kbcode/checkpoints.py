"""Automatic pre-edit snapshots + rollback (the Hermes idea).

Before the agent's first file-mutating tool call each turn, take a cheap
snapshot of the project — a commit in a hidden shadow git repo that never
touches the user's real `.git` (separate `GIT_DIR`/`GIT_WORK_TREE`/
`GIT_INDEX_FILE`, no shared config). If the agent goes sideways, `/rollback`
puts the working tree back exactly where it was.

The shadow repo lives in the project's state dir (`~/.kbcode/projects/<slug>/
checkpoints/`, see `Config.state_dir`) — outside the project's working tree,
so it never shows up in the host project's git. Deleting that folder is always
safe — it just forgets
the undo history.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_REF = "refs/kbcode/checkpoint"
_GIT_TIMEOUT = 30
_COMMIT_HASH_RE = re.compile(r"^[0-9a-fA-F]{4,40}$")

# Never snapshot these — kbcode's own state, VCS internals, dependency /
# build output, and anything secret-shaped (mirrors redact.py's stance).
_EXCLUDES = [
    ".git/", ".kbcode/",
    "node_modules/", "dist/", "build/", "target/", "out/",
    "__pycache__/", "*.pyc", ".venv/", "venv/",
    ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
    ".env", ".env.*",
    "*.so", "*.dll", "*.dylib", "*.exe",
    "*.zip", "*.tar", "*.tar.gz", "*.7z",
    ".DS_Store", "Thumbs.db",
]


def _validate_hash(commit_hash: str) -> str | None:
    """Return an error string if ``commit_hash`` is unsafe/malformed, else None.

    Rejects anything git would interpret as a flag (e.g. a leading ``-``),
    which would otherwise let a checkpoint id smuggle arbitrary git options.
    """
    if not commit_hash or commit_hash.startswith("-"):
        return f"Invalid checkpoint id: {commit_hash!r}"
    if not _COMMIT_HASH_RE.match(commit_hash):
        return f"Invalid checkpoint id (expected a hex commit hash): {commit_hash!r}"
    return None


class Checkpoints:
    """Owns one shadow git store for a single project directory."""

    def __init__(self, project_root: Path, store_dir: Path):
        self.root = project_root
        self.store = store_dir
        self.index_file = store_dir / "index"
        self._taken_this_turn = False
        self._git_available: bool | None = None

    def new_turn(self) -> None:
        """Reset the once-per-turn dedup. Call at the start of each agent turn."""
        self._taken_this_turn = False

    # -- git plumbing -----------------------------------------------------
    def _git(self, args: list[str]) -> tuple[int, str, str]:
        """Run a git command against the shadow store. Returns (returncode, stdout, stderr).

        Returns the *raw* exit code rather than a collapsed ok/fail boolean —
        several callers need to distinguish specific nonzero codes (e.g.
        ``diff-index --quiet`` uses 0 = clean / 1 = dirty; ``rev-parse
        --verify`` on a ref that doesn't exist yet uses 128), which a single
        boolean can't represent.
        """
        env = os.environ.copy()
        env["GIT_DIR"] = str(self.store)
        env["GIT_WORK_TREE"] = str(self.root)
        env["GIT_INDEX_FILE"] = str(self.index_file)
        # Isolate from the user's git config — no signing prompts, no hooks.
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_SYSTEM"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(self.root),
                env=env,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return -1, "", str(exc)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def _available(self) -> bool:
        if self._git_available is None:
            self._git_available = shutil.which("git") is not None
        return self._git_available

    def _ensure_store(self) -> bool:
        if (self.store / "HEAD").exists():
            return True
        if not self._available():
            return False
        self.store.mkdir(parents=True, exist_ok=True)
        init_env = os.environ.copy()
        init_env["GIT_CONFIG_GLOBAL"] = os.devnull
        init_env["GIT_CONFIG_SYSTEM"] = os.devnull
        init_env["GIT_CONFIG_NOSYSTEM"] = "1"
        proc = subprocess.run(
            ["git", "init", "--quiet", "--bare", str(self.store)],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT, env=init_env,
        )
        if proc.returncode != 0:
            return False
        self._git(["config", "user.email", "kbcode@local"])
        self._git(["config", "user.name", "kbcode checkpoints"])
        self._git(["config", "commit.gpgsign", "false"])
        self._git(["config", "gc.auto", "0"])
        info = self.store / "info"
        info.mkdir(exist_ok=True)
        (info / "exclude").write_text("\n".join(_EXCLUDES) + "\n", encoding="utf-8")
        return True

    # -- public API ---------------------------------------------------------
    def ensure_checkpoint(self, reason: str = "auto") -> bool:
        """Snapshot the project if not already done this turn. Never raises."""
        if self._taken_this_turn:
            return False
        self._taken_this_turn = True  # dedup even on failure — don't retry every tool call
        try:
            return self._take(reason)
        except Exception:
            log.debug("checkpoint failed (reason=%s) — continuing without a snapshot", reason, exc_info=True)
            return False

    def _take(self, reason: str) -> bool:
        if not self._ensure_store():
            return False

        rc_ref, ref_commit, _ = self._git(["rev-parse", "--verify", _REF + "^{commit}"])
        has_ref = rc_ref == 0 and bool(ref_commit)
        if has_ref:
            self._git(["read-tree", ref_commit])
        elif self.index_file.exists():
            try:
                self.index_file.unlink()
            except OSError:
                pass

        rc_add, _, _ = self._git(["add", "-A"])
        if rc_add != 0:
            return False

        if has_ref:
            # `--quiet` exits 0 when the staged tree matches ref_commit (clean,
            # nothing to snapshot) and 1 when it differs (dirty, proceed).
            rc_diff, _, _ = self._git(["diff-index", "--cached", "--quiet", ref_commit])
            if rc_diff == 0:
                return False  # nothing changed since the last checkpoint
        else:
            rc_ls, ls_out, _ = self._git(["ls-files", "--cached"])
            if rc_ls == 0 and not ls_out.strip():
                return False  # nothing to snapshot yet

        rc_tree, tree_sha, _ = self._git(["write-tree"])
        if rc_tree != 0 or not tree_sha:
            return False

        commit_args = ["commit-tree", tree_sha, "-m", reason]
        if has_ref:
            commit_args += ["-p", ref_commit]
        rc_commit, new_sha, _ = self._git(commit_args)
        if rc_commit != 0 or not new_sha:
            return False

        rc_update, _, _ = self._git(["update-ref", _REF, new_sha])
        return rc_update == 0

    def list_checkpoints(self, limit: int = 20) -> list[dict]:
        """Most-recent-first list of ``{hash, short, when, reason}``."""
        if not (self.store / "HEAD").exists():
            return []
        rc, out, _ = self._git(["log", _REF, "--format=%H|%h|%aI|%s", "-n", str(limit)])
        if rc != 0 or not out:
            return []
        rows = []
        for line in out.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                rows.append({"hash": parts[0], "short": parts[1], "when": parts[2], "reason": parts[3]})
        return rows

    def restore(self, commit_hash: str, file_path: str | None = None) -> str:
        """Restore the working tree (or one file) to a checkpoint.

        Returns a human-readable status message (never raises).
        """
        err = _validate_hash(commit_hash)
        if err:
            return err
        if not (self.store / "HEAD").exists():
            return "No checkpoints exist yet."
        rc, _, _ = self._git(["cat-file", "-t", commit_hash])
        if rc != 0:
            return f"No checkpoint matches '{commit_hash}'."
        if file_path:
            target = (self.root / file_path).resolve()
            if self.root not in target.parents and target != self.root:
                return f"Path escapes the project root: {file_path}"

        # Snapshot the pre-restore state too, so a restore can itself be undone.
        self._take(f"before restoring to {commit_hash[:8]}")

        rc, _, err_out = self._git(["checkout", commit_hash, "--", file_path or "."])
        if rc != 0:
            return f"Restore failed: {err_out}"
        target = file_path or "the whole project"
        return f"Restored {target} to checkpoint {commit_hash[:8]}."

    def diff(self, commit_hash: str) -> str:
        """Diff a checkpoint against the current working tree."""
        err = _validate_hash(commit_hash)
        if err:
            return err
        if not (self.store / "HEAD").exists():
            return "No checkpoints exist yet."
        rc, _, _ = self._git(["cat-file", "-t", commit_hash])
        if rc != 0:
            return f"No checkpoint matches '{commit_hash}'."
        self._git(["add", "-A"])  # stage current state to diff against
        rc_diff, diff_out, _ = self._git(["diff", commit_hash, "--cached", "--no-color"])
        return diff_out if rc_diff == 0 and diff_out else "(no differences)"


def format_checkpoints(rows: list[dict]) -> str:
    """Render a checkpoint list for `/rollback` (no args)."""
    if not rows:
        return "No checkpoints yet — they're taken automatically before file edits."
    lines = [f"  {i}. {r['short']}  {r['when'][:16].replace('T', ' ')}  {r['reason']}" for i, r in enumerate(rows, 1)]
    lines.append("")
    lines.append("  /rollback <n>            restore the whole project to checkpoint n")
    lines.append("  /rollback <n> <file>     restore a single file from checkpoint n")
    lines.append("  /rollback diff <n>       preview what changed since checkpoint n")
    return "\n".join(lines)
