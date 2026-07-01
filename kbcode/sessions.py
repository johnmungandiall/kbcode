"""Session history — persist and resume chats (the Claude Code idea), rolled up
into cross-session usage stats (the Hermes idea).

Every chat is a JSON-lines file at ``.kbcode/sessions/<id>.jsonl`` — per
project, like memory.db and checkpoints, rather than Claude Code's global
``~/.claude/projects/``. Each line is one record, appended in real time as the
conversation happens (not written once at the end), so a crash or a killed
process loses at most the in-flight message:

  {"type": "meta", "id", "started_at", "provider", "model", "mode",
   "project_dir", "git_branch"}       -- once, at session creation
  {"type": "message", ...normalized message...}   -- one per turn/message
  {"type": "usage", "at", "usage": {...}}         -- after every turn
  {"type": "reset", "at"}                          -- on /reset: everything
                                                       before this is history,
                                                       not part of "this chat"

A resume (``--continue`` / ``--resume`` / ``/resume``) re-opens the same file
and keeps appending, so "continuing a session" is literally one growing
transcript rather than a new file chained to the old one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .pricing import estimate_cost

_ID_RE_LEN = 6  # hex chars of randomness appended to the timestamp


def new_session_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:_ID_RE_LEN]


def _git_branch(project_dir: Path) -> str | None:
    """Best-effort current branch of the user's real repo (not the checkpoint
    shadow one). Never raises; returns None if git/the repo isn't available."""
    if not shutil.which("git"):
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    branch = proc.stdout.strip()
    return branch if proc.returncode == 0 and branch and branch != "HEAD" else None


def _jsonable(value):
    """Recursively reduce a value to something json.dumps can write.

    Handles the two shapes that show up in Agent.messages that aren't already
    plain data: ``ToolCall`` dataclasses, and (for the Anthropic provider) the
    SDK's pydantic content-block objects stored in the "raw" replay field.
    Never raises — anything unrecognized falls back to str().
    """
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    model_dump = getattr(value, "model_dump", None)  # pydantic v2 (Anthropic SDK)
    if callable(model_dump):
        try:
            return _jsonable(model_dump(mode="json"))
        except Exception:  # noqa: BLE001 - fall through to other strategies
            pass
    as_dict = getattr(value, "dict", None)  # pydantic v1 fallback
    if callable(as_dict):
        try:
            return _jsonable(as_dict())
        except Exception:  # noqa: BLE001
            pass
    return str(value)


class SessionRecorder:
    """Owns one session's transcript file for the life of an Agent."""

    def __init__(
        self,
        sessions_dir: Path,
        project_dir: Path,
        provider: str,
        model: str,
        mode: str,
        *,
        resume_id: str | None = None,
    ):
        self.id = resume_id or new_session_id()
        self.path = sessions_dir / f"{self.id}.jsonl"
        self._enabled = True
        try:
            sessions_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._enabled = False
            return
        if resume_id is None:  # brand-new session -> write the header once
            self._write({
                "type": "meta",
                "id": self.id,
                "started_at": time.time(),
                "provider": provider,
                "model": model,
                "mode": mode,
                "project_dir": str(project_dir),
                "git_branch": _git_branch(project_dir),
            })

    def _write(self, record: dict) -> None:
        if not self._enabled:
            return
        try:
            line = json.dumps(_jsonable(record), ensure_ascii=False, default=str)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            self._enabled = False  # disk problem — stop trying, never crash the chat

    def append(self, message: dict) -> None:
        self._write({"type": "message", **message})

    def record_usage(self, usage: dict) -> None:
        self._write({"type": "usage", "at": time.time(), "usage": usage})

    def reset_marker(self) -> None:
        self._write({"type": "reset", "at": time.time()})


def _summarize(path: Path) -> dict | None:
    """One row for /sessions and the resume picker. Only reflects what
    happened after the last /reset in the file (a reset marker clears the
    running title/turn count, same as Agent.reset() clears self.messages)."""
    meta: dict | None = None
    title = ""
    turns = 0
    usage: dict | None = None
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = rec.get("type")
                if kind == "meta":
                    meta = rec
                elif kind == "reset":
                    title, turns = "", 0
                elif kind == "message":
                    if rec.get("role") == "user":
                        turns += 1
                        if not title:
                            title = " ".join(str(rec.get("content") or "").split())[:60]
                elif kind == "usage":
                    usage = rec.get("usage")
    except OSError:
        return None
    if meta is None:
        return None
    return {
        "id": meta.get("id", path.stem),
        "path": path,
        "started_at": meta.get("started_at", 0),
        "provider": meta.get("provider"),
        "model": meta.get("model"),
        "mode": meta.get("mode"),
        "git_branch": meta.get("git_branch"),
        "title": title,
        "turns": turns,
        "usage": usage,
    }


