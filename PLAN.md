# Image Model Evaluation Playground — Plan

A batch evaluation harness (runs locally) + a human scoring web app (hosted on
Vercel) for comparing image-generation models on the same (image, prompt) inputs.
Outputs and original inputs are stored in S3 (served via CDN); all metadata and
scores live in MongoDB. Built to stay extensible for load testing.

> Security: the app reads all secrets from the environment only. `.env` is never
> read, logged, echoed, or returned by any endpoint.

---

## Locked decisions

| Decision | Choice |
| --- | --- |
| Scoring scale | **1–10** (integer) per output |
| Scoring mode | **Blind + randomized** order (A/B/C), with a **toggle to reveal model labels** |
| Scorers | **Multiple scorers** per output (enables averaging + inter-rater agreement) |
| Mongo granularity | **One document per image** (nested per-model outputs) |
| Mongo driver | **pymongo** |
| Scoring app host | **Vercel** (serverless Python functions + static UI), standalone |
| Input vs results | **Separated**: a dataset is uploaded once and reused across many runs |
| Original images | **Uploaded to S3** so the Vercel app can show the reference via CDN |

---

## Two separated concepts (key design)

The input dataset and the run results are independent so one dataset can be run
many times:

- **Dataset** — registered once via `scripts/upload_dataset.py`. Uploads the
  original images to S3 and stores prompts + input CDN URLs in Mongo.
- **Run** — created each time via `scripts/run_experiment.py --dataset <id>`.
  Generates model outputs, uploads them to a run-specific S3 prefix, and writes
  results referencing the dataset. Re-runnable (new run id each time).

---

## Models under test (3 variants)

| Variant key | Provider | Model | Notes |
| --- | --- | --- | --- |
| `gemini_min` | Gemini | `gemini-3.1-flash-image` | thinking level **MINIMAL** |
| `gemini_high` | Gemini | `gemini-3.1-flash-image` | thinking level **HIGH** |
| `flux` | Replicate | `flux-2-klein-9b` | constant cost per image |

---

## Inputs (dataset folder)

Paired files keyed by numeric id:

```
data/<dataset>/
  1_img.webp      1_prompt.txt
  2_img.jpg       2_prompt.txt
  3_img.png       3_prompt.txt
  ...
```

`dataset.py` discovers and pairs files by id (any image extension), reads the
prompt text, and warns on orphans / missing pairs.

---

## Architecture

```
                      LOCAL                                  VERCEL (serverless)
  ┌─────────────────────────────────────────┐        ┌──────────────────────────┐
  │ upload_dataset.py ─► S3 (datasets/) ─► CDN│        │ Scoring app (FastAPI)    │
  │        │                                  │        │  /api/* functions        │
  │        ▼                                  │        │ Static UI (public/)      │
  │   dataset_items ───────────────┐          │        └───────────┬──────────────┘
  │                                ▼          │                    │ read/write
  │ run_experiment.py ─► 3 adapters ─► S3      │   MongoDB Atlas ◄──┘ (pymongo)
  │   (gemini_min/high, flux) (runs/) ─► CDN   │        ▲
  │        └───────────► results ──────────────┼────────┘
  └─────────────────────────────────────────┘
```

- **Runner** (local): heavy deps (gemini, replicate, boto3). Hits models, uploads
  to S3, writes Mongo. Concurrency-capped, retryable, resumable.
- **Scoring app** (Vercel): lean deps (fastapi + pymongo only). Reads results from
  Mongo, shows images via CDN, writes scores back to Mongo. No S3/model deps.

---

## Project structure

```
api/
  index.py                 # Vercel entrypoint — exposes the scoring FastAPI `app`
public/
  index.html               # scoring UI (served by Vercel CDN at /)
  scoring.js
  scoring.css
vercel.json                # routing + function config
.vercelignore              # keep runner-only files out of the Vercel bundle
requirements.txt           # LEAN: fastapi, pymongo[srv], python-dotenv  (Vercel)
requirements-runner.txt    # FULL local set: google-genai, replicate, boto3, ...

app/
  config.py                # all env reads + model variant defs + pricing
  db.py                    # shared pymongo client/db (lean: pymongo only)
  scoring/
    __init__.py
    app.py                 # FastAPI scoring app (routes under /api/...)
    store.py               # pymongo reads/writes for runs/results/scores
    blind.py               # deterministic A/B/C shuffle per image
  gemini_client.py         # existing (reused for both gemini variants)   [runner]
  replicate_client.py      # flux-2-klein-9b adapter                       [runner]
  models_registry.py       # 3 variants behind one interface              [runner]
  pricing.py               # cost calc (gemini per-token, flux constant)   [runner]
  dataset.py               # discover & pair {id}_img / {id}_prompt        [runner]
  experiment.py            # orchestration (resumable)                     [runner]
  storage/
    __init__.py
    s3_store.py            # upload bytes -> {s3_key, cdn_url} (boto3)      [runner]
    mongo_store.py         # dataset/run/result writes (pymongo)           [runner]
  main.py                  # existing ad-hoc playground (local only)
scripts/
  upload_dataset.py        # register a dataset (upload inputs + prompts)
  run_experiment.py        # run a dataset through the 3 models
data/                      # YOUR input folders (gitignored)
loadtest/                  # later
```

