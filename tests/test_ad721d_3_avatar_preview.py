"""AD-721d-3: visual avatar preview endpoint — boundary tests.

Verifies that ``POST /api/agent/{agent_id}/appearance/preview`` renders an
unpersisted ``AvatarDSL`` to a draft VRM and returns a SHA-256
``AttachmentStore`` ref (per the AD-731 refs-not-blobs invariant), with
honest-degrade behaviour when the renderer is unavailable.

Uses a real ``FilesystemAttachmentStore`` (BF-287: no MagicMock at the
attachment-store substrate boundary).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars.dsl import AvatarDSL


# ── Fakes ───────────────────────────────────────────────────────


def _good_dsl_dict() -> dict:
    return AvatarDSL().model_dump()


def _make_runtime(tmp_path: Path, *, avatars_enabled: bool = True, renderer_enabled: bool = True) -> MagicMock:
    runtime = MagicMock()

    agent = MagicMock()
    agent.id = "agent-007"
    agent.agent_type = "counselor"
    agent.pool = "counselor"
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent
    runtime.registry.all.return_value = [agent]

    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Troi"
    runtime.callsign_registry.resolve.return_value = {
        "callsign": "Troi",
        "agent_type": "counselor",
        "agent_id": "agent-007",
        "display_name": "Counselor",
        "department": "bridge",
    }
    runtime.trust_network = MagicMock()
    runtime.trust_network.get_score.return_value = 0.55
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    runtime.profile_store = None
    runtime.emit_event = MagicMock()

    # BF-287: use real Pydantic Config so attribute lookups hit real validation.
    from probos.config import AttachmentsConfig, AvatarsConfig

    avatars_cfg = AvatarsConfig(
        enabled=avatars_enabled,
        avatars_dir=str(tmp_path / "avatars"),
        dsl_drafts_dir=str(tmp_path / "drafts"),
        renderer_enabled=renderer_enabled,
        max_vrm_size_bytes=25 * 1024 * 1024,
    )
    attachments_cfg = AttachmentsConfig(
        enabled=True,
        attachments_dir=str(tmp_path / "attachments"),
    )

    cfg = MagicMock()
    cfg.avatars = avatars_cfg
    cfg.attachments = attachments_cfg
    runtime.config = cfg

    return runtime


@pytest.fixture(autouse=True)
def _clear_attachment_cache():
    """Stop cross-test attachment-store reuse from leaking tmp_path roots."""
    from probos.routers import chat as _chat

    _chat._ATTACHMENT_STORE_CACHE.clear()
    yield
    _chat._ATTACHMENT_STORE_CACHE.clear()


def _make_client(runtime: MagicMock) -> TestClient:
    from probos.api import create_app

    return TestClient(create_app(runtime))


class _StubVRMRenderer:
    """Stand-in for ``BlenderRenderer`` that writes a fixed VRM blob to drafts."""

    def __init__(self, blob: bytes, **kwargs) -> None:
        self._blob = blob
        self._drafts_dir = Path(kwargs["drafts_dir"])

    async def render(self, dsl, agent_id: str) -> Path:  # noqa: ANN001
        self._drafts_dir.mkdir(parents=True, exist_ok=True)
        out = self._drafts_dir / f"{agent_id}.vrm"
        out.write_bytes(self._blob)
        return out


# ── Tests ───────────────────────────────────────────────────────


def test_preview_happy_path_returns_sha256_attachment_ref(tmp_path, monkeypatch):
    import hashlib

    from probos.avatars import blender_renderer as _br_mod

    runtime = _make_runtime(tmp_path)
    blob = b"VRM-FAKE-BYTES-" + b"x" * 64

    def _factory(**kwargs):
        return _StubVRMRenderer(blob, **kwargs)

    monkeypatch.setattr(_br_mod, "BlenderRenderer", _factory, raising=False)

    client = _make_client(runtime)
    resp = client.post(
        "/api/agent/agent-007/appearance/preview",
        json={"dsl": _good_dsl_dict()},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_sha = hashlib.sha256(blob).hexdigest()
    assert body["attachment_id"] == expected_sha
    assert body["agent_id"] == "agent-007"
    assert body["size_bytes"] == len(blob)


def test_preview_avatars_disabled_returns_503(tmp_path):
    runtime = _make_runtime(tmp_path, avatars_enabled=False)
    client = _make_client(runtime)
    resp = client.post(
        "/api/agent/agent-007/appearance/preview",
        json={"dsl": _good_dsl_dict()},
    )
    assert resp.status_code == 503
    assert "avatars feature disabled" in resp.text


def test_preview_agent_missing_returns_404(tmp_path):
    runtime = _make_runtime(tmp_path)
    runtime.registry.get.return_value = None
    client = _make_client(runtime)
    resp = client.post(
        "/api/agent/agent-007/appearance/preview",
        json={"dsl": _good_dsl_dict()},
    )
    assert resp.status_code == 404


def test_preview_invalid_dsl_returns_422_schema_violation(tmp_path):
    runtime = _make_runtime(tmp_path)
    client = _make_client(runtime)
    # palette_hex must be 6-digit hex; supply bogus values to fail validation.
    bad_dsl = {"palette_hex": ["zzzzzz"]}
    resp = client.post(
        "/api/agent/agent-007/appearance/preview",
        json={"dsl": bad_dsl},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["reason"] == "schema_violation"


def test_preview_renderer_disabled_returns_503_renderer_unavailable(tmp_path):
    runtime = _make_runtime(tmp_path, renderer_enabled=False)
    client = _make_client(runtime)
    resp = client.post(
        "/api/agent/agent-007/appearance/preview",
        json={"dsl": _good_dsl_dict()},
    )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["reason"] == "renderer_unavailable"


def test_preview_blender_not_found_returns_503(tmp_path, monkeypatch):
    from probos.avatars import blender_renderer as _br_mod
    from probos.avatars.blender_renderer import BlenderNotFoundError

    runtime = _make_runtime(tmp_path)

    class _BoomRenderer:
        def __init__(self, **_): pass
        async def render(self, dsl, agent_id):
            raise BlenderNotFoundError(configured="", message="blender not installed")

    monkeypatch.setattr(_br_mod, "BlenderRenderer", _BoomRenderer, raising=False)

    client = _make_client(runtime)
    resp = client.post(
        "/api/agent/agent-007/appearance/preview",
        json={"dsl": _good_dsl_dict()},
    )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["reason"] == "blender_not_found"


def test_preview_render_failed_returns_502(tmp_path, monkeypatch):
    from probos.avatars import blender_renderer as _br_mod
    from probos.avatars.blender_renderer import BlenderRenderError

    runtime = _make_runtime(tmp_path)

    class _BoomRenderer:
        def __init__(self, **_): pass
        async def render(self, dsl, agent_id):
            raise BlenderRenderError("subprocess crashed")

    monkeypatch.setattr(_br_mod, "BlenderRenderer", _BoomRenderer, raising=False)

    client = _make_client(runtime)
    resp = client.post(
        "/api/agent/agent-007/appearance/preview",
        json={"dsl": _good_dsl_dict()},
    )
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["reason"] == "render_failed"


def test_preview_attachment_store_contract_real_filesystem(tmp_path, monkeypatch):
    """BF-287: real ``FilesystemAttachmentStore`` — verify the sha returned
    matches a stored blob retrievable by ``read(sha)``.
    """
    import asyncio
    import hashlib

    from probos.avatars import blender_renderer as _br_mod
    from probos.routers import chat as _chat

    runtime = _make_runtime(tmp_path)
    blob = b"VRM-CONTRACT-CHECK-BYTES"

    def _factory(**kwargs):
        return _StubVRMRenderer(blob, **kwargs)

    monkeypatch.setattr(_br_mod, "BlenderRenderer", _factory, raising=False)

    client = _make_client(runtime)
    resp = client.post(
        "/api/agent/agent-007/appearance/preview",
        json={"dsl": _good_dsl_dict()},
    )
    assert resp.status_code == 200, resp.text
    sha = resp.json()["attachment_id"]
    assert sha == hashlib.sha256(blob).hexdigest()

    # Round-trip through the real store: read the stored blob back.
    store = _chat._get_attachment_store(runtime)
    stored_blob = asyncio.get_event_loop().run_until_complete(store.read(sha))
    assert stored_blob == blob
    mime = asyncio.get_event_loop().run_until_complete(store.mime_for(sha))
    assert mime == "model/gltf-binary"
