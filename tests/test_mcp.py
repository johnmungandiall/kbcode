"""MCP support (kbcode/tools/mcp.py + the ToolsCore dispatch fork): config
parsing, an end-to-end run against tests/fake_mcp_server.py (a real
subprocess speaking stdio JSON-RPC), failure tolerance, and the safety rails
(permission gate, read_only/trusted, redaction, repair over MCP names).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kbcode.config import Config
from kbcode.knowledge_base import KnowledgeBase
from kbcode.memory import Memory
from kbcode.permissions import Permissions
from kbcode.tools import Tools
from kbcode.tools.mcp import MCPManager, MCPServerConfig, parse_mcp_configs

FAKE_SERVER = Path(__file__).parent / "fake_mcp_server.py"


def _fake_config(**overrides) -> MCPServerConfig:
    fields = {
        "name": "fake",
        "command": sys.executable,
        "args": [str(FAKE_SERVER)],
        "timeout": 15.0,
    }
    fields.update(overrides)
    return MCPServerConfig(**fields)


@pytest.fixture
def manager():
    mgr = MCPManager()
    yield mgr
    mgr.stop_all()


def _make_tools(tmp_path, mgr: MCPManager, perm: Permissions | None = None) -> Tools:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    config = Config(project_dir=project)
    config.ensure_dirs()
    tools = Tools(config, Memory(config.memory_db), KnowledgeBase(config.kb_dir), perm or Permissions(auto_approve=True))
    tools.mcp = mgr
    return tools


# --- config parsing ------------------------------------------------------

def test_parse_mcp_configs_skips_bad_and_disabled_entries():
    configs = parse_mcp_configs({
        "good": {"command": "server", "args": ["--x"], "read_only": True, "trusted": ["t1"]},
        "no-command": {"args": ["--x"]},
        "disabled": {"command": "server", "enabled": False},
        "not-a-dict": "server",
        "http": {"command": "server", "transport": "http"},
    })
    assert [c.name for c in configs] == ["good"]
    good = configs[0]
    assert good.read_only and good.trusted == ["t1"] and good.transport == "stdio"


def test_parse_mcp_configs_parallel_safe_is_read_only_alias():
    (cfg,) = parse_mcp_configs({"s": {"command": "x", "parallel_safe": True}})
    assert cfg.read_only


def test_parse_mcp_configs_expands_env_vars(monkeypatch):
    monkeypatch.setenv("KBCODE_TEST_MCP_REPO", "/some/repo")
    (cfg,) = parse_mcp_configs({"git": {"command": "uvx", "args": ["--repository", "${KBCODE_TEST_MCP_REPO}"]}})
    assert cfg.args == ["--repository", "/some/repo"]


# --- end-to-end against the fake stdio server ----------------------------

def test_manager_lists_namespaced_schemas_and_calls_tools(manager):
    manager.start_all([_fake_config()])
    assert "fake" in manager.clients

    names = [s["name"] for s in manager.schemas()]
    assert "mcp__fake__echo" in names and "mcp__fake__boom" in names

    result, is_error = manager.call("mcp__fake__echo", {"text": "hi"})
    assert result == "echo: hi" and not is_error

    result, is_error = manager.call("mcp__fake__boom", {})
    assert result == "kaboom" and is_error

    assert manager.summary() == [("fake", 3)]
    assert manager.tools_for("fake") == ["boom", "echo", "secretive"]


def test_manager_skips_a_server_that_fails_to_start(manager):
    warnings: list[str] = []
    manager.start_all(
        [_fake_config(name="broken", command="kbcode-no-such-binary-xyz"), _fake_config()],
        warn=warnings.append,
    )
    assert list(manager.clients) == ["fake"]  # the broken one is skipped, not fatal
    assert warnings and "broken" in warnings[0]


def test_read_only_server_marks_tools_parallel_safe(manager):
    manager.start_all([_fake_config(read_only=True)])
    assert all(s.get("parallel_safe") for s in manager.schemas())
    assert manager.is_read_only("mcp__fake__echo")
    assert manager.is_trusted("mcp__fake__echo")


def test_stop_all_is_idempotent(manager):
    manager.start_all([_fake_config()])
    manager.stop_all()
    manager.stop_all()
    assert not manager.clients and not manager.schemas()


def test_reload_reconnects(manager):
    manager.start_all([_fake_config()])
    manager.reload()
    result, is_error = manager.call("mcp__fake__echo", {"text": "again"})
    assert result == "echo: again" and not is_error


def test_reload_accepts_fresh_configs(manager):
    """/mcp reload passes freshly re-read configs so servers added to
    settings.json mid-session start without restarting kbcode."""
    manager.start_all([])  # launched with no mcpServers configured
    assert not manager.clients
    manager.reload([_fake_config()])
    result, is_error = manager.call("mcp__fake__echo", {"text": "late"})
    assert result == "echo: late" and not is_error


def test_load_mcp_servers_rereads_settings(tmp_path, monkeypatch, isolated_kbcode_home):
    """The helper /mcp reload uses picks up a block added after launch."""
    import json

    from kbcode.config import load_mcp_servers

    project = tmp_path / "proj"
    (project / ".kbcode").mkdir(parents=True)
    monkeypatch.chdir(project)

    assert load_mcp_servers(project) == {}  # nothing configured at "launch"
    (project / ".kbcode" / "settings.json").write_text(
        json.dumps({"mcpServers": {"late": {"command": "x"}}}), encoding="utf-8"
    )
    assert "late" in load_mcp_servers(project)  # added mid-session, seen on re-read


# --- ToolsCore dispatch fork ----------------------------------------------

def test_execute_routes_mcp_names_and_appends_schemas(tmp_path, manager):
    manager.start_all([_fake_config()])
    tools = _make_tools(tmp_path, manager)

    assert "mcp__fake__echo" in [s["name"] for s in tools.schemas]
    result, is_error = tools.execute("mcp__fake__echo", {"text": "hello"})
    assert result == "echo: hello" and not is_error


def test_execute_repair_suggests_close_mcp_name(tmp_path, manager):
    manager.start_all([_fake_config()])
    tools = _make_tools(tmp_path, manager)
    result, is_error = tools.execute("mcp__fake__ech", {"text": "x"})
    assert is_error and "Did you mean 'mcp__fake__echo'?" in result


def test_execute_denied_permission_blocks_the_call(tmp_path, manager):
    manager.start_all([_fake_config()])

    class DenyAll(Permissions):
        def check(self, tool, detail):
            return False

    tools = _make_tools(tmp_path, manager, perm=DenyAll(auto_approve=False))
    result, is_error = tools.execute("mcp__fake__echo", {"text": "hello"})
    assert is_error and "denied" in result.lower()


def test_execute_read_only_skips_the_permission_prompt(tmp_path, manager):
    manager.start_all([_fake_config(read_only=True)])

    class ExplodingPerm(Permissions):
        def check(self, tool, detail):  # pragma: no cover - the assertion IS not being called
            raise AssertionError("perm.check must not run for a read_only MCP tool")

    tools = _make_tools(tmp_path, manager, perm=ExplodingPerm(auto_approve=False))
    result, is_error = tools.execute("mcp__fake__echo", {"text": "quiet"})
    assert result == "echo: quiet" and not is_error


def test_execute_trusted_tool_skips_prompt_but_not_others(tmp_path, manager):
    manager.start_all([_fake_config(trusted=["echo"])])
    calls: list[str] = []

    class RecordingPerm(Permissions):
        def check(self, tool, detail):
            calls.append(tool)
            return True

    tools = _make_tools(tmp_path, manager, perm=RecordingPerm(auto_approve=False))
    tools.execute("mcp__fake__echo", {"text": "t"})
    assert calls == []  # trusted: no prompt
    tools.execute("mcp__fake__boom", {})
    assert calls == ["mcp__fake__boom"]  # untrusted sibling still prompts


def test_execute_redacts_secrets_in_mcp_results(tmp_path, manager):
    manager.start_all([_fake_config(read_only=True)])
    tools = _make_tools(tmp_path, manager)
    result, is_error = tools.execute("mcp__fake__secretive", {})
    assert not is_error
    assert "sk-ant-" not in result
    assert "redacted" in result  # the audit note from _note_redactions


# --- config merge ----------------------------------------------------------

def test_load_config_merges_mcp_servers_per_server(tmp_path, monkeypatch, isolated_kbcode_home):
    import json

    from kbcode.config import load_config

    home = isolated_kbcode_home
    (home / "settings.json").write_text(
        json.dumps({"mcpServers": {"home-server": {"command": "a"}, "shared": {"command": "home"}}}),
        encoding="utf-8",
    )
    project = tmp_path / "proj"
    (project / ".kbcode").mkdir(parents=True)
    (project / ".kbcode" / "settings.json").write_text(
        json.dumps({"mcpServers": {"proj-server": {"command": "b"}, "shared": {"command": "proj"}}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    config = load_config(project)
    assert set(config.mcp) == {"home-server", "proj-server", "shared"}  # union, not override
    assert config.mcp["shared"]["command"] == "proj"  # per-server: project wins
