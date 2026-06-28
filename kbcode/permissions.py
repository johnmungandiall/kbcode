"""Permission gating for risky actions (the Claude Code idea).

Before the agent writes files or runs commands, we ask the user. The user
can allow once, deny, or allow that tool for the rest of the session.
"""

from __future__ import annotations


class Permissions:
    def __init__(self, auto_approve: bool = False):
        self.auto_approve = auto_approve
        self.always_allow: set[str] = set()

    def check(self, tool: str, detail: str) -> bool:
        if self.auto_approve or tool in self.always_allow:
            return True
        print()
        print(f"  ┌─ permission needed: {tool}")
        for line in detail.splitlines() or [detail]:
            print(f"  │ {line}")
        print("  └─ allow? [y]es / [N]o / [a]lways for this session")
        try:
            answer = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer in ("a", "always"):
            self.always_allow.add(tool)
            return True
        return answer in ("y", "yes")
