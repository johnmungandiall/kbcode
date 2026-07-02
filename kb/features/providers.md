# Providers — normalized messages, translation, resilience, interrupts.

## Normalized messages + `raw` replay
`Agent.messages` (`kbcode/agent.py:92`) is provider-agnostic, never a provider's native
shape: `{"role":"user","content"}` (+ optional `"images"`), `{"role":"assistant",
"text","tool_calls","raw"}`, `{"role":"tool_results","results"}`. Each provider's
`_to_native` (Anthropic `kbcode/provider.py:181`, OpenAI-compatible `kbcode/provider.py:358`)
translates to/from its own API and stores the model's own assistant payload back
in `raw` so the next request replays it losslessly (Claude thinking blocks vs
OpenAI `tool_calls` differ structurally). **Invariant:** normalized<->native must
round-trip, and user/assistant turns must stay alternating after any message-list
surgery (see [[context-management]] on compaction). A session uses exactly one
provider, so `raw` is always that provider's shape — session replay requires a
matching provider (see [[sessions]]).

`get_provider()` (`kbcode/provider.py:489`) dispatches on `config.kind`. Every
non-Claude provider (OpenAI, Gemini, DeepSeek, OpenRouter, MiMo, custom) is the
*same* `OpenAICompatibleProvider` (`kbcode/provider.py:324`) with a different
`base_url`. `AnthropicProvider.complete` (`kbcode/provider.py:226`) tries a staged
kwargs fallback (`thinking`+`output_config` -> `thinking` -> plain), catching
`TypeError` per attempt for older SDKs.

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
Every real API call goes through `_with_retry()` (`kbcode/provider.py:100`): transient
failures (429/5xx/connection/timeout, classified by `_classify()` at
`kbcode/provider.py:62` from SDK-agnostic `status_code`+message) retry with exponential
backoff (`_MAX_RETRIES`/`_BACKOFF_BASE`, `kbcode/provider.py:58-59`). Hard errors
(401/403/4xx) raise `ProviderError` (`kbcode/provider.py:42`) immediately, no retry.
`_with_retry` deliberately re-raises `TypeError` untouched so the Anthropic
staged fallback still works.

## Interrupt mid-request
`Agent._complete()` (`kbcode/agent.py:126`) runs the blocking `provider.complete`/
`stream` call on a daemon worker thread and polls `done.wait(0.05)` on the main
thread — a blocking socket read swallows `KeyboardInterrupt` until it returns, so
without the poll, Esc would feel dead while "thinking...". `interrupt_on_escape()`
(`kbcode/interrupt.py:26`) is the watcher that raises it (Windows `msvcrt`, POSIX
`termios`+`select`); the orphaned worker just finishes and its result is dropped.
At turn end the watcher is **joined**, not just signalled (`kbcode/interrupt.py:47-48`):
it reads the console / holds the tty, so leaving it alive would race the next prompt
for stdin and eat the user's first keystrokes — see [[gotchas]].

See [[architecture]] for the big picture, [[vision]] for image/video routing
through providers, [[gotchas]] for the SDK-kwarg and threading traps.
