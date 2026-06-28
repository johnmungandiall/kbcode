"""Rough USD pricing for the /insights cost estimate (Hermes idea).

Prices are per 1,000,000 tokens (input, output) and are approximate — providers
change them and per-model tiers vary. Matched by substring of the model id, most
specific first. Unknown models report tokens only (cost shown as ``None``).
"""

from __future__ import annotations

# (substring, input $/MTok, output $/MTok). Order matters: first hit wins.
_PRICES: list[tuple[str, float, float]] = [
    ("claude-opus", 15.0, 75.0),
    ("claude-sonnet", 3.0, 15.0),
    ("claude-haiku", 0.80, 4.0),
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.0),
    ("gpt-4.1-mini", 0.40, 1.60),
    ("gpt-4.1", 2.0, 8.0),
    ("o4-mini", 1.10, 4.40),
    ("deepseek", 0.27, 1.10),
    ("gemini-2.0-flash", 0.10, 0.40),
    ("gemini-1.5-pro", 1.25, 5.0),
    ("gemini", 0.10, 0.40),
]


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD estimate for a token spend on ``model``, or None if pricing unknown."""
    m = (model or "").lower()
    for needle, in_price, out_price in _PRICES:
        if needle in m:
            return input_tokens / 1_000_000 * in_price + output_tokens / 1_000_000 * out_price
    return None
