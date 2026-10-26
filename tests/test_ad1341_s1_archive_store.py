"""AD-1341 S1 M1 (#1569): the Ship's Archive's schema v1, its one write and the Captain's erasure.

Every test runs the real ``ArchiveStore`` through the startup's ``default_factory`` on a temporary file and
reads the file back with ``sqlite3``, so what is asserted is what is on disk.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.oracle_service import OracleService
from probos.knowledge.archive_store import (
    ARCHIVE_REASON_MAX_CHARS,
    ARCHIVE_SCHEMA_VERSION,
    PROMOTABLE_CLASSIFICATIONS,
    ArchiveStore,
    GenerationOutcome,
    GenerationRecord,
    PromotionOutcome,
    PromotionRecord,
    SourceKind,
)
from probos.storage.sqlite_factory import default_factory

# The AD-524 schema exactly as it shipped, before AD-1341: the shape of the live vessel's file.
_V0_SCHEMA = """
CREATE TABLE IF NOT EXISTS archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author_agent_type TEXT NOT NULL DEFAULT '',
    author_callsign TEXT NOT NULL DEFAULT '',
    archived_at REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_archive_category ON archive(category);
CREATE INDEX IF NOT EXISTS idx_archive_timeline ON archive(timeline_id);
"""
_V1_COLUMNS = ("source_kind", "source_ref", "content_sha256", "classification", "author_did", "source_episode_ids")


def _store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _record(**overrides: Any) -> PromotionRecord:
    fields: dict[str, Any] = {
        "timeline_id": "timeline-one",
        "source_kind": SourceKind.CONVERGENCE_REPORT,
        "source_ref": "reports/convergence/convergence-20261022-000000.md",
        "title": "convergence-20261022-000000",
        "content": "## Convergence Report\n\nThree officers independently traced the coolant drift.",
        "classification": "ship",
        "author_callsign": "system",
    }
    fields.update(overrides)
    return PromotionRecord(**fields)


def _plant_v0(path: Path, *, extra_column: bool = False) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(_V0_SCHEMA)
        for title in ("Legacy one", "Legacy two"):
            connection.execute(
                "INSERT INTO archive (timeline_id, category, title, content, archived_at) VALUES (?, ?, ?, ?, ?)",
                ("timeline-zero", "lesson_learned", title, f"{title} content", 1.0),
            )
        if extra_column:  # a migration that stopped after its first column
            connection.execute("ALTER TABLE archive ADD COLUMN source_kind TEXT NOT NULL DEFAULT ''")
        connection.commit()
    finally:
        connection.close()


# --- A1 to A3: the schema -------------------------------------------------------------------------------------


async def test_a_fresh_archive_opens_at_schema_v1_with_its_tables(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.count() == 0
    finally:
        await store.close()
    path = tmp_path / "archive.db"
    assert ARCHIVE_SCHEMA_VERSION == 1
    assert _rows(path, "PRAGMA user_version") == [(1,)]
    assert set(_V1_COLUMNS) <= {row[1] for row in _rows(path, "PRAGMA table_info(archive)")}
    tables = {row[0] for row in _rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"archive", "generations", "archive_erasures"} <= tables
    index = _rows(path, "SELECT sql FROM sqlite_master WHERE name = 'idx_archive_promotion_key'")
    assert len(index) == 1
    assert "UNIQUE" in index[0][0] and "WHERE content_sha256 IS NOT NULL" in index[0][0]


@pytest.mark.parametrize("interrupted", [False, True], ids=["v0", "interrupted"])
async def test_a_v0_archive_keeps_its_rows_and_is_migrated_in_place(tmp_path: Path, interrupted: bool) -> None:
    path = tmp_path / "archive.db"
    _plant_v0(path, extra_column=interrupted)
    assert _rows(path, "PRAGMA user_version") == [(0,)]  # premise: the live vessel's archive is v0
    for _ in range(2):  # the second open finds v1 and changes nothing
        store = _store(tmp_path)
        await store.initialize()
        try:
            legacy = await store.search("Legacy")
        finally:
            await store.close()
        assert sorted(entry.title for entry in legacy) == ["Legacy one", "Legacy two"]
        assert all(entry.source_kind == "" and entry.content_sha256 == "" for entry in legacy)
    assert _rows(path, "PRAGMA user_version") == [(1,)]
    assert _rows(path, "SELECT content_sha256, classification, author_did, source_episode_ids FROM archive") == [
        (None, "", "", "[]"),
        (None, "", "", "[]"),
    ]


@pytest.mark.parametrize("version", [2, -1], ids=["later", "negative"])
async def test_an_archive_of_another_schema_version_is_refused(tmp_path: Path, version: int) -> None:
    path = tmp_path / "archive.db"
    _plant_v0(path)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    finally:
        connection.close()
    store = _store(tmp_path)
    with pytest.raises(RuntimeError, match="schema version"):
        await store.initialize()
    assert await store.entry_by_id(1) is None  # nothing was opened
    assert _rows(path, "PRAGMA user_version") == [(version,)]
    assert "source_kind" not in {row[1] for row in _rows(path, "PRAGMA table_info(archive)")}


# --- A4 to A7: the one write ----------------------------------------------------------------------------------


@pytest.mark.parametrize("second_timeline", ["timeline-one", "timeline-two"], ids=["same-timeline", "next-timeline"])
async def test_a_source_and_content_are_archived_once_whatever_the_timeline(
    tmp_path: Path, second_timeline: str,
) -> None:
    first = _record()
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.promote_entry(first) is PromotionOutcome.CREATED
        assert await store.promote_entry(_record(timeline_id=second_timeline)) is PromotionOutcome.PRESENT
        entry = (await store.get_recent())[0]
    finally:
        await store.close()
    rows = _rows(
        tmp_path / "archive.db",
        "SELECT timeline_id, category, title, content, author_callsign, source_kind, source_ref, content_sha256, "
        "classification, author_did, source_episode_ids FROM archive",
    )
    assert rows == [(
        "timeline-one", "convergence_report", first.title, first.content, "system", "convergence_report",
        first.source_ref, hashlib.sha256(first.content.encode("utf-8")).hexdigest(), "ship", "", "[]",
    )]
    assert (entry.source_kind, entry.source_ref, entry.content_sha256, entry.classification) == (
        "convergence_report", first.source_ref, first.content_sha256, "ship",
    )
    assert entry.source_episode_ids == ()


async def test_changed_content_from_the_same_source_is_a_new_entry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.promote_entry(_record()) is PromotionOutcome.CREATED
        revised = _record(content="## Convergence Report\n\nRevised after review.", source_episode_ids=("ep-1",))
        assert await store.promote_entry(revised) is PromotionOutcome.CREATED
        found = await store.search("Revised after review")
    finally:
        await store.close()
    assert len(_rows(tmp_path / "archive.db", "SELECT id FROM archive")) == 2
    assert [entry.source_episode_ids for entry in found] == [("ep-1",)]


@pytest.mark.parametrize(
    "overrides",
    [
        {"classification": "private"},
        {"classification": "department"},
        {"classification": "secret"},
        {"source_kind": "convergence_report"},
        {"source_ref": "  "},
        {"content": ""},
        {"timeline_id": ""},
        {"title": " "},
        {"source_episode_ids": ["ep-1"]},
        {"metadata": {"when": object()}},
    ],
    ids=[
        "private", "department", "unknown-class", "plain-str-kind", "blank-ref", "empty-content",
        "empty-timeline", "blank-title", "list-episode-ids", "unserialisable-metadata",
    ],
)
def test_a_record_the_archive_must_not_hold_is_refused_when_built(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _record(**overrides)


def test_source_kinds_are_closed_and_none_is_an_episode() -> None:
    # AD-1341 S4 (#1569): the exit note joins the closed set. It is a lesson a crew agent writes for its successor and
    # cites that agent's episodes by id; it is not an episode, so the assertion below still holds.
    assert {kind.value for kind in SourceKind} == {
        "convergence_report", "published_report", "captains_log", "notebook_finding", "exit_note",
    }
    assert not any("episode" in kind.value for kind in SourceKind)
    assert PROMOTABLE_CLASSIFICATIONS == frozenset({"ship", "fleet"})
    assert _record(classification="fleet").classification == "fleet"  # premise: the gate admits both


async def test_promote_entry_takes_only_a_promotion_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        with pytest.raises(TypeError):
            await store.promote_entry({"timeline_id": "timeline-one"})  # type: ignore[arg-type]
        assert await store.count() == 0
    finally:
        await store.close()


def test_the_store_has_no_append_update_or_delete_and_names_its_writes() -> None:
    for name in ("append", "update", "delete"):
        assert not hasattr(ArchiveStore, name)
    public = {
        name for name in vars(ArchiveStore)
        if not name.startswith("_") and callable(getattr(ArchiveStore, name))
    }
    # AD-1341 S3 (#1569): the Captain's veto (a write of no entry, Captain-only through ``probos archive veto``) and
    # two reads, the review's and the AD-754 erasure check's. There is still no update or delete of an entry.
    assert public == {
        "initialize", "close", "promote_entry", "record_generation", "erase_entry", "entry_by_id",
        "search", "get_recent", "count", "veto_source", "source_state", "entry_ids_citing",
    }


# --- A8 to A11: the Captain's erasure -------------------------------------------------------------------------


async def test_erasure_deletes_the_row_and_leaves_only_a_content_free_marker(tmp_path: Path) -> None:
    probe = f"AD1341-ERASE-PROBE-{uuid.uuid4().hex}"
    title_probe = f"AD1341-TITLE-PROBE-{uuid.uuid4().hex}"
    erased = _record(
        source_kind=SourceKind.NOTEBOOK_FINDING, source_ref="notebooks/Chapel/coolant.md",
        title=title_probe, content=f"{probe} " * 8, author_callsign="Chapel",
    )
    kept = _record()
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.promote_entry(kept) is PromotionOutcome.CREATED
        assert await store.promote_entry(erased) is PromotionOutcome.CREATED
        entry_id = next(entry.id for entry in await store.get_recent() if entry.title == title_probe)
        assert await store.erase_entry(entry_id, "Captain's order: not for later crews") is True
        assert await store.entry_by_id(entry_id) is None
        assert [entry.title for entry in await store.get_recent()] == [kept.title]
    finally:
        await store.close()
    path = tmp_path / "archive.db"
    columns = [row[1] for row in _rows(path, "PRAGMA table_info(archive_erasures)")]
    assert columns == ["id", "entry_id", "timeline_id", "source_kind", "source_ref", "reason", "erased_at"]
    markers = _rows(
        path, "SELECT entry_id, timeline_id, source_kind, source_ref, reason, erased_at FROM archive_erasures",
    )
    assert len(markers) == 1
    assert markers[0][:5] == (
        entry_id, "timeline-one", "notebook_finding", "notebooks/Chapel/coolant.md",
        "Captain's order: not for later crews",
    )
    assert markers[0][5] > 0
    raw = path.read_bytes()
    assert kept.content.encode("utf-8") in raw  # premise: the bytes check reads real row content
    assert probe.encode("utf-8") not in raw  # secure_delete overwrote the freed cell
    assert title_probe.encode("utf-8") not in raw


@pytest.mark.parametrize(
    ("content", "timeline"),
    [(None, "timeline-one"), ("Revised after the erasure.", "timeline-one"), (None, "timeline-two")],
    ids=["same-content", "changed-content", "next-timeline"],
)
async def test_an_erased_source_is_not_promoted_again(tmp_path: Path, content: str | None, timeline: str) -> None:
    first = _record()
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.promote_entry(first) is PromotionOutcome.CREATED
        entry_id = (await store.get_recent())[0].id
        assert await store.erase_entry(entry_id, "Captain's order") is True
        again = _record(timeline_id=timeline, content=content or first.content)
        assert await store.promote_entry(again) is PromotionOutcome.ERASED
        assert await store.count() == 0
    finally:
        await store.close()


async def test_erasing_an_absent_entry_writes_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await store.promote_entry(_record())
        assert await store.erase_entry(9999, "Captain's order") is False
        assert await store.count() == 1
    finally:
        await store.close()
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive_erasures") == []


@pytest.mark.parametrize(
    ("entry_id", "reason"),
    [
        (1, ""), (1, "   "), (1, "x" * (ARCHIVE_REASON_MAX_CHARS + 1)), (1, None),
        (0, "Captain's order"), (True, "Captain's order"),
    ],
    ids=["empty", "blank", "too-long", "not-a-string", "zero-id", "bool-id"],
)
async def test_an_erasure_needs_a_reason_and_a_real_id(tmp_path: Path, entry_id: Any, reason: Any) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await store.promote_entry(_record())
        with pytest.raises(ValueError):
            await store.erase_entry(entry_id, reason)
        assert await store.count() == 1
    finally:
        await store.close()
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive_erasures") == []


# --- A12: generations -----------------------------------------------------------------------------------------


async def test_a_generation_close_is_recorded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        promoted = await store.record_generation(GenerationRecord(
            timeline_id="timeline-one", reset_tier=2, outcome=GenerationOutcome.PROMOTED,
            created=3, present=1, erased=1, withheld=2,
        ))
        skipped = await store.record_generation(GenerationRecord(
            timeline_id="", reset_tier=3, outcome=GenerationOutcome.SKIPPED,
            reason="Captain: records already exported",
        ))
    finally:
        await store.close()
    rows = _rows(
        tmp_path / "archive.db",
        "SELECT id, timeline_id, reset_tier, outcome, created_count, present_count, erased_count, "
        "withheld_count, reason FROM generations ORDER BY id",
    )
    assert rows == [
        (promoted, "timeline-one", 2, "promoted", 3, 1, 1, 2, ""),
        (skipped, "", 3, "skipped", 0, 0, 0, 0, "Captain: records already exported"),
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"reset_tier": 1},
        {"outcome": GenerationOutcome.SKIPPED},
        {"timeline_id": ""},
        {"created": -1},
        {"outcome": "promoted"},
        {"reset_tier": True},
    ],
    ids=["tier-1", "skipped-without-reason", "promoted-without-timeline", "negative-count", "str-outcome", "bool-tier"],
)
def test_an_invalid_generation_close_is_refused(overrides: dict[str, Any]) -> None:
    fields: dict[str, Any] = {"timeline_id": "timeline-one", "reset_tier": 2, "outcome": GenerationOutcome.PROMOTED}
    fields.update(overrides)
    with pytest.raises(ValueError):
        GenerationRecord(**fields)


# --- A13: the seam --------------------------------------------------------------------------------------------


async def test_the_oracle_reads_a_promoted_entry_across_the_seam(tmp_path: Path) -> None:
    record = _record()
    store = _store(tmp_path)
    await store.initialize()
    try:
        await store.promote_entry(record)
        results = await OracleService(archive_store=store).query("coolant drift", tiers=["archive"])
    finally:
        await store.close()
    assert len(results) == 1
    assert results[0].source_tier == "archive"
    assert record.title in results[0].content
    assert results[0].metadata["timeline_id"] == "timeline-one"
    assert results[0].metadata["category"] == "convergence_report"


# --- A14 to A16 (Amendment A2): one transaction at a time (F1); ids beyond SQLite (F2) ------------------------

_SECOND_REF = "reports/convergence/convergence-20261023-000000.md"


def _closure() -> GenerationRecord:
    return GenerationRecord(
        timeline_id="timeline-one", reset_tier=2, outcome=GenerationOutcome.PROMOTED, created=1,
    )


async def _promoted_entry_id(store: ArchiveStore) -> int:
    assert await store.promote_entry(_record()) is PromotionOutcome.CREATED
    return (await store.get_recent())[0].id


def _refuse_generations(path: Path) -> None:
    """Make every ``generations`` insert fail inside the store: a database failure the store cannot prevent."""
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            "CREATE TRIGGER refuse_generations BEFORE INSERT ON generations "
            "BEGIN SELECT RAISE (ABORT, 'AD-1341 A2: injected failure'); END"
        )
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize(
    "pair", ["erase-and-missing-erase", "missing-erase-and-promote", "missing-erase-and-generation"],
)
async def test_overlapping_writes_never_report_a_success_another_write_undid(tmp_path: Path, pair: str) -> None:
    """F1: what each overlapping call reports is what the file holds, read back with ``sqlite3``."""
    reason = "Captain's order"
    store = _store(tmp_path)
    await store.initialize()
    try:
        entry_id = await _promoted_entry_id(store)
        missing_id = entry_id + 1000
        if pair == "erase-and-missing-erase":
            results = await asyncio.gather(
                store.erase_entry(entry_id, reason), store.erase_entry(missing_id, reason),
            )
        elif pair == "missing-erase-and-promote":
            results = await asyncio.gather(
                store.erase_entry(missing_id, reason), store.promote_entry(_record(source_ref=_SECOND_REF)),
            )
        else:
            results = await asyncio.gather(store.erase_entry(missing_id, reason), store.record_generation(_closure()))
    finally:
        await store.close()
    path = tmp_path / "archive.db"
    if pair == "erase-and-missing-erase":
        assert results == [True, False]
        assert _rows(path, "SELECT id FROM archive") == []  # the erasure it reported is on disk
        assert _rows(path, "SELECT entry_id FROM archive_erasures") == [(entry_id,)]
    elif pair == "missing-erase-and-promote":
        assert results == [False, PromotionOutcome.CREATED]
        assert _rows(path, "SELECT source_ref FROM archive ORDER BY id") == [(_record().source_ref,), (_SECOND_REF,)]
        assert _rows(path, "SELECT id FROM archive_erasures") == []
    else:
        assert results[0] is False
        assert _rows(path, "SELECT id FROM generations") == [(results[1],)]


async def test_close_waits_for_a_write_in_progress(tmp_path: Path) -> None:
    """F1: ``close`` never ends a write's transaction; it waits for the commit."""
    store = _store(tmp_path)
    await store.initialize()
    try:
        entry_id = await _promoted_entry_id(store)
        results = await asyncio.wait_for(
            asyncio.gather(store.erase_entry(entry_id, "Captain's order"), store.close(), return_exceptions=True),
            timeout=30,
        )
    finally:
        await store.close()  # nothing left to close once the gathered close ran
    assert results == [True, None]
    path = tmp_path / "archive.db"
    assert _rows(path, "SELECT id FROM archive") == []
    assert _rows(path, "SELECT entry_id FROM archive_erasures") == [(entry_id,)]


