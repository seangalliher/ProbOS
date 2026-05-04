"""AD-539c: Observational Gap Remediation Tracker tests."""

from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.gap_remediation import GapRemediationTracker, RemediationCandidate
from probos.config import GapPipelineExtensionsConfig
from probos.events import EventType
from probos.startup.finalize import _wire_gap_remediation_tracker


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _CollectingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


def _gap(
    *,
    gap_id: str = "gap:nav:fly:abc",
    agent_id: str = "agent-1",
    agent_type: str = "navigator",
    gap_type: str = "knowledge",
    qualification_path_id: str = "qpath-1",
    priority: str = "medium",
    affected_intent_types: list[str] | None = None,
) -> SimpleNamespace:
    """Lightweight GapReport-shaped stub."""
    return SimpleNamespace(
        id=gap_id,
        agent_id=agent_id,
        agent_type=agent_type,
        gap_type=gap_type,
        qualification_path_id=qualification_path_id,
        priority=priority,
        affected_intent_types=affected_intent_types or [],
    )


# ---------------------------------------------------------------------------
# Section 1 — RemediationCandidate contract
# ---------------------------------------------------------------------------


def test_remediation_candidate_is_frozen_dataclass() -> None:
    candidate = RemediationCandidate(
        gap_id="g1",
        agent_id="a1",
        gap_type="knowledge",
        proposed_action="trigger_qualification",
        reason="why",
        candidate_at=1.0,
    )
    assert dataclasses.is_dataclass(candidate)
    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.gap_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Section 2 — record_candidate
# ---------------------------------------------------------------------------


def test_record_candidate_returns_candidate() -> None:
    tracker = GapRemediationTracker(SimpleNamespace())
    result = tracker.record_candidate(_gap())
    assert isinstance(result, RemediationCandidate)
    assert result.gap_id == "gap:nav:fly:abc"
    assert result.agent_id == "agent-1"
    assert result.gap_type == "knowledge"
    assert result.proposed_action == "trigger_qualification"
    assert result.candidate_at > 0


def test_record_candidate_emits_event() -> None:
    tracker = GapRemediationTracker(SimpleNamespace())
    emitter = _CollectingEmitter()
    tracker.emit_event = emitter
    tracker.record_candidate(_gap())
    assert len(emitter.events) == 1
    event_type, data = emitter.events[0]
    assert event_type == EventType.GAP_REMEDIATION_RECORDED
    assert data["gap_id"] == "gap:nav:fly:abc"
    assert data["agent_id"] == "agent-1"
    assert data["gap_type"] == "knowledge"
    assert data["proposed_action"] == "trigger_qualification"
    assert "reason" in data


def test_record_candidate_appends_to_history() -> None:
    tracker = GapRemediationTracker(SimpleNamespace())
    tracker.record_candidate(_gap(gap_id="g1"))
    tracker.record_candidate(_gap(gap_id="g2"))
    recent = tracker.recent_candidates()
    assert len(recent) == 2
    assert {c.gap_id for c in recent} == {"g1", "g2"}


def test_record_candidate_evicts_oldest_at_max_history() -> None:
    tracker = GapRemediationTracker(SimpleNamespace(), max_history=3)
    for i in range(5):
        tracker.record_candidate(_gap(gap_id=f"g{i}"))
    recent = tracker.recent_candidates(limit=10)
    assert len(recent) == 3
    # Newest first — most recent three are g4, g3, g2.
    assert [c.gap_id for c in recent] == ["g4", "g3", "g2"]


# ---------------------------------------------------------------------------
# Section 3 — proposed_action_for mapping
# ---------------------------------------------------------------------------


def test_proposed_action_knowledge_with_qualification_path() -> None:
    tracker = GapRemediationTracker(SimpleNamespace())
    action = tracker.proposed_action_for(
        _gap(gap_type="knowledge", qualification_path_id="qpath-42")
    )
    assert action == "trigger_qualification"


def test_proposed_action_data_gap() -> None:
    tracker = GapRemediationTracker(SimpleNamespace())
    action = tracker.proposed_action_for(_gap(gap_type="data", qualification_path_id=""))
    assert action == "request_data_routing"


def test_proposed_action_capability_gap() -> None:
    tracker = GapRemediationTracker(SimpleNamespace())
    action = tracker.proposed_action_for(
        _gap(gap_type="capability", qualification_path_id="")
    )
    assert action == "escalate_capability"


def test_proposed_action_no_action_for_unknown_type() -> None:
    tracker = GapRemediationTracker(SimpleNamespace())
    # Unknown gap_type
    assert tracker.proposed_action_for(_gap(gap_type="unknown")) == "no_action"
    # Knowledge with empty qualification_path_id (observational hole)
    assert (
        tracker.proposed_action_for(_gap(gap_type="knowledge", qualification_path_id=""))
        == "no_action"
    )


# ---------------------------------------------------------------------------
# Section 4 — Query helpers
# ---------------------------------------------------------------------------


def test_recent_candidates_returns_descending_order() -> None:
    tracker = GapRemediationTracker(SimpleNamespace())
    tracker.record_candidate(_gap(gap_id="oldest"))
    time.sleep(0.001)
    tracker.record_candidate(_gap(gap_id="middle"))
    time.sleep(0.001)
    tracker.record_candidate(_gap(gap_id="newest"))
    recent = tracker.recent_candidates(limit=2)
    assert [c.gap_id for c in recent] == ["newest", "middle"]


def test_candidates_for_agent_filters_by_agent_id() -> None:
    tracker = GapRemediationTracker(SimpleNamespace())
    tracker.record_candidate(_gap(gap_id="g1", agent_id="alice"))
    tracker.record_candidate(_gap(gap_id="g2", agent_id="bob"))
    tracker.record_candidate(_gap(gap_id="g3", agent_id="alice"))
    alice_candidates = tracker.candidates_for_agent("alice")
    assert len(alice_candidates) == 2
    # Newest first.
    assert [c.gap_id for c in alice_candidates] == ["g3", "g1"]
    bob_candidates = tracker.candidates_for_agent("bob")
    assert len(bob_candidates) == 1
    assert bob_candidates[0].gap_id == "g2"


# ---------------------------------------------------------------------------
# Section 5 — Runtime wiring
# ---------------------------------------------------------------------------


def test_wire_gap_remediation_tracker_sets_public_attribute() -> None:
    runtime = MagicMock(spec=["emit_event", "gap_remediation_tracker"])
    config = SimpleNamespace(
        gap_pipeline_extensions=GapPipelineExtensionsConfig(remediation_tracker_enabled=True)
    )
    wired = _wire_gap_remediation_tracker(runtime=runtime, config=config)
    assert wired is True
    assert isinstance(runtime.gap_remediation_tracker, GapRemediationTracker)
