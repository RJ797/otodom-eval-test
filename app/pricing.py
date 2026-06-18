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
    if not token_usage:
        return 0.0
    prompt_tokens = token_usage.get("prompt") or 0
    output_tokens = token_usage.get("candidates") or 0
    cost = (
        prompt_tokens * config.GEMINI_PRICE_INPUT_PER_1M
        + output_tokens * config.GEMINI_PRICE_OUTPUT_PER_1M
    ) / 1_000_000
    return round(cost, 6)


def flux_cost() -> float:
    return round(config.FLUX_COST_PER_IMAGE, 6)
