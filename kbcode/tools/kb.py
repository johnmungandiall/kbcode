"""Knowledge-base tools (the claude-kb idea): kb_read/kb_search/kb_write."""

from __future__ import annotations


class KBToolsMixin:
    def _tool_kb_read(self, _inp: dict) -> str:
        """Return every kb/ note, concatenated (cached — see KnowledgeBase.read_all)."""
        return self.kb.read_all() or "(knowledge base is empty)"

    def _tool_kb_search(self, inp: dict) -> str:
        """Grep the kb/ notes for a keyword, without loading all of them."""
        hits = self.kb.search(inp["query"])
        return "\n".join(hits) or "(no matches)"

    def _tool_kb_write(self, inp: dict) -> str:
        """Create/update a kb/ note; an actual content change asks permission and shows a diff first."""
        name, content = inp["name"], inp["content"]
        existing = self.kb.read_note(name)
        # Only an actual overwrite of different content needs a look — a brand
        # new note, or rewriting it with the same text, is a routine no-risk
        # write (the kb reminder hook nudges this every turn; gating that too
        # would make the "cheap notes" workflow annoying).
        if existing is not None and existing != content:
            diff = self._unified_diff(existing, content, f"kb/{name} (current)", f"kb/{name} (new)")
            if not self.perm.check("kb_write", f"overwrite kb/{name}:\n{diff}"):
                raise PermissionError("User denied permission to overwrite the kb note.")
        result = self.kb.write_note(name, content)

        # Check this note's own path:line pointers right away, instead of
        # waiting for the agent's end-of-turn drift check — catches a typo'd
        # pointer immediately, while it's cheap to fix in the same turn.
        safe_name = self.kb._safe(name)
        problems = [p for p in self.kb.check_pointers(self.root) if p.startswith(f"kb/{safe_name}: ")]
        if problems:
            detail = "\n".join(f"- {p}" for p in problems)
            result += f"\n\n[pointer check] this note has unresolved path:line pointer(s):\n{detail}"
        return result
