"""AD-1341 S3 M1 (#1569): the Captain's veto record, the review's read and the citation read of the Ship's Archive.

The real ``ArchiveStore`` through the startup's ``default_factory`` on a temporary file, read back with ``sqlite3``;
Ship's Records written by the store's own producers; the real promotion service. Every test states its premise first,
so "not archived" can never mean "was never eligible".
"""

from __future__ import annotations

import ast
import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import probos
from probos.knowledge.archive_promotion import promote_ship_records, review_promotion
from probos.knowledge.archive_store import PromotionOutcome, SourceKind, SourceState, VetoOutcome
from tests.test_ad1341_s1_archive_store import _plant_v0, _record, _rows, _store
from tests.test_ad1341_s1_reset_and_erase import (
    _CONVERGENCE,
    _NEXT_SHIP,
    _SHIP,
    _data_dir,
    _records,
    _write_records,
)

_SRC = Path(probos.__file__).resolve().parent
_SECOND = "reports/convergence/convergence-20261022-000001.md"
_REPORT = "reports/coolant-review.md"
_FINDING = "notebooks/Chapel/coolant-finding.md"
_PRIVATE = "notebooks/Chapel/private-coolant-c0ffee02.md"  # S1's private notebook: withheld (C1)
_REVISED = "## Convergence Report\n\nFour officers now trace the coolant drift."
_TABLES = ("archive", "archive_erasures", "archive_vetoes", "generations")
_VETO_COLUMNS = ["id", "timeline_id", "source_kind", "source_ref", "reason", "vetoed_at"]
_EXPECTED_STATE = {
    "new": SourceState(PromotionOutcome.CREATED, ()),
    "present": SourceState(PromotionOutcome.PRESENT, (1,)),
    "revised": SourceState(PromotionOutcome.CREATED, (1,)),
    "erased": SourceState(PromotionOutcome.ERASED, ()),
    "vetoed": SourceState(PromotionOutcome.VETOED, ()),
}


def _counts(path: Path) -> dict[str, int]:
    """Rows per table: what a read must leave as it found it."""
    return {table: _rows(path, f"SELECT COUNT(*) FROM {table}")[0][0] for table in _TABLES}


def _vetoes(path: Path) -> list[tuple[Any, ...]]:
    return _rows(path, "SELECT timeline_id, source_kind, source_ref, reason FROM archive_vetoes ORDER BY id")


def _naming(name: str) -> set[str]:
    """The ``src`` files that name ``name`` as an attribute or spell it as a string (S1's census rule)."""
    naming: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == name) or (
                isinstance(node, ast.Constant) and node.value == name
            ):
                naming.add(path.relative_to(_SRC).as_posix())
    return naming


async def _review_scene(data_dir: Path, archive: Any, path: Path) -> dict[str, str]:
    """Ship's Records and the archive in every state the review shows; returns each state's Ship's Records path."""
    await _write_records(data_dir)  # a convergence report, the Captain's log and a private notebook (withheld)
    writer = _records(data_dir)
    await writer.write_entry(
        author="system", path=_SECOND, content="## Convergence Report\n\nThe relief valves agree.",
        message="AD-551: Convergence report (valves)", classification="ship",
    )
    first = await promote_ship_records(writer, archive, timeline_id=_SHIP)
    assert len(first.created) == 3 and len(first.withheld) == 1  # premise: both reports and the Captain's log
    (log_ref,) = [ref for ref in first.created if ref.startswith("captains-log/")]
    (log_id,) = _rows(path, "SELECT id FROM archive WHERE source_ref = ?", (log_ref,))[0]
    assert await archive.erase_entry(log_id, "the Captain's own log stays aboard")
    await writer.write_entry(
        author="system", path=_CONVERGENCE, content=_REVISED,
        message="AD-551: Convergence report (coolant, revised)", classification="ship",
    )
    await writer.write_entry(
        author="Chapel", path=_REPORT, content="The coolant review, as published.", message="Coolant review",
        classification="ship", status="published",
    )
    assert await archive.veto_source(SourceKind.PUBLISHED_REPORT, _REPORT, "not canon yet") is VetoOutcome.RECORDED
    await writer.write_notebook(
        callsign="Chapel", topic_slug="coolant-finding", content="Claim: the coolant drift is thermal.",
        classification="ship", extra_frontmatter={"claim_id": "c0ffee03c0ffee03", "contest_state": "uncontested"},
    )
    return {"revised": _CONVERGENCE, "present": _SECOND, "erased": log_ref, "vetoed": _REPORT, "new": _FINDING}


