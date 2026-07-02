"""Shared test fixtures.

Every test gets an isolated kbcode home: ``Config.state_dir`` (memory db,
sessions, checkpoints, history, log) resolves under ``~/.kbcode/projects/``,
so without this override the suite would write into the developer's real home
directory — and pick up their real ``~/.kbcode/settings.json`` in load_config.
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_kbcode_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("kbcode-home")
    monkeypatch.setenv("KBCODE_HOME", str(home))
    return home
