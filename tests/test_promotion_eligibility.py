"""AD-536: Promotion Eligibility tests (10 tests).

Tests ProcedureStore.request_promotion() validation logic:
compilation level, completions, effective rate, status guards, and cooldown.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta

import pytest

from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure, ProcedureStep


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_step(step_number: int = 1, action: str = "do thing") -> ProcedureStep:
    return ProcedureStep(step_number=step_number, action=action)


def _make_procedure(proc_id: str = "promo-1", **kwargs) -> Procedure:
    defaults = dict(
        id=proc_id,
        name="Promotable Procedure",
        description="A procedure for promotion tests",
        compilation_level=4,
        intent_types=["test"],
        steps=[_make_step()],
    )
    defaults.update(kwargs)
    return Procedure(**defaults)


@pytest.fixture
def store(tmp_path):
    s = ProcedureStore(data_dir=tmp_path)
    asyncio.get_event_loop().run_until_complete(s.start())
    yield s
    asyncio.get_event_loop().run_until_complete(s.stop())


async def _save_with_metrics(
    store: ProcedureStore,
    proc_id: str = "promo-1",
    compilation_level: int = 4,
    total_completions: int = 15,
    total_selections: int = 20,
    promotion_status: str = "private",
    decided_at: str | None = None,
    rejection_reason: str | None = None,
    **proc_kwargs,
) -> None:
    """Save a procedure and manually set its quality/promotion columns."""
    proc = _make_procedure(proc_id, compilation_level=compilation_level, **proc_kwargs)
    await store.save(proc)
    updates = [
        f"total_completions = {total_completions}",
        f"total_selections = {total_selections}",
        f"promotion_status = '{promotion_status}'",
    ]
    if decided_at is not None:
        updates.append(f"promotion_decided_at = '{decided_at}'")
    if rejection_reason is not None:
        updates.append(f"promotion_rejection_reason = '{rejection_reason}'")
    sql = f"UPDATE procedure_records SET {', '.join(updates)} WHERE id = ?"
    await store._db.execute(sql, (proc_id,))
    await store._db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPromotionEligibility:
    """Tests for ProcedureStore.request_promotion()."""

    @pytest.mark.asyncio
    async def test_eligible_procedure(self, store):
        """Level 4+, sufficient completions, good effective rate -> eligible."""
        await _save_with_metrics(store, total_completions=15, total_selections=20)
        result = await store.request_promotion("promo-1")
        assert result["eligible"] is True
        assert result["procedure_id"] == "promo-1"

    @pytest.mark.asyncio
    async def test_ineligible_low_compilation_level(self, store):
        """Level 3 < required 4 -> rejected."""
        await _save_with_metrics(store, compilation_level=3, total_completions=15, total_selections=20)
        result = await store.request_promotion("promo-1")
        assert result["eligible"] is False
        assert "Compilation level" in result["reason"]

    @pytest.mark.asyncio
    async def test_ineligible_low_completions(self, store):
        """5 completions < required 10 -> rejected."""
        await _save_with_metrics(store, total_completions=5, total_selections=20)
        result = await store.request_promotion("promo-1")
        assert result["eligible"] is False
        assert "completions" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_ineligible_low_effective_rate(self, store):
        """Effective rate 0.5 < required 0.7 -> rejected."""
        await _save_with_metrics(store, total_completions=10, total_selections=20)
        result = await store.request_promotion("promo-1")
        assert result["eligible"] is False
        assert "Effective rate" in result["reason"]

    @pytest.mark.asyncio
    async def test_already_pending(self, store):
        """Promotion already pending -> rejected."""
        await _save_with_metrics(store, promotion_status="pending",
                                 total_completions=15, total_selections=20)
        result = await store.request_promotion("promo-1")
        assert result["eligible"] is False
        assert "pending" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_already_approved(self, store):
        """Procedure already promoted -> rejected."""
        await _save_with_metrics(store, promotion_status="approved",
                                 total_completions=15, total_selections=20)
        result = await store.request_promotion("promo-1")
        assert result["eligible"] is False
        assert "promoted" in result["reason"].lower() or "approved" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_within_rejection_cooldown(self, store):
        """Rejected 10h ago, cooldown is 72h -> rejected."""
        recent = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        await _save_with_metrics(
            store, promotion_status="rejected",
            decided_at=recent, rejection_reason="not ready",
            total_completions=15, total_selections=20,
        )
        result = await store.request_promotion("promo-1")
        assert result["eligible"] is False
        assert "cooldown" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_past_rejection_cooldown(self, store):
        """Rejected 80h ago, cooldown is 72h -> eligible (cooldown expired)."""
        old = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
        await _save_with_metrics(
            store, promotion_status="rejected",
            decided_at=old, rejection_reason="stale rejection",
            total_completions=15, total_selections=20,
        )
        result = await store.request_promotion("promo-1")
        assert result["eligible"] is True

    @pytest.mark.asyncio
    async def test_procedure_not_found(self, store):
        """Non-existent procedure -> rejected."""
        result = await store.request_promotion("nonexistent-proc")
        assert result["eligible"] is False
        assert "not found" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_private_status_with_good_metrics(self, store):
        """Private (default) status with good metrics -> can request promotion."""
        await _save_with_metrics(
            store, promotion_status="private",
            total_completions=20, total_selections=25,
        )
        result = await store.request_promotion("promo-1")
        assert result["eligible"] is True
