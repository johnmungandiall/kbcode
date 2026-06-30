# CONCEPTS — feature catalogue mined from `references/`

> **తెలుగులో సారాంశం (plain summary)**
> `references/` లో ఐదు AI agent repos ఉన్నాయి. ఈ file వాటిలోని **అన్ని ఆలోచనలను (concepts)** ఒక చోట పెడుతుంది.
> ప్రతి concept పక్కన ఒక గుర్తు ఉంది:
> - ✅ = ఇది ఇప్పటికే kbcode లో ఉంది
> - 🔜 = kbcode లోకి తేవడం సులభం, విలువైనది — **తర్వాత add చేయాల్సినవి**
> - ⏭️ = ఈ చిన్న CLI agent కి అవసరం లేదు / చాలా పెద్దది (skip)
>
> చివర్లో **"Recommended next features"** అనే ప్రాధాన్యత list ఉంది — kbcode లో ఏది ముందు చేయాలో అదే.

This document is the bridge between study (the cloned `references/`) and product (the `kbcode/`
package). It is **not** shipped code — it is a working backlog. Each reference repo contributes a
"home concept" (named in `CLAUDE.md`), but each also carries many *secondary* ideas worth lifting.
The goal: harvest every concept once, mark what kbcode already has, and rank the rest.

**Legend** — ✅ already in kbcode · 🔜 portable & recommended · ⏭️ out of scope for a small local CLI

---

## 1. Claude Code — *the agentic loop + tools*

Home concept (✅ in kbcode): a single tool-using loop (read/write/edit/list/search/run) that drives
any model, with permission gating on writes & commands.

Secondary concepts mined from its plugins (`plugins/`) and `.claude/`:

| Concept | What it is | Status |
|---|---|---|
| **Slash commands as files** | A `commands/*.md` file with YAML frontmatter (`description`, `argument-hint`) + a prompt body becomes a reusable command (`$ARGUMENTS` is substituted). | 🔜 kbcode has hardcoded commands; loading `.kbcode/commands/*.md` would make them user-extensible. |
| **Subagents** | `agents/*.md` (frontmatter `name`/`description`/`tools`/`model`) run a task in their **own** context window; auto-delegated by `description`. Examples: `code-explorer`, `code-architect`, `code-reviewer`. | 🔜 High value — keeps heavy exploration out of the main session. |
| **Skills** | `skills/<name>/SKILL.md` — packaged know-how loaded on demand by trigger phrase. | ✅ kbcode has `save_skill`/`/skills` (simpler form). 🔜 could add the `SKILL.md` + frontmatter format. |
| **Hooks** | Scripts fired on lifecycle/tool events to inject rules or block actions (`hookify` plugin: regex rule → message). | 🔜 a lightweight `.kbcode/hooks/` (pre-write / pre-command) fits the permission model. |
| **Output styles** | Swappable response personas (`explanatory`, `learning`). | ⏭️ overlaps with modes; low priority. |
| **`/insights`-style usage stats** | Token/cost/tool-usage report from session history. | 🔜 (also appears in Hermes) — see §3. |
| **Guided multi-phase commands** | `feature-dev`: Discovery → Explore → Design → Implement, "ask clarifying questions first," TodoWrite throughout. | 🔜 maps onto a richer `architect` mode + a todo tool. |
| **MCP integration** | External tool servers over a protocol. | ⏭️ heavy; not needed locally yet. |

---

## 2. Hermes — *persistent memory/skills + context compaction*

Home concepts (✅ in kbcode): long-term memory (`remember`/`recall`), saved skills, and threshold
context compaction.

Secondary concepts mined from `agent/`:

| Concept | What it is | Status |
|---|---|---|
| **Curator** (`curator.py`) | A background, idle-triggered auxiliary-model pass that reviews agent-created skills: archive/pin/consolidate/patch stale ones. The memory **maintains itself**. | 🔜 a `/curate` (or idle) pass over `kb/` + skills is a natural fit. |
| **Insights engine** (`insights.py`) | Reads the session DB → tokens consumed, cost estimate, tool-usage patterns, per-model breakdown. | 🔜 kbcode already estimates tokens; a `/insights` over saved sessions is low effort. |
| **Iteration budget** (`iteration_budget.py`) | Thread-safe per-agent step cap (parent 90, subagent 50) — stops runaway loops. | 🔜 cheap safety rail for `Agent.run`. |
| **Pluggable context engine** (`context_engine.py`) | Compaction is an abstract, config-selected strategy (`context.engine`), not hardwired. | 🔜 small refactor: make `compaction` swappable; default = current summarizer. |
| **`/learn`** (`learn_prompt.py`) | Turn "what we just did" / a dir / a URL into one reusable `SKILL.md`. | 🔜 great UX layer over the existing `save_skill`. |
| **File safety** (`file_safety.py`) | Shared guardrails (protected paths, refuse-list) reused by every write path. | ✅ `Tools._protected_reason` refuses writes/edits to `.git/`, `.ssh/`, `.env`/secrets, keys, and kbcode's own state (allows `.env.example`, `.gitignore`, agent/mode markdown). |
| **Error classifier** (`error_classifier.py`) | Categorise provider/tool errors → retry vs surface vs abort. | ✅ `provider._classify` + `_with_retry` (retry transient 429/5xx/network with backoff; surface auth/bad-request as `ProviderError`). |
| **Multi-provider adapters** | anthropic / openai / gemini-native / bedrock / azure / codex. | ✅ kbcode covers anthropic + any OpenAI-compatible; native Gemini/Bedrock are ⏭️ for now. |
| **Background review, LSP client, browser/image providers, credential pool, ACP** | Larger subsystems. | ⏭️ beyond a small local CLI. |

