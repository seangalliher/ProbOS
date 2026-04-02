"""AD-538: Tests for procedure decay lifecycle."""

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


def _make_procedure(
    proc_id: str = "decay1",
    name: str = "Decay Proc",
    compilation_level: int = 4,
    last_used_at: float = 0.0,
    is_negative: bool = False,
    is_archived: bool = False,
) -> Procedure:
    return Procedure(
        id=proc_id,
        name=name,
        compilation_level=compilation_level,
        steps=[ProcedureStep(step_number=1, action="test")],
        extraction_date=time.time() - 86400 * 60,
        last_used_at=last_used_at,
        is_negative=is_negative,
        is_archived=is_archived,
    )


async def _save_with_metrics(store, proc, selections=5, completions=5, last_used=0.0):
    """Save procedure and set DB metrics for decay testing."""
    await store.save(proc)
    await store._db.execute(
        "UPDATE procedure_records SET total_selections = ?, total_completions = ?, "
        "last_used_at = ? WHERE id = ?",
        (selections, completions, last_used, proc.id),
    )
    await store._db.commit()


@pytest.mark.asyncio
async def test_decay_reduces_compilation_level(store):
    """Level 4 unused for 30+ days → Level 3."""
    now = time.time()
    proc = _make_procedure("d1", compilation_level=4, last_used_at=now - 86400 * 40)
    await _save_with_metrics(store, proc, selections=5, last_used=now - 86400 * 40)

    results = await store.decay_stale_procedures(now=now)
    assert len(results) == 1
    assert results[0]["old_level"] == 4
    assert results[0]["new_level"] == 3


@pytest.mark.asyncio
async def test_decay_never_below_level_1(store):
    """Level 1 procedures should not be decayed."""
    now = time.time()
    proc = _make_procedure("d2", compilation_level=1, last_used_at=now - 86400 * 40)
    await _save_with_metrics(store, proc, selections=5, last_used=now - 86400 * 40)

    results = await store.decay_stale_procedures(now=now)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_decay_resets_consecutive_successes(store):
    """Consecutive successes should be zeroed on decay."""
    now = time.time()
    proc = _make_procedure("d3", compilation_level=3, last_used_at=now - 86400 * 40)
    await _save_with_metrics(store, proc, selections=5, last_used=now - 86400 * 40)

    # Set some consecutive successes
    await store._db.execute(
        "UPDATE procedure_records SET consecutive_successes = 5 WHERE id = ?",
        ("d3",),
    )
    await store._db.commit()

    await store.decay_stale_procedures(now=now)

    cursor = await store._db.execute(
        "SELECT consecutive_successes FROM procedure_records WHERE id = ?", ("d3",)
    )
    row = await cursor.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_decay_respects_min_selections(store):
    """Procedures with < LIFECYCLE_MIN_SELECTIONS_FOR_DECAY selections not decayed."""
    now = time.time()
    proc = _make_procedure("d4", compilation_level=3, last_used_at=now - 86400 * 40)
    await _save_with_metrics(store, proc, selections=2, last_used=now - 86400 * 40)

    results = await store.decay_stale_procedures(now=now)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_decay_skips_recently_used(store):
    """Procedure used 10 days ago should not be decayed."""
    now = time.time()
    proc = _make_procedure("d5", compilation_level=4, last_used_at=now - 86400 * 10)
    await _save_with_metrics(store, proc, selections=5, last_used=now - 86400 * 10)

    results = await store.decay_stale_procedures(now=now)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_decay_skips_negative(store):
    """Negative (anti-pattern) procedures not decayed."""
    now = time.time()
    proc = _make_procedure("d6", compilation_level=3, last_used_at=now - 86400 * 40, is_negative=True)
    await _save_with_metrics(store, proc, selections=5, last_used=now - 86400 * 40)

    results = await store.decay_stale_procedures(now=now)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_decay_skips_archived(store):
    """Already archived procedures not decayed."""
    now = time.time()
    proc = _make_procedure("d7", compilation_level=3, last_used_at=now - 86400 * 40, is_archived=True)
    await store.save(proc)
    await store._db.execute(
        "UPDATE procedure_records SET total_selections = 5, last_used_at = ?, is_archived = 1 WHERE id = ?",
        (now - 86400 * 40, "d7"),
    )
    await store._db.commit()

    results = await store.decay_stale_procedures(now=now)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_decay_one_level_per_cycle(store):
    """Level 4 unused 60 days decays by ONE level per cycle, not two."""
    now = time.time()
    proc = _make_procedure("d8", compilation_level=4, last_used_at=now - 86400 * 60)
    await _save_with_metrics(store, proc, selections=5, last_used=now - 86400 * 60)

    results = await store.decay_stale_procedures(now=now)
    assert len(results) == 1
    assert results[0]["new_level"] == 3  # One level, not two


@pytest.mark.asyncio
async def test_decay_returns_report(store):
    """Return value includes id, name, old_level, new_level."""
    now = time.time()
    proc = _make_procedure("d9", name="Report Test", compilation_level=4, last_used_at=now - 86400 * 40)
    await _save_with_metrics(store, proc, selections=5, last_used=now - 86400 * 40)

    results = await store.decay_stale_procedures(now=now)
    assert len(results) == 1
    r = results[0]
    assert r["id"] == "d9"
    assert r["name"] == "Report Test"
    assert r["old_level"] == 4
    assert r["new_level"] == 3


@pytest.mark.asyncio
async def test_decay_updates_content_snapshot(store):
    """JSON blob (content_snapshot) reflects new level after decay."""
    now = time.time()
    proc = _make_procedure("d10", compilation_level=4, last_used_at=now - 86400 * 40)
    await _save_with_metrics(store, proc, selections=5, last_used=now - 86400 * 40)

    await store.decay_stale_procedures(now=now)

    reloaded = await store.get("d10")
    assert reloaded is not None
    assert reloaded.compilation_level == 3
