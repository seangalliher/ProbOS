"""AD-1341 S6 (#1569), M2: every tier 2 and 3 reset archives a description of the procedures the crew developed,
never the procedures.

Real objects: the real ``_cmd_reset`` and ``_cmd_archive`` on a temporary data directory; a ``procedures.db`` built
with the procedure store's own schema (``procedure_store._SCHEMA``); the real ``ArchiveStore``, ``OracleService`` and
Oracle tool. The config loader is the one stand-in. No test reaches a real data directory (the autouse fixture).
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sqlite3
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from probos import __main__ as cli
from probos.knowledge import records_snapshot
from probos.knowledge.archive_promotion import (
    NATURE_DESCRIPTION_PREFIX,
    promote_nature_description,
    review_nature_description,
)
from probos.cognitive.oracle_service import OracleService
from probos.cognitive.procedure_store import _SCHEMA as _PROCEDURE_SCHEMA
from probos.config import ArchiveConfig, KnowledgeConfig, SystemConfig
from probos.knowledge.archive_store import ArchiveStore, PromotionOutcome, SourceKind, SourceState
from probos.knowledge.nature_description import (
    NATURE_DESCRIPTION_MAX_CHARS,
    PROCEDURES_DB,
    _one_line,
    describe_nature,
    nature_description_record,
)
from probos.storage.sqlite_factory import default_factory
from probos.tools.oracle_query_tool import _MAX_ENTRY_CHARS, OracleQueryTool

_SHIP = "ship-did-alpha-0001"
_NEXT_SHIP = "ship-did-beta-0002"
_BOOT = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
_B = _BOOT.timestamp()
_INHERITED = {
    "id": "p-0", "name": "Inherited routine", "description": "From an earlier crew.", "created_at": _B - 86400.0,
    "total_selections": 50, "total_completions": 50,
}
_ROWS = (
    _INHERITED,
    {"id": "p-1", "name": "Coolant drift triage", "description": "Trace a coolant drift to its sensor before purging.",
     "created_at": _B + 60.0, "total_selections": 9, "total_completions": 8, "total_fallbacks": 1,
     "content_snapshot": '{"steps": ["STEP-BODY-SECRET"]}'},
    {"id": "p-2", "name": "Coolant drift triage, sensor first", "description": "Check the sensor, then trace the drift.",
     "evolution_type": "FIX", "change_summary": "The sensor check now comes first.", "created_at": _B + 120.0,
     "total_selections": 3, "total_completions": 3},
    {"id": "p-3", "name": "Purge before isolating", "description": "Purging before isolating vents the core.",
     "is_negative": 1, "created_at": _B + 30.0, "total_selections": 2, "total_fallbacks": 2},
)
_EXPECTED = "\n".join((
    "Procedures this crew developed since 2026-10-01 (UTC, the ship's first boot): 3; 3 active in the store at the "
    "close.",
    "They stay in the procedure store as nature. This records what they are and why, never their steps.",
    "- Coolant drift triage: Trace a coolant drift to its sensor before purging. (captured, active; 8 of 9 uses "
    "completed, 1 fell back)",
    "- Coolant drift triage, sensor first: Check the sensor, then trace the drift. (fix, active; 3 of 3 uses "
    "completed, 0 fell back); changed because: The sensor check now comes first.",
    "- Purge before isolating: Purging before isolating vents the core. (captured, an anti-pattern; 0 of 2 uses "
    "completed, 2 fell back)",
))
_WORST_LABEL = "[Inherited from the crew of generation 999999: not your own memory]"
_WORST_MARKER = "[source:archive relevance:1.00 age:59s]"


@pytest.fixture(autouse=True)
def _no_real_data_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every platform data and home path points under ``tmp_path``, and the CLI's default data directory raises."""
    home = tmp_path / "platform"
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(home / name.lower()))

    def _refuse() -> Path:
        raise AssertionError("AD-1341 S6: a test reached the platform data directory")

    monkeypatch.setattr(cli, "_default_data_dir", _refuse)


