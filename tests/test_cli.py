"""CLI smoke tests (IMPROVEMENTS.md #1.3): invoke the real `python -m kbcode`
entry point as a subprocess and check it exits cleanly for a few key paths.
No network/API calls are made — these only exercise argument handling,
scaffolding, and the "no API key configured" failure path.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

from kbcode.provider import ProviderError
from kbcode.repl import _ping, _read_multiline

REPO_ROOT = Path(__file__).resolve().parent.parent


class _FakeProviderForPing:
    def __init__(self, models=None, error=None):
        self.config = types.SimpleNamespace(provider="testprov")
        self._models = models or []
        self._error = error

    def list_models(self):
        if self._error is not None:
            raise self._error
        return self._models


class _FakeAgentForPing:
    def __init__(self, provider):
        self.provider = provider


def test_ping_reports_success_and_model_count(capsys):
    agent = _FakeAgentForPing(_FakeProviderForPing(models=["model-a", "model-b"]))
    _ping(agent)
    out = capsys.readouterr().out
    assert "testprov" in out
    assert "2 model" in out


def test_ping_reports_provider_error_with_hint(capsys):
    err = ProviderError("bad key", hint="check your .env")
    agent = _FakeAgentForPing(_FakeProviderForPing(error=err))
    _ping(agent)
    out = capsys.readouterr().out
    assert "bad key" in out
    assert "check your .env" in out


def test_ping_does_not_raise_on_unexpected_error(capsys):
    agent = _FakeAgentForPing(_FakeProviderForPing(error=RuntimeError("network exploded")))
    _ping(agent)  # must not raise
    out = capsys.readouterr().out
    assert "network exploded" in out


def test_read_multiline_passes_through_a_normal_line():
    lines = iter(["hello there"])
    assert _read_multiline(lambda: next(lines)) == "hello there"


def test_read_multiline_collects_a_triple_quote_block():
    lines = iter(['"""', "line one", "line two", '"""'])
    assert _read_multiline(lambda: next(lines)) == "line one\nline two"


def test_read_multiline_block_can_be_empty():
    lines = iter(['"""', '"""'])
    assert _read_multiline(lambda: next(lines)) == ""


def _run(args: list[str], cwd: Path, home: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    # Redirect home so load_config()'s global ~/.kbcode / ~/.kbcode/.env fallback
    # can't pick up a real key from the developer's machine.
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    for key_env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "KBCODE_API_KEY"):
        env.pop(key_env, None)
    return subprocess.run(
        [sys.executable, "-m", "kbcode", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_version_flag_prints_version_and_exits_zero(tmp_path):
    result = _run(["--version"], cwd=tmp_path, home=tmp_path / "home")
    assert result.returncode == 0
    assert "kbcode" in result.stdout


def test_init_scaffolds_project_and_exits_zero(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    result = _run(["init"], cwd=project, home=tmp_path / "home")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (project / "AGENT.md").exists()
    assert (project / "kb").is_dir()
    assert (project / ".kbcode").is_dir()


def test_missing_project_folder_reports_error_and_exits_nonzero(tmp_path):
    result = _run(["-C", str(tmp_path / "does-not-exist"), "hello"], cwd=tmp_path, home=tmp_path / "home")
    assert result.returncode == 1
    assert "Folder not found" in result.stdout


def test_one_shot_without_api_key_fails_cleanly(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    result = _run(["say hello"], cwd=project, home=tmp_path / "home")
    assert result.returncode == 1
    assert "No API key found" in result.stdout
    # scaffolding still happens before the key check
    assert (project / "AGENT.md").exists()
