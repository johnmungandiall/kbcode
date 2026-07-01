# Changelog — notable changes, newest first.

The ONLY place release history lives (don't duplicate it in other notes).

## v1.9.3 (current)
- **Parallel reads inside subagents + faster code-explorer** — subagents now
  batch consecutive `parallel_safe` tools (`read_file` + `list_dir` + `search_code`
  etc.) using `_run_subagent_parallel_batch`, the same way the main loop does.
  Updated default `.kbcode/agents/code-explorer.md` to use a narrow parallel-safe
  tool list and explicit instructions to request multiple reads together. This
  greatly reduces LLM round-trips for exploration tasks on slow models.
  Documentation updated in [[modes-subagents]] and `subagents.py`.
- **Higher `run_command` safety cap** (`kbcode/tools/file.py`) — raised
  `_MAX_COMMANDS_PER_TURN` from 10 to 25 so realistic build/check/fix
  workflows ("flutter analyze", multi-step verification, logs + retries, etc.)
  no longer immediately hit the "runaway loop guard" and force an early turn
  wrap-up. The guard and the "wrap up and continue in next message" message
  remain for true loops. Tests now import the constant to avoid drift; README
  and [[gotchas]] updated. (User-visible fix → version bump per rules.)

## v1.9.1
- **`kbcode update` now actually delivers new code** (`kbcode/cli.py`
  `_self_update`) — the old command ran a bare `pip install --upgrade
  git+URL`, which pip treats as "already satisfied" (a silent no-op) whenever
  `__version__` is unchanged, so any fix pushed to GitHub without a version
  bump never reached installed users even though the update "succeeded". They
  stayed on stale code while a dev running `python -m kbcode` from the updated
  source tree saw the fix — the classic "works from source, broken when
  installed" report. Now runs two pip steps: a normal `--upgrade` (to pick up
  new/bumped deps) then `--upgrade --force-reinstall --no-deps --no-cache-dir`
  on kbcode itself so the current GitHub HEAD is rebuilt every time regardless
  of the version string. README's "Update & version" section documents a
  one-time manual `--force-reinstall` for users stuck on ≤ 1.9.0 (whose old
  update command can't self-heal until they bump past the no-op). See
  [[cheatsheet]].

## v1.9.0
- **System prompt now stamps the current date/time** (`kbcode/prompts.py`) —
  `build_system_prompt()` injects a `## Current date & time` section
  (`datetime.now()`, injectable via a `now:` kwarg for tests) telling the
  model its training data can be stale and to use `web_search` instead of
  guessing for news/current-events/recent-version/price questions. Fixes the
  model composing search queries with a guessed, wrong-year date. See
  [[tools-and-repair]].
- **Configurable hooks timeout** (`kbcode/hooks.py`) — `HooksRunner`'s
  per-command `subprocess` timeout (30s default) can now be overridden via a
  `"timeout"` key in the `"hooks"` block of `.kbcode/settings.json` (e.g.
  `"hooks": {"timeout": 60, "PreToolUse": [...]}`); an explicit constructor
  arg still wins (used by tests). No caller changes needed since
  `ToolsCore.__init__` already builds `HooksRunner(config.hooks, self.root)`
  without passing a timeout. See [[safety]].
- **Concurrent `run_subagent` dispatch** (#4.3 extension, `kbcode/agent.py`) —
  a run of 2+ consecutive `run_subagent` calls now dispatches concurrently
  (same `ThreadPoolExecutor`/`_PARALLEL_MAX_WORKERS` mechanism as the
  existing read-only-tool batching), but only when every targeted subagent's
  `tools:` frontmatter is a subset of the schema-declared `parallel_safe`
  tool set (`Agent._subagent_parallel_safe`) — the default `tools: read`
  does not qualify. `Agent._record_usage()` is now lock-guarded
  (`Agent._usage_lock`) since usage can be recorded from multiple subagent
  pool threads at once; `_run_subagent()` gained a thread-local quiet flag
  (`Agent._quiet_subagents`) so its inline UI output is suppressed when
  running inside a parallel batch, byte-for-byte unchanged on the normal
  sequential path. No new tool, no schema change, no LLM call added. See
  [[tools-and-repair]], [[modes-subagents]].
- **Hooks system** (`kbcode/hooks.py`, the Claude Code idea) —
  PreToolUse/PostToolUse/Stop tool-call interception via a `"hooks"` key in
  `.kbcode/settings.json`, reimplementing Claude Code's public documented
  hooks contract (JSON-over-stdin, exit-code protocol: 0 allow / 2 block /
  other non-fatal) from scratch. `ToolsCore` builds a `HooksRunner` per
  project; `Agent._dispatch_tool()` wraps every tool call (6 call sites as
  of the concurrent-subagent extension above, including subagent
  delegation) with Pre/PostToolUse, and `Agent._stop_hook_feedback()` lets a
  `Stop` hook veto ending a turn. See [[safety]].

## v1.8.0
- **`web_search` tool** (`kbcode/tools/web.py`) — the Hermes web-search idea,
  right-sized to one backend instead of its multi-provider plugin registry.
  DuckDuckGo search via the free `ddgs` package, no API key needed.
  Read-only/`parallel_safe`, available in every mode's `READ` group. A
  throwaway single-worker thread pool enforces a hard 20s timeout since
  `ddgs` can't be cancelled mid-call (see [[gotchas]]). `ddgs>=9.0` is now a
  hard dependency.

## v1.7.0
Three review-driven improvements (none is a bug fix; the "bug" findings they came
with were verified false against the code):
- **#6 parallel-safe tools are now schema-declared.** Each pure-read tool carries
  `"parallel_safe": True` (`tools/schemas.py`); `Agent` reads the set via
  `ToolsCore.parallel_safe_tools` instead of a hardcoded list, so a new read-only
  tool can't silently run sequential. `AnthropicProvider._api_tools` strips the
  flag before the request (OpenAI path already rebuilds tools).
- **#5 diagnostic file log.** `logs.py` `setup_logging()` writes a quiet rotating
  log at `.kbcode/kbcode.log` (`KBCODE_LOG_LEVEL`, default INFO; off/none = none).
  Wired in `cli.py`; silent swallow points (checkpoints, compaction, tool errors)
  now log with `exc_info`.
- **#9 file-path autocomplete** for `/open`/`/image`/`/video` (`PATH_COMMANDS` +
  `_path_completions` in `prompt_input.py`), on top of slash-command completion.

## KB audit — 2026-07-01
`tools/kb-check.sh --fix`/`--freshness` reported 0 broken/stale/drift (133
pointers). Manual spot-check of ~60 `Name (path:line)` pointers (name-match not
covered by the checker for that style) found one real miss: `architecture.md`
named `_repl()` where the function is `repl()` — fixed. Added `wizard.py` to
the component list (existed in code, missing from the map) and documented the
new `.claude/hooks/kb_*.py` enforcement hooks in `about-kb.md` (committed this
session, undocumented). No other drift found.

## v1.6.3
- Fix "agent freezes for minutes" on slow/stalled providers (esp. MiMo + a
  subagent making many calls): the SDK clients were built with no request
  timeout, so a stalled call inherited the SDK's ~600s default. Added
  `Config.request_timeout` (default 120s, `KBCODE_REQUEST_TIMEOUT`, 0 = off),
  passed to both provider clients via `LLMProvider._client_kwargs()`; the
  resulting timeout is transient so `_with_retry` backs off and retries.
- Fix "can't type after a reply" (intermittent, Windows-visible): the Esc
  watcher (`interrupt_on_escape`) only signalled its daemon thread at turn end
  without joining it, so the watcher kept reading the console and raced the next
  prompt for stdin, eating the first keystrokes (POSIX: could leave cbreak). Now
  it `thread.join()`s before returning. Also made `_TickingStatus.stop()`
  lock-guarded so the worker + main thread can't tear the spinner's Rich `Live`
  down at once. Regression test: `tests/test_interrupt.py`.

## v1.6.2
- Fix streamed replies rendering as shredded line-fragments (only the tail of
  each line survived — hit tables and plain prose alike). The thinking spinner
  is a Rich `Live` region redrawn from a background ticker thread; leaving it
  live while reply text streamed in from the provider worker thread meant two
  threads wrote the terminal at once and the spinner's redraw stomped each
  half-printed line. `ui.stream_chunk` now stops the spinner on the first token
  (`_TickingStatus.stop`, idempotent + thread-safe) so only one writer remains.

## v1.6.1
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
