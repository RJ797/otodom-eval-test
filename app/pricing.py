"""Cost calculation.

The Gemini API returns only token counts (no USD cost), so Gemini cost is
computed from tokens using configurable per-1M rates. For image models, the
generated image is billed as output (`candidates`) tokens. Flux has no usage in
its response, so it uses a flat per-image rate.
"""

from __future__ import annotations

from typing import Optional

from app import config


def gemini_cost(token_usage: Optional[dict]) -> float:
    """Cost from token counts. `candidates` tokens include text + image output;
    image output is billed at a much higher rate, so split them out."""
    if not token_usage:
        return 0.0
    input_tokens = token_usage.get("prompt") or 0
    candidates = token_usage.get("candidates") or 0
    image_output = token_usage.get("image_output") or 0
    text_output = max(0, candidates - image_output)
    cost = (
        input_tokens * config.GEMINI_PRICE_INPUT_PER_1M
        + text_output * config.GEMINI_PRICE_TEXT_OUTPUT_PER_1M
        + image_output * config.GEMINI_PRICE_IMAGE_OUTPUT_PER_1M
    ) / 1_000_000
    return round(cost, 6)


def flux_cost() -> float:
    return round(config.FLUX_COST_PER_IMAGE, 6)
