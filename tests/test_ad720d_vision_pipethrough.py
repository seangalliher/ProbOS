"""AD-720d (Wave 139): vision pipe-through routing tests.

Covers:
  - image attachments routed via vision tier with multimodal messages payload
  - text/markdown/json/csv attachments inline-extracted into augmented prompt
  - oversize text truncated with [TRUNCATED] marker
  - vision tier unhealthy → text-only stub (no LLM call)
  - PDF with extraction disabled → deferred-feature stub
  - zero-attachment regression guard (decomposer still called)
  - cfg.enabled=False short-circuits the new branch
"""

from __future__ import annotations

import base64
import hashlib
import json as json_mod
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from probos.config import AttachmentsConfig
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime, get_ws_broadcast, get_task_tracker, get_pending_designs


_PNG_HEADER = b"\x89PNG\r\n\x1a\n"
_PDF_HEADER = b"%PDF-1.4\n"


@pytest.fixture
def runtime_fixture(tmp_path: Path, monkeypatch):
    """Build a stub runtime + pre-write a few content-addressed blobs."""
    target = tmp_path / "attachments"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "probos.attachments.store._resolve_attachments_dir",
        lambda configured: target,
    )
    cfg = AttachmentsConfig(
        attachments_dir=str(target),
        max_attachment_bytes=10 * 1024 * 1024,
        text_extraction_max_bytes=1024,
        vision_tier="standard",
        pdf_extraction_enabled=False,
    )

    # Mock LLM client.
    llm_client = MagicMock()
    canned_response = SimpleNamespace(
        content="VISION_TIER_REPLY",
        model="claude-sonnet-4.6",
        tier="standard",
        tokens_used=42,
        prompt_tokens=20,
        completion_tokens=22,
    )
    llm_client.complete = AsyncMock(return_value=canned_response)
    llm_client.get_health_status = MagicMock(
        return_value={"tiers": {"standard": {"status": "operational"}}, "overall": "operational"},
    )

    # Spy on process_natural_language so we can assert what it was called with.
    pnl = AsyncMock(return_value={
        "final_response": "DECOMPOSER_REPLY",
        "results": {},
        "dag": [],
    })

    rt = SimpleNamespace(
        config=SimpleNamespace(attachments=cfg),
        llm_client=llm_client,
        process_natural_language=pnl,
    )

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()

    # Pre-write blobs through the same store the chat handler will use.
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    store = FilesystemAttachmentStore(target)

    async def _write(blob: bytes, mime: str) -> str:
        sha = hashlib.sha256(blob).hexdigest()
        await store.write(sha, blob, mime)
        return sha

    # Build the FastAPI app with our stub runtime.
    a = FastAPI()
    a.include_router(chat_router_mod.router)
    a.dependency_overrides[get_runtime] = lambda: rt
    a.dependency_overrides[get_ws_broadcast] = lambda: (lambda msg: None)
    a.dependency_overrides[get_task_tracker] = lambda: (lambda coro, name="": None)
    a.dependency_overrides[get_pending_designs] = lambda: {}

    yield a, rt, _write
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.fixture
async def client(runtime_fixture):
    a, rt, write_blob = runtime_fixture
    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, rt, write_blob


