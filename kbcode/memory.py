"""Persistent memory + learned skills (the "Hermes" idea).

A tiny SQLite store that survives across sessions. The agent can:
  - remember(...)  : jot down a fact/decision for later
  - recall(query)  : full-text search past memories
  - save_skill(...) : record a reusable how-to it figured out

Full-text search uses SQLite FTS5 when available, and falls back to a
simple LIKE search otherwise, so it works on any Python build.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path


class Memory:
    """Thread-safe: parallel tool batches and concurrent subagents (#4.3) can
    hit ``recall`` from pool threads, so the single connection is opened with
    ``check_same_thread=False`` and every operation serializes behind one
    lock — SQLite itself allows this as long as calls don't interleave."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.fts = False
        self._init_db()

    def _init_db(self) -> None:
        c = self.conn
        c.execute(
            """CREATE TABLE IF NOT EXISTS memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL DEFAULT 'note',
                key TEXT,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS skills(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                steps TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        try:
            c.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts "
                "USING fts5(content, content='memories', content_rowid='id')"
            )
            c.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                  INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                  INSERT INTO memories_fts(memories_fts, rowid, content)
                  VALUES('delete', old.id, old.content);
                END;
                """
            )
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False  # FTS5 not compiled in; LIKE fallback is used.
        c.commit()

    # --- memories ------------------------------------------------------
    def remember(self, content: str, kind: str = "note", key: str | None = None) -> str:
        with self._lock:
            self.conn.execute(
                "INSERT INTO memories(kind, key, content, created_at) VALUES (?, ?, ?, ?)",
                (kind, key, content, time.time()),
            )
            self.conn.commit()
        return "remembered"

    def recall(self, query: str, limit: int = 5, kind: str | None = None) -> list[dict]:
        """Search memory, optionally narrowed to one `kind` (decision,
        preference, bug, todo, note — #8.4)."""
        rows: list[sqlite3.Row] = []
        with self._lock:
            if self.fts and query.strip():
                sql = (
                    "SELECT m.kind, m.key, m.content FROM memories_fts f "
                    "JOIN memories m ON m.id = f.rowid WHERE memories_fts MATCH ?"
                )
                params: list = [self._fts_query(query)]
                if kind:
                    sql += " AND m.kind = ?"
                    params.append(kind)
                sql += " ORDER BY rank LIMIT ?"
                params.append(limit)
                try:
                    rows = self.conn.execute(sql, params).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:
                sql = "SELECT kind, key, content FROM memories WHERE content LIKE ?"
                params = [f"%{query}%"]
                if kind:
                    sql += " AND kind = ?"
                    params.append(kind)
                sql += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)
                rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def recent(self, limit: int = 8, kind: str | None = None) -> list[dict]:
        with self._lock:
            if kind:
                rows = self.conn.execute(
                    "SELECT kind, key, content FROM memories WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
                    (kind, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT kind, key, content FROM memories ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def prune(self, older_than_days: float | None = None) -> dict:
        """Remove duplicate memories (#8.3) — the table otherwise grows
        forever. Keeps the newest row for each exact-duplicate content, and
        optionally ages out anything older than ``older_than_days``. Returns
        how many rows each pass removed.
        """
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM memories WHERE id NOT IN (SELECT MAX(id) FROM memories GROUP BY content)"
            )
            duplicates_removed = cur.rowcount
            aged_removed = 0
            if older_than_days is not None:
                cutoff = time.time() - older_than_days * 86400
                cur = self.conn.execute("DELETE FROM memories WHERE created_at < ?", (cutoff,))
                aged_removed = cur.rowcount
            self.conn.commit()
        return {"duplicates_removed": duplicates_removed, "aged_removed": aged_removed}

    @staticmethod
    def _fts_query(query: str) -> str:
        terms = re.findall(r"\w+", query)
        return " OR ".join(terms) if terms else query

    # --- skills --------------------------------------------------------
    def save_skill(self, name: str, description: str, steps: str) -> str:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO skills(name, description, steps, created_at) "
                "VALUES (?, ?, ?, ?)",
                (name, description, steps, time.time()),
            )
            self.conn.commit()
        return "skill saved"

    def list_skills(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT name, description FROM skills ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_skill(self, name: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT name, description, steps FROM skills WHERE name = ?", (name,)
            ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        with self._lock:
            self.conn.close()
