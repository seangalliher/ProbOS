"""BF-617 (Natural Conversation epic #882): shared meeting vision.

The Captain's live test: "Yeo can't see me but Ezri can." Root cause: the
perception fan-out only writes frames to REGISTERED observers (crew with
``vision_capable=True`` — counselor/architect). A present participant who is not
a vision-capable observer (e.g. the yeoman) had an empty ring, so AD-978
rendered the BF-294 "camera not active" sentinel and the agent said it couldn't
see — even though the shared meeting camera was live.

BF-617: a shared-camera meeting has ONE feed. ``VisionConsumer`` now records the
latest observation (``latest_shared_observation``), and ``_render_agent_scene_block``
falls back to it when an agent's own ring is empty — so every present participant
sees the same camera, WITHOUT enrolling non-observers in ambient perception.

BF-287 discipline: real ``VisionWorkingMemory`` rings + a real-but-fake consumer
exposing ``latest_shared_observation`` (NOT MagicMock).
"""
from __future__ import annotations

import time
from types import SimpleNamespace

from probos.config import PerceptionConfig
from probos.perception.consumer import (
    get_or_create_working_memory,
    reset_working_memories_for_tests,
)
from probos.perception.working_memory import VisionObservation
from probos.routers.thread_fanout import _render_agent_scene_block

import pytest


@pytest.fixture(autouse=True)
def _clean_wm():
    reset_working_memories_for_tests()
    yield
    reset_working_memories_for_tests()


class _FakeConsumer:
    """Real-but-fake consumer: holds a shared observation like the real one."""

    def __init__(self, obs):
        self._obs = obs

    def latest_shared_observation(self):
        return self._obs


def _obs(desc: str) -> VisionObservation:
    return VisionObservation(
        timestamp=time.time(),
        attachment_ref="sha-shared",
        description=desc,
        novelty_score=0.9,
        subject_identity="captain",
    )


def _runtime(*, enabled: bool, consumer):
    return SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig(enabled=enabled)),
        perception_mode_controller=None,
        perception_engagement_registry=None,
        vision_consumer=consumer,
    )


def test_observer_with_own_ring_sees_own_frame():
    # An observer (e.g. Ezri) has her own ring populated -> renders THAT, not
    # the shared fallback.
    wm = get_or_create_working_memory("ezri")
    wm.append(_obs("Ezri's own view: the Captain at a desk."))
    rt = _runtime(enabled=True, consumer=_FakeConsumer(_obs("shared view")))
    out = _render_agent_scene_block(rt, "ezri")
    assert "Ezri's own view" in out
    assert "shared view" not in out


def test_non_observer_falls_back_to_shared_observation():
    # Yeo has no ring (not a vision_capable observer). With a live shared feed,
    # he now sees it instead of the "camera not active" sentinel.
    rt = _runtime(enabled=True, consumer=_FakeConsumer(_obs("the Captain in a black shirt, plant behind")))
    out = _render_agent_scene_block(rt, "yeo")
    assert "Current Visual Context" in out
    assert "black shirt" in out
    assert "camera not active" not in out.lower()


def test_non_observer_empty_ring_gets_populated_for_next_time():
    # The fallback shares the observation INTO the agent's ring (meeting-scoped),
    # so a subsequent render is a normal own-ring render.
    rt = _runtime(enabled=True, consumer=_FakeConsumer(_obs("a shared scene")))
    _render_agent_scene_block(rt, "yeo")
    assert get_or_create_working_memory("yeo").entries(), "ring populated by share"


def test_no_shared_observation_still_sentinel():
    # No frame described yet -> no shared obs -> the honest BF-294 sentinel.
    rt = _runtime(enabled=True, consumer=_FakeConsumer(None))
    out = _render_agent_scene_block(rt, "yeo")
    assert "camera not active" in out.lower() or "no frames described yet" in out.lower()


def test_disabled_perception_renders_nothing():
    rt = _runtime(enabled=False, consumer=_FakeConsumer(_obs("a scene")))
    assert _render_agent_scene_block(rt, "yeo") == ""


def test_no_consumer_degrades_to_sentinel():
    # perception enabled but no vision_consumer wired -> empty ring -> sentinel,
    # never raises.
    rt = _runtime(enabled=True, consumer=None)
    out = _render_agent_scene_block(rt, "yeo")
    assert "camera not active" in out.lower() or "no frames described yet" in out.lower()
