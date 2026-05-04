"""AD-539d: Fleet-Level Gap Aggregation tests."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.gap_aggregation import FleetGapAggregator, FleetGapSnapshot
from probos.config import GapPipelineExtensionsConfig
from probos.events import EventType
from probos.startup.finalize import _wire_gap_aggregator


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _CollectingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


class _FakeOntology:
    """Ontology stub returning department objects with department_id attr."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def get_agent_department(self, agent_type: str) -> Any:
        if agent_type not in self._mapping:
            return None
        return SimpleNamespace(department_id=self._mapping[agent_type])


def _gap(
    *,
    gap_id: str = "g1",
    agent_id: str = "agent-1",
    agent_type: str = "navigator",
    gap_type: str = "knowledge",
    priority: str = "medium",
    affected_intent_types: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=gap_id,
        agent_id=agent_id,
        agent_type=agent_type,
        gap_type=gap_type,
        priority=priority,
        affected_intent_types=affected_intent_types or [],
    )


# ---------------------------------------------------------------------------
# Section 1 — FleetGapSnapshot contract
# ---------------------------------------------------------------------------


def test_fleet_gap_snapshot_is_frozen_dataclass() -> None:
    snapshot = FleetGapSnapshot(
        snapshot_at=1.0,
        total_gaps=0,
        by_gap_type={},
        by_priority={},
        by_department={},
        top_intents=(),
    )
    assert dataclasses.is_dataclass(snapshot)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.total_gaps = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Section 2 — take_snapshot aggregation
# ---------------------------------------------------------------------------


def test_take_snapshot_empty_reports_returns_zero_counts() -> None:
    aggregator = FleetGapAggregator(SimpleNamespace())
    snapshot = aggregator.take_snapshot([])
    assert snapshot.total_gaps == 0
    assert snapshot.by_gap_type == {}
    assert snapshot.by_priority == {}
    assert snapshot.by_department == {}
    assert snapshot.top_intents == ()


def test_take_snapshot_aggregates_total_count() -> None:
    aggregator = FleetGapAggregator(SimpleNamespace())
    reports = [_gap(gap_id=f"g{i}") for i in range(7)]
    snapshot = aggregator.take_snapshot(reports)
    assert snapshot.total_gaps == 7


def test_take_snapshot_groups_by_gap_type() -> None:
    aggregator = FleetGapAggregator(SimpleNamespace())
    reports = [
        _gap(gap_id="g1", gap_type="knowledge"),
        _gap(gap_id="g2", gap_type="knowledge"),
        _gap(gap_id="g3", gap_type="data"),
        _gap(gap_id="g4", gap_type="capability"),
    ]
    snapshot = aggregator.take_snapshot(reports)
    assert snapshot.by_gap_type == {"knowledge": 2, "data": 1, "capability": 1}


def test_take_snapshot_groups_by_priority() -> None:
    aggregator = FleetGapAggregator(SimpleNamespace())
    reports = [
        _gap(gap_id="g1", priority="critical"),
        _gap(gap_id="g2", priority="high"),
        _gap(gap_id="g3", priority="high"),
        _gap(gap_id="g4", priority="low"),
    ]
    snapshot = aggregator.take_snapshot(reports)
    assert snapshot.by_priority == {"critical": 1, "high": 2, "low": 1}


def test_take_snapshot_groups_by_department_via_ontology() -> None:
    ontology = _FakeOntology({"navigator": "ops", "doctor": "medical"})
    runtime = SimpleNamespace(ontology=ontology)
    aggregator = FleetGapAggregator(runtime)
    reports = [
        _gap(gap_id="g1", agent_type="navigator"),
        _gap(gap_id="g2", agent_type="navigator"),
        _gap(gap_id="g3", agent_type="doctor"),
    ]
    snapshot = aggregator.take_snapshot(reports)
    assert snapshot.by_department == {"ops": 2, "medical": 1}


