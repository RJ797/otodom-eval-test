"""Register a dataset once: upload input images to S3 and store prompts in Mongo.

Usage:
    python -m scripts.upload_dataset --folder data/batch1 --dataset-id batch1 \
        --name "first dataset"

Re-running is safe (idempotent upserts). Reuse the dataset id across many runs.
"""

from __future__ import annotations

import argparse

from app import config
from app.dataset import discover
from app.storage import mongo_store, s3_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload + register a dataset.")
    parser.add_argument("--folder", required=True, help="Folder with {id}_img.* / {id}_prompt.txt")
    parser.add_argument("--dataset-id", required=True, help="Stable dataset id (e.g. batch1)")
    parser.add_argument("--name", default="", help="Human-friendly dataset name")
    args = parser.parse_args()

    if not config.has_s3():
        raise SystemExit("S3_BUCKET and CDN_BASE_URL must be set in .env")
    if not config.has_mongo():
        raise SystemExit("MONGODB_URI must be set in .env")

    pairs, warnings = discover(args.folder)
    for w in warnings:
        print(f"  WARN: {w}")
    if not pairs:
        raise SystemExit("No valid {id}_img/{id}_prompt pairs found.")

    print(f"Found {len(pairs)} pairs. Uploading inputs to S3...")
    items = []
    for p in pairs:
        key = s3_store.dataset_input_key(args.dataset_id, p.image_id, p.ext)
        stored = s3_store.upload_bytes(key, p.read_image(), p.mime)
        items.append(
            {"image_id": p.image_id, "prompt": p.read_prompt(), "input_image": stored}
        )
        print(f"  [{p.image_id}] -> {stored['cdn_url']}")

    s3_prefix = f"{config.S3_ROOT_PREFIX}/datasets/{args.dataset_id}"
    mongo_store.upsert_dataset(args.dataset_id, args.name or args.dataset_id, len(items), s3_prefix)
    n = mongo_store.upsert_dataset_items(args.dataset_id, items)
    print(f"Done. Dataset '{args.dataset_id}' registered with {n} items.")


if __name__ == "__main__":
    main()
