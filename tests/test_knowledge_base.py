from kbcode.knowledge_base import KnowledgeBase


def test_scaffold_creates_starter_notes(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.scaffold()
    notes = kb.list_notes()
    assert "overview.md" in notes
    assert "architecture.md" in notes
    assert "about-you.md" in notes


def test_scaffold_is_noop_if_notes_already_exist(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("custom.md", "# custom\nmine")
    kb.scaffold()
    assert kb.list_notes() == ["custom.md"]


def test_is_scaffold_true_for_empty_or_untouched_templates(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    assert kb.is_scaffold()  # no notes yet
    kb.scaffold()
    assert kb.is_scaffold()  # untouched starter templates


def test_is_scaffold_false_once_a_note_is_customized(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.scaffold()
    kb.write_note("overview", "# Overview\nA real project, indexed.")
    assert not kb.is_scaffold()


def test_is_scaffold_false_for_extra_non_template_note(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.scaffold()
    kb.write_note("features", "# Features\n- real content")
    assert not kb.is_scaffold()


def test_write_and_read_note_round_trip(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("gotchas", "# Gotchas\n- watch out")
    assert kb.read_note("gotchas") == "# Gotchas\n- watch out"
    assert kb.read_note("missing") is None


def test_read_all_concatenates_notes(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("a.md", "note A")
    kb.write_note("b.md", "note B")
    joined = kb.read_all()
    assert "### kb/a.md" in joined
    assert "note A" in joined
    assert "### kb/b.md" in joined
    assert "note B" in joined


def test_read_all_truncates_when_over_limit(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("big.md", "x" * 1000)
    joined = kb.read_all(max_chars=100)
    assert len(joined) < 1000
    assert "[...knowledge base truncated...]" in joined


def test_search_finds_matching_lines_case_insensitively(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("architecture.md", "The Widget lives in main.py.\nOther line.")
    kb.write_note("gotchas.md", "Nothing about that here.")
    hits = kb.search("widget")
    assert len(hits) == 1
    assert hits[0] == "kb/architecture.md:1: The Widget lives in main.py."


def test_search_empty_query_returns_nothing(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("a.md", "anything")
    assert kb.search("") == []
    assert kb.search("   ") == []


def test_search_respects_max_results(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("a.md", "\n".join(f"needle {i}" for i in range(10)))
    assert len(kb.search("needle", max_results=3)) == 3


def test_read_all_caches_between_calls(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("a.md", "first version")
    first = kb.read_all()
    # a direct filesystem edit, bypassing write_note(), should NOT be picked
    # up until the cache is invalidated — that's the documented trade-off.
    (tmp_path / "kb" / "a.md").write_text("changed on disk directly", encoding="utf-8")
    assert kb.read_all() == first


def test_write_note_invalidates_the_cache(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("a.md", "first version")
    kb.read_all()  # populate the cache
    kb.write_note("a.md", "second version")
    assert "second version" in kb.read_all()
    assert "first version" not in kb.read_all()


def test_check_pointers_flags_missing_file(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("notes.md", "See `nope.py:10` for details.")
    problems = kb.check_pointers(project)
    assert len(problems) == 1
    assert "file not found" in problems[0]


def test_check_pointers_flags_stale_line_number(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "mod.py"
    target.write_text("line1\nline2\nline3\n")
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("notes.md", "See `mod.py:50` for details.")
    problems = kb.check_pointers(project)
    assert len(problems) == 1
    assert "stale" in problems[0]


def test_check_pointers_passes_for_valid_pointer(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "mod.py"
    target.write_text("line1\nline2\nline3\n")
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("notes.md", "See `mod.py:2` for details.")
    assert kb.check_pointers(project) == []


def test_check_pointers_skips_placeholder_examples(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    kb = KnowledgeBase(tmp_path / "kb")
    kb.scaffold()  # templates reference path/to/main etc.
    assert kb.check_pointers(project) == []


def test_fix_pointers_relocates_by_unique_definition(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "mod.py"
    # `def widget` moved from line 1 (where the note claims) to line 5
    target.write_text("\n\n\n\ndef widget():\n    pass\n")
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("notes.md", "The widget() function lives at `mod.py:1`.")

    fixed, unresolved = kb.fix_pointers(project)
    assert unresolved == []
    assert len(fixed) == 1
    assert kb.read_note("notes.md") == "The widget() function lives at `mod.py:5`."


def test_fix_pointers_reports_unresolved_for_missing_file(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    kb = KnowledgeBase(tmp_path / "kb")
    kb.write_note("notes.md", "See `gone.py:1`.")
    fixed, unresolved = kb.fix_pointers(project)
    assert fixed == []
    assert len(unresolved) == 1
    assert "file not found" in unresolved[0]
