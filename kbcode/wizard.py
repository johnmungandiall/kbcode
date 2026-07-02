"""The `kbcode model` setup wizard (#2.1) — pick a provider, give a key,
auto-fetch models, pick one, persist so the next run picks it up.

Saves provider/model to global (~/.kbcode/settings.json for defaults) + the
current project's .kbcode/settings.json (so it sticks for `kb` in this folder).
Keys only go to global .env. If a project .env pins via KBCODE_* vars we update
the pins so the selection actually applies (env vars otherwise beat settings).
"""

from __future__ import annotations

from pathlib import Path

from .cli import _read, console
from .config import PRESETS, Config, clear_env_key, global_dir, persist_choice, save_settings, upsert_env_value


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

    # 6) Persist so next `kb` (or `kb -C`) immediately uses the choice.
    # persist_choice writes settings (global + project) and syncs KBCODE_* in
    # an existing project .env. Only the key (if newly entered) goes to global .env.
    preset_base = PRESETS[provider]["base_url"]
    base_to_save = config.base_url if config.base_url != preset_base else None

    if key:
        upsert_env_value(global_dir() / ".env", config.key_env, key)
        if base_to_save:
            upsert_env_value(global_dir() / ".env", "KBCODE_BASE_URL", base_to_save)

    # This handles writing settings.json + updating any project .env pins.
    persist_choice(config)

    console.print(
        f"[green]Saved to {global_dir()}[/green] (global default) and current project.\n"
        f"provider=[bold]{provider}[/bold] model=[bold]{config.model}[/bold]\n"
        "Start chatting here with  [bold]python -m kbcode[/bold], or on another folder with "
        "[bold]python -m kbcode -C \"<path>\"[/bold]."
    )
    return 0
