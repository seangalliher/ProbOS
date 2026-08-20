"""AD-539c-i + AD-539d-i: tests for active remediation + federated aggregation."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.gap_remediation import GapRemediationTracker
from probos.cognitive.gap_aggregation import (
    FederatedGapSnapshot,
    FleetGapSnapshot,
    merge_fleet_snapshots,
)


# ---------------------------------------------------------------------------
# AD-539c-i — active remediation
# ---------------------------------------------------------------------------


@dataclass
class _GapReport:
    id: str = "g1"
    agent_id: str = "alpha"
    gap_type: str = "knowledge"
    qualification_path_id: str = "qp_security_basics"
    priority: str = "high"
    affected_intent_types: tuple[str, ...] = ()


def _runtime_with_flag(flag: bool, *, qual=None, bus=None) -> SimpleNamespace:
    cfg = SimpleNamespace(
        gap_pipeline_extensions=SimpleNamespace(
            active_remediation_enabled=flag,
            remediation_tracker_enabled=True,
            fleet_aggregator_enabled=True,
            remediation_max_history=100,
        ),
    )
    return SimpleNamespace(
        config=cfg,
        qualification_service=qual,
        intent_bus=bus,
        emit_event=None,
        ontology=None,
    )


@pytest.mark.asyncio
async def test_disabled_flag_returns_no_op() -> None:
    rt = _runtime_with_flag(False)
    tracker = GapRemediationTracker(rt)
    cand = tracker.record_candidate(_GapReport())
    out = await tracker.execute_remediation(cand)
    assert out["executed"] is False
    assert "disabled" in out["detail"]


@pytest.mark.asyncio
async def test_trigger_qualification_calls_service_trigger() -> None:
    calls: list[dict] = []

    class _Qual:
        def trigger(self, *, agent_id, qualification_path_id):
            calls.append({"agent_id": agent_id, "qpath": qualification_path_id})
            return "scheduled:1"

    rt = _runtime_with_flag(True, qual=_Qual())
    tracker = GapRemediationTracker(rt)
    gap = _GapReport()
    cand = tracker.record_candidate(gap)
    out = await tracker.execute_remediation(cand, gap_report=gap)
    assert out["executed"] is True
    assert calls == [{"agent_id": "alpha", "qpath": "qp_security_basics"}]


@pytest.mark.asyncio
async def test_trigger_qualification_no_service_returns_unavailable() -> None:
    rt = _runtime_with_flag(True, qual=None)
    tracker = GapRemediationTracker(rt)
    gap = _GapReport()
    cand = tracker.record_candidate(gap)
    out = await tracker.execute_remediation(cand, gap_report=gap)
    assert out["executed"] is False
    assert "unavailable" in out["detail"]


@pytest.mark.asyncio
async def test_request_data_routing_broadcasts() -> None:
    sent: list = []

    class _Bus:
        def __init__(self) -> None:
            self.raise_on_denial_flags: list[bool] = []

        async def broadcast(self, intent, timeout=2.0, *, raise_on_denial=False):
            # BF-790: recorded so this double cannot mask the remediation path
            # dropping its opt-in and returning executed=True for a refusal.
            self.raise_on_denial_flags.append(raise_on_denial)
            sent.append(intent)
            return []

    bus = _Bus()
    rt = _runtime_with_flag(True, bus=bus)
    tracker = GapRemediationTracker(rt)
    gap = _GapReport(gap_type="data", qualification_path_id="")
    cand = tracker.record_candidate(gap)
    out = await tracker.execute_remediation(cand, gap_report=gap)
    assert out["executed"] is True
    assert len(sent) == 1
    assert sent[0].intent == "data_routing_requested"
    # BF-790: without the opt-in a refused broadcast returns [] and this path
    # reports executed=True for work that never went out.
    assert bus.raise_on_denial_flags == [True]


@pytest.mark.asyncio
async def test_escalate_capability_emits_event() -> None:
    events: list[tuple] = []

    rt = _runtime_with_flag(True)
    rt.emit_event = lambda et, payload: events.append((et, payload))
    tracker = GapRemediationTracker(rt)
    gap = _GapReport(gap_type="capability", qualification_path_id="")
    cand = tracker.record_candidate(gap)
    out = await tracker.execute_remediation(cand, gap_report=gap)
    assert out["executed"] is True
    # Should have emitted at least one event with phase=escalated
    assert any(payload.get("phase") == "escalated" for _, payload in events)


@pytest.mark.asyncio
async def test_remediation_handler_exception_log_and_degrade() -> None:
    class _BadQual:
        def trigger(self, **kw):
            raise RuntimeError("qual broke")
    rt = _runtime_with_flag(True, qual=_BadQual())
    tracker = GapRemediationTracker(rt)
    gap = _GapReport()
    cand = tracker.record_candidate(gap)
    out = await tracker.execute_remediation(cand, gap_report=gap)
    assert out["executed"] is False
    assert "RuntimeError" in out["detail"]


# ---------------------------------------------------------------------------
# AD-539d-i — federated aggregation
# ---------------------------------------------------------------------------


def _snap(total: int, types: dict[str, int], priorities: dict[str, int]) -> FleetGapSnapshot:
    return FleetGapSnapshot(
        snapshot_at=0.0,
        total_gaps=total,
        by_gap_type=types,
        by_priority=priorities,
        by_department={},
        top_intents=(),
    )


def test_merge_local_only() -> None:
    local = _snap(5, {"knowledge": 3, "data": 2}, {"high": 4, "low": 1})
    fed = merge_fleet_snapshots("uss-a", local, peer_snapshots={})
    assert fed.total_gaps == 5
    assert fed.contributing_ships == ("uss-a",)
    assert fed.per_ship["uss-a"]["total_gaps"] == 5


def test_merge_local_plus_peer() -> None:
    local = _snap(5, {"knowledge": 3, "data": 2}, {"high": 4, "low": 1})
    peer = _snap(3, {"capability": 3}, {"medium": 3})
    fed = merge_fleet_snapshots("uss-a", local, peer_snapshots={"uss-b": peer})
    assert fed.total_gaps == 8
    assert sorted(fed.contributing_ships) == ["uss-a", "uss-b"]
    assert fed.by_gap_type == {"knowledge": 3, "data": 2, "capability": 3}
    assert fed.by_priority == {"high": 4, "low": 1, "medium": 3}


def test_merge_avoids_double_counting_when_local_in_peer_dict() -> None:
    local = _snap(5, {"knowledge": 5}, {"high": 5})
    fed = merge_fleet_snapshots("uss-a", local, peer_snapshots={"uss-a": local})
    assert fed.total_gaps == 5
    assert fed.contributing_ships == ("uss-a",)


def test_merge_with_no_local() -> None:
    peer1 = _snap(3, {"data": 3}, {"high": 3})
    peer2 = _snap(2, {"capability": 2}, {"low": 2})
    fed = merge_fleet_snapshots(
        "uss-a", local=None, peer_snapshots={"uss-b": peer1, "uss-c": peer2},
    )
    assert fed.total_gaps == 5
    assert sorted(fed.contributing_ships) == ["uss-b", "uss-c"]


def test_merge_top_intents_aggregates_across_ships() -> None:
    s1 = FleetGapSnapshot(
        snapshot_at=0.0, total_gaps=2, by_gap_type={}, by_priority={},
        by_department={}, top_intents=(("alpha", 5), ("beta", 2)),
    )
    s2 = FleetGapSnapshot(
        snapshot_at=0.0, total_gaps=1, by_gap_type={}, by_priority={},
        by_department={}, top_intents=(("alpha", 3),),
    )
    fed = merge_fleet_snapshots("uss-a", s1, peer_snapshots={"uss-b": s2})
    intents = dict(fed.top_intents)
    assert intents["alpha"] == 8
    assert intents["beta"] == 2
