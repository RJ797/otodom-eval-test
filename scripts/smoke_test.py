"""Connectivity smoke test — verifies env/keys without burning credits.

By default it checks the cheap stuff (config flags, MongoDB ping, S3 upload +
CDN read-back, and that the Gemini/Replicate clients build). Add --live to also
make ONE real Gemini image call and ONE real Flux call (these cost money).

Usage:
    python -m scripts.smoke_test
    python -m scripts.smoke_test --live
"""

from __future__ import annotations

import argparse
import time

from app import config

OK = "\033[92mPASS\033[0m"
BAD = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"


def line(name: str, status: str, detail: str = "") -> None:
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def check_config() -> None:
    print("\nConfig (booleans only, never the secret values):")
    line("GEMINI_API_KEY set", OK if config.has_api_key() else BAD)
    line("REPLICATE_API_TOKEN set", OK if config.has_replicate_token() else BAD)
    line("MONGODB_URI + DB set", OK if config.has_mongo() else BAD)
    line("S3_BUCKET + CDN_BASE_URL set", OK if config.has_s3() else BAD)
    line("FLUX_COST_PER_IMAGE", OK, str(config.FLUX_COST_PER_IMAGE))
    line("S3_ROOT_PREFIX", OK, config.S3_ROOT_PREFIX)


def check_mongo() -> bool:
    print("\nMongoDB:")
    if not config.has_mongo():
        line("ping", SKIP, "not configured")
        return False
    try:
        from app.db import get_client, get_db

        get_client().admin.command("ping")
        names = get_db().list_collection_names()
        line("ping", OK, f"db '{config.MONGODB_DB}', {len(names)} collections")
        return True
    except Exception as exc:  # noqa: BLE001
        line("ping", BAD, f"{type(exc).__name__}: {exc}")
        return False


def check_s3() -> bool:
    print("\nS3 + CDN:")
    if not config.has_s3():
        line("upload", SKIP, "not configured")
        return False
    try:
        from app.storage import s3_store

        key = f"{config.S3_ROOT_PREFIX}/_smoke/ping-{int(time.time())}.txt"
        payload = b"smoke-test"
        stored = s3_store.upload_bytes(key, payload, "text/plain", cache_control=None)
        line("put_object", OK, stored["s3_key"])
        try:
            from app.http_util import fetch_bytes

            got = fetch_bytes(stored["cdn_url"], timeout=15)
            if got == payload:
                line("CDN read-back", OK, stored["cdn_url"])
            else:
                line("CDN read-back", BAD, "content mismatch")
        except Exception as exc:  # noqa: BLE001
            line("CDN read-back", BAD, f"{type(exc).__name__}: {exc} (check CDN mapping/propagation)")
        return True
    except Exception as exc:  # noqa: BLE001
        line("put_object", BAD, f"{type(exc).__name__}: {exc}")
        return False


def check_clients() -> None:
    print("\nClients build:")
    try:
        from app import gemini_client

        gemini_client.get_client()
        line("Gemini client", OK)
    except Exception as exc:  # noqa: BLE001
        line("Gemini client", BAD, f"{type(exc).__name__}: {exc}")
    try:
        from app import replicate_client

        replicate_client.get_client()
        line("Replicate client", OK)
    except Exception as exc:  # noqa: BLE001
        line("Replicate client", BAD, f"{type(exc).__name__}: {exc}")


def check_live() -> None:
    print("\nLive model calls (this costs money):")
    from app import models_registry

    prompt = "A small red cube on a white background."
    g = models_registry.run_variant("gemini_min", prompt=prompt)
    line(
        "gemini_min",
        OK if g.get("status") == "ok" else BAD,
        f"{g.get('time_taken_ms')}ms cost={g.get('cost_usd')} err={g.get('error')}",
    )
    f = models_registry.run_variant("flux", prompt=prompt)
    line(
        "flux",
        OK if f.get("status") == "ok" else BAD,
        f"{f.get('time_taken_ms')}ms cost={f.get('cost_usd')} err={f.get('error')}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Connectivity smoke test")
    parser.add_argument("--live", action="store_true", help="Also make real model calls (costs money)")
    args = parser.parse_args()

    print("=" * 60)
    print("SMOKE TEST")
    print("=" * 60)
    check_config()
    check_mongo()
    check_s3()
    check_clients()
    if args.live:
        check_live()
    print("\nDone.")


if __name__ == "__main__":
    main()
