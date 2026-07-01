"""Auxiliary vision fallback (the Hermes idea): when the active model can't
accept image input directly, or for video — which none of kbcode's own
providers have a native code path for at all — describe the media with a
separate vision-capable model instead of failing outright.

Deliberately independent of the main provider/model. Tries, in order:

1. An explicit ``KBCODE_VISION_*`` override — trusted outright, since the
   user set it specifically for this purpose.
2. The *active* provider's own route, but only when its ``base_url`` is
   verifiably ``openrouter.ai`` — some presets (e.g. ``mimo``) point their
   ``key_env`` at ``OPENROUTER_API_KEY`` while ``KBCODE_BASE_URL`` overrides
   them to a vendor's own endpoint (Xiaomi's own MiMo API, say). In that case
   the value in ``OPENROUTER_API_KEY`` is that vendor's key, *not* a real
   OpenRouter credential — trusting the env var name alone silently 401s
   against the real openrouter.ai. Checking the resolved base_url avoids that.
3. Whichever other vision-capable key is already configured — Anthropic (if
   present, preferred: usually the best quality and already in most setups),
   then Gemini, then OpenAI. Each of those env var names is unambiguous.

Every function here returns ``None`` (never raises) when nothing is
configured or every candidate's call fails, so callers fall through to their
existing error handling instead of masking it with a new traceback.
"""

from __future__ import annotations

import os
from pathlib import Path

# (kind, base_url, model) for the OpenRouter / explicit-override candidates.
_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "google/gemini-2.0-flash-001"  # cheap, fast, natively multimodal

_DESCRIBE_SYSTEM = (
    "You are a vision assistant helping a coding agent that cannot see images "
    "or video itself. Describe what's shown thoroughly and precisely — any "
    "visible text verbatim, UI layout, error messages, diagrams, code, colors, "
    "actions/motion — then directly answer the question asked."
)


def _candidates(config) -> list[tuple[str, str, str | None, str]]:
    """Ordered ``(kind, api_key, base_url, model)`` candidates, most-trusted
    first. ``config`` is the *active* provider's ``Config`` (or ``None``)."""
    out: list[tuple[str, str, str | None, str]] = []

    explicit_key = os.environ.get("KBCODE_VISION_API_KEY")
    if explicit_key:
        kind = os.environ.get("KBCODE_VISION_KIND", "openai")
        base_url = os.environ.get("KBCODE_VISION_BASE_URL") or _DEFAULT_BASE_URL
        model = os.environ.get("KBCODE_VISION_MODEL") or _DEFAULT_MODEL
        out.append((kind, explicit_key, base_url, model))

    if config is not None and config.api_key and config.base_url and "openrouter.ai" in config.base_url:
        model = os.environ.get("KBCODE_VISION_MODEL") or _DEFAULT_MODEL
        out.append(("openai", config.api_key, config.base_url, model))

    if os.environ.get("ANTHROPIC_API_KEY"):
        out.append(("anthropic", os.environ["ANTHROPIC_API_KEY"], None, "claude-opus-4-8"))
    if os.environ.get("GEMINI_API_KEY"):
        out.append((
            "openai", os.environ["GEMINI_API_KEY"],
            "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash",
        ))
    if os.environ.get("OPENAI_API_KEY"):
        out.append(("openai", os.environ["OPENAI_API_KEY"], None, "gpt-4o"))

    return out


def available(config=None) -> bool:
    """Whether any auxiliary vision route is configured at all."""
    return bool(_candidates(config))


def _ask_image(kind: str, api_key: str, base_url: str | None, model: str,
               images: list[dict], question: str) -> str | None:
    """Describe images via kbcode's own provider abstraction — reuses
    AnthropicProvider/OpenAICompatibleProvider's existing image-embedding
    (``_to_native``) and retry logic instead of duplicating it."""
    try:
        from .config import Config
        from .provider import get_provider

        cfg = Config(
            project_dir=Path("."), kind=kind, model=model,
            base_url=base_url, api_key=api_key, max_tokens=1000,
        )
        provider = get_provider(cfg)
        resp = provider.complete(
            _DESCRIBE_SYSTEM,
            [{"role": "user", "content": question, "images": images}],
            [],
        )
        return (resp.text or "").strip() or None
    except Exception:  # noqa: BLE001 - try the next candidate instead
        return None


def _ask_video(api_key: str, base_url: str | None, model: str,
                video: dict, question: str) -> str | None:
    """Describe a video. Always a raw OpenAI-compatible call (``video_url``
    content part) — no provider here has a native video code path to reuse,
    and Anthropic's Messages API has no video content-part at all."""
    try:
        from openai import OpenAI

        url = f"data:{video['media_type']};base64,{video['data']}"
        client = OpenAI(api_key=api_key, base_url=base_url or _DEFAULT_BASE_URL)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _DESCRIBE_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "video_url", "video_url": {"url": url}},
                    ],
                },
            ],
            max_tokens=1500,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:  # noqa: BLE001 - try the next candidate instead
        return None


def describe_images(images: list[dict], question: str, config=None) -> str | None:
    """Describe attached images with an auxiliary vision model. ``images`` is
    the ``[{"media_type", "data"(base64)}]`` shape used everywhere else (see
    images.py). Tries every candidate route in order; returns the first
    successful description, or ``None`` if none worked."""
    if not images:
        return None
    q = (question or "").strip() or "Describe this image in detail."
    for kind, api_key, base_url, model in _candidates(config):
        text = _ask_image(kind, api_key, base_url, model, images, q)
        if text:
            return text
    return None


def describe_video(video: dict, question: str, config=None) -> str | None:
    """Describe an attached video with an auxiliary vision model. ``video``
    is ``{"media_type", "data"(base64)}`` (see videos.py). Skips any
    Anthropic candidate (no video support) and tries the rest in order;
    returns the first successful description, or ``None`` if none worked."""
    q = (question or "").strip() or "Describe what happens in this video in detail."
    for kind, api_key, base_url, model in _candidates(config):
        if kind == "anthropic":
            continue
        text = _ask_video(api_key, base_url, model, video, q)
        if text:
            return text
    return None
