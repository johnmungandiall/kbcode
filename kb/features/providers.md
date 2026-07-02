# Providers — normalized messages, translation, resilience, interrupts.

## Normalized messages + `raw` replay
`Agent.messages` (`kbcode/agent.py:98`) is provider-agnostic, never a provider's native
shape: `{"role":"user","content"}` (+ optional `"images"`), `{"role":"assistant",
"text","tool_calls","raw"}`, `{"role":"tool_results","results"}`. Each provider's
`_to_native` (Anthropic `kbcode/provider.py:187`, OpenAI-compatible `kbcode/provider.py:442`)
translates to/from its own API and stores the model's own assistant payload back
in `raw` so the next request replays it losslessly (Claude thinking blocks vs
OpenAI `tool_calls` differ structurally). **Invariant:** normalized<->native must
round-trip, and user/assistant turns must stay alternating after any message-list
surgery (see [[context-management]] on compaction). A session uses exactly one
provider, so `raw` is always that provider's shape — session replay requires a
matching provider (see [[sessions]]).

`get_provider()` (`kbcode/provider.py:709`) dispatches on `config.kind`. Every
non-Claude provider (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, custom) is the
*same* `OpenAICompatibleProvider` (`kbcode/provider.py:472`) with a different
`base_url`. `AnthropicProvider.complete` (`kbcode/provider.py:334`) tries a staged
kwargs fallback (`thinking`+`output_config` -> `thinking` -> plain), catching
`TypeError` per attempt for older SDKs. Temperature (if set) and thinking level
(from `config.thinking`) are included **only if not "off"** (Anthropic output_config.effort,
OpenAI `reasoning_effort` + `temperature`). Use `/thinking off` or KBCODE_THINKING=off
to disable reasoning blocks entirely. "normal" normalizes to "medium".

`max_tokens` is now model-aware: `config.max_tokens` (and thus every `messages.create`
call) is chosen automatically from the model id unless `KBCODE_MAX_TOKENS` or
settings pinned it (see [[config]] + `get_default_max_tokens`).

## Prompt caching (Anthropic only)
Anthropic prompt caching is a **prefix match** over the rendered request
(order: tools -> system -> messages), max 4 `cache_control` breakpoints. kbcode
spends one on the system prompt (`complete`/`stream` build `system_blocks`
with `cache_control`) — being last in the render order it covers the tool
definitions too. The other three go on the conversation:
`_add_cache_breakpoints()` (`kbcode/provider.py:238`) marks the last content
block of the newest `_MESSAGE_CACHE_BREAKPOINTS = 3` (`kbcode/provider.py:235`)
user-role native messages, so every tool round-trip re-reads the previous
request's history from cache (~0.1x input price) instead of paying full price —
the dominant cost of a long agentic turn. Several anchors (not one) because a
cache lookup only walks back 20 content blocks and a parallel batch can add
more than that per round-trip. **Only user-role messages are marked** — they
are built fresh by `_to_native` per request, so markers never accumulate into
`Agent.messages`; assistant `raw` blocks are never mutated (see [[gotchas]]).
Compaction rewrites history, so the first request after a compact is a cache
miss — expected, one-time. `_usage()` (`kbcode/provider.py:305`) folds
`cache_creation_input_tokens` + `cache_read_input_tokens` back into
`input_tokens` (the API reports only the uncached remainder there) so /cost
and turn summaries stay comparable; the estimate is conservative (cache reads
actually bill at ~0.1x). Tests: `tests/test_provider_caching.py`.

## Streaming progress: tool names, tool ARGS, and thinking
`stream(..., on_tool=, on_tool_args=, on_thinking=)` (base signature
`kbcode/provider.py:184`) reports, mid-stream: each tool call's *name* the
moment it appears (`on_tool`), the accumulated size of its arguments JSON as
it streams (`on_tool_args(name, chars)` — the Hermes tool-progress-callback
idea), and reasoning deltas (`on_thinking`). The Anthropic path iterates the
SDK's event stream (synthetic `"text"`/`"thinking"` events, `"input_json"`
partial_json for args, `content_block_start` for names); the OpenAI path
fires on the first name fragment per tool-call index, counts
`function.arguments` deltas, and reads `delta.reasoning_content` (DeepSeek) /
`delta.reasoning` (OpenRouter). NOTHING is printed from the worker thread
anymore: `ui.stream_tool_hint` (`kbcode/ui.py:604`) now only relabels the
live spinner ("<name> — composing the call…"), `ui.stream_tool_args`
(`kbcode/ui.py:619`) keeps a `writing the call… N chars` counter ticking (the
fix for "a big write looks stuck"), `ui.stream_thinking` (`kbcode/ui.py:591`)
counts reasoning chars, and `ui.stream_chunk` counts reply chars. The
complete reply is markdown-rendered by `ui.assistant_text` once the response
resolves, preceded by a collapsed `🧠 thought…` line (`ui.thought_summary`)
when the model reasoned — `/thoughts` (`ui.thoughts`) expands the full text,
kept per turn on `Agent.last_thinking`.

