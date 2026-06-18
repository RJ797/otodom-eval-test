"""Mongo writes for the runner side: datasets, dataset_items, runs, results.

Uses the shared pymongo connection in app.db. The scoring app has its own
read/score module (app.scoring.store); this module is for the local pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from pymongo import UpdateOne

from app import config
from app.db import get_db


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Datasets ----------------------------------------------------------------

def upsert_dataset(dataset_id: str, name: str, count: int, s3_prefix: str) -> None:
    get_db()[config.COLL_DATASETS].update_one(
        {"_id": dataset_id},
        {
            "$set": {"name": name, "count": count, "s3_prefix": s3_prefix},
            "$setOnInsert": {"created_at": _now()},
        },
        upsert=True,
    )


def upsert_dataset_items(dataset_id: str, items: Iterable[dict]) -> int:
    ops = []
    for it in items:
        _id = f"{dataset_id}:{it['image_id']}"
        ops.append(
            UpdateOne(
                {"_id": _id},
                {
                    "$set": {
                        "dataset_id": dataset_id,
                        "image_id": it["image_id"],
                        "prompt": it["prompt"],
                        "input_image": it["input_image"],
                    }
                },
                upsert=True,
            )
        )
    if not ops:
        return 0
    res = get_db()[config.COLL_DATASET_ITEMS].bulk_write(ops, ordered=False)
    return (res.upserted_count or 0) + (res.modified_count or 0)


def list_dataset_items(dataset_id: str) -> list[dict]:
    cur = get_db()[config.COLL_DATASET_ITEMS].find({"dataset_id": dataset_id})
    return sorted(cur, key=lambda d: d["image_id"])


# --- Runs --------------------------------------------------------------------

def create_run(
    run_id: str, name: str, dataset_id: str, models: list[str], s3_prefix: str, total: int
) -> None:
    get_db()[config.COLL_RUNS].update_one(
        {"_id": run_id},
        {
            "$set": {
                "name": name,
                "dataset_id": dataset_id,
                "models": models,
                "s3_prefix": s3_prefix,
                "status": "running",
            },
            "$setOnInsert": {
                "created_at": _now(),
                "counts": {"total": total, "completed": 0, "failed": 0},
            },
        },
        upsert=True,
    )


def set_run_status(run_id: str, status: str) -> None:
    get_db()[config.COLL_RUNS].update_one({"_id": run_id}, {"$set": {"status": status}})


def update_run_counts(run_id: str, completed: int, failed: int, total: int) -> None:
    get_db()[config.COLL_RUNS].update_one(
        {"_id": run_id},
        {"$set": {"counts": {"total": total, "completed": completed, "failed": failed}}},
    )


# --- Results -----------------------------------------------------------------

def get_result(run_id: str, image_id: int) -> Optional[dict]:
    return get_db()[config.COLL_RESULTS].find_one({"_id": f"{run_id}:{image_id}"})


def ensure_result(run_id: str, dataset_id: str, item: dict) -> None:
    """Create the result doc skeleton (denormalizing prompt + input image)."""
    _id = f"{run_id}:{item['image_id']}"
    get_db()[config.COLL_RESULTS].update_one(
        {"_id": _id},
        {
            "$setOnInsert": {
                "run_id": run_id,
                "dataset_id": dataset_id,
                "image_id": item["image_id"],
                "prompt": item["prompt"],
                "input_image": item["input_image"],
                "outputs": {},
                "scores": {},
                "score_agg": {},
                "best_picks": [],
                "scoring_status": "pending",
            }
        },
        upsert=True,
    )


def set_output(run_id: str, image_id: int, variant: str, output: dict[str, Any]) -> None:
    get_db()[config.COLL_RESULTS].update_one(
        {"_id": f"{run_id}:{image_id}"},
        {"$set": {f"outputs.{variant}": output}},
    )


def variant_done(run_id: str, image_id: int, variant: str) -> bool:
    doc = get_db()[config.COLL_RESULTS].find_one(
        {"_id": f"{run_id}:{image_id}"}, {f"outputs.{variant}.status": 1}
    )
    if not doc:
        return False
    return doc.get("outputs", {}).get(variant, {}).get("status") == "ok"
