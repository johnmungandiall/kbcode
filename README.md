# 🤖 kbcode

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Version](https://img.shields.io/badge/version-1.11.1-2ea44f)
![Platforms](https://img.shields.io/badge/Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-555)
![Models](https://img.shields.io/badge/Claude%20%2B%20any%20OpenAI--compatible-8A2BE2)
[![CI](https://github.com/johnmungandiall/kbcode/actions/workflows/ci.yml/badge.svg)](https://github.com/johnmungandiall/kbcode/actions/workflows/ci.yml)

**A small AI coding agent you run in your terminal.** 💬 Ask in plain language —
it reads your code, writes files, and runs commands for you, using *your own* AI key.

> [!TIP]
> First time? Jump straight to **[🚀 Quick start](#-quick-start)** — three steps and you're chatting.

It blends five ideas, each borrowed from a well-known agent:

| 🧩 Idea | 📦 From | ✨ What it gives you |
|------|------|-------------------|
| **🛠️ Hands** — reads/writes files, runs commands | Claude Code | The agent actually does the work, not just talks. |
| **🧠 Memory + skills** — remembers across sessions | Hermes agent | It recalls past decisions and reuses how-tos it learned. |
| **📚 Knowledge base** — short `kb/` notes | claude-kb | It understands your project cheaply, without re-scanning every file. |
| **🎭 Modes** — code / architect / ask / debug | Kilo Code | One agent with focused personalities and the right guardrails. |
| **🔧 Tool-call repair** — fixes malformed calls, recovers ones written as plain text | openclaw | Weaker models self-correct instead of hard-failing or stalling. |

It works with **Claude** (default) or **any OpenAI-compatible model** — see
[🧠 Choose your AI model](#-choose-your-ai-model).

## 🚀 Quick start

Three steps and you're chatting. 🎉

### 1️⃣ Install

Install Python 3.10+, then:

```bash
pip install git+https://github.com/johnmungandiall/kbcode.git
```

That gives you a real `kbcode` command you can run from any folder (also
aliased as the shorter `kb`). Check it:

```bash
kbcode --version
```

### 2️⃣ Configure your AI model 🔑

Run the setup wizard — **once**, and it's saved for every project:

```bash
kbcode model
```

It asks you three easy things:

1. **Which provider?** — Claude, OpenAI, Gemini, DeepSeek, OpenRouter… (type the number)
2. **Your API key** — paste it in
3. **Which model?** — it fetches the list for you; pick a number

> [!IMPORTANT]
> You need an API key from your provider. For Claude, get one at
> **<https://console.anthropic.com/>**. Your key is saved to `~/.kbcode` on your
> own computer — never shared.

> [!NOTE]
> Prefer not to use the wizard? See [🧠 Choose your AI model](#-choose-your-ai-model)
> to set it by hand, or to switch models later from inside the chat.

### 3️⃣ Run it on your project ▶️

```bash
cd path/to/your/project
kbcode init        # one-time: creates AGENT.md + the kb/ notes folder
kb                 # start chatting (short for `kbcode` — either works)
```

> [!TIP]
> That's it! Ask in plain language — *"add input validation to login() and run the
> tests"* — approve the file writes / commands when it asks, and press **Esc** any
> time to stop the agent.

### 🧰 Other ways to install

- **Just try it (no install):** `pip install -r requirements.txt`, then run
  `python -m kbcode` everywhere this guide says `kbcode`.
- **For development (editable):** clone the repo and run `pip install -e .` from
  it — your code edits take effect immediately.

### ⌨️ All terminal commands

Run these in your shell. (`kb` works everywhere `kbcode` does — it's the same
command under a shorter name. Use `python -m kbcode` instead if you chose the
no-install option.)

| Command | What it does |
|---|---|
| `kb` | Start the chat on the current folder. |
| `kbcode "do the thing"` | Run one task and exit (one-shot). |
| `kbcode -y "do the thing"` | One-shot, but auto-approve every write & command (no y/N prompts). |
| `kbcode -c` / `kbcode --continue` | Reopen the most recent saved chat for this folder. |
| `kbcode --resume` | Pick a past chat from a list and reopen it (`--resume <id>` skips the picker). |
| `kbcode init` | Set up the current folder (`AGENT.md` + `kb/`). Target another with `kbcode init "C:\path"`. |
| `kbcode model` | Pick provider + key + model interactively; persists so the next run in the folder uses it (global default + project override). |
| `kbcode -C "C:\path"` | Work on another project folder without `cd` (also `--dir` / `--project`). |
| `kbcode update` | Update to the latest version from GitHub. |
| `kbcode --version` | Show the version (also `-v`, `-V`, or `/version` in chat). |

### 📁 Work on another project

By default kbcode works on the folder you launch it in. To point it at a
different project without `cd`-ing there, use `-C` (also `--dir` / `--project`):

```
python -m kbcode -C "C:\path\to\other-project" init   # one-time setup
python -m kbcode -C "C:\path\to\other-project"         # start chatting on it
```

Already in a chat? Switch live with **`/open "C:\path\to\other-project"`** — it
re-roots the session, sets the folder up if needed, and keeps your model + key.
(Tip: if you type `init <path>` in the chat by mistake, kbcode notices and shows
you the right command.)

Your provider, model and API key are looked up from the project, then the folder
you launched from, then a global `~/.kbcode` — so once configured (e.g. via
`python -m kbcode model`, which saves globally), `-C` works on any project
without re-entering your key there. A project can still override with its own
`.env` / `.kbcode/settings.json`.

### 🖥️ The terminal

kbcode runs as a chat terminal in the style of Claude Code / Hermes: a header
banner with your provider and model, and answers rendered as markdown. Tool
calls show live as a readable verb + the full resolved path — `⏺ Read D:\proj\kbcode\agent.py`,
`⏺ Run $ pytest`, `⏺ Delegate → code-explorer` — each with an indented `↳`
result preview (or a red `✗` on error). After every turn a dim footer reports
`3 actions · ~1.5k tokens · 4.5s`, and `/status` shows a context-fullness bar
versus the auto-compact threshold. Approval prompts for risky actions are a
**selectable Yes / Always / No menu** (↑/↓ + Enter, or press 1/2/3) — Claude Code
style — falling back to a typed `y/N/a` prompt where no interactive menu is available.

While a step is running, its spinner counts up so a slow tool call or model
reply never looks stalled — e.g. `running… 3.2s  (total 8.1s)  (Esc to interrupt)` —
showing both the current step's elapsed time and a running total for the whole
turn. Press **Esc** (or Ctrl-C) any time to interrupt and drop back to the prompt.

Type `/` and a **popup menu of commands** appears and filters as you type
(arrow keys + Tab/Enter to pick); after `/provider` it suggests provider names,
after `/mode` mode names, and after `/kb-check` the `--fix` flag. This needs
`prompt_toolkit` (in `requirements.txt`); without it, commands still work by
typing them in full. Input history persists across sessions (in the project's
`~/.kbcode/projects/<slug>/history`),
so **↑/↓** recall prompts from earlier chats too, not just this one.

**Multi-line messages:** type a bare `"""` on its own line to start one, type
your lines, then `"""` again on its own line to send — handy for pasting a
longer request or a multi-paragraph error message.

### 🖼️ Images (vision)

Show the agent a screenshot or a picture:

- **📋 From your clipboard — press `Alt+V`.** Copy any image (e.g. a screenshot),
  press **Alt+V** in the chat, then type your question and Enter. The bottom bar
  shows `📎 1 image attached`.
- **📁 From a file — `/image <path>`** (or just `/image` to grab the clipboard):
  ```text
  /image C:\Users\me\Pictures\error.png
  what does this error mean?
  ```
- **⚡ One-shot — `--image`:** `kbcode --image error.png "what's wrong here?"`

> [!IMPORTANT]
> Best on a **vision-capable model** (Claude, GPT-4o, Gemini…) — the image is sent
> straight into your conversation. On a model without vision (e.g. many MiMo /
> custom-endpoint routes), kbcode automatically **falls back**: it describes the
> image with an auxiliary vision model (the Hermes idea) and hands your model
> that description as text instead of failing outright. It auto-detects a route
> from `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` (or a genuinely
> OpenRouter-routed main provider) — set `KBCODE_VISION_API_KEY` to override —
> see `.env.example`. Clipboard paste needs Pillow — it's installed automatically
> with kbcode, or `pip install Pillow`.

> [!WARNING]
> **Alt+V does nothing?** First make sure you're on the latest version
> (`kbcode update`, then `kbcode --version` should show ≥ 1.1.1). When it fires
> you'll see `📎 image attached`. If your terminal swallows Alt+V (some consoles
> do), just use **`/image`** instead — it always works.

### 🎬 Video

None of kbcode's providers accept video natively, so `/video` always routes
through the same auxiliary vision fallback used for non-vision images above —
it describes the video as text, then that description (not the raw video) is
what your model actually sees:

```text
/video C:\clips\demo.mp4
what's going wrong in this recording?
```

- **⚡ One-shot — `--video`:** `kbcode --video demo.mp4 "what's wrong here?"`
- Supports mp4, webm, mov, avi, mkv, mpeg (≤ 30 MB). Same auto-detected fallback
  route as images above — except Claude/Anthropic can't do video at all, so
  video specifically needs `GEMINI_API_KEY` / `OPENAI_API_KEY` / a genuinely
  OpenRouter-routed provider / `KBCODE_VISION_API_KEY`.

### 🎭 Modes (the Kilo Code idea)

One agent, several focused personalities. Each mode pairs a short instruction
with a set of allowed tools, so you get the right behaviour *and* the right
guardrails:

| Mode | What it's for | Can edit / run? |
|------|---------------|-----------------|
| `code` | implement and edit code (default) | yes |
| `architect` | plan and design first | no — read-only on code (can write notes) |
| `ask` | answer questions about the project | no — pure read-only |
| `debug` | find the root cause, then fix | yes |

Switch any time with `/mode architect` (or `/mode` to list them). The popup
completes mode names after `/mode`. Add your own modes as markdown files in
`.kbcode/modes/` — `description:` and `tools:` (e.g. `read, notes`) frontmatter
plus a body of instructions; the filename becomes the mode name.

### ⌨️ Chat commands

Type `/` in the chat to see them all (with a popup menu). Grouped:

Session:
- `/help` — show the command table (grouped)
- `/version` — show the kbcode version
- `/status` — provider, model, mode, and a context-fullness bar
- `/ping` — quick connectivity/auth check for the current provider (lists models; no chat call)
- `/open <folder>` — switch to working on another project folder
- `/insights` — tokens used and estimated cost (this chat + all saved sessions)
- `/cost` — one-line cost summary — `model · tokens · $` (see `/insights` for detail)
- `/compact` — summarize earlier chat to free up context
- `/rollback` — undo AI edits from an auto-saved checkpoint
- `/diff [n]` — show what the AI changed since a checkpoint (no `n` = newest)
- `/sessions [query]` — list past chat sessions, or full-text search them for a query
- `/export [id]` — export a session (current, or by id) as a markdown file
- `/resume [id]` — resume a past session (no id = pick from a list)
- `/reset` — clear the current chat (memory and kb are kept; starts a fresh saved session)
- `/exit` — quit

Knowledge & memory:
- `/kb` — list knowledge-base notes
- `/kb-check [--fix]` — check `path:line` pointers in `kb/` (with `--fix`, relocate drifted ones by symbol)
- `/memory` — show recent long-term memory
- `/memory-prune [days]` — remove duplicate memories (and, if given, anything older than `[days]`)
- `/skills` — list learned skills
- `/learn [topic]` — save what we just did as a reusable skill

Planning & agents:
- `/todo` — show the agent's current task checklist
- `/agents` — list available subagents (`.kbcode/agents/`)

Models & modes:
- `/mode [name]` — switch mode: code / architect / ask / debug (no name = list)
- `/provider [name] [model]` — switch provider (no name = list them)
- `/model [id]` — switch model (no id = list this provider's models)

### 🧩 Planning, subagents, and what it learns

- **Todos** — for a multi-step job the agent keeps a checklist (the `manage_todos`
  tool); see it any time with `/todo`. ✓ done · ◐ in progress · ○ pending.
- **Subagents** — heavy exploration can be delegated to a specialist that runs in
  its **own** context window and returns just a summary, so the main chat stays
  lean. They live as markdown files in `.kbcode/agents/*.md` (a read-only
  `code-explorer` is created for you); list them with `/agents`. Same frontmatter
  as modes (`description:`, `tools:`) plus a body of instructions.
- **Insights** — `/insights` reports requests, input/output tokens, and an
  estimated USD cost for this session (cost is approximate; unknown models show
  tokens only).
- **Learn** — `/learn` (optionally `/learn <topic>`) turns what you just did into a
  reusable skill, saved to memory and listed by `/skills`.

### 📌 Standing orders (always-on instructions)

Anything you write in `.kbcode/standing-orders.md` is added to the agent's
instructions at the **start of every session** — e.g. "always run the tests
after changing code" or "reply in plain language." `init` creates a commented
template; leave it untouched (or empty) to disable.

Prefer splitting instructions across files instead of one growing file? Drop
`.md` files in `.kbcode/prompts/` — they're concatenated in **sorted filename
order** and appended right after standing orders, e.g. `10-style.md`,
`20-testing.md`. Optional; nothing is created there automatically.

### 📜 Session history (the Claude Code + Hermes idea)

Every chat is saved as it happens to `~/.kbcode/projects/<slug>/sessions/<id>.jsonl`
— one line
per message, so a crash or a closed terminal loses at most the in-flight one.
Pick it back up later:

- **`kbcode -c` / `--continue`** — reopen the most recent chat for this folder.
- **`kbcode --resume`** — pick from a list of past chats (`--resume <id>` jumps
  straight to one, no picker).
- **`/sessions`** and **`/resume [id]`** — same thing without leaving the chat.

Resuming restores the provider, model, and mode that chat was using, and
`/insights` rolls every saved session into an all-time token/cost total —
not just the one you're in. `/reset` starts a fresh saved session rather than
erasing history; deleting the `sessions/` folder is always safe, it just forgets
past chats.

### 💸 Long sessions stay cheap (auto-compaction)

When a chat grows long, kbcode automatically summarizes the older middle of the
conversation into a short recap and keeps going — so it doesn't slow down, get
expensive, or overflow the model's context window. (This is the Hermes idea.)
Tune it with `KBCODE_COMPACT_TOKENS` in `.env` (`0` turns it off), or run
`/compact` yourself any time.

## ⚙️ How it works

```
your request
     │
     ▼
  ┌─────────────────────────────── Agent loop ───────────────────────────────┐
  │  Claude (claude-opus-4-8)  ──asks for──▶  tools  ──results──▶  back to Claude │
  └────────────────────────────────────────────────────────────────────────────┘
     │ tools:
     │   read_file / write_file / edit_file / list_dir / search_code / run_command
     │   kb_read / kb_search / kb_write   (knowledge base — claude-kb idea)
     │   remember / recall / save_skill   (memory + skills — Hermes idea)
     │   manage_todos                (task checklist — Kilo Code idea)
     │   run_subagent                (delegate to a specialist — Claude Code idea)
     │   web_search                  (DuckDuckGo, free/no key — Hermes idea)
     ▼
  files in your project      kb/ notes        memory.db (in ~/.kbcode)
```

- **`kb/`** — short markdown notes about the project, loaded into the prompt each
  session so the agent doesn't re-read everything.
- **`~/.kbcode/projects/<project-slug>/`** — the project's **runtime state**, kept in
  your home dir the way Claude Code keeps `~/.claude/projects/`: `memory.db` (a tiny
  SQLite database of long-term memories and skills), `sessions/` (one JSONL file per
  chat, for `--continue` / `--resume` and the all-time `/insights` rollup),
  `checkpoints/` (pre-edit snapshots), `history` (input history), and `kbcode.log`.
  Nothing here ever shows up in your project's git. (A project that already has a
  `.kbcode/memory.db` from an older kbcode keeps using it, so nothing is lost.
  `KBCODE_HOME` relocates `~/.kbcode` itself.)
- **`.kbcode/`** (in the project) — just the per-project **config**: `settings.json`,
  `standing-orders.md` (always-on instructions added to every session), `agents/`
  (your subagent definitions, `*.md`), `modes/` (your custom modes, `*.md`), and
  `prompts/`. kbcode drops a `.gitignore` inside it so it stays out of your project's
  git; delete that file if you'd rather commit e.g. your standing orders.
- **`.kbcode/settings.json`**'s `"hooks"` key — optional `PreToolUse`/`PostToolUse`/`Stop`
  scripts that can inspect or block a tool call before/after it runs, same shape and
  exit-code contract as real Claude Code's hooks (`0` allow, `2` block + message), e.g.
  `{"PreToolUse": [{"matcher": "run_command", "hooks": [{"type": "command", "command": "..."}]}]}`.
- **`AGENT.md`** — a short pointer file telling the agent how to work here.

> [!CAUTION]
> **You're always in control.** Risky actions (writing files, running commands)
> ask for your approval first — and overwriting an existing file shows a
> **colored diff** of what's actually changing (a brand-new file just shows
> the byte count; nothing to diff yet). A relative path is anchored to the
> project folder, but an absolute path is honored exactly as given — even
> outside the project — so if you name a specific location, that's where
> the file goes;
> the approval prompt flags it with **`-- OUTSIDE the project folder`** so
> you always see it before saying yes. As an extra safety rail, the agent
> **refuses** to write to or edit sensitive files — `.git/`, `.ssh/`, `.env`
> and secrets, private keys, and kbcode's own state — even if you approve,
> no matter where they are. (Templates like `.env.example` and your
> `.gitignore` are fine.) It also **redacts secrets**
> it stumbles into — API keys, auth headers, private keys, DB passwords — out
> of command output and file reads before they ever reach the model or the
> transcript — and tells you *how many* it caught (never the values), e.g.
> `[kbcode redacted 1 likely secret from this output]`. Turn redaction off with
> `KBCODE_REDACT_SECRETS=false` if you need raw values. Commands matching an
> outright destructive pattern (`rm -rf /`, a fork bomb, `format C:`, …) are
> **refused outright**, no prompt; a run-away loop is also capped at 25
> `run_command` calls per turn. Writing to somewhere that looks like an OS
> directory (`C:\Windows`, `/etc`, …) still asks, but the prompt flags it in
> **bold** so it's hard to miss. And before it edits or runs anything, it
> **auto-saves a checkpoint** — if it makes a mess, `/rollback` puts your files
> back exactly how they were.

## 🗂️ Project layout

```
kbcode/
  cli.py            entry point: argv parsing, project setup, console/ui singletons
  repl.py           the interactive chat loop + slash commands (split out of cli.py)
  wizard.py         the `kbcode model` setup wizard (split out of cli.py)
  agent.py          the agent loop, subagent delegation, /insights usage tally
  modes.py          code/architect/ask/debug modes (Kilo Code idea)
  subagents.py      .kbcode/agents/*.md loader — delegated specialists (Claude Code idea)
  ui.py             terminal look-and-feel (banner, tool lines, menus, summaries)
  prompt_input.py   "/" command autocomplete + the selectable menu (prompt_toolkit)
  compaction.py     summarize long chats to stay within context (Hermes idea)
  sessions.py       persisted chat transcripts — --continue/--resume, /insights rollup
  provider.py       talks to Claude / any OpenAI-compatible model, streaming + non (+ token usage)
  tools/            the agent's tools, one module per category (+ execute-time repair, openclaw idea)
    __init__.py     the Tools facade — composes the categories below
    core.py         schema/dispatch machinery + helpers shared across categories
    schemas.py      the JSON schema for every built-in tool
    file.py         read/write/edit/list/search/run_command
    kb.py           kb_read/kb_search/kb_write
    memory.py       remember/recall/save_skill
    planning.py     manage_todos
    subagent.py     run_subagent
    web.py          web_search (DuckDuckGo via the ddgs package, no API key)
    mcp.py          MCP client — external tool servers over stdio (Claude Code idea)
  repair.py         recover tool calls a weak model wrote as plain text (openclaw idea)
  pricing.py        rough per-model USD pricing for /insights (Hermes idea)
  prompts.py        the system prompt (+ standing orders, + .kbcode/prompts/ fragments)
  memory.py         persistent memory + skills (SQLite)
  knowledge_base.py kb/ notes + path:line checker & auto-fix (claude-kb idea)
  permissions.py    approval menu for risky actions
  hooks.py          PreToolUse/PostToolUse/Stop hook runner (Claude Code idea, see settings.json)
  config.py         paths + settings
```

## 🔌 MCP servers (external tools)

kbcode can connect to [MCP](https://modelcontextprotocol.io) servers and use
their tools as if built-in — filesystem, git, Playwright, SQLite, and the rest
of the community-server ecosystem — with zero per-tool code. Add a Claude
Code-compatible `mcpServers` block to `.kbcode/settings.json` (project, or
`~/.kbcode/settings.json` for all projects — entries merge per server,
project wins on a name clash):

```json
{
  "mcpServers": {
    "git":  { "command": "uvx", "args": ["mcp-server-git", "--repository", "."] },
    "fs":   { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
              "read_only": true }
  }
}
```

Tools show up namespaced (`mcp__git__git_status`) and go through the same
safety rails as built-ins: a permission prompt by default, an automatic
checkpoint before anything that may mutate, and secret redaction on results.
Optional per-server fields: `read_only: true` (pure-read server — no prompts,
runs in parallel batches), `trusted: ["tool"]` (auto-approve specific tools),
`env`, `cwd`, `timeout`, `enabled`. `/mcp` lists connected servers,
`/mcp reload` reconnects (a server that changes its tool set mid-session
needs this — change notifications aren't consumed).

Scope & prerequisites: **local stdio servers, tools only** — no remote
HTTP/OAuth servers, resources, or prompts (yet). `npx ...` servers need
Node.js installed, `uvx ...` needs Python 3.10+ with uv; kbcode just runs the
command you configure. A server that fails to start is skipped with a warning
— it never blocks the agent.

## 🧠 Choose your AI model

kbcode works with **Claude** and **any OpenAI-compatible model**. Three ways,
easiest first.

### ✅ The easy way — `kbcode model`

```bash
kbcode model
```

Run it and follow the prompts: pick a provider, paste your key, choose a model
from the list it fetches. The selection is saved so `kb` (or `kb -C ...`) immediately
sees the new provider/model for the folder (also updates global default). **This is all most people ever need.**

> [!WARNING]
> **Model not configured? / "No API key found"?** That just means no key is saved
> yet (or you're on a fresh install). Fix it in one of two ways:
> - Run **`kbcode model`** again and paste your key, **or**
> - Add your key to `~/.kbcode/.env` by hand, e.g. `ANTHROPIC_API_KEY=sk-ant-...`
>
> Confirm it worked: start `kbcode` and check the banner shows your provider + model.

### 🔄 Switch live inside a chat (no restart)

```text
/provider openai gpt-4o     # change provider (and optionally the model)
/model deepseek-chat        # change just the model
/provider                   # list available providers
/model                      # list this provider's models
```

### ⚙️ By hand in `.env`

Set `KBCODE_PROVIDER` and the matching key:

| Provider | `KBCODE_PROVIDER` | 🔑 Key to set | Default model |
|----------|-------------------|------------|---------------|
| 🟣 Claude | `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-4-8` |
| 🟢 OpenAI (ChatGPT) | `openai` | `OPENAI_API_KEY` | `gpt-4o` |
| 🔵 Google Gemini | `gemini` | `GEMINI_API_KEY` | `gemini-2.0-flash` |
| 🌊 DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| 🛰️ OpenRouter (many models) | `openrouter` | `OPENROUTER_API_KEY` | `openai/gpt-4o` |
| 🤖 MiMo (via OpenRouter) | `mimo` | `OPENROUTER_API_KEY` | set `KBCODE_MODEL` |
| 🦙 Ollama (local models) | `ollama` | none needed (or `OLLAMA_API_KEY` for a remote server) | `llama3.1` |
| 🧩 Any custom endpoint | `custom` | `KBCODE_API_KEY` + `KBCODE_BASE_URL` | set `KBCODE_MODEL` |

Example `.env`:

```bash
KBCODE_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
```

> [!NOTE]
> - `KBCODE_MODEL` overrides the model id for any provider.
> - Switching provider clears the current chat (memory and kb are kept).
> - `KBCODE_TEMPERATURE`, `KBCODE_THINKING` and `KBCODE_MAX_TOKENS` are adjustable at runtime (`/temperature`, `/thinking`, `/maxtokens`). `KBCODE_THINKING=off` disables reasoning/thinking. "normal" maps to medium for thinking. When `KBCODE_MAX_TOKENS` is not set, max_tokens is chosen automatically based on the current model. Use `/maxtokens auto` to return to model-driven behavior.
> - `KBCODE_REQUEST_TIMEOUT` (seconds, default `120`) caps how long one model
>   call can hang before it fails fast and retries — handy for slow endpoints;
>   set `0` to restore the SDK's ~10-minute default. See `.env.example`.
> - `KBCODE_MAX_STEPS` (default `50`) and `KBCODE_MAX_COMMANDS` (default `25`)
>   are the runaway-loop guards: tool round-trips per message and shell commands
>   per turn. Hitting one pauses the turn safely — saying "continue" resumes —
>   so raise them if long tasks keep pausing on you.
> - `KBCODE_LOG_LEVEL` (default `INFO`) writes a quiet diagnostic log to
>   `~/.kbcode/projects/<slug>/kbcode.log` — set `DEBUG` for full detail when
>   reporting a bug, or `off` to write nothing. Separate from the on-screen output.
> - `KBCODE_HOME` relocates `~/.kbcode` itself (global settings, model cache, and
>   every project's runtime state under `projects/`).

## 🔄 Update & version

- 🔢 **See your version:** `kbcode --version` (or `/version` in chat — the banner
  shows it too).
- ⬆️ **Update to the latest:** `kbcode update` — pulls the newest release from
  GitHub and force-reinstalls kbcode so the latest code always lands, even
  when the version number hasn't changed.
- 🩹 **Stuck on an old version?** If `kbcode update` keeps leaving you on an
  older build (a known trap in versions ≤ 1.9.0, where a plain
  `pip install --upgrade` would silently do nothing), run this once by hand to
  break out of it — after that, `kbcode update` works normally:

  ```bash
  pip install --upgrade --force-reinstall --no-cache-dir git+https://github.com/johnmungandiall/kbcode.git
  ```

## 🗑️ Uninstall

Three layers — remove as much or as little as you want:

1. **The program itself:**

   ```bash
   pip uninstall kbcode
   ```

   This removes the `kbcode` and `kb` commands. (If you used the no-install
   option, there's nothing to uninstall — just delete the cloned folder.)

2. **Your global data** — API keys, saved model choice, and every project's
   chat history / memory / logs all live in **one folder**. Delete it and
   they're gone:

   - Windows: `rmdir /s /q %USERPROFILE%\.kbcode` (or delete `~/.kbcode` in Explorer)
   - macOS / Linux: `rm -rf ~/.kbcode`

   > [!NOTE]
   > The folder appears the first time you *run* kbcode (not at `pip install`) —
   > if it isn't there, there's simply nothing to delete. If you set
   > `KBCODE_HOME`, delete that folder instead — and remove the env var too.

3. **Per-project leftovers (optional):** inside each project where you ran
   `kbcode init`, you may have an `AGENT.md`, a `kb/` folder, and a `.kbcode/`
   folder. They're plain files that do nothing without kbcode — the `kb/`
   notes are readable project documentation, so many people keep them. Delete
   them only if you want a fully clean project.

Steps 2 and 3 are permanent — chat history and memory can't be recovered once
those folders are deleted. Skipping them is also fine: if you reinstall later,
kbcode picks up your old keys and history right where you left off.

## 🧪 Development

```bash
git clone https://github.com/johnmungandiall/kbcode.git
cd kbcode
pip install -e ".[dev]"  # kbcode itself + pytest + ruff
pytest -q                # run the test suite
ruff check .              # lint
```

GitHub Actions runs both on every push/PR (`.github/workflows/ci.yml`), across
Python 3.10/3.12 on Ubuntu and Windows. See `CONTRIBUTING.md` for the full
workflow (coding style, PR expectations).
