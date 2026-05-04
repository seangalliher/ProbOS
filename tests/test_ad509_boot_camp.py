"""AD-509 Boot Camp Phase Tracker v1."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from probos.config import BootCampPhaseConfig
from probos.crew_development import (
    AgentBootCampRecord,
    BootCampPhase,
    BootCampPhaseTracker,
)
from probos.events import EventType
from probos.startup.finalize import _wire_boot_camp_tracker


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _CollectingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


# ---------------------------------------------------------------------------
# Section 0 — EventType + Pydantic config
# ---------------------------------------------------------------------------


def test_event_type_boot_camp_phase_advanced_exists() -> None:
    assert hasattr(EventType, "BOOT_CAMP_PHASE_ADVANCED")
    assert EventType.BOOT_CAMP_PHASE_ADVANCED.value == "boot_camp_phase_advanced"


def test_boot_camp_config_defaults() -> None:
    cfg = BootCampPhaseConfig()
    assert cfg.enabled is True


# ---------------------------------------------------------------------------
# Section 2 — Enum + record
# ---------------------------------------------------------------------------


def test_boot_camp_phase_enum_has_5_phases_plus_completed() -> None:
    expected = {
        "ORIENTATION",
        "CORE_KNOWLEDGE",
        "A_SCHOOL",
        "CALIBRATION",
        "INTEGRATION",
        "COMPLETED",
    }
    actual = {p.name for p in BootCampPhase}
    assert actual == expected
    # 5 active phases + 1 terminal sentinel
    assert len(BootCampPhase) == 6


def test_agent_boot_camp_record_initial_state() -> None:
    rec = AgentBootCampRecord(agent_id="agent-1")
    assert rec.agent_id == "agent-1"
    assert rec.current_phase is BootCampPhase.ORIENTATION
    assert rec.phase_history == []
    assert rec.started_at > 0


# ---------------------------------------------------------------------------
# Section 3 — Tracker behavior
# ---------------------------------------------------------------------------


def test_get_or_create_idempotent() -> None:
    tracker = BootCampPhaseTracker()
    a = tracker.get_or_create("agent-1")
    b = tracker.get_or_create("agent-1")
    assert a is b


def test_get_or_create_seeds_orientation_history_entry() -> None:
    tracker = BootCampPhaseTracker()
    rec = tracker.get_or_create("agent-1")
    assert len(rec.phase_history) == 1
    phase_value, ts = rec.phase_history[0]
    assert phase_value == BootCampPhase.ORIENTATION.value
    assert ts == rec.started_at


def test_advance_phase_progresses_through_order() -> None:
    tracker = BootCampPhaseTracker()
    sequence = [
        BootCampPhase.CORE_KNOWLEDGE,
        BootCampPhase.A_SCHOOL,
        BootCampPhase.CALIBRATION,
        BootCampPhase.INTEGRATION,
        BootCampPhase.COMPLETED,
    ]
    for expected in sequence:
        actual = tracker.advance_phase("agent-1")
        assert actual is expected
    rec = tracker.get_record("agent-1")
    assert rec is not None
    assert rec.current_phase is BootCampPhase.COMPLETED


def test_advance_phase_stops_at_completed() -> None:
    tracker = BootCampPhaseTracker()
    # Advance to COMPLETED (5 advances from ORIENTATION).
    for _ in range(5):
        tracker.advance_phase("agent-1")
    assert tracker.is_completed("agent-1")
    # Further advances should be no-ops returning COMPLETED.
    result = tracker.advance_phase("agent-1")
    assert result is BootCampPhase.COMPLETED
    rec = tracker.get_record("agent-1")
    assert rec is not None
    # phase_history has the seed (ORIENTATION) + 5 advances = 6 entries; no more.
    assert len(rec.phase_history) == 6


def test_advance_phase_emits_event() -> None:
    tracker = BootCampPhaseTracker()
    emitter = _CollectingEmitter()
    tracker.emit_event = emitter
    tracker.advance_phase("agent-1")
    assert len(emitter.events) == 1
    event_type, data = emitter.events[0]
    assert event_type is EventType.BOOT_CAMP_PHASE_ADVANCED
    assert data == {
        "agent_id": "agent-1",
        "previous_phase": BootCampPhase.ORIENTATION.value,
        "current_phase": BootCampPhase.CORE_KNOWLEDGE.value,
    }


def test_advance_phase_records_phase_history() -> None:
    tracker = BootCampPhaseTracker()
    tracker.advance_phase("agent-1")
    tracker.advance_phase("agent-1")
    rec = tracker.get_record("agent-1")
    assert rec is not None
    # Seed (ORIENTATION) + 2 advances = 3 entries.
    assert len(rec.phase_history) == 3
    phase_values = [entry[0] for entry in rec.phase_history]
    assert phase_values == [
        BootCampPhase.ORIENTATION.value,
        BootCampPhase.CORE_KNOWLEDGE.value,
        BootCampPhase.A_SCHOOL.value,
    ]


def test_get_record_returns_record_or_none() -> None:
    tracker = BootCampPhaseTracker()
    assert tracker.get_record("missing") is None
    tracker.get_or_create("agent-1")
    rec = tracker.get_record("agent-1")
    assert isinstance(rec, AgentBootCampRecord)
    assert rec.agent_id == "agent-1"


def test_all_records_returns_tuple() -> None:
    tracker = BootCampPhaseTracker()
    assert tracker.all_records() == ()
    tracker.get_or_create("agent-1")
    tracker.get_or_create("agent-2")
    out = tracker.all_records()
    assert isinstance(out, tuple)
    assert len(out) == 2
    ids = {r.agent_id for r in out}
    assert ids == {"agent-1", "agent-2"}


def test_is_completed_returns_true_only_at_completed_phase() -> None:
    tracker = BootCampPhaseTracker()
    assert tracker.is_completed("missing") is False
    tracker.get_or_create("agent-1")
    assert tracker.is_completed("agent-1") is False
    for _ in range(5):
        tracker.advance_phase("agent-1")
    assert tracker.is_completed("agent-1") is True


# ---------------------------------------------------------------------------
# Section 5 — Runtime wiring
# ---------------------------------------------------------------------------


def test_runtime_attribute_set_when_enabled() -> None:
    runtime = MagicMock(spec=["emit_event", "boot_camp_tracker"])
    config = SimpleNamespace(boot_camp_phase=BootCampPhaseConfig(enabled=True))
    wired = _wire_boot_camp_tracker(runtime=runtime, config=config)
    assert wired is True
    assert isinstance(runtime.boot_camp_tracker, BootCampPhaseTracker)


def test_runtime_attribute_not_set_when_disabled() -> None:
    runtime = SimpleNamespace(emit_event=lambda *a, **k: None)
    config = SimpleNamespace(boot_camp_phase=BootCampPhaseConfig(enabled=False))
    wired = _wire_boot_camp_tracker(runtime=runtime, config=config)
    assert wired is False
    assert not hasattr(runtime, "boot_camp_tracker")
