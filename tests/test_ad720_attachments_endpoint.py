"""AD-720: /api/chat/attachments endpoint tests (lightweight — no full runtime)."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from probos.config import AttachmentsConfig
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime


_PNG_HEADER = b"\x89PNG\r\n\x1a\n"
_JPEG_HEADER = b"\xff\xd8\xff\xe0"


def _build_payload(blob: bytes, mime: str) -> dict:
    return {
        "content_hash": hashlib.sha256(blob).hexdigest(),
        "blob_b64": base64.b64encode(blob).decode("ascii"),
        "mime": mime,
    }


@pytest.fixture
def app(tmp_path: Path, monkeypatch):
    target = tmp_path / "attachments"
    monkeypatch.setattr(
        "probos.attachments.store._resolve_attachments_dir",
        lambda configured: target,
    )
    cfg = AttachmentsConfig(attachments_dir=str(target))
    runtime_stub = SimpleNamespace(config=SimpleNamespace(attachments=cfg))
    a = FastAPI()
    a.include_router(chat_router_mod.router)
    a.dependency_overrides[get_runtime] = lambda: runtime_stub
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    yield a, runtime_stub
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.fixture
async def client(app):
    a, rt = app
    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, rt


@pytest.mark.asyncio
async def test_post_attachment_happy_path(client):
    ac, _ = client
    blob = _PNG_HEADER + b"a" * 64
    payload = _build_payload(blob, "image/png")
    r = await ac.post("/api/chat/attachments", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["attachment_id"] == payload["content_hash"]
    assert data["mime"] == "image/png"
    assert data["size_bytes"] == len(blob)
    assert data["sha256"] == payload["content_hash"]
    assert data["url"].endswith(payload["content_hash"])


@pytest.mark.asyncio
async def test_post_attachment_oversized_returns_413(client):
    ac, rt = client
    rt.config.attachments.max_attachment_bytes = 64
    blob = _PNG_HEADER + b"a" * 200
    payload = _build_payload(blob, "image/png")
    r = await ac.post("/api/chat/attachments", json=payload)
    assert r.status_code == 413
    assert r.json()["error"] == "too_large"


@pytest.mark.asyncio
async def test_post_attachment_disallowed_mime_returns_415(client):
    ac, _ = client
    payload = {
        "content_hash": hashlib.sha256(b"x").hexdigest(),
        "blob_b64": base64.b64encode(b"x").decode("ascii"),
        "mime": "image/svg+xml",
    }
    r = await ac.post("/api/chat/attachments", json=payload)
    assert r.status_code == 415
    assert r.json()["error"] == "mime_not_allowed"


@pytest.mark.asyncio
async def test_post_attachment_magic_mismatch_returns_415(client):
    ac, _ = client
    blob = _PNG_HEADER + b"a" * 64
    payload = _build_payload(blob, "image/jpeg")
    r = await ac.post("/api/chat/attachments", json=payload)
    assert r.status_code == 415
    assert r.json()["error"] == "magic_mismatch"


@pytest.mark.asyncio
async def test_post_attachment_invalid_base64_returns_400(client):
    ac, _ = client
    payload = {
        "content_hash": "0" * 64,
        "blob_b64": "!!!not-base64!!!",
        "mime": "image/png",
    }
    r = await ac.post("/api/chat/attachments", json=payload)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_base64"


@pytest.mark.asyncio
async def test_post_attachment_hash_mismatch_returns_400(client):
    ac, _ = client
    blob = _PNG_HEADER + b"a" * 64
    payload = _build_payload(blob, "image/png")
    payload["content_hash"] = "0" * 64
    r = await ac.post("/api/chat/attachments", json=payload)
    assert r.status_code == 400
    assert r.json()["error"] == "hash_mismatch"


@pytest.mark.asyncio
async def test_post_attachment_idempotent_reupload_returns_200(client):
    ac, _ = client
    blob = _PNG_HEADER + b"b" * 64
    payload = _build_payload(blob, "image/png")
    r1 = await ac.post("/api/chat/attachments", json=payload)
    r2 = await ac.post("/api/chat/attachments", json=payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["attachment_id"] == r2.json()["attachment_id"]
    assert r1.json()["url"] == r2.json()["url"]


@pytest.mark.asyncio
async def test_post_attachment_jpeg_happy_path(client):
    ac, _ = client
    blob = _JPEG_HEADER + b"a" * 64
    payload = _build_payload(blob, "image/jpeg")
    r = await ac.post("/api/chat/attachments", json=payload)
    assert r.status_code == 200
    assert r.json()["mime"] == "image/jpeg"


@pytest.mark.asyncio
async def test_post_attachment_disabled_returns_503(client):
    ac, rt = client
    rt.config.attachments.enabled = False
    blob = _PNG_HEADER + b"a" * 64
    payload = _build_payload(blob, "image/png")
    r = await ac.post("/api/chat/attachments", json=payload)
    assert r.status_code == 503
    assert r.json()["error"] == "attachments_disabled"
