"""AD-818a: Paginated, cancellable episodic migrations (issue #751 #2/#3).

Verifies the new ``_iter_collection_pages`` helper and the per-page streaming
conversion of the three scan-and-rewrite migrations:
- ``migrate_episode_agent_ids`` (BF-103)
- ``migrate_anchor_metadata`` (AD-570)
- ``migrate_participant_index`` (AD-570b)

Uses REAL in-memory ChromaDB (no MagicMock at the ChromaDB boundary). Multi-page
behavior is forced by monkeypatching ``probos.cognitive.episodic._MIGRATION_BATCH_SIZE``
to a small value (works ONLY because the helper resolves ``page_size`` at call
time per R1), or by passing an explicit small ``page_size`` to the helper directly.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.cognitive import episodic as episodic_mod
from probos.cognitive.episodic import (
    EpisodicMemory,
    _iter_collection_pages,
    migrate_anchor_metadata,
    migrate_episode_agent_ids,
    migrate_participant_index,
)
from probos.cognitive.participant_index import ParticipantIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(mappings: dict[str, str] | None = None) -> MagicMock:
    """Mock identity registry: {slot_id: sovereign_uuid}. (Not the chroma boundary.)"""
    reg = MagicMock()
    mappings = mappings or {}

    def _get_by_slot(slot_id: str):
        if slot_id in mappings:
            return SimpleNamespace(agent_uuid=mappings[slot_id])
        return None

    reg.get_by_slot = MagicMock(side_effect=_get_by_slot)
    return reg


def _base_meta(*, agent_ids_json: str = "[]", anchors_json: str = "") -> dict:
    return {
        "timestamp": time.time(),
        "intent_type": "",
        "dag_summary_json": "{}",
        "outcomes_json": "[]",
        "reflection": "",
        "agent_ids_json": agent_ids_json,
        "duration_ms": 10.0,
        "shapley_values_json": "{}",
        "trust_deltas_json": "[]",
        "source": "direct",
        "anchors_json": anchors_json,
        "content_hash": "",
        "_hash_v": 2,
    }


def _seed(
    mem: EpisodicMemory,
    ep_id: str,
    *,
    agent_ids_json: str = "[]",
    anchors_json: str = "",
    extra_meta: dict | None = None,
) -> None:
    """Add a single episode directly to the collection WITHOUT promoted fields."""
    meta = _base_meta(agent_ids_json=agent_ids_json, anchors_json=anchors_json)
    if extra_meta:
        meta.update(extra_meta)
    mem._collection.add(ids=[ep_id], documents=[f"doc {ep_id}"], metadatas=[meta])


async def _new_mem(
    tmp_path, name: str, *, with_participants: bool = False
) -> EpisodicMemory:
    mem = EpisodicMemory(
        db_path=tmp_path / f"{name}.db", max_episodes=100, relevance_threshold=0.3
    )
    await mem.start()
    if with_participants:
        idx = ParticipantIndex(db_path=str(tmp_path / f"{name}_pi.db"))
        await idx.start()
        mem.set_participant_index(idx)  # mem.stop() stops the sidecar (AD-570b)
    return mem


# ---------------------------------------------------------------------------
# Helper-direct tests (#1-#4) — pass explicit small page_size
# ---------------------------------------------------------------------------

class TestIterCollectionPages:
    """Direct tests of _iter_collection_pages with an explicit page_size arg."""

    @pytest.mark.asyncio
    async def test_empty_collection_yields_nothing(self, tmp_path):
        """#1: empty collection -> loop body never runs."""
        mem = await _new_mem(tmp_path, "empty")
        try:
            pages = [
                p
                async for p in _iter_collection_pages(
                    mem._collection, include=["metadatas"], page_size=2
                )
            ]
            assert pages == []
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_single_short_page_all_ids(self, tmp_path):
        """#2: fewer rows than page_size -> exactly one page, all ids present."""
        mem = await _new_mem(tmp_path, "short")
        try:
            for i in range(3):
                _seed(mem, f"ep-{i}")
            pages = [
                p
                async for p in _iter_collection_pages(
                    mem._collection, include=["metadatas"], page_size=10
                )
            ]
            assert len(pages) == 1
            assert set(pages[0]["ids"]) == {"ep-0", "ep-1", "ep-2"}
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_exact_multiple_no_dup_no_infinite(self, tmp_path):
        """#3: seed 2*N, page_size=N -> every id once, no duplicate/empty trailing page."""
        mem = await _new_mem(tmp_path, "exact")
        try:
            n = 3
            for i in range(2 * n):
                _seed(mem, f"ep-{i}")
            seen: list[str] = []
            pages = 0
            async for p in _iter_collection_pages(
                mem._collection, include=["metadatas"], page_size=n
            ):
                pages += 1
                seen.extend(p["ids"])
                assert len(p["ids"]) > 0  # no empty trailing page yielded
            assert pages == 2
            assert sorted(seen) == sorted(f"ep-{i}" for i in range(2 * n))
            assert len(seen) == len(set(seen))  # no id seen twice
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_multiple_pages_partial_last(self, tmp_path):
        """#4: partial last page -> union == full collection, no id twice."""
        mem = await _new_mem(tmp_path, "partial")
        try:
            total = 7
            for i in range(total):
                _seed(mem, f"ep-{i}")
            seen: list[str] = []
            async for p in _iter_collection_pages(
                mem._collection, include=["metadatas"], page_size=3
            ):
                seen.extend(p["ids"])
            assert sorted(seen) == sorted(f"ep-{i}" for i in range(total))
            assert len(seen) == len(set(seen))
        finally:
            await mem.stop()


