"""Covers modes.py: frontmatter 'tools:' parsing (_parse_tools), the builtin
modes, and loading custom modes from .kbcode/modes/*.md — see kbcode/modes.py.
"""

from __future__ import annotations

from kbcode.modes import (
    EDIT,
    EXEC,
    NOTES,
    READ,
    Mode,
    _parse_tools,
    builtin_modes,
    load_custom_modes,
    load_modes,
)

# --- _parse_tools ------------------------------------------------------------


def test_empty_string_means_all_tools():
    assert _parse_tools("") is None


def test_all_keyword_means_all_tools():
    assert _parse_tools("all") is None


def test_star_means_all_tools():
    assert _parse_tools("*") is None


def test_all_keyword_is_case_insensitive():
    assert _parse_tools("ALL") is None


def test_read_only_aliases_all_map_to_read_group():
    for value in ("read-only", "readonly", "read"):
        assert _parse_tools(value) == frozenset(READ)


def test_group_name_expands_to_its_tool_set():
    assert _parse_tools("notes") == frozenset(NOTES)
    assert _parse_tools("edit") == frozenset(EDIT)
    assert _parse_tools("exec") == frozenset(EXEC)


def test_comma_separated_groups_are_unioned():
    assert _parse_tools("read, notes") == frozenset(READ | NOTES)


def test_comma_with_no_space_also_splits():
    assert _parse_tools("read,edit") == frozenset(READ | EDIT)


def test_value_is_lowercased_before_matching():
    assert _parse_tools("EDIT") == frozenset(EDIT)


def test_unknown_token_is_kept_as_an_explicit_tool_name():
    assert _parse_tools("some_custom_tool") == frozenset({"some_custom_tool"})


def test_mixed_group_and_explicit_tool_name():
    result = _parse_tools("read some_custom_tool")
    assert result == frozenset(READ | {"some_custom_tool"})


# --- Mode.allows -------------------------------------------------------------


def test_mode_with_none_tools_allows_anything():
    mode = Mode("code", "d", "i", None)
    assert mode.allows("run_command")
    assert mode.allows("anything_at_all")


def test_mode_with_tool_set_only_allows_listed_tools():
    mode = Mode("ask", "d", "i", frozenset(READ))
    assert mode.allows("read_file")
    assert not mode.allows("write_file")


# --- builtin modes -----------------------------------------------------------


def test_builtin_modes_contains_the_four_documented_modes():
    modes = builtin_modes()
    assert set(modes) == {"code", "architect", "ask", "debug"}


def test_code_and_debug_have_full_access():
    modes = builtin_modes()
    assert modes["code"].tools is None
    assert modes["debug"].tools is None


def test_ask_is_read_only():
    modes = builtin_modes()
    assert modes["ask"].tools == frozenset(READ)
    assert not modes["ask"].allows("write_file")
    assert not modes["ask"].allows("run_command")


def test_architect_is_read_only_plus_notes():
    modes = builtin_modes()
    assert modes["architect"].tools == frozenset(READ | NOTES)
    assert modes["architect"].allows("kb_write")
    assert not modes["architect"].allows("write_file")


# --- load_custom_modes --------------------------------------------------------


def test_missing_modes_dir_returns_empty(tmp_path):
    assert load_custom_modes(tmp_path / "does-not-exist") == {}


def test_custom_mode_parses_frontmatter_and_body(tmp_path):
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    (modes_dir / "docs-writer.md").write_text(
        "---\n"
        "description: Write docs only\n"
        "tools: read, notes\n"
        "---\n"
        "You are the docs writer. Improve README and kb/ notes.\n",
        encoding="utf-8",
    )
    modes = load_custom_modes(modes_dir)
    assert set(modes) == {"docs-writer"}
    mode = modes["docs-writer"]
    assert mode.name == "docs-writer"
    assert mode.description == "Write docs only"
    assert mode.tools == frozenset(READ | NOTES)
    assert "docs writer" in mode.instructions


def test_custom_mode_without_tools_key_defaults_to_all(tmp_path):
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    (modes_dir / "freeform.md").write_text(
        "---\ndescription: No tools key\n---\nBody text.\n", encoding="utf-8"
    )
    mode = load_custom_modes(modes_dir)["freeform"]
    assert mode.tools is None


def test_custom_mode_without_frontmatter_uses_defaults(tmp_path):
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    (modes_dir / "plain.md").write_text("Just a body, no frontmatter.\n", encoding="utf-8")
    mode = load_custom_modes(modes_dir)["plain"]
    assert mode.tools is None
    assert "custom mode (plain)" in mode.description
    assert mode.instructions == "Just a body, no frontmatter."


def test_unclosed_frontmatter_fence_does_not_crash(tmp_path):
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    (modes_dir / "broken.md").write_text("---\ndescription: no closing fence\nbody here", encoding="utf-8")
    modes = load_custom_modes(modes_dir)
    # falls back to treating the whole file as body since the second '---' never closes
    assert "broken" in modes
    assert modes["broken"].tools is None


def test_load_modes_merges_builtin_and_custom(tmp_path):
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    (modes_dir / "reviewer.md").write_text(
        "---\ndescription: Review only\ntools: read\n---\nReview code.\n", encoding="utf-8"
    )
    modes = load_modes(modes_dir)
    assert "code" in modes and "reviewer" in modes
    assert modes["reviewer"].tools == frozenset(READ)


def test_custom_mode_can_override_a_builtin_name(tmp_path):
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    (modes_dir / "ask.md").write_text(
        "---\ndescription: Custom ask override\ntools: all\n---\nOverridden.\n", encoding="utf-8"
    )
    modes = load_modes(modes_dir)
    assert modes["ask"].tools is None
    assert modes["ask"].description == "Custom ask override"
