"""The task-checklist tool (the Kilo Code idea): manage_todos."""

from __future__ import annotations

_TODO_MARKS = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}


def format_todos(todos: list[dict]) -> str:
    """Render a todo checklist as plain text (for tool results and /todo)."""
    if not todos:
        return "(no todos yet)"
    return "\n".join(f"{_TODO_MARKS.get(t['status'], '[ ]')} {t['task']}" for t in todos)


class PlanningToolsMixin:
    def _tool_manage_todos(self, inp: dict) -> str:
        """Replace the current task checklist wholesale with the given list."""
        cleaned: list[dict] = []
        for item in inp.get("todos") or []:
            task = str(item.get("task", "")).strip()
            if not task:
                continue
            status = str(item.get("status", "pending")).strip().lower()
            if status not in _TODO_MARKS:
                status = "pending"
            cleaned.append({"task": task, "status": status})
        self.todos = cleaned
        return "Updated checklist:\n" + format_todos(cleaned)
