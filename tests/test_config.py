from pathlib import Path

from kbcode.config import (
    DEFAULT_MAX_COMMANDS,
    DEFAULT_MAX_STEPS,
    PRESETS,
    Config,
    load_config,
    project_slug,
)


def test_ollama_preset_is_registered():
    assert "ollama" in PRESETS
    assert PRESETS["ollama"]["kind"] == "openai"
    assert PRESETS["ollama"]["base_url"] == "http://localhost:11434/v1"


def test_use_provider_ollama_works_without_an_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("KBCODE_API_KEY", raising=False)
    config = Config(project_dir=tmp_path)
    config.use_provider("ollama")
    assert config.api_key  # a dummy value, not None/empty — the SDK requires *something*
    assert config.base_url == "http://localhost:11434/v1"
    assert config.model == "llama3.1"


def test_use_provider_ollama_prefers_real_key_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "real-remote-key")
    config = Config(project_dir=tmp_path)
    config.use_provider("ollama")
    assert config.api_key == "real-remote-key"


def test_runaway_guard_defaults():
    config = Config(project_dir=Path("."))
    assert config.max_steps == DEFAULT_MAX_STEPS
    assert config.max_commands_per_turn == DEFAULT_MAX_COMMANDS


def test_runaway_guard_env_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # keep the repo's own .env out of load_dotenv's reach
    monkeypatch.setenv("KBCODE_MAX_STEPS", "150")
    monkeypatch.setenv("KBCODE_MAX_COMMANDS", "100")
    config = load_config(tmp_path)
    assert config.max_steps == 150
    assert config.max_commands_per_turn == 100


def test_runaway_guard_zero_means_unlimited(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # keep the repo's own .env out of load_dotenv's reach
    monkeypatch.setenv("KBCODE_MAX_STEPS", "0")
    monkeypatch.setenv("KBCODE_MAX_COMMANDS", "0")
    config = load_config(tmp_path)
    assert config.max_steps == 0  # 0 passes through — Agent treats it as no cap
    assert config.max_commands_per_turn == 0


def test_use_provider_unknown_raises():
    config = Config(project_dir=Path("."))
    try:
        config.use_provider("not-a-real-provider")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_project_slug_encodes_path_claude_code_style(tmp_path):
    project = tmp_path / "My App"
    project.mkdir()
    slug = project_slug(project)
    assert slug == "".join(c if c.isalnum() else "-" for c in str(project.resolve()))
    assert " " not in slug and "\\" not in slug and ":" not in slug


def test_state_dir_lives_under_kbcode_home(tmp_path, isolated_kbcode_home):
    config = Config(project_dir=tmp_path)
    state = config.state_dir
    assert state == isolated_kbcode_home / "projects" / project_slug(tmp_path)
    # every runtime-state path hangs off it, out of the project's working tree
    for p in (config.memory_db, config.checkpoints_dir, config.sessions_dir, config.history_file):
        assert state in p.parents
        assert tmp_path not in p.parents


def test_state_dir_legacy_project_keeps_local_kbcode(tmp_path):
    config = Config(project_dir=tmp_path)
    config.kbcode_dir.mkdir()
    (config.kbcode_dir / "memory.db").touch()  # marker: project predates the home-dir move
    assert config.state_dir == config.kbcode_dir
    assert config.memory_db == config.kbcode_dir / "memory.db"


def test_ensure_dirs_writes_self_ignoring_gitignore(tmp_path):
    config = Config(project_dir=tmp_path)
    config.ensure_dirs()
    gitignore = config.kbcode_dir / ".gitignore"
    assert gitignore.read_text(encoding="utf-8").strip() == "*"
    # a customized one is left alone
    gitignore.write_text("settings.json\n", encoding="utf-8")
    config.ensure_dirs()
    assert gitignore.read_text(encoding="utf-8") == "settings.json\n"


def test_upsert_env_value_creates_missing_parent_dir(tmp_path):
    """The wizard writes the API key to ~/.kbcode/.env BEFORE anything else has
    created ~/.kbcode — on a fresh install this used to crash with
    FileNotFoundError and leave no global folder at all."""
    from kbcode.config import upsert_env_value

    env = tmp_path / "kbhome" / ".env"  # kbhome does not exist yet
    upsert_env_value(env, "MY_KEY", "abc")
    assert env.read_text(encoding="utf-8") == "MY_KEY=abc\n"
