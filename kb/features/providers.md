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

`get_provider()` (`kbcode/provider.py:596`) dispatches on `config.kind`. Every
non-Claude provider (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, custom) is the
*same* `OpenAICompatibleProvider` (`kbcode/provider.py:408`) with a different
`base_url`. `AnthropicProvider.complete` (`kbcode/provider.py:144`) tries a staged
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
miss — expected, one-time. `_usage()` (`kbcode/provider.py:278`) folds
`cache_creation_input_tokens` + `cache_read_input_tokens` back into
`input_tokens` (the API reports only the uncached remainder there) so /cost
and turn summaries stay comparable; the estimate is conservative (cache reads
actually bill at ~0.1x). Tests: `tests/test_provider_caching.py`.

## Streaming tool-name hints
`stream(..., on_tool=)` (base signature `kbcode/provider.py:147`) reports each
tool call's *name* the moment it appears mid-stream, so a long tool-call-heavy
response doesn't look frozen while the arguments JSON generates. The Anthropic
path iterates the SDK's event stream (synthetic `"text"` events for deltas,
`content_block_start` with a `tool_use` block for names) instead of the old
`text_stream`; the OpenAI path fires on the first name fragment per tool-call
index. `Agent._complete()` forwards `on_tool` and `Agent.run` passes
`ui.stream_tool_hint` (`kbcode/ui.py:566`), which prints one dim `⏺ name …`
line after stopping any live spinner (it's the only mid-stream printer left —
see [[gotchas]]). Text chunks themselves are NOT printed: `ui.stream_chunk`
only feeds a `writing… N chars` progress label into the thinking spinner, and
the complete reply is markdown-rendered by `ui.assistant_text` once the
response resolves. The real described `tool_call()` line still follows when
the response resolves.

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

## Interrupt mid-request
`Agent._complete()` (`kbcode/agent.py:132`) runs the blocking `provider.complete`/
`stream` call on a daemon worker thread and polls `done.wait(0.05)` on the main
thread — a blocking socket read swallows `KeyboardInterrupt` until it returns, so
without the poll, Esc would feel dead while "thinking...". `interrupt_on_escape()`
(`kbcode/interrupt.py:58`) is the watcher that raises it (Windows `msvcrt`, POSIX
`termios`+`select`); the orphaned worker just finishes and its result is dropped.
At turn end the watcher is **joined**, not just signalled (`kbcode/interrupt.py:47-48`):
it reads the console / holds the tty, so leaving it alive would race the next prompt
for stdin and eat the user's first keystrokes — see [[gotchas]].

See [[architecture]] for the big picture, [[vision]] for image/video routing
through providers, [[gotchas]] for the SDK-kwarg and threading traps.
