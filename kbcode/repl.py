"""The interactive chat loop (#2.1) — reads a line, dispatches slash
commands, or runs it as an agent turn. Split out of cli.py, which still owns
argv parsing, project setup, and the shared console/ui singletons + a few
helpers (_build_agent, _scaffold, _resume_agent, _session_picker,
_find_session, _require_key, _read) that this module imports from cli.py.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from . import __version__
from .agent import Agent
from .checkpoints import format_checkpoints
from .cli import (
    _build_agent,
    _find_session,
    _read,
    _require_key,
    _resume_agent,
    _scaffold,
    _session_picker,
    ui,
)
from .config import PRESETS, Config, persist_choice, persist_global_choice, load_model_cache, save_model_cache
from .interrupt import interrupt_on_escape
from .knowledge_base import KnowledgeBase
from .memory import Memory
from .prompt_input import make_input, select
from .provider import ProviderError, get_provider
from .sessions import export_markdown, lifetime_stats, list_sessions, search_sessions
from .ui import COMMANDS


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


def _model_completion_sources(config: Config):
    """Build the (``/provider``, ``/model``) autocomplete callables.

    ``/provider``'s first argument completes to preset names (with the current
    provider marked ●); its second — and ``/model``'s first — completes to that
    provider's live model ids, fetched with ``list_models()`` once per provider
    per session and cached. The cache persists to ``~/.kbcode/models/`` on disk
    so autocomplete is instant across sessions (no network delay on first keystroke).
    The fetch runs on the completer's background thread (see ``make_input``), so
    typing never blocks; a provider with no usable key falls back to the disk cache.
    Closures read ``config`` live, so ``/provider`` switches are picked up.
    """
    cache: dict[str, list[str]] = {}

    def models_for(name: str) -> list[str]:
        if name not in cache:
            # Start from disk cache so autocomplete is instant even offline.
            disk = load_model_cache(name)
            cache[name] = sorted(disk) if disk else []
            try:
                probe = replace(config)  # don't mutate the live config
                probe.use_provider(name)
                live = sorted(get_provider(probe).list_models())
                if live:
                    cache[name] = live
                    save_model_cache(name, live)
            except Exception:  # noqa: BLE001 - no key / offline → use whatever was cached
                pass
        return cache[name]

    def provider_args(args: list[str]) -> list[str] | list[tuple[str, str]]:
        if len(args) <= 1:
            # Show current provider with a ● marker in autocomplete meta.
            return [
                (name, "● current" if name == config.provider else "")
                for name in PRESETS
            ]
        if len(args) == 2:
            models = models_for(args[0])
            return [
                (m, "● current" if m == config.model else "")
                for m in models
            ]
        return []

    def model_args(args: list[str]) -> list[str] | list[tuple[str, str]]:
        if len(args) <= 1:
            models = models_for(config.provider)
            return [
                (m, "● current" if m == config.model else "")
                for m in models
            ]
        return []

    return provider_args, model_args


def _list_models(config: Config) -> None:
    """Fetch and print the model ids the current provider/key can use."""
    with ui.working("fetching available models…"):
        try:
            models = sorted(get_provider(config).list_models())
            from .config import save_model_cache
            if models:
                save_model_cache(config.provider, models)
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


def _ping(agent: Agent) -> None:
    """`/ping` — a cheap connectivity/auth check (#3.5): list models instead of
    running a full chat completion, so a stale/expired key surfaces before the
    user types a long prompt and waits for it to fail."""
    start = time.perf_counter()
    try:
        with ui.working("pinging provider…"):
            models = agent.provider.list_models()
        elapsed = time.perf_counter() - start
        provider_name = agent.provider.config.provider
        ui.notice(f"✓ {provider_name} reachable ({len(models)} model(s) visible) — {elapsed:.2f}s", style="green")
    except ProviderError as exc:
        ui.error(str(exc))
        if exc.hint:
            ui.notice(exc.hint, style="dim")
    except Exception as exc:  # noqa: BLE001 - surface any transport error, don't crash the REPL
        ui.error(f"ping failed: {exc}")


def _split_path_and_rest(text: str) -> tuple[str, str]:
    """Split ``"<path>" [rest]`` into ``(path, rest)`` — the path may be quoted
    (to allow spaces) or bare (split on the first whitespace)."""
    text = text.strip()
    if text[:1] in "\"'":
        quote = text[0]
        end = text.find(quote, 1)
        if end != -1:
            return text[1:end], text[end + 1 :].strip()
    parts = text.split(maxsplit=1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _read_multiline(read_line) -> str:
    """A bare ``\"\"\"`` line starts a multi-line block: keep reading (via
    ``read_line``) until a closing ``\"\"\"`` and return the lines joined with
    newlines. Any other first line is returned as-is — this is the one input
    path both the prompt_toolkit reader and the plain fallback share, so
    multi-line paste/typing works the same either way."""
    first = read_line()
    if first.strip() != '"""':
        return first
    lines: list[str] = []
    while True:
        line = read_line()
        if line.strip() == '"""':
            break
        lines.append(line)
    return "\n".join(lines)


