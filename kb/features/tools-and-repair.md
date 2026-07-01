# Tools, repair, and the UI seam.

## Tool-call repair — two layers (openclaw idea)
*Parse layer* (`repair.py`): if the model returns text but no structured
`tool_calls`, `promote(text, allowed_names)` (`kbcode/repair.py:48`) scans it for a
tool call written as plain text — `[read_file]\n{...}` (`_find_bracketed`,
`kbcode/repair.py:136`), `<name>{...}</name>` (`_find_tagged`, `kbcode/repair.py:148`), or a
bare `{"name"/"tool", "arguments"}` object (`_find_keyed_json`, `kbcode/repair.py:160`)
— only for names the mode actually offers. `Agent._run_promoted()`
(`kbcode/agent.py:345`) runs them and feeds outputs back as a plain `user` turn (no
native tool ids to replay) with a nudge to use the real format.

*Execute layer*: `Tools.execute()` (`kbcode/tools/core.py:76`) runs `_repair()`
(`kbcode/tools/core.py:94`) first — unknown tool name -> closest match via
`difflib`; missing required args -> names them.

## Path resolution & protected files
`_resolve()` (`kbcode/tools/core.py:114`) anchors a relative path to the
project root but honors an absolute path exactly as given, even outside the
project — kbcode is not sandboxed to the project folder. `_protected_reason()`
(`kbcode/tools/file.py:88`) refuses `write_file`/`edit_file` to `.git/`/`.ssh/`
(`_PROTECTED_DIRS`, `kbcode/tools/file.py:24`), `.env`/secrets/private keys
(`_PROTECTED_NAMES`/`_PROTECTED_SUFFIXES`, `kbcode/tools/file.py:25-26`), and
kbcode's own state (`_KBCODE_STATE`, `kbcode/tools/file.py:27`) — checked
against the full resolved path, not just relative to the project root — while
allowing templates (`.env.example`, `_ENV_TEMPLATE_TAILS`,
`kbcode/tools/file.py:28`), `.gitignore`, and user-authored `.kbcode/agents`/
`modes` markdown. `_is_outside_project()` (`kbcode/tools/core.py:122`) drives
the `-- OUTSIDE the project folder` flag on the permission prompt.

## The roster & UI
Tools: `read/write/edit/list/search/run` + `kb_read/kb_write` +
`remember/recall/save_skill` + `manage_todos` + the conditional
`run_subagent` (see [[modes-subagents]]). `write_file`/`edit_file`/
`run_command` gate through `Permissions` (see [[safety]]). All terminal output
goes through `TerminalUI` (`ui.py`) — the loop never calls `console.print`
directly; `_describe_tool()` (`kbcode/ui.py:171`) renders a human verb+target line,
looked up per tool name in `_TOOL_DESCRIBERS` (`kbcode/ui.py:153`).

See [[conventions]] for how to add a new tool, [[gotchas]] for the two-layer
repair trap.