# --- V1: the table -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("shape", ["fresh", "s1-file"])
async def test_the_archive_has_a_content_free_veto_table_keyed_by_source(tmp_path: Path, shape: str) -> None:
    path = tmp_path / "archive.db"
    if shape == "s1-file":
        _plant_v0(path)
        earlier = _store(tmp_path)
        await earlier.initialize()
        await earlier.close()
        connection = sqlite3.connect(str(path))
        try:
            connection.execute("DROP TABLE archive_vetoes")  # the file as S1 left it: v1, with no veto table
            connection.commit()
        finally:
            connection.close()
        tables = {row[0] for row in _rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "archive_vetoes" not in tables and "archive_erasures" in tables  # premise: an S1-era v1 file
    store = _store(tmp_path)
    await store.initialize()
    await store.close()

    assert _rows(path, "PRAGMA user_version") == [(1,)]
    assert [row[1] for row in _rows(path, "PRAGMA table_info(archive_vetoes)")] == _VETO_COLUMNS
    (sql,) = _rows(path, "SELECT sql FROM sqlite_master WHERE name = 'idx_archive_vetoes_source'")[0]
    assert sql.startswith("CREATE UNIQUE INDEX") and "(source_kind, source_ref)" in sql
    if shape == "s1-file":
        assert _rows(path, "SELECT title FROM archive ORDER BY id") == [("Legacy one",), ("Legacy two",)]


# --- V2 to V4: the veto ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("attempt", ["same-content", "revised-content", "next-timeline"])
async def test_a_vetoed_source_is_never_archived_with_any_content(tmp_path: Path, attempt: str) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        record = _record()
        assert _counts(path)["archive"] == 0  # premise: nothing archived yet
        outcome = await store.veto_source(
            record.source_kind, record.source_ref, "  not canon: one officer's reading  ", timeline_id=" timeline-one ",
        )
        assert outcome is VetoOutcome.RECORDED
        later = {
            "same-content": record,
            "revised-content": _record(content=_REVISED),
            "next-timeline": _record(timeline_id="timeline-two"),
        }[attempt]
        assert await store.promote_entry(later) is PromotionOutcome.VETOED
    finally:
        await store.close()

    assert _counts(path) == {"archive": 0, "archive_erasures": 0, "archive_vetoes": 1, "generations": 0}
    assert _vetoes(path) == [("timeline-one", "convergence_report", record.source_ref, "not canon: one officer's reading")]


@pytest.mark.parametrize(
    ("setup", "expected", "vetoes"),
    [("archived", VetoOutcome.ARCHIVED, 0), ("erased", VetoOutcome.ERASED, 0), ("again", VetoOutcome.ALREADY_VETOED, 1)],
    ids=["archived", "erased", "again"],
)
async def test_a_veto_that_would_change_nothing_writes_nothing(
    tmp_path: Path, setup: str, expected: VetoOutcome, vetoes: int,
) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        record = _record()
        if setup in ("archived", "erased"):
            assert await store.promote_entry(record) is PromotionOutcome.CREATED  # entry 1
        if setup == "erased":
            assert await store.erase_entry(1, "erased for the test")
        if setup == "again":
            assert await store.veto_source(record.source_kind, record.source_ref, "the first veto") is VetoOutcome.RECORDED

        assert await store.veto_source(record.source_kind, record.source_ref, "a second reason") is expected
    finally:
        await store.close()

    assert _counts(path)["archive_vetoes"] == vetoes
    assert _counts(path)["archive"] == (1 if setup == "archived" else 0)
    if setup == "again":
        assert _vetoes(path) == [("", "convergence_report", record.source_ref, "the first veto")]


@pytest.mark.parametrize(
    ("kind", "ref", "reason", "timeline"),
    [
        ("convergence_report", "reports/convergence/x.md", "why", ""),
        (SourceKind.PUBLISHED_REPORT, "   ", "why", ""),
        (SourceKind.PUBLISHED_REPORT, 7, "why", ""),
        (SourceKind.PUBLISHED_REPORT, "reports/x.md", "   ", ""),
        (SourceKind.PUBLISHED_REPORT, "reports/x.md", "x" * 501, ""),
        (SourceKind.PUBLISHED_REPORT, "reports/x.md", "why", 7),
    ],
    ids=["str-kind", "blank-ref", "int-ref", "blank-reason", "long-reason", "int-timeline"],
)
async def test_a_veto_needs_a_kind_a_source_and_a_reason(
    tmp_path: Path, kind: Any, ref: Any, reason: Any, timeline: Any,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        with pytest.raises(ValueError):
            await store.veto_source(kind, ref, reason, timeline_id=timeline)
    finally:
        await store.close()
    assert _counts(tmp_path / "archive.db")["archive_vetoes"] == 0


# --- V5, V5b: one rule for the review and the promotion -----------------------------------------------------------


@pytest.mark.parametrize("state", ["new", "present", "revised", "erased", "vetoed"])
async def test_the_review_reads_what_promote_entry_then_does(tmp_path: Path, state: str) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        original = _record()
        if state in ("present", "revised", "erased"):
            assert await store.promote_entry(original) is PromotionOutcome.CREATED  # entry 1
        if state == "erased":
            assert await store.erase_entry(1, "erased for the test")
        if state == "vetoed":
            assert await store.veto_source(original.source_kind, original.source_ref, "not canon") is VetoOutcome.RECORDED
        record = _record(content=_REVISED) if state == "revised" else original
        expected = _EXPECTED_STATE[state]
        before = _counts(path)

        preview = await store.source_state(record)

        assert _counts(path) == before  # a read: nothing recorded
        assert preview == expected
        assert await store.promote_entry(record) is expected.outcome
    finally:
        await store.close()


@pytest.mark.parametrize("between", ["veto", "erasure"])
async def test_a_veto_or_erasure_after_the_review_decides_the_promotion(tmp_path: Path, between: str) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        if between == "erasure":
            assert await store.promote_entry(_record()) is PromotionOutcome.CREATED  # entry 1, the earlier version
        record = _record(content=_REVISED)
        assert (await store.source_state(record)).outcome is PromotionOutcome.CREATED  # premise: it would be archived
        if between == "veto":
            assert await store.veto_source(record.source_kind, record.source_ref, "not canon") is VetoOutcome.RECORDED
        else:
            assert await store.erase_entry(1, "erased after the review")
        expected = PromotionOutcome.VETOED if between == "veto" else PromotionOutcome.ERASED

        assert await store.promote_entry(record) is expected
        assert (await store.source_state(record)).outcome is expected
    finally:
        await store.close()
    assert _rows(path, "SELECT COUNT(*) FROM archive WHERE content = ?", (_REVISED,)) == [(0,)]


# --- V6, V6b: the citation read -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        (["ep-a"], ("one",)),
        (["ep-c", "ep-a"], ("one", "two")),
        (["ep-z"], ()),
        (["", "ep-b"], ("two",)),
        ([], ()),
        (("ep-b",), ("two",)),
    ],
    ids=["one", "two-in-id-order", "none", "blank-ignored", "empty", "tuple"],
)
async def test_the_entries_citing_an_episode_are_found_in_id_order(
    tmp_path: Path, asked: Any, expected: tuple[str, ...],
) -> None:
    path = tmp_path / "archive.db"
    _plant_v0(path)  # two AD-524 rows: no citations, never a match
    store = _store(tmp_path)
    await store.initialize()
    try:
        for name, cited in (("one", ("ep-a",)), ("two", ("ep-b", "ep-c")), ("none", ())):
            created = await store.promote_entry(_record(source_ref=f"reports/convergence/{name}.md", source_episode_ids=cited))
            assert created is PromotionOutcome.CREATED
        ids = {
            ref.rsplit("/", 1)[-1].removesuffix(".md"): entry_id
            for entry_id, ref in _rows(path, "SELECT id, source_ref FROM archive WHERE source_ref != ''")
        }
        before = _counts(path)

        found = await store.entry_ids_citing(asked)

        assert _counts(path) == before
    finally:
        await store.close()
    assert found == tuple(ids[name] for name in expected)


