from __future__ import annotations

import time

import pytest

from probos.cognitive.oracle_service import OracleService
from probos.config import ArchiveConfig
from probos.knowledge.archive_store import ArchiveEntry, ArchiveStore, PromotionOutcome, PromotionRecord, SourceKind
from probos.storage.sqlite_factory import SQLiteConnectionFactory


@pytest.mark.asyncio
async def test_archive_store_initialize(tmp_path) -> None:
    store = _make_store(tmp_path)
    try:
        await store.initialize()
        assert await store.count() == 0
    finally:
        await store.close()


# AD-1341 S1 (#1569): ``append`` is gone and ``promote_entry`` is the archive's one write. This test asserted that
# the old write returned an id; it now asserts that the one write archives a record.
@pytest.mark.asyncio
async def test_archive_store_promote(tmp_path) -> None:
    store = _make_store(tmp_path)
    try:
        await store.initialize()
        outcome = await _append_entry(store, title="Exit note", content="Keep logs")
        assert outcome is PromotionOutcome.CREATED
        assert await store.count() == 1
    finally:
        await store.close()


def test_archive_store_append_only() -> None:
    # AD-1341 S1 (#1569): no update, delete or append. The one removal is the Captain's ``erase_entry``, reached
    # only from ``probos archive erase``; tests/test_ad1341_s1_archive_store.py holds its marker contract.
    assert not hasattr(ArchiveStore, "update")
    assert not hasattr(ArchiveStore, "delete")
    assert not hasattr(ArchiveStore, "append")


@pytest.mark.asyncio
async def test_archive_store_search_by_keyword(tmp_path) -> None:
    store = _make_store(tmp_path)
    try:
        await store.initialize()
        await _append_entry(store, title="Warp", content="Plasma manifold")
        await _append_entry(store, title="Shields", content="Emitter alignment")
        await _append_entry(store, title="Sensors", content="Lateral array")

        results = await store.search("Emitter")

        assert len(results) == 1
        assert results[0].title == "Shields"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_archive_store_search_by_category(tmp_path) -> None:
    store = _make_store(tmp_path)
    try:
        await store.initialize()
        # AD-1341 S1 (#1569): an entry's category is now its source kind; the filter is unchanged.
        await _append_entry(
            store,
            source_kind=SourceKind.CONVERGENCE_REPORT,
            title="Warp",
            content="Shared keyword",
        )
        await _append_entry(
            store,
            source_kind=SourceKind.CAPTAINS_LOG,
            title="Procedure",
            content="Shared keyword",
        )

        results = await store.search("Shared", category="captains_log")

        assert len(results) == 1
        assert results[0].category == "captains_log"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_archive_store_count(tmp_path) -> None:
    store = _make_store(tmp_path)
    try:
        await store.initialize()
        for index in range(5):
            await _append_entry(store, title=f"Entry {index}", content="content")

        assert await store.count() == 5
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_oracle_service_queries_archive_tier(tmp_path) -> None:
    store = _make_store(tmp_path)
    try:
        await store.initialize()
        await _append_entry(
            store,
            source_kind=SourceKind.NOTEBOOK_FINDING,  # AD-1341 S1 (#1569): the category is the source kind
            title="Reset lesson",
            content="Preserve mission logs",
            author_callsign="Chapel",
        )
        oracle = OracleService(archive_store=store)

        results = await oracle.query("mission", tiers=["archive"])

        assert len(results) == 1
        assert results[0].source_tier == "archive"
        assert "Reset lesson" in results[0].content
        assert results[0].metadata["author"] == "Chapel"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_oracle_default_tiers_include_archive() -> None:
    archive_store = _FakeArchiveStore(
        [
            ArchiveEntry(
                id=1,
                timeline_id="timeline-123456",
                category="observation",
                title="Mission archive",
                content="Archive memory",
                author_agent_type="science",
                author_callsign="Spock",
                archived_at=time.time(),
            )
        ]
    )
    oracle = OracleService(archive_store=archive_store)

    results = await oracle.query("archive")

    assert archive_store.queries == [("archive", 5)]
    assert [result.source_tier for result in results] == ["archive"]


def test_archive_config_defaults() -> None:
    config = ArchiveConfig()

    assert config.enabled is True
    assert config.db_path == ""


def _make_store(tmp_path) -> ArchiveStore:
    return ArchiveStore(
        str(tmp_path / "archive.db"),
        connection_factory=SQLiteConnectionFactory(),
    )


async def _append_entry(
    store: ArchiveStore,
    *,
    timeline_id: str = "timeline-1",
    source_kind: SourceKind = SourceKind.NOTEBOOK_FINDING,
    title: str,
    content: str,
    author_agent_type: str = "medical",
    author_callsign: str = "Chapel",
) -> PromotionOutcome:
    # AD-1341 S1 (#1569): ``append`` is gone; ``promote_entry`` is the archive's one write. The helper keeps its
    # name so the tests above read as before; each entry is a ship-classified record with its own source ref.
    return await store.promote_entry(
        PromotionRecord(
            timeline_id=timeline_id,
            source_kind=source_kind,
            source_ref=f"notebooks/{author_callsign}/{title}.md",
            title=title,
            content=content,
            classification="ship",
            author_callsign=author_callsign,
            author_agent_type=author_agent_type,
            metadata={"source": "test"},
        )
    )


class _FakeArchiveStore:
    def __init__(self, entries: list[ArchiveEntry]) -> None:
        self._entries = entries
        self.queries: list[tuple[str, int]] = []

    async def search(self, query: str, *, limit: int = 10) -> list[ArchiveEntry]:
        self.queries.append((query, limit))
        return self._entries[:limit]
