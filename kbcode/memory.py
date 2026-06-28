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
import time
from pathlib import Path


class Memory:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
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
        self.conn.execute(
            "INSERT INTO memories(kind, key, content, created_at) VALUES (?, ?, ?, ?)",
            (kind, key, content, time.time()),
        )
        self.conn.commit()
        return "remembered"

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        rows: list[sqlite3.Row] = []
        if self.fts and query.strip():
            try:
                rows = self.conn.execute(
                    "SELECT m.kind, m.key, m.content FROM memories_fts f "
                    "JOIN memories m ON m.id = f.rowid "
                    "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                    (self._fts_query(query), limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            rows = self.conn.execute(
                "SELECT kind, key, content FROM memories "
                "WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def recent(self, limit: int = 8) -> list[dict]:
        rows = self.conn.execute(
            "SELECT kind, key, content FROM memories ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _fts_query(query: str) -> str:
        terms = re.findall(r"\w+", query)
        return " OR ".join(terms) if terms else query

    # --- skills --------------------------------------------------------
    def save_skill(self, name: str, description: str, steps: str) -> str:
        self.conn.execute(
            "INSERT OR REPLACE INTO skills(name, description, steps, created_at) "
            "VALUES (?, ?, ?, ?)",
            (name, description, steps, time.time()),
        )
        self.conn.commit()
        return "skill saved"

    def list_skills(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name, description FROM skills ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_skill(self, name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT name, description, steps FROM skills WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self.conn.close()
