"""clipboard.py — /copy's helpers: fenced-block extraction + clipboard write."""

from __future__ import annotations

from kbcode import clipboard
from kbcode.clipboard import copy_to_clipboard, extract_code_blocks


def test_extract_single_block_strips_fences_and_language_tag():
    text = "Here you go:\n```python\nprint('hi')\n```\ndone."
    assert extract_code_blocks(text) == ["print('hi')"]


def test_extract_multiple_blocks_in_order():
    text = "```\none\n```\nwords\n```js\ntwo\nlines\n```"
    assert extract_code_blocks(text) == ["one", "two\nlines"]


def test_extract_tilde_fences_and_empty_input():
    assert extract_code_blocks("~~~\nbody\n~~~") == ["body"]
    assert extract_code_blocks("") == []
    assert extract_code_blocks("no blocks here") == []


def test_extract_keeps_blank_lines_inside_a_block():
    text = "```\nfirst\n\nlast\n```"
    assert extract_code_blocks(text) == ["first\n\nlast"]


def test_extract_backticks_inside_body_do_not_close_the_block():
    # An indented/inline ``` inside the body isn't a closer (closer must be at
    # line start); a longer opener needs an equally long closer.
    text = "````\nuse ``` for fences\n````"
    assert extract_code_blocks(text) == ["use ``` for fences"]


def test_copy_reports_success_and_failure(monkeypatch):
    # Pin the platform branch so this passes on any OS/CI runner.
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: f"/usr/bin/{name}")
    sent = {}

    def fake_run(cmd, **kwargs):
        sent["cmd"], sent["input"] = cmd, kwargs["input"]

    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    assert copy_to_clipboard("hello") is None
    assert sent["cmd"] == ["wl-copy"]
    assert sent["input"] == b"hello"

    def boom(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(clipboard.subprocess, "run", boom)
    err = copy_to_clipboard("hello")
    assert err is not None and "not found" in err


def test_copy_reports_missing_clipboard_tool(monkeypatch):
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: None)
    err = copy_to_clipboard("hello")
    assert err is not None and "no clipboard tool" in err


def test_copy_windows_pipes_utf16_for_clip(monkeypatch):
    monkeypatch.setattr(clipboard.sys, "platform", "win32")
    sent = {}
    monkeypatch.setattr(
        clipboard.subprocess, "run",
        lambda cmd, **kwargs: sent.update(cmd=cmd, input=kwargs["input"]),
    )
    assert copy_to_clipboard("హలో") is None  # non-ASCII must survive clip.exe
    assert sent["cmd"] == ["clip"]
    assert sent["input"] == "హలో".encode("utf-16")