def test_take_snapshot_department_empty_when_ontology_absent() -> None:
    runtime = SimpleNamespace(ontology=None)
    aggregator = FleetGapAggregator(runtime)
    reports = [_gap(gap_id="g1", agent_type="navigator")]
    snapshot = aggregator.take_snapshot(reports)
    assert snapshot.by_department == {}


def test_take_snapshot_top_intents_returns_max_5_descending() -> None:
    aggregator = FleetGapAggregator(SimpleNamespace())
    # Construct intent counts: navigate(4), repair(3), scan(2), heal(1), cook(1), drink(1), sleep(1)
    reports = [
        _gap(gap_id="g1", affected_intent_types=["navigate", "repair"]),
        _gap(gap_id="g2", affected_intent_types=["navigate", "repair", "scan"]),
        _gap(gap_id="g3", affected_intent_types=["navigate", "scan"]),
        _gap(gap_id="g4", affected_intent_types=["navigate", "repair"]),
        _gap(gap_id="g5", affected_intent_types=["heal", "cook", "drink", "sleep"]),
    ]
    snapshot = aggregator.take_snapshot(reports)
    assert len(snapshot.top_intents) == 5
    # Descending order by count.
    counts = [count for _, count in snapshot.top_intents]
    assert counts == sorted(counts, reverse=True)
    top3_intents = {intent for intent, _ in snapshot.top_intents[:3]}
    assert top3_intents == {"navigate", "repair", "scan"}


# ---------------------------------------------------------------------------
# Section 3 — Event emission + privacy
# ---------------------------------------------------------------------------


def test_take_snapshot_emits_event_with_summary_payload() -> None:
    aggregator = FleetGapAggregator(SimpleNamespace(ontology=None))
    emitter = _CollectingEmitter()
    aggregator.emit_event = emitter
    reports = [
        _gap(gap_id="g1", gap_type="knowledge", priority="high"),
        _gap(gap_id="g2", gap_type="data", priority="low"),
    ]
    aggregator.take_snapshot(reports)
    assert len(emitter.events) == 1
    event_type, data = emitter.events[0]
    assert event_type == EventType.FLEET_GAP_SNAPSHOT_TAKEN
    assert data["total_gaps"] == 2
    assert data["by_gap_type"] == {"knowledge": 1, "data": 1}
    assert data["by_priority"] == {"high": 1, "low": 1}


def test_take_snapshot_payload_excludes_agent_ids() -> None:
    aggregator = FleetGapAggregator(SimpleNamespace(ontology=None))
    emitter = _CollectingEmitter()
    aggregator.emit_event = emitter
    reports = [
        _gap(gap_id="g1", agent_id="alice", gap_type="knowledge"),
        _gap(gap_id="g2", agent_id="bob", gap_type="data"),
    ]
    aggregator.take_snapshot(reports)
    assert len(emitter.events) == 1
    _, data = emitter.events[0]
    # Privacy: payload contains aggregate counts only — no agent_ids,
    # no gap_ids, no descriptions.
    assert "agent_id" not in data
    assert "agent_ids" not in data
    assert "gap_id" not in data
    assert "description" not in data
    serialized = repr(data)
    assert "alice" not in serialized
    assert "bob" not in serialized
    assert "g1" not in serialized
    assert "g2" not in serialized


# ---------------------------------------------------------------------------
# Section 4 — Runtime wiring
# ---------------------------------------------------------------------------


def test_wire_gap_aggregator_sets_public_attribute() -> None:
    runtime = MagicMock(spec=["emit_event", "gap_aggregator"])
    config = SimpleNamespace(
        gap_pipeline_extensions=GapPipelineExtensionsConfig(fleet_aggregator_enabled=True)
    )
    wired = _wire_gap_aggregator(runtime=runtime, config=config)
    assert wired is True
    assert isinstance(runtime.gap_aggregator, FleetGapAggregator)
