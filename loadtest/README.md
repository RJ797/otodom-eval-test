# Load testing (placeholder — not built yet)

This folder is intentionally a stub. The app is structured so load testing can be
added later **without touching the request logic**.

## The reusable seam

All Gemini calls live in [`app/gemini_client.py`](../app/gemini_client.py):

- `generate_text(prompt, model, images=..., thinking=..., thinking_budget=...)`
- `generate_image(prompt, model, images=...)`

Both return a `GenResult` with `ok`, `latency_ms`, `usage`, `text`, `images`, and
`error` — everything a load test needs to assert on.

## When you're ready (suggested: Locust)

```bash
pip install locust
```

Then create `loadtest/locustfile.py` that imports the same client, e.g.:

```python
from locust import User, task, between
from app import gemini_client

class GeminiUser(User):
    wait_time = between(1, 3)

    @task
    def text(self):
        gemini_client.generate_text("ping", model="gemini-3.1-flash-lite")
```

You can drive it either directly against the SDK (via `gemini_client`) or against
the running FastAPI endpoints (`/api/generate`, `/api/image`) with `HttpUser`.

Nothing here is implemented yet — this is just the documented extension point.
