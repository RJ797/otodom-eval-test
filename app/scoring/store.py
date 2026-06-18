"""Scoring-app data access (pymongo only — Vercel-safe).

Reads runs/results and writes scores back. No S3 or model SDK imports.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Optional

from app import config
from app.db import get_db
from app.scoring import blind


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _results():
    return get_db()[config.COLL_RESULTS]


def _runs():
    return get_db()[config.COLL_RUNS]


# --- Reads -------------------------------------------------------------------

def list_runs() -> list[dict]:
    runs = list(_runs().find().sort("created_at", -1))
    for r in runs:
        r["id"] = r.pop("_id")
        created = r.get("created_at")
        r["created_at"] = created.isoformat() if hasattr(created, "isoformat") else created
    return runs


def _public_outputs(doc: dict, run_id: str, image_id: int) -> list[dict]:
    """Outputs in blind order; image bytes never stored, only CDN urls."""
    outputs = doc.get("outputs", {})
    variants = list(outputs.keys()) or doc.get("variants", [])
    order = blind.blind_order(run_id, image_id, variants)
    items = []
    for entry in order:
        v = entry["variant"]
        o = outputs.get(v, {})
        items.append(
            {
                "label": entry["label"],
                "variant": v,  # UI hides this until "reveal labels" toggle
                "model": o.get("model"),
                "thinking_level": o.get("thinking_level"),
                "status": o.get("status"),
                "image_url": (o.get("image_output") or {}).get("cdn_url"),
                "time_taken_ms": o.get("time_taken_ms"),
                "token_usage": o.get("token_usage"),
                "cost_usd": o.get("cost_usd"),
                "error": o.get("error"),
            }
        )
    return items


def _scored_by(doc: dict, scorer: str) -> bool:
    scores = doc.get("scores", {})
    variants = list(doc.get("outputs", {}).keys())
    if not variants:
        return False
    for v in variants:
        if not any(s.get("scorer") == scorer for s in scores.get(v, [])):
            return False
    return True


def list_results(run_id: str, scorer: Optional[str] = None) -> list[dict]:
    docs = list(_results().find({"run_id": run_id}).sort("image_id", 1))
    out = []
    for d in docs:
        out.append(
            {
                "image_id": d["image_id"],
                "prompt": d.get("prompt"),
                "input_url": (d.get("input_image") or {}).get("cdn_url"),
                "scoring_status": d.get("scoring_status"),
                "scored_by_me": _scored_by(d, scorer) if scorer else False,
            }
        )
    return out


def get_result(run_id: str, image_id: int, scorer: Optional[str] = None) -> Optional[dict]:
    d = _results().find_one({"_id": f"{run_id}:{image_id}"})
    if not d:
        return None
    my_scores = {}
    if scorer:
        for v, arr in (d.get("scores") or {}).items():
            mine = next((s for s in arr if s.get("scorer") == scorer), None)
            if mine:
                my_scores[v] = {"value": mine.get("value"), "comment": mine.get("comment")}
    my_best = None
    if scorer:
        my_best = next(
            (b["variant"] for b in d.get("best_picks", []) if b.get("scorer") == scorer), None
        )
    return {
        "run_id": run_id,
        "image_id": image_id,
        "prompt": d.get("prompt"),
        "input_url": (d.get("input_image") or {}).get("cdn_url"),
        "outputs": _public_outputs(d, run_id, image_id),
        "my_scores": my_scores,
        "my_best_pick": my_best,
        "score_agg": d.get("score_agg", {}),
    }


# --- Writes ------------------------------------------------------------------

def _recompute_agg(scores: dict[str, list]) -> dict[str, dict]:
    agg: dict[str, dict] = {}
    for variant, arr in scores.items():
        vals = [s["value"] for s in arr if isinstance(s.get("value"), (int, float))]
        if vals:
            agg[variant] = {
                "avg": round(sum(vals) / len(vals), 2),
                "n": len(vals),
                "min": min(vals),
                "max": max(vals),
            }
    return agg


def save_score(
    run_id: str,
    image_id: int,
    scorer: str,
    scores: dict[str, dict],
    best_pick: Optional[str] = None,
) -> dict:
    """Upsert one scorer's per-variant scores (and optional best pick)."""
    doc = _results().find_one({"_id": f"{run_id}:{image_id}"})
    if not doc:
        raise KeyError("result not found")

    all_scores: dict[str, list] = doc.get("scores", {}) or {}
    variants = list(doc.get("outputs", {}).keys())

    for variant, payload in scores.items():
        if variant not in variants:
            continue
        value = payload.get("value")
        if value is None:
            continue
        value = max(config.SCORE_MIN, min(config.SCORE_MAX, int(value)))
        arr = [s for s in all_scores.get(variant, []) if s.get("scorer") != scorer]
        arr.append(
            {
                "scorer": scorer,
                "value": value,
                "comment": (payload.get("comment") or "").strip(),
                "scored_at": _now_iso(),
            }
        )
        all_scores[variant] = arr

    best_picks = [b for b in doc.get("best_picks", []) if b.get("scorer") != scorer]
    if best_pick and best_pick in variants:
        best_picks.append({"scorer": scorer, "variant": best_pick})

    agg = _recompute_agg(all_scores)
    scored_variants = sum(1 for v in variants if all_scores.get(v))
    if scored_variants == 0:
        status = "pending"
    elif scored_variants < len(variants):
        status = "partial"
    else:
        status = "done"

    _results().update_one(
        {"_id": f"{run_id}:{image_id}"},
        {
            "$set": {
                "scores": all_scores,
                "score_agg": agg,
                "best_picks": best_picks,
                "scoring_status": status,
            }
        },
    )
    return {"ok": True, "scoring_status": status, "score_agg": agg}


