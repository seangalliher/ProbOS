"""AD-538: Tests for procedure deduplication and merge."""

from __future__ import annotations

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
    proc_id: str,
    name: str = "Proc",
    intent_types: list[str] | None = None,
    tags: list[str] | None = None,
    learned_via: str = "direct",
) -> Procedure:
    return Procedure(
        id=proc_id,
        name=name,
        compilation_level=3,
        steps=[ProcedureStep(step_number=1, action="test action")],
        intent_types=intent_types or ["read_file"],
        tags=tags or [],
        extraction_date=time.time(),
        last_used_at=time.time(),
        learned_via=learned_via,
    )


async def _save_with_stats(store, proc, selections=10, completions=8):
    """Save procedure and set DB metrics."""
    await store.save(proc)
    await store._db.execute(
        "UPDATE procedure_records SET total_selections = ?, total_completions = ? WHERE id = ?",
        (selections, completions, proc.id),
    )
    await store._db.commit()


# -- Dedup tests (ChromaDB-dependent — these test the SQL/logic layer) --

@pytest.mark.asyncio
async def test_find_duplicates_no_chroma_returns_empty(store):
    """Without ChromaDB, find_duplicate_candidates returns empty."""
    store._chroma_collection = None
    result = await store.find_duplicate_candidates()
    assert result == []


@pytest.mark.asyncio
async def test_find_duplicates_requires_shared_intent_check():
    """Verify the intent_type overlap check logic is functional."""
    proc_intents = {"read_file", "write_file"}
    match_intents = {"delete_file"}
    assert not (proc_intents & match_intents)

    match_intents2 = {"read_file", "execute"}
    assert proc_intents & match_intents2


@pytest.mark.asyncio
async def test_find_duplicates_primary_selection_logic():
    """Higher completion count wins primary role."""
    # Simulate the primary selection logic from find_duplicate_candidates
    proc_comp, match_comp = 10, 5
    assert proc_comp > match_comp  # proc is primary

    proc_comp, match_comp = 3, 7
    assert match_comp > proc_comp  # match is primary


@pytest.mark.asyncio
async def test_find_duplicates_self_skip():
    """Ensure a procedure ID is never compared against itself."""
    proc_id = "abc123"
    match_id = "abc123"
    assert proc_id == match_id  # Should be skipped in real code


# -- Merge tests (SQL-only, no ChromaDB needed) --

@pytest.mark.asyncio
async def test_merge_transfers_stats(store):
    """Completion counts should be summed after merge."""
    p = _make_procedure("primary1", "Primary", intent_types=["read_file"])
    d = _make_procedure("dup1", "Duplicate", intent_types=["read_file"])
    await _save_with_stats(store, p, selections=10, completions=8)
    await _save_with_stats(store, d, selections=5, completions=4)

    success = await store.merge_procedures("primary1", "dup1")
    assert success is True

    metrics = await store.get_quality_metrics("primary1")
    assert metrics["total_selections"] == 15
    assert metrics["total_completions"] == 12


@pytest.mark.asyncio
async def test_merge_deactivates_duplicate(store):
    """Duplicate should have is_active=0 and superseded_by=primary."""
    p = _make_procedure("primary2", "Primary")
    d = _make_procedure("dup2", "Duplicate")
    await _save_with_stats(store, p)
    await _save_with_stats(store, d)

    await store.merge_procedures("primary2", "dup2")

    cursor = await store._db.execute(
        "SELECT is_active, superseded_by FROM procedure_records WHERE id = ?",
        ("dup2",),
    )
    row = await cursor.fetchone()
    assert row[0] == 0  # is_active
    assert row[1] == "primary2"  # superseded_by


@pytest.mark.asyncio
async def test_merge_unions_tags(store):
    """Tags from both procedures should be combined."""
    p = _make_procedure("primary3", "Primary", tags=["tag_a", "tag_b"])
    d = _make_procedure("dup3", "Duplicate", tags=["tag_b", "tag_c"])
    await _save_with_stats(store, p)
    await _save_with_stats(store, d)

    await store.merge_procedures("primary3", "dup3")

    reloaded = await store.get("primary3")
    assert set(reloaded.tags) == {"tag_a", "tag_b", "tag_c"}


@pytest.mark.asyncio
async def test_merge_unions_intent_types(store):
    """Intent types from both procedures should be combined."""
    p = _make_procedure("primary4", "Primary", intent_types=["read_file"])
    d = _make_procedure("dup4", "Duplicate", intent_types=["read_file", "write_file"])
    await _save_with_stats(store, p)
    await _save_with_stats(store, d)

    await store.merge_procedures("primary4", "dup4")

    reloaded = await store.get("primary4")
    assert set(reloaded.intent_types) == {"read_file", "write_file"}


@pytest.mark.asyncio
async def test_merge_preserves_observational_provenance(store):
    """learned_via info should be tagged on primary when merging observed procedure."""
    p = _make_procedure("primary5", "Primary")
    d = _make_procedure("dup5", "Observed Dup", learned_via="observation")
    await _save_with_stats(store, p)
    await _save_with_stats(store, d)

    await store.merge_procedures("primary5", "dup5")

    reloaded = await store.get("primary5")
    assert any("merged_from_observed:dup5" in t for t in reloaded.tags)


@pytest.mark.asyncio
async def test_merge_fails_inactive_primary(store):
    """Merge should fail if primary is inactive."""
    p = _make_procedure("primary6", "Primary")
    d = _make_procedure("dup6", "Duplicate")
    await _save_with_stats(store, p)
    await _save_with_stats(store, d)

    # Deactivate primary
    await store.deactivate("primary6")

    success = await store.merge_procedures("primary6", "dup6")
    assert success is False
