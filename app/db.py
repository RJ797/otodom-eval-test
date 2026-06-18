"""Shared MongoDB access (pymongo only — Vercel-safe).

A single cached client is reused across serverless invocations. This module
imports nothing heavy (no boto3 / SDKs) so it is safe to bundle on Vercel.
"""

from __future__ import annotations

from typing import Optional

import certifi
from pymongo import MongoClient
from pymongo.database import Database

from app import config

_client: Optional[MongoClient] = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        if not config.has_mongo():
            raise RuntimeError("MONGODB_URI is not set in the environment.")
        # Reasonable serverless-friendly timeouts. `tlsCAFile=certifi.where()`
        # fixes "CERTIFICATE_VERIFY_FAILED" on environments (e.g. macOS Python)
        # that lack a system CA bundle when connecting to Atlas over TLS.
        _client = MongoClient(
            config.MONGODB_URI,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
            tlsCAFile=certifi.where(),
            tz_aware=True,
        )
    return _client


def get_db() -> Database:
    return get_client()[config.MONGODB_DB]
