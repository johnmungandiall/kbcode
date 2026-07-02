# Gotchas — traps specific to this repo. Read before editing.

## Anthropic SDK kwargs
- the staged `attempts` list in `complete` (`kbcode/provider.py`) conditionally tries thinking + output_config.effort (plus temperature) only if thinking != "off"; falls back for older SDKs (see [[providers]])
- An older SDK rejects newer kwargs via `TypeError`, caught and retried with simpler params — don't let `_with_retry` swallow it, it deliberately re-raises `TypeError`

## Threaded provider calls
- `kbcode/agent.py:132-169` — `Agent._complete()` runs the HTTP request on a daemon thread so Esc works mid-request (see [[providers]])
- Don't assume `KeyboardInterrupt` is only raised between Python statements

## Session replay requires matching provider
- `kbcode/cli.py:200-200` — `_resume_agent` restores the recorded provider/model from session meta
- If the recorded provider isn't configured, it falls back to the current one with a warning

## JSON serialization of SDK objects
- `kbcode/sessions.py:59-86` — `_jsonable()` handles pydantic models, dataclasses, and plain types
- New Anthropic SDK content-block shapes need `model_dump(mode="json")` fallback

## Tool-call repair is two layers (+ provider markers)
- `kbcode/tools/core.py:167` — `_repair()` fixes name typos + missing required args (execute-time), and turns the `_malformed_args`/`_args_cut_off` markers from `provider._parse_tool_args` (`kbcode/provider.py:46`) into precise guidance (budget-aware truncated-write coaching — see [[providers]])
- `kbcode/repair.py:48` — `promote()` recovers tool calls written as plain text (parse-time)
- Both layers only work for names the mode/subagent actually offers — see [[tools-and-repair]], [[modes-subagents]]
- The `_malformed_args`/`_args_cut_off` keys are RESERVED marker names: `_repair` intercepts them before any `_tool_*` method runs, and `ui.tool_call`/`tool_result` render them as a yellow retry note instead of a red error. Don't name a real tool argument with a leading underscore.
- NEVER put a broken arguments string into `raw["tool_calls"]`: strict servers (MiMo) parse every replayed `arguments` field and 400 the whole follow-up request ("unexpected end of data"), killing the repair round. `_replayable_args` (`kbcode/provider.py:68`) stores the marker dict as valid JSON; `_sanitize_raw` (`kbcode/provider.py:507`) guards old sessions on replay — see [[providers]]

## Mid-turn user messages must piggyback, never append a user message
- `Agent._deliver_user_notes()` (`kbcode/agent.py:689`) appends what the user
  typed mid-turn onto the round-trip's LAST tool result. Appending a separate
  `{"role": "user"}` message after `tool_results` instead would put two
  user-role messages back-to-back after `_to_native` — Anthropic rejects
  non-alternating roles (HTTP 400). Same trick as `_auto_fix_feedback`'s
  report, which is safe only because it's followed by another model call.

## Protected files
- `kbcode/tools/file.py:116-137` — `_protected_reason()` refuses writes to `.git/`, `.ssh/`, `.env`, secrets
- `.env.example` and `.gitignore` are explicitly allowed — see [[safety]]

## Compaction token estimate
- `kbcode/compaction.py:49-66` — `estimate_tokens()` uses ~4 chars/token + flat 1300/image
- This is rough; don't rely on exact counts — see [[context-management]]

## `tools.py` no longer exists
- Split into the `kbcode/tools/` package in v1.6.0 ([[changelog]]); a stray
  `kbcode/tools.py:<line>` pointer anywhere in this KB is drift — fix it to the
  actual submodule (`core.py`/`file.py`/`kb.py`/`memory.py`/`planning.py`/
  `subagent.py`/`schemas.py`)

## Only ONE thread may write the terminal — spinner vs. mid-turn prints
- The thinking()/working() spinner is a Rich `Live` region redrawn every 100ms by a
  background ticker thread (`_TickingStatus._tick`, `kbcode/ui.py:309`). Anything
  that *prints* from another thread while it's live (the old raw chunk streaming
  did; `stream_tool_hint` still does) shreds output into trailing fragments —
  so every mid-turn printer stops `_active_status` first.
- Since v1.15.0 `stream_chunk` (`kbcode/ui.py:543`) does NOT print chunks at all:
  it buffers a char count and feeds `set_progress()` (`kbcode/ui.py:293`) so the
  spinner shows `writing… N chars`, and `Agent.run` renders the COMPLETE reply as
  markdown via `assistant_text` (`kbcode/ui.py:535`) once the response resolves
  (`kbcode/agent.py:296`). Don't reintroduce raw chunk printing — it both
  races the spinner and makes markdown rendering impossible.