def _archive_db(tmp_path: Path) -> Path:
    return tmp_path / "archive" / "archive.db"


def _config(tmp_path: Path) -> SystemConfig:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    (tmp_path / "archive").mkdir(exist_ok=True)
    section = ArchiveConfig(enabled=True, db_path=str(_archive_db(tmp_path)))
    return SystemConfig(knowledge=KnowledgeConfig(repo_path=str(knowledge)), archive=section)


def _data_dir(tmp_path: Path, *, instance_id: str = _SHIP) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "ontology").mkdir(parents=True)
    if instance_id:
        id_file = data_dir / "ontology" / "instance_id"
        id_file.write_text(f"{instance_id}\n", encoding="utf-8")
        os.utime(id_file, (_B, _B))  # the ship's first boot
    for name in ("events.db", "trust.db", "ward_room.db"):
        (data_dir / name).write_text(name, encoding="utf-8")
    return data_dir


def _procedure_store(data_dir: Path, rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> Path:
    """``procedures/procedures.db`` with the store's own schema and ``rows``."""
    path = data_dir / PROCEDURES_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(_PROCEDURE_SCHEMA)
        for row in rows:
            columns, marks = ", ".join(row), ", ".join("?" for _ in row)
            connection.execute(f"INSERT INTO procedure_records ({columns}) VALUES ({marks})", tuple(row.values()))
        connection.commit()
    finally:
        connection.close()
    return path


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _reset(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, data_dir: Path, **flags: Any) -> Any:
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    values: dict[str, Any] = {
        "yes": True, "soft": False, "full": False, "dry_run": False, "wipe_records": False, "config": None,
        "data_dir": data_dir, "skip_promotion": None,
    }
    values.update(flags)
    return cli._cmd_reset(Namespace(**values))


def _archive(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, command: str, **values: Any) -> Any:
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    return cli._cmd_archive(Namespace(archive_cmd=command, config=None, **values))


async def _read_only(path: str) -> Any:
    return await default_factory.connect(path, read_only=True)


async def _later_crew_reads(tmp_path: Path, text: str) -> list[Any]:
    later = ArchiveStore(str(_archive_db(tmp_path)), connection_factory=default_factory)
    await later.initialize()
    try:
        oracle = OracleService(archive_store=later)
        oracle.attach_current_timeline(_NEXT_SHIP)
        return await oracle.query(text, tiers=["archive"])
    finally:
        await later.close()


def test_a_reset_archives_one_description_of_what_this_crew_developed_never_the_procedures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    store = _procedure_store(data_dir, _ROWS)
    created = _rows(store, "SELECT id FROM procedure_records WHERE created_at >= ? ORDER BY created_at, id", (_B,))
    assert created == [("p-3",), ("p-1",), ("p-2",)]  # premise: not the completions order _EXPECTED lists
    before = store.read_bytes()

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0

    archive = _archive_db(tmp_path)
    assert _rows(
        archive,
        "SELECT timeline_id, source_kind, source_ref, title, classification, author_did, author_callsign, "
        "source_episode_ids FROM archive",
    ) == [(
        _SHIP, "nature_description", f"{NATURE_DESCRIPTION_PREFIX}{_SHIP}",
        f"Procedures developed by the crew of timeline {_SHIP}", "ship", "", "", "[]",
    )]
    ((content,),) = _rows(archive, "SELECT content FROM archive")
    assert content == _EXPECTED  # developed since the first boot only, listed by completions; never a step
    assert "STEP-BODY-SECRET" not in content and "Inherited routine" not in content
    assert store.read_bytes() == before  # read, never written; nature persists at tier 2
    assert f"Nature description {NATURE_DESCRIPTION_PREFIX}{_SHIP}: created." in capsys.readouterr().out
    assert _rows(archive, "SELECT timeline_id, reset_tier, outcome, created_count FROM generations") == [
        (_SHIP, 2, "promoted", 0),
    ]  # the generation's counts stay Ship's Records' own
    results = asyncio.run(_later_crew_reads(tmp_path, "sensor"))
    assert [result.content.splitlines()[0] for result in results] == [
        "[Inherited from the crew of generation 1: not your own memory]",
    ]


@pytest.mark.parametrize("shape", ["long-text", "short-text"])
async def test_a_description_at_its_bound_reaches_a_later_crew_whole_through_the_oracle_tool(
    shape: str, tmp_path: Path,
) -> None:
    timeline = "t" * 64
    long_text = shape == "long-text"
    rows = [
        {"id": f"p-{index:02d}", "created_at": _B + index, "evolution_type": "FIX" if long_text else "CAPTURED",
         "name": "N" * 100 if long_text else f"P{index:02d}",
         "description": f"NATUREBOUND {'D' * 300}" if long_text else "NATUREBOUND",
         "change_summary": "S" * 300 if long_text else ""}
        for index in range(40)
    ]
    store = _procedure_store(_data_dir(tmp_path, instance_id=timeline), rows)

    record = await nature_description_record(store, _read_only, timeline_id=timeline, started=_BOOT)

    assert record is not None and len(record.content) <= NATURE_DESCRIPTION_MAX_CHARS
    listed = record.metadata["procedures_listed"]
    assert 1 <= listed < 40 and record.content.count("\n- ") == listed
    assert record.content.endswith(f"And {40 - listed} more in the procedure store.")
    archive = ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)
    await archive.initialize()
    try:
        assert await promote_nature_description(archive, record) is PromotionOutcome.CREATED
        oracle = OracleService(archive_store=archive)
        oracle.attach_current_timeline(_NEXT_SHIP)
        result = await OracleQueryTool(oracle=oracle).invoke({"query": "NATUREBOUND", "kind": "archive"})
    finally:
        await archive.close()
    assert not result.error and result.metadata["returned_count"] == 1  # premise: the real tool delivered it
    entry = result.output[result.output.index("[source:archive"):].rstrip("\n")
    marker, label = entry.splitlines()[:2]
    assert label.startswith("[Inherited from ") and "[entry shortened]" not in entry
    for line in record.content.splitlines():
        assert line in entry  # whole: the count of the rest too
    assert len(entry) - len(marker) - len(label) + len(_WORST_MARKER) + len(_WORST_LABEL) <= _MAX_ENTRY_CHARS


