"""Command-line entry point and the interactive chat loop."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .agent import Agent
from .checkpoints import format_checkpoints
from .config import PRESETS, Config, global_dir, load_config, save_settings
from .interrupt import interrupt_on_escape
from .knowledge_base import AGENT_MD_TEMPLATE, KnowledgeBase
from .memory import Memory
from .modes import load_modes
from .permissions import Permissions
from .prompt_input import make_input, select
from .prompts import build_system_prompt
from .provider import ProviderError, get_provider
from .subagents import load_subagents
from .tools import Tools
from .ui import COMMANDS, TerminalUI

console = Console()
ui = TerminalUI(console)

# Where releases live, so `kbcode update` can pull the latest (GitHub install).
_REPO_URL = "https://github.com/johnmungandiall/kbcode"
_GIT_TARGET = f"git+{_REPO_URL}.git"


def _self_update() -> int:
    """`kbcode update` — upgrade the install in place from GitHub."""
    console.print(f"[cyan]Updating kbcode from {_REPO_URL} …[/cyan]")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", _GIT_TARGET],
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - surface any launch failure cleanly
        console.print(f"[red]Update failed:[/red] {exc}")
        return 1
    if proc.returncode == 0:
        console.print("[green]Updated.[/green]  Check with  [bold]kbcode --version[/bold]")
    else:
        console.print("[yellow]pip reported a problem (see its output above).[/yellow]")
    return proc.returncode


def _scaffold(config: Config, kb: KnowledgeBase) -> None:
    config.ensure_dirs()
    if not config.agent_md.exists():
        config.agent_md.write_text(AGENT_MD_TEMPLATE, encoding="utf-8")
    if not config.standing_orders_file.exists():
        config.standing_orders_file.write_text(_STANDING_ORDERS_TEMPLATE, encoding="utf-8")
    agents_dir = config.kbcode_dir / "agents"
    sample_agent = agents_dir / "code-explorer.md"
    if not sample_agent.exists():
        agents_dir.mkdir(parents=True, exist_ok=True)
        sample_agent.write_text(_CODE_EXPLORER_AGENT, encoding="utf-8")
    kb.scaffold()


# Pinned, always-on instructions prepended to every session's system prompt.
_STANDING_ORDERS_TEMPLATE = """\
# Standing orders

Anything you write here is added to the agent's instructions at the start of
*every* session. Use it for durable rules the agent should always follow, e.g.:

- Always run the project's tests after changing code.
- Reply in plain language; avoid jargon.
- Never edit files under `vendor/` or `migrations/`.

(Delete these examples and add your own. Leave the file empty to disable.)
"""

# A starter subagent so .kbcode/agents/ has a working example to copy.
_CODE_EXPLORER_AGENT = """\
---
description: Explore the codebase and report the key files and how a feature works.
tools: read
---
You are a code explorer running in your own context window. You are read-only.

Given a task, trace it through the code: find entry points, follow the call path,
and note the files and `path:line` anchors that matter. Do NOT edit anything.

