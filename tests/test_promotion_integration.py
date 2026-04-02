# Copyright 2026 Sean Galliher. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""AD-536: Integration tests for procedure promotion combining multiple components."""

from __future__ import annotations

import asyncio
import time

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.procedure_store import ProcedureStore, classify_criticality
from probos.cognitive.procedures import Procedure, ProcedureStep
from probos.config import TRUST_COMMANDER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent() -> CognitiveAgent:
    """Create a bare CognitiveAgent without calling __init__ (avoids runtime deps)."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    return agent


def _make_procedure(
    proc_id: str = "integ-proc-001",
    name: str = "Integration Test Procedure",
    compilation_level: int = 4,
    intent_types: list[str] | None = None,
    origin_agent_ids: list[str] | None = None,
    steps: list[ProcedureStep] | None = None,
) -> Procedure:
    return Procedure(
        id=proc_id,
        name=name,
        description="Integration test procedure",
        steps=steps or [
            ProcedureStep(step_number=1, action="analyze input"),
            ProcedureStep(step_number=2, action="process data"),
        ],
        intent_types=intent_types or ["code_review"],
        origin_agent_ids=origin_agent_ids or ["engineer_agent"],
        compilation_level=compilation_level,
        extraction_date=time.time(),
    )


async def _boost_quality(store: ProcedureStore, proc_id: str, count: int = 15) -> None:
    """Increment selection and completion counters to meet promotion eligibility."""
    for _ in range(count):
        await store._increment_counter(proc_id, "total_selections")
        await store._increment_counter(proc_id, "total_completions")


@pytest.fixture
def store(tmp_path):
    s = ProcedureStore(data_dir=tmp_path)
    asyncio.get_event_loop().run_until_complete(s.start())
    yield s
    asyncio.get_event_loop().run_until_complete(s.stop())


# ===========================================================================
# End-to-end promotion flow
# ===========================================================================


class TestPromotionEndToEnd:
    """Integration tests for the full promotion lifecycle."""

    @pytest.mark.asyncio
    async def test_full_approve_flow(self, store):
        """procedure -> request_promotion -> approve -> get_promoted_procedures returns it."""
        proc = _make_procedure(proc_id="e2e-approve-001")
        await store.save(proc)
        await _boost_quality(store, proc.id)

        # Request promotion
        result = await store.request_promotion(proc.id)
        assert result["eligible"] is True

        # Approve
        await store.approve_promotion(proc.id, "captain", "dir-e2e-001")

        # Verify in promoted list
        promoted = await store.get_promoted_procedures()
        ids = [p["procedure_id"] for p in promoted]
        assert proc.id in ids

        match = [p for p in promoted if p["procedure_id"] == proc.id]
        assert match[0]["decided_by"] == "captain"
        assert match[0]["directive_id"] == "dir-e2e-001"

    @pytest.mark.asyncio
    async def test_full_reject_flow(self, store):
        """procedure -> request_promotion -> reject -> check rejection stored."""
        proc = _make_procedure(proc_id="e2e-reject-001")
        await store.save(proc)
        await _boost_quality(store, proc.id)

        result = await store.request_promotion(proc.id)
        assert result["eligible"] is True

        await store.reject_promotion(proc.id, "captain", "needs more testing")

        status = await store.get_promotion_status(proc.id)
        assert status == "rejected"

        # Verify rejection reason stored in DB
        cursor = await store._db.execute(
            "SELECT promotion_rejection_reason FROM procedure_records WHERE id = ?",
            (proc.id,),
        )
        row = await cursor.fetchone()
        assert row[0] == "needs more testing"


# ===========================================================================
# Level 5 trust gating (combined CognitiveAgent + store)
# ===========================================================================


class TestLevel5TrustGating:
    """Integration tests for Level 5 unlock via _max_compilation_level_for_promoted."""

    def test_approved_commander_trust_unlocks_5(self):
        """Approved + Commander trust (0.8) -> _max_compilation_level_for_promoted returns 5."""
        agent = _make_agent()
        level = agent._max_compilation_level_for_promoted(0.8, "approved")
        assert level == 5

    def test_approved_lieutenant_trust_stays_4(self):
        """Approved + Lieutenant trust (0.6) -> returns 4."""
        agent = _make_agent()
        level = agent._max_compilation_level_for_promoted(0.6, "approved")
        assert level == 4

    def test_private_commander_blocked(self):
        """Private procedure -> Level 5 blocked regardless of trust."""
        agent = _make_agent()
        level = agent._max_compilation_level_for_promoted(0.9, "private")
        assert level == 4

    def test_rejected_high_trust_blocked(self):
        """Rejected procedure -> Level 5 blocked regardless of trust."""
        agent = _make_agent()
        level = agent._max_compilation_level_for_promoted(0.85, "rejected")
        assert level == 4


# ===========================================================================
# Criticality classification + routing
# ===========================================================================


class TestCriticalityRouting:
    """Integration test for classify_criticality with destructive names."""

    def test_destructive_name_returns_critical(self):
        """Procedure with destructive keyword -> CRITICAL classification."""
        proc = _make_procedure(
            proc_id="crit-001",
            name="Delete all user data",
            intent_types=["data_management"],
        )
        crit = classify_criticality(proc)
        assert crit.value == "critical"

    def test_security_role_returns_high(self):
        """Procedure with security agent role -> HIGH classification."""
        proc = _make_procedure(
            proc_id="crit-002",
            name="Audit access logs",
            steps=[
                ProcedureStep(step_number=1, action="scan logs", agent_role="security_analysis"),
            ],
        )
        crit = classify_criticality(proc)
        assert crit.value == "high"


# ===========================================================================
# Rejection cooldown
# ===========================================================================


class TestRejectionCooldown:
    """Integration test for rejection cooldown blocking re-requests."""

    @pytest.mark.asyncio
    async def test_re_request_within_cooldown_blocked(self, store):
        """Rejection cooldown -> re-request within 72h blocked."""
        proc = _make_procedure(proc_id="cooldown-integ-001")
        await store.save(proc)
        await _boost_quality(store, proc.id)

        # Request and reject
        result1 = await store.request_promotion(proc.id)
        assert result1["eligible"] is True
        await store.reject_promotion(proc.id, "captain", "not yet")

        # Re-request immediately
        result2 = await store.request_promotion(proc.id)
        assert result2["eligible"] is False
        assert "cooldown" in result2["reason"].lower()


# ===========================================================================
# Status check after approval
# ===========================================================================


class TestStatusAfterApproval:
    """Verify status transitions are reflected correctly."""

    @pytest.mark.asyncio
    async def test_approved_status(self, store):
        """After approval, get_promotion_status returns 'approved'."""
        proc = _make_procedure(proc_id="status-check-001")
        await store.save(proc)

        # Initial status
        status0 = await store.get_promotion_status(proc.id)
        assert status0 == "private"

        # Request
        await _boost_quality(store, proc.id)
        await store.request_promotion(proc.id)
        status1 = await store.get_promotion_status(proc.id)
        assert status1 == "pending"

        # Approve
        await store.approve_promotion(proc.id, "captain", "dir-status-001")
        status2 = await store.get_promotion_status(proc.id)
        assert status2 == "approved"
