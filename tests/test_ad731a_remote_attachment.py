"""AD-731a-1: cross-host attachment serving + verifying fetch (issue #638).

BF-287: real ``FilesystemAttachmentStore`` on ``tmp_path`` + real
``AttachmentsConfig`` / ``AuthConfig`` + the real ASGI app served in-process —
NO MagicMock at the substrate boundary. The serving tests exercise the actual
FastAPI route (with the ``require_crew_scope`` dependency); the client tests
use httpx ``MockTransport`` so no real network is touched.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import AttachmentsConfig, AuthConfig
from probos.federation.attachment_fetch import fetch_remote_attachment
from probos.routers import federation_attachments


_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body-for-ad731a"
_PNG_SHA = hashlib.sha256(_PNG_BYTES).hexdigest()
_PNG_MIME = "image/png"


# ---------------------------------------------------------------------------
# Helpers — real store + real config + real ASGI app (BF-287)
# ---------------------------------------------------------------------------

def _make_runtime(
    tmp_path,
    *,
    serve_remote_enabled: bool,
    crew_scope_token: str,
    max_attachment_bytes: int = 10 * 1024 * 1024,
) -> tuple[Any, FilesystemAttachmentStore]:
    """Real-ish runtime stub: real Pydantic config + real filesystem store."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    config = SimpleNamespace(
        attachments=AttachmentsConfig(
            serve_remote_enabled=serve_remote_enabled,
            max_attachment_bytes=max_attachment_bytes,
        ),
        auth=AuthConfig(crew_scope_token=crew_scope_token),
    )
    runtime = SimpleNamespace(config=config, attachment_store=store)
    return runtime, store


def _make_client(runtime: Any) -> AsyncClient:
    """Mount only the federation_attachments router on a bare ASGI app."""
    app = FastAPI()
    app.include_router(federation_attachments.router)
    app.state.runtime = runtime
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Serving endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serve_known_sha_returns_bytes(tmp_path):
    """Flag on + token set + correct Bearer -> 200, body == bytes, mime."""
    runtime, store = _make_runtime(
        tmp_path, serve_remote_enabled=True, crew_scope_token="secret"
    )
    await store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    async with _make_client(runtime) as client:
        resp = await client.get(
            f"/api/federation/attachments/{_PNG_SHA}",
            headers={"Authorization": "Bearer secret"},
        )
    assert resp.status_code == 200
    assert resp.content == _PNG_BYTES
    assert resp.headers["content-type"].split(";")[0].strip() == _PNG_MIME


