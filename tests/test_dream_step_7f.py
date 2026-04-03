"""AD-538: Tests for Dream Step 7f — lifecycle maintenance."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import DreamingConfig
from probos.types import DreamReport


@pytest.fixture
def mock_store():
    """Create a mock ProcedureStore with lifecycle methods."""
    store = AsyncMock()
    store.decay_stale_procedures = AsyncMock(return_value=[])
    store.archive_stale_procedures = AsyncMock(return_value=[])
    store.find_duplicate_candidates = AsyncMock(return_value=[])
    store.list_active = AsyncMock(return_value=[])
    store.get = AsyncMock(return_value=None)
    store.has_cluster = AsyncMock(return_value=False)
    return store


def _build_engine(mock_store, **overrides):
    """Build a minimal DreamingEngine using object.__new__ to bypass __init__."""
    from probos.cognitive.dreaming import DreamingEngine

    engine = object.__new__(DreamingEngine)
    engine.router = MagicMock()
    engine.router.get_recent_pairs = MagicMock(return_value=[])
    engine.router.prune = MagicMock(return_value=0)
    engine.trust_network = MagicMock()
    engine.trust_network.get_trust = MagicMock(return_value=0.5)
    engine.episodic_memory = AsyncMock()
    engine.episodic_memory.get_stats = AsyncMock(return_value={"total": 0})
    engine.episodic_memory.get_recent = AsyncMock(return_value=[])
    engine.episodic_memory.flush_to_long_term = AsyncMock(
        return_value={"episodes_replayed": 0, "weights_strengthened": 0}
    )
    engine.config = DreamingConfig()
    engine.pre_warm_intents = []
    engine._idle_scale_down_fn = None
    engine._gap_prediction_fn = None
    engine._last_clusters = []
    engine._contradiction_resolve_fn = None
    engine._last_consolidated_count = 0
    engine._llm_client = overrides.get("llm_client", AsyncMock())
    engine._procedure_store = mock_store
    engine._last_procedures = []
    engine._extracted_cluster_ids = set()
    engine._addressed_degradations = {}
    engine._extraction_candidates = {}
    engine._reactive_cooldowns = {}
    engine._fallback_learning_queue = []
    # AD-537 fields
    engine._ward_room = None
    engine._agent_id = ""
    engine._trust_network_lookup = None
    engine._observed_threads = set()
    # AD-557 fields
    engine._emergence_metrics_engine = None
    engine._get_department = None
    # AD-551 fields
    engine._records_store = None
    return engine


@pytest.fixture
def make_engine(mock_store):
    """Build a minimal DreamingEngine with mocked dependencies."""
    return _build_engine(mock_store)


@pytest.mark.asyncio
async def test_step_7f_runs_decay(make_engine, mock_store):
    """Dream cycle should call decay_stale_procedures."""
    mock_store.decay_stale_procedures.return_value = [
        {"id": "p1", "name": "Test", "old_level": 3, "new_level": 2},
    ]
    report = await make_engine.dream_cycle()
    mock_store.decay_stale_procedures.assert_called_once()
    assert report.procedures_decayed == 1


@pytest.mark.asyncio
async def test_step_7f_runs_archival(make_engine, mock_store):
    """Dream cycle should call archive_stale_procedures."""
    mock_store.archive_stale_procedures.return_value = [
        {"id": "p2", "name": "Old", "days_unused": 95},
    ]
    report = await make_engine.dream_cycle()
    mock_store.archive_stale_procedures.assert_called_once()
    assert report.procedures_archived == 1


@pytest.mark.asyncio
async def test_step_7f_runs_dedup(make_engine, mock_store):
    """Dream cycle should call find_duplicate_candidates."""
    mock_store.find_duplicate_candidates.return_value = [
        {"primary_id": "p1", "primary_name": "A", "duplicate_id": "p2",
         "duplicate_name": "B", "similarity": 0.92},
    ]
    report = await make_engine.dream_cycle()
    mock_store.find_duplicate_candidates.assert_called_once()
    assert report.dedup_candidates_found == 1


@pytest.mark.asyncio
async def test_step_7f_updates_dream_report(make_engine, mock_store):
    """DreamReport fields should reflect lifecycle step results."""
    mock_store.decay_stale_procedures.return_value = [
        {"id": "p1", "name": "A", "old_level": 4, "new_level": 3},
        {"id": "p2", "name": "B", "old_level": 3, "new_level": 2},
    ]
    mock_store.archive_stale_procedures.return_value = [
        {"id": "p3", "name": "C", "days_unused": 100},
    ]
    mock_store.find_duplicate_candidates.return_value = []

    report = await make_engine.dream_cycle()
    assert report.procedures_decayed == 2
    assert report.procedures_archived == 1
    assert report.dedup_candidates_found == 0


@pytest.mark.asyncio
async def test_step_7f_no_store_graceful():
    """No ProcedureStore -> step completes silently."""
    engine = _build_engine(None)
    engine._procedure_store = None
    report = await engine.dream_cycle()
    assert report.procedures_decayed == 0
    assert report.procedures_archived == 0
    assert report.dedup_candidates_found == 0


@pytest.mark.asyncio
async def test_step_7f_decay_before_archive(make_engine, mock_store):
    """Within step 7f: decay runs first, then archive."""
    call_order = []
    mock_store.decay_stale_procedures = AsyncMock(
        side_effect=lambda: call_order.append("decay") or []
    )
    mock_store.archive_stale_procedures = AsyncMock(
        side_effect=lambda: call_order.append("archive") or []
    )
    mock_store.find_duplicate_candidates = AsyncMock(
        side_effect=lambda: call_order.append("dedup") or []
    )
    await make_engine.dream_cycle()
    assert call_order.index("decay") < call_order.index("archive")


@pytest.mark.asyncio
async def test_step_7f_dedup_does_not_auto_merge(make_engine, mock_store):
    """Dedup detection should NOT call merge_procedures."""
    mock_store.find_duplicate_candidates.return_value = [
        {"primary_id": "p1", "primary_name": "A", "duplicate_id": "p2",
         "duplicate_name": "B", "similarity": 0.95},
    ]
    mock_store.merge_procedures = AsyncMock()

    await make_engine.dream_cycle()

    mock_store.merge_procedures.assert_not_called()


def test_dream_report_has_lifecycle_fields():
    """DreamReport should have lifecycle fields with default 0."""
    report = DreamReport()
    assert report.procedures_decayed == 0
    assert report.procedures_archived == 0
    assert report.dedup_candidates_found == 0
