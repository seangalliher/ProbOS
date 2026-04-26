"""BF-207: Shutdown race condition causes episodic memory hash mismatch.

Tests cover:
- Auto-heal current-version hash mismatches (Part 3)
- Auto-heal old-version mismatches still works
- Auto-heal graceful degradation (no collection, update failure)
- Shutdown ordering (episodic stop before knowledge store)
- Dream cycle timeout reduced to 2s
- Eviction audit stops with episodic memory
"""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from probos.cognitive.episodic import (
    _HASH_VERSION,
    _verify_episode_hash,
    compute_episode_hash,
)
from probos.types import Episode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def episode():
    """A minimal episode for hash testing."""
    return Episode(
        id="251209b5abcd1234",
        timestamp=1000.0,
        user_input="Test input",
        dag_summary={"key": "value"},
        outcomes=[{"result": "ok"}],
        reflection="Test reflection",
        agent_ids=["agent-1"],
        duration_ms=100.0,
    )


@pytest.fixture
def mock_collection():
    """Mock ChromaDB collection with update()."""
    col = MagicMock()
    col.update = MagicMock()
    return col


# ===========================================================================
# Part 3: Auto-Heal Hash Mismatches
# ===========================================================================

class TestAutoHealCurrentVersion:
    """Auto-heal now repairs current-version hash mismatches."""

    def test_auto_heal_current_version_mismatch(self, episode, mock_collection):
        """Episode with _hash_v=current but wrong content_hash is auto-healed."""
        correct_hash = compute_episode_hash(episode)
        wrong_hash = "d26c3f50e3a4aabbccdd"  # Stale hash from shutdown race

        metadata = {
            "content_hash": wrong_hash,
            "_hash_v": _HASH_VERSION,
        }

        result = _verify_episode_hash(
            episode, wrong_hash, metadata=metadata, collection=mock_collection,
        )

        assert result is True
        mock_collection.update.assert_called_once()
        call_kwargs = mock_collection.update.call_args
        updated_meta = call_kwargs[1]["metadatas"][0] if "metadatas" in call_kwargs[1] else call_kwargs[0][0]
        # Verify the hash was updated to the correct recomputed value
        if isinstance(updated_meta, dict):
            assert updated_meta["content_hash"] == correct_hash
            assert updated_meta["_hash_v"] == _HASH_VERSION

    def test_auto_heal_old_version_still_works(self, episode, mock_collection):
        """Episode with _hash_v < current is still auto-healed (existing path)."""
        correct_hash = compute_episode_hash(episode)
        old_hash = "oldoldhash123"

        metadata = {
            "content_hash": old_hash,
            "_hash_v": 1,  # Old version
        }

        result = _verify_episode_hash(
            episode, old_hash, metadata=metadata, collection=mock_collection,
        )

        assert result is True
        mock_collection.update.assert_called_once()

    def test_auto_heal_no_collection(self, episode):
        """Mismatch with collection=None returns False, no crash."""
        wrong_hash = "aabbccdd11223344"
        metadata = {
            "content_hash": wrong_hash,
            "_hash_v": _HASH_VERSION,
        }

        result = _verify_episode_hash(
            episode, wrong_hash, metadata=metadata, collection=None,
        )

        assert result is False

    def test_auto_heal_update_failure(self, episode, mock_collection):
        """collection.update() raises → graceful degradation (returns False)."""
        wrong_hash = "aabbccdd11223344"
        metadata = {
            "content_hash": wrong_hash,
            "_hash_v": _HASH_VERSION,
        }
        mock_collection.update.side_effect = RuntimeError("ChromaDB error")

        result = _verify_episode_hash(
            episode, wrong_hash, metadata=metadata, collection=mock_collection,
        )

        assert result is False

    def test_auto_heal_preserves_episode_data(self, episode, mock_collection):
        """After auto-heal, only content_hash and _hash_v change in metadata."""
        correct_hash = compute_episode_hash(episode)
        wrong_hash = "stale_hash_value"
        metadata = {
            "content_hash": wrong_hash,
            "_hash_v": _HASH_VERSION,
            "agent_id": "agent-1",
            "custom_field": "preserved",
        }

        _verify_episode_hash(
            episode, wrong_hash, metadata=metadata, collection=mock_collection,
        )

        call_kwargs = mock_collection.update.call_args
        updated_meta = call_kwargs[1]["metadatas"][0]
        assert updated_meta["content_hash"] == correct_hash
        assert updated_meta["_hash_v"] == _HASH_VERSION
        assert updated_meta["agent_id"] == "agent-1"
        assert updated_meta["custom_field"] == "preserved"

    def test_matching_hash_returns_true(self, episode):
        """Matching hash returns True without any heal attempt."""
        correct_hash = compute_episode_hash(episode)
        metadata = {
            "content_hash": correct_hash,
            "_hash_v": _HASH_VERSION,
        }

        result = _verify_episode_hash(
            episode, correct_hash, metadata=metadata, collection=None,
        )

        assert result is True

    def test_no_metadata_returns_false(self, episode):
        """Mismatch with metadata=None returns False."""
        result = _verify_episode_hash(
            episode, "wrong_hash", metadata=None, collection=MagicMock(),
        )
        assert result is False