Return a tight summary: the 3-8 files worth reading, what each does, and the one
or two functions where the real work happens. Keep it short — the main agent only
gets your summary, not your steps.
"""


def _build_agent(config: Config, kb: KnowledgeBase, memory: Memory) -> Agent:
    ui.root = config.project_dir  # so file tool-lines show the full path
    perm = Permissions(auto_approve=config.auto_approve, ui=ui)
    tools = Tools(config, memory, kb, perm)
    agent_md = config.agent_md.read_text(encoding="utf-8") if config.agent_md.exists() else ""
    orders = ""
    if config.standing_orders_file.exists():
        raw = config.standing_orders_file.read_text(encoding="utf-8")
        # Ignore the untouched scaffold (its examples are not real orders).
        if raw.strip() and raw.strip() != _STANDING_ORDERS_TEMPLATE.strip():
            orders = raw
    system = build_system_prompt(
        kb.read_all(), memory.list_skills(), memory.recent(), agent_md, orders
    )
    return Agent(
        system,
        get_provider(config, ui),
        tools,
        compact_threshold=config.compact_threshold,
        ui=ui,
        modes=load_modes(config.kbcode_dir / "modes"),
        subagents=load_subagents(config.kbcode_dir / "agents"),
    )


def _rollback_menu(cps, rows: list[dict]) -> bool:
    """Arrow-key checkpoint picker for `/rollback` with no arguments.

    Basic users shouldn't have to remember `/rollback <n> <file>` syntax — this
    walks them through it with the same selectable-menu UI Permissions uses.
    Returns True if it handled the flow, False if no interactive menu is
    available here (no TTY / prompt_toolkit missing) so the caller can fall
    back to printing the plain numbered list.
    """
    labels = [f"{r['short']}  {r['when'][:16].replace('T', ' ')}  {r['reason']}" for r in rows]
    available, idx = select(labels, header="  pick a checkpoint  (↑/↓ then Enter, Esc to cancel):")
    if not available:
        return False
    if idx is None:
        return True  # cancelled
    chosen = rows[idx]

    action_labels = [
        "Restore the whole project",
        "Restore a single file",
        "Preview what changed first (diff)",
        "Cancel",
    ]
    _, action = select(action_labels, header=f"  checkpoint {chosen['short']} — {chosen['reason']}:")
    if action is None or action == 3:
        return True

    if action == 2:  # preview, then ask again
        ui.print(cps.diff(chosen["hash"]))
        _, confirm = select(["Restore now", "Cancel"], header="  ")
        if confirm != 0:
            return True
        action = 0

    file_arg = None
    if action == 1:
        try:
            file_arg = ui.console.input("  which file (relative path)?  › ").strip()
        except (EOFError, KeyboardInterrupt):
            return True
        if not file_arg:
            return True

    msg = cps.restore(chosen["hash"], file_arg)
    ui.notice(msg, style="green" if msg.startswith("Restored") else "yellow")
    return True


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
        "Set it up once for every project:\n"
        "  [bold]python -m kbcode model[/bold]   (picks provider + model, saves your key globally)\n"
        f"or add  [bold]{config.key_env}=your-key-here[/bold]  to a .env file — either in this "
        f"project, in the folder you launch kbcode from, or in [bold]{global_dir() / '.env'}[/bold].\n"
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


def _repl(config: Config, kb: KnowledgeBase, memory: Memory) -> None:
    agent = _build_agent(config, kb, memory)
    ui.banner(config.provider, config.model, config.project_dir, agent.mode.name)

    arg_options = {
        "/provider": list(PRESETS),
        "/mode": list(agent.modes),
        "/kb-check": ["--fix"],
    }
    cmd_input = make_input(COMMANDS, arg_options)  # None if no autocomplete available
    if cmd_input:
        ui.notice("type / for commands · Alt+V attaches an image")

    pending_images: list[dict] = []  # vision attachments waiting for the next turn

    while True:
        try:
            if cmd_input:
                user = cmd_input.read(ui.prompt_html(agent.mode.name))
            else:
                user = _read(ui.prompt(agent.mode.name))
        except (EOFError, KeyboardInterrupt):
            ui.print("\nbye 👋")
            return
        if cmd_input:  # collect any images attached with Alt+V during this prompt
            new_imgs = cmd_input.pop_images()
            if new_imgs:
                pending_images.extend(new_imgs)
                ui.notice(
                    f"📎 {len(pending_images)} image(s) attached — they'll go with your next message.",
                    style="green",
                )
        if not user:
            continue

        if user in ("/exit", "/quit"):
            ui.print("bye 👋")
            return
        if user == "/help":
            ui.help()
            continue
        if user == "/version":
            ui.print(f"kbcode v{__version__}  ·  update with  [bold]kbcode update[/bold]")
            continue
        if user == "/status":
            ui.status_line(
                config.provider, config.model, agent.mode.name,
                agent.context_tokens(), config.compact_threshold,
            )
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
            agent.provider = get_provider(config, ui)  # same chat, new model
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
        if user == "/todo":
            ui.todos(agent.tools.todos)
            continue
        if user == "/insights":
            ui.insights(agent.insights())
            continue
        if user in ("/agents", "/subagents"):
            ui.agents(agent.subagents)
            continue
        if user.split() and user.split()[0] == "/learn":
            topic = user.split(maxsplit=1)[1].strip() if len(user.split()) > 1 else ""
            scope = f" Focus the skill on: {topic}." if topic else ""
            agent.run(
                "Review what we accomplished in this conversation and capture it as a reusable "
                "skill by calling save_skill(): give it a short name, a one-line description, and "
                "clear markdown steps someone could follow to repeat it." + scope
            )
            continue
        if user == "/compact":
            agent.compact_now()
            continue
        if user.split() and user.split()[0] == "/rollback":
            cps = agent.tools.checkpoints
            parts = user.split()
            rows = cps.list_checkpoints()
            if len(parts) == 1:
                if not rows:
                    ui.notice("No checkpoints yet — they're taken automatically before file edits.", style="yellow")
                elif not _rollback_menu(cps, rows):
                    ui.print(format_checkpoints(rows))  # no interactive menu here (no TTY)
                continue
            if parts[1] == "diff":
                if len(parts) < 3 or not parts[2].isdigit() or not (1 <= int(parts[2]) <= len(rows)):
                    ui.error(f"usage: /rollback diff <n>  (1-{len(rows)})" if rows else "no checkpoints yet")
                    continue
                ui.print(cps.diff(rows[int(parts[2]) - 1]["hash"]))
                continue
            if not parts[1].isdigit() or not (1 <= int(parts[1]) <= len(rows)):
                ui.error(f"usage: /rollback <n> [file]  (1-{len(rows)})" if rows else "no checkpoints yet")
                continue
            file_arg = parts[2] if len(parts) > 2 else None
            msg = cps.restore(rows[int(parts[1]) - 1]["hash"], file_arg)
            ui.notice(msg, style="green" if msg.startswith("Restored") else "yellow")
            continue
        if user.split() and user.split()[0] == "/kb-check":
            if "--fix" in user.split() or "fix" in user.split()[1:]:
                fixed, unresolved = kb.fix_pointers(config.project_dir)
                if fixed:
                    ui.notice("Auto-fixed:", style="green")
                    ui.print("\n".join(f"- {f}" for f in fixed))
                if unresolved:
                    ui.notice("Still need attention:", style="yellow")
                    ui.print("\n".join(f"- {p}" for p in unresolved))
                if not fixed and not unresolved:
                    ui.notice("All kb/ pointers resolve — nothing to fix.", style="green")
            else:
                problems = kb.check_pointers(config.project_dir)
                if problems:
                    ui.notice("Pointer problems (run /kb-check --fix to repair):", style="yellow")
                    ui.print("\n".join(f"- {p}" for p in problems))
                else:
                    ui.notice("All kb/ pointers resolve.", style="green")
            continue
        if user == "/reset":
            agent.reset()
            ui.notice("chat cleared")
            continue
        if user.split() and user.split()[0] in ("/image", "/img"):
            from .images import grab_clipboard_image, load_image_file

            parts = user.split(maxsplit=1)
            arg = parts[1].strip().strip('"').strip("'") if len(parts) > 1 else ""
            img = load_image_file(arg) if arg else grab_clipboard_image()
            if img:
                pending_images.append(img)
                ui.notice(
                    f"📎 image attached ({len(pending_images)} pending) — type your question and it'll be sent.",
                    style="green",
                )
            elif arg:
                ui.error(f"couldn't read an image at: {arg}")
            else:
                ui.error(
                    "no image on the clipboard. Copy an image first (or use /image <path>). "
                    "Clipboard paste needs Pillow:  pip install Pillow"
                )
            continue
        if user.split() and user.split()[0] in ("/open", "/cd"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                ui.error('usage: /open "C:\\path\\to\\project"')
                continue
            target = Path(parts[1].strip().strip('"').strip("'")).expanduser()
            if not target.is_dir():
                ui.error(f"folder not found: {target}")
                continue
            config.project_dir = target.resolve()
            memory.close()
            kb = KnowledgeBase(config.kb_dir)
            memory = Memory(config.memory_db)
            _scaffold(config, kb)  # set it up (AGENT.md, kb/, .kbcode/) if new
            agent = _build_agent(config, kb, memory)
            ui.notice(f"now working on {config.project_dir}", style="green")
            ui.banner(config.provider, config.model, config.project_dir, agent.mode.name)
            continue

        # Guard a common mix-up: `init`/`model` are TERMINAL commands. Typed in
        # the chat they would otherwise be sent to the agent, which then explores
        # the wrong folder. Catch the command-like forms and explain instead.
        first = user.split()[0].lower()
        rest = user.split(maxsplit=1)[1] if len(user.split()) > 1 else ""
        command_like = not rest or rest[0] in "-/.~" or ":\\" in rest or rest.startswith("\\")
        if first in ("init", "model") and command_like:
            ui.notice(
                f"'{first}' is a terminal command, not a chat message — in chat, commands start with /.",
                style="yellow",
            )
            if first == "init":
                target = rest.strip().strip('"') or "<folder>"
                ui.print(
                    f'To switch to it right now, type:  [bold]/open "{target}"[/bold]\n'
                    "(that also sets it up). Or from the terminal:  "
                    f'[bold]python -m kbcode -C "{target}"[/bold]'
                )
            else:
                ui.print("To change the model, use  [bold]/model[/bold]  here, or  [bold]python -m kbcode model[/bold]  in the terminal.")
            continue

        try:
            with interrupt_on_escape():  # press Esc (or Ctrl-C) to stop this turn
                agent.run(user, images=pending_images or None)
        except KeyboardInterrupt:
            ui.notice("interrupted — back to the prompt.", style="yellow")
        except ProviderError as exc:
            ui.error(str(exc))
            if exc.hint:
                ui.notice(exc.hint)
        except Exception as exc:  # noqa: BLE001 - keep the REPL alive
            ui.error(str(exc))
        finally:
            pending_images.clear()  # consumed by this turn (or dropped on error)


def _take_dir(argv: list[str]) -> Path | None:
    """Pull a ``-C/--dir/--project <path>`` option out of argv, if present."""
    for flag in ("-C", "--dir", "--project"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv):
                value = argv[i + 1]
                del argv[i : i + 2]
                return Path(value).expanduser()
            argv.remove(flag)
    return None


def _take_images(argv: list[str]) -> list[dict]:
    """Pull every ``--image/-i <path>`` option out of argv and load it (one-shot)."""
    from .images import load_image_file

    images: list[dict] = []
    for flag in ("--image", "-i"):
        while flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                argv.remove(flag)
                break
            path = argv[i + 1]
            del argv[i : i + 2]
            img = load_image_file(path)
            if img:
                images.append(img)
            else:
                console.print(f"[yellow]Skipped (not a readable image):[/yellow] {path}")
    return images


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Version + update are handled before anything else: they need no project,
    # config, or API key.
    if any(f in argv for f in ("--version", "-v", "-V")):
        console.print(f"kbcode {__version__}")
        return 0
    if argv and argv[0] == "update":
        return _self_update()

    auto = False
    for flag in ("-y", "--yes"):
        if flag in argv:
            argv.remove(flag)
            auto = True

    images = _take_images(argv)  # one-shot vision attachments: --image/-i <path>

    # Which project to work on: -C <path>, else `init <path>`, else the cwd.
    project_dir = _take_dir(argv)
    if argv and argv[0] == "init" and len(argv) > 1 and project_dir is None:
        project_dir = Path(argv[1]).expanduser()
        del argv[1]
    if project_dir is not None and not project_dir.is_dir():
        console.print(
            f"[red]Folder not found:[/red] {project_dir}\n"
            "Pass an existing folder, e.g.  python -m kbcode -C \"C:\\path\\to\\project\""
        )
        return 1

    config = load_config(project_dir or Path.cwd())
    config.auto_approve = auto
    kb = KnowledgeBase(config.kb_dir)

    if argv and argv[0] == "init":
        _scaffold(config, kb)
        console.print(
            f"[green]Initialized[/green] {config.project_dir}\n"
            "Created AGENT.md, kb/, and .kbcode/.\n"
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
        if argv or images:  # one-shot: kbcode "do something" [--image pic.png]
            agent = _build_agent(config, kb, memory)
            with interrupt_on_escape():  # Esc / Ctrl-C stops the run
                agent.run(" ".join(argv), images=images or None)
        else:  # interactive chat
            _repl(config, kb, memory)
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted.[/yellow]")
        return 130
    except ProviderError as exc:
        console.print(f"[red]{exc}[/red]")
        if exc.hint:
            console.print(f"[dim]{exc.hint}[/dim]")
        return 1
    finally:
        memory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
