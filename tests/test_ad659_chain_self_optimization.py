"""AD-659 v1: Cognitive Chain Self-Optimization tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.chain_optimizer import (
    ChainOptimizer,
    OptimizationProposal,
    detect_high_error_rate_by_chain_source,
    detect_latency_p95_regression,
    detect_success_rate_floor_breach,
)
from probos.routers import chain_optimizer as router_module
from probos.routers.deps import get_runtime


def _trace(**overrides):
    """Build a chain-trace row dict with sensible defaults."""
    base = {
        "step_name": "evaluate",
        "tier": "standard",
        "sub_task_type": "evaluate",
        "chain_trust_band": "mid",
        "chain_source": "user_request",
        "duration_ms": 1000.0,
        "success": 1,
    }
    base.update(overrides)
    return base


# --- Detector tests --------------------------------------------------------


def test_detect_latency_p95_regression_happy_path():
    # 25 slow traces all above floor → p95 trivially exceeds 10000ms
    traces = [
        _trace(step_name="dm_compose", tier="standard", duration_ms=12000.0)
        for _ in range(25)
    ]
    proposals = detect_latency_p95_regression(
        traces, p95_floor_ms=10000.0, min_samples=20,
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.target_parameter.startswith("chain_step.tier[")
    assert p.proposed_value == "fast"
    assert p.current_value == "standard"
    assert p.risk_level == "medium"
    assert p.detector_name == "latency_p95_regression"


def test_detect_latency_p95_regression_below_min_samples_returns_empty():
    traces = [
        _trace(step_name="dm_compose", tier="standard", duration_ms=20000.0)
        for _ in range(19)
    ]
    proposals = detect_latency_p95_regression(
        traces, p95_floor_ms=10000.0, min_samples=20,
    )
    assert proposals == []


def test_detect_success_rate_floor_breach_low_band():
    # 25 traces in low band, 50/50 success → 0.5 < 0.7 floor → propose
    traces = []
    for i in range(25):
        traces.append(_trace(
            sub_task_type="evaluate",
            chain_trust_band="low",
            success=1 if i % 2 == 0 else 0,
        ))
    proposals = detect_success_rate_floor_breach(
        traces, success_floor=0.7, min_samples=20,
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.target_parameter == "chain_tuning.low_trust_ceiling"
    assert p.current_value == 0.60
    assert p.proposed_value == 0.65
    assert p.risk_level == "medium"


def test_detect_success_rate_floor_breach_mid_band_no_proposal():
    # mid band has no single-knob fix → skipped
    traces = []
    for i in range(25):
        traces.append(_trace(
            sub_task_type="evaluate",
            chain_trust_band="mid",
            success=1 if i % 2 == 0 else 0,
        ))
    proposals = detect_success_rate_floor_breach(
        traces, success_floor=0.7, min_samples=20,
    )
    assert proposals == []


def test_detect_high_error_rate_by_chain_source_happy_path():
    # 25 traces from "dm_comprehension"; 60% errors → > 0.3 ceiling
    traces = []
    for i in range(25):
        traces.append(_trace(
            chain_source="dm_comprehension",
            success=0 if i < 15 else 1,  # 15/25 errors = 0.6
        ))
    proposals = detect_high_error_rate_by_chain_source(
        traces, error_rate_ceiling=0.3, min_samples=20,
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.target_parameter.startswith("chain_source.review[")
    assert p.risk_level == "low"
    assert p.detector_name == "high_error_rate_by_chain_source"


# --- Service tests ---------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_optimizer_analyze_aggregates_all_detectors():
    # Build a trace list that triggers all three detectors
    traces = []
    # latency: 25 slow traces all above floor
    for i in range(25):
        traces.append(_trace(
            step_name="dm_compose", tier="standard",
            duration_ms=12000.0,
            sub_task_type="latency_only",  # avoid double-trigger on success
            chain_trust_band="mid",
            chain_source="user_request",
            success=1,
        ))
    # success: 25 low-band failures
    for i in range(25):
        traces.append(_trace(
            step_name="evaluate", tier="fast",
            sub_task_type="evaluate",
            chain_trust_band="low",
            chain_source="user_request",
            duration_ms=500.0,
            success=1 if i % 2 == 0 else 0,
        ))
    # error rate: 25 from "broken_source", 60% errors
    for i in range(25):
        traces.append(_trace(
            step_name="comprehend", tier="fast",
            sub_task_type="comprehend",
            chain_trust_band="mid",
            chain_source="broken_source",
            duration_ms=500.0,
            success=0 if i < 15 else 1,
        ))

    journal = SimpleNamespace(
        get_recent_chain_traces=AsyncMock(return_value=traces),
        record_optimization_proposal=AsyncMock(return_value=None),
        get_pending_optimization_proposals=AsyncMock(return_value=[]),
    )
    runtime = SimpleNamespace(cognitive_journal=journal)
    opt = ChainOptimizer(runtime, min_samples_per_group=20)

    new = await opt.analyze()
    assert len(new) >= 3
    detector_names = {p.detector_name for p in new}
    assert "latency_p95_regression" in detector_names
    assert "success_rate_floor_breach" in detector_names
    assert "high_error_rate_by_chain_source" in detector_names

    # list_pending returns all undecided
    pending = opt.list_pending()
    assert len(pending) == len(opt.pending_proposals)

    # decide flips fields (AD-659b: now async + persists)
    target = pending[0]
    decided = await opt.decide(target.proposal_id, "approve", actor="captain")
    assert decided is not None
    assert decided.decision == "approve"
    assert decided.decided_by == "captain"
    assert decided.decided_at is not None

    # decided proposal no longer in list_pending
    assert target not in opt.list_pending()


@pytest.mark.asyncio
async def test_chain_optimizer_apply_proposal_disabled_raises_runtime_error():
    """AD-659b: apply_enabled=False → RuntimeError from apply_proposal."""
    opt = ChainOptimizer(SimpleNamespace(), apply_enabled=False)
    with pytest.raises(RuntimeError, match="apply_enabled=False"):
        await opt.apply_proposal("anything")


# --- API tests -------------------------------------------------------------


def test_chain_optimizer_router_list_and_decide_endpoints():
    # Build a runtime stub carrying a real ChainOptimizer with one proposal
    opt = ChainOptimizer(SimpleNamespace())
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60,
        proposed_value=0.65,
        rationale="test",
        supporting_metric="test",
        risk_level="medium",
        detector_name="success_rate_floor_breach",
    )
    opt.pending_proposals.append(proposal)
    runtime_stub = SimpleNamespace(chain_optimizer=opt)

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[get_runtime] = lambda: runtime_stub

    client = TestClient(app)

    # GET /proposals → list contains our proposal
    r = client.get("/api/chain-optimizer/proposals")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert len(body["proposals"]) == 1
    assert body["proposals"][0]["proposal_id"] == proposal.proposal_id

    # POST decide → applied: False
    r = client.post(
        f"/api/chain-optimizer/proposals/{proposal.proposal_id}/decide",
        json={"decision": "approve", "actor": "captain"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "recorded"
    assert body["applied"] is False
    assert body["proposal"]["decision"] == "approve"

    # GET pending only → empty (proposal now decided)
    r = client.get("/api/chain-optimizer/proposals")
    assert r.status_code == 200
    assert r.json()["proposals"] == []

    # GET include_decided=true → still has it
    r = client.get("/api/chain-optimizer/proposals?include_decided=true")
    assert r.status_code == 200
    assert len(r.json()["proposals"]) == 1

    # POST garbage decision → 400
    r = client.post(
        f"/api/chain-optimizer/proposals/{proposal.proposal_id}/decide",
        json={"decision": "garbage"},
    )
    assert r.status_code == 400

    # POST against missing id → 404
    r = client.post(
        "/api/chain-optimizer/proposals/nonexistent/decide",
        json={"decision": "approve"},
    )
    assert r.status_code == 404
