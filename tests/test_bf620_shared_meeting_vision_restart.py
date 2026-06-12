"""BF-620 (Natural Conversation epic #882): shared meeting vision survives restart.

Follow-up to BF-617. The Captain's RE-TEST still showed "Yeo can't see but Ezri
can" — after BF-617 shipped. Root cause: ``VisionConsumer._last_observation`` is
in-RAM and starts ``None`` after a restart, but a vision-capable observer's ring
hydrates from disk (AD-742f persistence) so SHE renders a scene while a
non-observer's fallback found ``None`` and rendered the BF-294 "camera not
active" sentinel. The Captain restarts before every test, so this reproduced
every time.

BF-620: ``latest_shared_observation`` now falls back to the most-recent
observation any REGISTERED OBSERVER currently holds when ``_last_observation``
is unset — so a non-observer borrows the live shared feed regardless of restart.

BF-287 discipline: a REAL ``VisionConsumer`` + REAL ``VisionWorkingMemory`` rings
(only the runtime/intent_bus service boundary is a MagicMock, matching the
canonical ``test_ad733a`` fixture).
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.config import PerceptionConfig, SystemConfig
from probos.perception.consumer import (
    VisionConsumer,
    get_or_create_working_memory,
    reset_working_memories_for_tests,
)
from probos.perception.working_memory import VisionObservation
from probos.routers.thread_fanout import _render_agent_scene_block


@pytest.fixture(autouse=True)
def _clean_wm():
    reset_working_memories_for_tests()
    yield
    reset_working_memories_for_tests()


def _obs(desc: str, ts: float) -> VisionObservation:
    return VisionObservation(
        timestamp=ts,
        attachment_ref=f"sha-{ts}",
        description=desc,
        novelty_score=0.9,
        subject_identity="captain",
    )


def _consumer() -> VisionConsumer:
    """Real ``VisionConsumer`` — the runtime/intent_bus are the service-level
    MagicMock (matching the canonical ``test_ad733a`` fixture); the rings under
    test are real ``VisionWorkingMemory`` instances."""
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    runtime.config = cfg
    runtime.intent_bus = MagicMock()
    return VisionConsumer(runtime, min_interval_seconds=0.0)


def test_returns_last_observation_when_set():
    # Unchanged behavior: a fresh in-RAM describe wins, no ring scan.
    c = _consumer()
    fresh = _obs("a fresh frame", time.time())
    c._last_observation = fresh
    assert c.latest_shared_observation() is fresh


def test_falls_back_to_observer_ring_after_restart():
    # The Captain-reported scenario: _last_observation is None (in-RAM, post
    # restart) but Ezri's ring hydrated from disk holds the feed.
    c = _consumer()
    c.register_observer("ezri")
    c._last_observation = None
    get_or_create_working_memory("ezri").append(
        _obs("the Captain in a black shirt", time.time())
    )
    out = c.latest_shared_observation()
    assert out is not None
    assert "black shirt" in out.description


def test_no_observation_anywhere_returns_none():
    # Camera truly off: no in-RAM obs, observer ring empty -> honest None.
    c = _consumer()
    c.register_observer("ezri")
    c._last_observation = None
    assert c.latest_shared_observation() is None


def test_picks_most_recent_across_observers():
    c = _consumer()
    c.register_observer("ezri")
    c.register_observer("data")
    c._last_observation = None
    get_or_create_working_memory("ezri").append(_obs("older view", 1000.0))
    get_or_create_working_memory("data").append(_obs("newer view", 2000.0))
    out = c.latest_shared_observation()
    assert out is not None and "newer view" in out.description


def test_non_observer_sees_borrowed_feed_end_to_end():
    # _render_agent_scene_block for the yeoman (no own ring, not an observer)
    # borrows the shared feed via the real consumer fallback -> the real scene,
    # not the "camera not active" sentinel. This is the exact Captain report.
    c = _consumer()
    c.register_observer("ezri")
    c._last_observation = None
    get_or_create_working_memory("ezri").append(
        _obs("the Captain, a plant behind", time.time())
    )
    rt = SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig(enabled=True)),
        perception_mode_controller=None,
        perception_engagement_registry=None,
        vision_consumer=c,
    )
    out = _render_agent_scene_block(rt, "yeo")
    assert "plant behind" in out
    assert "camera not active" not in out.lower()
