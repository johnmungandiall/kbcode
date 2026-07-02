# Gotchas — traps specific to this repo. Read before editing.

## Anthropic SDK kwargs
- the staged `attempts` list in `complete` (`kbcode/provider.py`) conditionally tries thinking + output_config.effort (plus temperature) only if thinking != "off"; falls back for older SDKs (see [[providers]])
- An older SDK rejects newer kwargs via `TypeError`, caught and retried with simpler params — don't let `_with_retry` swallow it, it deliberately re-raises `TypeError`

## Threaded provider calls
- `kbcode/agent.py:126-164` — `Agent._complete()` runs the HTTP request on a daemon thread so Esc works mid-request (see [[providers]])
- Don't assume `KeyboardInterrupt` is only raised between Python statements

## Session replay requires matching provider
- `kbcode/cli.py:192-200` — `_resume_agent` restores the recorded provider/model from session meta
- If the recorded provider isn't configured, it falls back to the current one with a warning

## JSON serialization of SDK objects
- `kbcode/sessions.py:58-86` — `_jsonable()` handles pydantic models, dataclasses, and plain types
- New Anthropic SDK content-block shapes need `model_dump(mode="json")` fallback

## Tool-call repair is two layers
- `kbcode/tools/core.py:139` — `_repair()` fixes name typos + missing required args (execute-time)
- `kbcode/repair.py:48` — `promote()` recovers tool calls written as plain text (parse-time)
- Both layers only work for names the mode/subagent actually offers — see [[tools-and-repair]], [[modes-subagents]]

## Protected files
- `kbcode/tools/file.py:118-136` — `_protected_reason()` refuses writes to `.git/`, `.ssh/`, `.env`, secrets
- `.env.example` and `.gitignore` are explicitly allowed — see [[safety]]

## Compaction token estimate
- `kbcode/compaction.py:47-64` — `estimate_tokens()` uses ~4 chars/token + flat 1300/image
- This is rough; don't rely on exact counts — see [[context-management]]

## `tools.py` no longer exists
- Split into the `kbcode/tools/` package in v1.6.0 ([[changelog]]); a stray
  `kbcode/tools.py:<line>` pointer anywhere in this KB is drift — fix it to the
  actual submodule (`core.py`/`file.py`/`kb.py`/`memory.py`/`planning.py`/
  `subagent.py`/`schemas.py`)

## Streamed text must stop the thinking spinner first
- The thinking()/working() spinner is a Rich `Live` region redrawn every 100ms by a
  background ticker thread (`_TickingStatus._tick`, `kbcode/ui.py:254`). Streamed
  reply text arrives via `on_text` on the *provider worker thread*
  (`kbcode/agent.py:150`). Two threads writing the terminal at once = the spinner's
  redraw stomps the half-printed line, shredding any multi-line reply into trailing
  fragments (was true for tables AND plain prose).
- Fix: `stream_chunk` (`kbcode/ui.py:477`) calls `_active_status.stop()`
  (`kbcode/ui.py:293`) on the first token, so from then on only the worker thread
  prints. Don't re-introduce a spinner that stays live during streaming.
  `stream_tool_hint` (`kbcode/ui.py:502`) follows the same rules — spinner
  stopped first, half-printed stream line closed via `_stream_open`.
- `stop()` is called from BOTH the worker thread (via `stream_chunk`) and the main
  thread (the `with thinking()` exit), so its check-and-tear-down is guarded by
  `self._stop_lock` — without it both callers can pass the `_stopped` check and
  tear the Rich `Live` down twice at once, corrupting the terminal. Keep it locked.
- Replies are still streamed raw, not markdown-rendered — `assistant_text`'s
  `Markdown()` (`kbcode/ui.py:473`) is not used on the streaming path.

