"""AD-538: Tests for last_used_at tracking."""

from __future__ import annotations

import asyncio
import time

import pytest

from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure, ProcedureStep


@pytest.fixture
def store(tmp_path):
    s = ProcedureStore(data_dir=tmp_path)
    asyncio.get_event_loop().run_until_complete(s.start())
    yield s
    asyncio.get_event_loop().run_until_complete(s.stop())


def _make_procedure(proc_id: str = "lu1", extraction_date: float = 0.0) -> Procedure:
    if not extraction_date:
        extraction_date = time.time()
    return Procedure(
        id=proc_id,
        name="Last Used Test",
        compilation_level=3,
        steps=[ProcedureStep(step_number=1, action="test")],
        extraction_date=extraction_date,
    )


@pytest.mark.asyncio
async def test_last_used_at_on_save(store):
    """Newly saved procedure has last_used_at set (from extraction_date)."""
    ext_date = time.time() - 100
    proc = _make_procedure("lu1", extraction_date=ext_date)
    await store.save(proc)

    cursor = await store._db.execute(
        "SELECT last_used_at FROM procedure_records WHERE id = ?", ("lu1",)
    )
    row = await cursor.fetchone()
    # last_used_at should be set to extraction_date (or close to it)
    assert row[0] > 0


@pytest.mark.asyncio
async def test_last_used_at_updated_on_selection(store):
    """record_selection() updates last_used_at."""
    proc = _make_procedure("lu2")
    await store.save(proc)

    before = time.time()
    await store.record_selection("lu2")

    cursor = await store._db.execute(
        "SELECT last_used_at FROM procedure_records WHERE id = ?", ("lu2",)
    )
    row = await cursor.fetchone()
    assert row[0] >= before


@pytest.mark.asyncio
async def test_last_used_at_persists(store):
    """save + get preserves last_used_at."""
    proc = _make_procedure("lu3")
    proc.last_used_at = 12345.0
    await store.save(proc)

    reloaded = await store.get("lu3")
    assert reloaded is not None
    assert reloaded.last_used_at == 12345.0


@pytest.mark.asyncio
async def test_last_used_at_migration(store):
    """Migration adds last_used_at column with default 0.0."""
    cursor = await store._db.execute("PRAGMA table_info(procedure_records)")
    columns = {row[1] for row in await cursor.fetchall()}
    assert "last_used_at" in columns
    assert "is_archived" in columns


@pytest.mark.asyncio
async def test_to_dict_includes_last_used_at():
    """Serialization includes new fields."""
    proc = _make_procedure("lu5")
    proc.last_used_at = 99999.0
    proc.is_archived = True
    d = proc.to_dict()
    assert d["last_used_at"] == 99999.0
    assert d["is_archived"] is True
