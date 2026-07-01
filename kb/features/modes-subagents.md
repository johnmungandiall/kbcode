# Modes & subagents — personalities, tool guardrails, delegation.

## Modes apply per turn
`Mode` (`kbcode/modes.py:30`) pairs instructions with an allowed-tool set from the
`READ`/`NOTES`/`EDIT`/`EXEC` groups (`kbcode/modes.py:23-26` — `manage_todos` lives in
`READ` so the task checklist works even read-only). `Agent.run` rebuilds
`_system_for_mode()` (`kbcode/agent.py:176`) and `_mode_schemas()` (`kbcode/agent.py:179`) on
**every** model call. Enforcement is two-layer: disallowed tools are never shown
to the model, and `run()` guards again at execute time. Builtins
(`_BUILTINS`, `kbcode/modes.py:40`): `code`/`debug` (all tools), `architect` (read +
notes), `ask` (read-only). Custom modes load from `.kbcode/modes/*.md` via
`load_custom_modes()` (`kbcode/modes.py:99`).

## Subagents delegate into a fresh context
`load_subagents()` (`kbcode/subagents.py:40`) reads `.kbcode/agents/*.md` (same
frontmatter parser as modes) into `Subagent` records (`kbcode/subagents.py:30`).
`Agent.__init__` wires `tools.subagents` and `tools.delegate = self
._run_subagent`; `Tools.schemas` (`kbcode/tools/core.py:43`) conditionally
appends the `run_subagent` schema (`_subagent_schema`, `kbcode/tools/core.py:49`)
only when subagents exist, roster baked into its description. `_run_subagent()`
(`kbcode/agent.py:470`) runs a separate bounded loop (`_SUBAGENT_MAX_STEPS`,
`kbcode/agent.py:27`) with the subagent's own system prompt + filtered schemas, shares
the same `Tools` instance (file/KB side-effects land in the same project),
blocks nested delegation, and returns only the final text. Token usage still
accrues to `Agent.usage`.

## Standing orders
`build_system_prompt()` (`kbcode/prompts.py:41`) injects an optional `standing_orders`
string (from `.kbcode/standing-orders.md`) right after the base rules, so it
takes priority. `cli._build_agent` (`kbcode/cli.py:109`) ignores the untouched scaffold
template (`_STANDING_ORDERS_TEMPLATE`, `kbcode/cli.py:79`) so its examples never become
live orders.

See [[architecture]] for how this fits the agent loop, [[conventions]] for how
to add a new mode/subagent (ship a markdown file, no code change), [[tools-and-repair]]
for how tool calls are dispatched once a mode/subagent has picked its roster.