def list_sessions(sessions_dir: Path, limit: int = 50) -> list[dict]:
    """Most-recent-first session summaries for this project."""
    if not sessions_dir.exists():
        return []
    rows = [s for s in (_summarize(p) for p in sessions_dir.glob("*.jsonl")) if s]
    rows.sort(key=lambda r: r["started_at"], reverse=True)
    return rows[:limit]


def _first_match(path: Path, needle: str) -> str | None:
    """The first user/assistant message text containing ``needle``
    (case-insensitive), collapsed to one short line — or None."""
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "message":
                    continue
                text = rec.get("content") if rec.get("role") == "user" else rec.get("text")
                if not text:
                    continue
                text = str(text)
                if needle in text.lower():
                    snippet = " ".join(text.split())
                    return snippet[:100] + ("…" if len(snippet) > 100 else "")
    except OSError:
        return None
    return None


def search_sessions(sessions_dir: Path, query: str, limit: int = 20) -> list[dict]:
    """Full-text search across this project's saved session transcripts
    (#8.1) — find "that conversation about the auth bug" without listing
    every session first. Returns session summary rows (like list_sessions)
    plus a ``snippet`` of the first matching line, most-recent-first.
    """
    needle = query.strip().lower()
    if not needle or not sessions_dir.exists():
        return []
    hits: list[dict] = []
    for path in sessions_dir.glob("*.jsonl"):
        snippet = _first_match(path, needle)
        if snippet is None:
            continue
        summary = _summarize(path)
        if summary is None:
            continue
        row = dict(summary)
        row["snippet"] = snippet
        hits.append(row)
    hits.sort(key=lambda r: r["started_at"], reverse=True)
    return hits[:limit]


def load_session(path: Path) -> tuple[dict, list[dict]]:
    """Rebuild (meta, messages) from a transcript for resuming.

    Only messages after the last /reset marker are returned, matching what
    the picker's turn count/title describe. Assistant ``tool_calls`` are
    reconstructed into ``ToolCall`` instances (not left as plain dicts) since
    compaction._render() reads them by attribute (tc.name / tc.input).
    """
    from .provider import ToolCall  # local import: avoid a hard provider<->sessions coupling

    meta: dict = {}
    messages: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = rec.get("type")
            if kind == "meta":
                meta = {k: v for k, v in rec.items() if k != "type"}
            elif kind == "reset":
                messages = []
            elif kind == "message":
                msg = {k: v for k, v in rec.items() if k != "type"}
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    msg["tool_calls"] = [ToolCall(**tc) for tc in msg["tool_calls"]]
                messages.append(msg)
    return meta, messages


def _fmt_args(args: dict, limit: int = 200) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(args)
    return text if len(text) <= limit else text[:limit] + "…"


def export_markdown(path: Path) -> str:
    """Render a saved session transcript as readable markdown (#8.2) — for
    sharing or documentation, since the raw .jsonl isn't meant for humans.
    """
    meta, messages = load_session(path)
    lines: list[str] = [f"# kbcode session {meta.get('id', path.stem)}", ""]
    started = meta.get("started_at")
    if started:
        lines.append(f"- started: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(started))}")
    if meta.get("provider"):
        lines.append(f"- provider/model: {meta['provider']} / {meta.get('model', '?')}")
    if meta.get("git_branch"):
        lines.append(f"- git branch: {meta['git_branch']}")
    lines.append("")

    for m in messages:
        role = m.get("role")
        if role == "user":
            content = str(m.get("content") or "")
            if m.get("images"):
                content += f"\n\n*(with {len(m['images'])} image(s) attached)*"
            lines.append(f"## User\n\n{content}\n")
        elif role == "assistant":
            text = (m.get("text") or "").strip()
            if text:
                lines.append(f"## Assistant\n\n{text}\n")
            for tc in m.get("tool_calls") or []:
                lines.append(f"> called `{tc.name}({_fmt_args(tc.input)})`\n")
        elif role == "tool_results":
            for r in m.get("results") or []:
                tag = "error" if r.get("is_error") else "ok"
                body = str(r.get("content") or "")
                lines.append(f"```\n[tool result: {tag}]\n{body}\n```\n")
    return "\n".join(lines)


def lifetime_stats(sessions_dir: Path) -> dict:
    """Roll every saved session's last-known usage into an all-time total —
    Hermes' insights-across-sessions idea, without needing a database: each
    session's own recorded model prices its own tokens, so mixed-provider
    projects still get one honest total."""
    rows = list_sessions(sessions_dir, limit=10_000)
    input_tokens = sum((r["usage"] or {}).get("input_tokens", 0) for r in rows)
    output_tokens = sum((r["usage"] or {}).get("output_tokens", 0) for r in rows)
    cost = 0.0
    known_cost = False
    for r in rows:
        u = r["usage"] or {}
        c = estimate_cost(r.get("model") or "", u.get("input_tokens", 0), u.get("output_tokens", 0))
        if c is not None:
            cost += c
            known_cost = True
    return {
        "sessions": len(rows),
        "turns": sum(r["turns"] for r in rows),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost": cost if known_cost else None,
    }
