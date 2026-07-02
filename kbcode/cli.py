"""Command-line entry point: argv parsing, project setup, and the shared
console/ui singletons + helpers that both the one-shot path here and the
interactive REPL (repl.py) need. The REPL loop itself lives in repl.py, and
the `kbcode model` wizard in wizard.py — both import their shared
infrastructure (console, ui, _read, _build_agent, ...) from this module via
a deferred import inside main() (see the "model"/interactive branches below),
which avoids a circular import since this module never imports them at its
own top level.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console

from . import __version__
from .agent import Agent
from .config import Config, global_dir, load_config
from .interrupt import interrupt_on_escape
from .knowledge_base import AGENT_MD_TEMPLATE, KnowledgeBase
from .logs import setup_logging
from .memory import Memory
from .modes import load_modes
from .permissions import Permissions
from .prompt_input import select
from .prompts import build_system_prompt, load_prompt_fragments
from .provider import ProviderError, get_provider
from .sessions import SessionRecorder, list_sessions, load_session
from .subagents import load_subagents
from .tools import Tools
from .tools.mcp import MCPManager, parse_mcp_configs
from .ui import TerminalUI

console = Console()
ui = TerminalUI(console)

# Where releases live, so `kbcode update` can pull the latest (GitHub install).
_REPO_URL = "https://github.com/johnmungandiall/kbcode"
_GIT_TARGET = f"git+{_REPO_URL}.git"


def _self_update() -> int:
    """`kbcode update` — upgrade the install in place from GitHub.

    Two pip steps on purpose. A plain ``pip install --upgrade git+URL`` is a
    silent no-op whenever ``__version__`` has not changed: pip sees the same
    version already installed and reports "Requirement already satisfied",
    so any fix pushed to GitHub without a version bump never reaches users
    (they stay on stale code even though ``kbcode update`` "succeeded"). The
    first step still runs a normal upgrade so any new/bumped dependencies get
    pulled in; the second force-reinstalls kbcode itself (``--no-deps`` to
    avoid re-fetching every dependency, ``--no-cache-dir`` so pip rebuilds
    from the current GitHub HEAD instead of serving a cached same-version
    wheel). That second step is what actually guarantees the latest code
    lands regardless of the version string.
    """
    console.print(f"[cyan]Updating kbcode from {_REPO_URL} …[/cyan]")

    if os.name == "nt":
        console.print(
            "[yellow]Windows note: If you get 'file is being used by another process' error, "
            "completely close this Command Prompt and run 'kb update' again in a fresh window.[/yellow]"
        )
        console.print(
            "[yellow]You can also try this command in a new window:[/yellow]"
        )
        console.print(
            f"[cyan]python -m pip install --upgrade --force-reinstall --no-deps --no-cache-dir {_GIT_TARGET}[/cyan]"
        )

    steps = (
        [sys.executable, "-m", "pip", "install", "--upgrade", _GIT_TARGET],
        [sys.executable, "-m", "pip", "install", "--upgrade",
         "--force-reinstall", "--no-deps", "--no-cache-dir", _GIT_TARGET],
    )
    try:
        for cmd in steps:
            proc = subprocess.run(cmd, check=False)
            if proc.returncode != 0:
                console.print("[yellow]pip reported a problem (see its output above).[/yellow]")
                return proc.returncode
    except Exception as exc:  # noqa: BLE001 - surface any launch failure cleanly
        console.print(f"[red]Update failed:[/red] {exc}")
        return 1
    console.print("[green]Updated.[/green]  Check with  [bold]kbcode --version[/bold]")
    return 0


def _scaffold(config: Config, kb: KnowledgeBase) -> None:
    """Create AGENT.md, standing-orders.md, the sample subagent, and kb/ — all idempotent."""
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


def _build_agent(config: Config, kb: KnowledgeBase, memory: Memory, *, resume_id: str | None = None) -> Agent:
    """Wire up a fresh Agent: tools, system prompt (kb + skills + memory + AGENT.md + standing orders), provider, modes, subagents, and its session recorder."""
    ui.root = config.project_dir  # so file tool-lines show the full path
    perm = Permissions(auto_approve=config.auto_approve, ui=ui)
    tools = Tools(config, memory, kb, perm)
    if config.mcp:
        manager = MCPManager()
        manager.start_all(parse_mcp_configs(config.mcp), warn=lambda m: ui.notice(m, style="yellow"))
        tools.mcp = manager
        # Backstop for crash paths; the normal path is Agent.close() -> stop_all
        # (idempotent), which /exit, /provider and /open all go through.
        atexit.register(manager.stop_all)
        if manager.clients:
            ui.notice(
                "MCP: " + ", ".join(f"{n} ({c} tool{'s' if c != 1 else ''})" for n, c in manager.summary())
            )
    agent_md = config.agent_md.read_text(encoding="utf-8") if config.agent_md.exists() else ""
    orders = ""
    if config.standing_orders_file.exists():
        raw = config.standing_orders_file.read_text(encoding="utf-8")
        # Ignore the untouched scaffold (its examples are not real orders).
        if raw.strip() and raw.strip() != _STANDING_ORDERS_TEMPLATE.strip():
            orders = raw
    system = build_system_prompt(
        kb.read_all(), memory.list_skills(), memory.recent(), agent_md, orders,
        load_prompt_fragments(config.prompts_dir),
        project_dir=config.project_dir,
    )
    agent = Agent(
        system,
        get_provider(config, ui),
        tools,
        compact_threshold=config.compact_threshold,
        ui=ui,
        modes=load_modes(config.kbcode_dir / "modes"),
        subagents=load_subagents(config.kbcode_dir / "agents"),
        max_steps=config.max_steps,
    )
    # Claude Code / Hermes idea: persist every chat so it can be picked back up
    # with --continue / --resume / /resume, and rolled into /insights later.
    agent.session = SessionRecorder(
        config.sessions_dir, config.project_dir, config.provider, config.model,
        agent.mode.name, resume_id=resume_id,
    )
    return agent


_SESSION_ID_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}$")


def _resume_agent(config: Config, kb: KnowledgeBase, memory: Memory, row: dict) -> Agent:
    """Rebuild an Agent from a saved session's transcript (--continue / --resume / /resume)."""
    meta, messages = load_session(row["path"])

    # "raw" assistant payloads are provider-shaped (see provider.py), so replay
    # only works cleanly under the same provider/model the session was
    # recorded with — restore it (Claude Code preserves model across resume),
    # falling back to the current one if it isn't configured here.
    recorded_provider = meta.get("provider")
    if recorded_provider and recorded_provider != config.provider:
        prev_provider, prev_model = config.provider, config.model
        config.use_provider(recorded_provider, model=meta.get("model"))
        if not config.api_key:
            config.use_provider(prev_provider, model=prev_model)
            ui.notice(
                f"Session was recorded with provider '{recorded_provider}', which isn't "
                f"configured here — resuming under {config.provider}/{config.model} instead; "
                "older turns may not replay if you send another message.",
                style="yellow",
            )
    elif meta.get("model"):
        config.model = meta["model"]

    agent = _build_agent(config, kb, memory, resume_id=meta.get("id"))
    agent.messages = messages
    if meta.get("mode") in agent.modes:
        agent.mode = agent.modes[meta["mode"]]
    turns = row.get("turns", 0)
    ui.notice(
        f"↳ resumed session {meta.get('id')} — \"{row.get('title') or '(no messages yet)'}\" "
        f"({turns} turn{'s' if turns != 1 else ''})",
        style="cyan",
    )
    return agent