@pytest.mark.asyncio
async def test_image_attachment_routes_via_vision_tier(client):
    ac, rt, write_blob = client
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    r = await ac.post(
        "/api/chat",
        json={"message": "what is this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["response"] == "VISION_TIER_REPLY"
    rt.llm_client.complete.assert_called_once()
    sent_request = rt.llm_client.complete.call_args.args[0]
    assert sent_request.tier == "standard"
    assert sent_request.messages is not None
    content = sent_request.messages[0]["content"]
    assert any(item.get("type") == "image" for item in content)
    image_item = next(item for item in content if item.get("type") == "image")
    assert image_item["source"]["media_type"] == "image/png"
    rt.process_natural_language.assert_not_called()


@pytest.mark.asyncio
async def test_text_plain_attachment_appends_block_and_decomposes(client):
    ac, rt, write_blob = client
    sha = await write_blob(b"hello attachment world", "text/plain")
    r = await ac.post(
        "/api/chat",
        json={"message": "summarise this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    rt.llm_client.complete.assert_not_called()
    rt.process_natural_language.assert_called_once()
    augmented_prompt = rt.process_natural_language.call_args.args[0]
    assert "summarise this" in augmented_prompt
    assert "<ATTACHMENT" in augmented_prompt
    assert "mime=\"text/plain\"" in augmented_prompt
    assert "hello attachment world" in augmented_prompt


@pytest.mark.asyncio
async def test_text_markdown_attachment_appends_block(client):
    ac, rt, write_blob = client
    sha = await write_blob(b"# Heading\n\nbody.", "text/markdown")
    r = await ac.post(
        "/api/chat",
        json={"message": "explain", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    augmented_prompt = rt.process_natural_language.call_args.args[0]
    assert "mime=\"text/markdown\"" in augmented_prompt
    assert "# Heading" in augmented_prompt


@pytest.mark.asyncio
async def test_json_attachment_appends_pretty_block(client):
    ac, rt, write_blob = client
    sha = await write_blob(b'{"k":"v","n":1}', "application/json")
    r = await ac.post(
        "/api/chat",
        json={"message": "look", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    augmented_prompt = rt.process_natural_language.call_args.args[0]
    assert "mime=\"application/json\"" in augmented_prompt
    # Pretty-printed (indent=2) should produce a newline + spaces.
    assert '"k": "v"' in augmented_prompt
    assert '"n": 1' in augmented_prompt


@pytest.mark.asyncio
async def test_csv_attachment_appends_block(client):
    ac, rt, write_blob = client
    sha = await write_blob(b"a,b,c\n1,2,3\n", "text/csv")
    r = await ac.post(
        "/api/chat",
        json={"message": "tally", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    augmented_prompt = rt.process_natural_language.call_args.args[0]
    assert "mime=\"text/csv\"" in augmented_prompt
    assert "a,b,c" in augmented_prompt


@pytest.mark.asyncio
async def test_oversize_text_truncated(client):
    ac, rt, write_blob = client
    rt.config.attachments.text_extraction_max_bytes = 32
    blob = b"x" * 200
    sha = await write_blob(blob, "text/plain")
    r = await ac.post(
        "/api/chat",
        json={"message": "summarise", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    augmented_prompt = rt.process_natural_language.call_args.args[0]
    assert "[TRUNCATED]" in augmented_prompt


@pytest.mark.asyncio
async def test_vision_tier_unhealthy_returns_text_only_stub(client, caplog):
    ac, rt, write_blob = client
    rt.llm_client.get_health_status = MagicMock(
        return_value={"tiers": {"standard": {"status": "unreachable"}}, "overall": "degraded"},
    )
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    with caplog.at_level(logging.WARNING):
        r = await ac.post(
            "/api/chat",
            json={"message": "what is this", "history": [], "attachment_ids": [sha]},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "vision processing is currently unavailable" in body["response"]
    assert sha[:6] in body["response"] or sha in body["response"]
    rt.llm_client.complete.assert_not_called()
    assert any(
        "AD-720d vision tier=standard unavailable" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_pdf_attachment_with_extraction_disabled_emits_stub(client):
    ac, rt, write_blob = client
    sha = await write_blob(_PDF_HEADER + b"body", "application/pdf")
    r = await ac.post(
        "/api/chat",
        json={"message": "read this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    augmented_prompt = rt.process_natural_language.call_args.args[0]
    assert "PDF extraction not yet wired" in augmented_prompt
    assert "AD-720a-1" in augmented_prompt


@pytest.mark.asyncio
async def test_zero_attachment_chat_unchanged_regression(client):
    ac, rt, _ = client
    r = await ac.post(
        "/api/chat",
        json={"message": "hello", "history": [], "attachment_ids": []},
    )
    assert r.status_code == 200, r.text
    rt.llm_client.complete.assert_not_called()
    rt.process_natural_language.assert_called_once()
    sent_prompt = rt.process_natural_language.call_args.args[0]
    assert sent_prompt == "hello"  # un-augmented


@pytest.mark.asyncio
async def test_attachments_disabled_skips_branch(client):
    ac, rt, write_blob = client
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    rt.config.attachments.enabled = False
    r = await ac.post(
        "/api/chat",
        json={"message": "hello", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    # Neither vision dispatch nor augmented prompt should have fired.
    rt.llm_client.complete.assert_not_called()
    rt.process_natural_language.assert_called_once()
    sent_prompt = rt.process_natural_language.call_args.args[0]
    assert sent_prompt == "hello"  # un-augmented
