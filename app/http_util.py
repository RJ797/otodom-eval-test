"""Small HTTP helper that verifies TLS using the certifi CA bundle.

macOS Python (and some other environments) lack a system CA bundle, so plain
urllib raises CERTIFICATE_VERIFY_FAILED on https URLs. Routing every download
through here fixes that consistently.
"""

from __future__ import annotations

import ssl
import urllib.request

import certifi

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def fetch_bytes(url: str, timeout: int = 30) -> bytes:
    """GET a URL and return its bytes, verifying TLS via certifi."""
    with urllib.request.urlopen(url, timeout=timeout, context=_SSL_CONTEXT) as resp:  # noqa: S310
        return resp.read()