@pytest.mark.parametrize("case", ["no-store", "nothing-since-boot", "no-instance-id"])
def test_nothing_to_describe_archives_nothing_and_creates_no_store(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path, instance_id="" if case == "no-instance-id" else _SHIP)
    if case == "nothing-since-boot":
        _procedure_store(data_dir, [_INHERITED])
    elif case == "no-instance-id":
        _procedure_store(data_dir, _ROWS)

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0

    archive = _archive_db(tmp_path)
    if archive.exists():
        assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE source_kind = 'nature_description'") == [(0,)]
    if case == "no-store":
        assert not (data_dir / "procedures").exists()  # a read-only open never creates the store


@pytest.mark.parametrize(
    ("raw", "limit", "expected"),
    [
        ("a\nb\tc", 20, "a b c"),
        ("\x1b[31mred\x1b[0m", 20, "[31mred [0m"),
        ("bidi‮evil", 20, "bidi evil"),
        ("zero​width", 20, "zero width"),
        ("  spaced   out  ", 20, "spaced out"),
        ("x" * 30, 10, "xxxxxxx..."),
        (None, 20, ""),
    ],
    ids=["whitespace", "escape", "bidi-override", "zero-width", "spaces", "cut", "not-text"],
)
def test_text_from_the_store_is_one_line_without_control_or_format_characters(
    raw: Any, limit: int, expected: str,
) -> None:
    assert _one_line(raw, limit) == expected


