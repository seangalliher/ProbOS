# Copyright 2026 Sean Galliher. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""AD-536: Tests for procedure promotion approval/rejection flow and Level 5 unlock logic."""

from __future__ import annotations

import time

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.procedure_store import ProcedureStore
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
    proc_id: str = "proc-test-001",
    name: str = "Test Procedure",
    compilation_level: int = 4,
    intent_types: list[str] | None = None,
    origin_agent_ids: list[str] | None = None,
) -> Procedure:
    return Procedure(
        id=proc_id,
        name=name,
        description="A test procedure for promotion tests",
        steps=[
            ProcedureStep(step_number=1, action="step one"),
            ProcedureStep(step_number=2, action="step two"),
        ],
        intent_types=intent_types or ["code_review"],
        origin_agent_ids=origin_agent_ids or ["engineer_agent"],
        compilation_level=compilation_level,
        extraction_date=time.time(),
    )


@pytest.fixture
async def store(tmp_path):
    s = ProcedureStore(data_dir=tmp_path)
    await s.start()
    yield s
    await s.stop()


# ===========================================================================
# _max_compilation_level_for_promoted tests
# ===========================================================================


class TestMaxCompilationLevelForPromoted:
    """Tests for CognitiveAgent._max_compilation_level_for_promoted."""

    def test_approved_commander_trust_returns_5(self):
        """Approved + Commander trust (0.8) -> Level 5 unlocked."""
        agent = _make_agent()
        result = agent._max_compilation_level_for_promoted(0.8, "approved")
        assert result == 5

    def test_approved_lieutenant_trust_returns_4(self):
        """Approved + Lieutenant trust (0.6) -> stays at Level 4 (base)."""
        agent = _make_agent()
        result = agent._max_compilation_level_for_promoted(0.6, "approved")
        assert result == 4

    def test_private_commander_trust_returns_4(self):
        """Private + Commander trust (0.8) -> Level 4 max (no Level 5 for private)."""
        agent = _make_agent()
        result = agent._max_compilation_level_for_promoted(0.8, "private")
        assert result == 4

    def test_approved_ensign_trust_returns_2(self):
        """Approved + Ensign trust (0.3) -> Level 2 max (trust-clamped)."""
        agent = _make_agent()
        result = agent._max_compilation_level_for_promoted(0.3, "approved")
        assert result == 2

    def test_approved_exact_commander_threshold(self):
        """Approved + exactly TRUST_COMMANDER -> Level 5 unlocked."""
        agent = _make_agent()
        result = agent._max_compilation_level_for_promoted(TRUST_COMMANDER, "approved")
        assert result == 5

    def test_rejected_commander_trust_returns_4(self):
        """Rejected + Commander trust -> stays at Level 4 (not approved)."""
        agent = _make_agent()
        result = agent._max_compilation_level_for_promoted(0.8, "rejected")
        assert result == 4


# ===========================================================================
# Approval / Rejection flow tests (ProcedureStore)
# ===========================================================================


class TestApprovalRejectionFlow:
    """Tests for procedure promotion approval and rejection in the store."""

    @pytest.mark.asyncio
    async def test_approve_stores_directive_id(self, store):
        """approve_promotion creates linked directive_id in store."""
        proc = _make_procedure()
        await store.save(proc)

        # Set up metrics to make promotion eligible
        await store._db.execute(
            "UPDATE procedure_records SET total_completions=15, total_selections=20 WHERE id=?",
            (proc.id,),
        )
        await store._db.commit()

        # First request promotion to set status to 'pending'
        await store.request_promotion(proc.id)
        status_before = await store.get_promotion_status(proc.id)
        assert status_before == "pending"

        # Now approve with a directive ID
        await store.approve_promotion(proc.id, "captain", "dir-abc-123")

        status_after = await store.get_promotion_status(proc.id)
        assert status_after == "approved"

        # Verify directive_id is stored
        promoted = await store.get_promoted_procedures()
        assert len(promoted) >= 1
        match = [p for p in promoted if p["procedure_id"] == proc.id]
        assert len(match) == 1
        assert match[0]["directive_id"] == "dir-abc-123"

    @pytest.mark.asyncio
    async def test_reject_stores_reason_and_timestamp(self, store):
        """reject_promotion sets rejection reason and timestamp."""
        proc = _make_procedure(proc_id="proc-reject-001")
        await store.save(proc)
        await store.request_promotion(proc.id)

        await store.reject_promotion(proc.id, "captain", "insufficient coverage")

        status = await store.get_promotion_status(proc.id)
        assert status == "rejected"

        # The rejection reason should be in the DB
        cursor = await store._db.execute(
            "SELECT promotion_rejection_reason, promotion_decided_at, "
            "promotion_decided_by FROM procedure_records WHERE id = ?",
            (proc.id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "insufficient coverage"
        assert row[1] is not None  # timestamp set
        assert row[2] == "captain"

    @pytest.mark.asyncio
    async def test_rejection_anti_loop_cooldown(self, store):
        """Reject then try request_promotion within cooldown -> rejected."""
        proc = _make_procedure(proc_id="proc-cooldown-001")
        await store.save(proc)

        # Boost quality metrics so the procedure is eligible
        for _ in range(15):
            await store._increment_counter(proc.id, "total_selections")
            await store._increment_counter(proc.id, "total_completions")

        # Request and reject
        result1 = await store.request_promotion(proc.id)
        assert result1["eligible"] is True
        await store.reject_promotion(proc.id, "captain", "not ready")

        # Try re-requesting immediately (within cooldown)
        result2 = await store.request_promotion(proc.id)
        assert result2["eligible"] is False
        assert "cooldown" in result2["reason"].lower()

    @pytest.mark.asyncio
    async def test_rejection_sets_status_to_rejected(self, store):
        """After rejection: procedure.promotion_status == 'rejected'."""
        proc = _make_procedure(proc_id="proc-status-check")
        await store.save(proc)
        await store.request_promotion(proc.id)
        await store.reject_promotion(proc.id, "captain", "quality concern")

        status = await store.get_promotion_status(proc.id)
        assert status == "rejected"
