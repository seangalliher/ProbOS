"""AD-610: Tests for utility-based storage gating."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.storage_gate import StorageDecision, StorageGate
from probos.events import EventType
from probos.types import AnchorFrame, Episode


class _FakeStorageGateConfig:
    """Stub config for tests."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        duplicate_threshold: float = 0.95,
        utility_floor: float = 0.2,
        recent_window: int = 50,
        contradiction_check_enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.duplicate_threshold = duplicate_threshold
        self.utility_floor = utility_floor
        self.recent_window = recent_window
        self.contradiction_check_enabled = contradiction_check_enabled


class _FakeEventCollector:
    """Collect emitted events for assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


@pytest.fixture
def collector() -> _FakeEventCollector:
    return _FakeEventCollector()


@pytest.fixture
def gate(collector: _FakeEventCollector) -> StorageGate:
    return StorageGate(
        config=_FakeStorageGateConfig(),
        emit_event_fn=collector,
    )


def _make_anchor() -> AnchorFrame:
    return AnchorFrame(
        department="operations",
        channel="ward_room",
        trigger_type="direct_message",
        watch_section="first",
        participants=["Lynx"],
        trigger_agent="Captain",
    )


def _make_episode(
    *,
    user_input: str = "test observation with enough operational detail to matter",
    importance: int = 5,
    source: str = "direct",
    anchors: AnchorFrame | None = None,
    outcomes: list[dict[str, Any]] | None = None,
    episode_id: str = "",
) -> Episode:
    return Episode(
        id=episode_id or uuid.uuid4().hex,
        timestamp=time.time(),
        user_input=user_input,
        importance=importance,
        source=source,
        anchors=anchors,
        outcomes=outcomes or [],
        agent_ids=["agent-1"],
    )


def test_accept_normal_episode(gate: StorageGate) -> None:
    episode = _make_episode(anchors=_make_anchor())

    decision = gate.evaluate(episode)

    assert decision.action == "ACCEPT"
    assert decision.reason == "passed_all_checks"
    assert decision.utility_score >= 0.2


def test_reject_near_duplicate(gate: StorageGate) -> None:
    first = _make_episode(user_input="Alpha beta gamma repeated observation", anchors=_make_anchor())
    duplicate = _make_episode(user_input="Alpha beta gamma repeated observation", anchors=_make_anchor())

    gate.evaluate(first)
    decision = gate.evaluate(duplicate)

    assert decision.action == "REJECT"
    assert decision.reason == "near_duplicate"
    assert decision.duplicate_of == first.id


def test_reject_low_utility(gate: StorageGate) -> None:
    episode = _make_episode(user_input="ok", importance=1, anchors=None)

    decision = gate.evaluate(episode)

    assert decision.action == "REJECT"
    assert decision.reason == "below_utility_floor"
    assert decision.utility_score < 0.2


def test_detect_contradiction(caplog: pytest.LogCaptureFixture) -> None:
    gate = StorageGate(config=_FakeStorageGateConfig(duplicate_threshold=1.1, utility_floor=0.0))
    first = _make_episode(
        user_input="trust score for relay alpha is stable",
        outcomes=[{"success": True}],
        anchors=_make_anchor(),
    )
    second = _make_episode(
        user_input="trust score for relay alpha is stable",
        outcomes=[{"success": False}],
        anchors=_make_anchor(),
    )

    gate.evaluate(first)
    with caplog.at_level(logging.INFO, logger="probos.cognitive.storage_gate"):
        decision = gate.evaluate(second)

    assert decision.action == "ACCEPT"
    assert "Contradiction detected" in caplog.text


def test_utility_scoring_components(gate: StorageGate) -> None:
    episode = _make_episode(
        user_input="x" * 500,
        importance=5,
        source="secondhand",
        anchors=_make_anchor(),
    )

    utility = gate._check_utility(episode, episode.user_input)

    assert utility == pytest.approx(0.76)


def test_duplicate_threshold_configurable() -> None:
    gate = StorageGate(config=_FakeStorageGateConfig(duplicate_threshold=0.5, utility_floor=0.0))
    first = _make_episode(user_input="alpha beta gamma", anchors=_make_anchor())
    second = _make_episode(user_input="alpha beta gamma delta", anchors=_make_anchor())

    gate.evaluate(first)
    decision = gate.evaluate(second)

    assert decision.action == "REJECT"
    assert decision.reason == "near_duplicate"


def test_utility_floor_configurable() -> None:
    gate = StorageGate(config=_FakeStorageGateConfig(utility_floor=0.7))
    episode = _make_episode(anchors=_make_anchor())

    decision = gate.evaluate(episode)

    assert decision.action == "REJECT"
    assert decision.reason == "below_utility_floor"


def test_disabled_gate_accepts_all() -> None:
    gate = StorageGate(config=_FakeStorageGateConfig(enabled=False))
    episode = _make_episode(user_input="", importance=1, anchors=None)

    decision = gate.evaluate(episode)

    assert decision.action == "ACCEPT"
    assert decision.reason == "gate_disabled"
    assert decision.utility_score == 1.0


def test_merge_decision() -> None:
    decision = StorageDecision(
        action="MERGE",
        reason="future_merge_path",
        utility_score=0.9,
        duplicate_of="episode-1",
    )

    assert decision.action == "MERGE"
    assert decision.duplicate_of == "episode-1"


def test_recent_window_boundary() -> None:
    gate = StorageGate(config=_FakeStorageGateConfig(recent_window=2, utility_floor=0.0))
    first = _make_episode(user_input="alpha one")
    second = _make_episode(user_input="beta two")
    third = _make_episode(user_input="gamma three")
    duplicate_of_first = _make_episode(user_input="alpha one")

    gate.evaluate(first)
    gate.evaluate(second)
    gate.evaluate(third)
    decision = gate.evaluate(duplicate_of_first)

    assert gate.recent_count == 2
    assert decision.action == "ACCEPT"


def test_high_importance_bypasses_utility() -> None:
    gate = StorageGate(config=_FakeStorageGateConfig(utility_floor=0.99))
    episode = _make_episode(user_input="ok", importance=8, anchors=None)

    decision = gate.evaluate(episode)

    assert decision.action == "ACCEPT"


def test_event_emitted_on_reject(collector: _FakeEventCollector) -> None:
    gate = StorageGate(config=_FakeStorageGateConfig(), emit_event_fn=collector)
    episode = _make_episode(user_input="ok", importance=1, anchors=None)

    decision = gate.evaluate(episode)

    assert decision.action == "REJECT"
    assert collector.events == [(
        EventType.EPISODE_REJECTED,
        {
            "episode_id": episode.id,
            "agent_ids": ["agent-1"],
            "reason": "below_utility_floor",
            "importance": 1,
        },
    )]


def test_empty_episode_rejected(gate: StorageGate) -> None:
    episode = _make_episode(user_input="", outcomes=[], anchors=None)

    decision = gate.evaluate(episode)

    assert decision.action == "REJECT"
    assert decision.reason == "empty_content"


@pytest.mark.asyncio
async def test_integration_with_store(tmp_path: Any) -> None:
    memory = EpisodicMemory(
        db_path=tmp_path / "episodes.db",
        max_episodes=100,
        relevance_threshold=0.3,
    )
    gate = StorageGate(config=_FakeStorageGateConfig())
    memory.set_storage_gate(gate)
    await memory.start()
    try:
        await memory.store(_make_episode(user_input="", outcomes=[], anchors=None))

        stats = await memory.get_stats()
        assert stats["total"] == 0
    finally:
        await memory.stop()