"""Configuration, project paths, multi-provider presets, and saved settings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional at runtime
    def load_dotenv(*_args, **_kwargs):
        return False


DEFAULT_MAX_TOKENS = 16000
DEFAULT_EFFORT = "high"
# Auto-compact the chat once its history crosses this rough token estimate.
# 0 disables it. Override with KBCODE_COMPACT_TOKENS.
DEFAULT_COMPACT_TOKENS = 12000
# Per-request HTTP timeout (seconds) for the provider call. Without this the
# SDK default (~600s) lets a stalled model freeze the agent for ten minutes —
# painfully visible when a subagent makes many calls. On timeout the request
# fails fast and _with_retry backs off and retries. Override with
# KBCODE_REQUEST_TIMEOUT; 0 restores the SDK default (no explicit timeout).
DEFAULT_REQUEST_TIMEOUT = 120

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
    # Local models via Ollama's OpenAI-compatible endpoint. No real API key is
    # needed, but the OpenAI SDK requires a non-empty value, so a dummy is used
    # unless OLLAMA_API_KEY is set (e.g. for a remote/authenticated Ollama).
    "ollama": {
        "kind": "openai",
        "base_url": "http://localhost:11434/v1",
        "key_env": "OLLAMA_API_KEY",
        "model": "llama3.1",
        "key_optional": True,
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
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT
    auto_approve: bool = False
    hooks: dict = field(default_factory=dict)  # PreToolUse/PostToolUse/Stop config, from settings.json (see hooks.py)

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
    def checkpoints_dir(self) -> Path:
        # Hermes idea: a hidden shadow git store for auto pre-edit snapshots.
        return self.kbcode_dir / "checkpoints"

    @property
    def sessions_dir(self) -> Path:
        # Claude Code / Hermes idea: persisted chat transcripts for --continue,
        # --resume, and cross-session /insights rollups.
        return self.kbcode_dir / "sessions"

    @property
    def agent_md(self) -> Path:
        return self.project_dir / "AGENT.md"

    @property
    def settings_file(self) -> Path:
        return self.kbcode_dir / "settings.json"

    @property
    def standing_orders_file(self) -> Path:
        # openclaw idea: persistent instructions injected into every session.
        return self.kbcode_dir / "standing-orders.md"

    @property
    def history_file(self) -> Path:
        # prompt_toolkit's on-disk input history, so up-arrow recalls past
        # prompts across sessions (not just within one REPL run).
        return self.kbcode_dir / "history"

    @property
    def prompts_dir(self) -> Path:
        # Custom system-prompt fragments (like standing-orders.md, but split
        # across files), appended in sorted order.
        return self.kbcode_dir / "prompts"

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
        if not self.api_key and preset.get("key_optional"):
            self.api_key = "not-needed"  # e.g. a local Ollama server doesn't check it
        self.base_url = base_url if base_url is not None else preset["base_url"]
        self.model = model or preset["model"]


def global_dir() -> Path:
    """User-level kbcode config (``~/.kbcode``) — shared by every project."""
    return Path.home() / ".kbcode"


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
    """Build a Config. Precedence for provider/model/base_url and the API key is:
    environment vars  >  the project's `.kbcode`/.env  >  the launch folder's  >
    the global `~/.kbcode`  >  preset defaults.

    The launch-folder and global fallbacks mean you can configure kbcode once
    (e.g. `python -m kbcode model`, which saves to `~/.kbcode`) and then point it
    at any project with `-C` without re-entering your key there.
    """
    project_dir = (project_dir or Path.cwd()).resolve()
    launch_dir = Path.cwd().resolve()
    home = global_dir()

    # Load .env files highest-priority first (load_dotenv never overrides a value
    # already set, so the project's .env wins, then the launch folder, then global).
    load_dotenv(project_dir / ".env")
    if launch_dir != project_dir:
        load_dotenv(launch_dir / ".env")
    load_dotenv(home / ".env")

    # Merge settings.json the same way: read low→high priority, let higher win.
    settings: dict = {}
    for kbdir in (home, launch_dir / ".kbcode", project_dir / ".kbcode"):
        for key, value in load_settings(kbdir).items():
            if value is not None:
                settings[key] = value

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
        request_timeout=_int("KBCODE_REQUEST_TIMEOUT", DEFAULT_REQUEST_TIMEOUT),
        hooks=settings.get("hooks") or {},
    )
    config.use_provider(provider, model=model, base_url=base_url)
    return config
