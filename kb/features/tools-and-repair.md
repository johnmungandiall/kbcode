# Tools, repair, and the UI seam.

## Tool-call repair — two layers (openclaw idea)
*Parse layer* (`repair.py`): if the model returns text but no structured
`tool_calls`, `promote(text, allowed_names)` (`kbcode/repair.py:48`) scans it for a
tool call written as plain text — `[read_file]\n{...}` (`_find_bracketed`,
`kbcode/repair.py:136`), `<name>{...}</name>` (`_find_tagged`, `kbcode/repair.py:148`), or a
bare `{"name"/"tool", "arguments"}` object (`_find_keyed_json`, `kbcode/repair.py:160`)
— only for names the mode actually offers. `Agent._run_promoted()`
(`kbcode/agent.py:452`) runs them and feeds outputs back as a plain `user` turn (no
native tool ids to replay) with a nudge to use the real format.

*Execute layer*: `Tools.execute()` (`kbcode/tools/core.py:89`) runs `_repair()`
(`kbcode/tools/core.py:108`) first — unknown tool name -> closest match via
`difflib`; missing required args -> names them. Every call site wraps
`execute()` in `Agent._dispatch_tool()` (`kbcode/agent.py:195`), which runs
configured PreToolUse/PostToolUse hooks around it — see [[safety]].

## Path resolution & protected files
`_resolve()` (`kbcode/tools/core.py:128`) anchors a relative path to the
project root but honors an absolute path exactly as given, even outside the
project — kbcode is not sandboxed to the project folder. `_protected_reason()`
(`kbcode/tools/file.py:88`) refuses `write_file`/`edit_file` to `.git/`/`.ssh/`
(`_PROTECTED_DIRS`, `kbcode/tools/file.py:24`), `.env`/secrets/private keys
(`_PROTECTED_NAMES`/`_PROTECTED_SUFFIXES`, `kbcode/tools/file.py:25-26`), and
kbcode's own state (`_KBCODE_STATE`, `kbcode/tools/file.py:27`) — checked
against the full resolved path, not just relative to the project root — while
allowing templates (`.env.example`, `_ENV_TEMPLATE_TAILS`,
`kbcode/tools/file.py:28`), `.gitignore`, and user-authored `.kbcode/agents`/
`modes` markdown. `_is_outside_project()` (`kbcode/tools/core.py:134`) drives
the `-- OUTSIDE the project folder` flag on the permission prompt.

## The roster & UI
Tools: `read/write/edit/list/search/run` + `kb_read/kb_write` +
`remember/recall/save_skill` + `manage_todos` + `web_search`
(`_tool_web_search`, `kbcode/tools/web.py:39`) + the conditional
`run_subagent` (see [[modes-subagents]]). `write_file`/`edit_file`/
`run_command` gate through `Permissions` (see [[safety]]). All terminal output
goes through `TerminalUI` (`ui.py`) — the loop never calls `console.print`
directly; `_describe_tool()` (`kbcode/ui.py:171`) renders a human verb+target line,
looked up per tool name in `_TOOL_DESCRIBERS` (`kbcode/ui.py:153`).

## Parallel-safe tools (#4.3)
Consecutive **read-only** tool calls run concurrently (`Agent._run_parallel_batch`,
`kbcode/agent.py:344`); mutating tools stay sequential. Which tools are safe is
declared per-tool by a `"parallel_safe": True` key on the schema
(`kbcode/tools/schemas.py`) — the single source of truth. `Agent.run` reads the
set via `ToolsCore.parallel_safe_tools` (`kbcode/tools/core.py:81`, a comprehension
over `schemas`), never a hardcoded list, so a new read-only tool opts in just by
carrying the flag and can't silently fall back to sequential. `parallel_safe` is
kbcode-only metadata: the OpenAI path rebuilds tool payloads (`_tools`), and the
Anthropic path strips it via `_api_tools` (see [[providers]], [[gotchas]]) before
the schema reaches the model API.

**`run_subagent` conditional extension.** A run of 2+ consecutive `run_subagent`
calls is also eligible for concurrent dispatch, but only when *every* targeted
subagent qualifies — `Agent._is_parallel_subagent_call()`
(`kbcode/agent.py:610`) checks `Agent._subagent_parallel_safe(name)`
(`kbcode/agent.py:595`), which requires the subagent's own `tools:` frontmatter
(a `frozenset[str]`, never `None`) to be a subset of the same
`parallel_safe_tools` set above. The default `tools: read` does NOT qualify —
it includes `recall`/`manage_todos`, which touch Memory's non-thread-safe
sqlite3 connection / todos state — so only a subagent deliberately authored
with a narrow, explicit tool list opts in. `Agent.run`'s batching loop
(`kbcode/agent.py:297-320`) checks this as a second, symmetric branch after the
read-only-tool check; a qualifying run goes through
`_run_subagents_parallel_batch()` (`kbcode/agent.py:391`), which mirrors
`_run_parallel_batch`'s shape: a `ThreadPoolExecutor` (same
`_PARALLEL_MAX_WORKERS = 8` cap) runs `_quiet_dispatch()` (`kbcode/agent.py:379`)
per call, then call/result lines render sequentially afterward in the
model's original order so `tool_results` stays aligned with tool_call ids.
`_quiet_dispatch` sets a thread-local flag (`Agent._quiet_subagents`, a
`threading.local()`) that `_run_subagent()` (`kbcode/agent.py:615`) reads to
suppress its own inline `ui.notice`/`ui.tool_call`/`ui.tool_result`/
`ui.tool_running()` calls — Rich's Live-backed spinner isn't safe to have two
open at once. `_quiet_dispatch` still calls through `_dispatch_tool()`, the
same entry point the sequential path uses, so PreToolUse/PostToolUse hooks
fire exactly as before (see [[safety]]). Anything else — a single
`run_subagent` call, mixed eligibility in a run, or a subagent with
`tools: None` or any write/exec tool — stays fully sequential through the
normal `_run_subagent()` path. `Agent._record_usage()` (`kbcode/agent.py:570`)
is guarded by `Agent._usage_lock` (a `threading.Lock()` set in `__init__`)
since it can now be called from multiple subagent pool threads at once — see
[[modes-subagents]].

## Date-awareness for `web_search`
`build_system_prompt()` (`kbcode/prompts.py:41`) stamps a `## Current date &
time` section with `datetime.now()` (injectable via a `now:` kwarg for tests)
and tells the model its training data can be stale — don't guess a
training-cutoff-era date, and use `web_search` for anything time-sensitive
instead of answering from memory. Fixes the model composing search queries
with a wrong/guessed year (e.g. "July 2025" when it's actually 2026).

See [[conventions]] for how to add a new tool, [[gotchas]] for the two-layer
repair trap and the schema-metadata-strip trap.