---

## 3. claude-kb — *token-cheap `kb/` notes + `path:line` pointer checking*

Home concepts (✅ in kbcode): the `kb/` note set in the system prompt, and `check_pointers()`
(`/kb-check`) that resolves every `path:line` and flags missing/stale references.

Secondary concepts mined from `kb/`, `prompt.md`, `update.md`, `verify.md`, `check.md`, `slim.md`:

| Concept | What it is | Status |
|---|---|---|
| **The three KB workflows** | `init` (build KB) / `update` (upgrade to latest spec) / `verify` (audit drift, classify STALE/WRONG/MISSING/ORPHAN/BROKEN, auto-fix cheap). | Partly ✅ (`/kb-check` = the pointer gate). 🔜 add a `verify`-style **drift audit + auto-fix + changelog bump**. |
| **`--fix` auto-repair** | The checker can move a drifted pointer to its new line automatically. | 🔜 upgrade `check_pointers()` from *report* to *repair*. |
| **KB subagents** | `.claude/agents/kb-maintainer` (refresh notes after any change, PROACTIVELY), `kb-verify`, `kb-slim`. | 🔜 pairs with the subagents idea (§1) — a "refresh the affected note after editing code" agent. |
| **`[[wiki-links]]` between notes** | Cross-link notes so related context is discoverable. | ✅/🔜 used in memory; could be surfaced in `kb/` too. |
| **`slim` pass** | Shrink a bloated context file by moving detail into `kb/`. | 🔜 a `/slim` for `AGENT.md`/`CLAUDE.md`. |
| **Pre-commit drift hook** | `tools/hooks/pre-commit` runs the checker so drift never lands. | 🔜 ship a sample git hook (opt-in). |
| **Note taxonomy** | Standard notes: `overview`, `architecture`, `conventions`, `glossary`, `gotchas`, `cheatsheet`, `changelog`, `about-you`. | ✅ `kbcode init` scaffolds all eight (`_TEMPLATES` in `knowledge_base.py`); AGENT.md's notes-map lists them. |

---

## 4. Kilo Code — *modes*

Home concept (✅ in kbcode): `Mode` = instructions + allowed-tool set, applied per turn; built-ins
`code`/`architect`/`ask`/`debug`; custom modes from `.kbcode/modes/*.md`.

Secondary concepts:

