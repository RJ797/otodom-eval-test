# Image Model Evaluation Playground

Compare image-generation models on the same (image, prompt) inputs:

- **Local runner** generates outputs from 3 variants — `gemini-3.1-flash-image`
  (MINIMAL thinking), `gemini-3.1-flash-image` (HIGH thinking), and
  `flux-2-klein-9b` (Replicate) — uploads images to **S3** (served via **CDN**),
  and writes structured results (latency, token usage, cost) to **MongoDB**.
- **Scoring web app** (hosted on **Vercel**) lets human testers blind-score each
  output 1–10; scores are written back to MongoDB.

See [`PLAN.md`](PLAN.md) for the full design. Architecture details below.

> Secrets are read from the environment only. `.env` is gitignored and never read,
> logged, or returned by any endpoint.

## Two separated concepts

- **Dataset** (uploaded once, reusable): `scripts/upload_dataset.py` uploads input
  images to S3 and stores prompts in Mongo (`datasets`, `dataset_items`).
- **Run** (per execution): `scripts/run_experiment.py` generates outputs for a
  dataset and writes `runs` + `results`. Run the same dataset many times.

## Layout

```
api/index.py            # Vercel entrypoint (exposes scoring FastAPI app)
public/                 # scoring UI (served by Vercel CDN)
vercel.json / .vercelignore
requirements.txt        # LEAN — Vercel scoring app (fastapi + pymongo)
requirements-runner.txt # FULL — local runner + playground

app/
  config.py             # all env + model variants + pricing
  db.py                 # shared pymongo client (lean)
  scoring/              # scoring app: app.py, store.py, blind.py
  gemini_client.py replicate_client.py models_registry.py pricing.py
  dataset.py experiment.py
  storage/s3_store.py storage/mongo_store.py
  main.py               # ad-hoc single-prompt playground (local only)
scripts/upload_dataset.py  scripts/run_experiment.py
```

## Setup (local runner)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-runner.txt
cp .env.example .env   # then fill in the values
```

Required `.env` for the runner: `GEMINI_API_KEY`, `REPLICATE_API_TOKEN`, AWS creds
+ `S3_BUCKET` + `S3_ROOT_PREFIX` + `CDN_BASE_URL`, `MONGODB_URI` + `MONGODB_DB`, and
`FLUX_COST_PER_IMAGE`. Gemini cost is read from the API response; the Flux model
`black-forest-labs/flux-2-klein-9b` is fixed in code.

### 1. Register a dataset (once)

Folder format — paired files keyed by numeric id:

```
data/batch1/
  1_img.webp   1_prompt.txt
  2_img.jpg    2_prompt.txt
```

```bash
python -m scripts.upload_dataset --folder data/batch1 --dataset-id batch1 --name "first dataset"
```

### 2. Run an evaluation (repeatable)

```bash
python -m scripts.run_experiment --dataset batch1 --name "first eval"
# optional: --run <id> --variants gemini_min gemini_high flux --force
```

Runs are resumable: completed variants are skipped unless `--force`.

## Scoring app (Vercel)

The scoring app is standalone and needs only Mongo.

**Deploy:**
1. Push this repo to GitHub and import it into Vercel (Python is auto-detected from
   `requirements.txt`; `api/index.py` exposes the `app`).
2. Set Vercel env vars: `MONGODB_URI`, `MONGODB_DB`.
3. In MongoDB Atlas, allowlist `0.0.0.0/0` (Vercel IPs are dynamic).
4. Deploy. The UI is served at `/`, the API at `/api/*`.

**Run locally:**
```bash
pip install -r requirements.txt
uvicorn app.scoring.app:app --reload --port 8033
# open http://127.0.0.1:8033
```

**Scoring flow:** enter your name, pick a run, score each output 1–10 (outputs are
shown blind in randomized A/B/C order; toggle "Reveal model labels" to unblind),
optionally pick a best, then Save & next. The Summary button shows per-model avg
score, win-rate, latency (avg/p95), and cost.

## Ad-hoc playground (optional, local)

The original single-prompt playground still exists:
```bash
uvicorn app.main:app --reload   # http://127.0.0.1:8000
```

## Load testing (future)

The runner already exercises all models through `app/models_registry.py`. A Locust
runner under `loadtest/` can import the same adapters. Not built yet.
```
