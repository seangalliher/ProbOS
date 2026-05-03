"""AD-641b: Ward Room Hebbian Router tests."""

from __future__ import annotations

import pytest

from probos.cognitive.ward_room_hebbian import WardRoomHebbianRouter
from probos.config import WardRoomHebbianConfig
from probos.events import EventType


def test_event_type_ward_room_hebbian_updated_exists():
    assert EventType.WARD_ROOM_HEBBIAN_UPDATED.value == "ward_room_hebbian_updated"


def test_event_type_ward_room_hebbian_decayed_exists():
    assert EventType.WARD_ROOM_HEBBIAN_DECAYED.value == "ward_room_hebbian_decayed"


def test_ward_room_hebbian_config_defaults():
    cfg = WardRoomHebbianConfig()
    assert cfg.enabled is True
    assert cfg.learning_rate == 0.10
    assert cfg.decay_factor == 0.99


def test_record_contribution_creates_weight():
    router = WardRoomHebbianRouter()
    assert router.get_weight("infosec", "alice") == 0.0
    new = router.record_contribution("infosec", "alice", signal=1.0)
    assert new == pytest.approx(0.10)
    assert router.get_weight("infosec", "alice") == pytest.approx(0.10)
    assert router.weight_count == 1


def test_record_contribution_clamped_to_max():
    router = WardRoomHebbianRouter()
    for _ in range(50):
        router.record_contribution("topic", "agent", signal=1.0)
    assert router.get_weight("topic", "agent") == pytest.approx(1.0)


def test_record_contribution_clamped_to_min():
    router = WardRoomHebbianRouter()
    new = router.record_contribution("topic", "agent", signal=-1.0)
    assert new == 0.0
    assert router.get_weight("topic", "agent") == 0.0


def test_record_contribution_emits_event():
    emitted: list[tuple[EventType, dict]] = []
    router = WardRoomHebbianRouter(
        emit_event=lambda et, payload: emitted.append((et, payload)),
    )
    router.record_contribution("infosec", "alice", signal=1.0)
    assert len(emitted) == 1
    et, payload = emitted[0]
    assert et == EventType.WARD_ROOM_HEBBIAN_UPDATED
    assert payload["topic"] == "infosec"
    assert payload["agent_id"] == "alice"
    assert payload["weight"] == pytest.approx(0.10)
    assert payload["signal"] == 1.0


def test_record_contribution_empty_topic_rejected():
    router = WardRoomHebbianRouter()
    assert router.record_contribution("", "alice", signal=1.0) == 0.0
    assert router.record_contribution("infosec", "", signal=1.0) == 0.0
    assert router.weight_count == 0


def test_get_weight_unknown_returns_zero():
    router = WardRoomHebbianRouter()
    assert router.get_weight("nope", "noone") == 0.0


def test_top_contributors_filters_zero_weight_and_sorts_desc():
    router = WardRoomHebbianRouter()
    # Boost three agents on "infosec".
    for _ in range(5):
        router.record_contribution("infosec", "alice", signal=1.0)
    for _ in range(3):
        router.record_contribution("infosec", "bob", signal=1.0)
    for _ in range(1):
        router.record_contribution("infosec", "carol", signal=1.0)
    # Add a fourth that we'll force to zero post-write.
    router.record_contribution("infosec", "dan", signal=1.0)
    router._weights[("infosec", "dan")] = 0.0  # simulate decayed-to-zero
    # Different topic -- should not appear in infosec results.
    router.record_contribution("ops", "alice", signal=1.0)

    top = router.top_contributors("infosec", k=5)
    agents = [a for a, _ in top]
    weights = [w for _, w in top]
    assert "dan" not in agents
    assert agents == ["alice", "bob", "carol"]
    assert weights == sorted(weights, reverse=True)


def test_decay_modifies_all_weights_and_emits_event():
    emitted: list[tuple[EventType, dict]] = []
    router = WardRoomHebbianRouter(
        emit_event=lambda et, payload: emitted.append((et, payload)),
        decay_factor=0.5,
    )
    router.record_contribution("topic", "a", signal=1.0)  # 0.10
    router.record_contribution("topic", "b", signal=1.0)  # 0.10
    emitted.clear()
    modified = router.decay()
    assert modified == 2
    assert router.get_weight("topic", "a") == pytest.approx(0.05)
    assert router.get_weight("topic", "b") == pytest.approx(0.05)
    assert any(et == EventType.WARD_ROOM_HEBBIAN_DECAYED for et, _ in emitted)
    decay_payload = next(p for et, p in emitted if et == EventType.WARD_ROOM_HEBBIAN_DECAYED)
    assert decay_payload["weights_decayed"] == 2
    assert decay_payload["factor"] == 0.5
