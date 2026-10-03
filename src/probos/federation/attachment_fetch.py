"""AD-731a-1: content-verifying remote attachment fetch (issue #638).

Client side of cross-host attachment distribution v1. Pulls attachment bytes
from an authenticated federation peer's
``GET /api/federation/attachments/{content_hash}`` serving endpoint and stores
them ONLY after verifying that ``sha256(received_bytes)`` equals the requested
``content_hash``. Tampered or corrupt bytes are rejected and never stored.

AD-1198 slice 3a: :func:`fetch_remote_attachment_signed` is the armed path. It
POSTs a signed peer request (``probos.federation.peer_requests``) to the peer's
main API, sends no ``Authorization`` header, refuses a content-encoded response
before reading it (nothing a peer sends is decompressed), refuses the first
chunk that would take the body past the size cap, and verifies exactly as the
bearer-token fetch does.

DI: ``store`` and ``http`` are injectable so the integrity, size, and
honest-degrade paths can be exercised with no network (httpx ``MockTransport``).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _is_content_hash(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


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
    if not _is_content_hash(content_hash):
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
    return await _store_verified(peer_url, content_hash, blob, content_type, store=store, max_bytes=max_bytes)


async def fetch_remote_attachment_signed(
    api_url: str,
    content_hash: str,
    *,
    body: bytes,
    store: Any,
    http: httpx.AsyncClient | None = None,
    max_bytes: int = 10 * 1024 * 1024,
) -> bool:
    """AD-1198: fetch + verify + store a peer's attachment with a signed peer request. Returns True iff stored.

    POSTs ``body`` -- a peer request sealed for that peer (``PeerRequests.sign``) -- to
    ``{api_url}/api/federation/attachments/{content_hash}`` with no ``Authorization`` header, asking for an
    unencoded response. A response with any ``Content-Encoding`` other than ``identity`` is refused (``False``)
    before a byte of it is read, so nothing is decompressed and the cap counts the bytes the peer sent. Any
    other response is read chunk by chunk, and a chunk joins the body only while the body stays within
    ``max_bytes``: the first chunk that would pass the cap refuses the response, so the body never holds more
    than ``max_bytes``. Each chunk is still held once as the transport delivers it (over HTTP/1.1, httpcore reads
    at most 64 KiB per socket read). The body is then verified exactly as :func:`fetch_remote_attachment`. Raises
    ``ValueError`` for a malformed ``content_hash`` (before any network call) and re-raises peer HTTP errors
    other than 404; a 401 means the peer refused this ship's request.
    """
    if not _is_content_hash(content_hash):
        raise ValueError(f"AD-1198: malformed content_hash {content_hash!r}")
    url = f"{api_url.rstrip('/')}/api/federation/attachments/{content_hash}"
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}  # AD-1198 no Authorization header: a peer request is signed
    owns_client = http is None
    client = http or httpx.AsyncClient()
    try:
        async with client.stream("POST", url, content=body, headers=headers) as response:
            if response.status_code == 404:
                logger.info("AD-1198: peer %s has no attachment %s (404); skipping", api_url, content_hash[:8])
                return False
            if response.status_code >= 400:
                response.raise_for_status()
            encoding = response.headers.get("content-encoding", "identity")
            if encoding.strip().lower() != "identity":  # AD-1198 only an unencoded response is read: nothing a peer sends is decompressed
                logger.warning(
                    "AD-1198: peer %s attachment %s is content-encoded (%r); only identity is read, rejecting",
                    api_url, content_hash[:8], encoding[:64],
                )
                return False
            content_type = response.headers.get("content-type") or ""
            blob = bytearray()
            async for chunk in response.aiter_bytes():
                if len(blob) + len(chunk) > max_bytes:  # AD-1198 the body never grows past the cap: the first chunk that would take it past is refused
                    logger.warning(
                        "AD-1198: peer %s attachment %s exceeds the %d byte cap; rejecting",
                        api_url, content_hash[:8], max_bytes,
                    )
                    return False
                blob.extend(chunk)  # AD-1198 a chunk joins the body only while the body stays within the cap
    finally:
        if owns_client:
            await client.aclose()
    return await _store_verified(api_url, content_hash, bytes(blob), content_type, store=store, max_bytes=max_bytes)


async def _store_verified(
    source: str, content_hash: str, blob: bytes, content_type: str, *, store: Any, max_bytes: int,
) -> bool:
    """Steps 3-6 of both fetches: the size cap, the integrity check, the mime, then the store."""
    # 3. Size cap — reject oversize, do not store.
    if len(blob) > max_bytes:
        logger.warning(
            "AD-731a-1: peer %s attachment %s is %d bytes (> %d cap); rejecting",
            source, content_hash[:8], len(blob), max_bytes,
        )
        return False

    # 4. Integrity — sha256(bytes) MUST equal the requested hash.
    if hashlib.sha256(blob).hexdigest() != content_hash:
        logger.warning(
            "AD-731a-1: integrity check FAILED for %s from %s "
            "(content-hash mismatch); rejecting tampered/corrupt bytes",
            content_hash[:8], source,
        )
        return False

    # 5. Mime — derive from the response. The store is the single authority on
    #    acceptability (it raises ValueError for an unknown mime), so an empty
    #    content-type is rejected here and an unstorable one is caught on write.
    mime = (content_type.split(";")[0] if content_type else "").strip().lower()
    if not mime:
        logger.warning(
            "AD-731a-1: peer %s returned no content-type for %s; rejecting",
            source, content_hash[:8],
        )
        return False

    # 6. Store the verified bytes (origin tagged as a chat attachment so the
    #    reaper never sweeps it by age).
    try:
        await store.write(content_hash, blob, mime, origin="chat_attachment")
    except ValueError:
        logger.warning(
            "AD-731a-1: store rejected mime %r for %s from %s; not stored",
            mime, content_hash[:8], source,
        )
        return False
    return True
