# Improvement Suggestions for kbcode

A prioritized list of enhancements to make kbcode more robust, capable, and pleasant to use. Grouped by category; each item notes the affected files and estimated effort.

---

## 1. Testing (Critical — currently zero coverage)

The repo has no test suite. Every other improvement is riskier without one.

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 1.1 | **Add a unit test suite** — start with `pytest`. Cover `repair.py` (pure functions, easy to test), `compaction.py`, `redact.py`, `pricing.py`, `knowledge_base.py` pointer checking, and `prompt_input.py`'s `suggest()`. | new `tests/` dir | Medium |
| 1.2 | **Mock-based integration tests for the agent loop** — fake the provider, verify that tool calls dispatch correctly, promoted calls get executed, and compaction triggers at the threshold. | `tests/test_agent.py` | Medium |
| 1.3 | **CLI smoke tests** — use `subprocess` or `click.testing.CliRunner`-style invocation to verify `--version`, `init`, `model` wizard exits cleanly. | `tests/test_cli.py` | Low |
| 1.4 | **Add a CI pipeline** (GitHub Actions) — run tests on push, lint with `ruff`, type-check with `mypy`. | `.github/workflows/ci.yml` | Low |

---

## 2. Architecture & Code Quality

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 2.1 | **Split `cli.py`** — at 900 lines it handles arg parsing, the REPL, the model wizard, session resume, scaffolding, and video/image dispatch. Extract `_repl()` and its slash-command handlers into `repl.py`, and the wizard into `wizard.py`. | `cli.py` → `repl.py`, `wizard.py` | Medium |
| 2.2 | **Split `tools.py`** — file tools, KB tools, memory tools, and planning tools could live in separate modules (e.g. `tools/file.py`, `tools/kb.py`) behind a unified `Tools` facade. Would also make adding new tool categories cleaner. | `tools.py` → `tools/` package | Medium |
| 2.3 | **Eliminate the `_describe_tool()` if-chain** — the 30-branch `if name == ...` block in `ui.py:73-119` is a maintenance trap. Use a dict registry or add a `displayVerb`/`displayTarget` method to each tool. | `ui.py` | Low |
| 2.4 | **Use an enum for tool names** — currently tool names are bare strings scattered everywhere (`_KB_WRITE_TOOLS`, `_PROTECTED_*`, mode tool sets). A `ToolName` enum or `StrEnum` would catch typos at definition time. | `tools.py`, `modes.py`, `agent.py` | Low |
| 2.5 | **Centralize path resolution** — `_resolve()` lives in `Tools` but `checkpoints.py` also resolves paths independently. Consolidate into a single `PathResolver` or at least a shared helper. | `tools.py`, `checkpoints.py` | Low |
| 2.6 | **Extract provider-specific logic from `agent.py`** — the vision-fallback retry in `_try_vision_fallback` and the SDK kwarg fallback in `AnthropicProvider.complete` are provider concerns leaking into the agent. Move them behind the `LLMProvider` interface. | `agent.py`, `provider.py` | Medium |

---

