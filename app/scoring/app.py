"""Scoring web app (FastAPI) — deployed standalone on Vercel.

Imports only pymongo-backed modules (no boto3 / model SDKs) so the Vercel bundle
stays small and needs only MONGODB_URI / MONGODB_DB.

Static UI lives in /public and is served by Vercel's CDN in production. For local
dev we also mount it so `uvicorn app.scoring.app:app` serves the whole thing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import config
from app.scoring import store

app = FastAPI(title="Image Eval — Scoring")

# Static UI lives inside the package so it is bundled into the Vercel function
# (the FastAPI preset's catch-all function serves all routes, including "/").
STATIC_DIR = Path(__file__).resolve().parent / "static"


class ScoreItem(BaseModel):
    value: Optional[int] = None
    comment: Optional[str] = None


class ScorePayload(BaseModel):
    scorer: str
    scores: dict[str, ScoreItem]
    best_pick: Optional[str] = None


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "mongo_configured": config.has_mongo(),
        "score_min": config.SCORE_MIN,
        "score_max": config.SCORE_MAX,
    }


@app.get("/api/runs")
def get_runs() -> dict:
    return {"runs": store.list_runs()}


@app.get("/api/runs/{run_id}/results")
def get_results(run_id: str, scorer: Optional[str] = None) -> dict:
    return {"run_id": run_id, "results": store.list_results(run_id, scorer)}


@app.get("/api/runs/{run_id}/results/{image_id}")
def get_result(run_id: str, image_id: int, scorer: Optional[str] = None) -> dict:
    res = store.get_result(run_id, image_id, scorer)
    if not res:
        raise HTTPException(status_code=404, detail="result not found")
    return res


@app.patch("/api/runs/{run_id}/results/{image_id}/score")
def patch_score(run_id: str, image_id: int, payload: ScorePayload) -> JSONResponse:
    if not payload.scorer.strip():
        raise HTTPException(status_code=400, detail="scorer is required")
    scores = {k: v.model_dump() for k, v in payload.scores.items()}
    try:
        result = store.save_score(
            run_id, image_id, payload.scorer.strip(), scores, payload.best_pick
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="result not found")
    return JSONResponse(result)


@app.get("/api/runs/{run_id}/summary")
def get_summary(run_id: str) -> dict:
    return store.run_summary(run_id)


# Serve the static UI from the function (mounted last so /api/* routes win).
if STATIC_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