The scoring app deliberately imports **only** `app.scoring.*`, `app.db`, and
`app.config` (no boto3 / gemini / replicate), so the Vercel bundle stays small
and needs only `MONGODB_URI` / `MONGODB_DB`.

---

## S3 + CDN layout (separated)

```
# inputs — uploaded once per dataset, reused across runs
s3://<bucket>/<root_prefix>/datasets/<dataset_id>/<image_id>.<ext>

# outputs — per run
s3://<bucket>/<root_prefix>/runs/<run_id>/<image_id>/gemini_min.png
s3://<bucket>/<root_prefix>/runs/<run_id>/<image_id>/gemini_high.png
s3://<bucket>/<root_prefix>/runs/<run_id>/<image_id>/flux.png
```

`cdn_url = <CDN_BASE_URL>/<same key>`.

---

## MongoDB schema (4 collections)

### `datasets` (one per dataset)

```json
{
  "_id": "batch1",
  "name": "first dataset",
  "count": 50,
  "s3_prefix": "<root_prefix>/datasets/batch1",
  "created_at": "..."
}
```

### `dataset_items` (one per input image; reusable across runs)

```json
{
  "_id": "batch1:1",
  "dataset_id": "batch1",
  "image_id": 1,
  "prompt": "text from 1_prompt.txt",
  "input_image": { "s3_key": "...", "cdn_url": "...", "mime": "image/webp" }
}
```

### `runs` (one per execution)

```json
{
  "_id": "2026-06-18_run1",
  "name": "first eval",
  "dataset_id": "batch1",
  "models": ["gemini_min", "gemini_high", "flux"],
  "s3_prefix": "<root_prefix>/runs/2026-06-18_run1",
  "status": "running | done | failed",
  "counts": { "total": 50, "completed": 50, "failed": 0 },
  "created_at": "..."
}
```

### `results` (one document per image per run)

Denormalizes `prompt` + `input_image` from the dataset (immutable) so the Vercel
app reads a single collection.

```json
{
  "_id": "2026-06-18_run1:1",
  "run_id": "2026-06-18_run1",
  "dataset_id": "batch1",
  "image_id": 1,
  "prompt": "text from 1_prompt.txt",
  "input_image": { "s3_key": "...", "cdn_url": "...", "mime": "image/webp" },
  "outputs": {
    "gemini_min": {
      "model": "gemini-3.1-flash-image", "thinking_level": "MINIMAL",
      "status": "ok | error",
      "image_output": { "s3_key": "...", "cdn_url": "...", "mime": "image/png" },
      "time_taken_ms": 4200,
      "token_usage": { "prompt": 290, "candidates": 1290, "total": 1580 },
      "cost_usd": 0.0039, "error": null
    },
    "gemini_high": { "...": "..." },
    "flux": { "model": "flux-2-klein-9b", "token_usage": null, "cost_usd": 0.03, "...": "..." }
  },
  "scores": {
    "gemini_min":  [ { "scorer": "alice", "value": 7, "comment": "...", "scored_at": "..." } ],
    "gemini_high": [ { "scorer": "alice", "value": 9, "comment": "...", "scored_at": "..." } ],
    "flux":        [ { "scorer": "bob",   "value": 6, "comment": "...", "scored_at": "..." } ]
  },
  "score_agg": {
    "gemini_min":  { "avg": 7.0, "n": 1, "min": 7, "max": 7 },
    "gemini_high": { "avg": 9.0, "n": 1, "min": 9, "max": 9 },
    "flux":        { "avg": 6.0, "n": 1, "min": 6, "max": 6 }
  },
  "best_picks": [ { "scorer": "alice", "variant": "gemini_high" } ],
  "scoring_status": "pending | partial | done"
}
```

> Multiple scorers → `scores` is an **array per model variant** (one entry per
> scorer, upserted by `scorer`). `score_agg` holds rolling aggregates updated on
> each save. `best_picks` is optional forced-choice (one per scorer).

---

## Run pipeline (per image)

1. `run_experiment.py` loads `dataset_items` for the dataset.
2. `experiment.py` runs the 3 adapters (concurrency cap + retry/backoff), capturing
   `time_taken_ms`, `token_usage` (Gemini only), and output bytes.
3. Upload each output to the run's S3 prefix → `{s3_key, cdn_url}`.
4. Compute `cost_usd` via `pricing.py`.
5. Upsert the `results` doc — **idempotent / resumable** (skip variants already done;
   a single variant can be re-run without redoing others).