def test_the_captain_reviews_and_vetoes_a_description_before_the_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    store = _procedure_store(data_dir, _ROWS)
    config = _config(tmp_path)
    ref = f"{NATURE_DESCRIPTION_PREFIX}{_SHIP}"

    assert _archive(monkeypatch, config, "pending", data_dir=data_dir) == 0
    out = capsys.readouterr().out
    assert f"  + would be promoted: {ref}" in out
    assert f"    Procedures developed by the crew of timeline {_SHIP}" in out
    for line in _EXPECTED.splitlines():  # A2 (B-F1): the Captain reviews the text itself, whole
        assert f"    {line}" in out

    connection = sqlite3.connect(str(store))  # the store changes after the review: the reset's text differs
    connection.execute(
        "INSERT INTO procedure_records (id, name, created_at) VALUES (?, ?, ?)", ("p-9", "Late arrival", _B + 999.0),
    )
    connection.commit()
    connection.close()
    assert _archive(
        monkeypatch, config, "veto", data_dir=data_dir, source_ref=ref, reason="not this one", yes=True,
    ) == 0
    assert "Late arrival" in capsys.readouterr().out  # A2 (B-F1): the veto shows the text it keeps out

    assert _reset(monkeypatch, config, data_dir) == 0

    assert f"Nature description {ref}: vetoed." in capsys.readouterr().out
    archive = _archive_db(tmp_path)
    assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE source_kind = 'nature_description'") == [(0,)]
    assert _rows(archive, "SELECT source_kind, source_ref, reason FROM archive_vetoes") == [
        ("nature_description", ref, "not this one"),
    ]


def test_a_procedure_store_that_cannot_be_read_refuses_the_reset_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    (data_dir / PROCEDURES_DB).parent.mkdir(parents=True)
    (data_dir / PROCEDURES_DB).write_bytes(b"not a database " * 100)

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 1

    assert "DatabaseError" in capsys.readouterr().out
    assert all((data_dir / name).is_file() for name in ("events.db", "trust.db", "ward_room.db"))
    assert (data_dir / "ontology" / "instance_id").is_file()


async def test_only_a_nature_description_without_episodes_is_promoted_as_one(tmp_path: Path) -> None:
    good = describe_nature(_SHIP, _BOOT, (), developed=1, active=0)
    archive = ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)
    await archive.initialize()
    try:
        for bad in (
            dataclasses.replace(good, source_kind=SourceKind.CONVERGENCE_REPORT),
            dataclasses.replace(good, source_episode_ids=("ep-1",)),
            dataclasses.replace(good, source_ref="reports/elsewhere.md"),
        ):
            with pytest.raises(ValueError):
                await promote_nature_description(archive, bad)
        assert await archive.count() == 0
        assert await promote_nature_description(archive, good) is PromotionOutcome.CREATED
        assert await promote_nature_description(archive, good) is PromotionOutcome.PRESENT  # once per content
    finally:
        await archive.close()
    with pytest.raises(ValueError):
        describe_nature("t" * 65, _BOOT, (), developed=1, active=0)


def test_the_dry_run_shows_the_description_the_reset_would_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _procedure_store(data_dir, _ROWS)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, dry_run=True) == 0

    out = capsys.readouterr().out
    assert f"    + {NATURE_DESCRIPTION_PREFIX}{_SHIP} (the nature description):" in out
    for line in _EXPECTED.splitlines():
        assert f"      {line}" in out
    assert not _archive_db(tmp_path).exists()  # a dry run opens no archive