# ---------------------------------------------------------------------------
# Cancellability (#5) — DETERMINISTIC via blocking to_thread (Rec1)
# ---------------------------------------------------------------------------

class TestCancellability:
    @pytest.mark.asyncio
    async def test_wait_for_cancels_at_page_boundary(self, tmp_path, monkeypatch):
        """#5: monkeypatch _MIGRATION_BATCH_SIZE=2 + slow per-page fetch; wait_for
        with a tight timeout must raise AND stop early (proves problem #3 fixed).
        Uses migrate_participant_index (its only to_thread is the page get)."""
        mem = await _new_mem(tmp_path, "cancel", with_participants=True)
        try:
            # Seed 6 episodes -> with page_size 2 that's 3 data pages + 1 empty.
            for i in range(6):
                _seed(mem, f"ep-{i}", agent_ids_json=json.dumps([f"a{i}"]))

            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)

            completed = {"n": 0}
            real_to_thread = asyncio.to_thread
            delay = 0.1

            async def slow_to_thread(func, *args, **kwargs):
                await asyncio.sleep(delay)
                result = await real_to_thread(func, *args, **kwargs)
                completed["n"] += 1
                return result

            monkeypatch.setattr(episodic_mod.asyncio, "to_thread", slow_to_thread)

            # 4 page-fetches * 0.1s = 0.4s total; timeout 0.15s -> cancels early.
            with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
                await asyncio.wait_for(migrate_participant_index(mem), timeout=0.15)

            # Stopped EARLY: fewer than the 4 page-fetches a full run would do.
            assert completed["n"] < 4
        finally:
            await mem.stop()


# ---------------------------------------------------------------------------
# Per-migration equivalence (#6-#9) — monkeypatch _MIGRATION_BATCH_SIZE small
# ---------------------------------------------------------------------------

class TestMigrateEpisodeAgentIds:
    @pytest.mark.asyncio
    async def test_multi_page_rewrite_and_idempotent(self, tmp_path, monkeypatch):
        """#6: multi-page slot->sovereign rewrite; count == changed; rerun == 0."""
        mem = await _new_mem(tmp_path, "bf103")
        try:
            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)
            for i in range(5):
                _seed(mem, f"ep-{i}", agent_ids_json=json.dumps([f"slot_{i}"]))
            reg = _make_registry({f"slot_{i}": f"sov-{i}" for i in range(5)})

            migrated = await migrate_episode_agent_ids(mem, reg)
            assert migrated == 5  # spans 3 pages (2+2+1)

            # Verify every slot id was rewritten to its sovereign id.
            for i in range(5):
                res = mem._collection.get(ids=[f"ep-{i}"], include=["metadatas"])
                assert json.loads(res["metadatas"][0]["agent_ids_json"]) == [f"sov-{i}"]

            # Idempotent: second run finds nothing to change.
            assert await migrate_episode_agent_ids(mem, reg) == 0
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_empty_collection_returns_zero(self, tmp_path):
        """#9: empty collection -> 0, no error."""
        mem = await _new_mem(tmp_path, "bf103empty")
        try:
            reg = _make_registry({})
            assert await migrate_episode_agent_ids(mem, reg) == 0
        finally:
            await mem.stop()