@pytest.mark.asyncio
async def test_serve_unknown_sha_404(tmp_path):
    """Valid 64-hex hash that is not stored -> 404 attachment_not_found."""
    runtime, _store = _make_runtime(
        tmp_path, serve_remote_enabled=True, crew_scope_token="secret"
    )
    unknown = "0" * 64
    async with _make_client(runtime) as client:
        resp = await client.get(
            f"/api/federation/attachments/{unknown}",
            headers={"Authorization": "Bearer secret"},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "attachment_not_found"


@pytest.mark.asyncio
async def test_serve_flag_off_404_byte_identical(tmp_path):
    """Feature off -> 404 disabled (does not leak token state; no Bearer)."""
    runtime, store = _make_runtime(
        tmp_path, serve_remote_enabled=False, crew_scope_token=""
    )
    await store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    async with _make_client(runtime) as client:
        resp = await client.get(f"/api/federation/attachments/{_PNG_SHA}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "attachments_remote_serving_disabled"


@pytest.mark.asyncio
async def test_serve_token_unset_403_fail_closed(tmp_path):
    """Flag on but token unset -> 403 (never serve through a pass-through gate)."""
    runtime, store = _make_runtime(
        tmp_path, serve_remote_enabled=True, crew_scope_token=""
    )
    await store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    async with _make_client(runtime) as client:
        resp = await client.get(f"/api/federation/attachments/{_PNG_SHA}")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "remote_serving_requires_token"


@pytest.mark.asyncio
async def test_serve_wrong_or_missing_bearer_401(tmp_path):
    """Token set + wrong/missing Bearer -> 401 from require_crew_scope."""
    runtime, store = _make_runtime(
        tmp_path, serve_remote_enabled=True, crew_scope_token="secret"
    )
    await store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    async with _make_client(runtime) as client:
        wrong = await client.get(
            f"/api/federation/attachments/{_PNG_SHA}",
            headers={"Authorization": "Bearer WRONG"},
        )
        missing = await client.get(f"/api/federation/attachments/{_PNG_SHA}")
    assert wrong.status_code == 401
    assert missing.status_code == 401


@pytest.mark.asyncio
async def test_serve_bad_sha_400_no_store_call(tmp_path):
    """Malformed hash -> 400 invalid_content_hash before any store access."""
    runtime, _store = _make_runtime(
        tmp_path, serve_remote_enabled=True, crew_scope_token="secret"
    )
    headers = {"Authorization": "Bearer secret"}
    async with _make_client(runtime) as client:
        for bad in ("zzz", "a" * 63, "z" * 64):
            resp = await client.get(
                f"/api/federation/attachments/{bad}", headers=headers
            )
            assert resp.status_code == 400, bad
            assert resp.json()["detail"] == "invalid_content_hash"
        # Path-traversal token can never bind as a single {content_hash}
        # path segment; the router rejects it (normalizes away) -> never 200.
        trav = await client.get(
            "/api/federation/attachments/../etc", headers=headers
        )
        assert trav.status_code in (400, 404)


@pytest.mark.asyncio
async def test_serve_over_cap_413(tmp_path):
    """Stored blob larger than max_attachment_bytes -> 413 attachment_too_large."""
    big = b"x" * 100
    big_sha = hashlib.sha256(big).hexdigest()
    runtime, store = _make_runtime(
        tmp_path,
        serve_remote_enabled=True,
        crew_scope_token="secret",
        max_attachment_bytes=4,
    )
    await store.write(big_sha, big, _PNG_MIME)
    async with _make_client(runtime) as client:
        resp = await client.get(
            f"/api/federation/attachments/{big_sha}",
            headers={"Authorization": "Bearer secret"},
        )
    assert resp.status_code == 413
    assert resp.json()["detail"] == "attachment_too_large"


# ---------------------------------------------------------------------------
# Client helper — httpx MockTransport, no network
# ---------------------------------------------------------------------------

def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_fetch_roundtrip_verified_stores(tmp_path):
    """200 + matching sha + good mime -> True, bytes stored and round-trip."""
    store = FilesystemAttachmentStore(tmp_path / "client")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        seen["url"] = str(request.url)
        return httpx.Response(
            200, content=_PNG_BYTES, headers={"content-type": "image/png"}
        )

    client = _mock_client(handler)
    try:
        ok = await fetch_remote_attachment(
            "http://peer", _PNG_SHA, auth_token="tok", store=store, http=client
        )
    finally:
        await client.aclose()

    assert ok is True
    assert seen["auth"] == "Bearer tok"
    assert seen["url"].endswith(f"/api/federation/attachments/{_PNG_SHA}")
    assert await store.exists(_PNG_SHA)
    assert await store.read(_PNG_SHA) == _PNG_BYTES


@pytest.mark.asyncio
async def test_fetch_tamper_detected_not_stored(tmp_path):
    """Body sha != requested hash -> False, write NOT called (nothing stored)."""
    store = FilesystemAttachmentStore(tmp_path / "client")
    tampered = b"TAMPERED-bytes-do-not-match-the-requested-sha"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=tampered, headers={"content-type": "image/png"}
        )

    client = _mock_client(handler)
    try:
        ok = await fetch_remote_attachment(
            "http://peer", _PNG_SHA, auth_token="tok", store=store, http=client
        )
    finally:
        await client.aclose()

    assert ok is False
    assert not await store.exists(_PNG_SHA)


@pytest.mark.asyncio
async def test_fetch_peer_404_returns_false_no_write(tmp_path):
    """Peer 404 -> False, nothing stored."""
    store = FilesystemAttachmentStore(tmp_path / "client")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = _mock_client(handler)
    try:
        ok = await fetch_remote_attachment(
            "http://peer", _PNG_SHA, auth_token="tok", store=store, http=client
        )
    finally:
        await client.aclose()

    assert ok is False
    assert not await store.exists(_PNG_SHA)


@pytest.mark.asyncio
async def test_fetch_bad_mime_rejected(tmp_path):
    """Matching sha but a mime the store rejects -> False, nothing stored."""
    store = FilesystemAttachmentStore(tmp_path / "client")

    def handler(request: httpx.Request) -> httpx.Response:
        # sha matches the bytes, but image/tiff is not a storable mime.
        return httpx.Response(
            200, content=_PNG_BYTES, headers={"content-type": "image/tiff"}
        )

    client = _mock_client(handler)
    try:
        ok = await fetch_remote_attachment(
            "http://peer", _PNG_SHA, auth_token="tok", store=store, http=client
        )
    finally:
        await client.aclose()

    assert ok is False
    assert not await store.exists(_PNG_SHA)


@pytest.mark.asyncio
async def test_fetch_malformed_hash_raises_before_network(tmp_path):
    """Malformed content_hash -> ValueError before any HTTP call."""
    store = FilesystemAttachmentStore(tmp_path / "client")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200, content=_PNG_BYTES, headers={"content-type": "image/png"}
        )

    client = _mock_client(handler)
    try:
        with pytest.raises(ValueError):
            await fetch_remote_attachment(
                "http://peer", "not-a-valid-hash", auth_token="tok",
                store=store, http=client,
            )
    finally:
        await client.aclose()

    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_fetch_oversize_rejected(tmp_path):
    """Body larger than max_bytes -> False, nothing stored."""
    store = FilesystemAttachmentStore(tmp_path / "client")
    big = b"y" * 50
    big_sha = hashlib.sha256(big).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=big, headers={"content-type": "image/png"}
        )

    client = _mock_client(handler)
    try:
        ok = await fetch_remote_attachment(
            "http://peer", big_sha, auth_token="tok", store=store,
            http=client, max_bytes=4,
        )
    finally:
        await client.aclose()

    assert ok is False
    assert not await store.exists(big_sha)
