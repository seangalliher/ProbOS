"""AD-746 Layer 1 — VisionAggregator debounce-fusion contract tests.

Real ``SystemConfig`` + real ``FilesystemAttachmentStore`` + real
``IntentBus`` (MagicMock at the bus-method boundary only — the
aggregator calls ``intent_bus.subscribe``).
"""
from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import SystemConfig
from probos.perception.aggregator import VisionAggregator
from probos.perception.consumer import (
    VisionConsumer,
    reset_working_memories_for_tests,
)
from probos.routers.chat import _ATTACHMENT_STORE_CACHE
from probos.types import IntentMessage, LLMResponse


def _make_jpeg(color: tuple[int, int, int]) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), color=color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


async def _store(runtime: Any, frame_bytes: bytes) -> str:
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    sha = hashlib.sha256(frame_bytes).hexdigest()
    await store.write(sha, frame_bytes, "image/jpeg")
    return sha


def _build_runtime(tmp_path: Path) -> Any:
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    cfg.attachments.attachments_dir = str(tmp_path / "attachments")
    runtime.config = cfg
    (tmp_path / "attachments").mkdir(parents=True, exist_ok=True)
    _ATTACHMENT_STORE_CACHE.clear()
    runtime._attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.subscribe = MagicMock(return_value=None)
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock(return_value=None)
    runtime.llm_client = MagicMock()
    runtime.llm_client.complete = AsyncMock(
        return_value=LLMResponse(content="A scene.", model="vision-fake")
    )
    runtime.profile_store = None
    return runtime


@pytest.fixture(autouse=True)
def _reset_state():
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()
    yield
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_single_source_passthrough_after_window(tmp_path: Path) -> None:
    """One source only → after the window expires, the original message
    is forwarded UNCHANGED (no ``fused`` flag, no ``attachment_refs``)."""
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    forwarded: list[IntentMessage] = []
    async def _capture(msg: IntentMessage) -> None:
        forwarded.append(msg)
    consumer._handle = _capture  # type: ignore[assignment]
    agg = VisionAggregator(runtime, consumer, fusion_window_ms=100)
    sha = await _store(runtime, _make_jpeg((10, 10, 10)))
    msg = IntentMessage(intent="vision_observation", params={
        "attachment_ref": sha, "session_id": "s1", "source": "camera",
    })
    await agg._handle(msg)
    await asyncio.sleep(0.2)
    await agg.stop()
    assert len(forwarded) == 1
    assert forwarded[0].params.get("fused", False) is False
    assert forwarded[0].params["attachment_ref"] == sha
    assert "attachment_refs" not in forwarded[0].params


@pytest.mark.asyncio
async def test_two_source_fusion_within_window(tmp_path: Path) -> None:
    """Two sources within the window → one fused message; both refs in
    arrival order; ``fused=True``."""
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    forwarded: list[IntentMessage] = []
    async def _capture(msg: IntentMessage) -> None:
        forwarded.append(msg)
    consumer._handle = _capture  # type: ignore[assignment]
    agg = VisionAggregator(runtime, consumer, fusion_window_ms=500)
    cam_sha = await _store(runtime, _make_jpeg((10, 10, 10)))
    scr_sha = await _store(runtime, _make_jpeg((200, 200, 200)))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": cam_sha, "session_id": "s1", "source": "camera",
    }))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": scr_sha, "session_id": "s1", "source": "screen",
    }))
    await agg.stop()
    assert len(forwarded) == 1
    fused = forwarded[0]
    assert fused.params["fused"] is True
    assert fused.params["attachment_refs"] == [cam_sha, scr_sha]
    assert fused.params["sources"] == ["camera", "screen"]


@pytest.mark.asyncio
async def test_window_expiry_passes_through(tmp_path: Path) -> None:
    """Single frame buffered then window expires → unchanged forward."""
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    forwarded: list[IntentMessage] = []
    async def _capture(msg: IntentMessage) -> None:
        forwarded.append(msg)
    consumer._handle = _capture  # type: ignore[assignment]
    agg = VisionAggregator(runtime, consumer, fusion_window_ms=100)
    sha = await _store(runtime, _make_jpeg((50, 50, 50)))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": sha, "session_id": "s2", "source": "screen",
    }))
    # No second-source frame within the window.
    await asyncio.sleep(0.25)
    await agg.stop()
    assert len(forwarded) == 1
    assert forwarded[0].params.get("fused", False) is False
    assert forwarded[0].params["source"] == "screen"


