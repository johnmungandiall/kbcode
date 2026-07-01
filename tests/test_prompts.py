"""Covers IMPROVEMENTS.md #9.3: .kbcode/prompts/*.md fragments should be
appended to the system prompt in sorted order.
"""

from __future__ import annotations

from kbcode.prompts import build_system_prompt, load_prompt_fragments


def test_load_prompt_fragments_missing_dir_returns_empty(tmp_path):
    assert load_prompt_fragments(tmp_path / "does-not-exist") == ""


def test_load_prompt_fragments_empty_dir_returns_empty(tmp_path):
    d = tmp_path / "prompts"
    d.mkdir()
    assert load_prompt_fragments(d) == ""


def test_load_prompt_fragments_concatenates_in_sorted_order(tmp_path):
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "20-testing.md").write_text("always run tests", encoding="utf-8")
    (d / "10-style.md").write_text("use tabs", encoding="utf-8")
    result = load_prompt_fragments(d)
    assert result.index("use tabs") < result.index("always run tests")


def test_load_prompt_fragments_skips_blank_files(tmp_path):
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "a.md").write_text("real content", encoding="utf-8")
    (d / "b.md").write_text("   \n  ", encoding="utf-8")
    assert load_prompt_fragments(d) == "real content"


def test_build_system_prompt_includes_extra_prompts_section():
    system = build_system_prompt(
        kb_text="", skills=[], memories=[], extra_prompts="always be terse"
    )
    assert "## Additional instructions" in system
    assert "always be terse" in system


def test_build_system_prompt_omits_section_when_no_extra_prompts():
    system = build_system_prompt(kb_text="", skills=[], memories=[], extra_prompts="")
    assert "## Additional instructions" not in system