| Concept | What it is | Status |
|---|---|---|
| **Orchestrator / "Boomerang" mode** | A mode that splits a job into subtasks and delegates each to the best mode/agent, then stitches results. | 🔜 the missing 5th mode — depends on subagents (§1). |
| **Per-mode "sticky" model** | Each mode remembers its own provider/model (cheap model for `ask`, strong for `architect`). | 🔜 add an optional `model:` to mode frontmatter. |
| **Todo-list tool** | A first-class checklist the agent maintains across a task (`specs/v2/todo.md`, also Claude Code's TodoWrite). | 🔜 a `manage_todos` tool + `/todo` view; raises reliability on multi-step jobs. |
| **Codebase indexing** | Embeddings index for semantic "find by meaning" search. | ⏭️ heavy (needs an embedding provider) — `search_code` (ripgrep) is enough for now. |
| **Custom modes via UI/file** | User-authored modes. | ✅ already (`.kbcode/modes/*.md`). |
| **Auto-approve / allow-list per mode** | Pre-approve certain tools so trusted modes don't prompt. | 🔜 ties into Permissions. |

---

## 5. openclaw — *tool-call repair*

Home concept (✅ in kbcode): tool-call repair in **two layers** — *execute-time* `Tools._repair()`
(unknown tool name → closest match via `difflib`; missing required args → named) **and** *parse-time*
`repair.promote()` (recover a tool call a weak model wrote as plain text, when the provider reports no
structured `tool_calls`) — so weaker models self-correct instead of hard-failing **or stalling**.

Secondary concepts mined from `docs/automation/` and `packages/`:

| Concept | What it is | Status |
|---|---|---|
| **Automation surfaces** | A clear taxonomy: **cron** (exact schedule), **heartbeat** (approximate periodic), **hooks** (lifecycle events), **standing orders** (instructions injected every session), **inferred commitments** (remembered follow-ups), **task flow** (durable multi-step). | 🔜 *standing orders* = always-on instructions in `AGENT.md`/`.kbcode` is the cheapest, highest-value pick. |
| **Standing orders** | Persistent instructions auto-injected into every session ("always check compliance before replying"). | 🔜 trivial: a file whose contents prepend the system prompt every run. |
| **Hooks (internal vs typed)** | File-based side-effect hooks vs in-process typed hooks that can rewrite prompts / block tools. | 🔜 same hook idea as §1; converge into one design. |
| **Background tasks ledger** | Track detached work; `tasks list` / `tasks audit`. | ⏭️ needs a daemon; out of scope. |
| **`tool-call-repair` as a package** | The repair logic isolated & testable; notably its job is to **promote tool calls a model emitted as plain text** into real calls. | ✅ kbcode's `repair.py` (`promote()`) recovers `[name]{…}` / `[tool:name]` / `<name>{…}</name>` / bare `{"name"/"tool"/"function", "arguments"}` blocks, fed back as a `user` turn; plus execute-time `Tools._repair`. |
| **Channels (Slack/Discord/Matrix/SMS…)** | Multi-surface messaging. | ⏭️ not a local coding CLI concern. |
| **net-policy / plugin-sdk / model-catalog** | Network egress policy, plugin contract, dynamic model registry. | Partly ✅ (kbcode auto-fetches model lists); rest ⏭️. |

---

## Recommended next features for kbcode (priority order)

Ranked by **value ÷ effort** for a small, single-file-per-module local CLI. Each names its source.
**Status: items 1–6 and 8–10 are now implemented.**

1. ✅ **Todo tool + `/todo`** *(Kilo Code / Claude Code)* — `manage_todos` tool, shown in the UI;
   allowed in every mode via the READ group. (`tools.py`, `ui.py`, `cli.py`, `modes.py`)
2. ✅ **Standing orders** *(openclaw)* — `.kbcode/standing-orders.md` is prepended to the system
   prompt every run; the untouched scaffold is ignored. (`config.py`, `prompts.py`, `cli.py`)
3. ✅ **KB drift auto-fix** *(claude-kb)* — `/kb-check --fix` relocates a drifted `path:line` by the
   code symbol named on the note line (`KnowledgeBase.fix_pointers`). (`knowledge_base.py`, `cli.py`)
4. ✅ **Subagents** *(Claude Code / claude-kb)* — `.kbcode/agents/*.md` run in their own context
   window via the `run_subagent` tool; ships a read-only `code-explorer`. (`subagents.py`, `agent.py`,
   `tools.py`, `cli.py`) — this is the base Orchestrator mode (#7) builds on.
5. ✅ **`/insights`** *(Hermes)* — per-session tokens + estimated cost from real provider usage
   (`pricing.py`, `Agent.insights`). (`provider.py`, `agent.py`, `ui.py`, `cli.py`)
6. ✅ **`/learn`** *(Hermes)* — sends a guided prompt so the agent turns the conversation (optionally a
   named topic) into a reusable skill via `save_skill`. (`cli.py`, `ui.py`)
7. 🔜 **Per-mode sticky model + Orchestrator mode** *(Kilo Code)* — `model:` in mode frontmatter, then a
   5th mode that delegates subtasks to the subagents from #4.
8. ✅ **File safety / write guardrails** *(Hermes `file_safety.py`)* — `Tools._protected_reason` refuses
   writes/edits to `.git/`, `.ssh/`, `.env` & secrets, private keys, and kbcode's own state files, while
   allowing templates (`.env.example`), `.gitignore`, and user-authored agent/mode markdown. (`tools.py`)
9. ✅ **Error classifier + auto-retry** *(Hermes `error_classifier.py`)* — `provider._classify` +
   `_with_retry` retry transient failures (429/5xx/network) with exponential backoff and surface
   auth/bad-request as a clean `ProviderError(hint=…)`; the CLI prints it without a traceback. (`provider.py`, `cli.py`)
10. ✅ **Plain-text tool-call repair** *(openclaw `tool-call-repair`)* — when a weak / OpenAI-compatible
   model writes a tool call as text instead of using the function-calling interface, `repair.promote`
   recovers it and `Agent._run_promoted` runs it + nudges the model back to the proper format, so the
   turn no longer stalls at "no tool calls → done". (`repair.py`, `agent.py`)

Alongside these, a **production pass**: `pyproject.toml` makes `kbcode` a real installable command, and
write/edit tool-lines now show the **full resolved path** so you always see where a file lands.

**Still open / future:** #7 above, plus an *iteration budget* (per-run step cap — partly covered by the
existing `_MAX_STEPS`/`_SUBAGENT_MAX_STEPS` caps), the `verify`-style **changelog bump** on KB fixes,
pre-commit drift hooks, file-based slash commands, and lifecycle hooks.
See the per-repo tables for the rest.
