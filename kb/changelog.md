# Changelog — notable changes, newest first.

The ONLY place release history lives (don't duplicate it in other notes).

## v1.5.0 (current)
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
