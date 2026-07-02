# Tools, repair, and the UI seam.

## Tool-call repair — two layers (openclaw idea)
*Parse layer* (`repair.py`): if the model returns text but no structured
`tool_calls`, `promote(text, allowed_names)` (`kbcode/repair.py:48`) scans it for a
tool call written as plain text — `[read_file]\n{...}` (`_find_bracketed`,
`kbcode/repair.py:148`), `<name>{...}</name>` (`_find_tagged`, `kbcode/repair.py:148`), or a
bare `{"name"/"tool", "arguments"}` object (`_find_keyed_json`, `kbcode/repair.py:160`)
— only for names the mode actually offers. `Agent._run_promoted()`
(`kbcode/agent.py:530`) runs them and feeds outputs back as a plain `user` turn (no
native tool ids to replay) with a nudge to use the real format.

*Execute layer*: `Tools.execute()` (`kbcode/tools/core.py:102`) runs `_repair()`
(`kbcode/tools/core.py:167`) first — unknown tool name -> closest match via
`difflib`; missing required args -> names them; the reserved
`_malformed_args`/`_args_cut_off` markers (set by `provider._parse_tool_args`
when the arguments JSON was invalid or cut off by max_tokens — [[providers]])
-> explains the real cause (naming the actual token limit) and, for
write_file/edit_file/edit_files, coaches splitting the write with a
BUDGET-AWARE size: `_split_write_hint()` (`kbcode/tools/core.py:157`) derives
"keep each call under ~N chars" from the live `config.max_tokens`
(`_write_call_char_budget`, `kbcode/tools/core.py:149` — max_tokens·3/2; every
model's limit differs and /maxtokens changes it live). The system prompt also
tells the model its budget UP FRONT so big writes are split proactively:
`Agent._output_budget_note()` (`kbcode/agent.py:276`), appended per request by
`_system_for_mode()`. Every
call site wraps `execute()` in `Agent._dispatch_tool()`
(`kbcode/agent.py:237`), which runs configured PreToolUse/PostToolUse hooks
around it — see [[safety]].

## Post-edit syntax check (Aider idea)
Every successful `write_file`/`edit_file`/`edit_files` runs the new content
through `lint_text()` (`kbcode/lint.py:16`) via `_lint_note()`
(`kbcode/tools/file.py:231`) and, if it does not parse, APPENDS a WARNING to
the (still successful) tool result — the model sees the exact error + a
█-marked context snippet in the very next step, instead of the bug surfacing
when the code runs. Syntax-level only, by design: pure stdlib parsers
(`compile()` for .py, `json.loads` for .json, `tomllib` for .toml, PyYAML for
.yaml only if importable) — no external linter subprocess, so it is
dependency-free, instant, and hang-proof. Two contracts to keep: (1) a lint
problem is a NOTE on a successful write, never an exception — the file is
already on disk; (2) the warning's second sentence excuses deliberately
piece-wise writes (the output-budget rules above tell the model to build big
files in parts, and a half-written .py never parses) — see [[gotchas]].

## Flexible edit_file matching (Aider idea #3)
When `edit_file`/`edit_files` can't find an exact match — models often get
indentation wrong or add extra blank lines — `edit_strategies.try_edit()`
(`kbcode/tools/edit_strategies.py:36`) tries five strategies in order:
exact → strip-blanks → indent → strip+indent → fuzzy (difflib, ≥70 %).
Every strategy includes a uniqueness check; the strategy name tags the
permission prompt and result line (`[strategy: indent]`). Pure stdlib, zero
new dependencies. See [[edit-strategies]].

## MCP tools (external servers, namespaced `mcp__server__tool`)
When `.kbcode/settings.json` has an `mcpServers` block, `_build_agent` attaches
an `MCPManager` to `Tools.mcp` (`kbcode/tools/core.py:41`); `ToolsCore.schemas`
appends the live server schemas (`kbcode/tools/core.py:59`) so `_repair()` and
`parallel_safe_tools` cover them for free, and `execute()` forks on the
`mcp__` prefix (`kbcode/tools/core.py:121`) into `_execute_mcp()`
(`kbcode/tools/core.py:121`) — permission gate, checkpoint, redaction, then
the JSON-RPC call. The prefix keeps MCP names far from built-ins in
edit-distance, so difflib never "corrects" across the namespace boundary.
Deep dive: [[mcp]].

## Path resolution & protected files
`_resolve()` (`kbcode/tools/core.py:208`) anchors a relative path to the
project root but honors an absolute path exactly as given, even outside the
project — kbcode is not sandboxed to the project folder. `_protected_reason()`
(`kbcode/tools/file.py:123`) refuses `write_file`/`edit_file` to `.git/`/`.ssh/`
(`_PROTECTED_DIRS`, `kbcode/tools/file.py:38`), `.env`/secrets/private keys
(`_PROTECTED_NAMES`/`_PROTECTED_SUFFIXES`, `kbcode/tools/file.py:39-40`), and
kbcode's own state (`_KBCODE_STATE`, `kbcode/tools/file.py:41`) — checked
against the full resolved path, not just relative to the project root — while
allowing templates (`.env.example`, `_ENV_TEMPLATE_TAILS`,
`kbcode/tools/file.py:42`), `.gitignore`, and user-authored `.kbcode/agents`/
`modes` markdown. `_is_outside_project()` (`kbcode/tools/core.py:216`) drives
the `-- OUTSIDE the project folder` flag on the permission prompt.
`_display_path()` (`kbcode/tools/core.py:219`) formats a resolved path for tool
output — relative to the root when inside the project, absolute otherwise —
because those same out-of-project paths make a bare `Path.relative_to(root)`
raise `ValueError`, which would abort the tool (search hits used to do this; see
[[gotchas]]). New tools that print a resolved path must go through it.

## The roster & UI
Tools: `read/write/edit/edit_files/list/search/run` + `check_task` + `kb_read/kb_write` +
`remember/recall/save_skill` + `manage_todos` + `web_search` + `fetch_url` + `repo_map`

`run_command` accepts optional `background: true`: after the same rate-limit /
dangerous-command / permission gates (prompt shows "(background — keeps
running)"), `_start_background_command()` (`kbcode/tools/file.py:528`) starts
the Popen detached (output to named temp files) and returns a task id like
`bg-1`; the registry is `ToolsCore.bg_tasks` + `_bg_seq` (`kbcode/tools/core.py:46`).
`check_task` (`_tool_check_task`, `kbcode/tools/file.py:583`) polls it —
status running/finished/killed + redacted stdout/stderr tails via `_tail_file`
— and `kill: true` stops it with `_kill_process_tree`. Survivors are killed at
exit by `stop_background_tasks()` (`kbcode/tools/file.py:616`), called from
`Agent.close()` — note that also fires on `/provider`/`/open` agent rebuilds
(see [[gotchas]]).

`fetch_url` (`_tool_fetch_url`, `kbcode/tools/web.py:82`) fetches an http(s)
URL via stdlib urllib in a worker thread (hang-proof, 20s cap, 2 MB / 20k-char
limits); HTML is converted to plain text by `_html_to_text`, JSON/plain text
returned as-is. No API key; `parallel_safe`.

`read_file` supports optional `offset` (1-based) + `limit` (lines) for reading slices of large files without shell chunking or full loads. When a range is given it streams lines (no full file load in memory).

New tools `repo_map` (structural overview) and `edit_files` (multi-file edits) were added inspired by Aider and Zed after studying their references. Use `repo_map` early for exploration and `edit_files` for coordinated changes across files.

`edit_files` allows the agent to propose coordinated changes across several files
in a single step (with one permission dialog showing diffs), similar to how
advanced AI-native editors like Zed let their agents perform multi-file refactors
and feature implementations cleanly.
(`_tool_web_search`, `kbcode/tools/web.py:112`) + the conditional
`run_subagent` (see [[modes-subagents]]). `write_file`/`edit_file`/
`run_command` gate through `Permissions` (see [[safety]]). All terminal output
goes through `TerminalUI` (`ui.py`) — the loop never calls `console.print`
directly; `_describe_tool()` (`kbcode/ui.py:232`) renders a human verb+target line,
looked up per tool name in `_TOOL_DESCRIBERS` (`kbcode/ui.py:209`). Every describer
entry must be a callable `(a, g, full) -> (verb, target)`; a bare string degrades to
a static label instead of crashing (`'str' object is not callable` — see [[gotchas]]).

## Parallel-safe tools (#4.3)
Consecutive **read-only** tool calls run concurrently (`Agent._run_parallel_batch`,
`kbcode/agent.py:422`); mutating tools stay sequential. Which tools are safe is
declared per-tool by a `"parallel_safe": True` key on the schema
(`kbcode/tools/schemas.py`) — the single source of truth. `Agent.run` reads the
set via `ToolsCore.parallel_safe_tools` (`kbcode/tools/core.py:94`, a comprehension
over `schemas`), never a hardcoded list, so a new read-only tool opts in just by
carrying the flag and can't silently fall back to sequential. `parallel_safe` is
kbcode-only metadata: the OpenAI path rebuilds tool payloads (`_tools`), and the
Anthropic path strips it via `_api_tools` (see [[providers]], [[gotchas]]) before
the schema reaches the model API.

**`run_subagent` conditional extension.** A run of 2+ consecutive `run_subagent`
calls is also eligible for concurrent dispatch, but only when *every* targeted
subagent qualifies — `Agent._is_parallel_subagent_call()`
(`kbcode/agent.py:848`) checks `Agent._subagent_parallel_safe(name)`
(`kbcode/agent.py:833`), which requires the subagent's own `tools:` frontmatter
(a `frozenset[str]`, never `None`) to be a subset of the same
`parallel_safe_tools` set above plus `_SUBAGENT_PARALLEL_EXTRAS`
(`frozenset({"manage_todos"})`, `kbcode/agent.py:66`). The default `tools: read`
(the READ group) now QUALIFIES: `recall` is schema-`parallel_safe` since
Memory serializes all SQLite access behind an RLock
(`check_same_thread=False`, `kbcode/memory.py:21`), and `manage_todos` is
tolerated because its whole-list replacement is atomic under the GIL (worst
case concurrent subagents overwrite each other's checklist, never corrupt
it — `kbcode/tools/planning.py:31`). Any write/exec tool or `tools: None`
keeps a subagent sequential. `Agent.run`'s batching loop
(`kbcode/agent.py:348-360`) checks this as a second, symmetric branch after the
read-only-tool check; a qualifying run goes through
`_run_subagents_parallel_batch()` (`kbcode/agent.py:469`), which mirrors
`_run_parallel_batch`'s shape: a `ThreadPoolExecutor` (same
`_PARALLEL_MAX_WORKERS = 16` cap, `kbcode/agent.py:65`) runs `_quiet_dispatch()` (`kbcode/agent.py:457`)
per call, then call/result lines render sequentially afterward in the
model's original order so `tool_results` stays aligned with tool_call ids.
`_quiet_dispatch` sets a thread-local flag (`Agent._quiet_subagents`, a
`threading.local()`) that `_run_subagent()` (`kbcode/agent.py:693`) reads to
suppress its own inline `ui.notice`/`ui.tool_call`/`ui.tool_result`/
`ui.tool_running()` calls — Rich's Live-backed spinner isn't safe to have two
open at once. `_quiet_dispatch` still calls through `_dispatch_tool()`, the
same entry point the sequential path uses, so PreToolUse/PostToolUse hooks
fire exactly as before (see [[safety]]). Anything else — a single
`run_subagent` call, mixed eligibility in a run, or a subagent with
`tools: None` or any write/exec tool — stays fully sequential through the
normal `_run_subagent()` path. `Agent._record_usage()` (`kbcode/agent.py:648`)
is guarded by `Agent._usage_lock` (a `threading.Lock()` set in `__init__`)
since it can now be called from multiple subagent pool threads at once — see
[[modes-subagents]].

## Date- & folder-awareness
`build_system_prompt()` (`kbcode/prompts.py:43`) takes a `project_dir:` kwarg
(passed by `cli._build_agent`) and stamps a `## Project folder` section naming
the absolute path and folder name — without it the model can't tell which
project it is in (a live MiMo session answered generically for that reason).
It also stamps a `## Current date &
time` section with `datetime.now()` (injectable via a `now:` kwarg for tests)
and tells the model its training data can be stale — don't guess a
training-cutoff-era date, and use `web_search` for anything time-sensitive
instead of answering from memory. Fixes the model composing search queries
with a wrong/guessed year (e.g. "July 2025" when it's actually 2026).

See [[conventions]] for how to add a new tool, [[gotchas]] for the two-layer
repair trap and the schema-metadata-strip trap.
