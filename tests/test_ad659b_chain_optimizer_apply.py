"""AD-659b — ChainOptimizer apply path, persistence, dedup, revert, scheduled loop.

Tests:
  1. Persistence roundtrip — analyze persists, restart-equivalent fetch returns same set.
  2. Dedup — re-running analyze() over identical traces does NOT append duplicates.
  3. Apply happy path (low_trust_ceiling) — config mutated, fields populated.
  4. Apply happy path (high_trust_floor) — config mutated, fields populated.
  5. Apply on un-approved proposal → ValueError.
  6. Apply on already-applied proposal → ValueError.
  7. Apply on non-tunable target (chain_step.tier[X]) → ValueError mentioning AD-659b-1.
  8. Revert restores pre_apply_value and clears applied flag.
  9. Scheduled loop fires at least once when interval > 0 (test uses tiny interval).
 10. API: apply endpoint returns 403 when apply_enabled=False; 200 when enabled.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.chain_optimizer import (
    ChainOptimizer,
    OptimizationProposal,
)
from probos.routers import chain_optimizer as router_module
from probos.routers.deps import get_runtime


# Shared fixture builder ----------------------------------------------------

def _make_journal_stub(traces):
    """Build a journal stub that supports record + dedup query + trace fetch.

    Stores recorded proposals in a list and serves get_pending_optimization_proposals
    by filtering it. This mimics the SQLite-backed CognitiveJournal surface enough
    for unit-level testing of ChainOptimizer dedup + persistence behavior.
    """
    stored: list[OptimizationProposal] = []

    async def record(proposal):
        # If proposal_id already in stored, REPLACE semantics
        for i, p in enumerate(stored):
            if p.proposal_id == proposal.proposal_id:
                stored[i] = proposal
                return
        stored.append(proposal)

    async def get_pending(*, detector_name=None, target_parameter=None):
        return [
            p.to_dict() for p in stored
            if p.decision is None
            and (detector_name is None or p.detector_name == detector_name)
            and (target_parameter is None or p.target_parameter == target_parameter)
        ]

    async def get_proposal(proposal_id):
        for p in stored:
            if p.proposal_id == proposal_id:
                return p.to_dict()
        return None

    return SimpleNamespace(
        get_recent_chain_traces=AsyncMock(return_value=traces),
        record_optimization_proposal=record,
        get_pending_optimization_proposals=get_pending,
        get_optimization_proposal=get_proposal,
    ), stored


def _trace(**overrides):
    base = dict(
        chain_id="c", step_index=0, step_name="comprehend",
        sub_task_type="comprehend", tier="standard",
        chain_source="user_request", agent_id="a", agent_type="t",
        intent="x", intent_id="i",
        started_at=0.0, duration_ms=500.0, tokens_used=0,
        success=1, error_truncated="",
        context_keys_declared="", context_keys_passed="",
        context_filter_applied=0, communication_context="formal",
        chain_trust_band="mid", trust_score=0.5,
        boot_camp_active=0, from_captain=0, is_dm=0,
    )
    base.update(overrides)
    return base


def _failing_low_band_traces(n=25):
    return [
        _trace(
            sub_task_type="evaluate", chain_trust_band="low",
            success=1 if i % 4 == 0 else 0,  # 25% success → below floor
        )
        for i in range(n)
    ]


def _make_runtime_with_config():
    """Build a runtime stub carrying a real ChainTuningConfig instance."""
    from probos.config import ChainTuningConfig
    config = SimpleNamespace(chain_tuning=ChainTuningConfig())
    return config


# 1. Persistence ---------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_persists_proposals_to_journal():
    journal, stored = _make_journal_stub(_failing_low_band_traces())
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        config=_make_runtime_with_config(),
    )
    opt = ChainOptimizer(runtime, min_samples_per_group=20)
    new = await opt.analyze()
    assert len(new) >= 1
    assert len(stored) == len(new)
    assert {p.proposal_id for p in stored} == {p.proposal_id for p in new}


# 2. Dedup ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_dedups_on_detector_and_target():
    traces = _failing_low_band_traces()
    journal, stored = _make_journal_stub(traces)
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        config=_make_runtime_with_config(),
    )
    opt = ChainOptimizer(runtime, min_samples_per_group=20)

    first = await opt.analyze()
    second = await opt.analyze()
    assert len(first) >= 1
    assert second == []  # all candidates deduplicated against pending entries
    # Pending list and journal should NOT have grown
    assert len(opt.pending_proposals) == len(first)
    assert len(stored) == len(first)


# 3 & 4. Apply happy path -----------------------------------------------

@pytest.mark.asyncio
async def test_apply_proposal_low_trust_ceiling():
    journal, _ = _make_journal_stub([])
    config = _make_runtime_with_config()
    runtime = SimpleNamespace(cognitive_journal=journal, config=config)
    opt = ChainOptimizer(runtime, apply_enabled=True)

    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal.decision = "approve"
    proposal.decided_by = "captain"
    opt.pending_proposals.append(proposal)

    applied = await opt.apply_proposal(proposal.proposal_id, actor="captain")
    assert applied.applied is True
    assert applied.applied_by == "captain"
    assert applied.pre_apply_value == 0.60
    assert config.chain_tuning.low_trust_ceiling == 0.65


@pytest.mark.asyncio
async def test_apply_proposal_high_trust_floor():
    journal, _ = _make_journal_stub([])
    config = _make_runtime_with_config()
    runtime = SimpleNamespace(cognitive_journal=journal, config=config)
    opt = ChainOptimizer(runtime, apply_enabled=True)

    proposal = OptimizationProposal(
        target_parameter="chain_tuning.high_trust_floor",
        current_value=0.75, proposed_value=0.80,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal.decision = "approve"
    opt.pending_proposals.append(proposal)
    applied = await opt.apply_proposal(proposal.proposal_id)
    assert applied.applied is True
    assert applied.pre_apply_value == 0.75
    assert config.chain_tuning.high_trust_floor == 0.80


# 5 & 6 & 7. Apply error paths ------------------------------------------

@pytest.mark.asyncio
async def test_apply_unapproved_raises():
    journal, _ = _make_journal_stub([])
    runtime = SimpleNamespace(cognitive_journal=journal,
                              config=_make_runtime_with_config())
    opt = ChainOptimizer(runtime, apply_enabled=True)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    opt.pending_proposals.append(proposal)
    with pytest.raises(ValueError, match="not approved"):
        await opt.apply_proposal(proposal.proposal_id)


@pytest.mark.asyncio
async def test_apply_already_applied_raises():
    journal, _ = _make_journal_stub([])
    runtime = SimpleNamespace(cognitive_journal=journal,
                              config=_make_runtime_with_config())
    opt = ChainOptimizer(runtime, apply_enabled=True)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal.decision = "approve"
    opt.pending_proposals.append(proposal)
    await opt.apply_proposal(proposal.proposal_id)
    with pytest.raises(ValueError, match="already applied"):
        await opt.apply_proposal(proposal.proposal_id)


@pytest.mark.asyncio
async def test_apply_non_tunable_target_defers_to_ad659b1():
    journal, _ = _make_journal_stub([])
    runtime = SimpleNamespace(cognitive_journal=journal,
                              config=_make_runtime_with_config())
    opt = ChainOptimizer(runtime, apply_enabled=True)
    proposal = OptimizationProposal(
        target_parameter="chain_step.tier[evaluate]",
        current_value="standard", proposed_value="fast",
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="latency_p95_regression",
    )
    proposal.decision = "approve"
    opt.pending_proposals.append(proposal)
    with pytest.raises(ValueError, match="AD-659b-1"):
        await opt.apply_proposal(proposal.proposal_id)


# 8. Revert ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_revert_restores_pre_apply_value():
    journal, _ = _make_journal_stub([])
    config = _make_runtime_with_config()
    runtime = SimpleNamespace(cognitive_journal=journal, config=config)
    opt = ChainOptimizer(runtime, apply_enabled=True)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal.decision = "approve"
    opt.pending_proposals.append(proposal)
    await opt.apply_proposal(proposal.proposal_id)
    assert config.chain_tuning.low_trust_ceiling == 0.65
    reverted = await opt.revert_proposal(proposal.proposal_id)
    assert reverted.applied is False
    assert config.chain_tuning.low_trust_ceiling == 0.60


# 9. Scheduled loop -------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduled_loop_fires_at_least_once():
    journal, stored = _make_journal_stub(_failing_low_band_traces())
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        config=_make_runtime_with_config(),
    )
    opt = ChainOptimizer(
        runtime, min_samples_per_group=20,
        analysis_interval_seconds=1,
    )
    opt.start_scheduled_loop()
    # Wait long enough for one iteration to complete (analyze, then sleep 1s).
    await asyncio.sleep(0.2)
    await opt.stop()
    # At least one proposal should have been written by the loop.
    assert len(stored) >= 1


# 10. REST: apply endpoint -----------------------------------------------

def test_router_apply_endpoint_403_when_disabled_and_200_when_enabled():
    journal_disabled, _ = _make_journal_stub([])
    config = _make_runtime_with_config()
    runtime_disabled = SimpleNamespace(
        cognitive_journal=journal_disabled, config=config,
    )
    opt_disabled = ChainOptimizer(runtime_disabled, apply_enabled=False)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal.decision = "approve"
    opt_disabled.pending_proposals.append(proposal)
    runtime_disabled.chain_optimizer = opt_disabled

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[get_runtime] = lambda: runtime_disabled
    client = TestClient(app)
    r = client.post(
        f"/api/chain-optimizer/proposals/{proposal.proposal_id}/apply",
        json={"actor": "captain"},
    )
    assert r.status_code == 403
    assert "apply_enabled=False" in r.json()["detail"]

    # Now enable apply and rerun
    journal_enabled, _ = _make_journal_stub([])
    config2 = _make_runtime_with_config()
    runtime_enabled = SimpleNamespace(
        cognitive_journal=journal_enabled, config=config2,
    )
    opt_enabled = ChainOptimizer(runtime_enabled, apply_enabled=True)
    proposal2 = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal2.decision = "approve"
    opt_enabled.pending_proposals.append(proposal2)
    runtime_enabled.chain_optimizer = opt_enabled

    app2 = FastAPI()
    app2.include_router(router_module.router)
    app2.dependency_overrides[get_runtime] = lambda: runtime_enabled
    client2 = TestClient(app2)
    r2 = client2.post(
        f"/api/chain-optimizer/proposals/{proposal2.proposal_id}/apply",
        json={"actor": "captain"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["applied"] is True
    assert body["proposal"]["applied"] is True
    assert config2.chain_tuning.low_trust_ceiling == 0.65
