"""The agent's tools — the "hands" (Claude Code idea), plus tools that wire
in memory (Hermes) and the knowledge base (claude-kb).

Each tool has a JSON schema (so Claude knows how to call it) and a Python
method named ``_tool_<name>`` that runs it. ``execute`` returns
``(content, is_error)`` so the agent can feed results back to the model.

Split into one module per tool category (#2.2) — file.py, kb.py, memory.py,
planning.py, subagent.py — composed here into one ``Tools`` facade so callers
keep using ``from kbcode.tools import Tools`` unchanged; core.py holds the
schema/dispatch machinery and helpers shared across categories.
"""

from __future__ import annotations

from .core import ToolsCore
from .file import FileToolsMixin
from .kb import KBToolsMixin
from .memory import MemoryToolsMixin
from .planning import PlanningToolsMixin, format_todos
from .subagent import SubagentToolsMixin

__all__ = ["Tools", "format_todos"]


class Tools(
    FileToolsMixin,
    KBToolsMixin,
    MemoryToolsMixin,
    PlanningToolsMixin,
    SubagentToolsMixin,
    ToolsCore,
):
    """Composes every tool category behind one class; see module docstring."""
