# kbcode

A small AI coding agent you run in your terminal. It blends three ideas:

| Idea | From | What it gives you |
|------|------|-------------------|
| **Hands** — reads/writes files, runs commands | Claude Code | The agent actually does the work, not just talks. |
| **Memory + skills** — remembers across sessions | Hermes agent | It recalls past decisions and reuses how-tos it learned. |
| **Knowledge base** — short `kb/` notes | claude-kb | It understands your project cheaply, without re-scanning every file. |

It uses your own AI API key (Anthropic / Claude).

## Setup

1. Install Python 3.10+.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Add your API key — copy `.env.example` to `.env` and paste your key:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   Get one at https://console.anthropic.com/

## Use

From inside the project you want the agent to work on:

```
# set up the kb/ folder and AGENT.md once
python -m kbcode init

# let it learn the project and write notes
python -m kbcode "build the knowledge base for this project"

# start chatting
python -m kbcode
```

You can also give a one-off task:

```
python -m kbcode "add input validation to login() and run the tests"
```

Add `-y` to auto-approve file writes and commands (skip the y/N prompts):

```
python -m kbcode -y "fix the failing test in tests/test_auth.py"
```

### The terminal

kbcode runs as a chat terminal in the style of Claude Code / Hermes: a header
banner with your provider and model, answers rendered as markdown, tool calls
shown live as `⏺ tool(args)` with a `↳` result preview, and a `/status` line
showing how much context you've used.

### Chat commands

- `/help` — show the command table
- `/status` — show provider, model and context size
- `/provider [name] [model]` — switch provider (no name = list them)
- `/model [id]` — switch model (no id = list this provider's models)
- `/kb` — list knowledge-base notes
- `/kb-check` — check that `path:line` pointers in `kb/` still resolve
- `/memory` — show recent long-term memory
- `/skills` — list learned skills
- `/compact` — summarize earlier chat to free up context
- `/reset` — clear the current chat (memory and kb are kept)
- `/exit` — quit

### Long sessions stay cheap (auto-compaction)

When a chat grows long, kbcode automatically summarizes the older middle of the
conversation into a short recap and keeps going — so it doesn't slow down, get
expensive, or overflow the model's context window. (This is the Hermes idea.)
Tune it with `KBCODE_COMPACT_TOKENS` in `.env` (`0` turns it off), or run
`/compact` yourself any time.

## How it works

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
     ▼
  files in your project      kb/ notes        .kbcode/memory.db
```

- **`kb/`** — short markdown notes about the project, loaded into the prompt each
  session so the agent doesn't re-read everything.
- **`.kbcode/memory.db`** — a tiny SQLite database of long-term memories and
  skills, kept between sessions. (Git-ignored; it's per-machine.)
- **`AGENT.md`** — a short pointer file telling the agent how to work here.

Risky actions (writing files, running commands) ask for your approval first.

## Project layout

```
kbcode/
  cli.py            entry point + chat loop
  agent.py          the agent loop
  ui.py             terminal look-and-feel (banner, markdown, tool lines)
  compaction.py     summarize long chats to stay within context (Hermes idea)
  provider.py       talks to Claude / any OpenAI-compatible model
  tools.py          the agent's tools
  prompts.py        the system prompt
  memory.py         persistent memory + skills (SQLite)
  knowledge_base.py kb/ notes + path:line pointer checker (claude-kb idea)
  permissions.py    y/N approval for risky actions
  config.py         paths + settings
```

## Use other models

kbcode works with Claude **and** any OpenAI-compatible model. Pick one in `.env`:

| Provider | `KBCODE_PROVIDER` | Key to set | Default model |
|----------|-------------------|------------|---------------|
| Claude | `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-4-8` |
| OpenAI (ChatGPT) | `openai` | `OPENAI_API_KEY` | `gpt-4o` |
| Google Gemini | `gemini` | `GEMINI_API_KEY` | `gemini-2.0-flash` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| OpenRouter (many models) | `openrouter` | `OPENROUTER_API_KEY` | `openai/gpt-4o` |
| MiMo (via OpenRouter) | `mimo` | `OPENROUTER_API_KEY` | set `KBCODE_MODEL` |
| Any custom endpoint | `custom` | `KBCODE_API_KEY` + `KBCODE_BASE_URL` | set `KBCODE_MODEL` |

Example `.env`:

```
KBCODE_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
```

Or switch live inside the chat:

```
/provider openai gpt-4o
/model deepseek-chat
/providers
```

Notes:
- `KBCODE_MODEL` overrides the model id for any provider.
- Switching provider clears the current chat (memory and kb are kept).
- `KBCODE_EFFORT` (low/medium/high/max) applies to Claude only.
