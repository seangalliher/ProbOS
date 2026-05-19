"""AD-733-1: camera frame upload tags origin=perception_frame."""

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
from probos.routers.chat import _ATTACHMENT_STORE_CACHE, _get_attachment_store
from probos.types import IntentMessage


def _make_jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(120, 200, 80)).save(buf, "JPEG", quality=70)
    return buf.getvalue()


def _make_png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(30, 30, 200)).save(buf, "PNG")
    return buf.getvalue()


def _build_runtime(tmp_path: Path) -> MagicMock:
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    cfg.perception.camera.enabled = True
    cfg.attachments.attachments_dir = str(tmp_path / "attachments")
    runtime.config = cfg
    runtime.config_path = None
    runtime._start_time = 0.0

    (tmp_path / "attachments").mkdir(parents=True, exist_ok=True)
    _ATTACHMENT_STORE_CACHE.clear()

    runtime.intent_bus = MagicMock()
    runtime.intent_bus.broadcast = AsyncMock(side_effect=lambda _msg: [])
    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock(return_value=None)
    return runtime


@pytest.fixture(autouse=True)
def _reset_perception_state():
    perception_router._reset_state_for_tests()
    yield
    perception_router._reset_state_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()


def test_camera_frame_tags_origin_perception_frame(tmp_path: Path) -> None:
    """AD-733-1: POST /api/perception/camera/frame writes origin=perception_frame."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))

    files = {"file": ("frame.jpg", _make_jpeg(), "image/jpeg")}
    r = client.post(
        "/api/perception/camera/frame",
        files=files,
        data={"session_id": "ad733-1-origin"},
    )
    assert r.status_code == 200, r.text
    sha = r.json()["attachment_ref"]

    store = _get_attachment_store(runtime)
    assert isinstance(store, FilesystemAttachmentStore)
    # Index entry tags it as perception_frame.
    entry = store._index[sha]  # noqa: SLF001
    assert entry["origin"] == "perception_frame"

    # list_by_origin sees it under perception_frame and NOT chat_attachment.
    import asyncio
    rows_p = asyncio.run(store.list_by_origin("perception_frame"))
    rows_c = asyncio.run(store.list_by_origin("chat_attachment"))
    assert sha in [r[0] for r in rows_p]
    assert sha not in [r[0] for r in rows_c]


def test_chat_paste_defaults_to_chat_attachment(tmp_path: Path) -> None:
    """AD-733-1 regression: chat-paste path keeps origin=chat_attachment."""
    runtime = _build_runtime(tmp_path)
    client = TestClient(create_app(runtime))

    import base64
    import hashlib
    png_bytes = _make_png()
    payload = {
        "blob_b64": base64.b64encode(png_bytes).decode("ascii"),
        "mime": "image/png",
        "content_hash": hashlib.sha256(png_bytes).hexdigest(),
    }
    r = client.post("/api/chat/attachments", json=payload)
    assert r.status_code == 200, r.text
    sha = r.json()["sha256"]

    store = _get_attachment_store(runtime)
    assert isinstance(store, FilesystemAttachmentStore)
    entry = store._index[sha]  # noqa: SLF001
    assert entry["origin"] == "chat_attachment"
