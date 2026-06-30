"""Image attachments for vision-capable models.

Grab an image from the clipboard (what **Alt+V** does in the chat) or load one
from a file path (`/image <path>`), and return it as a small normalized dict::

    {"media_type": "image/png", "data": "<base64>"}

The agent carries that on a user turn (``messages[i]["images"]``) and each
provider turns it into its own vision format (Claude image blocks / OpenAI
``image_url`` data URLs).

Pillow is only needed for the *clipboard* path and for re-encoding odd file
types; plain image files (png/jpeg/gif/webp) load without it. Everything is
guarded — if Pillow is missing or the clipboard holds no image, the helpers
return ``None`` and the caller shows a friendly hint instead of crashing.
"""

from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import Path

# Formats the vision models accept. Anything else we re-encode to PNG (via Pillow).
_OK_MEDIA = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_MAX_DIM = 1568  # Claude's recommended max edge; keeps payload + tokens sane


def _encode_pil(im, media_type: str = "image/png") -> dict:
    """Encode a Pillow image to a base64 dict, downscaling very large ones."""
    if max(im.size) > _MAX_DIM:
        ratio = _MAX_DIM / max(im.size)
        im = im.resize((max(1, int(im.width * ratio)), max(1, int(im.height * ratio))))
    buf = io.BytesIO()
    try:
        im.save(buf, format="PNG")
    except Exception:  # noqa: BLE001 - exotic mode (e.g. CMYK) → flatten to RGB
        im.convert("RGB").save(buf, format="PNG")
    return {"media_type": "image/png", "data": base64.b64encode(buf.getvalue()).decode("ascii")}


def grab_clipboard_image() -> dict | None:
    """Return the image currently on the clipboard, or ``None``.

    Handles both a copied bitmap (e.g. a screenshot) and a copied image *file*
    (Explorer/Finder put filenames on the clipboard). Needs Pillow.
    """
    try:
        from PIL import Image, ImageGrab
    except Exception:  # noqa: BLE001 - Pillow not installed
        return None
    try:
        obj = ImageGrab.grabclipboard()
    except Exception:  # noqa: BLE001 - unsupported platform / empty clipboard
        return None
    if isinstance(obj, list):  # filenames were copied
        for path in obj:
            img = load_image_file(path)
            if img:
                return img
        return None
    if isinstance(obj, Image.Image):
        return _encode_pil(obj)
    return None


def load_image_file(path: str | Path) -> dict | None:
    """Load an image file by path, or ``None`` if it isn't a readable image.

    Directly-supported types (png/jpeg/gif/webp) within size limits are sent as
    is; anything oversized or in another format is re-encoded to PNG via Pillow
    (with a downscale). Without Pillow, only supported types load — as raw bytes.
    """
    try:
        p = Path(path).expanduser()
    except Exception:  # noqa: BLE001
        return None
    if not p.is_file():
        return None
    media, _ = mimetypes.guess_type(p.name)

    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - Pillow not installed
        Image = None

    if Image is not None:
        try:
            with Image.open(p) as im:
                im.load()
                # Re-encode if it's an unsupported format or too large to send.
                if media not in _OK_MEDIA or max(im.size) > _MAX_DIM:
                    return _encode_pil(im)
        except Exception:  # noqa: BLE001 - not a Pillow-readable image
            if media not in _OK_MEDIA:
                return None

    if media in _OK_MEDIA:
        return {"media_type": media, "data": base64.b64encode(p.read_bytes()).decode("ascii")}
    return None
