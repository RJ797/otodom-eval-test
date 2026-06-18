"""Orchestration: run a dataset through the model variants and store results.

Resumable: variants already completed (status == ok) are skipped on re-run.
Concurrency is bounded by config.RUN_CONCURRENCY using a thread pool.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from app import config, models_registry
from app.storage import mongo_store, s3_store


def _run_one_variant(
    run_id: str,
    item: dict,
    variant: str,
    *,
    image_bytes: bytes,
    input_image_url: str,
    force: bool,
) -> tuple[str, str]:
    """Run a single (image, variant); upload + persist. Returns (variant, status)."""
    image_id = item["image_id"]
    if not force and mongo_store.variant_done(run_id, image_id, variant):
        return variant, "skipped"

    out = models_registry.run_variant(
        key=variant,
        prompt=item["prompt"],
        image_bytes=image_bytes,
        mime=item["input_image"]["mime"],
        input_image_url=input_image_url,
    )

    raw = out.pop("image_bytes", None)
    image_output = None
    if out.get("status") == "ok" and raw:
        ext = "png" if out.get("mime", "image/png").endswith("png") else "jpg"
        key = s3_store.run_output_key(run_id, image_id, variant, ext)
        image_output = s3_store.upload_bytes(key, raw, out.get("mime", "image/png"))

    out["image_output"] = image_output
    mongo_store.set_output(run_id, image_id, variant, out)
    return variant, out.get("status", "error")


def run(
    run_id: str,
    name: str,
    dataset_id: str,
    variants: Optional[list[str]] = None,
    *,
    force: bool = False,
) -> dict:
    """Execute a full run over a registered dataset. Returns a summary dict."""
    variants = variants or config.DEFAULT_VARIANTS
    items = mongo_store.list_dataset_items(dataset_id)
    if not items:
        raise RuntimeError(f"No dataset_items found for dataset '{dataset_id}'. Upload it first.")

    s3_prefix = f"{config.S3_ROOT_PREFIX}/runs/{run_id}"
    mongo_store.create_run(run_id, name, dataset_id, variants, s3_prefix, total=len(items))

    completed = 0
    failed = 0
    started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=config.RUN_CONCURRENCY) as pool:
        for item in items:
            mongo_store.ensure_result(run_id, dataset_id, item)
            s3_key = item["input_image"]["s3_key"]
            # Read input bytes straight from S3 (for byte-based models like
            # Gemini) and mint a presigned S3 URL (for URL-based models like
            # Flux/Replicate). Neither path depends on the CDN.
            image_bytes = s3_store.get_bytes(s3_key)
            input_image_url = s3_store.presigned_url(s3_key)

            futures = {
                pool.submit(
                    _run_one_variant,
                    run_id,
                    item,
                    v,
                    image_bytes=image_bytes,
                    input_image_url=input_image_url,
                    force=force,
                ): v
                for v in variants
            }
            item_failed = False
            for fut in as_completed(futures):
                _variant, status = fut.result()
                if status == "error":
                    item_failed = True
            if item_failed:
                failed += 1
            else:
                completed += 1
            mongo_store.update_run_counts(run_id, completed, failed, len(items))

    mongo_store.set_run_status(run_id, "done")
    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "total": len(items),
        "completed": completed,
        "failed": failed,
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
