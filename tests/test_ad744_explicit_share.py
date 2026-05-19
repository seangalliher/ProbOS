"""AD-744: Captain-initiated explicit share-to-agent tests.

Verifies the explicit-share gate, the distinct anchor trigger_type, the
BF-302 force-bypass + AD-742c agent_ids fan-out on the share path, and
the AD-731 invariant (refs not blobs) for the screen source code path.
"""
from __future__ import annotations

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
    Image.new("RGB", (4, 4), color=(50, 50, 200)).save(buf, "JPEG", quality=70)
    return buf.getvalue()


def _build_runtime(
    tmp_path: Path,
    *,
    explicit_share_enabled: bool = True,
) -> MagicMock:
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    cfg.perception.camera.enabled = True
    cfg.perception.screen.enabled = True
    cfg.perception.explicit_share_enabled = explicit_share_enabled
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


def test_explicit_share_succeeds_when_enabled(tmp_path: Path) -> None:
    """source=screen + force=true + agent_ids → 200 OK + bound fan-out."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))
    r = client.post(
        "/api/perception/camera/frame",
        files={"file": ("share.jpg", _make_jpeg(), "image/jpeg")},
        data={
            "session_id": "share_e1_123",
            "source": "screen",
            "force": "true",
            "agent_ids": "e1",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "attachment_ref" in body
    # Bus broadcast received the force flag + bound agent + screen source.
    msg = runtime._broadcast_log[-1]
    assert msg.params["force"] is True
    assert msg.params["bound_agent_ids"] == ["e1"]
    assert msg.params["source"] == "screen"


def test_explicit_share_disabled_returns_503(tmp_path: Path) -> None:
    """Master switch off → 503 explicit_share_disabled when force+agent_ids."""
    runtime = _build_runtime(tmp_path, explicit_share_enabled=False)
    client = TestClient(create_app(runtime))
    r = client.post(
        "/api/perception/camera/frame",
        files={"file": ("share.jpg", _make_jpeg(), "image/jpeg")},
        data={
            "session_id": "share_e1_123",
            "source": "screen",
            "force": "true",
            "agent_ids": "e1",
        },
    )
    assert r.status_code == 503
    assert r.json()["error"] == "explicit_share_disabled"


def test_ambient_screen_unaffected_when_share_disabled(tmp_path: Path) -> None:
    """Ambient screen (no force, no agent_ids) still admits with master OFF."""
    runtime = _build_runtime(tmp_path, explicit_share_enabled=False)
    client = TestClient(create_app(runtime))
    r = client.post(
        "/api/perception/camera/frame",
        files={"file": ("scr.jpg", _make_jpeg(), "image/jpeg")},
        data={"session_id": "ambient-1", "source": "screen"},
    )
    assert r.status_code == 200, r.text


def test_operator_preview_force_only_unaffected_when_share_disabled(tmp_path: Path) -> None:
    """force=true alone (no agent_ids) is operator preview — not explicit share."""
    runtime = _build_runtime(tmp_path, explicit_share_enabled=False)
    client = TestClient(create_app(runtime))
    r = client.post(
        "/api/perception/camera/frame",
        files={"file": ("scr.jpg", _make_jpeg(), "image/jpeg")},
        data={
            "session_id": "preview-1",
            "source": "screen",
            "force": "true",
        },
    )
    assert r.status_code == 200, r.text


def test_force_true_propagates_to_bus(tmp_path: Path) -> None:
    """BF-302: force flag carried on the IntentMessage so supervisor bypasses novelty."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))
    r = client.post(
        "/api/perception/camera/frame",
        files={"file": ("share.jpg", _make_jpeg(), "image/jpeg")},
        data={
            "session_id": "share_e1_999",
            "source": "screen",
            "force": "1",
            "agent_ids": "counselor",
        },
    )
    assert r.status_code == 200
    msg = runtime._broadcast_log[-1]
    assert msg.params["force"] is True


def test_anchor_trigger_is_captain_explicit_share(tmp_path: Path) -> None:
    """AD-541b: anchor episode uses distinct trigger_type for share path."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))
    r = client.post(
        "/api/perception/camera/frame",
        files={"file": ("share.jpg", _make_jpeg(), "image/jpeg")},
        data={
            "session_id": "share_e1_anchor",
            "source": "screen",
            "force": "true",
            "agent_ids": "e1",
        },
    )
    assert r.status_code == 200
    assert runtime._stored_episodes, "anchor episode never stored"
    ep = runtime._stored_episodes[-1]
    assert ep.anchors is not None
    assert ep.anchors.trigger_type == "captain_explicit_share"
    # Distinct from AD-733-2 ambient anchor.
    assert ep.anchors.trigger_type != "screen_stream_began"


def test_ad731_no_inline_base64_in_router_after_ad744(tmp_path: Path) -> None:
    """AD-731 source-scan rerun after AD-744 edits."""
    src = Path("src/probos/routers/perception.py").read_text(encoding="utf-8")
    assert "b64encode(" not in src
    assert "base64.b64encode" not in src


def test_share_with_camera_source_also_works(tmp_path: Path) -> None:
    """Share is source-agnostic: camera + force + agent_ids works the same."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))
    r = client.post(
        "/api/perception/camera/frame",
        files={"file": ("cam.jpg", _make_jpeg(), "image/jpeg")},
        data={
            "session_id": "share_e1_cam",
            "source": "camera",
            "force": "true",
            "agent_ids": "e1",
        },
    )
    assert r.status_code == 200
    ep = runtime._stored_episodes[-1]
    assert ep.anchors.trigger_type == "captain_explicit_share"
