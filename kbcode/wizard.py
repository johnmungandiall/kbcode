"""The `kbcode model` setup wizard (#2.1) — pick a provider, give a key,
auto-fetch models, pick one, save globally. Split out of cli.py, which still
owns the shared console singleton and the generic `_read` line-reader this
module imports.
"""

from __future__ import annotations

from pathlib import Path

from .cli import _read, console
from .config import PRESETS, Config, global_dir, save_settings


def _upsert_env(path: Path, key: str, value: str) -> None:
    """Set KEY=value in the .env file, replacing any existing (non-comment) line."""
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


def model_wizard(config: Config) -> int:
    """Interactive: pick a provider, give a key, auto-fetch models, pick one, save."""
    from .provider import get_provider  # local import keeps startup light

    config.ensure_dirs()
    names = list(PRESETS)

    # 1) provider
    console.print("[bold]Choose a provider:[/bold]")
    for i, name in enumerate(names, 1):
        console.print(f"  {i}. {name}")
    pick = _read("number > ")
    try:
        provider = names[int(pick) - 1]
    except (ValueError, IndexError):
        console.print("[red]Invalid choice.[/red]")
        return 1
    config.use_provider(provider)
    console.print(f"[green]→ {provider}[/green]")

    # 2) api key
    has_key = bool(config.api_key)
    suffix = " [Enter = keep current]" if has_key else ""
    key = _read(f"Enter API key ({config.key_env}){suffix} > ")
    if key:
        config.api_key = key
    elif not has_key:
        console.print("[red]A key is required to fetch the model list.[/red]")
        return 1

    # 3) base url (openai-compatible providers)
    if config.kind == "openai":
        shown = config.base_url or "default (api.openai.com)"
        base = _read(f"Base URL [{shown}] (Enter = keep) > ")
        if base:
            config.base_url = base

    # 4) fetch available models
    console.print("[dim]fetching available models...[/dim]")
    try:
        models = sorted(get_provider(config).list_models())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Couldn't fetch the model list ({exc}).[/yellow]")
        models = []

    # 5) pick a model
    if models:
        shown = models[:50]
        for i, m in enumerate(shown, 1):
            console.print(f"  {i}. {m}")
        if len(models) > len(shown):
            console.print(f"  ...and {len(models) - len(shown)} more")
        console.print("[dim]Pick a number, or type a model id directly.[/dim]")
        sel = _read(f"model [{config.model}] > ")
        if sel.isdigit() and 1 <= int(sel) <= len(shown):
            config.model = shown[int(sel) - 1]
        elif sel:
            config.model = sel
    else:
        sel = _read(f"Type the model id [{config.model}] > ")
        if sel:
            config.model = sel

    # 6) save GLOBALLY (~/.kbcode) so it applies to every project: selection ->
    #    settings.json, key -> .env. A project can still override via its own files.
    home = global_dir()
    preset_base = PRESETS[provider]["base_url"]
    base_to_save = config.base_url if config.base_url != preset_base else None
    save_settings(home, provider, config.model, base_to_save)
    if key:
        _upsert_env(home / ".env", config.key_env, key)
        if base_to_save:
            _upsert_env(home / ".env", "KBCODE_BASE_URL", base_to_save)

    console.print(
        f"[green]Saved to {home}[/green] — applies to every project.\n"
        f"provider=[bold]{provider}[/bold] model=[bold]{config.model}[/bold]\n"
        "Start chatting here with  [bold]python -m kbcode[/bold], or on another folder with "
        "[bold]python -m kbcode -C \"<path>\"[/bold]."
    )
    return 0
