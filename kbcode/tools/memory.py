"""Long-term memory tools (the Hermes idea): remember/recall/save_skill."""

from __future__ import annotations

# Memory kinds (#8.4) — memory.py's `kind` column was always 'note' before;
# this is the small, fixed vocabulary the model and /memory-prune can rely on.
_MEMORY_KINDS = ("note", "decision", "preference", "bug", "todo")


class MemoryToolsMixin:
    def _tool_remember(self, inp: dict) -> str:
        """Save a memory row; an unrecognized `kind` is coerced to 'note' rather than rejected."""
        kind = inp.get("kind") or "note"
        if kind not in _MEMORY_KINDS:
            kind = "note"
        return self.memory.remember(inp["content"], kind=kind, key=inp.get("key"))

    def _tool_recall(self, inp: dict) -> str:
        """Search memory (FTS if available, else LIKE), optionally narrowed to one kind."""
        kind = inp.get("kind") or None
        rows = self.memory.recall(inp["query"], kind=kind)
        if not rows:
            return "(nothing relevant in memory)"
        return "\n".join(f"- [{r['kind']}] {r['content']}" for r in rows)

    def _tool_save_skill(self, inp: dict) -> str:
        """Record (or overwrite, by name) a reusable how-to."""
        return self.memory.save_skill(inp["name"], inp["description"], inp["steps"])