## 3. Provider & Model Support

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 3.1 | **Streaming responses** — currently the user sees nothing until the full response arrives. Streaming tokens as they arrive (via `client.messages.stream()` / `stream=True`) would make long responses feel instant. | `provider.py`, `agent.py`, `ui.py` | High |
| 3.2 | **Structured tool-call output for OpenAI-compatible** — some OpenAI-compat models support JSON mode / structured output. Offering `response_format` could improve tool-call reliability on weaker models. | `provider.py` | Low |
| 3.3 | **Dynamic model pricing** — the hardcoded `_PRICES` table in `pricing.py` goes stale. Consider fetching prices from an API (e.g. OpenRouter's `/models` endpoint returns pricing) or at least warning the user the prices are estimates. | `pricing.py` | Medium |
| 3.4 | **Add Ollama as a preset** — Ollama is a common local-model runner with an OpenAI-compatible API at `http://localhost:11434/v1`. Adding it to `PRESETS` with `key_env="OLLAMA_API_KEY"` (or a dummy) would reduce setup friction for local models. | `config.py` | Low |
| 3.5 | **Provider health check** — add a `/ping` command or automatic connectivity test on startup so users don't type a long prompt only to discover the key is expired. | `cli.py`, `provider.py` | Low |

---

## 4. Agent Loop Intelligence

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 4.1 | **Smarter compaction** — currently summarizes everything between head and tail indiscriminately. Prioritize keeping *decisions*, *file paths*, and *error messages* over verbose tool output. The summarization prompt could be tuned. | `compaction.py` | Medium |
| 4.2 | **Token-budget-aware tool results** — `_MAX_READ_CHARS` is 60K but a single large file could blow the context. Truncate tool results relative to remaining context budget, not a fixed limit. | `tools.py`, `agent.py` | Medium |
| 4.3 | **Parallel tool calls** — when the model requests multiple independent tools (e.g. read two files), run them concurrently with `concurrent.futures` instead of sequentially. | `agent.py` | Medium |
| 4.4 | **Retry-on-repair loop** — when `promote()` recovers a plain-text tool call, the model gets nudged to use proper format, but there's no limit on how many times this can happen per turn. Add a counter and give up after 2-3 recoveries. | `agent.py` | Low |
| 4.5 | **Context-aware step budget** — `_MAX_STEPS = 50` is a flat cap. Dynamically adjust based on remaining context headroom: slow down as context fills up, forcing compaction or a sooner stop. | `agent.py` | Low |

---

## 5. Knowledge Base

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 5.1 | **Auto-scaffold on first use** — when a user starts kbcode on a project with no `kb/`, prompt "Want me to build the knowledge base?" instead of just creating empty templates. | `cli.py`, `knowledge_base.py` | Low |
| 5.2 | **Note diffing** — before `kb_write()` overwrites a note, show a diff and ask for approval (like file edits). Prevents accidental knowledge loss. | `tools.py`, `knowledge_base.py` | Low |
| 5.3 | **Pointer check on write** — `check_pointers()` runs at end-of-turn, but a `kb_write` that introduces a bad pointer could be caught immediately. | `knowledge_base.py`, `tools.py` | Low |
| 5.4 | **Search within KB** — add a `kb_search` tool so the model can find which note covers a topic without reading all notes (important as the KB grows). | `knowledge_base.py`, `tools.py` | Low |
| 5.5 | **Note versioning** — track note revisions in the shadow git (or a simple backup folder) so `kb_write()` mistakes can be undone. | `knowledge_base.py`, `checkpoints.py` | Medium |

---

## 6. Security & Safety

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 6.1 | **Sandbox `run_command`** — currently commands run with full user privileges. Consider optional `docker`/`bubblewrap` sandboxing or at least a configurable blocklist of dangerous commands (`rm -rf /`, `chmod 777`, etc.). | `tools.py` | High |
| 6.2 | **Redaction audit log** — when `redact.py` masks something, log a count so the user knows secrets were caught (without revealing them). Currently masking is silent. | `redact.py`, `ui.py` | Low |
| 6.3 | **Path traversal guard for absolute paths** — `_resolve()` honors absolute paths as-is, which is by design, but there's no warning when the model writes to `/etc/`, `/usr/`, or other system directories. Add a warning (not a block) for clearly system-level paths. | `tools.py` | Low |
| 6.4 | **Rate-limit `run_command`** — a runaway agent loop could fire 50 commands in one turn. Add a per-turn command count limit (e.g. 10) as a safety rail. | `agent.py`, `tools.py` | Low |
| 6.5 | **Secrets scanning before model call** — redaction only catches *output*. If the model's *response* contains what looks like a user secret it inferred, flag it rather than storing it in the session transcript. | `agent.py`, `redact.py` | Medium |

---

## 7. User Experience

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 7.1 | **Streaming output** (see 3.1) — the single biggest UX win. Users currently stare at a spinner for 5-30 seconds. | `provider.py`, `agent.py`, `ui.py` | High |
| 7.2 | **Diff preview before edits** — show the user a colored diff of what `write_file`/`edit_file` will change, like Claude Code does, instead of just "write file.py (N chars)". | `ui.py`, `tools.py` | Medium |
| 7.3 | **Undo confirmation** — `/rollback` could show a one-line summary of what will change before asking which checkpoint. The interactive menu is good but a preview of *files affected* would help. | `checkpoints.py`, `cli.py` | Low |
| 7.4 | **Syntax-highlighted tool results** — `_tool_read_file` returns plain `line\ttext`. Render it with `rich.syntax.Syntax` for code files based on extension. | `ui.py`, `tools.py` | Low |
| 7.5 | **Context usage bar in prompt** — show a compact `█░░ 15%` indicator in the prompt area so the user always knows how close to compaction they are, without running `/status`. | `ui.py`, `prompt_input.py` | Low |
| 7.6 | **Command history persistence** — `prompt_toolkit` supports history files. Persist input history across sessions (`.kbcode/history`) so up-arrow recalls previous prompts. | `prompt_input.py` | Low |
| 7.7 | **`/cost` shortcut** — `/insights` is verbose. Add `/cost` as a one-liner alias showing just `model · tokens · $X.XX`. | `cli.py` | Low |
| 7.8 | **Multiline input** — currently there's no way to paste or type multiline messages cleanly. Bind Shift+Enter or support `"""` triple-quote blocks. | `prompt_input.py` | Medium |

---

## 8. Session & Memory Management

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 8.1 | **Session search** — `/sessions` only lists by date. Add full-text search across session transcripts so users can find "that conversation about the auth bug". | `sessions.py`, `cli.py` | Medium |
| 8.2 | **Session export** — let users export a session as markdown (for sharing or documentation). | `sessions.py`, `cli.py` | Low |
| 8.3 | **Memory pruning** — the `memories` table grows forever. Add a `/memory-prune` that deduplicates similar entries or ages out old ones. | `memory.py`, `cli.py` | Medium |
| 8.4 | **Memory categories** — `kind` column exists but is always `'note'`. Use it to distinguish `decision`, `preference`, `bug`, `todo` and let `recall()` filter by kind. | `memory.py`, `tools.py` | Low |
| 8.5 | **Skill versioning** — `save_skill` does `INSERT OR REPLACE`. Track skill evolution so the user can see how a how-to changed over time. | `memory.py` | Low |

---

## 9. Extensibility

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 9.1 | **Plugin system for tools** — let users drop `.py` files in `.kbcode/tools/` that register new tool schemas + handlers. Would let power users add project-specific tools (e.g. "deploy to staging") without forking. | `tools.py`, new loader | High |
| 9.2 | **Hook system** — expose pre/post hooks for tool execution (e.g. "always lint after writing a .py file"). Could be `.kbcode/hooks.json` or a simple Python callback. | `tools.py`, `agent.py` | High |
| 9.3 | **Custom system prompt fragments** — currently AGENT.md and standing-orders.md are the only user-authored prompt inputs. Allow `.kbcode/prompts/*.md` files that get appended in sorted order. | `prompts.py`, `cli.py` | Low |
| 9.4 | **MCP (Model Context Protocol) support** — integrate MCP servers as tool providers, letting kbcode use community-built tools without writing Python. | `tools.py`, new `mcp.py` | High |

---

## 10. Performance & Efficiency

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 10.1 | **Lazy imports** — `import anthropic` and `from openai import OpenAI` happen at class construction time. Move them to `complete()` so kbcode starts faster when only one provider is used. | `provider.py` | Low |
| 10.2 | **Incremental KB reading** — `read_all()` concatenates every note into the system prompt every turn. Cache the result and only rebuild when `kb_write` is called. | `knowledge_base.py`, `prompts.py` | Low |
| 10.3 | **Search indexing** — `search_code` does a full `os.walk` + regex scan on every call. For large projects, build a file index or use `ripgrep` (`rg`) when available. | `tools.py` | Medium |
| 10.4 | **Checkpoint batching** — `ensure_checkpoint` runs `git add -A` + `git write-tree` before every first edit in a turn. For multi-file edits, batch into one checkpoint at turn start instead of per-tool-call. | `checkpoints.py` | Low |
| 10.5 | **Session file compaction** — JSONL session files grow unbounded. Periodically compact old sessions into a summary record (similar to chat compaction) to keep `/sessions` fast. | `sessions.py` | Medium |

---

## 11. Documentation

| # | Suggestion | Files | Effort |
|---|-----------|-------|--------|
| 11.1 | **User-facing README** — the current `README.md` is minimal. Add installation steps, screenshots/GIF, feature list, and a quick-start guide. | `README.md` | Low |
| 11.2 | **Contributing guide** — `CONTRIBUTING.md` with setup instructions, coding standards, and PR workflow. | `CONTRIBUTING.md` | Low |
| 11.3 | **Docstrings** — most public methods have them, but `Tools._tool_*` methods and several `cli.py` helpers don't. Add them for maintainability. | various | Low |
| 11.4 | **Architecture decision records** — key design choices (shadow git, normalized message format, two-layer repair) deserve short ADRs explaining *why*, not just *what*. | `docs/adr/` | Medium |

---

## Quick Wins (do these first)

These are low-effort, high-impact items that don't require major refactoring:

1. **Add `pytest` + a few test files** for `repair.py`, `redact.py`, `pricing.py` (#1.1)
2. **GitHub Actions CI** with `ruff` lint + `pytest` (#1.4)
3. **Ollama preset** in `config.py` (#3.4)
4. **`/cost` shortcut** (#7.7)
5. **Command history file** (#7.6)
6. **Multiline input** support (#7.8)
7. **Redaction audit count** (#6.2)
8. **Lazy provider imports** (#10.1)
9. **Note diff preview before `kb_write`** (#5.2)
10. **README with screenshots** (#11.1)

---

*Generated from a full read of the kbcode v1.4.2 codebase (24 modules, ~3,700 lines).*
