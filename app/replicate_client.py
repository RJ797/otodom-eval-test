"""Replicate adapter for Flux (flux-2-klein-9b). Runner-only.

Returns raw image bytes plus timing so the experiment runner can upload and
record results uniformly with the Gemini path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import replicate

from app import config
from app.http_util import fetch_bytes


@dataclass
class FluxResult:
    ok: bool
    image_bytes: Optional[bytes] = None
    mime: str = "image/png"
    time_taken_ms: int = 0
    error: str = ""


_client: Optional[replicate.Client] = None


def get_client() -> "replicate.Client":
    global _client
    if _client is None:
        if not config.has_replicate_token():
            raise RuntimeError("REPLICATE_API_TOKEN is not set in the environment.")
        _client = replicate.Client(api_token=config.REPLICATE_API_TOKEN)
    return _client


def _to_bytes(output: Any) -> Optional[bytes]:
    """Normalize Replicate output (FileOutput, URL string, or list) to bytes."""
    item = output
    if isinstance(output, (list, tuple)):
        if not output:
            return None
        item = output[0]
    # Newer SDK returns FileOutput objects with .read()
    read = getattr(item, "read", None)
    if callable(read):
        return read()
    # Otherwise expect a URL string
    if isinstance(item, str) and item.startswith("http"):
        return fetch_bytes(item)
    return None


def generate(
    prompt: str,
    image_url: Optional[str] = None,
    model: Optional[str] = None,
) -> FluxResult:
    """Run the Flux model with a prompt and optional input image URL."""
    started = time.perf_counter()
    try:
        client = get_client()
    except RuntimeError as exc:
        return FluxResult(ok=False, error=str(exc))

    model_id = model or config.REPLICATE_FLUX_MODEL
    payload: dict[str, Any] = {
        config.REPLICATE_FLUX_PROMPT_FIELD: prompt,
        "go_fast": config.REPLICATE_FLUX_GO_FAST,
        "output_format": config.REPLICATE_FLUX_OUTPUT_FORMAT,
        "output_quality": config.REPLICATE_FLUX_OUTPUT_QUALITY,
        "output_megapixels": config.REPLICATE_FLUX_OUTPUT_MEGAPIXELS,
    }
    if image_url:
        # `images` is an array of input images (image-to-image, max 5).
        # match_input_image keeps the output's aspect ratio identical to input.
        payload[config.REPLICATE_FLUX_IMAGES_FIELD] = [image_url]
        payload["aspect_ratio"] = config.REPLICATE_FLUX_ASPECT_RATIO

    try:
        output = client.run(model_id, input=payload)
        data = _to_bytes(output)
    except Exception as exc:  # noqa: BLE001
        return FluxResult(
            ok=False,
            time_taken_ms=int((time.perf_counter() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )

    if not data:
        return FluxResult(
            ok=False,
            time_taken_ms=int((time.perf_counter() - started) * 1000),
            error="Replicate returned no image data.",
        )

    fmt = config.REPLICATE_FLUX_OUTPUT_FORMAT.lower()
    mime = "image/jpeg" if fmt in ("jpg", "jpeg") else f"image/{fmt}"
    return FluxResult(
        ok=True,
        image_bytes=data,
        mime=mime,
        time_taken_ms=int((time.perf_counter() - started) * 1000),
    )
