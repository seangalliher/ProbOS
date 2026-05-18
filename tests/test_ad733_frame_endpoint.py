"""AD-733: Camera frame endpoint tests.

BF-287: real ``SystemConfig()`` so every defense-in-depth gate hits real
Pydantic; real ``FilesystemAttachmentStore`` against ``tmp_path`` so the
AD-731 invariant assertion verifies bytes actually flow through SHA-256.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

from probos.api import create_app
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import SystemConfig
from probos.routers import perception as perception_router
from probos.routers.chat import _ATTACHMENT_STORE_CACHE
from probos.types import IntentMessage


# Minimal valid JPEG is constructed at test time via PIL (already a ProbOS dep).


def _make_jpeg(size_pad: int = 0) -> bytes:
    """Return a valid JPEG (PIL.Image 4x4 red) padded to at least ``size_pad`` bytes."""
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(200, 30, 30)).save(buf, "JPEG", quality=70)
    data = buf.getvalue()
    if size_pad and len(data) < size_pad:
        # JPEGs tolerate trailing bytes after EOI; AD-720 magic check only looks at the prefix.
        data = data + b"\x00" * (size_pad - len(data))
    return data


def _build_runtime(tmp_path: Path, *, perception_enabled: bool = True, camera_enabled: bool = True) -> MagicMock:
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = perception_enabled
    cfg.perception.camera.enabled = camera_enabled
    cfg.attachments.attachments_dir = str(tmp_path / "attachments")
    runtime.config = cfg
    runtime.config_path = None
    runtime._start_time = 0.0

    # Real FilesystemAttachmentStore (AD-731 invariant verifier).
    (tmp_path / "attachments").mkdir(parents=True, exist_ok=True)
    runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    _ATTACHMENT_STORE_CACHE.clear()

    # IntentBus broadcast captured so AD-731 assertion can inspect params.
    runtime.intent_bus = MagicMock()
    runtime._broadcast_log: list[IntentMessage] = []

    async def _capture(msg: IntentMessage):
        runtime._broadcast_log.append(msg)
        return []

    runtime.intent_bus.broadcast = AsyncMock(side_effect=_capture)
    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock(return_value=None)
    return runtime


@pytest.fixture(autouse=True)
def _reset_perception_state():
    perception_router._reset_state_for_tests()
    yield
    perception_router._reset_state_for_tests()


def test_perception_disabled_returns_503(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path, perception_enabled=False)
    client = TestClient(create_app(runtime))
    files = {"file": ("frame.jpg", _make_jpeg(), "image/jpeg")}
    r = client.post("/api/perception/camera/frame", files=files, data={"session_id": "abc"})
    assert r.status_code == 503
    assert r.json()["error"] == "perception_disabled"


def test_camera_disabled_returns_503(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path, camera_enabled=False)
    client = TestClient(create_app(runtime))
    files = {"file": ("frame.jpg", _make_jpeg(), "image/jpeg")}
    r = client.post("/api/perception/camera/frame", files=files, data={"session_id": "abc"})
    assert r.status_code == 503
    assert r.json()["error"] == "camera_disabled"


def test_valid_frame_stores_and_returns_sha(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))

    files = {"file": ("frame.jpg", _make_jpeg(), "image/jpeg")}
    r = client.post("/api/perception/camera/frame", files=files, data={"session_id": "sess-1"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert re.fullmatch(r"[0-9a-f]{64}", body["attachment_ref"])
    assert body["captured_at"] > 0


def test_broadcast_carries_only_ref_no_inline_blob(tmp_path: Path) -> None:
    """AD-731 invariant: IntentMessage.params must not carry image bytes."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))

    files = {"file": ("frame.jpg", _make_jpeg(), "image/jpeg")}
    r = client.post("/api/perception/camera/frame", files=files, data={"session_id": "sess-2"})
    assert r.status_code == 200

    assert len(runtime._broadcast_log) == 1
    msg = runtime._broadcast_log[0]
    assert msg.intent == "vision_observation"
    allowed_keys = {"attachment_ref", "mime", "captured_at", "source", "session_id"}
    assert set(msg.params.keys()) <= allowed_keys
    # Belt-and-suspenders: no key whose value is a long string (>128 chars =
    # likely base64 blob — the SHA is exactly 64 hex chars).
    for key, val in msg.params.items():
        if isinstance(val, str) and len(val) > 128:
            pytest.fail(f"AD-731 violation: params[{key!r}] looks like a blob ({len(val)} chars)")


def test_rate_limit_triggers_429(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    runtime.config.perception.camera_max_fps_server = 2
    client = TestClient(create_app(runtime))

    files_factory = lambda: {"file": ("frame.jpg", _make_jpeg(), "image/jpeg")}
    statuses: list[int] = []
    for _ in range(5):
        r = client.post(
            "/api/perception/camera/frame",
            files=files_factory(),
            data={"session_id": "burst"},
        )
        statuses.append(r.status_code)
        if r.status_code == 429:
            assert r.headers.get("Retry-After") == "1"
    assert 429 in statuses, f"Expected at least one 429 in {statuses}"


def test_frame_too_large_returns_413(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    runtime.config.perception.frame_max_size_bytes = 4096
    client = TestClient(create_app(runtime))

    big = _make_jpeg(size_pad=8192)
    files = {"file": ("frame.jpg", big, "image/jpeg")}
    r = client.post("/api/perception/camera/frame", files=files, data={"session_id": "sess-big"})
    assert r.status_code == 413
    assert r.json()["error"] == "frame_too_large"


def test_router_source_has_no_inline_blob_patterns() -> None:
    """AD-731 source-scan — the router must NEVER inline base64.

    BF-278 + AD-732 8-guard catalog: future maintenance prompts that drift
    toward Anthropic-shape ``source.base64`` or any other inline byte
    pattern in :class:`IntentMessage.params` are blocked at the source.
    """
    src = Path("src/probos/routers/perception.py").read_text(encoding="utf-8")
    forbidden = ("b64encode", "base64.b64", "b64decode", "\"blob_b64\"", "'blob_b64'", "\"blob\"")
    for pattern in forbidden:
        assert pattern not in src, (
            f"AD-731 violation: {pattern!r} appears in routers/perception.py — "
            "frames must be referenced by SHA only."
        )


def test_anchor_episode_written_on_first_frame_per_session(tmp_path: Path) -> None:
    """AD-541b: high-importance anchored episode marks camera-stream-began."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))

    files = {"file": ("frame.jpg", _make_jpeg(), "image/jpeg")}
    r1 = client.post("/api/perception/camera/frame", files=files, data={"session_id": "anchored"})
    assert r1.status_code == 200

    assert runtime.episodic_memory.store.await_count == 1
    episode = runtime.episodic_memory.store.await_args.args[0]
    assert episode.importance == 8
    assert episode.anchors is not None
    assert episode.anchors.trigger_type == "camera_stream_began"

    # Second frame in the SAME session must NOT write a second anchor.
    r2 = client.post(
        "/api/perception/camera/frame",
        files={"file": ("frame.jpg", _make_jpeg(), "image/jpeg")},
        data={"session_id": "anchored"},
    )
    assert r2.status_code == 200
    assert runtime.episodic_memory.store.await_count == 1
