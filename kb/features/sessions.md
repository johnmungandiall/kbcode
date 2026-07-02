# Sessions — history, replay, and usage tally.

## Session history
Every chat is persisted per-project to `<state dir>/sessions/<id>.jsonl` —
i.e. `~/.kbcode/projects/<slug>/sessions/`, via `Config.sessions_dir`, NOT
inside the project tree (see [[config]] "Where files live").
`SessionRecorder` (`kbcode/sessions.py:89`) appends one JSON line per message **as it
happens** — `Agent._append()` (`kbcode/agent.py:212`) wraps every
`self.messages.append`, so a crash loses at most the in-flight message. Three
other record types share the file: `meta` (written once by `cli._build_agent`,
`kbcode/cli.py:143`, capturing provider/model/mode/git branch), `usage` (written after
every turn), and `reset` (written by `Agent.reset()`, `kbcode/agent.py:778` — a marker,
not a new file, so replay only reconstructs what happened after the last reset
while the file keeps a full audit trail underneath).

`kbcode -c`/`--continue`, `--resume [id]`, and in-chat `/sessions`/`/resume`
resolve to `cli._resume_agent()` (`kbcode/cli.py:179`), which restores the session's
original provider/model — **raw assistant payloads are provider-shaped** (see
[[providers]]), so replay only works cleanly under the same one — and
reconstructs `tool_calls` back into `ToolCall` instances (`sessions
.load_session`, `kbcode/sessions.py:250`) since `compaction._render()` reads them by
attribute.

## Usage tally
`Agent.usage` (`kbcode/agent.py:97`) accumulates `requests`/`input_tokens`/
`output_tokens` from each response's usage (both providers populate it, see
[[providers]]), written through `Agent._record_usage()` (`kbcode/agent.py:586`)
under `Agent._usage_lock` (a `threading.Lock()` set in `__init__`) since #4.3's
`run_subagent` extension can now call it from multiple pool threads at once —
see [[modes-subagents]], [[tools-and-repair]]. `Agent.insights()`
(`kbcode/agent.py:593`) + `pricing.estimate_cost()`
(`kbcode/pricing.py:27`) back `/insights`. After every user turn `Agent._turn_summary()`
(`kbcode/agent.py:573`) prints the `actions * tokens * elapsed` footer and records
usage so `/insights` reflects a session even if it never cleanly exits.
`sessions.lifetime_stats()` (`kbcode/sessions.py:328`) rolls every saved session's
last-known usage into an all-time total, pricing each with *its own* recorded
model — no database needed, mixed-provider projects still get one honest total.

See [[gotchas]] for the session-replay-needs-matching-provider trap and the SDK
JSON-serialization trap, [[context-management]] for how compaction interacts
with a growing session.
