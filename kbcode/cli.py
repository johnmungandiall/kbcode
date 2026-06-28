"""Command-line entry point and the interactive chat loop."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from .agent import Agent
from .config import PRESETS, Config, load_config, save_settings
from .knowledge_base import AGENT_MD_TEMPLATE, KnowledgeBase
from .memory import Memory
from .modes import load_modes
from .permissions import Permissions
from .prompt_input import make_input
from .prompts import build_system_prompt
from .provider import get_provider
from .tools import Tools
from .ui import COMMANDS, TerminalUI

console = Console()
ui = TerminalUI(console)


def _scaffold(config: Config, kb: KnowledgeBase) -> None:
    config.ensure_dirs()
    if not config.agent_md.exists():
        config.agent_md.write_text(AGENT_MD_TEMPLATE, encoding="utf-8")
    kb.scaffold()


def _build_agent(config: Config, kb: KnowledgeBase, memory: Memory) -> Agent:
    perm = Permissions(auto_approve=config.auto_approve)
    tools = Tools(config, memory, kb, perm)
    agent_md = config.agent_md.read_text(encoding="utf-8") if config.agent_md.exists() else ""
    system = build_system_prompt(kb.read_all(), memory.list_skills(), memory.recent(), agent_md)
    return Agent(
        system,
        get_provider(config),
        tools,
        compact_threshold=config.compact_threshold,
        ui=ui,
        modes=load_modes(config.kbcode_dir / "modes"),
    )


def _list_models(config: Config) -> None:
    """Fetch and print the model ids the current provider/key can use."""
    with ui.working("fetching available models…"):
        try:
            models = sorted(get_provider(config).list_models())
        except Exception as exc:  # noqa: BLE001
            ui.notice(f"Couldn't fetch models: {exc}", style="yellow")
            return
    if not models:
        ui.notice("No models reported by this provider.", style="yellow")
        return
    current = config.model
    lines = [(f"  {'●' if m == current else ' '} {m}") for m in models]
    ui.print("\n".join(lines))
    ui.notice("switch with  /model <id>")


def _require_key(config: Config) -> bool:
    if config.api_key:
        return True
    console.print(f"[red]No API key found for provider '{config.provider}'.[/red]")
    console.print(
        f"Add this line to your [bold].env[/bold] file (in this folder):\n"
        f"  {config.key_env}=your-key-here\n"
        "See .env.example for every provider's setting."
    )
    return False


def _read(prompt: str) -> str:
    """Read a line, tolerating a BOM some shells inject on piped input."""
    return "".join(c for c in console.input(prompt) if c.isprintable()).strip()


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


def _model_wizard(config: Config) -> int:
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

    # 6) save: selection -> settings.json, key -> .env
    preset_base = PRESETS[provider]["base_url"]
    base_to_save = config.base_url if config.base_url != preset_base else None
    save_settings(config.kbcode_dir, provider, config.model, base_to_save)
    if key:
        _upsert_env(config.project_dir / ".env", config.key_env, key)
        if base_to_save:
            _upsert_env(config.project_dir / ".env", "KBCODE_BASE_URL", base_to_save)

    console.print(
        f"[green]Saved.[/green] provider=[bold]{provider}[/bold] model=[bold]{config.model}[/bold]\n"
        "Run  [bold]python -m kbcode[/bold]  to start chatting."
    )
    return 0


def _repl(config: Config, kb: KnowledgeBase, memory: Memory) -> None:
    agent = _build_agent(config, kb, memory)
    ui.banner(config.provider, config.model, config.project_dir, agent.mode.name)

    arg_options = {"/provider": list(PRESETS), "/mode": list(agent.modes)}
    cmd_input = make_input(COMMANDS, arg_options)  # None if no autocomplete available
    if cmd_input:
        ui.notice("type / for commands")

    while True:
        try:
            if cmd_input:
                user = cmd_input.read(ui.prompt_html(agent.mode.name))
            else:
                user = _read(ui.prompt(agent.mode.name))
        except (EOFError, KeyboardInterrupt):
            ui.print("\nbye 👋")
            return
        if not user:
            continue

        if user in ("/exit", "/quit"):
            ui.print("bye 👋")
            return
        if user == "/help":
            ui.help()
            continue
        if user == "/status":
            ui.status_line(config.provider, config.model, agent.mode.name, agent.context_tokens())
            continue
        if user in ("/mode", "/modes"):
            for name, m in agent.modes.items():
                mark = "●" if name == agent.mode.name else " "
                ui.print(f"  {mark} [bold cyan]{name}[/bold cyan] — {m.description}")
            ui.notice("switch with  /mode <name>")
            continue
        if user.startswith("/mode"):
            name = user.split(maxsplit=1)[1].strip()
            if agent.set_mode(name):
                ui.notice(f"mode → {agent.mode.name}", style="green")
            else:
                ui.error(f"unknown mode '{name}'. Try: {', '.join(agent.modes)}")
            continue
        if user in ("/provider", "/providers"):
            ui.print("\n".join(f"  {'●' if n == config.provider else ' '} {n}" for n in PRESETS))
            ui.notice("switch with  /provider <name> [model]")
            continue
        if user.startswith("/provider"):
            parts = user.split()
            try:
                config.use_provider(parts[1], parts[2] if len(parts) > 2 else None)
            except ValueError as exc:
                ui.error(str(exc))
                continue
            if not _require_key(config):
                continue
            agent = _build_agent(config, kb, memory)  # new provider -> fresh chat
            ui.notice(f"switched → {config.provider} / {config.model}", style="green")
            continue
        if user in ("/model", "/models"):
            _list_models(config)
            continue
        if user.startswith("/model"):
            config.model = user.split(maxsplit=1)[1].strip()
            agent.provider = get_provider(config)  # same chat, new model
            ui.notice(f"model → {config.model}", style="green")
            continue
        if user == "/kb":
            notes = kb.list_notes()
            ui.print("\n".join(f"- kb/{n}" for n in notes) or "(knowledge base is empty)")
            continue
        if user == "/memory":
            rows = memory.recent()
            ui.print("\n".join(f"- {r['content']}" for r in rows) or "(memory is empty)")
            continue
        if user == "/skills":
            rows = memory.list_skills()
            ui.print("\n".join(f"- {r['name']}: {r['description']}" for r in rows) or "(no skills yet)")
            continue
        if user == "/compact":
            agent.compact_now()
            continue
        if user == "/kb-check":
            problems = kb.check_pointers(config.project_dir)
            if problems:
                ui.notice("Pointer problems:", style="yellow")
                ui.print("\n".join(f"- {p}" for p in problems))
            else:
                ui.notice("All kb/ pointers resolve.", style="green")
            continue
        if user == "/reset":
            agent.reset()
            ui.notice("chat cleared")
            continue

        try:
            agent.run(user)
        except Exception as exc:  # noqa: BLE001 - keep the REPL alive
            ui.error(str(exc))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    auto = False
    for flag in ("-y", "--yes"):
        if flag in argv:
            argv.remove(flag)
            auto = True

    config = load_config(Path.cwd())
    config.auto_approve = auto
    kb = KnowledgeBase(config.kb_dir)

    if argv and argv[0] == "init":
        _scaffold(config, kb)
        console.print(
            "[green]Initialized.[/green] Created AGENT.md, kb/, and .kbcode/.\n"
            "Next: pick a model with  [bold]python -m kbcode model[/bold]"
        )
        return 0

    if argv and argv[0] == "model":
        return _model_wizard(config)

    _scaffold(config, kb)
    if not _require_key(config):
        return 1

    memory = Memory(config.memory_db)
    try:
        if argv:  # one-shot: kbcode "do something"
            agent = _build_agent(config, kb, memory)
            agent.run(" ".join(argv))
        else:  # interactive chat
            _repl(config, kb, memory)
    finally:
        memory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