def test_ad731_invariant_no_inline_base64_in_aggregator() -> None:
    """AD-731 source-scan extended to aggregator.py."""
    import probos.perception.aggregator as _agg_mod
    src_path = Path(_agg_mod.__file__ or "")
    text = src_path.read_text(encoding="utf-8")
    for token in ("b64encode", "base64.b64", "blob_b64"):
        assert token not in text, (
            f"AD-731 violation: aggregator.py contains forbidden {token!r}"
        )


@pytest.mark.asyncio
async def test_fused_observation_counts_as_one_llm_call(tmp_path: Path) -> None:
    """AD-733c-6 budget invariant: a fused two-source observation must
    flow through the consumer as ONE vision-tier call, not two.

    The aggregator only forwards once; the consumer's existing single-
    flight + describe path issues exactly one LLM call per forward.
    Verified by counting forwards (aggregator output == 1).
    """
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    forwarded: list[IntentMessage] = []
    async def _capture(msg: IntentMessage) -> None:
        forwarded.append(msg)
    consumer._handle = _capture  # type: ignore[assignment]
    agg = VisionAggregator(runtime, consumer, fusion_window_ms=300)
    cam_sha = await _store(runtime, _make_jpeg((10, 10, 10)))
    scr_sha = await _store(runtime, _make_jpeg((200, 200, 200)))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": cam_sha, "session_id": "s3", "source": "camera",
    }))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": scr_sha, "session_id": "s3", "source": "screen",
    }))
    await agg.stop()
    assert len(forwarded) == 1


@pytest.mark.asyncio
async def test_primary_ref_preserved_on_fused(tmp_path: Path) -> None:
    """The first-arrived frame's ref is the ``attachment_ref`` (primary
    alias) on the fused message."""
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    forwarded: list[IntentMessage] = []
    async def _capture(msg: IntentMessage) -> None:
        forwarded.append(msg)
    consumer._handle = _capture  # type: ignore[assignment]
    agg = VisionAggregator(runtime, consumer, fusion_window_ms=300)
    scr_sha = await _store(runtime, _make_jpeg((10, 100, 10)))
    cam_sha = await _store(runtime, _make_jpeg((100, 10, 100)))
    # Screen arrives FIRST → primary.
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": scr_sha, "session_id": "s4", "source": "screen",
    }))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": cam_sha, "session_id": "s4", "source": "camera",
    }))
    await agg.stop()
    assert len(forwarded) == 1
    assert forwarded[0].params["attachment_ref"] == scr_sha
    assert forwarded[0].params["source"] == "screen"


@pytest.mark.asyncio
async def test_sources_list_contains_both(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    forwarded: list[IntentMessage] = []
    async def _capture(msg: IntentMessage) -> None:
        forwarded.append(msg)
    consumer._handle = _capture  # type: ignore[assignment]
    agg = VisionAggregator(runtime, consumer, fusion_window_ms=300)
    cam_sha = await _store(runtime, _make_jpeg((30, 30, 30)))
    scr_sha = await _store(runtime, _make_jpeg((180, 180, 180)))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": cam_sha, "session_id": "s5", "source": "camera",
    }))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": scr_sha, "session_id": "s5", "source": "screen",
    }))
    await agg.stop()
    assert set(forwarded[0].params["sources"]) == {"camera", "screen"}


@pytest.mark.asyncio
async def test_sources_list_ordering_deterministic(tmp_path: Path) -> None:
    """Arrival order determines the parallel ordering of refs + sources."""
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    forwarded: list[IntentMessage] = []
    async def _capture(msg: IntentMessage) -> None:
        forwarded.append(msg)
    consumer._handle = _capture  # type: ignore[assignment]
    agg = VisionAggregator(runtime, consumer, fusion_window_ms=300)
    a = await _store(runtime, _make_jpeg((1, 1, 1)))
    b = await _store(runtime, _make_jpeg((250, 0, 0)))
    # screen first, camera second → ['screen','camera'] in fused.
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": a, "session_id": "s6", "source": "screen",
    }))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": b, "session_id": "s6", "source": "camera",
    }))
    await agg.stop()
    assert forwarded[0].params["sources"] == ["screen", "camera"]
    assert forwarded[0].params["attachment_refs"] == [a, b]