def repl(config: Config, kb: KnowledgeBase, memory: Memory, agent: Agent | None = None) -> None:
    """The interactive chat loop: read a line, dispatch slash commands, or run it as a turn."""
    agent = agent or _build_agent(config, kb, memory)
    ui.banner(config.provider, config.model, config.project_dir, agent.mode.name)

    provider_args, model_args = _model_completion_sources(config)
    arg_options = {
        "/provider": provider_args,  # provider names, then that provider's models
        "/model": model_args,  # current provider's models
        "/mode": list(agent.modes),
        "/kb-check": ["--fix"],
        "/resume": [r["id"] for r in list_sessions(config.sessions_dir)],
    }
    cmd_input = make_input(COMMANDS, arg_options, history_file=config.history_file)  # None if no autocomplete available
    if cmd_input:
        ui.notice('type / for commands · Alt+V attaches an image · """ on its own line starts/ends a multi-line message')

    pending_images: list[dict] = []  # vision attachments waiting for the next turn
    pending_notes: list[str] = []  # e.g. /video descriptions, prepended to the next turn

    while True:
        try:
            # Context bar reflects the size *before* this turn — cheap (no
            # tokenizing), and close enough to tell the user how close they
            # are to auto-compaction without them running /status.
            ctx_tokens, ctx_limit = agent.context_tokens(), config.compact_threshold
            if cmd_input:
                user = _read_multiline(
                    lambda: cmd_input.read(ui.prompt_html(agent.mode.name, ctx_tokens, ctx_limit))
                )
            else:
                user = _read_multiline(lambda: _read(ui.prompt(agent.mode.name, ctx_tokens, ctx_limit)))
        except (EOFError, KeyboardInterrupt):
            ui.print("\nbye 👋")
            agent.close()
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
            agent.close()
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
        if user == "/ping":
            _ping(agent)
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
            agent.close()
            agent = _build_agent(config, kb, memory)  # new provider -> fresh chat
            persist_global_choice(config)  # cross-project default — all projects see this change
            ui.notice(f"switched → {config.provider} / {config.model}", style="green")
            continue
        if user in ("/model", "/models"):
            _list_models(config)
            continue
        if user.startswith("/model"):
            config.model = user.split(maxsplit=1)[1].strip()
            agent.provider = get_provider(config, ui)  # same chat, new model
            persist_global_choice(config)  # cross-project default — all projects see this change
            ui.notice(f"model → {config.model}", style="green")
            continue
        if user == "/kb":
            notes = kb.list_notes()
            ui.print("\n".join(f"- kb/{n}" for n in notes) or "(knowledge base is empty)")
            continue
        if user == "/memory":
            rows = memory.recent()
            ui.print("\n".join(f"- [{r['kind']}] {r['content']}" for r in rows) or "(memory is empty)")
            continue
        if user == "/memory-prune" or (user.split() and user.split()[0] == "/memory-prune"):
            parts = user.split(maxsplit=1)
            days = float(parts[1].strip()) if len(parts) > 1 and parts[1].strip().replace(".", "", 1).isdigit() else None
            result = memory.prune(older_than_days=days)
            total = result["duplicates_removed"] + result["aged_removed"]
            if total == 0:
                ui.notice("Nothing to prune.")
            else:
                msg = f"pruned {result['duplicates_removed']} duplicate memor{'y' if result['duplicates_removed'] == 1 else 'ies'}"
                if days is not None:
                    msg += f", {result['aged_removed']} older than {days:g}d"
                ui.notice(msg + ".", style="green")
            continue
        if user == "/skills":
            rows = memory.list_skills()
            ui.print("\n".join(f"- {r['name']}: {r['description']}" for r in rows) or "(no skills yet)")
            continue
        if user == "/todo":
            ui.todos(agent.tools.todos)
            continue
        if user == "/insights":
            ui.insights(agent.insights(), lifetime_stats(config.sessions_dir))
            continue
        if user == "/cost":
            ui.cost(agent.insights())
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
        if user == "/sessions" or (user.split() and user.split()[0] == "/sessions"):
            parts = user.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():  # /sessions <query> -> full-text search (#8.1)
                query = parts[1].strip()
                ui.session_search_results(search_sessions(config.sessions_dir, query), query)
            else:
                rows = list_sessions(config.sessions_dir)
                ui.sessions(rows, current_id=agent.session.id if agent.session else None)
            continue
        if user == "/export" or (user.split() and user.split()[0] == "/export"):
            parts = user.split(maxsplit=1)
            wanted = parts[1].strip() if len(parts) > 1 else ""
            if wanted:
                row = _find_session(list_sessions(config.sessions_dir), wanted)
                if row is None:
                    ui.error(f"no saved session matches '{wanted}'. Try /sessions to list them.")
                    continue
                target_path, export_id = row["path"], row["id"]
            elif agent.session:
                target_path, export_id = agent.session.path, agent.session.id
            else:
                ui.notice("No active session to export.", style="yellow")
                continue
            out_path = config.project_dir / f"kbcode-session-{export_id}.md"
            out_path.write_text(export_markdown(target_path), encoding="utf-8")
            ui.notice(f"Exported to {out_path}", style="green")
            continue
        if user.split() and user.split()[0] == "/resume":
            parts = user.split(maxsplit=1)
            current_id = agent.session.id if agent.session else None
            rows = [r for r in list_sessions(config.sessions_dir) if r["id"] != current_id]
            if len(parts) > 1 and parts[1].strip():
                chosen = _find_session(rows, parts[1].strip())
                if chosen is None:
                    ui.error(f"no saved session matches '{parts[1].strip()}'. Try /sessions to list them.")
                    continue
            elif not rows:
                ui.notice("No other saved sessions yet.", style="yellow")
                continue
            else:
                chosen = _session_picker(rows)
                if chosen is None:
                    continue
            agent.close()
            agent = _resume_agent(config, kb, memory, chosen)
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
        if user.split() and user.split()[0] == "/video":
            from . import vision_fallback
            from .videos import load_video_file

            parts = user.split(maxsplit=1)
            rest = parts[1].strip() if len(parts) > 1 else ""
            if not rest:
                ui.error('usage: /video "<path>" [question]')
                continue
            path, question = _split_path_and_rest(rest)
            vid = load_video_file(path)
            if not vid:
                ui.error(f"couldn't read a video at: {path} (check the path, format, or size)")
                continue
            with ui.working("🎬 describing video with an auxiliary vision model…"):
                description = vision_fallback.describe_video(vid, question, config=config)
            if description is None:
                ui.error(
                    "No auxiliary vision model configured for video analysis — none of "
                    "kbcode's providers accept video natively, and no ANTHROPIC_API_KEY / "
                    "GEMINI_API_KEY / OPENAI_API_KEY / KBCODE_VISION_API_KEY was usable "
                    "(Anthropic can't do video — set one of the others)."
                )
                continue
            pending_notes.append(f"[video: {path}]\n{description}")
            ui.notice(
                f"🎬 video described ({len(pending_notes)} pending) — type your question and it'll be sent.",
                style="green",
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
            agent.close()
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

        turn_input = "\n\n".join(pending_notes + [user]) if pending_notes else user
        try:
            with interrupt_on_escape():  # press Esc (or Ctrl-C) to stop this turn
                agent.run(turn_input, images=pending_images or None)
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
            pending_notes.clear()
