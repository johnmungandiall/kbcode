# 🤖 kbcode

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Version](https://img.shields.io/badge/version-1.0.2-2ea44f)
![Platforms](https://img.shields.io/badge/Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-555)
![Models](https://img.shields.io/badge/Claude%20%2B%20any%20OpenAI--compatible-8A2BE2)

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

That gives you a real `kbcode` command you can run from any folder. Check it:

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
kbcode             # start chatting
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

Run these in your shell. (Use `python -m kbcode` instead of `kbcode` if you
chose the no-install option.)

| Command | What it does |
|---|---|
| `kbcode` | Start the chat on the current folder. |
| `kbcode "do the thing"` | Run one task and exit (one-shot). |
| `kbcode -y "do the thing"` | One-shot, but auto-approve every write & command (no y/N prompts). |
| `kbcode init` | Set up the current folder (`AGENT.md` + `kb/`). Target another with `kbcode init "C:\path"`. |
| `kbcode model` | Pick provider + key + model interactively; saved globally. |
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
calls show live as a readable verb + target — `⏺ Read kbcode/agent.py`,
`⏺ Run $ pytest`, `⏺ Delegate → code-explorer` — each with an indented `↳`
result preview (or a red `✗` on error). After every turn a dim footer reports
`3 actions · ~1.5k tokens · 4.5s`, and `/status` shows a context-fullness bar
versus the auto-compact threshold. Approval prompts for risky actions are a
**selectable Yes / Always / No menu** (↑/↓ + Enter, or press 1/2/3) — Claude Code
style — falling back to a typed `y/N/a` prompt where no interactive menu is available.

While a turn is running you can press **Esc** (or Ctrl-C) to interrupt it and drop
back to the prompt — the spinner shows an `(Esc to interrupt)` hint.

Type `/` and a **popup menu of commands** appears and filters as you type
(arrow keys + Tab/Enter to pick); after `/provider` it suggests provider names,
after `/mode` mode names, and after `/kb-check` the `--fix` flag. This needs
`prompt_toolkit` (in `requirements.txt`); without it, commands still work by
typing them in full.

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
- `/open <folder>` — switch to working on another project folder
- `/insights` — tokens used and estimated cost this session
- `/compact` — summarize earlier chat to free up context
- `/reset` — clear the current chat (memory and kb are kept)
- `/exit` — quit

Knowledge & memory:
- `/kb` — list knowledge-base notes
- `/kb-check [--fix]` — check `path:line` pointers in `kb/` (with `--fix`, relocate drifted ones by symbol)
- `/memory` — show recent long-term memory
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
     │   kb_read / kb_write          (knowledge base — claude-kb idea)
     │   remember / recall / save_skill   (memory + skills — Hermes idea)
     │   manage_todos                (task checklist — Kilo Code idea)
     │   run_subagent                (delegate to a specialist — Claude Code idea)
     ▼
  files in your project      kb/ notes        .kbcode/memory.db
```

- **`kb/`** — short markdown notes about the project, loaded into the prompt each
  session so the agent doesn't re-read everything.
- **`.kbcode/memory.db`** — a tiny SQLite database of long-term memories and
  skills, kept between sessions. (Git-ignored; it's per-machine.)
- **`.kbcode/standing-orders.md`** — always-on instructions added to every session.
- **`.kbcode/agents/`** — your subagent definitions (`*.md`).
- **`.kbcode/modes/`** — your custom modes (`*.md`), if any.
- **`AGENT.md`** — a short pointer file telling the agent how to work here.

> [!CAUTION]
> **You're always in control.** Risky actions (writing files, running commands)
> ask for your approval first. As an extra safety rail, the agent **refuses** to
> write to or edit sensitive files — `.git/`, `.ssh/`, `.env` and secrets, private
> keys, and kbcode's own state — even if you approve. (Templates like
> `.env.example` and your `.gitignore` are fine.)

## 🗂️ Project layout

```
kbcode/
  cli.py            entry point + chat loop, slash commands, -C / init / /open
  agent.py          the agent loop, subagent delegation, /insights usage tally
  modes.py          code/architect/ask/debug modes (Kilo Code idea)
  subagents.py      .kbcode/agents/*.md loader — delegated specialists (Claude Code idea)
  ui.py             terminal look-and-feel (banner, tool lines, menus, summaries)
  prompt_input.py   "/" command autocomplete + the selectable menu (prompt_toolkit)
  compaction.py     summarize long chats to stay within context (Hermes idea)
  provider.py       talks to Claude / any OpenAI-compatible model (+ token usage)
  tools.py          the agent's tools (+ execute-time tool-call repair, openclaw idea)
  repair.py         recover tool calls a weak model wrote as plain text (openclaw idea)
  pricing.py        rough per-model USD pricing for /insights (Hermes idea)
  prompts.py        the system prompt (+ standing orders)
  memory.py         persistent memory + skills (SQLite)
  knowledge_base.py kb/ notes + path:line checker & auto-fix (claude-kb idea)
  permissions.py    approval menu for risky actions
  config.py         paths + settings
```

## 🧠 Choose your AI model

kbcode works with **Claude** and **any OpenAI-compatible model**. Three ways,
easiest first.

### ✅ The easy way — `kbcode model`

```bash
kbcode model
```

Run it and follow the prompts: pick a provider, paste your key, choose a model
from the list it fetches. It's saved globally (`~/.kbcode`), so every project
uses it. **This is all most people ever need.**

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
| 🧩 Any custom endpoint | `custom` | `KBCODE_API_KEY` + `KBCODE_BASE_URL` | set `KBCODE_MODEL` |

Example `.env`:

```bash
KBCODE_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
```

> [!NOTE]
> - `KBCODE_MODEL` overrides the model id for any provider.
> - Switching provider clears the current chat (memory and kb are kept).
> - `KBCODE_EFFORT` (low/medium/high/max) applies to Claude only.

## 🔄 Update & version

- 🔢 **See your version:** `kbcode --version` (or `/version` in chat — the banner
  shows it too).
- ⬆️ **Update to the latest:** `kbcode update` — pulls the newest release from
  GitHub. (Same as `pip install --upgrade git+https://github.com/johnmungandiall/kbcode.git`.)