@pytest.mark.asyncio
async def test_missing_source_defaults_to_camera(tmp_path: Path) -> None:
    """Legacy intents that omit ``source`` default to ``camera`` (pre-AD-733-2
    behavior). Passthrough preserves the missing field shape."""
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    forwarded: list[IntentMessage] = []
    async def _capture(msg: IntentMessage) -> None:
        forwarded.append(msg)
    consumer._handle = _capture  # type: ignore[assignment]
    agg = VisionAggregator(runtime, consumer, fusion_window_ms=100)
    sha = await _store(runtime, _make_jpeg((40, 40, 40)))
    msg = IntentMessage(intent="vision_observation", params={
        "attachment_ref": sha, "session_id": "s7",
        # No ``source`` field.
    })
    await agg._handle(msg)
    await asyncio.sleep(0.2)
    await agg.stop()
    assert len(forwarded) == 1
    # Passthrough is byte-identical — source key absence preserved.
    assert "source" not in forwarded[0].params


@pytest.mark.asyncio
async def test_cancellation_cleanup(tmp_path: Path) -> None:
    """``stop()`` cancels pending window timers and clears state."""
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    consumer._handle = AsyncMock(return_value=None)  # type: ignore[assignment]
    agg = VisionAggregator(runtime, consumer, fusion_window_ms=5000)
    sha = await _store(runtime, _make_jpeg((90, 90, 90)))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": sha, "session_id": "s8", "source": "camera",
    }))
    assert "s8" in agg._timers
    await agg.stop()
    assert agg._timers == {}
    assert agg._pending == {}


@pytest.mark.asyncio
async def test_bf323_same_source_replacement_does_not_deadlock(tmp_path: Path) -> None:
    """BF-323: multiple same-source frames in a single session must NOT
    deadlock the aggregator. The replacement branch keeps the original
    timer; when it expires, it must forward whatever is currently
    pending (the most-recent replacement), not bail on identity mismatch.

    Pre-BF-323 behavior: after the first same-source replacement, the
    original timer's identity check fired, returned without forwarding,
    and ``_pending`` was stuck forever. All subsequent frames hit the
    "pending != None" branch and never armed a new timer. Zero forwards
    for the entire session — matches the 2026-05-25 field report
    ("sent: 724 / supervisor: 0 described · 0 dropped").
    """
    runtime = _build_runtime(tmp_path)
    consumer = VisionConsumer(runtime)
    forwarded: list[IntentMessage] = []
    async def _capture(msg: IntentMessage) -> None:
        forwarded.append(msg)
    consumer._handle = _capture  # type: ignore[assignment]
    agg = VisionAggregator(runtime, consumer, fusion_window_ms=100)
    sha_a = await _store(runtime, _make_jpeg((10, 20, 30)))
    sha_b = await _store(runtime, _make_jpeg((40, 50, 60)))
    sha_c = await _store(runtime, _make_jpeg((70, 80, 90)))
    # Three same-source frames in rapid succession, all within the
    # 100ms fusion window. F1 arms timer; F2 + F3 replace pending.
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": sha_a, "session_id": "bf323", "source": "camera",
    }))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": sha_b, "session_id": "bf323", "source": "camera",
    }))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": sha_c, "session_id": "bf323", "source": "camera",
    }))
    # Window expires.
    await asyncio.sleep(0.25)
    # Latest frame must have been forwarded (most-recent-wins).
    assert len(forwarded) == 1, (
        f"BF-323 regression: expected 1 forward (latest), got {len(forwarded)}"
    )
    assert forwarded[0].params["attachment_ref"] == sha_c, (
        "BF-323 regression: forwarded frame is not the latest replacement"
    )
    # And ``_pending`` must be cleared so the NEXT frame in this session
    # can arm a fresh timer (the second half of the deadlock).
    assert agg._pending.get("bf323") is None, (
        "BF-323 regression: _pending not cleared after expire — next "
        "frame would hit replacement branch and never arm a timer"
    )
    # Send a fourth frame AFTER the window has expired. It must arm a
    # new timer and forward through the normal path.
    sha_d = await _store(runtime, _make_jpeg((100, 110, 120)))
    await agg._handle(IntentMessage(intent="vision_observation", params={
        "attachment_ref": sha_d, "session_id": "bf323", "source": "camera",
    }))
    await asyncio.sleep(0.25)
    await agg.stop()
    assert len(forwarded) == 2
    assert forwarded[1].params["attachment_ref"] == sha_d
