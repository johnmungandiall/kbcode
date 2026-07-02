"""Put text on the system clipboard (what **/copy** does in the chat) and
pull fenced code blocks out of a reply to feed it.

No new dependencies: each platform already ships a clipboard writer we can
pipe into — ``clip.exe`` (Windows), ``pbcopy`` (macOS), ``wl-copy`` /
``xclip`` / ``xsel`` (Linux, first one found wins). Reading images FROM the
clipboard is a different feature and lives in images.py.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys

# A fenced block: ``` or ~~~ opener (optionally with a language tag), the
# body, then a matching closer at line start. Non-greedy so back-to-back
# blocks split correctly.
_FENCE = re.compile(
    r"^(?P<fence>```+|~~~+)[^\n]*\n(?P<body>.*?)^(?P=fence)[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


def extract_code_blocks(text: str) -> list[str]:
    """All fenced code-block bodies in *text*, in order, fences stripped."""
    return [m.group("body").rstrip("\n") for m in _FENCE.finditer(text or "")]


def copy_to_clipboard(text: str) -> str | None:
    """Copy *text* to the system clipboard. Returns None on success, or a
    short human-readable reason on failure (missing tool, subprocess error) —
    the caller shows it as a notice rather than crashing the REPL."""
    if sys.platform == "win32":
        # clip.exe treats input as the OEM codepage unless it sees a UTF-16LE
        # BOM — encode UTF-16 (BOM included) so non-ASCII survives.
        cmd, payload = ["clip"], text.encode("utf-16")
    elif sys.platform == "darwin":
        cmd, payload = ["pbcopy"], text.encode("utf-8")
    else:
        for candidate in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            if shutil.which(candidate[0]):
                cmd, payload = candidate, text.encode("utf-8")
                break
        else:
            return "no clipboard tool found — install wl-clipboard, xclip, or xsel"
    try:
        subprocess.run(cmd, input=payload, check=True, capture_output=True, timeout=10)
    except FileNotFoundError:
        return f"{cmd[0]} not found on PATH"
    except Exception as exc:  # noqa: BLE001 - clipboard failure must never crash the REPL
        return str(exc)
    return None