6. Human scoring happens later in the Vercel app, patching `scores`/`score_agg`.

---

## Scoring web app (Vercel)

- **Scorer identity:** tester enters a `scorer` name (kept in the browser); progress
  is per-scorer.
- **Run picker** → images with per-scorer progress (scored / total).
- Per image: **input image + prompt** and the **3 outputs**, each with a **1–10**
  score input + comment, and metadata (latency, tokens, cost).
- **Blind (default):** outputs shown in **randomized A/B/C** order, labels hidden;
  order is seeded by image id (stable per image).
- **Toggle to reveal model labels** at any time.
- Optional **"pick best"** forced choice (per scorer).
- Saving upserts the current scorer's entry; keyboard shortcuts + auto-advance.

### Scoring API (under `/api`, served by `api/index.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | liveness + whether Mongo is configured |
| `GET` | `/api/runs` | list runs + counts |
| `GET` | `/api/runs/{run_id}/results?scorer=<name>` | results (randomized blind order; marks scorer's done items) |
| `GET` | `/api/runs/{run_id}/results/{image_id}` | single result |
| `PATCH` | `/api/runs/{run_id}/results/{image_id}/score` | upsert one scorer's scores / best pick |
| `GET` | `/api/runs/{run_id}/summary` | per-model aggregates (avg score, agreement, latency, cost, win-rate) |

Static UI is served from `public/` by Vercel's CDN (root `/`).

---

## Cost model (`pricing.py`)

- **Gemini:** cost is taken **directly from the Gemini API response** (no rate math).
- **Flux:** constant `FLUX_COST_PER_IMAGE` from env/config.
- Stored per output, aggregated per run.

---

## Configuration / `.env` keys (you provide; never read by me)

| Key | Used by | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | runner | Gemini (already set) |
| `REPLICATE_API_TOKEN` | runner | Replicate / Flux (model `black-forest-labs/flux-2-klein-9b` is fixed in code) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | runner | S3 access |
| `S3_BUCKET` | runner | test bucket |
| `S3_ROOT_PREFIX` | runner | experiment root path inside the bucket |
| `CDN_BASE_URL` | runner | CDN base url mapped to the bucket |
| `MONGODB_URI` | runner + Vercel | Atlas SRV connection string |
| `MONGODB_DB` | runner + Vercel | database name |

Pricing: Gemini cost comes from the API response; set `FLUX_COST_PER_IMAGE` only.

**On Vercel, set only:** `MONGODB_URI`, `MONGODB_DB` (the app reads images via the
CDN URLs already stored in Mongo).

---

## Future scope (useful testing additions)

- **Aggregate dashboard:** avg score, p50/p95 latency, avg cost, win-rate per model.
- **Inter-rater agreement:** Krippendorff's alpha / variance across scorers to flag
  noisy items.
- **Pairwise / ELO ranking** mode alongside absolute scores.
- **Automated metrics:** CLIP / prompt-adherence, SSIM vs reference, NSFW flagging.
- **Load testing:** the runner is already a load generator; add `loadtest/` with
  Locust reusing `models_registry` (concurrency, rate limits, percentiles).
- **Reproducibility:** seed control where supported; store raw API responses.
- **Slicing:** prompt/model versioning, image tags/categories.
- **Export:** results to CSV / JSON.

---

## Build order

1. `config.py` + split requirements + `app/db.py`.
2. `storage/s3_store.py` + `storage/mongo_store.py`.
3. `replicate_client.py` + `models_registry.py` + `pricing.py`.
4. `dataset.py` + `experiment.py` + `scripts/*`.
5. Scoring app (`app/scoring/*`) + `public/*` + `api/index.py` + `vercel.json`.

---

## Your setup checklist

- [ ] Add keys to local `.env` (Replicate + model slug, AWS creds, S3 bucket,
      S3 root prefix, CDN base url, Mongo SRV + db).
- [ ] **S3:** create test bucket; grant `PutObject`; allow read via CDN; CORS if needed.
- [ ] **CDN:** point CloudFront (or CDN) at the bucket; provide the CDN base url.
- [ ] **MongoDB Atlas:** cluster + db user + **allowlist `0.0.0.0/0`** (Vercel IPs are
      dynamic); provide SRV URI + db name.
- [ ] **Replicate:** confirm exact `flux-2-klein-9b` slug/version + input field names
      + output format.
- [ ] **Vercel:** create project from this repo; set env vars `MONGODB_URI`,
      `MONGODB_DB`; deploy.
- [ ] Set `FLUX_COST_PER_IMAGE` (Gemini cost is read from the API response).
- [ ] Prepare a dataset folder (`{id}_img.{ext}` / `{id}_prompt.txt`).
```
