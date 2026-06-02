"""AD-818a-2: Paginated, cancellable AD-605 + BF-207 migrations (issue #751).

Extends the AD-818a pagination work to the last two scan-and-rewrite
migrations:
- ``migrate_enriched_embedding`` (AD-605) — re-embeds every episode with
  enriched document text, one bounded page at a time, each page a single
  batched in-place ``collection.update``.
- ``sweep_hash_integrity`` (BF-207) — streams every page into a bounded
  size-``max_episodes`` min-heap keyed by timestamp so only the newest
  episodes are retained, drains the heap newest-first, and batch-heals stale
  content hashes. Honest-degrade is now owned by the ``_run_one_migration``
  wrapper at the call site, so the function no longer swallows exceptions.

Uses REAL in-memory ChromaDB at the boundary wherever practical (mirroring
``test_ad818a_paginated_migrations.py``). Multi-page behavior is forced by
monkeypatching ``probos.cognitive.episodic._MIGRATION_BATCH_SIZE`` small —
which works ONLY because ``_iter_collection_pages`` resolves ``page_size`` at
call time (R1). MagicMock collections are used only for the two BF-207 PIN
tests that must assert exact in-place ``update`` ordering parity with the
pre-pagination sweep.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import MagicMock

import pytest

from probos.cognitive import episodic as episodic_mod
from probos.cognitive.episodic import (
    EpisodicMemory,
    migrate_enriched_embedding,
    sweep_hash_integrity,
)
from probos.types import Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_meta(*, content_hash: str = "", **overrides) -> dict:
    meta = {
        "timestamp": time.time(),
        "intent_type": "",
        "dag_summary_json": "{}",
        "outcomes_json": "[]",
        "reflection": "",
        "agent_ids_json": "[]",
        "duration_ms": 10.0,
        "shapley_values_json": "{}",
        "trust_deltas_json": "[]",
        "source": "direct",
        "anchors_json": "",
        "content_hash": content_hash,
        "_hash_v": 2,
    }
    meta.update(overrides)
    return meta


def _seed(mem: EpisodicMemory, ep_id: str, *, content_hash: str = "", **overrides) -> None:
    """Add one episode directly to the collection WITHOUT promoted fields."""
    meta = _base_meta(content_hash=content_hash, **overrides)
    mem._collection.add(ids=[ep_id], documents=[f"doc {ep_id}"], metadatas=[meta])


async def _new_mem(tmp_path, name: str) -> EpisodicMemory:
    mem = EpisodicMemory(
        db_path=tmp_path / f"{name}.db", max_episodes=100, relevance_threshold=0.3
    )
    await mem.start()
    return mem


# ---------------------------------------------------------------------------
# AD-605: migrate_enriched_embedding — paginated re-embed
# ---------------------------------------------------------------------------

class TestMigrateEnrichedEmbedding:
    @pytest.mark.asyncio
    async def test_multi_page_reembed_and_version_marker(self, tmp_path, monkeypatch):
        """Multi-page re-embed across >=2 pages; docs enriched; marker set to 1."""
        mem = await _new_mem(tmp_path, "ad605multi")
        try:
            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)
            anchors = {
                "department": "engineering",
                "channel": "ward_room",
                "watch_section": "second",
                "trigger_type": "direct_message",
            }
            for i in range(5):
                _seed(mem, f"ep-{i}", anchors_json=json.dumps(anchors))

            migrated = await migrate_enriched_embedding(mem)
            assert migrated == 5  # spans 3 pages (2 + 2 + 1)

            # Every doc was rebuilt with the bracketed anchor prefix and the
            # original raw text preserved; user_input meta populated.
            for i in range(5):
                res = mem._collection.get(
                    ids=[f"ep-{i}"], include=["documents", "metadatas"]
                )
                doc = res["documents"][0]
                assert "[engineering]" in doc
                assert "[second]" in doc
                assert f"doc ep-{i}" in doc
                assert res["metadatas"][0]["user_input"] == f"doc ep-{i}"

            # Version marker written to the collection metadata.
            assert mem._collection.metadata.get("enriched_embedding_version") == 1
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_idempotent_rerun_returns_zero(self, tmp_path, monkeypatch):
        """Second run short-circuits on the version marker and re-embeds nothing."""
        mem = await _new_mem(tmp_path, "ad605idem")
        try:
            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)
            for i in range(3):
                _seed(mem, f"ep-{i}")

            assert await migrate_enriched_embedding(mem) == 3
            assert await migrate_enriched_embedding(mem) == 0
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_empty_collection_sets_marker(self, tmp_path):
        """Empty collection -> 0 re-embedded but version marker still set to 1."""
        mem = await _new_mem(tmp_path, "ad605empty")
        try:
            migrated = await migrate_enriched_embedding(mem)
            assert migrated == 0
            assert mem._collection.metadata.get("enriched_embedding_version") == 1
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_return_count_matches_migrated(self, tmp_path, monkeypatch):
        """Return value equals the number of episodes actually re-embedded."""
        mem = await _new_mem(tmp_path, "ad605count")
        try:
            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 3)
            for i in range(7):
                _seed(mem, f"ep-{i}")
            assert await migrate_enriched_embedding(mem) == 7
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_wait_for_cancels_at_page_boundary(self, tmp_path, monkeypatch):
        """DETERMINISTIC cancellability: slow per-page to_thread + tight wait_for
        timeout must raise AND stop early (proves the re-embed yields between
        pages so _run_one_migration's wait_for can cancel at a page boundary)."""
        mem = await _new_mem(tmp_path, "ad605cancel")
        try:
            for i in range(6):
                _seed(mem, f"ep-{i}")

            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)

            completed = {"n": 0}
            real_to_thread = asyncio.to_thread

            async def slow_to_thread(func, *args, **kwargs):
                await asyncio.sleep(0.1)
                result = await real_to_thread(func, *args, **kwargs)
                completed["n"] += 1
                return result

            monkeypatch.setattr(episodic_mod.asyncio, "to_thread", slow_to_thread)

            with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
                await asyncio.wait_for(migrate_enriched_embedding(mem), timeout=0.15)

            # Stopped EARLY: a full 3-page run does >2 to_thread calls (get+update
            # per page); the tight timeout cancels before all pages complete.
            assert completed["n"] < 6
        finally:
            await mem.stop()