# --- Summary -----------------------------------------------------------------

def run_summary(run_id: str) -> dict:
    docs = list(_results().find({"run_id": run_id}))
    per_variant: dict[str, dict] = {}
    wins: dict[str, int] = {}

    for d in docs:
        outputs = d.get("outputs", {})
        agg = d.get("score_agg", {})
        for v, o in outputs.items():
            slot = per_variant.setdefault(
                v, {"scores": [], "latencies": [], "costs": [], "n_ok": 0, "n_err": 0}
            )
            if o.get("status") == "ok":
                slot["n_ok"] += 1
            else:
                slot["n_err"] += 1
            if o.get("time_taken_ms") is not None:
                slot["latencies"].append(o["time_taken_ms"])
            if o.get("cost_usd") is not None:
                slot["costs"].append(o["cost_usd"])
            if v in agg and agg[v].get("avg") is not None:
                slot["scores"].append(agg[v]["avg"])
        # win = highest avg score for this image
        scored = {v: agg[v]["avg"] for v in agg if agg[v].get("avg") is not None}
        if scored:
            best = max(scored, key=scored.get)
            wins[best] = wins.get(best, 0) + 1

    summary = {}
    for v, slot in per_variant.items():
        scores = slot["scores"]
        summary[v] = {
            "avg_score": round(statistics.fmean(scores), 2) if scores else None,
            "score_stdev": round(statistics.pstdev(scores), 2) if len(scores) > 1 else 0,
            "n_scored": len(scores),
            "avg_latency_ms": int(statistics.fmean(slot["latencies"])) if slot["latencies"] else None,
            "p95_latency_ms": _p95(slot["latencies"]),
            "avg_cost_usd": round(statistics.fmean(slot["costs"]), 6) if slot["costs"] else None,
            "total_cost_usd": round(sum(slot["costs"]), 4) if slot["costs"] else 0,
            "n_ok": slot["n_ok"],
            "n_err": slot["n_err"],
            "wins": wins.get(v, 0),
        }
    return {"run_id": run_id, "n_images": len(docs), "variants": summary}


def _p95(values: list) -> Optional[int]:
    if not values:
        return None
    s = sorted(values)
    idx = max(0, int(round(0.95 * (len(s) - 1))))
    return int(s[idx])