## Every `_TOOL_DESCRIBERS` entry must be a CALLABLE, not a label string
- `_describe_tool` (`kbcode/ui.py:213`) does `describer(a, g, full)`. Registering a
  bare string (e.g. `"repo_map": "get codebase structure map"`) makes that call
  raise **`'str' object is not callable`** the moment the agent uses that tool —
  it crashes the whole tool-call render, not just the label. This bit `edit_files`
  and `repo_map` when they were added. Add a real `_describe_<tool>(a, g, full)`
  returning `(verb, target)`. A `not callable` guard in `_describe_tool` now degrades
  a stray string to a static label, but don't rely on it — write the function.

## The Esc watcher must be JOINED at turn end, not just signalled
- `interrupt_on_escape()` (`kbcode/interrupt.py:26`) runs a daemon thread that reads
  the console (Windows `msvcrt.getwch`) / holds the tty in cbreak (POSIX). Its
  `finally` does `stop.set()` **and** `thread.join(timeout=0.5)` (`kbcode/interrupt.py:47-48`).
- The join is load-bearing: without it the watcher outlives the turn and races the
  *next* prompt for stdin — stealing the user's first keystrokes so they "can't type
  after a reply" (intermittent, ~50ms poll window), or leaving POSIX in cbreak. Don't
  drop the join back to a bare `stop.set()`. Regression test: `tests/test_interrupt.py`.

