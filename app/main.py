"""FastAPI app: serves the playground UI and thin API wrappers.

Endpoints are deliberately thin — all real work lives in app.gemini_client so a
future load test can reuse the exact same logic.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, gemini_client

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Gemini API Playground")


@app.get("/api/models")
def list_models() -> dict:
    """Selectable Gemini models + defaults + whether a key is configured.

    Never returns the key itself — only a boolean.
    """
    return {
        "text_models": config.TEXT_MODELS,
        "image_models": config.IMAGE_MODELS,
        "image_thinking_levels": config.IMAGE_THINKING_LEVELS,
        "default_text_model": config.DEFAULT_TEXT_MODEL,
        "default_image_model": config.DEFAULT_IMAGE_MODEL,
        "default_image_thinking_level": config.DEFAULT_IMAGE_THINKING_LEVEL,
        "api_key_configured": config.has_api_key(),
    }


async def _read_image(upload: Optional[UploadFile]) -> Optional[list]:
    if upload is None:
        return None
    data = await upload.read()
    if not data:
        return None
    return [gemini_client.ImageInput(data=data, mime_type=upload.content_type or "image/png")]


@app.post("/api/generate")
async def generate(
    prompt: str = Form(...),
    model: str = Form(config.DEFAULT_TEXT_MODEL),
    thinking: bool = Form(True),
    thinking_budget: Optional[int] = Form(None),
    include_thoughts: bool = Form(True),
    temperature: Optional[float] = Form(None),
    system_instruction: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
) -> JSONResponse:
    images = await _read_image(image)
    result = gemini_client.generate_text(
        prompt=prompt,
        model=model,
        images=images,
        thinking=thinking,
        thinking_budget=thinking_budget,
        include_thoughts=include_thoughts,
        temperature=temperature,
        system_instruction=system_instruction or None,
    )
    return JSONResponse(result.to_dict(), status_code=200 if result.ok else 502)


@app.post("/api/image")
async def image_gen(
    prompt: str = Form(...),
    model: str = Form(config.DEFAULT_IMAGE_MODEL),
    thinking_level: str = Form(config.DEFAULT_IMAGE_THINKING_LEVEL),
    image_size: Optional[str] = Form(None),
    aspect_ratio: Optional[str] = Form(None),
    temperature: Optional[float] = Form(None),
    image: Optional[UploadFile] = File(None),
) -> JSONResponse:
    images = await _read_image(image)
    result = gemini_client.generate_image(
        prompt=prompt,
        model=model,
        images=images,
        thinking_level=thinking_level,
        image_size=image_size or None,
        aspect_ratio=aspect_ratio or None,
        temperature=temperature,
    )
    return JSONResponse(result.to_dict(), status_code=200 if result.ok else 502)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
