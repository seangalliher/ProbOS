"""AD-731a-1: content-verifying remote attachment fetch (issue #638).

Client side of cross-host attachment distribution v1. Pulls attachment bytes
from an authenticated federation peer's
``GET /api/federation/attachments/{content_hash}`` serving endpoint and stores
them ONLY after verifying that ``sha256(received_bytes)`` equals the requested
``content_hash``. Tampered or corrupt bytes are rejected and never stored.

DI: ``store`` and ``http`` are injectable so the integrity, size, and
honest-degrade paths can be exercised with no network (httpx ``MockTransport``).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def fetch_remote_attachment(
    peer_url: str,
    content_hash: str,
    *,
    auth_token: str,
    store: Any,
    http: httpx.AsyncClient | None = None,
    max_bytes: int = 10 * 1024 * 1024,
) -> bool:
    """Fetch + verify + store a remote attachment. Returns True iff stored.

    Returns ``False`` (honest-degrade, never stores) when the peer has no such
    attachment (404), the body exceeds ``max_bytes``, the sha256 of the bytes
    does not match ``content_hash`` (tamper/corruption), the response carries
    no content-type, or the store rejects the mime. Raises ``ValueError`` for a
    malformed ``content_hash`` (before any network call) and re-raises peer HTTP
    errors other than 404.
    """
    # 1. Validate the requested hash BEFORE any network call.
    if not (
        len(content_hash) == 64
        and all(c in "0123456789abcdef" for c in content_hash)
    ):
        raise ValueError(f"AD-731a-1: malformed content_hash {content_hash!r}")

    url = f"{peer_url.rstrip('/')}/api/federation/attachments/{content_hash}"
    headers = {"Authorization": f"Bearer {auth_token}"}

    # 2. GET — use the injected client (tests) or a short-lived owned one.
    owns_client = http is None
    client = http or httpx.AsyncClient()
    try:
        response = await client.get(url, headers=headers)
        if response.status_code == 404:
            logger.info(
                "AD-731a-1: peer %s has no attachment %s (404); skipping",
                peer_url, content_hash[:8],
            )
            return False
        if response.status_code >= 400:
            # Non-404 peer error — surface it (auth failure, 5xx, etc.).
            response.raise_for_status()
        blob = response.content
        content_type = response.headers.get("content-type") or ""
    finally:
        if owns_client:
            await client.aclose()

    # 3. Size cap — reject oversize, do not store.
    if len(blob) > max_bytes:
        logger.warning(
            "AD-731a-1: peer %s attachment %s is %d bytes (> %d cap); rejecting",
            peer_url, content_hash[:8], len(blob), max_bytes,
        )
        return False

    # 4. Integrity — sha256(bytes) MUST equal the requested hash.
    if hashlib.sha256(blob).hexdigest() != content_hash:
        logger.warning(
            "AD-731a-1: integrity check FAILED for %s from %s "
            "(content-hash mismatch); rejecting tampered/corrupt bytes",
            content_hash[:8], peer_url,
        )
        return False

    # 5. Mime — derive from the response. The store is the single authority on
    #    acceptability (it raises ValueError for an unknown mime), so an empty
    #    content-type is rejected here and an unstorable one is caught on write.
    mime = (content_type.split(";")[0] if content_type else "").strip().lower()
    if not mime:
        logger.warning(
            "AD-731a-1: peer %s returned no content-type for %s; rejecting",
            peer_url, content_hash[:8],
        )
        return False

    # 6. Store the verified bytes (origin tagged as a chat attachment so the
    #    reaper never sweeps it by age).
    try:
        await store.write(content_hash, blob, mime, origin="chat_attachment")
    except ValueError:
        logger.warning(
            "AD-731a-1: store rejected mime %r for %s from %s; not stored",
            mime, content_hash[:8], peer_url,
        )
        return False
    return True