def _session_picker(rows: list[dict]) -> dict | None:
    """Arrow-key picker for --resume / /resume with no id given. Returns the
    chosen row, or None if cancelled / no interactive menu is available here."""
    labels = [
        f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['started_at'])) if r['started_at'] else '?':<16}  "
        f"{(r['title'] or '(no messages yet)')[:48]:<48}  {r['turns']} turn(s)"
        for r in rows
    ]
    available, idx = select(labels, header="  pick a session to resume  (↑/↓ then Enter, Esc to cancel):")
    if not available:
        ui.sessions(rows)
        ui.notice("No interactive menu here — use  /resume <n or id>  instead.")
        return None
    if idx is None:
        return None
    return rows[idx]


def _find_session(rows: list[dict], token: str) -> dict | None:
    """Resolve a /resume argument: a 1-based list index, a full id, or an id prefix."""
    if token.isdigit() and 1 <= int(token) <= len(rows):
        return rows[int(token) - 1]
    return next((r for r in rows if r["id"] == token or r["id"].startswith(token)), None)


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


def _take_flag(argv: list[str], names: tuple[str, ...]) -> bool:
    """Pull a boolean flag (any of its spellings) out of argv."""
    found = False
    for flag in names:
        while flag in argv:
            argv.remove(flag)
            found = True
    return found


def _take_resume(argv: list[str]) -> tuple[bool, str | None]:
    """Pull ``--resume [session-id]`` out of argv (the Claude Code idea).

    The id is only consumed if it looks like one of our generated session ids
    (``YYYYMMDD_HHMMSS_xxxxxx``) — otherwise ``--resume`` is bare (interactive
    picker) and the rest of argv is still the one-shot prompt, if any.
    """
    if "--resume" not in argv:
        return False, None
    i = argv.index("--resume")
    del argv[i]
    if i < len(argv) and _SESSION_ID_RE.match(argv[i]):
        return True, argv.pop(i)
    return True, None


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