@pytest.mark.parametrize("fault", ["not-open", "a-string", "corrupt-row"])
async def test_the_citation_read_never_answers_none_when_it_cannot_read(tmp_path: Path, fault: str) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    if fault == "not-open":
        with pytest.raises(RuntimeError):
            await store.entry_ids_citing(["ep-a"])
        return
    await store.initialize()
    try:
        if fault == "a-string":
            with pytest.raises(TypeError):
                await store.entry_ids_citing("ep-a")
            return
        connection = sqlite3.connect(str(path))
        try:
            connection.execute(
                "INSERT INTO archive (timeline_id, category, title, content, archived_at, source_kind, source_ref, "
                "source_episode_ids) VALUES ('t', 'c', 't', 'c', 0, 'convergence_report', 'r', '{not json')"
            )
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(ValueError):
            await store.entry_ids_citing(["ep-a"])
    finally:
        await store.close()


# --- V7: overlapping writes ----------------------------------------------------------------------------------------


async def test_a_veto_and_a_promotion_of_one_source_never_both_succeed(tmp_path: Path) -> None:
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        record = _record()
        vetoed, promoted = await asyncio.gather(
            store.veto_source(record.source_kind, record.source_ref, "an overlapping veto"), store.promote_entry(record),
        )
    finally:
        await store.close()
    counts = _counts(path)
    assert (vetoed, promoted, counts["archive"], counts["archive_vetoes"]) in {
        (VetoOutcome.RECORDED, PromotionOutcome.VETOED, 0, 1),
        (VetoOutcome.ARCHIVED, PromotionOutcome.CREATED, 1, 0),
    }


