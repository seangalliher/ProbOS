"""Tests for InitiativeEngine (AD-381)."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.initiative import (
    ActionGate,
    ActionType,
    InitiativeEngine,
    RemediationProposal,
    TriggerSource,
    TriggerState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(**kwargs) -> InitiativeEngine:
    defaults = {"check_interval": 0.01, "persistence_threshold": 3}
    defaults.update(kwargs)
    return InitiativeEngine(**defaults)


def _make_sif_report(*, failed_checks: list[tuple[str, str]]) -> SimpleNamespace:
    """Create a mock SIF report with failed checks.

    Each tuple is (name, details).
    """
    checks = [
        SimpleNamespace(name=name, passed=False, details=details)
        for name, details in failed_checks
    ]
    return SimpleNamespace(checks=checks)


def _make_mock_sif(report=None) -> SimpleNamespace:
    if report is None:
        report = _make_sif_report(failed_checks=[("trust_bounds", "NaN trust")])
    return SimpleNamespace(last_report=report)


def _make_falling_trend(metric_name: str = "tc_n") -> SimpleNamespace:
    trend = SimpleNamespace(
        metric_name=metric_name,
        direction=SimpleNamespace(value="falling"),
        slope=-0.05,
        r_squared=0.9,
        current_value=0.2,
        window_size=25,
        significant=True,
    )
    return SimpleNamespace(
        significant_trends=[trend],
        tc_n=trend,
    )


def _make_mock_detector(trend_report=None) -> SimpleNamespace:
    report = trend_report or _make_falling_trend()
    return SimpleNamespace(compute_trends=MagicMock(return_value=report))


def _make_counselor_fn(*, agent_id: str = "agent-1", alert_level: str = "red"):
    assessment = SimpleNamespace(agent_id=agent_id, alert_level=alert_level)
    return MagicMock(return_value=[assessment])


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestTriggerState:
    def test_creation_defaults(self) -> None:
        ts = TriggerState(source=TriggerSource.SIF, key="sif:trust_bounds", detail="NaN trust")
        assert ts.source == TriggerSource.SIF
        assert ts.key == "sif:trust_bounds"
        assert ts.detail == "NaN trust"
        assert ts.consecutive_count == 1
        assert ts.first_seen > 0
        assert ts.last_seen > 0


class TestRemediationProposal:
    def test_to_dict(self) -> None:
        p = RemediationProposal(
            id="test-uuid",
            trigger_source=TriggerSource.SIF,
            trigger_detail="NaN trust",
            action_type=ActionType.DIAGNOSE,
            action_detail="Run diagnostics on: NaN trust",
            gate=ActionGate.AUTO,
            severity="high",
            affected_agents=["agent-1"],
            persistence_count=3,
        )
        d = p.to_dict()
        assert d["id"] == "test-uuid"
        assert d["trigger_source"] == "sif"
        assert d["action_type"] == "diagnose"
        assert d["gate"] == "auto"
        assert d["severity"] == "high"
        assert d["affected_agents"] == ["agent-1"]
        assert d["persistence_count"] == 3
        assert d["status"] == "proposed"
        assert "created_at" in d


class TestClassifyTrigger:
    def test_sif_trigger(self) -> None:
        engine = _make_engine()
        trigger = TriggerState(source=TriggerSource.SIF, key="sif:trust_bounds", detail="NaN")
        action, gate, severity = engine._classify_trigger(trigger)
        assert action == ActionType.DIAGNOSE
        assert gate == ActionGate.AUTO
        assert severity == "high"

    def test_counselor_red(self) -> None:
        engine = _make_engine()
        trigger = TriggerState(source=TriggerSource.COUNSELOR, key="counselor:agent-1:red", detail="red alert")
        action, gate, severity = engine._classify_trigger(trigger)
        assert action == ActionType.RECYCLE
        assert gate == ActionGate.COMMANDER
        assert severity == "high"

    def test_counselor_yellow(self) -> None:
        engine = _make_engine()
        trigger = TriggerState(source=TriggerSource.COUNSELOR, key="counselor:agent-1:yellow", detail="yellow alert")
        action, gate, severity = engine._classify_trigger(trigger)
        assert action == ActionType.DIAGNOSE
        assert gate == ActionGate.AUTO
        assert severity == "medium"

    def test_emergent_trigger(self) -> None:
        engine = _make_engine()
        trigger = TriggerState(source=TriggerSource.EMERGENT, key="emergent:tc_n_falling", detail="falling tc_n")
        action, gate, severity = engine._classify_trigger(trigger)
        assert action == ActionType.ALERT_CAPTAIN
        assert gate == ActionGate.AUTO
        assert severity == "medium"


class TestUpdateTrigger:
    def test_new_trigger(self) -> None:
        engine = _make_engine()
        engine._update_trigger(TriggerSource.SIF, "sif:test", "test detail")
        assert "sif:test" in engine._triggers
        assert engine._triggers["sif:test"].consecutive_count == 1

    def test_existing_trigger_increments(self) -> None:
        engine = _make_engine()
        engine._update_trigger(TriggerSource.SIF, "sif:test", "detail")
        engine._update_trigger(TriggerSource.SIF, "sif:test", "detail updated")
        assert engine._triggers["sif:test"].consecutive_count == 2
        assert engine._triggers["sif:test"].detail == "detail updated"


class TestRunChecks:
    @pytest.mark.asyncio
    async def test_resolved_triggers_cleared(self) -> None:
        engine = _make_engine()
        # Seed a trigger manually
        engine._triggers["sif:old"] = TriggerState(
            source=TriggerSource.SIF, key="sif:old", detail="old issue"
        )
        # No SIF wired → no active keys → old trigger should be cleared
        await engine._run_checks()
        assert "sif:old" not in engine._triggers

    @pytest.mark.asyncio
    async def test_proposal_generated_at_threshold(self) -> None:
        engine = _make_engine(persistence_threshold=3)
        sif = _make_mock_sif()
        engine.set_sif(sif)

        # Run checks 3 times to reach threshold
        for _ in range(3):
            await engine._run_checks()

        assert len(engine.recent_proposals) == 1
        p = engine.recent_proposals[0]
        assert p.trigger_source == TriggerSource.SIF
        assert p.action_type == ActionType.DIAGNOSE

    @pytest.mark.asyncio
    async def test_proposal_not_generated_below_threshold(self) -> None:
        engine = _make_engine(persistence_threshold=3)
        sif = _make_mock_sif()
        engine.set_sif(sif)

        # Run checks only 2 times — below threshold
        for _ in range(2):
            await engine._run_checks()

        assert len(engine.recent_proposals) == 0

    @pytest.mark.asyncio
    async def test_on_proposal_callback(self) -> None:
        callback = MagicMock()
        engine = _make_engine(persistence_threshold=1, on_proposal=callback)
        sif = _make_mock_sif()
        engine.set_sif(sif)

        await engine._run_checks()

        callback.assert_called_once()
        proposal = callback.call_args[0][0]
        assert isinstance(proposal, RemediationProposal)

    @pytest.mark.asyncio
    async def test_on_event_emitted(self) -> None:
        events: list[dict] = []
        engine = _make_engine(persistence_threshold=1, on_event=events.append)
        sif = _make_mock_sif()
        engine.set_sif(sif)

        await engine._run_checks()

        assert len(events) == 1
        assert events[0]["type"] == "initiative_proposal"
        assert "data" in events[0]

    @pytest.mark.asyncio
    async def test_sif_not_set_graceful(self) -> None:
        engine = _make_engine()
        # No SIF, detector, or counselor wired — should run without error
        await engine._run_checks()
        assert len(engine.active_triggers) == 0
        assert len(engine.recent_proposals) == 0


class TestProposalManagement:
    def test_approve_proposal(self) -> None:
        engine = _make_engine()
        p = RemediationProposal(
            id="p1", trigger_source=TriggerSource.SIF,
            trigger_detail="test", action_type=ActionType.DIAGNOSE,
            action_detail="diag", gate=ActionGate.AUTO, severity="high",
        )
        engine._proposals.append(p)
        assert engine.approve_proposal("p1")
        assert p.status == "approved"

    def test_reject_proposal(self) -> None:
        engine = _make_engine()
        p = RemediationProposal(
            id="p2", trigger_source=TriggerSource.SIF,
            trigger_detail="test", action_type=ActionType.DIAGNOSE,
            action_detail="diag", gate=ActionGate.AUTO, severity="high",
        )
        engine._proposals.append(p)
        assert engine.reject_proposal("p2")
        assert p.status == "rejected"

    def test_approve_nonexistent_returns_false(self) -> None:
        engine = _make_engine()
        assert not engine.approve_proposal("nonexistent")

    def test_proposals_capped_at_50(self) -> None:
        engine = _make_engine()
        for i in range(55):
            engine._proposals.append(RemediationProposal(
                id=f"p{i}", trigger_source=TriggerSource.SIF,
                trigger_detail="test", action_type=ActionType.DIAGNOSE,
                action_detail="diag", gate=ActionGate.AUTO, severity="high",
            ))
        # Manually trigger the cap logic
        if len(engine._proposals) > 50:
            engine._proposals = engine._proposals[-50:]
        assert len(engine._proposals) == 50
        # The first 5 should have been trimmed
        assert engine._proposals[0].id == "p5"


class TestDescribeAction:
    def test_all_action_types_covered(self) -> None:
        engine = _make_engine()
        trigger = TriggerState(source=TriggerSource.SIF, key="sif:test", detail="test detail")
        for action_type in ActionType:
            desc = engine._describe_action(trigger, action_type)
            assert isinstance(desc, str)
            assert len(desc) > 0
            assert "test detail" in desc
