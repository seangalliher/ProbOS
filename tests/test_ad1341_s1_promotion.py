"""AD-1341 S1 M2 (#1569): the records-only promotion service and the shared records-path resolver.

Ship's Records are written through the store's own producers, as the vessel writes them (``write_entry`` as
AD-551's convergence step calls it, ``write_notebook`` as AD-1140's publish_finding calls it,
``append_captains_log``), and read back by a ``RecordsStore`` that is never initialised, which is what
``probos reset`` has on a stopped vessel. The archive is the real ``ArchiveStore`` through
``default_factory``; the end of the chain is the real ``OracleService``.
"""

from __future__ import annotations

import ast
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import probos
from probos.cognitive.oracle_service import OracleService
from probos.config import RecordsConfig, resolve_records_repo_path
from probos.knowledge.archive_promotion import (
    ARCHIVE_READER,
    PromotionReport,
    plan_promotion,
    promote_ship_records,
    source_kind_for,
)
from probos.knowledge.archive_store import ArchiveStore, SourceKind
from probos.knowledge.records_store import RecordsStore
from probos.storage.sqlite_factory import default_factory

_SRC = Path(probos.__file__).resolve().parent
_CLAIM = {"claim_id": "c0ffee00c0ffee00", "contest_state": "uncontested"}
_PROMOTED = ("convergence", "captains-log", "published-report", "finding-ship", "finding-fleet")
_NOT_SELECTED = (
    "draft-report", "gap-report", "convergence-by-agent", "captains-log-by-agent", "manual", "creative",
    "duty-log", "plain-ship-notebook",
)
_WITHHELD = ("private", "department", "department-without-field", "empty-body")


def _records(repo: Path) -> RecordsStore:
    return RecordsStore(RecordsConfig(repo_path=str(repo), auto_commit=False))