async def test_a_failed_write_leaves_an_overlapping_erasure_intact(tmp_path: Path) -> None:
    """F1: a write that fails rolls back only itself, and its error still reaches its caller."""
    store = _store(tmp_path)
    await store.initialize()
    try:
        entry_id = await _promoted_entry_id(store)
        _refuse_generations(tmp_path / "archive.db")
        erased, failed = await asyncio.gather(
            store.erase_entry(entry_id, "Captain's order"), store.record_generation(_closure()),
            return_exceptions=True,
        )
    finally:
        await store.close()
    assert erased is True
    assert isinstance(failed, sqlite3.DatabaseError)  # premise: the injected failure reached the store
    path = tmp_path / "archive.db"
    assert _rows(path, "SELECT id FROM archive") == []
    assert _rows(path, "SELECT entry_id FROM archive_erasures") == [(entry_id,)]
    assert _rows(path, "SELECT id FROM generations") == []


@pytest.mark.parametrize("entry_id", [2**63 - 1, 2**63, 2**64], ids=["largest-rowid", "above-sqlite", "far-above"])
async def test_an_id_no_row_can_have_is_no_entry(tmp_path: Path, entry_id: int) -> None:
    """F2: an id above SQLite's largest rowid is a missing id (None, then False), not an ``OverflowError``."""
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _promoted_entry_id(store)
        assert await store.entry_by_id(entry_id) is None
        assert await store.erase_entry(entry_id, "Captain's order") is False
        assert await store.count() == 1
    finally:
        await store.close()
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive_erasures") == []
