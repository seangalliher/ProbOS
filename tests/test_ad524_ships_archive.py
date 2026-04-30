from __future__ import annotations

import time

import pytest

from probos.cognitive.oracle_service import OracleService
from probos.config import ArchiveConfig
from probos.knowledge.archive_store import ArchiveEntry, ArchiveStore
from probos.storage.sqlite_factory import SQLiteConnectionFactory


@pytest.mark.asyncio
async def test_archive_store_initialize(tmp_path) -> None:
    store = _make_store(tmp_path)
    try:
        await store.initialize()
        assert await store.count() == 0
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_archive_store_append(tmp_path) -> None:
    store = _make_store(tmp_path)
    try:
        await store.initialize()
        entry_id = await _append_entry(store, title="Exit note", content="Keep logs")
        assert entry_id > 0
    finally:
        await store.close()


def test_archive_store_append_only() -> None:
    assert not hasattr(ArchiveStore, "update")
    assert not hasattr(ArchiveStore, "delete")


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
        await _append_entry(
            store,
            category="lesson_learned",
            title="Warp",
            content="Shared keyword",
        )
        await _append_entry(
            store,
            category="procedure",
            title="Procedure",
            content="Shared keyword",
        )

        results = await store.search("Shared", category="procedure")

        assert len(results) == 1
        assert results[0].category == "procedure"
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
            category="exit_note",
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
    category: str = "duty_report",
    title: str,
    content: str,
    author_agent_type: str = "medical",
    author_callsign: str = "Chapel",
) -> int:
    return await store.append(
        timeline_id=timeline_id,
        category=category,
        title=title,
        content=content,
        author_agent_type=author_agent_type,
        author_callsign=author_callsign,
        metadata={"source": "test"},
    )


class _FakeArchiveStore:
    def __init__(self, entries: list[ArchiveEntry]) -> None:
        self._entries = entries
        self.queries: list[tuple[str, int]] = []

    async def search(self, query: str, *, limit: int = 10) -> list[ArchiveEntry]:
        self.queries.append((query, limit))
        return self._entries[:limit]
