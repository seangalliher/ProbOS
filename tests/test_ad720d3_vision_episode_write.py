"""AD-720d-3 (Wave 154): episodic write for /api/chat vision-routed turns.

The standard NL path stores an episode after decomposition, but the vision
branch in `/api/chat` short-circuits via `return` and would otherwise leave
the turn invisible to recall/dreaming. AD-720d-3 inserts an Episode store
inside that vision branch, before the return.

Tier-2 log-and-degrade — episode failures must NOT block the HTTP reply.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.config import AttachmentsConfig, CognitiveConfig

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
async def chat_client(monkeypatch, tmp_path):
    """FastAPI test client with stub runtime + filesystem attachment store.

    Mirrors the AD-732 chat_client fixture but exposes `episodic_memory` on
    the runtime so the AD-720d-3 episode write can be observed.
    """
    import probos.routers.chat as chat_router_mod
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.routers.deps import (
        get_pending_designs,
        get_runtime,
        get_task_tracker,
        get_ws_broadcast,
    )

    target = tmp_path / "attachments"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "probos.attachments.store._resolve_attachments_dir",
        lambda configured: target,
    )

    cfg_attach = AttachmentsConfig(
        attachments_dir=str(target),
        max_attachment_bytes=10 * 1024 * 1024,
        text_extraction_max_bytes=1024,
        vision_tier="vision",
        pdf_extraction_enabled=False,
    )
    cfg_cognitive = CognitiveConfig(
        llm_base_url_vision="http://127.0.0.1:11434/v1",
        llm_model_vision="llava:34b",
    )

    llm_client = MagicMock()
    llm_client.complete = AsyncMock(
        return_value=SimpleNamespace(
            content="An orange cat on a blue background.",
            tier="vision",
            model="llava:34b",
        ),
    )
    llm_client.get_health_status = MagicMock(
        return_value={
            "tiers": {
                "fast": {"status": "operational"},
                "standard": {"status": "operational"},
                "deep": {"status": "operational"},
                "vision": {"status": "operational"},
            },
            "overall": "operational",
        },
    )

    episodic_memory = MagicMock()
    episodic_memory.store = AsyncMock()

    pnl = AsyncMock(return_value={"final_response": "decomposer", "results": {}, "dag": []})

    rt = SimpleNamespace(
        config=SimpleNamespace(attachments=cfg_attach, cognitive=cfg_cognitive),
        llm_client=llm_client,
        episodic_memory=episodic_memory,
        process_natural_language=pnl,
    )

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()

    a = FastAPI()
    a.include_router(chat_router_mod.router)
    a.dependency_overrides[get_runtime] = lambda: rt
    a.dependency_overrides[get_ws_broadcast] = lambda: (lambda msg: None)
    a.dependency_overrides[get_task_tracker] = lambda: (lambda coro, name="": None)
    a.dependency_overrides[get_pending_designs] = lambda: {}

    store = FilesystemAttachmentStore(target)

    async def _write(blob: bytes, mime: str) -> str:
        sha = hashlib.sha256(blob).hexdigest()
        await store.write(sha, blob, mime)
        return sha

    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, rt, _write

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_vision_path_writes_episode_on_success(chat_client):
    """Successful vision DM writes exactly one Episode with the AD-720d-3 shape."""
    ac, rt, write_blob = chat_client
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    r = await ac.post(
        "/api/chat",
        json={"message": "what is this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text

    rt.episodic_memory.store.assert_called_once()
    episode = rt.episodic_memory.store.call_args.args[0]

    # Outcomes carry the AD-720d-3 vision metadata
    assert len(episode.outcomes) == 1
    outcome = episode.outcomes[0]
    assert outcome["has_image_attachment"] is True
    assert outcome["image_count"] == 1
    assert outcome["attachment_ids"] == [sha]
    assert outcome["llm_tier"] == "vision"
    assert outcome["llm_model"] == "llava:34b"

    # Captain identity on the main composer path
    assert episode.agent_ids == ["captain"]

    # AnchorFrame channel distinguishes this from per-agent DMs
    assert episode.anchors is not None
    assert episode.anchors.channel == "captain_chat"


@pytest.mark.asyncio
async def test_vision_path_does_not_block_on_episode_failure(chat_client):
    """Episode store failure is swallowed; HTTP reply still 200 with content."""
    ac, rt, write_blob = chat_client
    rt.episodic_memory.store = AsyncMock(side_effect=RuntimeError("chroma down"))
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    r = await ac.post(
        "/api/chat",
        json={"message": "what is this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["response"] == "An orange cat on a blue background."


@pytest.mark.asyncio
async def test_vision_path_episode_omitted_when_episodic_memory_unavailable(
    chat_client,
):
    """When runtime has no episodic_memory attribute, no error; reply still 200."""
    ac, rt, write_blob = chat_client
    # Remove the attribute entirely — getattr fallback should produce None.
    del rt.episodic_memory
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    r = await ac.post(
        "/api/chat",
        json={"message": "what is this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["response"] == "An orange cat on a blue background."