## Malformed / cut-off tool calls become repair markers
`_parse_tool_args()` (`kbcode/provider.py:46`) parses a tool call's arguments
JSON on both OpenAI paths. Malformed JSON no longer silently degrades to `{}`
(which surfaced as a bare red "missing required argument(s): path, content"
on every truncated `write_file`): it becomes `{"_malformed_args": <raw≤500>}`,
plus `"_args_cut_off": True` when the response's finish_reason was `length`
(max_tokens hit mid-call). `ToolsCore._repair` (`kbcode/tools/core.py:151`)
turns the markers into precise guidance — including the split-the-write
coaching (`_SPLIT_WRITE_HINT`, `kbcode/tools/core.py:144`) for
write_file/edit_file/edit_files — and `ui.tool_call`/`tool_result` render
these as a yellow "call arrived incomplete… ↻ asked the model to resend"
instead of a scary error. Tests: `tests/test_auto_mode.py`.

The broken arguments string must NEVER reach `raw["tool_calls"]`: strict
OpenAI-compatible servers (MiMo, live) parse every replayed `arguments` field
and reject the follow-up request with HTTP 400 "unexpected end of data" —
killing the repair round itself. `_replayable_args()` (`kbcode/provider.py:68`)
stores the marker dict as valid JSON instead, and
`OpenAICompatibleProvider._sanitize_raw()` (`kbcode/provider.py:507`) re-checks
every replayed raw payload in `_to_native` (covers sessions recorded before
the fix). Tests: `tests/test_provider_streaming.py`.

Tool schemas carry kbcode-only metadata (e.g. `parallel_safe`, see
[[tools-and-repair]]) that the model APIs reject as unknown keys. The OpenAI path
drops it by rebuilding each tool (`_tools`, `kbcode/provider.py`); the Anthropic
path, which otherwise forwards `tools` verbatim, keeps only name/description/
`input_schema` via `AnthropicProvider._api_tools` in both `complete` and `stream`
(see [[gotchas]]).

Both SDK clients are built lazily with a shared timeout from
`LLMProvider._client_kwargs()` (`kbcode/provider.py:135`): it passes
`timeout=config.request_timeout` (default 120s) so a stalled model fails fast
instead of freezing on the SDK's ~600s default; `KBCODE_REQUEST_TIMEOUT=0` opts
out (see [[config]]). The resulting timeout error is transient, so `_with_retry`
backs off and retries it.

## Resilience
Every real API call goes through `_with_retry()` (`kbcode/provider.py:103`): transient
failures (429/5xx/connection/timeout, classified by `_classify()` at
`kbcode/provider.py:62` from SDK-agnostic `status_code`+message) retry with exponential
backoff (`_MAX_RETRIES`/`_BACKOFF_BASE`, `kbcode/provider.py:49-59`). Hard errors
(401/403/4xx) raise `ProviderError` (`kbcode/provider.py:42`) immediately, no retry.
`_with_retry` deliberately re-raises `TypeError` untouched so the Anthropic
staged fallback still works.

## Interrupt mid-request + type-ahead
`Agent._complete()` (`kbcode/agent.py:162`) runs the blocking `provider.complete`/
`stream` call on a daemon worker thread and polls `done.wait(0.05)` on the main
thread — a blocking socket read swallows `KeyboardInterrupt` until it returns, so
without the poll, Esc would feel dead while "thinking...". `interrupt_on_escape()`
(`kbcode/interrupt.py:107`) is the watcher that raises it (Windows `msvcrt`, POSIX
`termios`+`select`); the orphaned worker just finishes and its result is dropped.
At turn end the watcher is **joined**, not just signalled: it reads the console /
holds the tty, so leaving it alive would race the next prompt for stdin and eat
the user's first keystrokes — see [[gotchas]].

The same watcher now also powers **type-ahead** (Claude Code style): non-Esc
keystrokes feed a `TypeAhead` buffer (`kbcode/interrupt.py:40`) — printable
chars append, backspace edits, Enter commits a line — echoed live under the
spinner via `ui.live_note` (polled by `_TickingStatus._render`,
`kbcode/ui.py:302`). Committed lines reach the model MID-TURN:
`repl._poll_user_notes` (`kbcode/repl.py:277`) is wired to
`Agent.poll_user_notes`, and `Agent._deliver_user_notes()`
(`kbcode/agent.py:689`) piggybacks them on the round-trip's last tool result
(a separate user message would break the alternating-roles invariant) with a
triage instruction: urgent → apply now, else after the current task. Slash
commands stay in the REPL queue and run after the turn; on interrupt,
`TypeAhead.take_all_text()` puts everything typed back into the next prompt
(prompt_toolkit `default=` prefill). Shift+Tab mid-turn hits the watcher's
`on_shift_tab` callback → ask/auto toggle ([[safety]]).

See [[architecture]] for the big picture, [[vision]] for image/video routing
through providers, [[gotchas]] for the SDK-kwarg and threading traps.
