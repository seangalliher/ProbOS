"""AD-536: Tests for ProcedureStore promotion CRUD methods."""

from __future__ import annotations

import json

import pytest

from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure, ProcedureStep


@pytest.fixture
async def store(tmp_path):
    s = ProcedureStore(data_dir=tmp_path)
    await s.start()
    yield s
    await s.stop()


def _make_procedure(proc_id: str = "test1", name: str = "Test Proc",
                    compilation_level: int = 4, total_completions: int = 20) -> Procedure:
    """Create a minimal Procedure suitable for promotion tests."""
    return Procedure(
        id=proc_id,
        name=name,
        compilation_level=compilation_level,
        steps=[ProcedureStep(step_number=1, action="test action")],
        success_count=total_completions,
    )


@pytest.mark.asyncio
async def test_schema_migration_adds_promotion_columns(store: ProcedureStore) -> None:
    """_ensure_promotion_columns() should add all six promotion columns."""
    cursor = await store._db.execute("PRAGMA table_info(procedure_records)")
    columns = {row[1] for row in await cursor.fetchall()}
    expected_cols = {
        "promotion_status",
        "promotion_requested_at",
        "promotion_decided_at",
        "promotion_decided_by",
        "promotion_rejection_reason",
        "promotion_directive_id",
    }
    assert expected_cols.issubset(columns), f"Missing columns: {expected_cols - columns}"


@pytest.mark.asyncio
async def test_request_promotion_sets_status_and_timestamp(store: ProcedureStore) -> None:
    """request_promotion() should set promotion_status='pending' and promotion_requested_at."""
    proc = _make_procedure("promo1", compilation_level=4, total_completions=20)
    await store.save(proc)
    # Ensure the procedure has enough completions in the DB
    await store._db.execute(
        "UPDATE procedure_records SET total_completions = 20, total_selections = 25 WHERE id = ?",
        ("promo1",),
    )
    await store._db.commit()

    result = await store.request_promotion("promo1")
    assert result.get("eligible") is True or result.get("status") == "pending"

    status = await store.get_promotion_status("promo1")
    assert status == "pending"


@pytest.mark.asyncio
async def test_approve_promotion_sets_decided_by_and_directive(store: ProcedureStore) -> None:
    """approve_promotion() should record decided_by and directive_id."""
    proc = _make_procedure("approve1")
    await store.save(proc)
    # Set to pending first
    await store._db.execute(
        "UPDATE procedure_records SET promotion_status = 'pending' WHERE id = ?",
        ("approve1",),
    )
    await store._db.commit()

    await store.approve_promotion("approve1", decided_by="captain", directive_id="dir-001")

    status = await store.get_promotion_status("approve1")
    assert status == "approved"

    cursor = await store._db.execute(
        "SELECT promotion_decided_by, promotion_directive_id FROM procedure_records WHERE id = ?",
        ("approve1",),
    )
    row = await cursor.fetchone()
    assert row[0] == "captain"
    assert row[1] == "dir-001"


@pytest.mark.asyncio
async def test_reject_promotion_sets_reason(store: ProcedureStore) -> None:
    """reject_promotion() should record decided_by and rejection reason."""
    proc = _make_procedure("reject1")
    await store.save(proc)
    await store._db.execute(
        "UPDATE procedure_records SET promotion_status = 'pending' WHERE id = ?",
        ("reject1",),
    )
    await store._db.commit()

    await store.reject_promotion("reject1", decided_by="worf", reason="Insufficient testing")

    status = await store.get_promotion_status("reject1")
    assert status == "rejected"

    cursor = await store._db.execute(
        "SELECT promotion_decided_by, promotion_rejection_reason FROM procedure_records WHERE id = ?",
        ("reject1",),
    )
    row = await cursor.fetchone()
    assert row[0] == "worf"
    assert row[1] == "Insufficient testing"


@pytest.mark.asyncio
async def test_get_pending_promotions_returns_only_pending(store: ProcedureStore) -> None:
    """get_pending_promotions() should return only procedures with status 'pending'."""
    for pid in ("pend1", "pend2", "not_pend"):
        proc = _make_procedure(pid, name=f"Proc {pid}")
        await store.save(proc)

    await store._db.execute(
        "UPDATE procedure_records SET promotion_status = 'pending' WHERE id IN ('pend1', 'pend2')",
    )
    await store._db.execute(
        "UPDATE procedure_records SET promotion_status = 'private' WHERE id = 'not_pend'",
    )
    await store._db.commit()

    pending = await store.get_pending_promotions()
    pending_ids = {p["procedure_id"] for p in pending}
    assert "pend1" in pending_ids
    assert "pend2" in pending_ids
    assert "not_pend" not in pending_ids


@pytest.mark.asyncio
async def test_get_pending_excludes_approved_and_rejected(store: ProcedureStore) -> None:
    """get_pending_promotions() must not include approved or rejected procedures."""
    for pid, status in [("app1", "approved"), ("rej1", "rejected"), ("pen1", "pending")]:
        proc = _make_procedure(pid, name=f"Proc {pid}")
        await store.save(proc)
        await store._db.execute(
            "UPDATE procedure_records SET promotion_status = ? WHERE id = ?",
            (status, pid),
        )
    await store._db.commit()

    pending = await store.get_pending_promotions()
    pending_ids = {p["procedure_id"] for p in pending}
    assert pending_ids == {"pen1"}


@pytest.mark.asyncio
async def test_get_promotion_status_returns_correct_status(store: ProcedureStore) -> None:
    """get_promotion_status() should return the current status string."""
    proc = _make_procedure("status1")
    await store.save(proc)

    # Default should be 'private'
    assert await store.get_promotion_status("status1") == "private"

    # After update
    await store._db.execute(
        "UPDATE procedure_records SET promotion_status = 'pending' WHERE id = ?",
        ("status1",),
    )
    await store._db.commit()
    assert await store.get_promotion_status("status1") == "pending"

    # Non-existent procedure
    assert await store.get_promotion_status("nonexistent") == "private"


@pytest.mark.asyncio
async def test_get_promoted_procedures_returns_approved_with_directive(store: ProcedureStore) -> None:
    """get_promoted_procedures() should return approved procedures with directive info."""
    proc = _make_procedure("promoted1", name="Promoted Proc")
    await store.save(proc)
    await store.approve_promotion("promoted1", decided_by="captain", directive_id="dir-999")

    promoted = await store.get_promoted_procedures()
    assert len(promoted) >= 1

    entry = next(p for p in promoted if p["procedure_id"] == "promoted1")
    assert entry["name"] == "Promoted Proc"
    assert entry["decided_by"] == "captain"
    assert entry["directive_id"] == "dir-999"
