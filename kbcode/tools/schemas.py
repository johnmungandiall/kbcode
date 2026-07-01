"""JSON schemas sent to the model for every built-in tool — kept as one data
module (not split per category) since keeping the full roster in one place
matters more here than the module split; the *implementations* live in
file.py/kb.py/memory.py/planning.py/subagent.py.
"""

from __future__ import annotations

from .memory import _MEMORY_KINDS

# A tool marked `"parallel_safe": True` is a pure read (no permission prompt, no
# file mutation, no checkpoint, no shared SQLite connection) and so is safe to
# run concurrently with other reads (#4.3). Declaring it *here*, next to the
# tool, is the source of truth — Agent derives its parallel set from this flag
# (via ToolsCore.parallel_safe_tools), so a new read-only tool opts in by adding
# the flag and can't silently fall back to sequential. The flag is metadata for
# kbcode only; providers strip it before the schema reaches the model API.

BASE_SCHEMAS: list[dict] = [
    {
        "name": "read_file",
        "parallel_safe": True,
        "description": "Read a text file from the project. Use this before editing a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative paths are anchored to the project root; absolute "
                        "paths are honored as given."
                    ),
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file with new content. Use for new files or full rewrites.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Where to create the file. A relative path (e.g. 'src/utils.py') "
                        "is anchored to the project root. An absolute path is honored "
                        "exactly as given, even outside the project — use one when the "
                        "user names a specific location."
                    ),
                },
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace an exact snippet in a file with new text. old_string must appear exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to the existing file. Relative paths are anchored to the "
                        "project root; absolute paths are honored as given."
                    ),
                },
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_dir",
        "parallel_safe": True,
        "description": "List files and folders in a directory (defaults to the project root).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory, relative to root. Optional."}},
        },
    },
    {
        "name": "search_code",
        "parallel_safe": True,
        "description": "Search the project for a regular expression. Returns matching path:line: text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "description": "Subdirectory to search. Optional."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "repo_map",
        "parallel_safe": True,
        "description": (
            "Get a structural map of the codebase showing the most important files, "
            "classes, functions and their signatures. Helps understand large projects "
            "cheaply without reading full files. Use before exploring with read_file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Optional subdirectory to map (defaults to whole project)."
                }
            },
        },
    },
    {
        "name": "web_search",
        "parallel_safe": True,
        "description": (
            "Search the web via DuckDuckGo (free, no API key). Returns up to "
            "20 results with title, url, and description. Use for current "
            "events, docs, or anything not in the project or your training data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "limit": {
                    "type": "integer",
                    "description": "Max results to return. Defaults to 5.",
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the project root. Use for tests, builds, git, installs. Needs user approval.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "kb_read",
        "parallel_safe": True,
        "description": "Read the whole knowledge base (kb/ notes). Do this first to understand the project cheaply.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_search",
        "parallel_safe": True,
        "description": (
            "Search the knowledge base for a keyword without reading every note "
            "(cheaper than kb_read once the KB has grown). Returns kb/<note>.md:line: text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "kb_write",
        "description": "Create or update a knowledge-base note (kb/<name>.md). Keep notes short; use path:line pointers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Note name, e.g. 'architecture'."},
                "content": {"type": "string"},
            },
            "required": ["name", "content"],
        },
    },
    {
        "name": "remember",
        "description": "Save a fact or decision to long-term memory so future sessions recall it. Call when you learn something durable.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "key": {"type": "string", "description": "Optional short label."},
                "kind": {
                    "type": "string",
                    "enum": list(_MEMORY_KINDS),
                    "description": "What kind of memory this is. Defaults to 'note'.",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "recall",
        "description": "Search long-term memory for relevant past facts before starting a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": list(_MEMORY_KINDS),
                    "description": "Optional: only recall memories of this kind.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "save_skill",
        "description": "Record a reusable how-to after finishing a non-trivial task, so you can repeat it later.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "steps": {"type": "string", "description": "The steps, as markdown."},
            },
            "required": ["name", "description", "steps"],
        },
    },
    {
        "name": "manage_todos",
        "description": (
            "Plan and track a multi-step task with a checklist. Pass the FULL list "
            "each call — it replaces the previous one. Keep exactly one item "
            "'in_progress', mark items 'done' as you finish, and add new ones as they "
            "come up. Use this for any job of 3+ steps so progress stays visible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The complete checklist, in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done"],
                            },
                        },
                        "required": ["task", "status"],
                    },
                }
            },
            "required": ["todos"],
        },
    },
]