- `stream_tool_hint` (`kbcode/ui.py:604`) no longer prints AT ALL: it (and
  `stream_tool_args`, `stream_thinking`) only relabel the live spinner from the
  worker thread. The old print-and-stop-the-spinner behavior left NOTHING
  moving while a big write call streamed its arguments — the "write looks
  stuck" complaint. Don't reintroduce a worker-thread print here.
- The spinner's `_render` also appends `ui.live_note()` (set by the REPL) —
  the type-ahead echo + auto-mode line. It's POLLED by the ticker (100ms), so
  the watcher thread never touches the terminal either.
- `stop()` can be called from worker AND main threads, so its check-and-tear-down
  is guarded by `self._stop_lock` — without it both callers can pass the
  `_stopped` check and tear the Rich `Live` down twice, corrupting the terminal.

## Mid-turn interactive prompts must stop the spinner AND pause the Esc watcher
- The permission menu fires DEEP inside a turn (`tools.execute` → `Permissions.check`
  → `ui.permission`, under `ui.tool_running()` and `interrupt_on_escape()`). Two
  things used to make it look stuck ("write_file hangs"): the live spinner's ticker
  redraw repainted over the menu, and the Esc watcher thread
  (`watch_windows`/`watch_posix`, `kbcode/interrupt.py:76`) ate the menu's
  keystrokes — `msvcrt.getwch()`/`stdin.read()` race the prompt for every key.
- Fix: `ui.permission` (`kbcode/ui.py:472`) stops `_active_status` first and wraps
  its `select()`/typed fallback in `pause_escape_watcher()`
  (`kbcode/interrupt.py:33`), which the watcher loops check via the module-level
  `_paused` event. ANY new mid-turn prompt must do both.

## Every `_TOOL_DESCRIBERS` entry must be a CALLABLE, not a label string
- `_describe_tool` (`kbcode/ui.py:232`) does `describer(a, g, full)`. Registering a
  bare string (e.g. `"repo_map": "get codebase structure map"`) makes that call
  raise **`'str' object is not callable`** the moment the agent uses that tool —
  it crashes the whole tool-call render, not just the label. This bit `edit_files`
  and `repo_map` when they were added. Add a real `_describe_<tool>(a, g, full)`
  returning `(verb, target)`. A `not callable` guard in `_describe_tool` now degrades
  a stray string to a static label, but don't rely on it — write the function.

## The Esc watcher must be JOINED at turn end, not just signalled
- `interrupt_on_escape()` (`kbcode/interrupt.py:107`) runs a daemon thread that reads
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
- `AnthropicProvider.stream`'s `do_stream` (`kbcode/provider.py:361`) iterates
  the SDK stream context itself — synthetic `"text"` events carry deltas,
  `content_block_start` events carry tool names for `on_tool` hints. Don't
  "simplify" it back to `stream_ctx.text_stream`: that silently drops the
  tool-name hints. The fakes in `tests/test_provider_streaming.py` yield
  event objects for the same reason.

## web_search uses a throwaway thread pool, not a shared one
- `kbcode/tools/web.py:112` — `_tool_web_search` can't cancel a blocking `ddgs`
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
- `kbcode/agent.py:693` — `_run_subagent()` is used both sequentially (main
  thread, normal path) and concurrently, one call per pool worker thread, from
  `_run_subagents_parallel_batch()` (`kbcode/agent.py:469`) via
  `_quiet_dispatch()` (`kbcode/agent.py:457`), which sets the per-thread
  `Agent._quiet_subagents.on` flag. Every inline `ui.notice`/`ui.tool_call`/
  `ui.tool_result`/`ui.tool_running()` call inside `_run_subagent()` checks
  `quiet` first — TerminalUI's Rich `Live`-backed spinner isn't safe to have
  two open at once, so an unguarded UI call added later will corrupt the
  terminal when multiple subagents run in parallel. If you add a new inline
  UI call inside `_run_subagent()`, gate it on `quiet` too. See
  [[tools-and-repair]], [[modes-subagents]].
