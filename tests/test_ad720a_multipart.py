"""AD-720a (Wave 139): /api/chat/attachments/multipart endpoint tests + helper-extraction regression."""

from __future__ import annotations

import base64
import hashlib
import json as json_mod
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from probos.config import AttachmentsConfig
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime


_PNG_HEADER = b"\x89PNG\r\n\x1a\n"
_PDF_HEADER = b"%PDF-1.4\n"


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
async def test_multipart_post_png_happy(client):
    ac, _ = client
    blob = _PNG_HEADER + b"a" * 64
    r = await ac.post(
        "/api/chat/attachments/multipart",
        files={"file": ("avatar.png", blob, "image/png")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    expected_hash = hashlib.sha256(blob).hexdigest()
    assert data["attachment_id"] == expected_hash
    assert data["mime"] == "image/png"
    assert data["size_bytes"] == len(blob)
    assert data["sha256"] == expected_hash
    assert data["url"].endswith(expected_hash)


@pytest.mark.asyncio
async def test_multipart_post_pdf_happy(client):
    ac, _ = client
    blob = _PDF_HEADER + b"%fake-pdf-body\n"
    r = await ac.post(
        "/api/chat/attachments/multipart",
        files={"file": ("doc.pdf", blob, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mime"] == "application/pdf"
    assert data["size_bytes"] == len(blob)


@pytest.mark.asyncio
async def test_multipart_post_text_happy(client):
    ac, _ = client
    blob = "Hello, attachment world.\n".encode("utf-8")
    r = await ac.post(
        "/api/chat/attachments/multipart",
        files={"file": ("notes.txt", blob, "text/plain")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["mime"] == "text/plain"


@pytest.mark.asyncio
async def test_multipart_post_json_happy(client):
    ac, _ = client
    blob = json_mod.dumps({"k": "v", "n": 1}).encode("utf-8")
    r = await ac.post(
        "/api/chat/attachments/multipart",
        files={"file": ("data.json", blob, "application/json")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["mime"] == "application/json"


@pytest.mark.asyncio
async def test_multipart_post_csv_happy(client):
    ac, _ = client
    blob = b"a,b,c\n1,2,3\n"
    r = await ac.post(
        "/api/chat/attachments/multipart",
        files={"file": ("rows.csv", blob, "text/csv")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["mime"] == "text/csv"


@pytest.mark.asyncio
async def test_multipart_post_oversize_returns_413(client):
    ac, rt = client
    rt.config.attachments.max_attachment_bytes = 64
    blob = _PNG_HEADER + b"a" * 200
    r = await ac.post(
        "/api/chat/attachments/multipart",
        files={"file": ("big.png", blob, "image/png")},
    )
    assert r.status_code == 413
    body = r.json()
    assert body["error"] == "too_large"
    assert body["max"] == 64


@pytest.mark.asyncio
async def test_multipart_post_disallowed_mime_returns_415(client):
    ac, _ = client
    r = await ac.post(
        "/api/chat/attachments/multipart",
        files={"file": ("evil.svg", b"<svg/>", "image/svg+xml")},
    )
    assert r.status_code == 415
    assert r.json()["error"] == "mime_not_allowed"


@pytest.mark.asyncio
async def test_multipart_post_magic_mismatch_returns_415(client):
    ac, _ = client
    # PNG bytes declared as PDF — magic-byte sniff catches it.
    blob = _PNG_HEADER + b"a" * 64
    r = await ac.post(
        "/api/chat/attachments/multipart",
        files={"file": ("notpdf.pdf", blob, "application/pdf")},
    )
    assert r.status_code == 415
    body = r.json()
    assert body["error"] == "magic_mismatch"
    assert body["declared"] == "application/pdf"


@pytest.mark.asyncio
async def test_multipart_post_attachments_disabled_returns_503(client):
    ac, rt = client
    rt.config.attachments.enabled = False
    blob = _PNG_HEADER + b"a" * 64
    r = await ac.post(
        "/api/chat/attachments/multipart",
        files={"file": ("x.png", blob, "image/png")},
    )
    assert r.status_code == 503
    assert r.json()["error"] == "attachments_disabled"


@pytest.mark.asyncio
async def test_multipart_post_text_extension_mismatch_returns_415(client):
    ac, _ = client
    # Valid UTF-8, declared text/plain, but filename has wrong extension.
    blob = b"plain text content"
    r = await ac.post(
        "/api/chat/attachments/multipart",
        files={"file": ("notes.bad", blob, "text/plain")},
    )
    assert r.status_code == 415
    body = r.json()
    assert body["error"] == "magic_mismatch"
    assert body["sniffed"] == "extension_mismatch"


@pytest.mark.asyncio
async def test_helper_extraction_regression_json_path_still_200(client):
    """AD-720a: existing JSON+base64 endpoint preserves bit-for-bit response shape
    after refactor to ``_validate_and_store_attachment`` helper."""
    ac, _ = client
    blob = _PNG_HEADER + b"a" * 64
    payload = {
        "content_hash": hashlib.sha256(blob).hexdigest(),
        "blob_b64": base64.b64encode(blob).decode("ascii"),
        "mime": "image/png",
    }
    r = await ac.post("/api/chat/attachments", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["attachment_id"] == payload["content_hash"]
    assert data["mime"] == "image/png"
    assert data["size_bytes"] == len(blob)
    assert data["sha256"] == payload["content_hash"]
    assert data["url"] == f"/api/chat/attachments/{payload['content_hash']}"
