"""Covers subagents.py: loading .kbcode/agents/*.md frontmatter into Subagent
objects. Shares its frontmatter parsing with modes.py's load_custom_modes (both
use modes._parse_tools) — the one deliberate difference is the *default*
when 'tools:' is omitted: modes default to "all", subagents default to
"read" (safer for delegated work, see subagents.py's module docstring). These
tests exist to catch that default silently drifting or the two loaders
diverging in some other way.
"""

from __future__ import annotations

from kbcode.modes import NOTES, READ
from kbcode.subagents import Subagent, load_subagents


def test_missing_agents_dir_returns_empty(tmp_path):
    assert load_subagents(tmp_path / "does-not-exist") == {}


def test_subagent_parses_frontmatter_and_body(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "code-explorer.md").write_text(
        "---\n"
        "description: Explore the codebase and report the key files.\n"
        "tools: read_file, search_code\n"
        "---\n"
        "You are a code explorer. Trace the feature, then summarize.\n",
        encoding="utf-8",
    )
    agents = load_subagents(agents_dir)
    assert set(agents) == {"code-explorer"}
    agent = agents["code-explorer"]
    assert agent.name == "code-explorer"
    assert agent.description == "Explore the codebase and report the key files."
    assert agent.tools == frozenset({"read_file", "search_code"})
    assert "code explorer" in agent.instructions


def test_tools_omitted_defaults_to_read_only_not_all(tmp_path):
    # the key divergence from modes.load_custom_modes, which defaults to "all".
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "no-tools-key.md").write_text(
        "---\ndescription: No tools key given\n---\nDo the job.\n", encoding="utf-8"
    )
    agent = load_subagents(agents_dir)["no-tools-key"]
    assert agent.tools == frozenset(READ)


def test_tools_group_names_resolve_same_as_modes(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "notes-writer.md").write_text(
        "---\ndescription: writes notes\ntools: read, notes\n---\nWrite notes.\n", encoding="utf-8"
    )
    agent = load_subagents(agents_dir)["notes-writer"]
    assert agent.tools == frozenset(READ | NOTES)


def test_tools_all_means_every_tool(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "full-access.md").write_text(
        "---\ndescription: full access\ntools: all\n---\nDo anything needed.\n", encoding="utf-8"
    )
    agent = load_subagents(agents_dir)["full-access"]
    assert agent.tools is None


def test_subagent_without_frontmatter_uses_defaults(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "plain.md").write_text("Just a body, no frontmatter.\n", encoding="utf-8")
    agent = load_subagents(agents_dir)["plain"]
    assert agent.tools == frozenset(READ)
    assert "subagent (plain)" in agent.description
    assert agent.instructions == "Just a body, no frontmatter."


def test_malformed_file_does_not_crash_the_loader(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "broken.md").write_text("---\ndescription: no closing fence\nbody here", encoding="utf-8")
    agents = load_subagents(agents_dir)
    assert "broken" in agents
    assert agents["broken"].tools == frozenset(READ)


def test_multiple_agent_files_all_load(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "a.md").write_text("---\ndescription: A\n---\nBody A.\n", encoding="utf-8")
    (agents_dir / "b.md").write_text("---\ndescription: B\n---\nBody B.\n", encoding="utf-8")
    agents = load_subagents(agents_dir)
    assert set(agents) == {"a", "b"}


# --- Subagent.allows ---------------------------------------------------


def test_subagent_with_none_tools_allows_anything():
    agent = Subagent("full", "d", "i", None)
    assert agent.allows("run_command")


def test_subagent_with_tool_set_restricts_to_listed_tools():
    agent = Subagent("explorer", "d", "i", frozenset({"read_file"}))
    assert agent.allows("read_file")
    assert not agent.allows("write_file")
