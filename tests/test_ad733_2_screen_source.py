"""AD-733-2: Passive screen-source frame endpoint tests.

Mirrors test_ad733_frame_endpoint.py shape per BF-287 (real SystemConfig,
real FilesystemAttachmentStore against tmp_path) so AD-731 invariant
assertions verify actual bytes-through-SHA flow.
"""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from probos.api import create_app
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import SystemConfig
from probos.routers import perception as perception_router
from probos.routers.chat import _ATTACHMENT_STORE_CACHE
from probos.types import IntentMessage


def _make_jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(30, 200, 30)).save(buf, "JPEG", quality=70)
    return buf.getvalue()


def _build_runtime(
    tmp_path: Path,
    *,
    perception_enabled: bool = True,
    camera_enabled: bool = True,
    screen_enabled: bool = True,
) -> MagicMock:
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = perception_enabled
    cfg.perception.camera.enabled = camera_enabled
    cfg.perception.screen.enabled = screen_enabled
    cfg.attachments.attachments_dir = str(tmp_path / "attachments")
    runtime.config = cfg
    runtime.config_path = None
    runtime._start_time = 0.0
    (tmp_path / "attachments").mkdir(parents=True, exist_ok=True)
    runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    _ATTACHMENT_STORE_CACHE.clear()
    runtime.intent_bus = MagicMock()
    runtime._broadcast_log: list[IntentMessage] = []

    async def _capture(msg: IntentMessage):
        runtime._broadcast_log.append(msg)
        return []

    runtime.intent_bus.broadcast = AsyncMock(side_effect=_capture)
    runtime.episodic_memory = MagicMock()
    runtime._stored_episodes: list = []

    async def _store(ep):
        runtime._stored_episodes.append(ep)
        return None

    runtime.episodic_memory.store = AsyncMock(side_effect=_store)
    return runtime


@pytest.fixture(autouse=True)
def _reset_perception_state():
    perception_router._reset_state_for_tests()
    yield
    perception_router._reset_state_for_tests()


def test_screen_source_succeeds_when_enabled(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))
    files = {"file": ("scr.jpg", _make_jpeg(), "image/jpeg")}
    r = client.post(
        "/api/perception/camera/frame",
        files=files,
        data={"session_id": "scr-1", "source": "screen"},
    )
    assert r.status_code == 200, r.text
    # AD-733-2: source=screen propagated into broadcast intent.
    assert runtime._broadcast_log, "intent_bus.broadcast was never invoked"
    msg = runtime._broadcast_log[-1]
    assert msg.intent == "vision_observation"
    assert msg.params["source"] == "screen"
    assert "attachment_ref" in msg.params


def test_screen_disabled_returns_503(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path, screen_enabled=False)
    client = TestClient(create_app(runtime))
    files = {"file": ("scr.jpg", _make_jpeg(), "image/jpeg")}
    r = client.post(
        "/api/perception/camera/frame",
        files=files,
        data={"session_id": "scr-1", "source": "screen"},
    )
    assert r.status_code == 503
    assert r.json()["error"] == "screen_disabled"


def test_invalid_source_returns_400(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))
    files = {"file": ("x.jpg", _make_jpeg(), "image/jpeg")}
    r = client.post(
        "/api/perception/camera/frame",
        files=files,
        data={"session_id": "x", "source": "webcam"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_source"


def test_per_source_rate_buckets_isolated(tmp_path: Path) -> None:
    """Rapid screen POSTs do not consume the camera token budget."""
    runtime = _build_runtime(tmp_path)
    # Pinch the screen cap to 1 so the second screen POST exhausts the
    # bucket; the camera POST that follows must still succeed.
    runtime.config.perception.screen_max_fps_server = 1
    runtime.config.perception.camera_max_fps_server = 1
    client = TestClient(create_app(runtime))

    files = {"file": ("scr.jpg", _make_jpeg(), "image/jpeg")}
    # First screen frame admitted.
    r1 = client.post(
        "/api/perception/camera/frame",
        files={"file": ("scr.jpg", _make_jpeg(), "image/jpeg")},
        data={"session_id": "s", "source": "screen"},
    )
    assert r1.status_code == 200
    # Second screen frame rate-limited (same session, same source).
    r2 = client.post(
        "/api/perception/camera/frame",
        files={"file": ("scr.jpg", _make_jpeg(), "image/jpeg")},
        data={"session_id": "s", "source": "screen"},
    )
    assert r2.status_code == 429
    # Camera frame on the SAME session still admits — independent bucket.
    r3 = client.post(
        "/api/perception/camera/frame",
        files={"file": ("cam.jpg", _make_jpeg(), "image/jpeg")},
        data={"session_id": "s", "source": "camera"},
    )
    assert r3.status_code == 200, r3.text


def test_screen_anchor_episode_distinct_trigger_type(tmp_path: Path) -> None:
    """AD-541b: first screen frame writes screen_stream_began anchor."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))
    files = {"file": ("scr.jpg", _make_jpeg(), "image/jpeg")}
    r = client.post(
        "/api/perception/camera/frame",
        files=files,
        data={"session_id": "ses-anchor", "source": "screen"},
    )
    assert r.status_code == 200
    assert runtime._stored_episodes, "anchor episode never stored"
    ep = runtime._stored_episodes[-1]
    assert ep.anchors is not None
    assert ep.anchors.trigger_type == "screen_stream_began"
    # Source recorded in outcome too.
    assert ep.outcomes and ep.outcomes[0]["source"] == "screen"


def test_ad731_no_inline_base64_in_router_after_ad7332(tmp_path: Path) -> None:
    """AD-731 source-scan: no base64-of-bytes encoding in perception.py."""
    src = Path("src/probos/routers/perception.py").read_text(encoding="utf-8")
    # b64encode of bytes (image payload) — not present.
    assert "b64encode(" not in src
    # base64.b64encode prefix — not present.
    assert "base64.b64encode" not in src


def test_bound_agent_ids_works_with_screen_source(tmp_path: Path) -> None:
    """Regression: agent_ids form field works alongside source=screen."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))
    r = client.post(
        "/api/perception/camera/frame",
        files={"file": ("scr.jpg", _make_jpeg(), "image/jpeg")},
        data={
            "session_id": "ses-bind",
            "source": "screen",
            "agent_ids": "counselor,medical",
        },
    )
    assert r.status_code == 200, r.text
    msg = runtime._broadcast_log[-1]
    assert msg.params["source"] == "screen"
    assert msg.params["bound_agent_ids"] == ["counselor", "medical"]


def test_camera_source_flow_byte_compatible(tmp_path: Path) -> None:
    """Regression: omitting source defaults to camera; existing flow intact."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))
    # No source field => defaults to "camera".
    r = client.post(
        "/api/perception/camera/frame",
        files={"file": ("cam.jpg", _make_jpeg(), "image/jpeg")},
        data={"session_id": "ses-cam-only"},
    )
    assert r.status_code == 200
    msg = runtime._broadcast_log[-1]
    assert msg.params["source"] == "camera"
    # Anchor remains camera_stream_began.
    ep = runtime._stored_episodes[-1]
    assert ep.anchors.trigger_type == "camera_stream_began"