class TestMigrateAnchorMetadata:
    @pytest.mark.asyncio
    async def test_multi_page_backfill_and_noop_rerun(self, tmp_path, monkeypatch):
        """#7: multi-page anchor promotion across >=2 pages; re-run is a no-op."""
        mem = await _new_mem(tmp_path, "ad570")
        try:
            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)
            for i in range(5):
                anchors = {
                    "department": f"dept{i}",
                    "channel": "ward_room",
                    "trigger_type": "dm",
                    "trigger_agent": "bones",
                    "watch_section": "first_watch",
                }
                _seed(mem, f"ep-{i}", anchors_json=json.dumps(anchors))

            migrated = await migrate_anchor_metadata(mem)
            assert migrated == 5

            for i in range(5):
                res = mem._collection.get(ids=[f"ep-{i}"], include=["metadatas"])
                meta = res["metadatas"][0]
                assert meta["anchor_department"] == f"dept{i}"
                assert meta["anchor_watch_section"] == "first_watch"

            # Re-run: all episodes now have anchor_watch_section -> skipped.
            assert await migrate_anchor_metadata(mem) == 0
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_empty_collection_returns_zero(self, tmp_path):
        """#9: empty collection -> 0, no error."""
        mem = await _new_mem(tmp_path, "ad570empty")
        try:
            assert await migrate_anchor_metadata(mem) == 0
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_per_page_write_failure_non_fatal(self, tmp_path, monkeypatch):
        """#10: BF-103/AD-570 R2 — a failing page's upsert is logged and skipped;
        remaining pages still processed; migration does NOT raise."""
        mem = await _new_mem(tmp_path, "ad570fail")
        try:
            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)
            for i in range(6):
                anchors = {"department": f"dept{i}", "watch_section": "w"}
                _seed(mem, f"ep-{i}", anchors_json=json.dumps(anchors))

            orig_upsert = mem._collection.upsert
            calls = {"n": 0}

            def failing_upsert(*args, **kwargs):
                calls["n"] += 1
                if calls["n"] == 2:  # fail the second page only
                    raise RuntimeError("simulated chroma upsert failure")
                return orig_upsert(*args, **kwargs)

            monkeypatch.setattr(mem._collection, "upsert", failing_upsert)

            # 6 episodes / page_size 2 = 3 pages; page 2 fails -> 2 pages survive.
            migrated = await migrate_anchor_metadata(mem)
            assert migrated == 4
            assert calls["n"] == 3  # all three pages attempted
        finally:
            await mem.stop()


class TestMigrateParticipantIndex:
    @pytest.mark.asyncio
    async def test_multi_page_populate(self, tmp_path, monkeypatch):
        """#8: multi-page populate of the sidecar; count == participating episodes."""
        mem = await _new_mem(tmp_path, "ad570b", with_participants=True)
        try:
            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)
            # 5 participating (agent_ids) + 1 non-participating (empty) = 6 rows.
            for i in range(5):
                _seed(mem, f"ep-{i}", agent_ids_json=json.dumps([f"sov-{i}"]))
            _seed(mem, "ep-none", agent_ids_json="[]")

            migrated = await migrate_participant_index(mem)
            assert migrated == 5  # only participating episodes counted

            ids = await mem._participant_index.get_episode_ids_for_agent("sov-0")
            assert "ep-0" in ids
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_empty_collection_returns_zero(self, tmp_path):
        """#9: empty collection -> 0, no error."""
        mem = await _new_mem(tmp_path, "ad570bempty", with_participants=True)
        try:
            assert await migrate_participant_index(mem) == 0
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_record_failure_propagates(self, tmp_path, monkeypatch):
        """#11: AD-570b R2 — a record_episode_batch failure PROPAGATES (no swallow),
        proving no new try/except was added around the per-page write."""
        mem = await _new_mem(tmp_path, "ad570bfail", with_participants=True)
        try:
            monkeypatch.setattr(episodic_mod, "_MIGRATION_BATCH_SIZE", 2)
            for i in range(4):
                _seed(mem, f"ep-{i}", agent_ids_json=json.dumps([f"sov-{i}"]))

            async def boom(_batch):
                raise RuntimeError("simulated sidecar failure")

            monkeypatch.setattr(mem._participant_index, "record_episode_batch", boom)

            with pytest.raises(RuntimeError, match="simulated sidecar failure"):
                await migrate_participant_index(mem)
        finally:
            await mem.stop()