# --- V8 to V10: the service --------------------------------------------------------------------------------------


async def test_the_promotion_reports_a_vetoed_source_and_archives_the_rest(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    await _write_records(data_dir)
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        assert await store.veto_source(SourceKind.CONVERGENCE_REPORT, _CONVERGENCE, "not canon") is VetoOutcome.RECORDED
        report = await promote_ship_records(_records(data_dir), store, timeline_id=_SHIP)
    finally:
        await store.close()

    assert report.vetoed == (_CONVERGENCE,)
    assert len(report.created) == 1 and report.created[0].startswith("captains-log/")
    assert (report.present, report.erased, report.withheld) == ((), (), (_PRIVATE,))
    assert _rows(path, "SELECT COUNT(*) FROM archive WHERE source_ref = ?", (_CONVERGENCE,)) == [(0,)]


async def test_the_review_shows_what_promoting_each_source_now_would_do_and_writes_nothing(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    path = tmp_path / "archive.db"
    store = _store(tmp_path)
    await store.initialize()
    try:
        refs = await _review_scene(data_dir, store, path)
        before = _counts(path)

        review = await review_promotion(_records(data_dir), store, timeline_id=_NEXT_SHIP)

        after = _counts(path)
    finally:
        await store.close()
    ids = dict(_rows(path, "SELECT source_ref, id FROM archive"))
    states = {pending.record.source_ref: pending.state for pending in review.sources}
    assert states == {
        refs["revised"]: SourceState(PromotionOutcome.CREATED, (ids[refs["revised"]],)),
        refs["present"]: SourceState(PromotionOutcome.PRESENT, (ids[refs["present"]],)),
        refs["erased"]: SourceState(PromotionOutcome.ERASED, ()),
        refs["vetoed"]: SourceState(PromotionOutcome.VETOED, ()),
        refs["new"]: SourceState(PromotionOutcome.CREATED, ()),
    }
    assert {pending.record.timeline_id for pending in review.sources} == {_NEXT_SHIP}
    assert review.withheld == (_PRIVATE,)
    assert after == before


def test_only_the_review_reads_what_a_promotion_would_do() -> None:
    """``source_state`` is named in ``src`` by the review service alone, beside its definition."""
    assert _naming("source_state") == {"knowledge/archive_promotion.py"}
