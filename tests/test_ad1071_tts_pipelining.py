"""AD-1071 — Sentence-chunked TTS pipelining (voice edge): config + status.

v1 is the SAFE sentence-pipelining slice: DEFAULT-OFF. These tests lock the
config default (``sentence_pipelining_enabled is False``) and prove that the
``GET /api/avatars/tts/status`` probe surfaces the flag so the browser can
read it via its existing one-time status probe. Full LLM streaming is
explicitly out of scope for v1.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.config import AttachmentsConfig, LipSyncConfig, TTSConfig
from probos.routers.deps import get_runtime
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod


# ---------------------------------------------------------------------------
# Config default (DEFAULT-OFF is the load-bearing guarantee)
# ---------------------------------------------------------------------------


def test_config_default_sentence_pipelining_is_false():
    # DEFAULT-OFF: an operator who does nothing gets today's one-call-per-reply
    # behaviour (byte-identical). Opting in requires an explicit flag flip.
    assert TTSConfig().sentence_pipelining_enabled is False


def test_config_opt_in_sets_flag_true():
    assert TTSConfig(sentence_pipelining_enabled=True).sentence_pipelining_enabled is True


# ---------------------------------------------------------------------------
# Status endpoint surfaces the flag
# ---------------------------------------------------------------------------


@pytest.fixture
async def avatar_client(monkeypatch, tmp_path):
    target = tmp_path / "attachments"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "probos.attachments.store._resolve_attachments_dir",
        lambda configured: target,
    )

    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=AttachmentsConfig(attachments_dir=str(target)),
            lipsync=LipSyncConfig(),
            tts=TTSConfig(),  # browser default, pipelining OFF
        ),
    )

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()

    a = FastAPI()
    a.include_router(avatars_router_mod.router)
    a.dependency_overrides[get_runtime] = lambda: rt

    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, rt

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_status_surfaces_pipelining_false_by_default(avatar_client):
    ac, _rt = avatar_client
    resp = await ac.get("/api/avatars/tts/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sentence_pipelining_enabled"] is False
    # Mirrors the existing enabled/backend surface (unchanged).
    assert body["enabled"] is True
    assert body["backend"] == "browser"


@pytest.mark.asyncio
async def test_status_surfaces_pipelining_true_when_opted_in(avatar_client):
    ac, rt = avatar_client
    rt.config.tts = TTSConfig(backend="piper", sentence_pipelining_enabled=True)
    resp = await ac.get("/api/avatars/tts/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sentence_pipelining_enabled"] is True
    assert body["backend"] == "piper"


@pytest.mark.asyncio
async def test_status_pipelining_false_when_tts_attr_missing(monkeypatch, tmp_path):
    # Honest-degrade: a config without a ``tts`` block must still report the
    # flag as False (the browser then never pipelines).
    target = tmp_path / "attachments"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "probos.attachments.store._resolve_attachments_dir",
        lambda configured: target,
    )
    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=AttachmentsConfig(attachments_dir=str(target)),
            lipsync=LipSyncConfig(),
            # Note: NO tts attr.
        ),
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    a = FastAPI()
    a.include_router(avatars_router_mod.router)
    a.dependency_overrides[get_runtime] = lambda: rt
    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/avatars/tts/status")
    assert resp.status_code == 200
    assert resp.json()["sentence_pipelining_enabled"] is False
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
