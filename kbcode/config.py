"""Configuration, project paths, multi-provider presets, and saved settings."""

from __future__ import annotations

import json
import os
import re
import time
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
DEFAULT_COMPACT_TOKENS = 80000
# Per-request HTTP timeout (seconds) for the provider call. Without this the
# SDK default (~600s) lets a stalled model freeze the agent for ten minutes —
# painfully visible when a subagent makes many calls. On timeout the request
# fails fast and _with_retry backs off and retries. Override with
# KBCODE_REQUEST_TIMEOUT; 0 restores the SDK default (no explicit timeout).
DEFAULT_REQUEST_TIMEOUT = 120
# Per-turn runaway-loop guards: tool round-trips per user message (the agent
# loop's step cap) and run_command calls per turn. Both stop the turn safely —
# saying "continue" resumes — but a long, legitimate task can hit them, so they
# are tunable: KBCODE_MAX_STEPS / KBCODE_MAX_COMMANDS.
DEFAULT_MAX_STEPS = 50
DEFAULT_MAX_COMMANDS = 25

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
    max_steps: int = DEFAULT_MAX_STEPS
    max_commands_per_turn: int = DEFAULT_MAX_COMMANDS
    auto_approve: bool = False
    hooks: dict = field(default_factory=dict)  # PreToolUse/PostToolUse/Stop config, from settings.json (see hooks.py)
    mcp: dict = field(default_factory=dict)  # MCP servers from settings.json "mcpServers" (see tools/mcp.py)

    # --- derived paths -------------------------------------------------
    @property
    def kbcode_dir(self) -> Path:
        return self.project_dir / ".kbcode"

    @property
    def kb_dir(self) -> Path:
        return self.project_dir / "kb"

    @property
    def state_dir(self) -> Path:
        """Machine-local runtime state for THIS project — memory db, sessions,
        checkpoints, input history, log. Lives in the user's home
        (``~/.kbcode/projects/<slug>``, mirroring Claude Code's
        ``~/.claude/projects``) so launching kbcode never dumps runtime files
        into the project's working tree. A project that already carries a
        legacy ``.kbcode/memory.db`` keeps using its local dir."""
        if (self.kbcode_dir / "memory.db").exists():
            return self.kbcode_dir
        return global_dir() / "projects" / project_slug(self.project_dir)

    @property
    def memory_db(self) -> Path:
        return self.state_dir / "memory.db"

    @property
    def checkpoints_dir(self) -> Path:
        # Hermes idea: a hidden shadow git store for auto pre-edit snapshots.
        return self.state_dir / "checkpoints"

    @property
    def sessions_dir(self) -> Path:
        # Claude Code / Hermes idea: persisted chat transcripts for --continue,
        # --resume, and cross-session /insights rollups.
        return self.state_dir / "sessions"

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
        return self.state_dir / "history"

    @property
    def prompts_dir(self) -> Path:
        # Custom system-prompt fragments (like standing-orders.md, but split
        # across files), appended in sorted order.
        return self.kbcode_dir / "prompts"

    def ensure_dirs(self) -> None:
        self.kbcode_dir.mkdir(parents=True, exist_ok=True)
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _ensure_self_ignore(self.kbcode_dir)

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


def _ensure_self_ignore(kbcode_dir: Path) -> None:
    """Drop a ``*`` .gitignore inside ``.kbcode/`` so its per-machine state
    (memory db, logs, sessions, checkpoints) never shows up as untracked in the
    host project's git — same trick as .pytest_cache/.ruff_cache. Existing
    file (user may have customized it) is left alone; failures are non-fatal."""
    gitignore = kbcode_dir / ".gitignore"
    try:
        if not gitignore.exists():
            gitignore.write_text("*\n", encoding="utf-8")
    except OSError:
        pass  # read-only mount etc. — worst case git shows the files again


def global_dir() -> Path:
    """User-level kbcode home (``~/.kbcode``) — shared config, plus each
    project's runtime state under ``projects/``. ``KBCODE_HOME`` overrides the
    location (tests use it to stay out of the real home dir)."""
    override = os.environ.get("KBCODE_HOME")
    if override:
        return Path(override)
    return Path.home() / ".kbcode"


def project_slug(project_dir: Path) -> str:
    """Encode an absolute project path as a single folder name, the way Claude
    Code names ``~/.claude/projects`` entries: every character that isn't a
    letter or digit becomes a dash (``d:\\AI Agents\\kb`` -> ``d--AI-Agents-kb``)."""
    resolved = str(Path(project_dir).resolve())
    return re.sub(r"[^A-Za-z0-9]", "-", resolved)


