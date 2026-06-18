"""Single interface to run any model variant. Runner-only.

`run_variant(key, prompt, image_bytes, mime, input_image_url)` dispatches on the
variant's provider and returns a normalized output dict ready to store in the
`results` document. This is the seam a load test would reuse.
"""

from __future__ import annotations

import base64
from typing import Any, Optional

from app import config, gemini_client, pricing, replicate_client


def variant_meta(key: str) -> dict:
    return config.VARIANTS[key]


def _gemini(key: str, prompt: str, image_bytes: Optional[bytes], mime: str) -> dict[str, Any]:
    meta = config.VARIANTS[key]
    images = (
        [gemini_client.ImageInput(data=image_bytes, mime_type=mime)]
        if image_bytes
        else None
    )
    aspect = config.GEMINI_IMAGE_ASPECT_RATIO
    res = gemini_client.generate_image(
        prompt=prompt,
        model=meta["model"],
        images=images,
        thinking_level=meta["thinking_level"],
        image_size=config.GEMINI_IMAGE_SIZE,
        aspect_ratio=None if str(aspect).lower() == "auto" else aspect,
    )
    out: dict[str, Any] = {
        "model": meta["model"],
        "thinking_level": meta["thinking_level"],
        "status": "ok" if res.ok else "error",
        "time_taken_ms": res.latency_ms,
        "token_usage": res.usage or None,
        "error": res.error or None,
        "image_bytes": None,
        "mime": "image/png",
    }
    if res.ok and res.images:
        first = res.images[0]
        out["image_bytes"] = base64.b64decode(first["data_b64"])
        out["mime"] = first.get("mime_type", "image/png")
    elif res.ok and not res.images:
        out["status"] = "error"
        out["error"] = "Model returned no image."
    # Gemini API returns only token counts (no USD), so compute cost from tokens.
    out["cost_usd"] = pricing.gemini_cost(out["token_usage"]) if out["status"] == "ok" else 0.0
    return out


def _flux(key: str, prompt: str, input_image_url: Optional[str]) -> dict[str, Any]:
    meta = config.VARIANTS[key]
    res = replicate_client.generate(prompt=prompt, image_url=input_image_url, model=meta["model"])
    return {
        "model": meta["model"],
        "thinking_level": None,
        "status": "ok" if res.ok else "error",
        "time_taken_ms": res.time_taken_ms,
        "token_usage": None,
        "error": res.error or None,
        "image_bytes": res.image_bytes,
        "mime": res.mime,
        "cost_usd": pricing.flux_cost() if res.ok else 0.0,
    }


def run_variant(
    key: str,
    prompt: str,
    image_bytes: Optional[bytes] = None,
    mime: str = "image/png",
    input_image_url: Optional[str] = None,
) -> dict[str, Any]:
    """Run one variant; returns a normalized dict including raw `image_bytes`.

    The caller uploads `image_bytes` to S3 and strips it before storing in Mongo.
    """
    meta = config.VARIANTS.get(key)
    if not meta:
        return {"status": "error", "error": f"Unknown variant '{key}'", "image_bytes": None}
    if meta["provider"] == "gemini":
        return _gemini(key, prompt, image_bytes, mime)
    if meta["provider"] == "replicate":
        return _flux(key, prompt, input_image_url)
    return {"status": "error", "error": f"Unknown provider for '{key}'", "image_bytes": None}
