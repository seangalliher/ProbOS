"""AD-721h: Captain-driven VRM upload — boundary tests.

Tests the multipart endpoint that lets the Captain drag a custom ``.vrm``
into the HXI. Validates glTF magic-byte security check, size cap, dual-write
(content-addressed AttachmentStore + named avatar cache per AD-731 invariant),
and ``ProfileStore.vrm_url`` persistence.

Real ``FilesystemAttachmentStore`` + real ``tmp_path`` avatars_dir per BF-287.
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.crew_profile import AppearanceProfile, CrewProfile


# ── Fakes ───────────────────────────────────────────────────────


class _ProfileStoreFake:
    def __init__(self) -> None:
        self.profiles: dict[str, CrewProfile] = {}

    def get(self, agent_id: str):
        return self.profiles.get(agent_id)

    def get_or_create(self, agent_id: str, agent_type: str = "", pool: str = "", **_):
        if agent_id in self.profiles:
            return self.profiles[agent_id]
        crew = CrewProfile(agent_id=agent_id, agent_type=agent_type, pool=pool)
        self.profiles[agent_id] = crew
        return crew

    def update(self, profile: CrewProfile) -> None:
        self.profiles[profile.agent_id] = profile


def _make_runtime(tmp_path: Path, *, avatars_enabled: bool = True, max_bytes: int = 25 * 1024 * 1024) -> MagicMock:
    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "agent-007"
    agent.agent_type = "engineer"
    agent.pool = "engineering"
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent
    runtime.registry.all.return_value = [agent]
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Echo"
    runtime.callsign_registry.resolve.return_value = {
        "callsign": "Echo",
        "agent_type": "engineer",
        "agent_id": "agent-007",
        "display_name": "Engineer",
        "department": "engineering",
    }
    runtime.trust_network = MagicMock()
    runtime.trust_network.get_score.return_value = 0.5
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
    runtime.profile_store = _ProfileStoreFake()
    runtime.emit_event = MagicMock()

    from probos.config import AttachmentsConfig, AvatarsConfig

    avatars_cfg = AvatarsConfig(
        enabled=avatars_enabled,
        avatars_dir=str(tmp_path / "avatars"),
        max_vrm_size_bytes=max_bytes,
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
    from probos.routers import chat as _chat
    _chat._ATTACHMENT_STORE_CACHE.clear()
    yield
    _chat._ATTACHMENT_STORE_CACHE.clear()


def _make_client(runtime: MagicMock) -> TestClient:
    from probos.api import create_app
    return TestClient(create_app(runtime))


def _gltf_blob(size: int = 256) -> bytes:
    """A blob that passes the magic-byte check + minimum-size gate."""
    body = b"glTF" + bytes(size - 4)
    return body


# ── Tests ───────────────────────────────────────────────────────


def test_upload_vrm_happy_path_writes_named_cache_and_updates_profile(tmp_path):
    import hashlib

    runtime = _make_runtime(tmp_path)
    client = _make_client(runtime)
    blob = _gltf_blob(512)
    files = {"file": ("custom.vrm", io.BytesIO(blob), "application/octet-stream")}
    resp = client.post("/api/agent/agent-007/appearance/vrm", files=files)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_sha = hashlib.sha256(blob).hexdigest()
    assert body["attachment_id"] == expected_sha
    assert body["vrm_url"] == "agent-007.vrm"
    assert body["bytes"] == len(blob)

    # Named cache file exists with the right bytes.
    named = tmp_path / "avatars" / "agent-007.vrm"
    assert named.exists()
    assert named.read_bytes() == blob

    # ProfileStore vrm_url updated.
    crew = runtime.profile_store.get("agent-007")
    assert crew is not None
    assert crew.appearance.vrm_url == "agent-007.vrm"


def test_upload_vrm_avatars_disabled_returns_503(tmp_path):
    runtime = _make_runtime(tmp_path, avatars_enabled=False)
    client = _make_client(runtime)
    files = {"file": ("custom.vrm", io.BytesIO(_gltf_blob()), "application/octet-stream")}
    resp = client.post("/api/agent/agent-007/appearance/vrm", files=files)
    assert resp.status_code == 503


def test_upload_vrm_agent_missing_returns_404(tmp_path):
    runtime = _make_runtime(tmp_path)
    runtime.registry.get.return_value = None
    client = _make_client(runtime)
    files = {"file": ("custom.vrm", io.BytesIO(_gltf_blob()), "application/octet-stream")}
    resp = client.post("/api/agent/agent-007/appearance/vrm", files=files)
    assert resp.status_code == 404


def test_upload_vrm_too_large_returns_413(tmp_path):
    runtime = _make_runtime(tmp_path, max_bytes=100)
    client = _make_client(runtime)
    # 200 bytes > 100 cap.
    files = {"file": ("custom.vrm", io.BytesIO(_gltf_blob(200)), "application/octet-stream")}
    resp = client.post("/api/agent/agent-007/appearance/vrm", files=files)
    assert resp.status_code == 413
    assert resp.json()["detail"]["reason"] == "too_large"


def test_upload_vrm_too_small_returns_400(tmp_path):
    runtime = _make_runtime(tmp_path)
    client = _make_client(runtime)
    files = {"file": ("custom.vrm", io.BytesIO(b"glTF"), "application/octet-stream")}
    resp = client.post("/api/agent/agent-007/appearance/vrm", files=files)
    assert resp.status_code == 400
    assert resp.json()["detail"]["reason"] == "too_small"


def test_upload_vrm_missing_gltf_magic_returns_415(tmp_path):
    """Security: reject non-glTF blobs BEFORE storage."""
    runtime = _make_runtime(tmp_path)
    client = _make_client(runtime)
    # Plausible 256-byte blob without glTF magic.
    bogus = b"PNG\x00" + bytes(252)
    files = {"file": ("evil.png", io.BytesIO(bogus), "application/octet-stream")}
    resp = client.post("/api/agent/agent-007/appearance/vrm", files=files)
    assert resp.status_code == 415
    assert resp.json()["detail"]["reason"] == "not_a_vrm"

    # Defense-in-depth: nothing landed on disk.
    named = tmp_path / "avatars" / "agent-007.vrm"
    assert not named.exists()


def test_upload_vrm_dual_write_attachment_and_named_cache_have_identical_bytes(tmp_path):
    """AD-731 invariant: AttachmentStore copy + named cache must match exactly."""
    import asyncio
    import hashlib

    runtime = _make_runtime(tmp_path)
    client = _make_client(runtime)
    blob = _gltf_blob(1024)
    files = {"file": ("custom.vrm", io.BytesIO(blob), "application/octet-stream")}
    resp = client.post("/api/agent/agent-007/appearance/vrm", files=files)
    assert resp.status_code == 200, resp.text
    sha = resp.json()["attachment_id"]
    assert sha == hashlib.sha256(blob).hexdigest()

    from probos.routers import chat as _chat
    store = _chat._get_attachment_store(runtime)
    stored = asyncio.new_event_loop().run_until_complete(store.read(sha))
    named = (tmp_path / "avatars" / "agent-007.vrm").read_bytes()
    assert stored == named == blob


def test_upload_vrm_last_write_wins_overwrites_named_cache(tmp_path):
    """Concurrent uploads end with the LAST blob persisted (os.replace atomic)."""
    runtime = _make_runtime(tmp_path)
    client = _make_client(runtime)

    first = _gltf_blob(256)
    second = b"glTF" + b"\x01" * 252  # different bytes, still valid magic

    files1 = {"file": ("a.vrm", io.BytesIO(first), "application/octet-stream")}
    files2 = {"file": ("b.vrm", io.BytesIO(second), "application/octet-stream")}

    r1 = client.post("/api/agent/agent-007/appearance/vrm", files=files1)
    r2 = client.post("/api/agent/agent-007/appearance/vrm", files=files2)
    assert r1.status_code == 200
    assert r2.status_code == 200

    named = (tmp_path / "avatars" / "agent-007.vrm").read_bytes()
    assert named == second
    # No tmp file leaked.
    assert not (tmp_path / "avatars" / "agent-007.vrm.tmp").exists()
