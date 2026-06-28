"""Context compaction — the Hermes "keep going on long sessions" idea.

A coding session can run for many turns. Left alone, the whole transcript is
re-sent to the model every step, which gets slow, expensive, and eventually
overflows the context window. Hermes solves this by *compacting*: summarize the
middle of the conversation into one short recap and keep working.

Strategy (from Hermes' trajectory compressor):
  1. protect the first exchange  — the original task framing.
  2. protect the last few exchanges — recent, in-flight work.
  3. summarize everything in between into a single recap.
  4. splice that recap onto the start of the protected tail.

We work on the *normalized* message format (see provider.py), so this is
provider-agnostic: it compacts a Claude session and an OpenAI session the same
way. An "exchange" starts at each genuine user turn (role == "user"); tool
results and assistant replies belong to the exchange above them.
"""

from __future__ import annotations

import json

from .provider import LLMProvider

_SUMMARY_SYSTEM = (
    "You compress an in-progress software engineering session into a faithful "
    "recap for the same agent to keep working from. Be concrete and factual; "
    "never invent progress that didn't happen."
)

_SUMMARY_INSTRUCTION = (
    "Summarize the conversation below into a compact recap the agent can resume "
    "from. Capture, as short bullet points:\n"
    "- the user's goal and any explicit instructions or preferences;\n"
    "- decisions made and why;\n"
    "- files created or edited, with the key change in each;\n"
    "- commands run and their result (pass/fail);\n"
    "- the current state and what is still left to do.\n"
    "Keep names, paths, and identifiers exact. Omit chit-chat."
)


def estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimate (~4 chars/token) over the whole message list."""
    total = 0
    for m in messages:
        try:
            total += len(json.dumps(m, default=str))
        except (TypeError, ValueError):
            total += len(str(m))
    return total // 4


def _exchange_starts(messages: list[dict]) -> list[int]:
    """Indices where a genuine user turn begins a new exchange."""
    return [i for i, m in enumerate(messages) if m["role"] == "user"]


def _short(value: object, limit: int = 80) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _render(messages: list[dict]) -> str:
    """Flatten normalized messages into a readable transcript for summarizing."""
    lines: list[str] = []
    for m in messages:
        role = m["role"]
        if role == "user":
            lines.append(f"USER: {m['content']}")
        elif role == "assistant":
            text = (m.get("text") or "").strip()
            if text:
                lines.append(f"ASSISTANT: {text}")
            for tc in m.get("tool_calls") or []:
                lines.append(f"ASSISTANT called {tc.name}({_short(tc.input)})")
        elif role == "tool_results":
            for r in m["results"]:
                body = _short(r["content"], 400)
                tag = "error" if r["is_error"] else "ok"
                lines.append(f"TOOL[{tag}]: {body}")
    return "\n".join(lines)


def _summarize(provider: LLMProvider, transcript: str) -> str:
    msg = [{"role": "user", "content": f"{_SUMMARY_INSTRUCTION}\n\n--- CONVERSATION ---\n{transcript}"}]
    try:
        resp = provider.complete(_SUMMARY_SYSTEM, msg, [])
        return resp.text.strip() or "(summary unavailable)"
    except Exception as exc:  # noqa: BLE001 - never let compaction crash the run
        return f"(summary failed: {exc})"


def compact(
    messages: list[dict],
    provider: LLMProvider,
    keep_head: int = 1,
    keep_tail: int = 2,
) -> tuple[list[dict], str | None]:
    """Return (new_messages, summary). If there isn't enough to compact, returns
    the original messages and None.

    Keeps the first ``keep_head`` exchanges and the last ``keep_tail`` exchanges
    intact, summarizes the middle, and prepends that recap to the first kept
    tail turn. Each protected exchange ends on an assistant turn, so the spliced
    recap (a user turn) preserves user/assistant alternation for every provider.
    """
    starts = _exchange_starts(messages)
    if len(starts) < keep_head + keep_tail + 1:
        return messages, None

    head_end = starts[keep_head]
    tail_start = starts[len(starts) - keep_tail]
    if tail_start <= head_end:
        return messages, None

    head = messages[:head_end]
    middle = messages[head_end:tail_start]
    tail = messages[tail_start:]

    summary = _summarize(provider, _render(middle))

    recap = (
        "[Recap of earlier conversation, summarized to save context]\n"
        f"{summary}\n"
        "[End recap — continuing with the current request]\n\n"
    )
    spliced = dict(tail[0])
    spliced["content"] = recap + str(spliced["content"])
    return head + [spliced] + tail[1:], summary
