"""Reusable Gemini client — the single seam through which ALL Gemini calls flow.

Both the FastAPI endpoints and any future load-test runner (e.g. Locust under
./loadtest) should import and call these functions. Keeping every SDK detail in
one place means the load test can reuse identical request logic with zero
duplication.

Return values are plain dicts (JSON-serializable) carrying the result plus
timing/usage metadata, which is exactly what a load test wants to assert on.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from google import genai
from google.genai import types

from app import config


# --- Client construction -----------------------------------------------------
# A single shared client is fine and recommended; the SDK handles concurrency.
_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    """Lazily build the shared SDK client from the env-provided key."""
    global _client
    if _client is None:
        if not config.has_api_key():
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your .env file."
            )
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


@dataclass
class ImageInput:
    """An image to send INTO a model (vision/multimodal input)."""

    data: bytes
    mime_type: str = "image/png"


@dataclass
class GenResult:
    """Normalized result returned by every call (load-test friendly)."""

    ok: bool
    model: str
    text: str = ""
    thoughts: str = ""
    images: list[dict[str, str]] = field(default_factory=list)  # {mime_type, data_b64}
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: Optional[float] = None  # billed cost reported by the Gemini API
    latency_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "model": self.model,
            "text": self.text,
            "thoughts": self.thoughts,
            "images": self.images,
            "usage": self.usage,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def _extract_usage(resp: Any) -> dict[str, Any]:
    usage = getattr(resp, "usage_metadata", None)
    if not usage:
        return {}
    out: dict[str, Any] = {}
    for key in (
        "prompt_token_count",
        "candidates_token_count",
        "thoughts_token_count",
        "total_token_count",
    ):
        val = getattr(usage, key, None)
        if val is not None:
            out[key] = val
    return out


def _extract_cost(resp: Any) -> Optional[float]:
    """Best-effort read of the billed cost the Gemini API reports in the response.

    Checks a few likely locations (top-level and usage_metadata) for a cost field.
    Returns None if the response does not carry a cost.
    """
    candidates = [resp, getattr(resp, "usage_metadata", None), getattr(resp, "metadata", None)]
    fields = ("cost", "cost_usd", "total_cost", "total_cost_usd", "billed_cost", "estimated_cost")
    for obj in candidates:
        if obj is None:
            continue
        for name in fields:
            val = getattr(obj, name, None)
            if isinstance(val, (int, float)):
                return float(val)
    return None


def _build_contents(prompt: str, images: Optional[list[ImageInput]]) -> list[Any]:
    parts: list[Any] = []
    if prompt:
        parts.append(types.Part.from_text(text=prompt))
    for img in images or []:
        parts.append(types.Part.from_bytes(data=img.data, mime_type=img.mime_type))
    return parts


def generate_text(
    prompt: str,
    model: str = config.DEFAULT_TEXT_MODEL,
    images: Optional[list[ImageInput]] = None,
    *,
    thinking: bool = True,
    thinking_budget: Optional[int] = None,
    include_thoughts: bool = True,
    temperature: Optional[float] = None,
    system_instruction: Optional[str] = None,
) -> GenResult:
    """Text/multimodal generation with optional thinking.

    - `thinking=True` enables the thinking process. `thinking_budget` controls the
      token budget (-1 = dynamic/auto, 0 = off). `include_thoughts` returns the
      thought summary so you can see it in the playground.
    - Pass `images` to do vision (image-in) prompting.
    """
    started = time.perf_counter()
    try:
        client = get_client()
    except RuntimeError as exc:
        return GenResult(ok=False, model=model, error=str(exc))

    cfg_kwargs: dict[str, Any] = {}
    if temperature is not None:
        cfg_kwargs["temperature"] = temperature
    if system_instruction:
        cfg_kwargs["system_instruction"] = system_instruction

    if thinking:
        thinking_kwargs: dict[str, Any] = {"include_thoughts": include_thoughts}
        if thinking_budget is not None:
            thinking_kwargs["thinking_budget"] = thinking_budget
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(**thinking_kwargs)
    else:
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

    config_obj = types.GenerateContentConfig(**cfg_kwargs) if cfg_kwargs else None

    try:
        resp = client.models.generate_content(
            model=model,
            contents=_build_contents(prompt, images),
            config=config_obj,
        )
    except Exception as exc:  # noqa: BLE001 - surface any SDK/API error to caller
        return GenResult(
            ok=False,
            model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )

    text_parts: list[str] = []
    thought_parts: list[str] = []
    candidates = getattr(resp, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if not part_text:
                continue
            if getattr(part, "thought", False):
                thought_parts.append(part_text)
            else:
                text_parts.append(part_text)

    return GenResult(
        ok=True,
        model=model,
        text="".join(text_parts),
        thoughts="\n".join(thought_parts),
        usage=_extract_usage(resp),
        cost_usd=_extract_cost(resp),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def generate_image(
    prompt: str,
    model: str = config.DEFAULT_IMAGE_MODEL,
    images: Optional[list[ImageInput]] = None,
    *,
    thinking_level: str = config.DEFAULT_IMAGE_THINKING_LEVEL,
    image_size: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    temperature: Optional[float] = None,
) -> GenResult:
    """Image generation (and image editing when input images are provided).

    Uses IMAGE-only response modality and a thinking level (HIGH / MINIMAL),
    mirroring the official sample. Returned images are base64 data URLs ready
    for the UI.
    """
    started = time.perf_counter()
    try:
        client = get_client()
    except RuntimeError as exc:
        return GenResult(ok=False, model=model, error=str(exc))

    cfg_kwargs: dict[str, Any] = {"response_modalities": ["IMAGE"]}
    if temperature is not None:
        cfg_kwargs["temperature"] = temperature
    if thinking_level:
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_level=thinking_level
        )

    image_cfg_kwargs: dict[str, Any] = {}
    if image_size:
        image_cfg_kwargs["image_size"] = image_size
    if aspect_ratio:
        image_cfg_kwargs["aspect_ratio"] = aspect_ratio
    if image_cfg_kwargs:
        cfg_kwargs["image_config"] = types.ImageConfig(**image_cfg_kwargs)

    try:
        resp = client.models.generate_content(
            model=model,
            contents=_build_contents(prompt, images),
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
    except Exception as exc:  # noqa: BLE001
        return GenResult(
            ok=False,
            model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )

    out_images: list[dict[str, str]] = []
    text_parts: list[str] = []
    candidates = getattr(resp, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                raw = inline.data
                b64 = raw if isinstance(raw, str) else base64.b64encode(raw).decode()
                out_images.append(
                    {
                        "mime_type": getattr(inline, "mime_type", "image/png"),
                        "data_b64": b64,
                    }
                )
            elif getattr(part, "text", None):
                text_parts.append(part.text)

    return GenResult(
        ok=True,
        model=model,
        text="".join(text_parts),
        images=out_images,
        usage=_extract_usage(resp),
        cost_usd=_extract_cost(resp),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