- Related: `Agent._record_usage()` (`kbcode/agent.py:648`) is guarded by
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
- `kbcode/tools/file.py:372` — `_tool_search_code` formats each hit through
  `self._display_path(fp)` (`kbcode/tools/core.py:219`), **not** a raw
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
- `kbcode/compaction.py:194` — `_compact_within_last_exchange()` is the second
  pass of `compact()`. The first pass (`_compact_exchanges`) summarizes whole
  *middle* exchanges and always protects the most recent one — but a turn that
  runs many tool round-trips and hits the step limit (`Agent.max_steps`,
  default `_MAX_STEPS = 50`, `kbcode/agent.py:27`; `KBCODE_MAX_STEPS` tunes
  it, and `0` disables the cap entirely — unlimited, the loop switches to
  `itertools.count()`; the emergency context stop still fires, see [[safety]],
  [[config]]) is a **single** exchange (one user turn + ~50
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
  `len(batch)` per loop iteration (`kbcode/agent.py:345`), and the turn-summary
  "~N tokens" is *cumulative* usage across the turn's API calls, not the context
  size. See [[context-management]].

## search_code's Python fallback must never crawl vendored trees
- The ripgrep pre-filter is gitignore-aware; the fallback walk was NOT — in
  this repo it crawled `references/` (7 cloned repos incl. zed) file by file,
  so one unscoped search ran 285s+ and looked like a hang (hit live via the
  fixer subagent). Two guards now, keep both: `_walk_files` skips the project
  .gitignore's plain top-level dir entries (`_gitignored_dirs`,
  `kbcode/tools/file.py:371`), and `_tool_search_code` enforces
  `_SEARCH_TIME_BUDGET` (30s, `kbcode/tools/file.py:28`) — past it, partial
  hits return with a "narrow with 'path'" note. Tests:
  `tests/test_tools_search.py` (gitignore-skip + budget; budget test uses a
  NEGATIVE budget — 0.0 was flaky when the clock didn't tick).

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
  `kbcode/tools/file.py:400`.

## run_command per-turn limit (runaway guard)
- `kbcode/tools/file.py:400` — `_tool_run_command` caps calls per turn at
  `Config.max_commands_per_turn` (default `DEFAULT_MAX_COMMANDS = 25`,
  `kbcode/config.py:117`; `KBCODE_MAX_COMMANDS` tunes it; `0` = unlimited —
  the check is gated on `limit > 0`, so a zero cap disables the guard). It
  increments a per-turn counter (reset in `ToolsCore.new_turn`, called at
  start of every `Agent.run`). Exceeding a positive cap raises: "Refused: hit
  the safety limit of N run_command calls in one turn (a runaway loop
  guard)..."
- Intended to stop infinite `ls` / `echo` / pointless loops. Real tasks (e.g.
  "check for compilation errors", analyze + build + targeted checks + logs +
  retries) legitimately need more than a tiny budget inside one user message.
  When hit, the model is told to wrap up the turn; user can continue in next
  message — or raise `KBCODE_MAX_COMMANDS` in `.env` (or set it to 0 for
  unlimited) so long tasks pause less
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
- `Config.state_dir` (`kbcode/config.py:217`) — memory db, sessions/, checkpoints/,
  input history, and kbcode.log live at `~/.kbcode/projects/<slug>/` (Claude Code
  style), NOT in the project. Exception: a project carrying a legacy
  `.kbcode/memory.db` keeps the project-local `.kbcode` as its state dir —
  deleting that file silently switches the project to the (empty) home-dir
  location, "losing" its sessions/checkpoints/history. See [[config]].
- `KBCODE_HOME` overrides `~/.kbcode` and is read on every `def global_dir`
  call (`kbcode/config.py:308` `global_dir`) — set it BEFORE any Config path is touched (tests do,
  via the autouse fixture in `tests/conftest.py`), or state splits across two homes.
- The project `.kbcode/` (config only) self-hides via an auto-written `*`
  .gitignore (`_ensure_self_ignore`, `kbcode/config.py:295`) — an existing,
  user-customized `.kbcode/.gitignore` is deliberately never overwritten.

## `fix_pointers` relocations are heuristic — still eyeball its "fixes"
- `KnowledgeBase.fix_pointers()` (`kbcode/knowledge_base.py:324`) relocates a
  drifted pointer by the symbol named on the note line. Hardened after real
  mis-fixes (`promote` → repair.py's docstring, `_record_usage` → `class
  Agent:`): matching is now case-insensitive, `_anchors` puts snake_case /
  called tokens before bare capitalized words, and `_relocate` tries every
  anchor at the definition stage before calls, then bare mentions. It's still
  a text heuristic — a symbol mentioned once in a comment but defined nowhere
  can attract a pointer, so after `/kb-check --fix`, skim the rewrites.
  Phrasing a note line as `` `def promote`, `path:line` `` steers the anchor.

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
  (`load_mcp_servers()`, `kbcode/config.py:326`) and bootstraps the manager if
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

## Background tasks die on /provider and /open, not just at exit
- `Agent.close()` calls `Tools.stop_background_tasks()` (`kbcode/tools/file.py:560`)
  so a model-started dev server can't outlive kbcode — but `close()` also runs
  on the `/provider` and `/open` agent rebuilds (same path that stops MCP
  servers). Switching provider therefore kills every `run_command
  background=true` task. Deliberate (no orphan processes) — if a task must
  survive a rebuild, start it in your own terminal instead.

See [[conventions]] for general rules, [[about-kb]] for how traps get indexed here.
