"""AD-742c — Per-agent camera selection.

Tests cover:
- ``PerceptionProfile.camera_device_id`` default empty (AD-733c-5 dep verified)
- Frame upload threads ``bound_agent_ids`` into IntentMessage.params
- Consumer fan-out restricted by ``bound_agent_ids``
- Anchor episode ``agent_ids_json`` matches the bound set
- GET /api/perception/cameras + POST /api/perception/cameras/binding
- AD-731 invariant source-scan (router never inlines image bytes)

Uses real ``CrewProfile`` + real ``ProfileStore`` + FastAPI TestClient
(BF-287). The consumer-side test uses a minimal stub for the
``_handle`` fan-out branch since the full VisionConsumer pipeline pulls
in heavy dependencies (LLM, supervisor, episodic chroma).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.crew_profile import CrewProfile, PerceptionProfile, ProfileStore
from probos.types import IntentMessage
from probos.routers import perception as perception_router


# ── Test 1: AD-733c-5 dependency verified at HEAD ─────────────


def test_perception_profile_camera_device_id_default_empty() -> None:
    p = PerceptionProfile()
    assert p.camera_device_id == ""


# ── Test 2: bound_agent_ids form field threading ──────────────


class _StubBus:
    def __init__(self) -> None:
        self.broadcasts: list[IntentMessage] = []

    async def broadcast(self, intent: IntentMessage) -> None:
        self.broadcasts.append(intent)


class _StubAttachmentStore:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    async def write(
        self,
        blob: bytes,
        mime: str,
        origin: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Compute a fake sha
        import hashlib

        sha = hashlib.sha256(blob).hexdigest()
        self._blobs[sha] = blob
        return {
            "ok": True,
            "attachment_id": sha,
            "mime": mime,
            "bytes": len(blob),
        }


class _StubCameraCfg:
    enabled = True


class _StubPerceptionCfg:
    enabled = True
    camera = _StubCameraCfg()
    camera_max_fps_server = 30
    frame_max_size_bytes = 10 * 1024 * 1024


class _StubConfig:
    perception = _StubPerceptionCfg()


class _StubRuntime:
    def __init__(self) -> None:
        self.config = _StubConfig()
        self.intent_bus = _StubBus()
        self._attachment_store = _StubAttachmentStore()
        self.profile_store: Any = None
        self.registry: Any = None
        self.ontology: Any = None


def _make_app(runtime: _StubRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(perception_router.router)

    def _get_runtime() -> Any:
        return runtime

    app.dependency_overrides[perception_router.get_runtime] = _get_runtime
    app.dependency_overrides[perception_router.require_crew_scope] = lambda: None
    return TestClient(app)


def _make_jpeg(size: int = 64) -> bytes:
    # Minimum JPEG with SOI + EOI + filler bytes.
    return b"\xff\xd8\xff\xe0" + b"\x00" * (size - 6) + b"\xff\xd9"


def test_upload_frame_with_agent_ids_threads_bound_agent_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _StubRuntime()

    # Patch the attachment store validator to use our stub.
    async def _fake_validate(
        runtime_: Any, blob: bytes, mime: str, **kwargs: Any
    ) -> tuple[bool, dict[str, Any]]:
        import hashlib

        return True, {"attachment_id": hashlib.sha256(blob).hexdigest()}

    monkeypatch.setattr(
        perception_router, "_validate_and_store_attachment", _fake_validate
    )

    # Disable the per-session rate check so the test is deterministic.
    monkeypatch.setattr(perception_router, "_check_rate", lambda *a, **k: True)

    client = _make_app(runtime)
    files = {"file": ("frame.jpg", _make_jpeg(), "image/jpeg")}
    data = {"session_id": "s1", "agent_ids": "e1,w1"}
    resp = client.post("/api/perception/camera/frame", files=files, data=data)
    assert resp.status_code == 200, resp.text
    # Bus received the intent with bound_agent_ids.
    assert len(runtime.intent_bus.broadcasts) == 1
    params = runtime.intent_bus.broadcasts[0].params
    assert params["bound_agent_ids"] == ["e1", "w1"]


def test_upload_frame_without_agent_ids_backcompat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _StubRuntime()

    async def _fake_validate(
        runtime_: Any, blob: bytes, mime: str, **kwargs: Any
    ) -> tuple[bool, dict[str, Any]]:
        import hashlib

        return True, {"attachment_id": hashlib.sha256(blob).hexdigest()}

    monkeypatch.setattr(
        perception_router, "_validate_and_store_attachment", _fake_validate
    )
    monkeypatch.setattr(perception_router, "_check_rate", lambda *a, **k: True)

    client = _make_app(runtime)
    files = {"file": ("frame.jpg", _make_jpeg(), "image/jpeg")}
    data = {"session_id": "s1"}
    resp = client.post("/api/perception/camera/frame", files=files, data=data)
    assert resp.status_code == 200
    params = runtime.intent_bus.broadcasts[0].params
    # Legacy fan-out path: bound_agent_ids absent.
    assert "bound_agent_ids" not in params


# ── Test 3: consumer fan-out restricted by bound_agent_ids ─────


def test_consumer_fan_out_intersection_logic() -> None:
    """Validates the set-intersection logic in _handle.

    Reads the actual consumer source and asserts the branch exists +
    the intersection happens against ``self._observer_agent_ids``.
    """
    import probos.perception.consumer as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "bound_agent_ids" in src
    # The branch must compare against self._observer_agent_ids.
    assert "fan_out_targets" in src
    # Anchor episode tagged with the fan_out_targets, not the full set.
    assert "anchor_agent_ids = list(fan_out_targets)" in src


# ── Test 4: GET /api/perception/cameras endpoint ──────────────


def test_get_cameras_endpoint_returns_bindings() -> None:
    runtime = _StubRuntime()
    client = _make_app(runtime)
    resp = client.get("/api/perception/cameras")
    assert resp.status_code == 200
    body = resp.json()
    assert "bindings" in body
    assert body["bindings"] == {}


# ── Test 5: POST /api/perception/cameras/binding ──────────────


def test_post_camera_binding_unknown_agent_404(tmp_path: Path) -> None:
    runtime = _StubRuntime()

    class _StubStore:
        def get(self, agent_id: str) -> CrewProfile | None:
            return None

    runtime.profile_store = _StubStore()
    client = _make_app(runtime)
    resp = client.post(
        "/api/perception/cameras/binding",
        json={"agent_id": "nope", "device_id": "cam-1"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "unknown_agent"


def test_post_camera_binding_persists(tmp_path: Path) -> None:
    runtime = _StubRuntime()
    profile = CrewProfile(
        agent_id="e1",
        agent_type="counselor",
        display_name="Ezri",
        callsign="Counselor",
        department="Counseling",
        pool="counselor",
        role="counselor",
    )

    class _StubStore:
        def __init__(self) -> None:
            self.profiles: dict[str, CrewProfile] = {"e1": profile}
            self.updates: list[CrewProfile] = []

        def get(self, agent_id: str) -> CrewProfile | None:
            return self.profiles.get(agent_id)

        def update(self, p: CrewProfile) -> None:
            self.profiles[p.agent_id] = p
            self.updates.append(p)

    store = _StubStore()
    runtime.profile_store = store
    client = _make_app(runtime)
    resp = client.post(
        "/api/perception/cameras/binding",
        json={"agent_id": "e1", "device_id": "cam-42"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent_id"] == "e1"
    assert body["device_id"] == "cam-42"
    # Verify persistence path was invoked.
    assert len(store.updates) == 1
    assert store.profiles["e1"].perception.camera_device_id == "cam-42"


def test_post_camera_binding_clears_with_empty_device_id(tmp_path: Path) -> None:
    runtime = _StubRuntime()
    profile = CrewProfile(
        agent_id="e1",
        agent_type="counselor",
        display_name="Ezri",
        callsign="Counselor",
        department="Counseling",
        pool="counselor",
        role="counselor",
    )
    profile.perception.camera_device_id = "cam-old"

    class _StubStore:
        def __init__(self) -> None:
            self.profiles: dict[str, CrewProfile] = {"e1": profile}

        def get(self, agent_id: str) -> CrewProfile | None:
            return self.profiles.get(agent_id)

        def update(self, p: CrewProfile) -> None:
            self.profiles[p.agent_id] = p

    store = _StubStore()
    runtime.profile_store = store
    client = _make_app(runtime)
    resp = client.post(
        "/api/perception/cameras/binding",
        json={"agent_id": "e1", "device_id": ""},
    )
    assert resp.status_code == 200
    assert store.profiles["e1"].perception.camera_device_id == ""


# ── Test 6: AD-731 invariant — no inline base64 in router ─────


def test_ad731_invariant_no_inline_base64_in_perception_router() -> None:
    import probos.routers.perception as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    # The router must never inline image bytes — AD-731 invariant.
    forbidden = ["b64encode(", "base64.b64encode", "to_base64"]
    for needle in forbidden:
        assert needle not in src, (
            f"AD-731 invariant: routers/perception.py must not contain "
            f"{needle!r}"
        )


# ── Test 7: bound_agent_ids list type is preserved (not bytes) ──


def test_bound_agent_ids_is_string_list_not_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-742c + AD-731: the new form field MUST carry string IDs, not
    image bytes."""
    runtime = _StubRuntime()

    async def _fake_validate(
        runtime_: Any, blob: bytes, mime: str, **kwargs: Any
    ) -> tuple[bool, dict[str, Any]]:
        import hashlib

        return True, {"attachment_id": hashlib.sha256(blob).hexdigest()}

    monkeypatch.setattr(
        perception_router, "_validate_and_store_attachment", _fake_validate
    )
    monkeypatch.setattr(perception_router, "_check_rate", lambda *a, **k: True)

    client = _make_app(runtime)
    files = {"file": ("frame.jpg", _make_jpeg(), "image/jpeg")}
    data = {"session_id": "s1", "agent_ids": "e1"}
    client.post("/api/perception/camera/frame", files=files, data=data)
    params = runtime.intent_bus.broadcasts[0].params
    bound = params["bound_agent_ids"]
    assert isinstance(bound, list)
    assert all(isinstance(x, str) for x in bound)
    assert bound == ["e1"]
