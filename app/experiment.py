"""Orchestration: run a dataset through the model variants and store results.

Resumable: variants already completed (status == ok) are skipped on re-run.
Concurrency is bounded by config.RUN_CONCURRENCY using a thread pool.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from app import config, models_registry
from app.storage import mongo_store, s3_store


def run(
    run_id: str,
    name: str,
    dataset_id: str,
    variants: Optional[list[str]] = None,
    *,
    force: bool = False,
) -> dict:
    """Execute a full run over a registered dataset. Returns a summary dict.

    All (image, variant) calls are submitted to one thread pool so work runs
    concurrently across images and models, bounded by config.RUN_CONCURRENCY.
    Input bytes (needed only by byte-based models like Gemini) are downloaded
    once per image and cached; URL-based models (Flux) use a presigned S3 URL.
    """
    variants = variants or config.DEFAULT_VARIANTS
    items = mongo_store.list_dataset_items(dataset_id)
    if not items:
        raise RuntimeError(f"No dataset_items found for dataset '{dataset_id}'. Upload it first.")

    s3_prefix = f"{config.S3_ROOT_PREFIX}/runs/{run_id}"
    mongo_store.create_run(run_id, name, dataset_id, variants, s3_prefix, total=len(items))
    for item in items:
        mongo_store.ensure_result(run_id, dataset_id, item)

    # Lazy, thread-safe per-image input-byte cache (only downloaded if a
    # byte-based variant actually runs for that image).
    _bytes_cache: dict[int, bytes] = {}
    _lock = threading.Lock()

    def get_input_bytes(item: dict) -> bytes:
        iid = item["image_id"]
        with _lock:
            if iid in _bytes_cache:
                return _bytes_cache[iid]
        data = s3_store.get_bytes(item["input_image"]["s3_key"])
        with _lock:
            _bytes_cache[iid] = data
        return data

    def task(item: dict, variant: str) -> dict:
        image_id = item["image_id"]
        if not force and mongo_store.variant_done(run_id, image_id, variant):
            return {"image_id": image_id, "variant": variant, "status": "skipped"}

        provider = config.VARIANTS.get(variant, {}).get("provider")
        image_bytes = get_input_bytes(item) if provider == "gemini" else None
        input_url = (
            s3_store.presigned_url(item["input_image"]["s3_key"]) if provider != "gemini" else None
        )

        out = models_registry.run_variant(
            key=variant,
            prompt=item["prompt"],
            image_bytes=image_bytes,
            mime=item["input_image"]["mime"],
            input_image_url=input_url,
        )

        raw = out.pop("image_bytes", None)
        image_output = None
        if out.get("status") == "ok" and raw:
            ext = "png" if out.get("mime", "image/png").endswith("png") else "jpg"
            key = s3_store.run_output_key(run_id, image_id, variant, ext)
            image_output = s3_store.upload_bytes(key, raw, out.get("mime", "image/png"))
        out["image_output"] = image_output
        mongo_store.set_output(run_id, image_id, variant, out)
        return {
            "image_id": image_id,
            "variant": variant,
            "status": out.get("status", "error"),
            "time_ms": out.get("time_taken_ms"),
            "cost": out.get("cost_usd"),
            "error": out.get("error"),
        }

    started = time.perf_counter()
    per_image: dict[int, dict[str, str]] = defaultdict(dict)
    n_variants = len(variants)
    total_tasks = len(items) * n_variants
    done_tasks = 0
    completed = 0
    failed = 0

    print(f"Starting: {len(items)} images x {n_variants} variants = {total_tasks} calls "
          f"(concurrency={config.RUN_CONCURRENCY})", flush=True)

    with ThreadPoolExecutor(max_workers=config.RUN_CONCURRENCY) as pool:
        futures = [pool.submit(task, item, v) for item in items for v in variants]
        for fut in as_completed(futures):
            r = fut.result()
            done_tasks += 1
            image_id = r["image_id"]

            mark = {"ok": "✓", "skipped": "•"}.get(r["status"], "✗")
            extra = ""
            if r["status"] == "ok":
                t = f"{r['time_ms']}ms" if r.get("time_ms") is not None else ""
                c = f" ${r['cost']}" if r.get("cost") is not None else ""
                extra = f" {t}{c}"
            elif r["status"] == "error":
                extra = f" {r.get('error') or ''}"
            elapsed = int(time.perf_counter() - started)
            print(f"[{done_tasks:>4}/{total_tasks}] {mark} img {image_id} {r['variant']}{extra} "
                  f"(t+{elapsed}s)", flush=True)

            per_image[image_id][r["variant"]] = r["status"]
            # When every variant for an image has finished, tally + log progress.
            if len(per_image[image_id]) == n_variants:
                if any(s == "error" for s in per_image[image_id].values()):
                    failed += 1
                else:
                    completed += 1
                mongo_store.update_run_counts(run_id, completed, failed, len(items))
                images_done = completed + failed
                if images_done % 5 == 0 or images_done == len(items):
                    pct = round(images_done / len(items) * 100)
                    rate = images_done / max(1, time.perf_counter() - started)
                    eta = int((len(items) - images_done) / rate) if rate else 0
                    print(f"  -- progress: {images_done}/{len(items)} images ({pct}%), "
                          f"{failed} failed, ETA ~{eta}s --", flush=True)

    mongo_store.set_run_status(run_id, "done")
    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "total": len(items),
        "completed": completed,
        "failed": failed,
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
