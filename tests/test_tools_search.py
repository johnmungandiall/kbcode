"""Covers IMPROVEMENTS.md #10.3: search_code should use ripgrep when it's on
PATH, and fall back to the original os.walk scan otherwise — deterministically
tested here via monkeypatching, since the CI runners may not have `rg` installed.
"""

from __future__ import annotations

import subprocess

from kbcode.config import Config
from kbcode.knowledge_base import KnowledgeBase
from kbcode.memory import Memory
from kbcode.permissions import Permissions
from kbcode.tools import Tools


def _make_tools(tmp_path) -> Tools:
    project = tmp_path / "project"
    project.mkdir()
    config = Config(project_dir=project)
    config.ensure_dirs()
    memory = Memory(config.memory_db)
    kb = KnowledgeBase(config.kb_dir)
    perm = Permissions(auto_approve=True)
    return Tools(config, memory, kb, perm)


def test_rg_candidate_files_returns_none_when_rg_missing(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    monkeypatch.setattr(tools, "_ripgrep_available", lambda: False)
    assert tools._rg_candidate_files("pattern", tools.root) is None


def test_rg_candidate_files_parses_stdout_and_filters_skip_dirs(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    monkeypatch.setattr(tools, "_ripgrep_available", lambda: True)
    good = tools.root / "a.py"
    skipped = tools.root / "node_modules" / "b.js"

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{good}\n{skipped}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    files = tools._rg_candidate_files("pattern", tools.root)
    assert files == [good]


def test_rg_candidate_files_falls_back_on_rg_error_exit_code(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    monkeypatch.setattr(tools, "_ripgrep_available", lambda: True)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="regex parse error")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert tools._rg_candidate_files("(bad(regex", tools.root) is None


def test_rg_candidate_files_falls_back_on_exception(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    monkeypatch.setattr(tools, "_ripgrep_available", lambda: True)

    def fake_run(cmd, **kwargs):
        raise OSError("rg vanished")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert tools._rg_candidate_files("pattern", tools.root) is None


def test_search_code_without_rg_uses_full_walk(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    monkeypatch.setattr(tools, "_ripgrep_available", lambda: False)
    (tools.root / "hit.py").write_text("needle here\n", encoding="utf-8")
    out = tools._tool_search_code({"pattern": "needle"})
    assert "hit.py:1: needle here" in out


def test_search_code_uses_rg_candidate_list_when_available(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    hit_file = tools.root / "hit.py"
    hit_file.write_text("needle here\n", encoding="utf-8")
    # a file that matches the pattern but is NOT in rg's candidate list —
    # if search_code is really using the candidate list, this must be skipped.
    (tools.root / "not_scanned.py").write_text("needle here too\n", encoding="utf-8")

    monkeypatch.setattr(tools, "_ripgrep_available", lambda: True)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{hit_file}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = tools._tool_search_code({"pattern": "needle"})
    assert "hit.py:1: needle here" in out
    assert "not_scanned.py" not in out


def test_search_code_no_matches(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    monkeypatch.setattr(tools, "_ripgrep_available", lambda: False)
    out = tools._tool_search_code({"pattern": "nonexistent-pattern-xyz"})
    assert out == "(no matches)"


def test_fallback_walk_skips_gitignored_top_level_dirs(tmp_path, monkeypatch):
    """The Python fallback walk must honor the project .gitignore's plain
    directory entries (e.g. a huge vendored `references/` tree) the way the
    ripgrep pre-filter does — crawling it made one search run for minutes."""
    tools = _make_tools(tmp_path)
    monkeypatch.setattr(tools, "_ripgrep_available", lambda: False)
    (tools.root / ".gitignore").write_text("# vendored\nreferences/\n*.pyc\n", encoding="utf-8")
    vendored = tools.root / "references" / "big-repo"
    vendored.mkdir(parents=True)
    (vendored / "clone.py").write_text("needle in a clone\n", encoding="utf-8")
    (tools.root / "mine.py").write_text("needle in my code\n", encoding="utf-8")

    out = tools._tool_search_code({"pattern": "needle"})

    assert "mine.py:1: needle in my code" in out
    assert "clone.py" not in out


def test_search_code_stops_at_the_time_budget_with_partial_results(tmp_path, monkeypatch):
    """A search must NEVER hang the turn: past _SEARCH_TIME_BUDGET it returns
    whatever it found plus a narrow-the-search note (the fixer-subagent
    'running… 285s' stall)."""
    import kbcode.tools.file as file_mod

    tools = _make_tools(tmp_path)
    monkeypatch.setattr(tools, "_ripgrep_available", lambda: False)
    (tools.root / "a.py").write_text("needle a\n", encoding="utf-8")
    (tools.root / "b.py").write_text("needle b\n", encoding="utf-8")
    # A negative budget puts the deadline strictly in the past — deterministic
    # (0.0 was flaky: the clock may not tick between deadline and first check).
    monkeypatch.setattr(file_mod, "_SEARCH_TIME_BUDGET", -1.0)

    out = tools._tool_search_code({"pattern": "needle"})

    assert "search stopped after -1s" in out
    assert "narrow it with the 'path' argument" in out


def test_search_code_outside_project_shows_absolute_path(tmp_path, monkeypatch):
    """A match outside the project root must not abort the search. kbcode isn't
    sandboxed to the project folder, so ``_resolve`` honors an absolute path
    pointing elsewhere — but ``Path.relative_to(self.root)`` raises ValueError
    ('... is not in the subpath of ...') on such a file. The hit should fall
    back to its absolute path instead of blowing up the whole tool."""
    tools = _make_tools(tmp_path)
    monkeypatch.setattr(tools, "_ripgrep_available", lambda: False)
    # a sibling of the project root, i.e. OUTSIDE it
    sibling = tmp_path / "other_project"
    sibling.mkdir()
    hit = sibling / "app.dart"
    hit.write_text("expiryDate here\n", encoding="utf-8")

    out = tools._tool_search_code({"pattern": "expiryDate", "path": str(sibling)})

    assert "expiryDate here" in out
    assert str(hit) in out  # absolute path, since it can't be made relative to root
