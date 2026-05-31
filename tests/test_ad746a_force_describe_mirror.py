"""AD-746a (Wave 202f): router-side latest-frame mirror for FORCE DESCRIBE.

``VisionConsumer.record_uploaded_frame`` is a public second writer to the
latest-frame cache, called by the upload router at admission time. It mirrors
the ``_handle`` write so ``force_describe_current_frame`` resolves a warm SHA
even when the VisionAggregator buffers/deadlocks and never reaches ``_handle``
(BF-323).

The force-describe test stubs ``_process`` (AsyncMock) — no live vision model
is invoked; we only assert the synthetic ``IntentMessage`` carries the mirrored
SHA. Mirrors the AD-733c-1 fixture style (real ``SystemConfig`` for
construction; service-level mocks).
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import SystemConfig
from probos.perception.consumer import (
    VisionConsumer,
    _reset_latest_frame_cache_for_tests,
)


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
async def test_force_describe_resolves_mirrored_sha_without_handle() -> None:
    """AD-746a: a frame mirrored via ``record_uploaded_frame`` (NO ``_handle``
    call) is resolvable by ``force_describe_current_frame``. ``_process`` is
    stubbed so no live vision model runs — we assert it received a synthetic
    ``IntentMessage`` carrying the mirrored SHA.
    """
    consumer = _build_consumer()
    captured_at = time.time()
    consumer.record_uploaded_frame("sha123", "s1", captured_at)

    processed: list[Any] = []

    async def _fake_process(msg: Any) -> None:
        processed.append(msg)

    consumer._process = AsyncMock(side_effect=_fake_process)

    await consumer.force_describe_current_frame(session_id="s1", timeout_s=5.0)

    assert len(processed) == 1
    synthetic = processed[0]
    assert synthetic.intent == "vision_observation"
    assert synthetic.params["attachment_ref"] == "sha123"
    assert synthetic.params["force"] is True
