"""Covers IMPROVEMENTS.md #8.3 (memory pruning) and #8.4 (memory kind filter)."""

from __future__ import annotations

import time

from kbcode.memory import Memory


def _make_memory(tmp_path) -> Memory:
    return Memory(tmp_path / "memory.db")


def test_remember_defaults_to_note_kind(tmp_path):
    mem = _make_memory(tmp_path)
    mem.remember("plain fact")
    assert mem.recent()[0]["kind"] == "note"


def test_remember_stores_a_custom_kind(tmp_path):
    mem = _make_memory(tmp_path)
    mem.remember("always use tabs", kind="preference")
    assert mem.recent()[0]["kind"] == "preference"


def test_recall_filters_by_kind(tmp_path):
    mem = _make_memory(tmp_path)
    mem.remember("fixed the login bug", kind="bug")
    mem.remember("decided on the SQLite approach", kind="decision")

    bugs = mem.recall("the", kind="bug")
    assert len(bugs) == 1
    assert bugs[0]["kind"] == "bug"

    decisions = mem.recall("the", kind="decision")
    assert len(decisions) == 1
    assert decisions[0]["kind"] == "decision"


def test_recall_without_kind_returns_all_matches(tmp_path):
    mem = _make_memory(tmp_path)
    mem.remember("uses widgets everywhere", kind="note")
    mem.remember("widgets should be blue", kind="preference")
    assert len(mem.recall("widgets")) == 2


def test_recent_filters_by_kind(tmp_path):
    mem = _make_memory(tmp_path)
    mem.remember("a todo item", kind="todo")
    mem.remember("a note item", kind="note")
    todos = mem.recent(kind="todo")
    assert len(todos) == 1
    assert todos[0]["content"] == "a todo item"


# --- prune ---------------------------------------------------------------


def test_prune_removes_exact_duplicates_keeping_newest(tmp_path):
    mem = _make_memory(tmp_path)
    mem.remember("same fact")
    mem.remember("same fact")
    mem.remember("different fact")

    result = mem.prune()
    assert result["duplicates_removed"] == 1
    remaining = [r["content"] for r in mem.recent(limit=100)]
    assert remaining.count("same fact") == 1
    assert "different fact" in remaining


def test_prune_ages_out_old_memories(tmp_path):
    mem = _make_memory(tmp_path)
    mem.conn.execute(
        "INSERT INTO memories(kind, key, content, created_at) VALUES (?, ?, ?, ?)",
        ("note", None, "an old memory", time.time() - 100 * 86400),
    )
    mem.conn.commit()
    mem.remember("a fresh memory")

    result = mem.prune(older_than_days=30)
    assert result["aged_removed"] == 1
    remaining = [r["content"] for r in mem.recent(limit=100)]
    assert "an old memory" not in remaining
    assert "a fresh memory" in remaining


def test_prune_with_no_duplicates_or_old_memories_is_a_noop(tmp_path):
    mem = _make_memory(tmp_path)
    mem.remember("only entry")
    result = mem.prune()
    assert result == {"duplicates_removed": 0, "aged_removed": 0}
