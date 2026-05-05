"""AD-659c — OptimizationCounselor watchdog + decision persistence.

Tests:
  1. EventType registration: 3 new values present, exact string values.
  2. ChainOptimizer.apply_proposal emits OPTIMIZATION_PROPOSAL_APPLIED with
     full payload (proposal_id, target_parameter, pre/proposed values, actor).
  3. ChainOptimizer.revert_proposal emits OPTIMIZATION_PROPOSAL_REVERTED.
  4. Journal record_optimization_decision + get_recent_optimization_decisions
     round-trip with real CognitiveJournal against tmp_path (all 11 fields).
  5. Journal get_recent_optimization_decisions filters by proposal_id.
  6. OptimizationDecision frozen + to_dict round-trip.
  7. _compute_success_rate_window filters traces by [end_time - window, end_time].
  8. _evaluate_and_record records "skipped" when baseline_n < min_samples.
  9. _evaluate_and_record records "no_regression" when drop < floor.
 10. _evaluate_and_record records "regression" when drop >= floor; emits
     OPTIMIZATION_REGRESSION_DETECTED; does NOT call revert when
     auto_revert_enabled=False.
 11. _evaluate_and_record records "regression" + calls
     optimizer.revert_proposal when auto_revert_enabled=True; auto_revert_succeeded=1.
 12. ChainOptimizerCounselorConfig defaults; field validators reject bad values.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.chain_optimizer import (
    ChainOptimizer,
    OptimizationProposal,
)
from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.optimization_counselor import (
    OptimizationCounselor,
    OptimizationDecision,
)
from probos.config import ChainOptimizerCounselorConfig
from probos.events import EventType


def _make_runtime_with_chain_tuning():
    """Real ChainTuningConfig wrapped in a runtime stub."""
    from probos.config import ChainTuningConfig
    return SimpleNamespace(chain_tuning=ChainTuningConfig())


def _trace(*, started_at: float, success: int = 1) -> dict:
    return {
        "chain_id": "c", "step_index": 0, "step_name": "comprehend",
        "sub_task_type": "comprehend", "tier": "standard",
        "chain_source": "user_request", "agent_id": "a", "agent_type": "t",
        "intent": "x", "intent_id": "i",
        "started_at": started_at, "duration_ms": 500.0, "tokens_used": 0,
        "success": success, "error_truncated": "",
        "context_keys_declared": "", "context_keys_passed": "",
        "context_filter_applied": 0, "communication_context": "formal",
        "chain_trust_band": "mid", "trust_score": 0.5,
        "boot_camp_active": 0, "from_captain": 0, "is_dm": 0,
    }


# 1 ----------------------------------------------------------------------

def test_event_types_registered():
    assert EventType.OPTIMIZATION_PROPOSAL_APPLIED.value == "optimization_proposal_applied"
    assert EventType.OPTIMIZATION_PROPOSAL_REVERTED.value == "optimization_proposal_reverted"
    assert EventType.OPTIMIZATION_REGRESSION_DETECTED.value == "optimization_regression_detected"


# 2 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_proposal_emits_applied_event():
    config = _make_runtime_with_chain_tuning()
    runtime = SimpleNamespace(cognitive_journal=None, config=config)
    captured: list[tuple] = []

    def emit(event_type, data):
        captured.append((event_type, data))

    opt = ChainOptimizer(runtime, apply_enabled=True, emit_event=emit)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
        decision="approve",
    )
    opt.pending_proposals.append(proposal)
    await opt.apply_proposal(proposal.proposal_id, actor="captain")
    assert len(captured) == 1
    et, payload = captured[0]
    assert et == EventType.OPTIMIZATION_PROPOSAL_APPLIED
    assert payload["proposal_id"] == proposal.proposal_id
    assert payload["target_parameter"] == "chain_tuning.low_trust_ceiling"
    assert payload["pre_apply_value"] == 0.60
    assert payload["proposed_value"] == 0.65
    assert payload["actor"] == "captain"
    assert payload["detector_name"] == "success_rate_floor_breach"


# 3 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revert_proposal_emits_reverted_event():
    config = _make_runtime_with_chain_tuning()
    runtime = SimpleNamespace(cognitive_journal=None, config=config)
    captured: list[tuple] = []

    def emit(event_type, data):
        captured.append((event_type, data))

    opt = ChainOptimizer(runtime, apply_enabled=True, emit_event=emit)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.high_trust_floor",
        current_value=0.75, proposed_value=0.80,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="d",
        decision="approve",
    )
    opt.pending_proposals.append(proposal)
    await opt.apply_proposal(proposal.proposal_id)
    captured.clear()
    await opt.revert_proposal(proposal.proposal_id, actor="optimization_counselor")
    assert len(captured) == 1
    et, payload = captured[0]
    assert et == EventType.OPTIMIZATION_PROPOSAL_REVERTED
    assert payload["proposal_id"] == proposal.proposal_id
    assert payload["actor"] == "optimization_counselor"
    assert payload["reverted_to"] == 0.75
    assert payload["from_value"] == 0.80


# 4 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_journal_decision_roundtrip(tmp_path: Path):
    journal = CognitiveJournal(db_path=str(tmp_path / "j.db"))
    await journal.start()
    try:
        await journal.record_optimization_decision(
            proposal_id="p1",
            decided_at=12345.0,
            decision="regression",
            baseline_success_rate=0.85,
            post_success_rate=0.65,
            drop_amount=0.20,
            sample_count_baseline=50,
            sample_count_post=45,
            auto_revert_attempted=True,
            auto_revert_succeeded=True,
            detail="drop=0.20 >= floor 0.10",
        )
        rows = await journal.get_recent_optimization_decisions(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["proposal_id"] == "p1"
        assert row["decision"] == "regression"
        assert row["baseline_success_rate"] == pytest.approx(0.85)
        assert row["post_success_rate"] == pytest.approx(0.65)
        assert row["drop_amount"] == pytest.approx(0.20)
        assert row["sample_count_baseline"] == 50
        assert row["sample_count_post"] == 45
        assert row["auto_revert_attempted"] == 1
        assert row["auto_revert_succeeded"] == 1
        assert row["detail"] == "drop=0.20 >= floor 0.10"
    finally:
        await journal.stop()


# 5 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_journal_decision_filter_by_proposal_id(tmp_path: Path):
    journal = CognitiveJournal(db_path=str(tmp_path / "j.db"))
    await journal.start()
    try:
        for pid in ("p1", "p1", "p2"):
            await journal.record_optimization_decision(
                proposal_id=pid, decided_at=time.time(), decision="no_regression",
            )
        rows_p1 = await journal.get_recent_optimization_decisions(proposal_id="p1")
        rows_p2 = await journal.get_recent_optimization_decisions(proposal_id="p2")
        assert len(rows_p1) == 2
        assert len(rows_p2) == 1
    finally:
        await journal.stop()


# 6 ----------------------------------------------------------------------

def test_optimization_decision_frozen_and_to_dict():
    d = OptimizationDecision(
        proposal_id="x", decided_at=1.0, decision="regression",
        baseline_success_rate=0.8, post_success_rate=0.6, drop_amount=0.2,
        sample_count_baseline=30, sample_count_post=30,
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        d.proposal_id = "y"  # type: ignore[misc]
    payload = d.to_dict()
    assert payload["proposal_id"] == "x"
    assert payload["decision"] == "regression"
    assert payload["sample_count_baseline"] == 30


# 7 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_success_rate_window_filters_by_time():
    now = 1000.0
    traces = [
        _trace(started_at=now - 1900, success=1),  # outside window (1800s)
        _trace(started_at=now - 100, success=1),
        _trace(started_at=now - 50, success=0),
        _trace(started_at=now - 25, success=1),
    ]
    journal = SimpleNamespace(
        get_recent_chain_traces=AsyncMock(return_value=traces),
    )
    runtime = SimpleNamespace(cognitive_journal=journal)
    counselor = OptimizationCounselor(runtime, observation_window_seconds=1800)
    rate, n = await counselor._compute_success_rate_window(
        end_time=now, window_seconds=1800.0,
    )
    assert n == 3  # the 1900s-old trace is excluded
    assert rate == pytest.approx(2 / 3)


# 8 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_records_skipped_when_insufficient_samples():
    journal = MagicMock()
    journal.record_optimization_decision = AsyncMock()
    runtime = SimpleNamespace(cognitive_journal=journal, emit_event=lambda *a, **k: None)
    counselor = OptimizationCounselor(runtime, min_samples_per_window=20)
    await counselor._evaluate_and_record(
        proposal_id="p1",
        baseline_rate=0.9, baseline_n=5,
        post_rate=0.5, post_n=5,
        decided_at=1.0,
    )
    journal.record_optimization_decision.assert_awaited_once()
    kwargs = journal.record_optimization_decision.await_args.kwargs
    assert kwargs["decision"] == "skipped"
    assert kwargs["sample_count_baseline"] == 5


# 9 ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_records_no_regression_when_drop_below_floor():
    journal = MagicMock()
    journal.record_optimization_decision = AsyncMock()
    captured: list = []
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        emit_event=lambda et, data: captured.append((et, data)),
    )
    counselor = OptimizationCounselor(
        runtime, min_samples_per_window=10, success_rate_drop_floor=0.10,
    )
    await counselor._evaluate_and_record(
        proposal_id="p1",
        baseline_rate=0.85, baseline_n=30,
        post_rate=0.80, post_n=30,  # drop=0.05, below 0.10 floor
        decided_at=1.0,
    )
    journal.record_optimization_decision.assert_awaited_once()
    kwargs = journal.record_optimization_decision.await_args.kwargs
    assert kwargs["decision"] == "no_regression"
    assert captured == []  # no regression event emitted


# 10 ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_records_regression_no_revert_when_auto_revert_disabled():
    journal = MagicMock()
    journal.record_optimization_decision = AsyncMock()
    optimizer = MagicMock()
    optimizer.revert_proposal = AsyncMock()
    captured: list = []
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        chain_optimizer=optimizer,
        emit_event=lambda et, data: captured.append((et, data)),
    )
    counselor = OptimizationCounselor(
        runtime,
        min_samples_per_window=10,
        success_rate_drop_floor=0.10,
        auto_revert_enabled=False,
    )
    await counselor._evaluate_and_record(
        proposal_id="p1",
        baseline_rate=0.90, baseline_n=30,
        post_rate=0.60, post_n=30,  # drop=0.30, well above floor
        decided_at=1.0,
    )
    journal.record_optimization_decision.assert_awaited_once()
    kwargs = journal.record_optimization_decision.await_args.kwargs
    assert kwargs["decision"] == "regression"
    assert kwargs["auto_revert_attempted"] is False
    optimizer.revert_proposal.assert_not_awaited()
    # Regression event emitted.
    assert any(
        et == EventType.OPTIMIZATION_REGRESSION_DETECTED for et, _ in captured
    )


# 11 ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_records_regression_and_reverts_when_auto_revert_enabled():
    journal = MagicMock()
    journal.record_optimization_decision = AsyncMock()
    optimizer = MagicMock()
    optimizer.revert_proposal = AsyncMock()
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        chain_optimizer=optimizer,
        emit_event=lambda *a, **k: None,
    )
    counselor = OptimizationCounselor(
        runtime,
        min_samples_per_window=10,
        success_rate_drop_floor=0.10,
        auto_revert_enabled=True,
    )
    await counselor._evaluate_and_record(
        proposal_id="p1",
        baseline_rate=0.90, baseline_n=30,
        post_rate=0.60, post_n=30,
        decided_at=1.0,
    )
    optimizer.revert_proposal.assert_awaited_once_with(
        "p1", actor="optimization_counselor",
    )
    kwargs = journal.record_optimization_decision.await_args.kwargs
    assert kwargs["decision"] == "regression"
    assert kwargs["auto_revert_attempted"] is True
    assert kwargs["auto_revert_succeeded"] is True


# 12 ---------------------------------------------------------------------

def test_chain_optimizer_counselor_config_defaults_and_validators():
    cfg = ChainOptimizerCounselorConfig()
    assert cfg.enabled is False
    assert cfg.auto_revert_enabled is False
    assert cfg.baseline_window_seconds == 1800.0
    assert cfg.observation_window_seconds == 1800.0
    assert cfg.success_rate_drop_floor == 0.10
    assert cfg.min_samples_per_window == 20
    with pytest.raises(Exception):
        ChainOptimizerCounselorConfig(observation_window_seconds=0.0)
    with pytest.raises(Exception):
        ChainOptimizerCounselorConfig(success_rate_drop_floor=1.5)
    with pytest.raises(Exception):
        ChainOptimizerCounselorConfig(min_samples_per_window=0)
