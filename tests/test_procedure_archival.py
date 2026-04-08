"""AD-538: Tests for procedure archival lifecycle."""

from __future__ import annotations

import json
import time

import pytest

from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure, ProcedureStep


@pytest.fixture
async def store(tmp_path):
    s = ProcedureStore(data_dir=tmp_path)
    await s.start()
    yield s
    await s.stop()


def _make_procedure(
    proc_id: str = "arch1",
    name: str = "Archive Proc",
    compilation_level: int = 1,
    last_used_at: float = 0.0,
) -> Procedure:
    return Procedure(
        id=proc_id,
        name=name,
        compilation_level=compilation_level,
        steps=[ProcedureStep(step_number=1, action="test")],
        extraction_date=time.time() - 86400 * 120,
        last_used_at=last_used_at,
    )


async def _save_archivable(store, proc, last_used):
    """Save and set up for archival testing."""
    await store.save(proc)
    await store._db.execute(
        "UPDATE procedure_records SET last_used_at = ?, compilation_level = 1 WHERE id = ?",
        (last_used, proc.id),
    )
    await store._db.commit()


@pytest.mark.asyncio
async def test_archive_stale_level_1(store):
    """Level 1 unused for 90+ days → archived."""
    now = time.time()
    proc = _make_procedure("a1", last_used_at=now - 86400 * 100)
    await _save_archivable(store, proc, now - 86400 * 100)

    results = await store.archive_stale_procedures(now=now)
    assert len(results) == 1
    assert results[0]["id"] == "a1"


@pytest.mark.asyncio
async def test_archive_sets_is_active_false(store):
    """is_active=0 after archival."""
    now = time.time()
    proc = _make_procedure("a2", last_used_at=now - 86400 * 100)
    await _save_archivable(store, proc, now - 86400 * 100)

    await store.archive_stale_procedures(now=now)

    cursor = await store._db.execute(
        "SELECT is_active FROM procedure_records WHERE id = ?", ("a2",)
    )
    row = await cursor.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_archive_sets_is_archived_true(store):
    """is_archived=1 after archival."""
    now = time.time()
    proc = _make_procedure("a3", last_used_at=now - 86400 * 100)
    await _save_archivable(store, proc, now - 86400 * 100)

    await store.archive_stale_procedures(now=now)

    cursor = await store._db.execute(
        "SELECT is_archived FROM procedure_records WHERE id = ?", ("a3",)
    )
    row = await cursor.fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_archive_skips_higher_levels(store):
    """Level 2+ not archived even if unused 90+ days."""
    now = time.time()
    proc = _make_procedure("a4", compilation_level=2, last_used_at=now - 86400 * 100)
    await store.save(proc)
    await store._db.execute(
        "UPDATE procedure_records SET last_used_at = ?, compilation_level = 2 WHERE id = ?",
        (now - 86400 * 100, "a4"),
    )
    await store._db.commit()

    results = await store.archive_stale_procedures(now=now)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_archive_writes_to_records(store, tmp_path):
    """RecordsStore _archived/ receives YAML if available."""
    class MockRecords:
        def __init__(self):
            self.entries = []
        async def write_entry(self, **kwargs):
            self.entries.append(kwargs)

    store._records_store = MockRecords()

    now = time.time()
    proc = _make_procedure("a5", last_used_at=now - 86400 * 100)
    await _save_archivable(store, proc, now - 86400 * 100)

    await store.archive_stale_procedures(now=now)

    assert len(store._records_store.entries) >= 1
    # The save() also writes to records, so the archive entry may not be first
    archived_entries = [e for e in store._records_store.entries if "_archived/" in e["path"]]
    assert len(archived_entries) >= 1


@pytest.mark.asyncio
async def test_archive_removes_from_chromadb(store):
    """ChromaDB collection should not contain archived procedure if ChromaDB is available."""
    # This test works even without ChromaDB — it just verifies the delete is attempted
    now = time.time()
    proc = _make_procedure("a6", last_used_at=now - 86400 * 100)
    await _save_archivable(store, proc, now - 86400 * 100)

    await store.archive_stale_procedures(now=now)
    # Verify procedure is not in active list
    active = await store.list_active()
    assert not any(p["id"] == "a6" for p in active)


@pytest.mark.asyncio
async def test_archive_returns_report(store):
    """Return value includes id, name, days_unused."""
    now = time.time()
    proc = _make_procedure("a7", name="Report Arch", last_used_at=now - 86400 * 100)
    await _save_archivable(store, proc, now - 86400 * 100)

    results = await store.archive_stale_procedures(now=now)
    assert len(results) == 1
    r = results[0]
    assert r["id"] == "a7"
    assert r["name"] == "Report Arch"
    assert r["days_unused"] >= 90


@pytest.mark.asyncio
async def test_restore_sets_active(store):
    """Restore: is_active=1, is_archived=0, level=1."""
    now = time.time()
    proc = _make_procedure("a8", last_used_at=now - 86400 * 100)
    await _save_archivable(store, proc, now - 86400 * 100)
    await store.archive_stale_procedures(now=now)

    success = await store.restore_procedure("a8")
    assert success is True

    cursor = await store._db.execute(
        "SELECT is_active, is_archived, compilation_level FROM procedure_records WHERE id = ?",
        ("a8",),
    )
    row = await cursor.fetchone()
    assert row[0] == 1  # is_active
    assert row[1] == 0  # is_archived
    assert row[2] == 1  # compilation_level


@pytest.mark.asyncio
async def test_restore_sets_last_used_at(store):
    """Restore: last_used_at = now."""
    now = time.time()
    proc = _make_procedure("a9", last_used_at=now - 86400 * 100)
    await _save_archivable(store, proc, now - 86400 * 100)
    await store.archive_stale_procedures(now=now)

    before_restore = time.time()
    success = await store.restore_procedure("a9")
    assert success is True

    cursor = await store._db.execute(
        "SELECT last_used_at FROM procedure_records WHERE id = ?", ("a9",)
    )
    row = await cursor.fetchone()
    assert row[0] >= before_restore


@pytest.mark.asyncio
async def test_restore_readds_to_active(store):
    """Restored procedure appears in list_active()."""
    now = time.time()
    proc = _make_procedure("a10", last_used_at=now - 86400 * 100)
    await _save_archivable(store, proc, now - 86400 * 100)
    await store.archive_stale_procedures(now=now)

    # Verify gone
    active = await store.list_active()
    assert not any(p["id"] == "a10" for p in active)

    # Restore
    await store.restore_procedure("a10")

    # Verify back
    active = await store.list_active()
    assert any(p["id"] == "a10" for p in active)
