"""web_search: the ddgs-backed tool in kbcode/tools/web.py."""

from __future__ import annotations

import json
import sys
import time

import kbcode.tools.web as web_mod
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


def test_web_search_returns_json_results(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    calls = []

    def fake_search(query, limit):
        calls.append((query, limit))
        return [{"title": "Example", "url": "https://example.com", "description": "desc"}]

    monkeypatch.setattr(web_mod, "_run_ddgs_search", fake_search)
    out = tools._tool_web_search({"query": "kbcode agent", "limit": 3})
    assert calls == [("kbcode agent", 3)]
    assert json.loads(out) == [{"title": "Example", "url": "https://example.com", "description": "desc"}]


def test_web_search_no_results(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    monkeypatch.setattr(web_mod, "_run_ddgs_search", lambda query, limit: [])
    assert tools._tool_web_search({"query": "nothing"}) == "No results found."


def test_web_search_limit_defaults_and_clamps(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    seen = {}

    def fake_search(query, limit):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(web_mod, "_run_ddgs_search", fake_search)
    tools._tool_web_search({"query": "q"})
    assert seen["limit"] == 5  # default
    tools._tool_web_search({"query": "q", "limit": 999})
    assert seen["limit"] == 20  # clamped to max
    tools._tool_web_search({"query": "q", "limit": "not-a-number"})
    assert seen["limit"] == 5  # falls back to default on bad input


def test_web_search_times_out(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    monkeypatch.setattr(web_mod, "_SEARCH_TIMEOUT_SECS", 0.05)

    def slow_search(query, limit):
        time.sleep(0.5)
        return []

    monkeypatch.setattr(web_mod, "_run_ddgs_search", slow_search)
    out = tools._tool_web_search({"query": "slow"})
    assert "timed out" in out


def test_web_search_reports_missing_package(tmp_path, monkeypatch):
    tools = _make_tools(tmp_path)
    monkeypatch.setitem(sys.modules, "ddgs", None)  # forces `import ddgs` to raise ImportError
    out = tools._tool_web_search({"query": "q"})
    assert "pip install ddgs" in out
