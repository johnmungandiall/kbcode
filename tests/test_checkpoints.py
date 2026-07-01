"""Covers IMPROVEMENTS.md #10.4: ensure_checkpoint() should batch into one
snapshot per turn, not one per tool call. Turns out this was already
implemented (Checkpoints._taken_this_turn, reset by new_turn()) — these tests
lock that behavior in rather than change it.
"""

from __future__ import annotations

import shutil

import pytest

from kbcode.checkpoints import Checkpoints

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _make_checkpoints(tmp_path) -> Checkpoints:
    project = tmp_path / "project"
    project.mkdir()
    (project / "file.txt").write_text("v1", encoding="utf-8")
    return Checkpoints(project, tmp_path / "store")


def test_only_the_first_call_in_a_turn_snapshots(tmp_path):
    cps = _make_checkpoints(tmp_path)
    assert cps.ensure_checkpoint("before write_file") is True
    assert cps.ensure_checkpoint("before edit_file") is False  # same turn — deduped
    assert cps.ensure_checkpoint("before run_command") is False  # still deduped
    assert len(cps.list_checkpoints()) == 1


def test_new_turn_allows_a_fresh_checkpoint(tmp_path):
    cps = _make_checkpoints(tmp_path)
    cps.ensure_checkpoint("turn 1")
    cps.new_turn()
    (cps.root / "file.txt").write_text("v2", encoding="utf-8")  # something to snapshot
    assert cps.ensure_checkpoint("turn 2") is True
    assert len(cps.list_checkpoints()) == 2


def test_ensure_checkpoint_is_a_noop_when_nothing_changed(tmp_path):
    cps = _make_checkpoints(tmp_path)
    cps.ensure_checkpoint("turn 1")
    cps.new_turn()
    # nothing changed on disk since the last checkpoint
    assert cps.ensure_checkpoint("turn 2") is False
    assert len(cps.list_checkpoints()) == 1
