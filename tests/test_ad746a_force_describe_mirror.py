"""AD-746a (Wave 202f): router-side latest-frame mirror for FORCE DESCRIBE.

``VisionConsumer.record_uploaded_frame`` is a public second writer to the
latest-frame cache, called by the upload router at admission time. It mirrors
the ``_handle`` write so ``force_describe_current_frame`` resolves a warm SHA
even when the VisionAggregator buffers/deadlocks and never reaches ``_handle``
(BF-323).

The force-describe test stubs ``_process`` with an annotated async callable — no live vision model
is invoked; we only assert the synthetic ``IntentMessage`` carries the mirrored
SHA. Mirrors the AD-733c-1 fixture style (real ``SystemConfig`` for
construction; service-level mocks).
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from probos.config import SystemConfig
from probos.perception.consumer import (
    VisionConsumer,
    _reset_latest_frame_cache_for_tests,
)
from probos.perception.working_memory import VisionObservation
from probos.routers.chat import _ATTACHMENT_STORE_CACHE
from probos.types import IntentMessage


_Candidate = tuple[str, float]


@pytest.fixture(autouse=True)
def _reset_attachment_store_cache() -> None:
    _ATTACHMENT_STORE_CACHE.clear()
    try:
        yield
    finally:
        _ATTACHMENT_STORE_CACHE.clear()


def _build_consumer() -> VisionConsumer:
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    runtime.config = cfg
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    _reset_latest_frame_cache_for_tests(consumer)
    return consumer


def test_record_uploaded_frame_populates_both_caches() -> None:
    consumer = _build_consumer()
    captured_at = time.time()

    consumer.record_uploaded_frame("sha123", "s1", captured_at)

    assert consumer._latest_frame_by_session["s1"] == ("sha123", captured_at)
    assert consumer._latest_frame_global == ("sha123", captured_at)


def test_record_uploaded_frame_empty_sha_is_noop() -> None:
    consumer = _build_consumer()

    consumer.record_uploaded_frame("", "s1", time.time())

    assert consumer._latest_frame_by_session == {}
    assert consumer._latest_frame_global is None


@pytest.mark.asyncio
async def test_force_describe_resolves_mirrored_sha_without_handle(
    tmp_path: Path,
) -> None:
    """AD-746a: a frame mirrored via ``record_uploaded_frame`` (NO ``_handle``
    call) is resolvable by ``force_describe_current_frame``. ``_process`` is
    stubbed so no live vision model runs — we assert it received a synthetic
    ``IntentMessage`` carrying the mirrored SHA.
    """
    from probos.routers.chat import _get_attachment_store

    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    cfg.attachments.attachments_dir = str(tmp_path / "attachments")
    runtime.config = cfg
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    _reset_latest_frame_cache_for_tests(consumer)
    frame_bytes = b"\xff\xd8\xff" + b"bf-666-real-frame" * 8
    sha = hashlib.sha256(frame_bytes).hexdigest()
    store = _get_attachment_store(runtime)
    await store.write(sha, frame_bytes, "image/jpeg", origin="perception_frame")
    captured_at = time.time()
    consumer.record_uploaded_frame(sha, "s1", captured_at)

    processed: list[tuple[IntentMessage, _Candidate | None]] = []

    async def _fake_process(
        msg: IntentMessage,
        *,
        cache_candidate: _Candidate | None = None,
    ) -> VisionObservation | None:
        processed.append((msg, cache_candidate))
        return None

    consumer._process = _fake_process  # type: ignore[method-assign]

    await consumer.force_describe_current_frame(session_id="s1", timeout_s=5.0)

    assert len(processed) == 1
    synthetic, cache_candidate = processed[0]
    assert synthetic.intent == "vision_observation"
    assert synthetic.params["attachment_ref"] == sha
    assert synthetic.params["force"] is True
    assert cache_candidate == (sha, captured_at)
