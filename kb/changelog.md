# Changelog — notable changes, newest first.

The ONLY place release history lives (don't duplicate it in other notes).

## KB audit — 2026-07-01
`tools/kb-check.sh --fix`/`--freshness` reported 0 broken/stale/drift (133
pointers). Manual spot-check of ~60 `Name (path:line)` pointers (name-match not
covered by the checker for that style) found one real miss: `architecture.md`
named `_repl()` where the function is `repl()` — fixed. Added `wizard.py` to
the component list (existed in code, missing from the map) and documented the
new `.claude/hooks/kb_*.py` enforcement hooks in `about-kb.md` (committed this
session, undocumented). No other drift found.

## v1.6.1 (current)
- Fix packaging: `pyproject.toml` only declared the top-level `kbcode`
  package, so the `tools/` subpackage (split out of `tools.py` in v1.6.0)
  was silently missing from every `pip install`, making `kbcode`/`kb` crash
  on launch with `ModuleNotFoundError: No module named 'kbcode.tools'`.
  Switched to `[tool.setuptools.packages.find]` so all `kbcode*` subpackages
  are always included.

## v1.6.0
- pytest suite (~211 tests) + GitHub Actions CI across Python 3.10/3.12 on
  Ubuntu/Windows.
- Streaming responses for both Anthropic and OpenAI-compatible providers
  (`provider.py` `stream()`).
- Safety rails: dangerous-command blocklist, per-turn `run_command` limit,
  system-path write warnings, colored diff previews before
  `write_file`/`edit_file`/`kb_write`.
- `kb_search`, memory kind filtering + `/memory-prune`, session full-text
  search + `/export`, `/cost`, `/ping`, an Ollama preset.
- Parallel execution for read-only tool calls, a context-aware step budget,
  token-budget-aware file reads, ripgrep-accelerated search, cached KB reads,
  batched checkpoints.
- Custom prompt fragments (`.kbcode/prompts/`), redaction audit counts,
  persistent command history, multi-line input.
- `tools.py` split into a `tools/` package; `cli.py` split into
  `cli.py` + `repl.py` + `wizard.py`.
- System prompt now tells the model to answer broad "read/explain the
  codebase" requests from `kb_read()`/`list()` instead of opening every
  source file in one turn (fixes a mid-turn emergency-stop on such prompts).

## v1.5.0
- Tool-execution spinner (`ui.tool_running()`) — a running command no longer
  looks stalled between the `⏺ Run …` line and its result.
- Every spinner (`thinking`/`tool_running`/`working`) now ticks up its own
  elapsed seconds live, plus a `(total …s)` counter that keeps running across
  the whole turn instead of resetting per step (`ui._TickingStatus`,
  `Agent.run` calls `ui.turn_started()`).
- `Read` tool-call lines now show the full resolved path, matching
  `Write`/`Edit` (`ui._describe_tool`).

## v1.4.2
- Knowledge base scaffolded with full project notes.
- See `kbcode/__init__.py:9`.
