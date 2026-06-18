"""Deterministic blind ordering for scoring.

Given a run + image, produce a stable randomized A/B/C order of the variants so a
tester sees outputs in an unbiased order. The mapping is reproducible (seeded by
run_id + image_id) so re-loading the same item is consistent.
"""

from __future__ import annotations

import hashlib
import random

LABELS = ["A", "B", "C", "D", "E", "F"]


def _seed(run_id: str, image_id: int) -> int:
    h = hashlib.sha256(f"{run_id}:{image_id}".encode()).hexdigest()
    return int(h[:16], 16)


def blind_order(run_id: str, image_id: int, variants: list[str]) -> list[dict]:
    """Return [{label, variant}] in a stable shuffled order."""
    ordered = list(variants)
    random.Random(_seed(run_id, image_id)).shuffle(ordered)
    return [{"label": LABELS[i], "variant": v} for i, v in enumerate(ordered)]
