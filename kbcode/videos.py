"""Video attachments (the Hermes idea, right-sized): load a local video file
for the auxiliary vision fallback (see vision_fallback.py) to describe.

Unlike images.py, this never attaches raw video to the main model — none of
kbcode's own providers (Anthropic Messages API, OpenAI-compatible chat
completions) have a native video content-part, so /video (cli.py) always
resolves a video straight to a text description before the main model ever
sees it.
"""

from __future__ import annotations

import base64
from pathlib import Path

_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
}

# Base64 expands a file by ~4/3; cap the source file so the resulting data URL
# stays well under what any provider will accept in one request.
_MAX_BYTES = 30 * 1024 * 1024


def load_video_file(path: str | Path) -> dict | None:
    """Load a video file by path, or ``None`` if it isn't a readable,
    supported, reasonably-sized video."""
    try:
        p = Path(path).expanduser()
    except Exception:  # noqa: BLE001
        return None
    if not p.is_file():
        return None
    mime = _MIME_TYPES.get(p.suffix.lower())
    if mime is None:
        return None
    if p.stat().st_size > _MAX_BYTES:
        return None
    return {"media_type": mime, "data": base64.b64encode(p.read_bytes()).decode("ascii")}
