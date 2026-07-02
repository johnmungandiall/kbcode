# Modes & subagents — personalities, tool guardrails, delegation.

## Modes apply per turn
`Mode` (`kbcode/modes.py:33`) pairs instructions with an allowed-tool set from the
`READ`/`NOTES`/`EDIT`/`EXEC` groups (`kbcode/modes.py:23-29` — `manage_todos` and
`web_search` live in `READ` so they work even read-only). `Agent.run` rebuilds
`_system_for_mode()` (`kbcode/agent.py:217`) and `_mode_schemas()` (`kbcode/agent.py:220`) on
**every** model call. Enforcement is two-layer: disallowed tools are never shown
to the model, and `run()` guards again at execute time. Builtins
(`_BUILTINS`, `kbcode/modes.py:43`): `code`/`debug` (all tools), `architect` (read +
notes), `ask` (read-only). Custom modes load from `.kbcode/modes/*.md` via
`load_custom_modes()` (`kbcode/modes.py:102`).

## Subagents delegate into a fresh context
`load_subagents()` (`kbcode/subagents.py:53`) reads `.kbcode/agents/*.md` (same
frontmatter parser as modes) into `Subagent` records (`kbcode/subagents.py:42`).
`Agent.__init__` (`kbcode/agent.py:73`) wires `tools.subagents` and `tools.delegate = self
._run_subagent`; `Tools.schemas` (`kbcode/tools/core.py:48`) conditionally
appends the `run_subagent` schema (`_subagent_schema`, `kbcode/tools/core.py:54`)
only when subagents exist, roster baked into its description. `_run_subagent()`
(`kbcode/agent.py:631`) runs a separate bounded loop (`_SUBAGENT_MAX_STEPS`,
`kbcode/agent.py:27`) with the subagent's own system prompt + filtered schemas, shares
the same `Tools` instance (file/KB side-effects land in the same project),
blocks nested delegation, and returns only the final text. Token usage still
accrues to `Agent.usage`, now under `Agent._usage_lock` since it can be
touched by multiple subagent threads at once (see below).

**Parallel-eligibility rule.** By default, several `run_subagent` calls in one
turn still run strictly one-at-a-time via `_run_subagent()`. A run of 2+
consecutive calls runs concurrently instead when every targeted subagent's
`tools:` frontmatter is an explicit, narrow subset of the schema-declared
`parallel_safe` tool set (`read_file`, `list_dir`, `search_code`, `web_search`,
`kb_read`, `kb_search`) — checked by `Agent._subagent_parallel_safe()`
(`kbcode/agent.py:611`). The default `tools: read` (used when a subagent's
frontmatter omits `tools:` — `load_subagents()`, `kbcode/subagents.py:80`) does
NOT qualify, since it also includes `recall`/`manage_todos`. This is the same
#4.3 parallel-tool-call mechanism extended to `run_subagent`, not a new code
path — see [[tools-and-repair]] for the full dispatch mechanics
(`_run_subagents_parallel_batch`, `_quiet_dispatch`, the quiet-UI thread-local).

**Making explorer subagents Cursor-fast.** Subagents that explore pay one
model round-trip per batch. Inside `_run_subagent`, consecutive parallel_safe
tools are batched and run concurrently (up to 16 at a time with
_PARALLEL_MAX_WORKERS). To achieve high speed:

- Use a narrow `tools:` list limited to parallel-safe tools only.
- In the subagent instructions, *explicitly* tell it to batch many reads in
  a single response (e.g. "call 5-10 tools together in one step").
- The built-in `code-explorer` now does this aggressively.

Higher parallelism (16 workers) + strong batching instructions = much fewer
slow LLM turns, closer to Cursor responsiveness on the same model.

## Standing orders
`build_system_prompt()` (`kbcode/prompts.py:42`) injects an optional `standing_orders`
string (from `.kbcode/standing-orders.md`) right after the base rules, so it
takes priority. `cli._build_agent` (`kbcode/cli.py:141`) ignores the untouched scaffold
template (`_STANDING_ORDERS_TEMPLATE`, `kbcode/cli.py:111`) so its examples never become
live orders.

See [[architecture]] for how this fits the agent loop, [[conventions]] for how
to add a new mode/subagent (ship a markdown file, no code change), [[tools-and-repair]]
for how tool calls are dispatched once a mode/subagent has picked its roster,
including the parallel-safe `run_subagent` extension.