# ---------------------------------------------------------------------------
# BF-207: sweep_hash_integrity — bounded-heap newest-K, batch heal
# ---------------------------------------------------------------------------

class TestSweepHashIntegrity:
    @pytest.mark.asyncio
    async def test_heap_retains_newest_across_pages(self, tmp_path, monkeypatch):
        """Bounded heap keeps only the newest max_episodes across multiple pages;
        older stale episodes are NOT healed (they fall off the heap)."""
        mem = await _new_mem(tmp_path, "bf207heap")
        try:
            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)
            # 6 stale episodes, ascending timestamps; newest three are ep-3/4/5.
            for i in range(6):
                _seed(mem, f"ep-{i}", content_hash="stale", timestamp=float(1000 + i))

            healed = await sweep_hash_integrity(mem, max_episodes=3)
            assert healed == 3  # only the newest three retained by the heap

            for i in range(6):
                res = mem._collection.get(ids=[f"ep-{i}"], include=["metadatas"])
                stored = res["metadatas"][0]["content_hash"]
                if i >= 3:
                    assert stored != "stale"  # newest -> healed
                else:
                    assert stored == "stale"  # oldest -> evicted, untouched
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_heal_across_pages(self, tmp_path, monkeypatch):
        """All stale episodes across multiple pages are healed when the heap
        budget exceeds the population."""
        mem = await _new_mem(tmp_path, "bf207heal")
        try:
            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)
            for i in range(5):
                _seed(mem, f"ep-{i}", content_hash="stale", timestamp=float(1000 + i))

            healed = await sweep_hash_integrity(mem, max_episodes=100)
            assert healed == 5

            for i in range(5):
                res = mem._collection.get(ids=[f"ep-{i}"], include=["metadatas"])
                assert res["metadatas"][0]["content_hash"] != "stale"
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_single_batched_update(self):
        """Multiple mismatches issue exactly one batched .update() call."""
        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection

        ids = ["ep-a", "ep-b", "ep-c"]
        metas = []
        docs = []
        for i, ep_id in enumerate(ids):
            metas.append(_base_meta(content_hash="stale", timestamp=float(1000 + i),
                                    user_input=f"input-{ep_id}"))
            docs.append(f"input-{ep_id}")
        mock_collection.get.return_value = {"ids": ids, "metadatas": metas, "documents": docs}

        healed = await sweep_hash_integrity(mock_em)
        assert healed == 3
        mock_collection.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_descending_order_pin(self):
        """PIN: the batched update lists ids in descending (timestamp, seq) order,
        matching the pre-pagination sweep exactly."""
        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection

        ids = ["ep-a", "ep-b", "ep-c"]
        metas = []
        docs = []
        for i, ep_id in enumerate(ids):
            metas.append(_base_meta(content_hash="stale", timestamp=float(1000 + i),
                                    user_input=f"input-{ep_id}"))
            docs.append(f"input-{ep_id}")
        mock_collection.get.return_value = {"ids": ids, "metadatas": metas, "documents": docs}

        await sweep_hash_integrity(mock_em)
        call_kwargs = mock_collection.update.call_args[1]
        assert call_kwargs["ids"] == ["ep-c", "ep-b", "ep-a"]  # newest-first

    @pytest.mark.asyncio
    async def test_skips_matching_hashes(self, tmp_path):
        """Episodes whose stored hash already matches are left untouched."""
        mem = await _new_mem(tmp_path, "bf207match")
        try:
            ep = Episode(
                id="ep-ok",
                timestamp=1000.0,
                user_input="correct input",
                dag_summary={},
                outcomes=[],
                agent_ids=["agent-1"],
                duration_ms=50.0,
            )
            await mem.store(ep)  # store() writes the correct content_hash

            healed = await sweep_hash_integrity(mem)
            assert healed == 0
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_skips_legacy_no_hash(self, tmp_path):
        """Legacy episodes with no stored hash are skipped (nothing to verify)."""
        mem = await _new_mem(tmp_path, "bf207legacy")
        try:
            _seed(mem, "ep-legacy", content_hash="", timestamp=1000.0)
            assert await sweep_hash_integrity(mem) == 0
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_empty_collection_returns_zero(self, tmp_path):
        """Empty collection -> 0 healed, no error."""
        mem = await _new_mem(tmp_path, "bf207empty")
        try:
            assert await sweep_hash_integrity(mem) == 0
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_no_collection_returns_zero(self):
        """No backing collection -> 0 healed, no error."""
        mock_em = MagicMock()
        mock_em._collection = None
        assert await sweep_hash_integrity(mock_em) == 0

    @pytest.mark.asyncio
    async def test_wait_for_cancels_at_page_boundary(self, tmp_path, monkeypatch):
        """DETERMINISTIC cancellability: slow per-page get + tight wait_for timeout
        must raise AND stop early (proves the sweep yields between pages)."""
        mem = await _new_mem(tmp_path, "bf207cancel")
        try:
            for i in range(6):
                _seed(mem, f"ep-{i}", content_hash="stale", timestamp=float(1000 + i))

            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)

            completed = {"n": 0}
            real_to_thread = asyncio.to_thread

            async def slow_to_thread(func, *args, **kwargs):
                await asyncio.sleep(0.1)
                result = await real_to_thread(func, *args, **kwargs)
                completed["n"] += 1
                return result

            monkeypatch.setattr(episodic_mod.asyncio, "to_thread", slow_to_thread)

            # 3 data pages + 1 empty = 4 page-fetches at 0.1s each = 0.4s;
            # timeout 0.15s cancels before they all complete.
            with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
                await asyncio.wait_for(
                    sweep_hash_integrity(mem, max_episodes=100), timeout=0.15
                )

            assert completed["n"] < 4
        finally:
            await mem.stop()