def _archive(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


async def _write_corpus(repo: Path) -> dict[str, str]:
    """Every source the service promotes and each near miss it must not, as case id -> records path."""
    writer = _records(repo)
    paths: dict[str, str] = {}
    paths["convergence"] = await writer.write_entry(
        author="system", path="reports/convergence/convergence-20261022-000000.md",
        content="## Convergence Report\n\nThree officers independently traced the coolant drift.",
        message="AD-551: Convergence report (coolant)", classification="ship", tags=["convergence", "ad-551"],
    )
    paths["captains-log"] = await writer.append_captains_log("Set course for the Briar Patch; coolant drift logged.")
    paths["published-report"] = await writer.write_entry(
        author="LaForge", path="reports/engineering/warp-core-audit.md",
        content="Warp core audit: the coolant manifold is within tolerance.", message="audit",
        classification="ship", status="published", topic="warp-core-audit",
    )
    paths["finding-ship"] = await writer.write_notebook(
        callsign="Chapel", topic_slug="coolant-exposure-c0ffee00",
        content="Claim: coolant exposure explains the fatigue reports.", department="medical",
        classification="ship", extra_frontmatter=dict(_CLAIM),
    )
    paths["finding-fleet"] = await writer.write_notebook(
        callsign="Spock", topic_slug="sensor-ghosts-c0ffee01",
        content="Claim: sensor ghosts track coolant venting.", department="science",
        classification="fleet", extra_frontmatter=dict(_CLAIM),
    )
    # Near misses: each fails its source's criterion.
    paths["draft-report"] = await writer.write_entry(
        author="LaForge", path="reports/engineering/draft.md", content="Unreviewed coolant notes.",
        message="draft", classification="ship",
    )
    paths["gap-report"] = await writer.write_entry(
        author="system", path="reports/gap-reports/gap-1.md", content="Gap: no coolant sensor.",
        message="gap", classification="ship",
    )
    paths["convergence-by-agent"] = await writer.write_entry(
        author="Worf", path="reports/convergence/convergence-forged.md", content="Forged coolant convergence.",
        message="forged", classification="ship",
    )
    paths["captains-log-by-agent"] = await writer.write_entry(
        author="Worf", path="captains-log/2026-01-01.md", content="Not the Captain's coolant entry.",
        message="forged", classification="ship", status="published",
    )
    paths["manual"] = await writer.write_entry(
        author="shipyard", path="manuals/coolant.md", content="Coolant manual.", message="manual",
        classification="ship", status="published",
    )
    paths["creative"] = await writer.write_entry(
        author="Chapel", path="creative/Chapel/coolant-ode.md", content="An ode to coolant.", message="poem",
        classification="ship", status="published",
    )
    paths["duty-log"] = await writer.write_entry(
        author="Worf", path="duty-logs/watch-1.md", content="Coolant watch quiet.", message="log",
        classification="ship", status="published",
    )
    paths["plain-ship-notebook"] = await writer.write_notebook(
        callsign="Worf", topic_slug="coolant-musings", content="Musings on coolant.", classification="ship",
    )
    # Selected by their criterion, then withheld: narrower than ship (C1), or nothing to archive.
    paths["private"] = await writer.write_notebook(
        callsign="Chapel", topic_slug="private-coolant-c0ffee02", content="Claim: a private coolant note.",
        classification="private", extra_frontmatter=dict(_CLAIM),
    )
    paths["department"] = await writer.write_notebook(
        callsign="Ogawa", topic_slug="dept-coolant-c0ffee03", content="Claim: a department coolant note.",
        department="medical", classification="department", extra_frontmatter=dict(_CLAIM),
    )
    paths["department-without-field"] = await writer.write_notebook(
        callsign="Ogawa", topic_slug="dept-bare-c0ffee04", content="Claim: a department note with no department.",
        classification="department", extra_frontmatter=dict(_CLAIM),
    )
    paths["empty-body"] = await writer.write_notebook(
        callsign="Chapel", topic_slug="empty-c0ffee05", content="   ", classification="ship",
        extra_frontmatter=dict(_CLAIM),
    )
    return paths


async def _promote(tmp_path: Path, repo: Path, timeline_id: str = "timeline-one") -> PromotionReport:
    archive = _archive(tmp_path)
    await archive.initialize()
    try:
        return await promote_ship_records(_records(repo), archive, timeline_id=timeline_id)
    finally:
        await archive.close()


def _execute(path: Path, sql: str) -> None:
    """One committed statement on the archive file through a second connection: how a test injects a failure."""
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


async def _write_blank_topics(repo: Path, topic: str) -> tuple[str, str]:
    """A3 (F1): two sources the producers accept with a blank topic: one named by its file, one whose file name is
    blank too (``write_notebook`` makes the slug both the topic and the file name)."""
    writer = _records(repo)
    named = await writer.write_entry(
        author="LaForge", path="reports/engineering/coolant-trend.md", content="Coolant trend: steady.",
        message="trend", classification="ship", status="published", topic=topic,
    )
    nameless = await writer.write_notebook(
        callsign="Chapel", topic_slug=" ", content="Claim: the coolant trend is steady.", classification="ship",
        extra_frontmatter=dict(_CLAIM),
    )
    return named, nameless


# --- P1: premise 2 --------------------------------------------------------------------------------------------


async def test_ship_records_read_offline_without_initialize(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    reader = _records(repo)  # never initialised: probos reset reads the records of a stopped vessel
    assert set(paths.values()) <= {entry["path"] for entry in await reader.list_entries()}
    document = await reader.read_entry(paths["convergence"], ARCHIVE_READER)
    assert document is not None and "coolant drift" in document["content"]
    assert await reader.read_entry(paths["private"], ARCHIVE_READER) is None
    assert not (repo / ".git").exists()


# --- P2 to P5: the criteria and the gate ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "kind"),
    [
        ("convergence", SourceKind.CONVERGENCE_REPORT),
        ("captains-log", SourceKind.CAPTAINS_LOG),
        ("published-report", SourceKind.PUBLISHED_REPORT),
        ("finding-ship", SourceKind.NOTEBOOK_FINDING),
        ("finding-fleet", SourceKind.NOTEBOOK_FINDING),
    ],
    ids=["convergence", "captains-log", "published-report", "finding-ship", "finding-fleet"],
)
async def test_each_source_is_promoted_with_its_provenance(tmp_path: Path, case: str, kind: SourceKind) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    report = await _promote(tmp_path, repo)
    assert paths[case] in report.created
    document = await _records(repo).read_entry(paths[case], "captain")
    frontmatter = document["frontmatter"]
    rows = _rows(
        tmp_path / "archive.db",
        "SELECT timeline_id, source_kind, category, classification, author_callsign, content, content_sha256, "
        "source_episode_ids, author_did FROM archive WHERE source_ref = ?",
        (paths[case],),
    )
    assert rows == [(
        "timeline-one", kind.value, kind.value, frontmatter["classification"], frontmatter["author"],
        document["content"], hashlib.sha256(document["content"].encode("utf-8")).hexdigest(), "[]", "",
    )]


@pytest.mark.parametrize("case", _NOT_SELECTED)
async def test_what_fails_its_criterion_is_not_promoted(tmp_path: Path, case: str) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    report = await _promote(tmp_path, repo)
    assert paths[case] not in report.created + report.present + report.erased + report.withheld
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive WHERE source_ref = ?", (paths[case],)) == []


@pytest.mark.parametrize("case", _WITHHELD)
async def test_what_is_narrower_than_ship_or_empty_is_withheld_and_the_run_goes_on(tmp_path: Path, case: str) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    report = await _promote(tmp_path, repo)
    assert paths[case] in report.withheld
    assert sorted(report.created) == sorted(paths[name] for name in _PROMOTED)
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive WHERE source_ref = ?", (paths[case],)) == []


@pytest.mark.parametrize("timeline", ["timeline-one", "timeline-two"], ids=["same-timeline", "next-timeline"])
async def test_a_second_run_archives_nothing_new(tmp_path: Path, timeline: str) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    first = await _promote(tmp_path, repo)
    second = await _promote(tmp_path, repo, timeline_id=timeline)
    assert sorted(first.created) == sorted(paths[name] for name in _PROMOTED)
    assert second.created == ()
    assert sorted(second.present) == sorted(first.created)
    assert len(_rows(tmp_path / "archive.db", "SELECT id FROM archive")) == len(_PROMOTED)
    assert {row[0] for row in _rows(tmp_path / "archive.db", "SELECT timeline_id FROM archive")} == {"timeline-one"}


# --- P6 to P10: edges -----------------------------------------------------------------------------------------


async def test_an_absent_records_directory_promotes_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "no-records"
    report = await _promote(tmp_path, missing, timeline_id="")
    assert report == PromotionReport(created=(), present=(), erased=(), withheld=())
    assert not missing.exists()


async def test_a_source_the_captain_erased_is_reported_and_not_archived_again(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    await _promote(tmp_path, repo)
    [(entry_id,)] = _rows(
        tmp_path / "archive.db", "SELECT id FROM archive WHERE source_ref = ?", (paths["convergence"],),
    )
    archive = _archive(tmp_path)
    await archive.initialize()
    try:
        assert await archive.erase_entry(entry_id, "Captain's order") is True
        report = await promote_ship_records(_records(repo), archive, timeline_id="timeline-two")
    finally:
        await archive.close()
    assert report.erased == (paths["convergence"],)
    assert report.created == ()
    assert _rows(tmp_path / "archive.db", "SELECT id FROM archive WHERE source_ref = ?", (paths["convergence"],)) == []


async def test_a_failed_write_propagates(tmp_path: Path) -> None:
    """A database failure mid-run reaches the caller; what was promoted before it stays, and a re-run reports that
    present and creates the rest. A3: a real failure in the store; this test once reached only the
    uninitialised-store guard, which a handler of ``sqlite3.DatabaseError`` alone would have passed."""
    repo = tmp_path / "ship-records"
    await _write_corpus(repo)
    plan = await plan_promotion(_records(repo), timeline_id="timeline-one")
    order = [record.source_ref for record in plan.records]
    assert len(order) == len(_PROMOTED)  # premise: the failure comes after four successful writes
    path = tmp_path / "archive.db"
    archive = _archive(tmp_path)
    await archive.initialize()
    try:
        _execute(
            path,
            "CREATE TRIGGER refuse_last BEFORE INSERT ON archive "
            f"WHEN new.source_ref = '{order[-1]}' BEGIN SELECT RAISE (ABORT, 'AD-1341 A3: injected failure'); END",
        )
        with pytest.raises(sqlite3.DatabaseError, match="injected failure"):
            await promote_ship_records(_records(repo), archive, timeline_id="timeline-one")
    finally:
        await archive.close()
    assert sorted(row[0] for row in _rows(path, "SELECT source_ref FROM archive")) == sorted(order[:-1])
    _execute(path, "DROP TRIGGER refuse_last")
    rerun = await _promote(tmp_path, repo, timeline_id="timeline-two")
    assert sorted(rerun.present) == sorted(order[:-1])
    assert rerun.created == (order[-1],)


async def test_records_to_promote_need_a_timeline(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    await _write_corpus(repo)
    with pytest.raises(ValueError, match="timeline_id"):
        await plan_promotion(_records(repo), timeline_id="")


async def test_planning_reads_ship_records_and_writes_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    before = {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}
    plan = await plan_promotion(_records(repo), timeline_id="timeline-one")
    assert sorted(record.source_ref for record in plan.records) == sorted(paths[name] for name in _PROMOTED)
    assert sorted(plan.withheld) == sorted(paths[name] for name in _WITHHELD)
    assert {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()} == before
    assert not (tmp_path / "archive.db").exists()


@pytest.mark.parametrize("frontmatter", ["a scalar", ["a", "list"], None], ids=["scalar", "list", "none"])
def test_a_document_without_mapping_frontmatter_is_never_a_source(frontmatter: Any) -> None:
    assert source_kind_for("reports/convergence/convergence-x.md", {"author": "system"}) is (
        SourceKind.CONVERGENCE_REPORT
    )  # premise: the same path with mapping frontmatter is a source
    assert source_kind_for("reports/convergence/convergence-x.md", frontmatter) is None


# --- P16: a blank topic (A3, F1) ------------------------------------------------------------------------------


@pytest.mark.parametrize("topic", ["   ", "\t\n"], ids=["spaces", "tab-newline"])
async def test_a_blank_topic_takes_the_file_name_and_the_run_goes_on(tmp_path: Path, topic: str) -> None:
    """A3 (F1): the producers accept a blank topic and the record refuses a blank title. The title falls back to the
    file name, then the records path; nothing is withheld for it, and every other source is still promoted."""
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    named, nameless = await _write_blank_topics(repo, topic)
    reader = _records(repo)
    for path in (named, nameless):
        document = await reader.read_entry(path, "captain")
        assert document is not None and not document["frontmatter"]["topic"].strip()  # premise: the topic is blank
    report = await _promote(tmp_path, repo)
    assert sorted(report.created) == sorted([named, nameless, *(paths[name] for name in _PROMOTED)])
    assert sorted(report.withheld) == sorted(paths[name] for name in _WITHHELD)
    titles = _rows(
        tmp_path / "archive.db", "SELECT source_ref, title FROM archive WHERE source_ref IN (?, ?)", (named, nameless),
    )
    assert sorted(titles) == sorted([(named, "coolant-trend"), (nameless, nameless)])


async def test_a_dry_run_plan_titles_a_blank_topic(tmp_path: Path) -> None:
    """A3 (F1): ``probos reset --dry-run`` lists this plan, so planning must not raise on a blank topic either."""
    repo = tmp_path / "ship-records"
    paths = await _write_corpus(repo)
    named, nameless = await _write_blank_topics(repo, "   ")
    plan = await plan_promotion(_records(repo), timeline_id="timeline-one")
    titles = {record.source_ref: record.title for record in plan.records}
    assert sorted(titles) == sorted([named, nameless, *(paths[name] for name in _PROMOTED)])
    assert (titles[named], titles[nameless]) == ("coolant-trend", nameless)
    assert sorted(plan.withheld) == sorted(paths[name] for name in _WITHHELD)


# --- P11: the chain -------------------------------------------------------------------------------------------


async def test_a_promoted_record_reaches_a_later_crews_oracle(tmp_path: Path) -> None:
    repo = tmp_path / "ship-records"
    await _write_corpus(repo)
    await _promote(tmp_path, repo)
    later = _archive(tmp_path)  # the next generation's boot opens the same file
    await later.initialize()
    try:
        results = await OracleService(archive_store=later).query("coolant drift", tiers=["archive"])
    finally:
        await later.close()
    assert results, "premise: the query reaches the archive tier"
    assert {result.metadata["timeline_id"] for result in results} == {"timeline-one"}
    assert any("convergence-20261022-000000" in result.content for result in results)


# --- P12 to P15: the resolver, the layer and the census -------------------------------------------------------


@pytest.mark.parametrize("override", [False, True], ids=["default", "override"])
def test_the_records_path_has_one_resolver(tmp_path: Path, override: bool) -> None:
    data_dir = tmp_path / "data"
    configured = str(tmp_path / "elsewhere" / "records") if override else ""
    resolved = resolve_records_repo_path(RecordsConfig(repo_path=configured), data_dir)
    assert resolved == (Path(configured) if override else data_dir / "ship-records")


def test_startup_reads_the_records_path_through_the_shared_resolver() -> None:
    """D10: one resolver, so ``probos reset`` reads the records this vessel writes.

    A structural pin on purpose: the startup branch runs inside the boot sequence, which no focused test
    reaches, and the property is that the default is not computed a second time.
    """
    source = (_SRC / "startup" / "cognitive_services.py").read_text(encoding="utf-8")
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "resolve_records_repo_path"
    ]
    assert len(calls) == 1
    assert '"ship-records"' not in source


def test_the_service_imports_only_the_knowledge_layer() -> None:
    tree = ast.parse((_SRC / "knowledge" / "archive_promotion.py").read_text(encoding="utf-8"))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    # AD-1341 S4 (#1569): the exit note's rule reads the lessons format (``probos.knowledge.lessons``), a module of the
    # same knowledge layer, so the service still imports only that layer.
    assert {name for name in modules if name.split(".")[0] == "probos"} == {
        "probos.knowledge.archive_store",
        "probos.knowledge.lessons",
        "probos.knowledge.records_store",
    }


def test_only_the_promotion_service_writes_the_archive() -> None:
    """Agents never write the archive: ``promote_entry`` is named in ``src`` (called, referenced or spelled as a
    string) by the promotion service alone, beside its definition."""
    naming: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == "promote_entry") or (
                isinstance(node, ast.Constant) and node.value == "promote_entry"
            ):
                naming.add(path.relative_to(_SRC).as_posix())
    assert naming == {"knowledge/archive_promotion.py"}
