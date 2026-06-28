"""Configuration, project paths, multi-provider presets, and saved settings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is optional at runtime
    def load_dotenv(*_args, **_kwargs):
        return False


DEFAULT_MAX_TOKENS = 16000
DEFAULT_EFFORT = "high"
# Auto-compact the chat once its history crosses this rough token estimate.
# 0 disables it. Override with KBCODE_COMPACT_TOKENS.
DEFAULT_COMPACT_TOKENS = 12000

# Built-in providers. "anthropic" uses the Anthropic SDK; every other entry is
# an OpenAI-compatible endpoint (so OpenAI, Gemini, DeepSeek, OpenRouter, etc.
# all share one code path — just a different base_url + key + model).
PRESETS: dict[str, dict] = {
    "anthropic": {
        "kind": "anthropic",
        "base_url": None,
        "key_env": "ANTHROPIC_API_KEY",
        "model": "claude-opus-4-8",
    },
    "openai": {
        "kind": "openai",
        "base_url": None,  # SDK default (api.openai.com)
        "key_env": "OPENAI_API_KEY",
        "model": "gpt-4o",
    },
    "openrouter": {
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "model": "openai/gpt-4o",
    },
    "deepseek": {
        "kind": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
    },
    "gemini": {
        "kind": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-2.0-flash",
    },
    # MiMo (and most other open models) are reachable through OpenRouter.
    "mimo": {
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "model": "openrouter/auto",
    },
    # Fully manual: set base_url + key yourself (e.g. a self-hosted endpoint).
    "custom": {
        "kind": "openai",
        "base_url": None,
        "key_env": "KBCODE_API_KEY",
        "model": "",
    },
}

DEFAULT_PROVIDER = "anthropic"


@dataclass
class Config:
    """Everything the agent needs: where files live and which model to call."""

    project_dir: Path
    provider: str = DEFAULT_PROVIDER
    kind: str = "anthropic"  # "anthropic" or "openai" (openai-compatible)
    model: str = "claude-opus-4-8"
    base_url: str | None = None
    api_key: str | None = None
    key_env: str = "ANTHROPIC_API_KEY"
    max_tokens: int = DEFAULT_MAX_TOKENS
    effort: str = DEFAULT_EFFORT
    compact_threshold: int = DEFAULT_COMPACT_TOKENS
    auto_approve: bool = False

    # --- derived paths -------------------------------------------------
    @property
    def kbcode_dir(self) -> Path:
        return self.project_dir / ".kbcode"

    @property
    def kb_dir(self) -> Path:
        return self.project_dir / "kb"

    @property
    def memory_db(self) -> Path:
        return self.kbcode_dir / "memory.db"

    @property
    def agent_md(self) -> Path:
        return self.project_dir / "AGENT.md"

    @property
    def settings_file(self) -> Path:
        return self.kbcode_dir / "settings.json"

    def ensure_dirs(self) -> None:
        self.kbcode_dir.mkdir(parents=True, exist_ok=True)
        self.kb_dir.mkdir(parents=True, exist_ok=True)

    def use_provider(
        self, name: str, model: str | None = None, base_url: str | None = None
    ) -> None:
        """Point the config at a provider preset. Explicit model/base_url win;
        otherwise the preset's defaults are used. The API key is read from the
        provider's key env var (or KBCODE_API_KEY)."""
        preset = PRESETS.get(name)
        if preset is None:
            raise ValueError(f"Unknown provider '{name}'. Choices: {', '.join(PRESETS)}")
        self.provider = name
        self.kind = preset["kind"]
        self.key_env = preset["key_env"]
        self.api_key = os.environ.get(preset["key_env"]) or os.environ.get("KBCODE_API_KEY")
        self.base_url = base_url if base_url is not None else preset["base_url"]
        self.model = model or preset["model"]


def load_settings(kbcode_dir: Path) -> dict:
    path = kbcode_dir / "settings.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(kbcode_dir: Path, provider: str, model: str, base_url: str | None) -> None:
    kbcode_dir.mkdir(parents=True, exist_ok=True)
    data = {"provider": provider, "model": model, "base_url": base_url}
    (kbcode_dir / "settings.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_config(project_dir: Path | None = None) -> Config:
    """Build a Config. Precedence for provider/model/base_url is:
    environment variables  >  saved .kbcode/settings.json  >  preset defaults.
    """
    project_dir = (project_dir or Path.cwd()).resolve()
    load_dotenv(project_dir / ".env")
    settings = load_settings(project_dir / ".kbcode")

    def _int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        try:
            return int(raw) if raw else default
        except ValueError:
            return default

    provider = os.environ.get("KBCODE_PROVIDER") or settings.get("provider") or DEFAULT_PROVIDER
    provider = provider.strip().lower()
    if provider not in PRESETS:
        provider = DEFAULT_PROVIDER
    preset = PRESETS[provider]

    model = os.environ.get("KBCODE_MODEL") or settings.get("model") or preset["model"]
    base_url = os.environ.get("KBCODE_BASE_URL") or settings.get("base_url") or preset["base_url"]

    config = Config(
        project_dir=project_dir,
        max_tokens=_int("KBCODE_MAX_TOKENS", DEFAULT_MAX_TOKENS),
        effort=os.environ.get("KBCODE_EFFORT", DEFAULT_EFFORT),
        compact_threshold=_int("KBCODE_COMPACT_TOKENS", DEFAULT_COMPACT_TOKENS),
    )
    config.use_provider(provider, model=model, base_url=base_url)
    return config
