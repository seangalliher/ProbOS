"""AD-742e: vision LLM call budget telemetry tests.

BF-286/287: real Pydantic config + real consumer (no MagicMock at substrate boundary).
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from probos.config import SystemConfig
from probos.perception.consumer import VisionConsumer


class _FakeRuntime:
    def __init__(self) -> None:
        self.config = SystemConfig()
        self.llm_client = None  # not used in these tests


def _make_consumer() -> VisionConsumer:
    return VisionConsumer(_FakeRuntime())


# -- 1. Initial state ---------------------------------------------------------


def test_consumer_starts_with_zero_counters() -> None:
    consumer = _make_consumer()
    snap = consumer.get_budget_snapshot()
    assert snap["calls_this_session"] == {"vision": 0, "vision_fast": 0}
    assert snap["calls_today"] == {"vision": 0, "vision_fast": 0}
    assert snap["total_session"] == 0
    assert snap["total_today"] == 0


# -- 2. Counter increment -----------------------------------------------------


def test_record_vision_call_increments_session_and_today() -> None:
    consumer = _make_consumer()
    consumer._record_vision_call("vision", "sess1")
    consumer._record_vision_call("vision", "sess1")
    snap = consumer.get_budget_snapshot()
    assert snap["calls_this_session"]["vision"] == 2
    assert snap["calls_today"]["vision"] == 2
    assert snap["total_session"] == 2


def test_record_vision_call_tracks_per_tier() -> None:
    consumer = _make_consumer()
    consumer._record_vision_call("vision", "sess1")
    consumer._record_vision_call("vision_fast", "sess1")
    consumer._record_vision_call("vision_fast", "sess1")
    snap = consumer.get_budget_snapshot()
    assert snap["calls_this_session"]["vision"] == 1
    assert snap["calls_this_session"]["vision_fast"] == 2


# -- 3. Session reset ---------------------------------------------------------


def test_record_vision_call_resets_on_session_change() -> None:
    consumer = _make_consumer()
    consumer._record_vision_call("vision", "sess1")
    consumer._record_vision_call("vision", "sess1")
    consumer._record_vision_call("vision", "sess2")
    snap = consumer.get_budget_snapshot()
    # New session: counter reset to 1
    assert snap["calls_this_session"]["vision"] == 1
    # Today counter spans sessions
    assert snap["calls_today"]["vision"] == 3


# -- 4. Date rollover ---------------------------------------------------------


def test_record_vision_call_resets_on_date_rollover() -> None:
    consumer = _make_consumer()

    class _FakeDT:
        _now = "2026-05-18"

        @classmethod
        def now(cls, tz: Any = None) -> Any:
            class _DT:
                @staticmethod
                def strftime(fmt: str) -> str:
                    return _FakeDT._now

            return _DT()

    # datetime is imported inside _record_vision_call (local-scope) — patch the
    # source module so the local import picks up the fake.
    with patch("datetime.datetime", _FakeDT):
        consumer._record_vision_call("vision", "sess1")
        consumer._record_vision_call("vision", "sess1")
        assert consumer.get_budget_snapshot()["calls_today"]["vision"] == 2
        # Roll the date forward.
        _FakeDT._now = "2026-05-19"
        consumer._record_vision_call("vision", "sess1")
        snap = consumer.get_budget_snapshot()
        # Today counter reset on date rollover.
        assert snap["calls_today"]["vision"] == 1


# -- 5. Snapshot shape --------------------------------------------------------


def test_get_budget_snapshot_shape() -> None:
    consumer = _make_consumer()
    consumer._record_vision_call("vision_fast", "sess1")
    snap = consumer.get_budget_snapshot()
    required_keys = {
        "session_id",
        "calls_this_session",
        "calls_today",
        "total_session",
        "total_today",
        "session_ceiling_estimate",
        "next_allowed_in_seconds",
    }
    assert required_keys.issubset(snap.keys())
    assert isinstance(snap["calls_this_session"], dict)
    assert isinstance(snap["next_allowed_in_seconds"], float)
    # AD-733c-6 (Wave 175): session_ceiling_estimate now maps to
    # cap_per_session (default 200). AD-742e backcompat key retained.
    assert snap["session_ceiling_estimate"] == 200


# -- 6. API endpoint ----------------------------------------------------------


def test_api_endpoint_returns_snapshot_shape_when_consumer_unwired() -> None:
    """GET /api/perception/budget returns honest-degrade shape when consumer is None."""
    import inspect
    from probos.routers import perception as _perception_router

    # Verify the function exists with the right signature.
    fn = getattr(_perception_router, "get_vision_budget", None)
    assert fn is not None
    sig = inspect.signature(fn)
    assert "runtime" in sig.parameters

    class _RT:
        vision_consumer = None

    result = asyncio.run(fn(runtime=_RT()))
    assert result["consumer_wired"] is False
    assert result["total_session"] == 0


def test_api_endpoint_returns_snapshot_when_consumer_wired() -> None:
    """GET /api/perception/budget returns the consumer's snapshot when wired."""
    from probos.routers import perception as _perception_router

    consumer = _make_consumer()
    consumer._record_vision_call("vision", "sess1")

    class _RT:
        vision_consumer = consumer

    result = asyncio.run(_perception_router.get_vision_budget(runtime=_RT()))
    assert result["consumer_wired"] is True
    assert result["total_session"] == 1
    assert result["calls_this_session"]["vision"] == 1
