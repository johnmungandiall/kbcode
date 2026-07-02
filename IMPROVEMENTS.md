# Improvement Suggestions for kbcode

Status refreshed 2026-07-02 against v1.14.0 (the original list was written
against v1.4.2 — most of it has shipped since). Only genuinely OPEN items keep
a row below; everything else is in the "Done" roll-up at the bottom.

---

## Open items

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 2.4 | **Use an enum for tool names** — tool names are bare strings scattered across `_KB_WRITE_TOOLS`, `_PROTECTED_*`, mode tool sets. A `StrEnum` would catch typos at definition time. | `tools/`, `modes.py`, `agent.py` | Low |
| 2.5 | **Centralize path resolution** — `_resolve()` lives in `ToolsCore` but `checkpoints.py` also resolves paths independently. | `tools/core.py`, `checkpoints.py` | Low |
| 2.6 | **Extract provider-specific logic from `agent.py`** — the vision-fallback retry is a provider concern leaking into the agent. | `agent.py`, `provider.py` | Medium |
| 3.2 | **Structured tool-call output for OpenAI-compatible** — offer `response_format` to improve tool-call reliability on weaker models. | `provider.py` | Low |
| 3.3 | **Dynamic model pricing** — the hardcoded `_PRICES` table goes stale; fetch from OpenRouter `/models` or warn that prices are estimates. | `pricing.py` | Medium |
| 4.1b | **Smarter compaction prompt** — pass 0 (free trim) exists; the LLM summary pass could still prioritize decisions/paths/errors explicitly. | `compaction.py` | Medium |
| 6.1b | **Optional sandbox for `run_command`** — the dangerous-command blocklist + per-turn rate limit exist; docker/bubblewrap isolation does not. | `tools/file.py` | High |
| 7.4 | **Syntax-highlighted tool results** — render read results with `rich.syntax.Syntax` by extension. | `ui.py`, `tools/file.py` | Low |
| 8.4 | **Memory categories** — use the `kind` column (`decision`/`preference`/`bug`/`todo`) and let `recall()` filter by it. | `memory.py`, `tools/memory.py` | Low |
| 8.5 | **Skill versioning** — `save_skill` does INSERT OR REPLACE; track how a how-to evolved. | `memory.py` | Low |
| 9.1 | **Plugin system for tools** — user-dropped `.py` files in `.kbcode/tools/` registering schema + handler. | `tools/`, new loader | High |
| 10.4 | **Checkpoint batching** — one checkpoint at turn start instead of per-first-edit. | `checkpoints.py` | Low |
| 10.5 | **Session file compaction** — periodically roll old JSONL sessions into summary records to keep `/sessions` fast. | `sessions.py` | Medium |
| 11.2 | **Contributing guide** — CONTRIBUTING.md with setup, standards, PR workflow. | `CONTRIBUTING.md` | Low |
| 11.4 | **Architecture decision records** — short ADRs for shadow git, normalized messages, two-layer repair. | `docs/adr/` | Medium |

---

## Done (roll-up)

- **Testing & CI (1.1–1.4)** — 389 pytest tests + GitHub Actions with ruff.
- **Architecture (2.1–2.3)** — `cli.py` split into `repl.py`/`wizard.py`; `tools/` package; `_TOOL_DESCRIBERS` dict registry.
- **Providers (3.1, 3.4, 3.5)** — streaming; Ollama/OpenAI-compatible presets; `/ping`.
- **Agent loop (4.1 pass 0, 4.2–4.5)** — free compaction pass; token-budget-aware tool-result truncation; parallel read-only tools + parallel subagents; promoted-recovery cap; context-aware step budget.
- **Knowledge base (5.1–5.5)** — `/init` onboarding + built/not-built flag (banner, `/status`, `/kb`); `kb_write` diff approval; pointer check on write; `kb_search`; note versioning (`kb/.history` + `/kb-undo`). Pointer check/fix now recurse into kb/ subfolders, skip IP:port / URL-host false positives, and relocate case-insensitively preferring snake_case anchors.
- **Safety (6.2–6.5 + parts of 6.1)** — redaction counts surfaced; outside-project write flag; per-turn command rate limit; dangerous-command blocklist; whole-session-line secret masking (covers the model's own replies and raw replay blocks).
- **UX (7.1–7.3, 7.5–7.8)** — streaming, diff previews, rollback picker, context bar, history file, `/cost`, multiline input.
- **Sessions & memory (8.1–8.3)** — session search/export, `/memory-prune`.
- **Extensibility (9.2–9.4)** — hooks, `.kbcode/prompts/*.md` fragments, MCP client (+ system-prompt hint so "install X MCP" configures `.kbcode/settings.json`, not an IDE file).
- **Performance (10.1–10.3)** — lazy SDK imports, cached `read_all()`, ripgrep-accelerated `search_code`.
- **Docs (11.1)** — full README.
- **Context grounding** — system prompt stamps current date/time and the project folder (path + name).