def _take_video(argv: list[str]) -> list[str]:
    """Pull every ``--video <path>`` option out of argv (one-shot). Returns the
    paths — call ``_describe_videos`` on them once ``load_config`` has loaded
    any ``.env``, since the auxiliary vision fallback needs its key visible."""
    paths: list[str] = []
    while "--video" in argv:
        i = argv.index("--video")
        if i + 1 >= len(argv):
            argv.remove("--video")
            break
        paths.append(argv[i + 1])
        del argv[i : i + 2]
    return paths


def _describe_videos(paths: list[str], config: Config) -> list[str]:
    """Load + describe each video path via the auxiliary vision fallback —
    kbcode has no native video path, so this always resolves straight to
    text. Returns the description notes."""
    from . import vision_fallback
    from .videos import load_video_file

    notes: list[str] = []
    for path in paths:
        vid = load_video_file(path)
        if not vid:
            console.print(f"[yellow]Skipped (not a readable video):[/yellow] {path}")
            continue
        console.print(f"[dim]🎬 describing video with an auxiliary vision model: {path}[/dim]")
        description = vision_fallback.describe_video(vid, "", config=config)
        if description is None:
            console.print(
                "[yellow]No auxiliary vision model configured — set ANTHROPIC_API_KEY / "
                "GEMINI_API_KEY / OPENAI_API_KEY / KBCODE_VISION_API_KEY (Anthropic can't "
                f"do video — set one of the others).[/yellow] Skipped: {path}"
            )
            continue
        notes.append(f"[video: {path}]\n{description}")
    return notes


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse flags, resolve the project + config, then either
    run one-shot, resume/continue a session, or drop into the REPL."""
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

    do_continue = _take_flag(argv, ("--continue", "-c"))  # resume the latest saved session
    want_resume, resume_id = _take_resume(argv)  # --resume [id] -> a specific or picked session

    images = _take_images(argv)  # one-shot vision attachments: --image/-i <path>
    video_paths = _take_video(argv)  # one-shot video attachments: --video <path>

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
    try:
        # The README promises global data lives in ~/.kbcode; make sure the
        # folder actually exists from the very first run (a legacy project
        # whose state_dir stays project-local would otherwise never create it).
        global_dir().mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # unwritable home — every consumer of global_dir() copes already
    setup_logging(config.state_dir)  # quiet on-disk trace for field debugging (#5)
    logging.getLogger(__name__).info(
        "kbcode %s starting — provider=%s model=%s dir=%s",
        __version__, config.provider, config.model, config.project_dir,
    )
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
        from .wizard import model_wizard  # deferred: avoids a module-level import cycle

        return model_wizard(config)

    _scaffold(config, kb)
    if not _require_key(config):
        return 1

    # Describe any --video attachments now that .env has been loaded by
    # load_config above (the fallback needs its key visible).
    video_notes = _describe_videos(video_paths, config) if video_paths else []

    memory = Memory(config.memory_db)
    agent: Agent | None = None
    try:
        if do_continue or want_resume:
            rows = list_sessions(config.sessions_dir)
            if not rows:
                console.print("[yellow]No saved sessions yet for this project — starting a new one.[/yellow]")
            elif resume_id:
                row = _find_session(rows, resume_id)
                if row is None:
                    console.print(f"[red]No saved session matches '{resume_id}'.[/red]")
                    return 1
                agent = _resume_agent(config, kb, memory, row)
            elif do_continue:
                agent = _resume_agent(config, kb, memory, rows[0])
            else:  # bare --resume -> interactive picker
                row = _session_picker(rows)
                if row is None:
                    return 0
                agent = _resume_agent(config, kb, memory, row)

        if argv or images or video_notes:  # one-shot: kbcode "do something" [--image pic.png]
            agent = agent or _build_agent(config, kb, memory)
            prompt_text = "\n\n".join(video_notes + [" ".join(argv)]) if video_notes else " ".join(argv)
            with interrupt_on_escape():  # Esc / Ctrl-C stops the run
                agent.run(prompt_text, images=images or None)
        else:  # interactive chat
            from .repl import repl  # deferred: avoids a module-level import cycle

            repl(config, kb, memory, agent=agent)
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted.[/yellow]")
        return 130
    except ProviderError as exc:
        console.print(f"[red]{exc}[/red]")
        if exc.hint:
            console.print(f"[dim]{exc.hint}[/dim]")
        return 1
    finally:
        if agent is not None:
            agent.close()
        memory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
