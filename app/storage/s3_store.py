"""S3 upload helper (runner-only; uses boto3).

Uploads bytes and returns the stored key plus its public CDN URL. Never used by
the Vercel scoring app.
"""

from __future__ import annotations

from typing import Optional

import boto3

from app import config

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        if not config.S3_BUCKET:
            raise RuntimeError("S3_BUCKET is not set in the environment.")
        _s3 = boto3.client("s3", region_name=config.AWS_REGION)
    return _s3


def cdn_url_for(key: str) -> str:
    return f"{config.CDN_BASE_URL}/{key.lstrip('/')}"


def get_bytes(key: str) -> bytes:
    """Download an object's bytes straight from S3 (no CDN dependency)."""
    resp = _client().get_object(Bucket=config.S3_BUCKET, Key=key)
    return resp["Body"].read()


def presigned_url(key: str, expires: int = 3600) -> str:
    """A temporary HTTPS URL to the S3 object, fetchable by external services
    (e.g. Replicate) without relying on the CDN."""
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": config.S3_BUCKET, "Key": key},
        ExpiresIn=expires,
    )


def upload_bytes(
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    cache_control: Optional[str] = "public, max-age=31536000, immutable",
) -> dict:
    """Upload bytes to S3 under `key`; return {s3_key, cdn_url, mime}."""
    extra = {"ContentType": content_type}
    if cache_control:
        extra["CacheControl"] = cache_control
    _client().put_object(Bucket=config.S3_BUCKET, Key=key, Body=data, **extra)
    return {"s3_key": key, "cdn_url": cdn_url_for(key), "mime": content_type}


def dataset_input_key(dataset_id: str, image_id: int, ext: str) -> str:
    ext = ext.lstrip(".")
    return f"{config.S3_ROOT_PREFIX}/datasets/{dataset_id}/{image_id}.{ext}"


def run_output_key(run_id: str, image_id: int, variant: str, ext: str = "png") -> str:
    return f"{config.S3_ROOT_PREFIX}/runs/{run_id}/{image_id}/{variant}.{ext}"
