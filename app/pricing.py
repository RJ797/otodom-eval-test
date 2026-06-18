"""Cost calculation.

Gemini cost comes directly from the Gemini API response (see gemini_client),
so no token-rate math is needed here. Flux has no per-call cost in its response,
so it uses a flat per-image rate from config/env.
"""

from __future__ import annotations

from app import config


def flux_cost() -> float:
    return round(config.FLUX_COST_PER_IMAGE, 6)
