from pathlib import Path

from kbcode.config import (
    DEFAULT_MAX_COMMANDS,
    DEFAULT_MAX_STEPS,
    PRESETS,
    Config,
    load_config,
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


def test_use_provider_unknown_raises():
    config = Config(project_dir=Path("."))
    try:
        config.use_provider("not-a-real-provider")
        assert False, "expected ValueError"
    except ValueError:
        pass
