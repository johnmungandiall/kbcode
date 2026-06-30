"""Recover tool calls a model wrote as **plain text** (the openclaw idea).

Stronger models use the provider's structured function-calling interface, so a
tool request arrives as a real ``tool_calls`` entry. Weaker / OpenAI-compatible
models often don't — they *write the call out as text* in the assistant message,
in one of a few shapes::

    [read_file]
    {"path": "main.py"}

    [tool:read_file]
    {"path": "main.py"}

    <read_file>{"path": "main.py"}</read_file>

    {"tool": "read_file", "arguments": {"path": "main.py"}}
    {"name": "read_file", "arguments": {"path": "main.py"}}
    {"function": {"name": "read_file", "arguments": "{\"path\": \"main.py\"}"}}

When that happens the provider reports *no* structured tool calls, so the agent
loop treats the text as a final answer and the task silently stalls. :func:`promote`
scans the text, recovers any tool calls it can confidently parse, and returns
them alongside the text with those blocks stripped out — so the agent can run
them and nudge the model back to the proper format instead of hard-failing.

This sits one layer *above* ``Tools._repair`` (which fixes an already-parsed
call's name/args). Here we recover the call that was never parsed at all.

Conservative on purpose: a block is only promoted when its tool name is one the
model was actually offered (``allowed_names``), so ordinary prose or JSON the
user asked for is never mistaken for a tool call.
"""

from __future__ import annotations

import json
import re
from typing import Iterable, Iterator

_NAME = r"[A-Za-z_][A-Za-z0-9_.-]*"
_OPEN_BRACKET = re.compile(r"\[(?:tool:)?(" + _NAME + r")\]")
_OPEN_TAG = re.compile(r"<(" + _NAME + r")>")

# (start, end, name, args) — source span of the recognized block plus the call.
_Span = tuple[int, int, str, dict]


def promote(text: str, allowed_names: Iterable[str]) -> tuple[list[tuple[str, dict]], str]:
    """Pull plain-text tool calls out of ``text``.

    Returns ``(calls, cleaned_text)`` where ``calls`` is a list of
    ``(name, args)`` pairs and ``cleaned_text`` is ``text`` with the recognized
    blocks removed (stripped). Returns ``([], text)`` when nothing is found.
    """
    allowed = set(allowed_names)
    if not text or not allowed:
        return [], text

    spans: list[_Span] = []
    for finder in (_find_bracketed, _find_tagged, _find_keyed_json):
        spans.extend(finder(text, allowed))
    if not spans:
        return [], text

    spans.sort(key=lambda s: s[0])
    chosen: list[_Span] = []
    last_end = -1
    for span in spans:
        if span[0] < last_end:  # overlaps a block we already took (e.g. JSON inside a tag)
            continue
        chosen.append(span)
        last_end = span[1]

    calls = [(name, args) for _, _, name, args in chosen]
    cleaned: list[str] = []
    idx = 0
    for start, end, _, _ in chosen:
        cleaned.append(text[idx:start])
        idx = end
    cleaned.append(text[idx:])
    return calls, "".join(cleaned).strip()


def _json_object_at(text: str, i: int) -> int | None:
    """If ``text[i]`` opens a JSON object, return the index just past its ``}``."""
    if i >= len(text) or text[i] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
    return None


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _args_at(text: str, after: int) -> tuple[dict, int] | None:
    """Parse a ``{...}`` object that begins (after whitespace) at ``after``."""
    j = _skip_ws(text, after)
    end = _json_object_at(text, j)
    if end is None:
        return None
    try:
        obj = json.loads(text[j:end])
    except ValueError:
        return None
    return (obj, end) if isinstance(obj, dict) else None


def _block_end(text: str, end: int, close: str) -> int:
    """Extend ``end`` past an optional closing marker like ``[/name]`` / ``</name>``."""
    k = _skip_ws(text, end)
    return k + len(close) if text.startswith(close, k) else end


def _find_bracketed(text: str, allowed: set[str]) -> Iterator[_Span]:
    for m in _OPEN_BRACKET.finditer(text):
        name = m.group(1)
        if name not in allowed:
            continue
        parsed = _args_at(text, m.end())
        if parsed is None:
            continue
        args, end = parsed
        yield m.start(), _block_end(text, end, f"[/{name}]"), name, args


def _find_tagged(text: str, allowed: set[str]) -> Iterator[_Span]:
    for m in _OPEN_TAG.finditer(text):
        name = m.group(1)
        if name not in allowed:
            continue
        parsed = _args_at(text, m.end())
        if parsed is None:
            continue
        args, end = parsed
        yield m.start(), _block_end(text, end, f"</{name}>"), name, args


def _find_keyed_json(text: str, allowed: set[str]) -> Iterator[_Span]:
    """Bare ``{"name"/"tool"/"function", "arguments"/...}`` objects anywhere in the text."""
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        end = _json_object_at(text, i)
        if end is None:
            i += 1
            continue
        try:
            obj = json.loads(text[i:end])
        except ValueError:
            i += 1
            continue
        call = _as_tool_call(obj, allowed) if isinstance(obj, dict) else None
        if call is not None:
            yield i, end, call[0], call[1]
        i = end  # already consumed this object; don't rescan its insides


def _as_tool_call(obj: dict, allowed: set[str]) -> tuple[str, dict] | None:
    """Read ``{name, arguments}`` (and OpenAI ``{function:{...}}``) shapes."""
    fn = obj.get("function")
    if isinstance(fn, dict):
        name, args = fn.get("name"), fn.get("arguments")
    else:
        name = obj.get("name") or obj.get("tool") or (fn if isinstance(fn, str) else None)
        args = obj.get("arguments")
        if args is None:
            args = obj.get("parameters")
        if args is None:
            args = obj.get("input")
        if args is None:
            args = obj.get("args")

    if not isinstance(name, str) or name not in allowed:
        return None
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return None
    if args is None:
        args = {}
    return (name, args) if isinstance(args, dict) else None
