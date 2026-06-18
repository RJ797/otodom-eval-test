"""Discover and pair dataset files: {id}_img.{ext} + {id}_prompt.txt."""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

IMG_RE = re.compile(r"^(\d+)_img\.([A-Za-z0-9]+)$")
PROMPT_RE = re.compile(r"^(\d+)_prompt\.txt$")


@dataclass
class Pair:
    image_id: int
    image_path: Path
    prompt_path: Path
    mime: str

    @property
    def ext(self) -> str:
        return self.image_path.suffix.lstrip(".").lower()

    def read_prompt(self) -> str:
        return self.prompt_path.read_text(encoding="utf-8").strip()

    def read_image(self) -> bytes:
        return self.image_path.read_bytes()


def discover(folder: str | Path) -> tuple[list[Pair], list[str]]:
    """Return (pairs sorted by id, warnings about orphans/missing)."""
    root = Path(folder)
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset folder not found: {root}")

    images: dict[int, Path] = {}
    prompts: dict[int, Path] = {}
    for p in root.iterdir():
        if not p.is_file():
            continue
        m_img = IMG_RE.match(p.name)
        if m_img:
            images[int(m_img.group(1))] = p
            continue
        m_prompt = PROMPT_RE.match(p.name)
        if m_prompt:
            prompts[int(m_prompt.group(1))] = p

    warnings: list[str] = []
    pairs: list[Pair] = []
    for image_id in sorted(set(images) | set(prompts)):
        img = images.get(image_id)
        prompt = prompts.get(image_id)
        if img and prompt:
            mime = mimetypes.guess_type(img.name)[0] or "application/octet-stream"
            pairs.append(Pair(image_id=image_id, image_path=img, prompt_path=prompt, mime=mime))
        elif img and not prompt:
            warnings.append(f"image_id {image_id}: image present but missing {image_id}_prompt.txt")
        elif prompt and not img:
            warnings.append(f"image_id {image_id}: prompt present but missing {image_id}_img.*")

    return pairs, warnings