def test_a_retried_reset_keeps_one_description_per_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (B-F2): a reset refused after its description was archived, retried after the store changed, archives no
    second description of the same generation; the review says it is archived already."""
    data_dir = _data_dir(tmp_path)
    store = _procedure_store(data_dir, _ROWS)
    config = _config(tmp_path)
    ref = f"{NATURE_DESCRIPTION_PREFIX}{_SHIP}"
    real_close = ArchiveStore.record_generation
    attempts: list[Any] = []

    async def _locked_once(self: ArchiveStore, closure: Any) -> Any:
        attempts.append(closure)
        if len(attempts) == 1:
            raise sqlite3.OperationalError("database is locked")
        return await real_close(self, closure)

    monkeypatch.setattr(ArchiveStore, "record_generation", _locked_once)

    assert _reset(monkeypatch, config, data_dir) == 1  # refused after the description was archived
    archive = _archive_db(tmp_path)
    descriptions = "SELECT content FROM archive WHERE source_kind = 'nature_description'"
    assert _rows(archive, descriptions) == [(_EXPECTED,)]
    assert (data_dir / "ontology" / "instance_id").is_file()

    connection = sqlite3.connect(str(store))  # the vessel ran again before the retry: the store changed
    connection.execute(
        "INSERT INTO procedure_records (id, name, created_at) VALUES (?, ?, ?)", ("p-9", "Late arrival", _B + 999.0),
    )
    connection.commit()
    connection.close()
    capsys.readouterr()
    assert _archive(monkeypatch, config, "pending", data_dir=data_dir) == 0
    assert f"  = already archived (entry 1): {ref}" in capsys.readouterr().out

    assert _reset(monkeypatch, config, data_dir) == 0

    assert f"Nature description {ref}: present." in capsys.readouterr().out
    assert _rows(archive, descriptions) == [(_EXPECTED,)]  # one per generation: the first is kept
    assert _rows(archive, "SELECT COUNT(*) FROM generations") == [(1,)]


async def test_one_description_per_generation_whatever_its_content(tmp_path: Path) -> None:
    """A2 (B-F2): once a generation's description is archived, a later one for the same reference is ``present``,
    never a revision, in the writer and in the review alike."""
    first = describe_nature(_SHIP, _BOOT, (), developed=1, active=0)
    later = describe_nature(_SHIP, _BOOT, (), developed=2, active=1)
    assert first.source_ref == later.source_ref and first.content != later.content  # premise
    archive = ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)
    await archive.initialize()
    try:
        assert await promote_nature_description(archive, first) is PromotionOutcome.CREATED
        assert await promote_nature_description(archive, later) is PromotionOutcome.PRESENT
        assert await archive.count() == 1
        review = await review_nature_description(archive, later)
        assert review.state == SourceState(PromotionOutcome.PRESENT, (1,))
    finally:
        await archive.close()


def test_a_full_reset_whose_snapshot_fails_archives_no_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (B-F2): the description is archived after the snapshot, so a snapshot that fails leaves none behind."""
    data_dir = _data_dir(tmp_path)
    _procedure_store(data_dir, _ROWS)
    notebooks = data_dir / "ship-records" / "notebooks"
    notebooks.mkdir(parents=True)
    (notebooks / "a.md").write_bytes(b"a note")

    def _sharing_violation(*args: Any, **kwargs: Any) -> str:
        raise PermissionError(13, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(records_snapshot, "_copy_member", _sharing_violation)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 1

    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM archive WHERE source_kind = 'nature_description'") == [
        (0,),
    ]
    assert (notebooks / "a.md").read_bytes() == b"a note"


def test_a_wal_mode_store_is_described_and_its_database_bytes_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (B-F4): the vessel's store is in WAL mode (``procedure_store.py:211``). Read through ``mode=ro``, its
    database bytes are unchanged; SQLite may create the ``-wal`` and ``-shm`` files beside it, as any reader may."""
    data_dir = _data_dir(tmp_path)
    store = _procedure_store(data_dir, _ROWS)
    connection = sqlite3.connect(str(store))
    connection.execute("PRAGMA journal_mode=WAL")
    connection.close()
    assert _rows(store, "PRAGMA journal_mode") == [("wal",)]  # premise
    before = store.read_bytes()

    assert _reset(monkeypatch, _config(tmp_path), data_dir, dry_run=True) == 0

    out = capsys.readouterr().out
    for line in _EXPECTED.splitlines():
        assert f"      {line}" in out
    assert store.read_bytes() == before
