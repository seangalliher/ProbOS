"""BF-624 (Natural Conversation epic #882): shared meeting vision refreshes a STALE ring.

Follow-up to BF-617 / BF-620. The Captain ran a live group chat and the crew
surfaced an asymmetry: the Counselor (a vision-capable observer) described the
LIVE frame (plaid shirt) while the Yeoman (NOT vision-capable) described a
22-hour-old frame (black shirt, teapot) for the WHOLE conversation. Root cause:
``_render_agent_scene_block`` shared the consumer's latest observation into a
participant's ring ONLY when that ring was EMPTY (the BF-617/BF-620 fallback).
The Yeoman's ring was NOT empty — it held a stale disk-hydrated frame
(AD-742f) — so the fallback never fired and he never refreshed, while
``force_describe_current_frame`` only writes to vision-capable observers' rings.

BF-624: share the consumer's latest observation into the agent's ring whenever
it is FRESHER than the ring's own latest (covers both empty and stale), so every
present participant sees the same current camera. Byte-identical for an
up-to-date observer (the shared obs is not newer than its own).

BF-287 discipline: REAL ``VisionConsumer`` + REAL ``VisionWorkingMemory`` rings
(only the runtime/intent_bus service boundary is a MagicMock, matching the
canonical ``test_bf620`` fixture).
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from probos.config import SystemConfig
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


def _runtime() -> MagicMock:
    """Runtime whose perception is ENABLED, with a real VisionConsumer wired."""
    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    runtime.config = cfg
    runtime.intent_bus = MagicMock()
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    runtime.vision_consumer = consumer
    # Per-agent engagement / mode controllers are optional; None disables them.
    runtime.perception_mode_controller = None
    runtime.perception_engagement_registry = None
    return runtime


def test_stale_ring_is_refreshed_with_the_fresher_shared_frame():
    """THE bug: the Yeoman holds a 22h-old frame; the live feed shows the
    current one. The scene block must render the CURRENT frame, not the stale."""
    runtime = _runtime()
    now = time.time()
    stale = now - 22 * 3600  # 22 hours ago (the reported black-shirt frame)
    # Yeoman's own ring: a stale disk-hydrated frame.
    get_or_create_working_memory("yeoman").append(_obs("Captain in a black shirt", stale))
    # The consumer's live shared observation: the current plaid-shirt frame.
    runtime.vision_consumer._last_observation = _obs("Captain in a plaid shirt", now)

    block = _render_agent_scene_block(runtime, "yeoman")
    assert "plaid shirt" in block
    assert "black shirt" not in block


def test_empty_ring_still_gets_the_shared_frame_bf617_bf620():
    """The BF-617/BF-620 case is preserved: an empty ring is refreshed too."""
    runtime = _runtime()
    runtime.vision_consumer._last_observation = _obs("Captain at the console", time.time())
    block = _render_agent_scene_block(runtime, "yeoman")
    assert "Captain at the console" in block


def test_up_to_date_observer_ring_is_not_downgraded():
    """An observer whose own ring already holds the freshest frame keeps it —
    the shared obs is not newer, so nothing is appended (byte-identical)."""
    runtime = _runtime()
    now = time.time()
    fresh = _obs("Captain in a plaid shirt", now)
    get_or_create_working_memory("ezri").append(fresh)
    # The consumer's shared obs is the SAME (or older) frame.
    runtime.vision_consumer._last_observation = fresh
    before = len(get_or_create_working_memory("ezri").entries())
    block = _render_agent_scene_block(runtime, "ezri")
    after = len(get_or_create_working_memory("ezri").entries())
    assert after == before  # no append — not downgraded, not duplicated
    assert "plaid shirt" in block


def test_agent_with_fresher_own_frame_keeps_it():
    """If the agent's own ring is somehow fresher than the shared obs, keep its
    own (never replace a newer frame with an older shared one)."""
    runtime = _runtime()
    now = time.time()
    get_or_create_working_memory("ezri").append(_obs("the current plaid frame", now))
    runtime.vision_consumer._last_observation = _obs("an older frame", now - 3600)
    block = _render_agent_scene_block(runtime, "ezri")
    assert "current plaid frame" in block
    assert "older frame" not in block


def test_no_shared_observation_leaves_ring_untouched():
    """Camera truly off (no shared obs, empty ring) -> the BF-294 sentinel,
    unchanged honest-degrade."""
    runtime = _runtime()
    runtime.vision_consumer._last_observation = None
    block = _render_agent_scene_block(runtime, "yeoman")
    # Empty ring + no shared obs -> the confabulation-guard sentinel.
    assert "Camera not active" in block


def test_perception_disabled_returns_empty_block():
    """Default-off gate: perception disabled -> '' (byte-identical when off)."""
    runtime = _runtime()
    runtime.config.perception.enabled = False
    assert _render_agent_scene_block(runtime, "yeoman") == ""
