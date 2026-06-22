"""Standalone Gemini sample: send a prompt + image (from a URL), print the full
response and token usage. Independent of the rest of the app.

Usage:
    python scripts/gemini_sample.py
    python scripts/gemini_sample.py https://example.com/some.webp

Reads GEMINI_API_KEY from the environment (.env is loaded automatically).
Edit PROMPT below. Default input image is IMAGE_URL.
"""

from __future__ import annotations

import mimetypes
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ---- Edit these -------------------------------------------------------------
PROMPT = """The space type is : Dining area Image edit only. Stage and refurnish this room in photorealistic Boho style using movable furniture and decor only. Keep the original room unchanged: camera angle, perspective, layout, walls, wall finish, floor, ceiling, doors, windows, trims, built-ins, and light fixtures. For bathrooms only add relevant decors and no furnitures. Do not overfill the room — add only relevant, purposeful furniture and decor, not too many pieces. Avoid half-formed furniture, broken objects, floating items, merged objects, warped shapes, duplicate items, and visual artifacts. Color combination for movable furniture textiles and decor only: sage green, warm white, and woven tan textiles."""
IMAGE_URL = "https://magicstore.styldod.com/otodom-image-eval/datasets/batch1/1.webp"
MODEL = "gemini-3.1-flash-image"     # image-capable Gemini model
THINKING_LEVEL = "HIGH"           # MINIMAL / HIGH
SAVE_OUTPUT_TO = "gemini_output"     # base name for any returned image(s)
# -----------------------------------------------------------------------------

_SSL = ssl.create_default_context(cafile=certifi.where())


def fetch_image(url: str) -> tuple[bytes, str]:
    """Download image bytes from a URL (TLS verified via certifi)."""
    with urllib.request.urlopen(url, timeout=30, context=_SSL) as resp:  # noqa: S310
        data = resp.read()
        mime = resp.headers.get("Content-Type")
    if not mime or "image" not in mime:
        mime = mimetypes.guess_type(url)[0] or "image/jpeg"
    return data, mime


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else IMAGE_URL
    image_bytes, mime = fetch_image(url)
    print(f"Input image: {url}  ({mime}, {len(image_bytes)} bytes)")
    print(f"Model: {MODEL}  thinking={THINKING_LEVEL}\n")

    client = genai.Client()  # picks up GEMINI_API_KEY from the environment

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                types.Part.from_text(text=PROMPT),
            ],
        )
    ]

    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level=THINKING_LEVEL),
        image_config=types.ImageConfig(image_size="1K"),
        response_modalities=["IMAGE"],
    )

    response = client.models.generate_content(model=MODEL, contents=contents, config=config)

    # ---- Whole response -----------------------------------------------------
    print("=" * 70)
    print("FULL RESPONSE")
    print("=" * 70)
    print(response)

    # ---- Token usage --------------------------------------------------------
    print("\n" + "=" * 70)
    print("TOKEN USAGE (usage_metadata)")
    print("=" * 70)
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        print("(no usage_metadata on response)")
    else:
        print(usage)
        for field in (
            "prompt_token_count",
            "candidates_token_count",
            "thoughts_token_count",
            "cached_content_token_count",
            "total_token_count",
        ):
            print(f"  {field}: {getattr(usage, field, None)}")

    # ---- Parts breakdown + save any returned image(s) -----------------------
    print("\n" + "=" * 70)
    print("PARTS")
    print("=" * 70)
    idx = 0
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                ext = mimetypes.guess_extension(inline.mime_type or "image/png") or ".png"
                out = f"{SAVE_OUTPUT_TO}_{idx}{ext}"
                Path(out).write_bytes(inline.data)
                print(f"  [image] {inline.mime_type} -> saved {out}")
                idx += 1
            elif getattr(part, "text", None):
                thought = " (thought)" if getattr(part, "thought", False) else ""
                print(f"  [text{thought}] {part.text}")


if __name__ == "__main__":
    main()