def load_mcp_servers(project_dir: Path, launch_dir: Path | None = None) -> dict:
    """The merged ``mcpServers`` blocks from home → launch → project — a
    PER-SERVER union (higher scope wins per server *name*, like Claude Code),
    unlike the whole-value shallow override every other settings key gets in
    ``load_config``. Split out so ``/mcp reload`` can re-read servers added
    mid-session without rebuilding the whole Config."""
    launch = (launch_dir or Path.cwd()).resolve()
    merged: dict = {}
    for kbdir in (global_dir(), launch / ".kbcode", Path(project_dir).resolve() / ".kbcode"):
        block = load_settings(kbdir).get("mcpServers")
        if isinstance(block, dict):
            merged.update(block)
    return merged


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
    _ensure_self_ignore(kbcode_dir)
    data = {"provider": provider, "model": model, "base_url": base_url}
    (kbcode_dir / "settings.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def persist_choice(config: "Config") -> None:
    """Persist the current provider/model/base_url choice from the live Config.

    Writes settings.json to both global (for future default) and the config's
    project .kbcode dir (so the folder immediately sees the choice).
    If the project folder already has a .env it also updates the KBCODE_PROVIDER
    / KBCODE_MODEL / KBCODE_BASE_URL pins so env-var precedence doesn't hide
    the selection.
    The API key itself is never written by this helper.
    """
    from pathlib import Path as _Path  # local alias to avoid shadowing

    home = global_dir()
    preset = PRESETS.get(config.provider, {})
    preset_base = preset.get("base_url")
    base_to_save = config.base_url if config.base_url != preset_base else None

    save_settings(home, config.provider, config.model, base_to_save)
    save_settings(config.kbcode_dir, config.provider, config.model, base_to_save)

    # If project .env already exists with KBCODE_* pins, keep it in sync.
    proj_env = config.project_dir / ".env"
    if proj_env.exists():
        upsert_env_value(proj_env, "KBCODE_PROVIDER", config.provider)
        upsert_env_value(proj_env, "KBCODE_MODEL", config.model)
        if base_to_save:
            upsert_env_value(proj_env, "KBCODE_BASE_URL", base_to_save)
        else:
            clear_env_key(proj_env, "KBCODE_BASE_URL")


def persist_global_choice(config: "Config") -> None:
    """Persist the current choice to `~/.kbcode` only — the cross-project default.

    Use this when switching provider/model from the REPL (``/provider``, ``/model``)
    so the change shows up as the default when you open a different project.
    Unlike :func:`persist_choice`, this does NOT write to the project's
    ``.kbcode/settings.json``, so a project that was explicitly configured via
    ``kb model`` can still keep its own overrides.
    """
    preset = PRESETS.get(config.provider, {})
    preset_base = preset.get("base_url")
    base_to_save = config.base_url if config.base_url != preset_base else None
    save_settings(global_dir(), config.provider, config.model, base_to_save)


# --- .env helpers (internal but usable by wizard + repl for consistent pinning) ---
def upsert_env_value(path: Path, key: str, value: str) -> None:
    """Set KEY=value (replaces non-comment existing line). Creates file if needed."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, found = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") and not stripped.startswith("#"):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def clear_env_key(path: Path, key: str) -> None:
    """Remove KEY= line (non-comment) from a .env."""
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    out = [
        ln for ln in lines
        if not (ln.strip().startswith(f"{key}=") and not ln.strip().startswith("#"))
    ]
    path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")


# --- model list cache (persisted across sessions for fast autocomplete) ---

# 24 hours — after that, the next autocomplete triggers a background refresh.
_MODEL_CACHE_TTL_SECONDS = 24 * 60 * 60


def _model_cache_dir() -> Path:
    """``~/.kbcode/models/`` — persisted model lists, one JSON file per provider."""
    d = global_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_model_cache(provider: str) -> list[str] | None:
    """Return a cached model list for *provider*, or None if missing or stale."""
    path = _model_cache_dir() / f"{provider}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - data.get("_ts", 0) > _MODEL_CACHE_TTL_SECONDS:
        return None  # stale — caller should refresh
    return data.get("models")


def save_model_cache(provider: str, models: list[str]) -> None:
    """Persist a model list for *provider* to disk (with a freshness timestamp)."""
    data = {"_ts": time.time(), "models": models}
    (_model_cache_dir() / f"{provider}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


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
    # Exception: "mcpServers" is merged PER SERVER by load_mcp_servers().
    settings: dict = {}
    for kbdir in (home, launch_dir / ".kbcode", project_dir / ".kbcode"):
        for key, value in load_settings(kbdir).items():
            if key == "mcpServers":
                continue  # merged per-server below, not whole-block
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
        compact_threshold=_int("KBCODE_COMPACT_TOKENS", settings.get("compact_tokens") or DEFAULT_COMPACT_TOKENS),
        request_timeout=_int("KBCODE_REQUEST_TIMEOUT", DEFAULT_REQUEST_TIMEOUT),
        max_steps=_int("KBCODE_MAX_STEPS", DEFAULT_MAX_STEPS),
        max_commands_per_turn=_int("KBCODE_MAX_COMMANDS", DEFAULT_MAX_COMMANDS),
        hooks=settings.get("hooks") or {},
        mcp=load_mcp_servers(project_dir, launch_dir),
    )
    config.use_provider(provider, model=model, base_url=base_url)
    return config