# ===========================================================================
# Shutdown Ordering
# ===========================================================================

class TestShutdownOrdering:
    """Verify episodic memory stops before knowledge store in shutdown sequence."""

    def test_episodic_stop_before_knowledge_store(self):
        """In shutdown.py source, episodic_memory.stop() appears before knowledge store persist."""
        from probos.startup import shutdown as shutdown_mod
        source = inspect.getsource(shutdown_mod.shutdown)

        # Find the BF-207 episodic stop block and the knowledge store persist block
        episodic_stop_pos = source.find("await runtime.episodic_memory.stop()")
        knowledge_persist_pos = source.find("Persist knowledge store artifacts")

        assert episodic_stop_pos != -1, "episodic_memory.stop() must exist in shutdown"
        assert knowledge_persist_pos != -1, "knowledge store persist block must exist"
        assert episodic_stop_pos < knowledge_persist_pos, \
            "episodic_memory.stop() should come before knowledge store persist"

    def test_eviction_audit_stops_with_episodic(self):
        """Eviction audit stop is adjacent to episodic memory stop."""
        from probos.startup import shutdown as shutdown_mod
        source = inspect.getsource(shutdown_mod.shutdown)

        episodic_stop_pos = source.find("await runtime.episodic_memory.stop()")
        eviction_pos = source.find("await _eviction_audit.stop()")
        knowledge_persist_pos = source.find("Persist knowledge store artifacts")

        assert eviction_pos > episodic_stop_pos, \
            "eviction_audit should come after episodic_memory.stop()"
        assert eviction_pos < knowledge_persist_pos, \
            "eviction_audit should come before knowledge store persist"

    def test_dream_cycle_timeout_is_2s(self):
        """Dream cycle shutdown timeout is 2s (reduced from 5s by BF-207)."""
        from probos.startup import shutdown as shutdown_mod
        source = inspect.getsource(shutdown_mod.shutdown)

        # Should contain timeout=2.0 for dream cycle
        assert "timeout=2.0" in source, \
            "Dream cycle timeout should be 2.0s"
        # Should NOT contain the old 5.0 timeout
        assert "timeout=5.0" not in source, \
            "Old 5.0s dream cycle timeout should be removed"

    def test_timeout_warning_says_2s(self):
        """Timeout warning message mentions 2s limit."""
        from probos.startup import shutdown as shutdown_mod
        source = inspect.getsource(shutdown_mod.shutdown)

        assert 'timed out (2s limit)' in source, \
            "Timeout warning should say '2s limit'"
        assert 'timed out (5s limit)' not in source, \
            "Old '5s limit' warning should be removed"

    def test_episodic_stop_before_service_stops(self):
        """BF-207 complete fix: episodic_memory.stop() before service cleanup."""
        from probos.startup import shutdown as shutdown_mod
        source = inspect.getsource(shutdown_mod.shutdown)

        episodic_stop_pos = source.find("await runtime.episodic_memory.stop()")
        acm_stop_pos = source.find("# Stop ACM")

        assert episodic_stop_pos != -1, "episodic_memory.stop() must exist"
        assert acm_stop_pos != -1, "ACM stop block must exist"
        assert episodic_stop_pos < acm_stop_pos, \
            "episodic_memory.stop() must come before service stops (ACM)"
        # Pin uniqueness — catch stale duplicates from incomplete cut-paste
        assert source.count("await runtime.episodic_memory.stop()") == 1, \
            "episodic_memory.stop() must appear exactly once (no duplicates)"

    def test_dream_consolidation_before_episodic_stop(self):
        """Dream consolidation must complete before episodic memory closes."""
        from probos.startup import shutdown as shutdown_mod
        source = inspect.getsource(shutdown_mod.shutdown)

        dream_pos = source.find("runtime.dream_scheduler.engine.dream_cycle()")
        episodic_stop_pos = source.find("await runtime.episodic_memory.stop()")

        assert dream_pos != -1, "dream_cycle() must exist in shutdown"
        assert episodic_stop_pos != -1, "episodic_memory.stop() must exist"
        assert dream_pos < episodic_stop_pos, \
            "dream_cycle() must run before episodic_memory.stop()"
        # Pin uniqueness — catch stale duplicates from incomplete cut-paste
        assert source.count("runtime.dream_scheduler.engine.dream_cycle()") == 1, \
            "dream_cycle() must appear exactly once (no duplicates)"
        assert source.count("await _eviction_audit.stop()") == 1, \
            "_eviction_audit.stop() must appear exactly once (no duplicates)"

    def test_phase_comments_present(self):
        """Shutdown has Phase 1 (critical persistence) and Phase 2 (service cleanup) markers."""
        from probos.startup import shutdown as shutdown_mod
        source = inspect.getsource(shutdown_mod.shutdown)

        assert "Phase 1: Critical Persistence" in source
        assert "Phase 2: Service Cleanup" in source


