"""Auxiliary vision fallback (the Hermes idea): when the active model can't
accept image input directly, or for video — which none of kbcode's own
providers have a native code path for at all — describe the media with a
separate vision-capable model instead of failing outright.

Deliberately independent of the main provider/model: resolves its own
OpenAI-compatible endpoint from ``KBCODE_VISION_*`` env vars, falling back to
``OPENROUTER_API_KEY`` since most non-Anthropic/OpenAI presets (mimo,
openrouter itself) already route through OpenRouter — so this typically needs
zero extra configuration. Every function here returns ``None`` (never raises)
when nothing is configured or the call itself fails, so callers fall through
to their existing error handling instead of masking it with a new traceback.
"""

from __future__ import annotations

import os

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "google/gemini-2.0-flash-001"  # cheap, fast, natively multimodal

_DESCRIBE_SYSTEM = (
    "You are a vision assistant helping a coding agent that cannot see images "
    "or video itself. Describe what's shown thoroughly and precisely — any "
    "visible text verbatim, UI layout, error messages, diagrams, code, colors, "
    "actions/motion — then directly answer the question asked."
)


def _resolve() -> tuple[str, str, str] | None:
    api_key = (
        os.environ.get("KBCODE_VISION_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("KBCODE_API_KEY")
    )
    if not api_key:
        return None
    base_url = os.environ.get("KBCODE_VISION_BASE_URL") or _DEFAULT_BASE_URL
    model = os.environ.get("KBCODE_VISION_MODEL") or _DEFAULT_MODEL
    return api_key, base_url, model


def available() -> bool:
    """Whether an auxiliary vision route is configured at all."""
    return _resolve() is not None


def _ask(parts: list[dict], max_tokens: int) -> str | None:
    resolved = _resolve()
    if resolved is None:
        return None
    api_key, base_url, model = resolved
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _DESCRIBE_SYSTEM},
                {"role": "user", "content": parts},
            ],
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:  # noqa: BLE001 - any failure just means "no fallback available"
        return None


def describe_images(images: list[dict], question: str) -> str | None:
    """Describe attached images with the auxiliary vision model. ``images`` is
    the ``[{"media_type", "data"(base64)}]`` shape used everywhere else (see
    images.py). Returns the description, or ``None``."""
    if not images:
        return None
    parts: list[dict] = [
        {"type": "text", "text": (question or "").strip() or "Describe this image in detail."}
    ]
    for im in images:
        url = f"data:{im['media_type']};base64,{im['data']}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return _ask(parts, max_tokens=1000)


def describe_video(video: dict, question: str) -> str | None:
    """Describe an attached video with the auxiliary vision model. ``video``
    is ``{"media_type", "data"(base64)}`` (see videos.py). Returns the
    description, or ``None``."""
    url = f"data:{video['media_type']};base64,{video['data']}"
    parts = [
        {
            "type": "text",
            "text": (question or "").strip() or "Describe what happens in this video in detail.",
        },
        {"type": "video_url", "video_url": {"url": url}},
    ]
    return _ask(parts, max_tokens=1500)
