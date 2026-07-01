# Sessions — history, replay, and usage tally.

## Session history
Every chat is persisted per-project to `.kbcode/sessions/<id>.jsonl`.
`SessionRecorder` (`kbcode/sessions.py:89`) appends one JSON line per message **as it
happens** — `Agent._append()` (`kbcode/agent.py:171`) wraps every
`self.messages.append`, so a crash loses at most the in-flight message. Three
other record types share the file: `meta` (written once by `cli._build_agent`,
`kbcode/cli.py:109`, capturing provider/model/mode/git branch), `usage` (written after
every turn), and `reset` (written by `Agent.reset()`, `kbcode/agent.py:534` — a marker,
not a new file, so replay only reconstructs what happened after the last reset
while the file keeps a full audit trail underneath).

`kbcode -c`/`--continue`, `--resume [id]`, and in-chat `/sessions`/`/resume`
resolve to `cli._resume_agent()` (`kbcode/cli.py:146`), which restores the session's
original provider/model — **raw assistant payloads are provider-shaped** (see
[[providers]]), so replay only works cleanly under the same one — and
reconstructs `tool_calls` back into `ToolCall` instances (`sessions
.load_session`, `kbcode/sessions.py:250`) since `compaction._render()` reads them by
attribute.

## Usage tally
`Agent.usage` (`kbcode/agent.py:83`) accumulates `requests`/`input_tokens`/
`output_tokens` from each response's usage (both providers populate it, see
[[providers]]); `Agent.insights()` (`kbcode/agent.py:452`) + `pricing.estimate_cost()`
(`kbcode/pricing.py:27`) back `/insights`. After every user turn `Agent._turn_summary()`
(`kbcode/agent.py:433`) prints the `actions * tokens * elapsed` footer and records
usage so `/insights` reflects a session even if it never cleanly exits.
`sessions.lifetime_stats()` (`kbcode/sessions.py:328`) rolls every saved session's
last-known usage into an all-time total, pricing each with *its own* recorded
model — no database needed, mixed-provider projects still get one honest total.

See [[gotchas]] for the session-replay-needs-matching-provider trap and the SDK
JSON-serialization trap, [[context-management]] for how compaction interacts
with a growing session.