# ===========================================================================
# __main__.py Shutdown Timeout
# ===========================================================================

class TestMainShutdownTimeout:
    """Verify __main__.py shutdown timeout is 10s (BF-207)."""

    def test_boot_and_run_timeout_10s(self):
        """_boot_and_run shutdown uses 10s timeout."""
        import probos.__main__ as main_mod
        source = inspect.getsource(main_mod._boot_and_run)
        assert "runtime.stop(reason=" in source and "timeout=10" in source, \
            "runtime.stop() shutdown timeout should be 10s"
        assert "timeout=5)" not in source, "old 5s timeout should be removed"

    def test_serve_timeout_10s(self):
        """_serve shutdown uses 10s timeout for runtime, 5s for adapter."""
        import probos.__main__ as main_mod
        source = inspect.getsource(main_mod._serve)
        # Pin both: runtime stop at 10s AND adapter stop at 5s (asymmetric by design)
        assert "runtime.stop(), timeout=10" in source, \
            "runtime.stop() should use 10s timeout"
        assert "adapter.stop(), timeout=5" in source, \
            "adapter.stop() should remain at 5s (separate concern)"


# ===========================================================================
# Startup Hash Integrity Sweep
# ===========================================================================

class TestStartupHashSweep:
    """BF-207: Startup hash integrity sweep."""

    @pytest.mark.asyncio
    async def test_sweep_heals_mismatches(self):
        """Sweep detects and heals stale content hashes."""
        from probos.cognitive.episodic import sweep_hash_integrity, compute_episode_hash

        ep = Episode(
            id="sweep-test-1",
            timestamp=1000.0,
            user_input="Sweep test input",
            dag_summary={},
            outcomes=[],
            agent_ids=["agent-1"],
            duration_ms=50.0,
        )
        correct_hash = compute_episode_hash(ep)

        # Mock episodic memory with one episode that has a stale hash
        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection

        mock_collection.get.return_value = {
            "ids": ["sweep-test-1"],
            "metadatas": [{
                "timestamp": 1000.0,
                "user_input": "Sweep test input",
                "dag_summary_json": "{}",
                "outcomes_json": "[]",
                "reflection": "",
                "agent_ids_json": '["agent-1"]',
                "duration_ms": 50.0,
                "shapley_values_json": "{}",
                "trust_deltas_json": "[]",
                "source": "direct",
                "anchors_json": "",
                "content_hash": "stale_hash_from_crash",
                "_hash_v": 2,
                "importance": 5,
            }],
            "documents": ["Sweep test input"],
        }

        healed = await sweep_hash_integrity(mock_em)

        assert healed == 1
        mock_collection.update.assert_called_once()
        call_kwargs = mock_collection.update.call_args
        updated_meta = call_kwargs[1]["metadatas"][0]
        assert updated_meta["content_hash"] == correct_hash

    @pytest.mark.asyncio
    async def test_sweep_batches_multiple_mismatches(self):
        """Sweep issues a single batch .update() call for multiple mismatches."""
        from probos.cognitive.episodic import sweep_hash_integrity

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection

        # Three episodes, all with stale hashes
        ids = ["ep-a", "ep-b", "ep-c"]
        base_meta = {
            "dag_summary_json": "{}",
            "outcomes_json": "[]",
            "reflection": "",
            "agent_ids_json": "[]",
            "duration_ms": 10.0,
            "shapley_values_json": "{}",
            "trust_deltas_json": "[]",
            "source": "direct",
            "anchors_json": "",
            "content_hash": "stale",
            "_hash_v": 2,
            "importance": 5,
        }
        metas = []
        docs = []
        for i, ep_id in enumerate(ids):
            m = dict(base_meta)
            m["timestamp"] = float(1000 + i)
            m["user_input"] = f"input-{ep_id}"
            metas.append(m)
            docs.append(f"input-{ep_id}")

        mock_collection.get.return_value = {
            "ids": ids,
            "metadatas": metas,
            "documents": docs,
        }

        healed = await sweep_hash_integrity(mock_em)

        assert healed == 3
        # Must be a single batched call, not 3 individual calls
        mock_collection.update.assert_called_once()
        call_kwargs = mock_collection.update.call_args[1]
        assert call_kwargs["ids"] == ["ep-c", "ep-b", "ep-a"]  # sorted by timestamp desc

    @pytest.mark.asyncio
    async def test_sweep_skips_matching_hashes(self):
        """Sweep does not touch episodes with correct hashes."""
        from probos.cognitive.episodic import sweep_hash_integrity, compute_episode_hash

        ep = Episode(
            id="clean-1",
            timestamp=2000.0,
            user_input="Clean episode",
            dag_summary={},
            outcomes=[],
            agent_ids=["agent-2"],
            duration_ms=75.0,
        )
        correct_hash = compute_episode_hash(ep)

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection

        mock_collection.get.return_value = {
            "ids": ["clean-1"],
            "metadatas": [{
                "timestamp": 2000.0,
                "user_input": "Clean episode",
                "dag_summary_json": "{}",
                "outcomes_json": "[]",
                "reflection": "",
                "agent_ids_json": '["agent-2"]',
                "duration_ms": 75.0,
                "shapley_values_json": "{}",
                "trust_deltas_json": "[]",
                "source": "direct",
                "anchors_json": "",
                "content_hash": correct_hash,
                "_hash_v": 2,
                "importance": 5,
            }],
            "documents": ["Clean episode"],
        }

        healed = await sweep_hash_integrity(mock_em)

        assert healed == 0
        mock_collection.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_sweep_skips_legacy_episodes(self):
        """Sweep ignores episodes with no stored hash (legacy)."""
        from probos.cognitive.episodic import sweep_hash_integrity

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection

        mock_collection.get.return_value = {
            "ids": ["legacy-1"],
            "metadatas": [{
                "timestamp": 500.0,
                "user_input": "Old episode",
                "dag_summary_json": "{}",
                "outcomes_json": "[]",
                "reflection": "",
                "agent_ids_json": "[]",
                "duration_ms": 0.0,
                "shapley_values_json": "{}",
                "trust_deltas_json": "[]",
                "source": "direct",
                "anchors_json": "",
                "content_hash": "",
                "_hash_v": 0,
                "importance": 5,
            }],
            "documents": ["Old episode"],
        }

        healed = await sweep_hash_integrity(mock_em)

        assert healed == 0
        mock_collection.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_sweep_handles_empty_collection(self):
        """Sweep returns 0 for empty collection."""
        from probos.cognitive.episodic import sweep_hash_integrity

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection
        mock_collection.get.return_value = {"ids": [], "metadatas": [], "documents": []}

        healed = await sweep_hash_integrity(mock_em)
        assert healed == 0

    @pytest.mark.asyncio
    async def test_sweep_handles_no_collection(self):
        """Sweep returns 0 when episodic memory has no collection."""
        from probos.cognitive.episodic import sweep_hash_integrity

        mock_em = MagicMock()
        mock_em._collection = None

        healed = await sweep_hash_integrity(mock_em)
        assert healed == 0

    @pytest.mark.asyncio
    async def test_sweep_graceful_on_exception(self):
        """Sweep catches exceptions and returns 0."""
        from probos.cognitive.episodic import sweep_hash_integrity

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection
        mock_collection.get.side_effect = RuntimeError("ChromaDB unavailable")

        healed = await sweep_hash_integrity(mock_em)
        assert healed == 0