## Tool-schema metadata must be stripped before the API
- Schemas may carry kbcode-only keys (currently `parallel_safe`, #4.3) that the
  model tool APIs reject as unknown. The OpenAI path is safe (it rebuilds each
  tool in `_tools`), but `AnthropicProvider` otherwise forwards `tools` verbatim
  — so `complete`/`stream` route through `_api_tools` (`kbcode/provider.py`),
  which keeps only name/description/`input_schema`.
- Add a new schema-level metadata key → confirm it's dropped for Anthropic
  (extend `_api_tools`), or Claude requests 400. See [[providers]], [[tools-and-repair]].

## Cache breakpoints must never leak into stored messages
- `AnthropicProvider._add_cache_breakpoints` (`kbcode/provider.py:238`) mutates
  the **native** message list, which is safe only because `_to_native` builds
  user-role dicts fresh on every call. Two ways to break it:
  1. Mark an **assistant** message — its `content` is the stored `raw` SDK
     blocks, so the marker would persist and replay on every later request.
  2. Make `_to_native` start *reusing* stored dicts for user/tool_results
     messages — markers would then accumulate in `Agent.messages`, and the API
     rejects a request carrying **more than 4** `cache_control` breakpoints.
- Also: the system prompt already spends 1 of the 4 breakpoints, so
  `_MESSAGE_CACHE_BREAKPOINTS` must stay ≤ 3. Regression tests:
  `tests/test_provider_caching.py` (accumulation + assistant-raw cases).
  See [[providers]].

## Anthropic stream iterates EVENTS, not text_stream
- `AnthropicProvider.stream`'s `do_stream` (`kbcode/provider.py:349`) iterates
  the SDK stream context itself — synthetic `"text"` events carry deltas,
  `content_block_start` events carry tool names for `on_tool` hints. Don't
  "simplify" it back to `stream_ctx.text_stream`: that silently drops the
  tool-name hints. The fakes in `tests/test_provider_streaming.py` yield
  event objects for the same reason.

## web_search uses a throwaway thread pool, not a shared one
- `kbcode/tools/web.py:39` — `_tool_web_search` can't cancel a blocking `ddgs`
  call on timeout, and `ddgs`'s own per-request timeout doesn't bound its
  internal multi-engine retry loop. A shared pool would let one hung search
  serialize every later search behind it.
- Fix: a fresh single-worker `ThreadPoolExecutor` per call, with
  `shutdown(wait=False, cancel_futures=True)` in `finally` so the hung worker
  thread is abandoned (leaked, not killed — Python can't kill threads) instead
  of blocking the tool call. Don't switch this to a shared/module-level pool.

## Hook commands run with full shell privileges, unsandboxed
- `kbcode/hooks.py:85` — `HooksRunner._run_one()` runs a configured hook's
  `command` via `subprocess.run(shell=True, ...)` — same trust model as
  Claude Code's own hooks. A malicious or careless hook script in
  `.kbcode/settings.json` can do anything a shell can do (no allowlist, no
  sandbox). See [[safety]].

## `_run_subagent`'s inline UI calls must stay quiet-flag-gated
- `kbcode/agent.py:631` — `_run_subagent()` is used both sequentially (main
  thread, normal path) and concurrently, one call per pool worker thread, from
  `_run_subagents_parallel_batch()` (`kbcode/agent.py:407`) via
  `_quiet_dispatch()` (`kbcode/agent.py:428`), which sets the per-thread
  `Agent._quiet_subagents.on` flag. Every inline `ui.notice`/`ui.tool_call`/
  `ui.tool_result`/`ui.tool_running()` call inside `_run_subagent()` checks
  `quiet` first — TerminalUI's Rich `Live`-backed spinner isn't safe to have
  two open at once, so an unguarded UI call added later will corrupt the
  terminal when multiple subagents run in parallel. If you add a new inline
  UI call inside `_run_subagent()`, gate it on `quiet` too. See
  [[tools-and-repair]], [[modes-subagents]].
- Related: `Agent._record_usage()` (`kbcode/agent.py:586`) is guarded by
  `Agent._usage_lock` since #4.3's `run_subagent` extension can call it from
  multiple threads at once — don't reintroduce an unguarded `self.usage[...]`
  mutation elsewhere.
- Inside subagents, consecutive parallel-safe reads are now batched too
  (`_run_subagent_parallel_batch`, up to 16 workers). To get Cursor-like speed,
  explorer subagents must declare narrow parallel-only `tools:` lists and be
  strongly instructed to batch many reads per LLM response (see updated
  `code-explorer.md` and [[modes-subagents]]). The system prompt now tells the
  main agent the same rule.
- search_code now supports optional "limit" (default 50) and the prompts strongly
  require using "path" scoping + repo_map first for any cross-directory work
  (e.g. broker comparisons) to prevent loops. repo_map improved to use rg when
  available and limit symbols per file.

## Displaying a path relative to root breaks outside the project
- `kbcode/tools/file.py:371` — `_tool_search_code` formats each hit through
  `self._display_path(fp)` (`kbcode/tools/core.py:170`), **not** a raw
  `fp.relative_to(self.root)`. kbcode isn't sandboxed to the project folder
  (`_resolve` honors absolute paths, see [[tools-and-repair]] and
  [[kbcode-write-anywhere]] intent), so a search/list base can point outside
  `root`. `Path.relative_to(self.root)` raises `ValueError` ('... is not in the
  subpath of ...') on a file that isn't under `root` — and that ValueError is
  **not** caught by search's `except (UnicodeDecodeError, OSError)`, so it aborts
  the whole tool on the first hit (this is what broke every search against a
  parent/sibling project). `_display_path` returns relative-when-inside,
  absolute-otherwise. Any new tool that displays a resolved path must use it,
  never a bare `relative_to`. Regression test: `tests/test_tools_search.py`
  (`test_search_code_outside_project_shows_absolute_path`).

## Compaction must shrink the *last* exchange too, not just the middle
- `kbcode/compaction.py:146` — `_compact_within_last_exchange()` is the second
  pass of `compact()`. The first pass (`_compact_exchanges`) summarizes whole
  *middle* exchanges and always protects the most recent one — but a turn that
  runs many tool round-trips and hits the step limit (`Agent.max_steps`,
  default `_MAX_STEPS = 50`, `kbcode/agent.py:26`; `KBCODE_MAX_STEPS` tunes
  it) is a **single** exchange (one user turn + ~50
  assistant/tool_results pairs). Pass 1 can't touch it, so `/compact`
  (`Agent.compact_now`) and mid-turn auto-compaction did nothing after a
  step-limit stop — the classic "`/compact` is broken" report.
- The within-exchange cut MUST land on an assistant boundary and drop only
  whole (assistant, tool_results) pairs, or you orphan a `tool_results` (a
  provider 400: every tool_use needs its matching tool_result, see
  [[providers]]). Don't "simplify" it into a raw slice. Regression tests:
  `tests/test_compaction.py` (`test_compact_shrinks_a_single_runaway_exchange`,
  `test_runaway_compaction_preserves_alternation_and_tool_pairing`).
- Note the step limit itself is a flat cap: `actions` can read *above*
  `max_steps` in the "hit the step limit" notice because a parallel batch adds
  `len(batch)` per loop iteration (`kbcode/agent.py:312`), and the turn-summary
  "~N tokens" is *cumulative* usage across the turn's API calls, not the context
  size. See [[context-management]].

## Avoiding search/exploration loops
- When doing comparisons across directories (e.g. similar functions in broker/kotak vs broker/zerodha), the agent must start with `repo_map` (scoped to subdirs) then use `search_code` with the `path` argument for narrow, targeted searches. Batch different scoped searches in one step. Stop and summarize as soon as the pattern is found — do not repeat similar searches. Updated BASE_SYSTEM, search_code description, and code-explorer instructions enforce this (see prompts.py and schemas.py). This prevents the repetitive search loops that previously caused long-running or "stuck" turns.

## run_command + pipes = infinite hang (Windows especially)
- NEVER capture a shell command's output with pipes
  (`subprocess.run(capture_output=True)`) in run_command-like code: a
  grandchild that outlives the direct child (explorer.exe after `taskkill &&
  start explorer.exe`, any backgrounded server) inherits the pipe handles, and
  the read blocks on EOF *forever* — `subprocess.run`'s own post-timeout
  cleanup does exactly this blocking read, so even `timeout=180` sailed past
  3000s in the field. Fixed (2026-07-02) by writing output to temp files +
  `proc.wait(timeout)` + `_kill_process_tree()` — see [[safety]] and
  `kbcode/tools/file.py:399`.

## run_command per-turn limit (runaway guard)
- `kbcode/tools/file.py:399` — `_tool_run_command` caps calls per turn at
  `Config.max_commands_per_turn` (default `DEFAULT_MAX_COMMANDS = 25`,
  `kbcode/config.py:116`; `KBCODE_MAX_COMMANDS` tunes it). It increments a
  per-turn counter (reset in `ToolsCore.new_turn`, called at start of every
  `Agent.run`). Exceeding it raises: "Refused: hit the safety limit of N
  run_command calls in one turn (a runaway loop guard)..."
- Intended to stop infinite `ls` / `echo` / pointless loops. Real tasks (e.g.
  "check for compilation errors", analyze + build + targeted checks + logs +
  retries) legitimately need more than a tiny budget inside one user message.
  When hit, the model is told to wrap up the turn; user can continue in next
  message — or raise `KBCODE_MAX_COMMANDS` in `.env` so long tasks pause less
  often. The count is shared with any `run_subagent` (they use the same
  `Tools` instance). Related to (and can combine with) the `max_steps` cap.
  See [[safety]], [[tools-and-repair]], [[config]].

## Vision-fallback candidate order matters
- `kbcode/vision_fallback.py:43` — `_candidates()` only trusts the active provider's
  own key as an OpenRouter route when `base_url` verifiably contains
  `openrouter.ai`; some presets (`mimo`) alias `key_env` to
  `OPENROUTER_API_KEY` while `KBCODE_BASE_URL` points elsewhere, so trusting
  the env var name alone would silently 401 — see [[vision]]

## Runtime state lives in the user home; a legacy `.kbcode/memory.db` pins it local
- `Config.state_dir` (`kbcode/config.py:216`) — memory db, sessions/, checkpoints/,
  input history, and kbcode.log live at `~/.kbcode/projects/<slug>/` (Claude Code
  style), NOT in the project. Exception: a project carrying a legacy
  `.kbcode/memory.db` keeps the project-local `.kbcode` as its state dir —
  deleting that file silently switches the project to the (empty) home-dir
  location, "losing" its sessions/checkpoints/history. See [[config]].
- `KBCODE_HOME` overrides `~/.kbcode` and is read on every `def global_dir`
  call (`kbcode/config.py:307`) — set it BEFORE any Config path is touched (tests do,
  via the autouse fixture in `tests/conftest.py`), or state splits across two homes.
- The project `.kbcode/` (config only) self-hides via an auto-written `*`
  .gitignore (`_ensure_self_ignore`, `kbcode/config.py:294`) — an existing,
  user-customized `.kbcode/.gitignore` is deliberately never overwritten.

## `fix_pointers` anchors on the FIRST text match — verify its "fixes"
- `KnowledgeBase.fix_pointers()` (`kbcode/knowledge_base.py:243`) relocates a
  drifted pointer by searching the target file for the symbol named on the
  note line — but it takes the *first* line containing that text, which can
  be a docstring/comment mention or a class header instead of the actual
  `def`. Repeat offenders: `promote` → repair.py's module docstring,
  `AnthropicProvider.complete` → the class line, `global_dir` → a call site.
  After running it (or `/kb-check --fix`), eyeball every rewrite; phrasing a
  note line as `` `def promote`, `path:line` `` steers the anchor to the
  definition.

## MCP traps (see [[mcp]] for the full picture)
- **`mcpServers` is the ONLY settings key merged per-server (deep)** across
  home → launch → project (`kbcode/config.py:333-337`); every other key is a
  whole-value shallow override. Don't "unify" the merge loop — a shallow
  `mcpServers` override silently hides every home-level server the moment a
  project defines one of its own.
- **The tool list is a startup cache.** `tools/list` runs once in
  `MCPManager.start_all`; `tools/list_changed` notifications are discarded
  (`_read_stdout`, `kbcode/tools/mcp.py`). A server that grows a tool
  mid-session stays invisible until `/mcp reload` — that's UX, not a bug.
- **So is the server list**: `_build_agent` only starts servers that were in
  settings.json at launch. An `mcpServers` block added mid-session does
  NOTHING until `/mcp reload`, which re-reads the merged config
  (`load_mcp_servers()`, `kbcode/config.py:325`) and bootstraps the manager if
  needed — don't tell users a settings edit alone activates a server.
- **Requests are serialized per client** (`MCPClient._lock`). `read_only`
  servers get `parallel_safe` schemas, so pool threads CAN dispatch two calls
  at one server concurrently — without the lock their writes interleave on a
  single stdin pipe and corrupt the JSON-RPC stream. Don't remove it.
- **`parallel_safe: true` in server config is an alias for `read_only`**
  (`parse_mcp_configs`): skipping the permission prompt and concurrent
  dispatch are only safe under the same "never mutates" assertion, so they're
  deliberately one flag.
- **MCP servers run with full user privileges** — same trust model as
  `run_command` and hooks: no sandbox, the permission gate is the backstop.
  Old-agent leak is handled: `/provider`/`/open` rebuild goes through
  `Agent.close()` → `stop_all()`; don't bypass close() when adding rebuilds.

## `kbcode update` needs force-reinstall; bump `__version__` every release
- `kbcode/cli.py:50` — `_self_update()` installs from a moving git branch, not a
  pinned commit. A bare `pip install --upgrade git+URL` is a **silent no-op**
  when `__version__` is unchanged: pip sees the same version already installed
  and skips, so a fix pushed to GitHub without a version bump never reaches
  installed users (they stay stale while `python -m kbcode` from source shows
  the fix — "works from source, broken when installed"). Two guards, keep both:
  (1) `_self_update` runs a second `--force-reinstall --no-deps --no-cache-dir`
  step so HEAD is rebuilt regardless of version; (2) **always bump
  `kbcode/__init__.py` `__version__` in the same commit as any user-facing fix**
  so even the OLD update command upgrades. Fixed in v1.9.1 ([[changelog]]).
- Same family as the v1.6.1 packaging trap — see [[changelog]].

See [[conventions]] for general rules, [[about-kb]] for how traps get indexed here.
