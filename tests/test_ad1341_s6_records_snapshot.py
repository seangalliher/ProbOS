"""AD-1341 S6 (#1569), M1: a ``--full`` reset keeps what it deletes from Ship's Records as one checked snapshot.

Real objects throughout: the real ``_cmd_reset``, ``_cmd_archive`` and ``main`` on a temporary data directory, Ship's
Records written by the store's own producers, the real ``ArchiveStore`` and ``ArchiveLedger`` on a temporary archive
file, and the real ``OracleService``. The config loader is the one stand-in. No test reaches a real data directory:
the platform's data and home variables point under ``tmp_path`` and the CLI's default data directory raises (the
autouse fixture). A fault is injected only where the platform cannot produce one on demand: a sharing violation, a
file that changes between the listing and the copy, a member that reads back wrong, a ledger that refuses its row.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import hashlib
import os
import re
import shutil
import sqlite3
import stat
import struct
import sys
import types
import zipfile
import zlib
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import probos
from probos import __main__ as cli
from probos.knowledge import records_snapshot
from probos.cognitive.oracle_service import OracleService
from probos.config import ArchiveConfig, KnowledgeConfig, RecordsConfig, SystemConfig
from probos.knowledge.archive_ledger import ArchiveLedger, SnapshotRecord
from probos.knowledge.archive_store import ArchiveStore
from probos.knowledge.records_snapshot import (
    SNAPSHOT_DIR_NAME,
    SnapshotPlan,
    SnapshotRefused,
    is_snapshot_relative_path,
    plan_snapshot,
    prepare_snapshot,
    snapshot_relative_path,
)
from probos.knowledge.records_store import RecordsStore
from probos.storage.sqlite_factory import default_factory

_SRC = Path(probos.__file__).resolve().parent
_SHIP = "ship-did-alpha-0001"
_CONVERGENCE = "reports/convergence/convergence-20261022-000000.md"
_STARTED = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
_ENDED = datetime(2026, 10, 27, 6, 0, 5, tzinfo=UTC)
_NAME = f"{_SHIP}/20261001T080000Z_20261027T060005Z.zip"
_DID = f"did:probos:{_SHIP}"


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


def _snapshots_dir(tmp_path: Path) -> Path:
    return tmp_path / "archive" / SNAPSHOT_DIR_NAME


def _config(tmp_path: Path, *, archive_enabled: bool = True) -> SystemConfig:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    (tmp_path / "archive").mkdir(exist_ok=True)
    section = ArchiveConfig(enabled=archive_enabled, db_path=str(_archive_db(tmp_path)))
    return SystemConfig(knowledge=KnowledgeConfig(repo_path=str(knowledge)), archive=section)


def _snapshot_files(tmp_path: Path) -> list[Path]:
    """Every file under the snapshots directory, a temporary ``.partial`` one included."""
    root = _snapshots_dir(tmp_path)
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []


def _data_dir(tmp_path: Path, *, instance_id: str = _SHIP) -> Path:
    """A stopped vessel's data directory: one file of each tier, and the instance id written at ``_STARTED``."""
    data_dir = tmp_path / "data"
    (data_dir / "ontology").mkdir(parents=True)
    if instance_id:
        id_file = data_dir / "ontology" / "instance_id"
        id_file.write_text(f"{instance_id}\n", encoding="utf-8")
        os.utime(id_file, (_STARTED.timestamp(), _STARTED.timestamp()))  # the ship's first boot
    for name in ("events.db", "trust.db", "ward_room.db"):  # tiers 1, 2 and 3
        (data_dir / name).write_text(name, encoding="utf-8")
    return data_dir


async def _write_records(data_dir: Path) -> None:
    """A convergence report and the Captain's log (both promoted) and a private notebook (never promoted)."""
    writer = RecordsStore(RecordsConfig(repo_path=str(data_dir / "ship-records"), auto_commit=False))
    await writer.write_entry(
        author="system", path=_CONVERGENCE, content="## Convergence Report\n\nThree officers traced the coolant drift.",
        message="AD-551: Convergence report (coolant)", classification="ship", tags=["convergence"],
    )
    await writer.append_captains_log("Set course for the Briar Patch.")
    await writer.write_notebook(
        callsign="Chapel", topic_slug="private-coolant", content="A private note: tachyon residue in the coolant.",
        classification="private",
    )


def _files(root: Path, contents: dict[str, bytes]) -> None:
    for relative, content in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _tree(root: Path, *, leave_out: tuple[str, ...] = ()) -> dict[str, bytes]:
    """Every regular file under ``root``: its POSIX path from ``root``, then its bytes; top-level ``leave_out`` skipped."""
    found: dict[str, bytes] = {}
    if not root.exists():
        return found
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative.split("/")[0] in leave_out or not path.is_file():
            continue
        found[relative] = path.read_bytes()
    return found


def _data_files(data_dir: Path) -> dict[str, bytes]:
    """The data directory's files, without the takeover lock every executing reset leaves (S1 A4)."""
    return {path: content for path, content in _tree(data_dir).items() if path != "probos.pid.lock"}


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _reset(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, data_dir: Path, **flags: Any) -> Any:
    """The real ``_cmd_reset`` with the loader returning ``config``; returns what it returns."""
    monkeypatch.setenv("COLUMNS", "200")  # Rich wraps at 80 columns off a terminal; the assertions read lines
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    values: dict[str, Any] = {
        "yes": True, "soft": False, "full": False, "dry_run": False, "wipe_records": False, "config": None,
        "data_dir": data_dir, "skip_promotion": None,
    }
    values.update(flags)
    return cli._cmd_reset(Namespace(**values))


def _archive(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, command: str, **values: Any) -> Any:
    """The real ``_cmd_archive`` with the loader returning ``config``."""
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    return cli._cmd_archive(Namespace(archive_cmd=command, config=None, **values))


def _erasures(tmp_path: Path) -> list[tuple[Any, ...]]:
    return _rows(_archive_db(tmp_path), "SELECT erased_at, erase_reason FROM archive_snapshots ORDER BY id")


def _link_dir(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), a symlink elsewhere. A host that refuses skips."""
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"this host cannot create a directory link: {exc}")


async def _later_crew_reads(tmp_path: Path, text: str) -> list[Any]:
    later = ArchiveStore(str(_archive_db(tmp_path)), connection_factory=default_factory)
    await later.initialize()
    try:
        oracle = OracleService(archive_store=later)
        oracle.attach_current_timeline("ship-did-beta-0002")
        return await oracle.query(text, tiers=["archive"])
    finally:
        await later.close()


def _prepare(root: Path, snapshots: Path, *, ended: datetime = _ENDED) -> Any:
    return prepare_snapshot(root, snapshots, timeline_id=_SHIP, ship_did=_DID, started=_STARTED, ended=ended)


# --- X1 to X5: the reset ------------------------------------------------------------------------------------------


def test_a_full_reset_keeps_ship_records_as_one_checked_bag_before_it_deletes_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    records = data_dir / "ship-records"
    _files(records, {
        "notebooks/garbled.md": b"---\nauthor: Chapel\n---\n\xff\xfe not UTF-8",  # S1 register RA3-1
        ".git/HEAD": b"ref: refs/heads/main\n",
        "procedures/p-1.yaml": b"steps: STEP-BODY-SECRET\n",
    })
    kept = _tree(records, leave_out=(".git", "procedures"))
    assert "notebooks/garbled.md" in kept and any("private-coolant" in path for path in kept)  # premise

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 0

    out = capsys.readouterr().out
    assert _tree(records) == {}  # tier 3 deleted Ship's Records ...
    (snapshot,) = _snapshot_files(tmp_path)  # ... and kept them first, as one file
    relative = snapshot.relative_to(_snapshots_dir(tmp_path)).as_posix()
    assert relative.startswith(f"{_SHIP}/20261001T080000Z_") and is_snapshot_relative_path(relative)
    total = sum(len(content) for content in kept.values())
    assert _rows(
        _archive_db(tmp_path),
        "SELECT id, timeline_id, ship_did, generation_started, relative_path, sha256, file_count, total_bytes, "
        "erased_at FROM archive_snapshots",
    ) == [(
        1, _SHIP, _DID, "2026-10-01T08:00:00Z", relative, _sha256(snapshot.read_bytes()), len(kept), total, None,
    )]
    bag = Path(relative).stem
    with zipfile.ZipFile(snapshot) as bag_zip:
        prefix = f"{bag}/data/"
        payload = {name[len(prefix):]: bag_zip.read(name) for name in bag_zip.namelist() if name.startswith(prefix)}
        bagit = bag_zip.read(f"{bag}/bagit.txt")
        manifest = bag_zip.read(f"{bag}/manifest-sha256.txt").decode("utf-8")
        info = bag_zip.read(f"{bag}/bag-info.txt").decode("utf-8")
    assert payload == kept  # byte for byte, every classification, the undecodable file too; no .git, no procedures
    assert bagit == b"BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n"
    assert manifest.splitlines() == [f"{_sha256(content)}  data/{path}" for path, content in sorted(kept.items())]
    for line in (f"External-Identifier: {_DID}", f"ProbOS-Timeline: {_SHIP}", f"Payload-Oxum: {total}.{len(kept)}",
                 "ProbOS-Generation-Started: 2026-10-01T08:00:00Z"):
        assert f"{line}\n" in info
    assert "1 Markdown file(s) Ship's Records cannot list, never promoted, are kept in it: notebooks/garbled.md" in out
    assert _rows(_archive_db(tmp_path), "SELECT reset_tier, outcome FROM generations") == [(3, "promoted")]
    assert asyncio.run(_later_crew_reads(tmp_path, "tachyon")) == []  # a snapshot is no archive entry


def test_a_tier2_reset_keeps_ship_records_and_takes_no_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    before = _tree(data_dir / "ship-records")

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0

    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM archive_snapshots") == [(0,)]
    assert _snapshot_files(tmp_path) == []
    assert _tree(data_dir / "ship-records") == before


_FAULTS = (
    "link", "too-many-files", "too-many-bytes", "grew", "shrank", "unreadable", "reads-back-wrong",
    "member-missing", "member-extra", "not-recorded",
)
#: A2: the faults the reset's preflight knows before anything is written: the archive is never even opened.
_PREFLIGHT_FAULTS = ("link", "too-many-files", "too-many-bytes")


def _inject(fault: str, records: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make one way a snapshot cannot be made happen."""
    real_plan, real_copy, real_text = (
        records_snapshot.plan_snapshot, records_snapshot._copy_member, records_snapshot._write_text,
    )
    if fault == "link":
        outside = tmp_path / "outside"
        _files(outside, {"secret.md": b"OUTSIDE-SECRET"})
        _link_dir(records / "linked", outside)
    elif fault == "too-many-files":
        monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_FILES", 2)
    elif fault == "too-many-bytes":
        monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_BYTES", 10)
    elif fault in ("grew", "shrank"):
        def _listed_then_changed(root: Path) -> SnapshotPlan:
            plan = real_plan(root)
            target = root / _CONVERGENCE
            content = target.read_bytes()
            target.write_bytes(content + b"!" if fault == "grew" else content[:-1])
            return plan

        monkeypatch.setattr(records_snapshot, "plan_snapshot", _listed_then_changed)
    elif fault == "unreadable":
        def _sharing_violation(*args: Any, **kwargs: Any) -> str:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")

        monkeypatch.setattr(records_snapshot, "_copy_member", _sharing_violation)
    elif fault == "reads-back-wrong":
        def _wrong_digest(*args: Any, **kwargs: Any) -> str:
            real_copy(*args, **kwargs)
            return "0" * 64

        monkeypatch.setattr(records_snapshot, "_copy_member", _wrong_digest)
    elif fault == "member-missing":
        def _no_bag_info(bag_zip: Any, name: str, text: str, stamp: Any) -> None:
            if not name.endswith("/bag-info.txt"):
                real_text(bag_zip, name, text, stamp)

        monkeypatch.setattr(records_snapshot, "_write_text", _no_bag_info)
    elif fault == "member-extra":  # A3: a member the bag does not list; only the member-list check refuses it (P-8)
        def _one_more(bag_zip: Any, name: str, text: str, stamp: Any) -> None:
            real_text(bag_zip, name, text, stamp)
            if name.endswith("/bagit.txt"):  # after the last member the bag lists
                real_text(bag_zip, name.removesuffix("bagit.txt") + "unlisted.txt", "unlisted\n", stamp)

        monkeypatch.setattr(records_snapshot, "_write_text", _one_more)
    else:  # "not-recorded": the file is written and checked, then the ledger refuses its row
        async def _ledger_refuses(self: ArchiveLedger, snapshot: SnapshotRecord) -> int:
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(ArchiveLedger, "record_snapshot", _ledger_refuses)


@pytest.mark.parametrize("fault", _FAULTS)
def test_a_snapshot_that_cannot_be_made_refuses_the_reset_and_deletes_nothing(
    fault: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    _inject(fault, data_dir / "ship-records", tmp_path, monkeypatch)
    changed = f"ship-records/{_CONVERGENCE}" if fault in ("grew", "shrank") else ""
    before = {path: content for path, content in _data_files(data_dir).items() if path != changed}

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 1

    after = _data_files(data_dir)
    assert set(after) == set(before) | ({changed} if changed else set())  # Ship's Records and every tier file
    assert {path: content for path, content in after.items() if path != changed} == before
    assert _snapshot_files(tmp_path) == []  # no snapshot, and no temporary file left behind
    if fault in _PREFLIGHT_FAULTS:  # A2: refused before anything is written: no promotion, description or row
        assert not _archive_db(tmp_path).exists()
    else:
        assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM archive_snapshots") == [(0,)]
        assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM generations") == [(0,)]  # closed only with its snapshot
    assert not (data_dir / "probos.pid").exists()


def test_skip_promotion_skips_the_snapshot_with_it_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True, skip_promotion="drill") == 0

    assert "The Ship's Records snapshot is skipped with it." in capsys.readouterr().out
    assert _snapshot_files(tmp_path) == []
    assert _rows(_archive_db(tmp_path), "SELECT reset_tier, outcome, reason FROM generations") == [(3, "skipped", "drill")]
    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM archive_snapshots") == [(0,)]


def test_without_an_instance_id_a_full_reset_of_ship_records_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path, instance_id="")
    _files(data_dir / "ship-records", {"manuals/m.md": b"---\nauthor: shipyard\n---\nA manual, never a source.\n"})
    before = _data_files(data_dir)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 1
    assert _data_files(data_dir) == before

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0  # tier 2 keeps Ship's Records: S1's rule, unchanged
    assert (data_dir / "ship-records" / "manuals" / "m.md").is_file()


# --- X6 to X10: the plan, the bag, the name ------------------------------------------------------------------------


def test_the_plan_lists_every_file_but_git_and_procedures_within_its_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "records"
    _files(root, {
        "a.md": b"a", "notebooks/b.md": b"bb", "notebooks/procedures/c.md": b"ccc", "reports/.hidden": b"x",
        ".git/HEAD": b"head", "procedures/p.yaml": b"steps",
    })
    plan = plan_snapshot(root)
    assert [(item.path, item.size) for item in plan.files] == [
        ("a.md", 1), ("notebooks/b.md", 2), ("notebooks/procedures/c.md", 3), ("reports/.hidden", 1),
    ]  # only the top-level .git and procedures stay out
    assert plan.total_bytes == 7
    monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_FILES", 4)
    monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_BYTES", 7)
    assert len(plan_snapshot(root).files) == 4  # exactly at both bounds
    monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_FILES", 3)
    with pytest.raises(SnapshotRefused, match="bound"):
        plan_snapshot(root)
    monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_FILES", 4)
    monkeypatch.setattr(records_snapshot, "SNAPSHOT_MAX_BYTES", 6)
    with pytest.raises(SnapshotRefused, match="bound"):
        plan_snapshot(root)
    assert plan_snapshot(tmp_path / "absent") == SnapshotPlan(files=(), total_bytes=0)
    (tmp_path / "empty").mkdir()
    assert _prepare(tmp_path / "empty", tmp_path / "snaps") is None
    assert not (tmp_path / "snaps").exists()  # an empty tree writes nothing
    (tmp_path / "a-file").write_bytes(b"x")
    with pytest.raises(SnapshotRefused, match="not a directory"):
        plan_snapshot(tmp_path / "a-file")


def test_a_link_inside_ship_records_is_never_followed(tmp_path: Path) -> None:
    root = tmp_path / "records"
    _files(root, {"notebooks/a.md": b"a"})
    outside = tmp_path / "outside"
    _files(outside, {"secret.md": b"OUTSIDE"})
    _link_dir(root / "notebooks" / "linked", outside)

    with pytest.raises(SnapshotRefused, match="notebooks/linked is a link"):
        plan_snapshot(root)


def test_a_prepared_snapshot_reads_back_as_written_and_is_published_once(tmp_path: Path) -> None:
    root = tmp_path / "records"
    _files(root, {"100%.md": b"percent", "notes/a b.md": b"space"})

    prepared = _prepare(root, tmp_path / "snaps")

    assert prepared.result.relative_path == _NAME
    assert (prepared.result.file_count, prepared.result.total_bytes) == (2, 12)
    assert prepared.result.paths == ("100%.md", "notes/a b.md")
    assert prepared.temp_path.is_file() and not prepared.final_path.exists()  # checked, not yet in place
    assert prepared.result.sha256 == _sha256(prepared.temp_path.read_bytes())
    prepared.publish()
    assert prepared.final_path == tmp_path / "snaps" / _NAME
    assert prepared.final_path.is_file() and not prepared.temp_path.exists()
    bag = "20261001T080000Z_20261027T060005Z"
    with zipfile.ZipFile(prepared.final_path) as bag_zip:
        assert bag_zip.namelist() == [
            f"{bag}/data/100%.md", f"{bag}/data/notes/a b.md", f"{bag}/manifest-sha256.txt", f"{bag}/bag-info.txt",
            f"{bag}/bagit.txt",
        ]
        manifest = bag_zip.read(f"{bag}/manifest-sha256.txt").decode("utf-8")
        info = bag_zip.read(f"{bag}/bag-info.txt").decode("utf-8")
    assert manifest == f"{_sha256(b'percent')}  data/100%25.md\n{_sha256(b'space')}  data/notes/a b.md\n"
    for line in ("Bagging-Date: 2026-10-27", "Payload-Oxum: 12.2", f"External-Identifier: {_DID}",
                 "ProbOS-Generation-Started: 2026-10-01T08:00:00Z", "ProbOS-Generation-Ended: 2026-10-27T06:00:05Z",
                 "ProbOS-Excluded: .git/ procedures/"):
        assert f"{line}\n" in info


def test_a_snapshot_is_never_written_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "records"
    _files(root, {"a.md": b"a"})
    first = _prepare(root, tmp_path / "snaps")
    first.publish()
    published = first.final_path.read_bytes()

    with pytest.raises(SnapshotRefused, match="exists already"):
        _prepare(root, tmp_path / "snaps")  # the same name: refused before anything is written
    assert first.final_path.read_bytes() == published

    later = _prepare(root, tmp_path / "snaps", ended=_ENDED.replace(second=6))
    later.final_path.write_bytes(b"someone else's file")  # appears after the check, before publishing
    with pytest.raises(SnapshotRefused, match="exists already"):
        later.publish()
    assert later.final_path.read_bytes() == b"someone else's file"
    later.discard()
    assert not later.temp_path.exists()

    racing = _prepare(root, tmp_path / "snaps", ended=_ENDED.replace(second=7))
    with monkeypatch.context() as patch:  # A2 (A-F4): the name appears after any check publish could make
        patch.setattr(records_snapshot.os.path, "lexists", lambda _path: False)
        racing.final_path.write_bytes(b"a racing writer's file")
        with pytest.raises(SnapshotRefused, match="exists already"):
            racing.publish()
    assert racing.final_path.read_bytes() == b"a racing writer's file"
    racing.discard()


@pytest.mark.parametrize("timeline", ["", " ", "../ship", "ship/one", "ship one", "a" * 65, ".hidden", "ship\n", None])
def test_an_instance_id_that_cannot_name_a_directory_refuses_the_snapshot(timeline: Any) -> None:
    with pytest.raises(SnapshotRefused):
        snapshot_relative_path(timeline, _STARTED, _ENDED)


def test_only_a_snapshot_s_own_name_is_a_snapshot_path() -> None:
    assert snapshot_relative_path(_SHIP, _STARTED, _ENDED) == _NAME
    assert snapshot_relative_path("a" * 64, _STARTED, _ENDED).startswith("a" * 64 + "/")
    assert is_snapshot_relative_path(_NAME)
    for bad in (f"../{_NAME}", f"{_SHIP}/../../escape.zip", f"{_SHIP}/notes.zip", _NAME + "/../x",
                _NAME.replace("/", "\\"), "", None, 7):
        assert not is_snapshot_relative_path(bad)
    with pytest.raises(ValueError):
        snapshot_relative_path(_SHIP, datetime(2026, 10, 1, 8, 0), _ENDED)  # a time with no offset


# --- X11 to X14: the ledger, the Captain's commands, the census, the dry run ---------------------------------------


def _record(**changes: Any) -> SnapshotRecord:
    record = SnapshotRecord(
        timeline_id=_SHIP, ship_did=_DID, generation_started="2026-10-01T08:00:00Z",
        generation_ended="2026-10-27T06:00:05Z", relative_path=_NAME, sha256="a" * 64, file_count=3, total_bytes=99,
    )
    return dataclasses.replace(record, **changes) if changes else record


async def test_the_ledger_records_a_snapshot_without_its_content_and_marks_its_erasure_once(tmp_path: Path) -> None:
    path = tmp_path / "archive.db"
    store = ArchiveStore(str(path), connection_factory=default_factory)
    await store.initialize()  # the store owns the schema: it creates archive_snapshots
    await store.close()
    ledger = ArchiveLedger(str(path), connection_factory=default_factory)
    await ledger.initialize()
    try:
        first = await ledger.record_snapshot(_record())
        with pytest.raises(sqlite3.IntegrityError):
            await ledger.record_snapshot(_record())  # one row per file name
        (entry,) = await ledger.snapshot_entries()
        assert (entry.id, entry.relative_path, entry.erased_at, entry.erase_reason) == (first, _NAME, None, "")
        marked = await ledger.mark_snapshot_erased(first, "the Captain's order")
        again = await ledger.mark_snapshot_erased(first, "a second reason")
        assert marked is not None and again is not None and marked.erased_at is not None
        assert (again.erased_at, again.erase_reason) == (marked.erased_at, "the Captain's order")  # the first stands
        assert await ledger.snapshot_by_id(first) == again
        assert await ledger.snapshot_by_id(first + 1) is None
        assert await ledger.mark_snapshot_erased(first + 1, "x") is None
        assert await ledger.mark_snapshot_erased(2**63, "x") is None
        for bad_id in (0, -1):
            with pytest.raises(ValueError):
                await ledger.mark_snapshot_erased(bad_id, "x")
        for reason in ("", "  ", "x" * 501):
            with pytest.raises(ValueError):
                await ledger.mark_snapshot_erased(first, reason)
    finally:
        await ledger.close()
    assert [row[1] for row in _rows(path, "PRAGMA table_info(archive_snapshots)")] == [
        "id", "timeline_id", "ship_did", "generation_started", "generation_ended", "relative_path", "sha256",
        "file_count", "total_bytes", "recorded_at", "erased_at", "erase_reason",
    ]  # no column for content
    for change in ({"sha256": "A" * 64}, {"sha256": "a" * 63}, {"file_count": -1}, {"total_bytes": True},
                   {"relative_path": " "}, {"ship_did": ""}):
        with pytest.raises(ValueError):
            _record(**change)


async def test_the_ledger_opens_only_an_archive_the_store_has_brought_to_its_schema(tmp_path: Path) -> None:
    for name, version in (("v7.db", 7), ("v0.db", 0)):
        connection = sqlite3.connect(str(tmp_path / name))
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
        connection.close()
        ledger = ArchiveLedger(str(tmp_path / name), connection_factory=default_factory)
        with pytest.raises(RuntimeError, match=f"schema version {version}"):
            await ledger.initialize()


def test_the_captain_lists_and_erases_a_snapshot_with_the_marker_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    (snapshot,) = _snapshot_files(tmp_path)
    relative = snapshot.relative_to(_snapshots_dir(tmp_path)).as_posix()
    capsys.readouterr()

    assert _archive(monkeypatch, config, "snapshots") == 0
    assert f"  1: {relative} (present);" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="drill", yes=False) == 0
    assert snapshot.is_file() and _erasures(tmp_path) == [(None, "")]  # declined: nothing recorded or deleted

    real_unlink = Path.unlink

    def _locked(self: Path, missing_ok: bool = False) -> None:
        if self == snapshot:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _locked)
    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="the Captain's order", yes=True) == 1
    assert snapshot.is_file()  # the file remains ...
    ((erased_at, reason),) = _erasures(tmp_path)
    assert erased_at is not None and reason == "the Captain's order"  # ... and the marker came first
    monkeypatch.setattr(Path, "unlink", real_unlink)

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="again", yes=True) == 0
    assert not snapshot.exists()  # the same command finished it
    assert _erasures(tmp_path) == [(erased_at, "the Captain's order")]  # the first reason stands
    capsys.readouterr()
    assert _archive(monkeypatch, config, "snapshots") == 0
    assert f"  1: {relative} (erased by the Captain);" in capsys.readouterr().out
    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=2, reason="x", yes=True) == 1  # no such id


def test_an_erasure_never_deletes_a_file_outside_the_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    (snapshot,) = _snapshot_files(tmp_path)
    outside = tmp_path / "archive" / "escape.zip"
    outside.write_bytes(b"not a snapshot")
    connection = sqlite3.connect(str(_archive_db(tmp_path)))
    connection.execute("UPDATE archive_snapshots SET relative_path = ?", ("../escape.zip",))  # a hand-edited row
    connection.commit()
    connection.close()

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="x", yes=True) == 1

    assert outside.read_bytes() == b"not a snapshot" and snapshot.is_file()
    assert _erasures(tmp_path) == [(None, "")]
    disabled = _config(tmp_path, archive_enabled=False)
    assert _archive(monkeypatch, disabled, "erase-snapshot", snapshot_id=1, reason="x", yes=True) == 2
    assert _archive(monkeypatch, disabled, "snapshots") == 2
    for bad_id, bad_reason in ((0, "x"), (1, " "), (1, "x" * 501)):
        assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=bad_id, reason=bad_reason, yes=True) == 2


@pytest.mark.parametrize(
    ("argv", "attribute", "value"),
    [
        (["archive", "snapshots"], "archive_cmd", "snapshots"),
        (["archive", "erase-snapshot", "3", "--reason", "drill", "--yes"], "snapshot_id", 3),
    ],
    ids=["snapshots", "erase-snapshot"],
)
def test_main_parses_the_snapshot_commands(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], attribute: str, value: Any,
) -> None:
    seen: list[Namespace] = []

    def _command(args: Namespace) -> int:
        seen.append(args)
        return 3

    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # no repository .env into the worker
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: None)  # main sets one on Windows
    monkeypatch.setattr(cli, "_cmd_archive", _command)
    monkeypatch.setattr("sys.argv", ["probos", *argv])

    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert exited.value.code == 3
    assert [getattr(args, attribute) for args in seen] == [value]


def test_only_the_cli_records_or_erases_a_snapshot_and_nothing_else_reads_one() -> None:
    """``record_snapshot`` and ``mark_snapshot_erased`` are named in ``src`` by ``__main__.py`` alone, and only it
    imports ``records_snapshot``: no agent, service or Oracle tier writes or reads a snapshot."""
    naming: dict[str, set[str]] = {"record_snapshot": set(), "mark_snapshot_erased": set()}
    importing: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        relative = path.relative_to(_SRC).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in naming:
                naming[node.attr].add(relative)
            elif isinstance(node, ast.Constant) and type(node.value) is str and node.value in naming:
                naming[node.value].add(relative)
            elif isinstance(node, ast.ImportFrom) and (
                node.module == "probos.knowledge.records_snapshot"
                or (node.module == "probos.knowledge" and any(alias.name == "records_snapshot" for alias in node.names))
            ):
                importing.add(relative)
    assert naming == {"record_snapshot": {"__main__.py"}, "mark_snapshot_erased": {"__main__.py"}}
    assert importing == {"__main__.py"}


def test_a_dry_run_shows_the_snapshot_a_full_reset_would_keep_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    records = data_dir / "ship-records"
    files = len(plan_snapshot(records).files)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True, dry_run=True) == 0
    assert f"Ship's Records snapshot: {files} file(s)" in capsys.readouterr().out
    assert not _snapshots_dir(tmp_path).exists()

    outside = tmp_path / "outside"
    _files(outside, {"secret.md": b"OUTSIDE"})
    _link_dir(records / "linked", outside)
    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True, dry_run=True) == 0
    assert "The Ship's Records snapshot would refuse this reset" in capsys.readouterr().out


# --- A2: the round-1 repairs ---------------------------------------------------------------------------------------


def test_a_publish_that_fails_leaves_its_row_shown_missing_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (A-F7): the row is recorded before the file is published, so a publish that fails leaves the row, never
    deleted, which ``probos archive snapshots`` shows as missing; the reset refuses with nothing deleted."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    before = _data_files(data_dir)
    config = _config(tmp_path)

    def _no_space(self: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(records_snapshot.PreparedSnapshot, "publish", _no_space)

    assert _reset(monkeypatch, config, data_dir, full=True) == 1

    assert _data_files(data_dir) == before and _snapshot_files(tmp_path) == []
    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM archive_snapshots") == [(1,)]  # the row stays
    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM generations") == [(0,)]
    capsys.readouterr()
    assert _archive(monkeypatch, config, "snapshots") == 0
    assert "(missing);" in capsys.readouterr().out


def test_a_ship_records_root_that_cannot_be_inspected_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (A-F1): only a root that is not there is an empty plan; an error inspecting it propagates."""
    root = tmp_path / "records"
    _files(root, {"a.md": b"a"})
    real_lstat = os.lstat

    def _denied(path: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(path, (str, os.PathLike)) and Path(path) == root:
            raise PermissionError(13, "Access is denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(records_snapshot.os, "lstat", _denied)
    with pytest.raises(PermissionError):
        plan_snapshot(root)


def test_a_ship_records_root_that_is_a_link_is_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (A-F1): a root that is a link or junction refuses, in the plan and in the reset, before anything is written."""
    outside = tmp_path / "outside"
    _files(outside, {"notebooks/a.md": b"OUTSIDE"})
    _link_dir(tmp_path / "records-link", outside)
    with pytest.raises(SnapshotRefused, match="is a link"):
        plan_snapshot(tmp_path / "records-link")

    data_dir = _data_dir(tmp_path)
    _link_dir(data_dir / "ship-records", outside)
    before = _tree(outside)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 1

    assert _tree(outside) == before and (data_dir / "trust.db").is_file()
    assert not _archive_db(tmp_path).exists()  # refused before anything was written


def test_a_tag_file_that_reads_back_wrong_refuses_the_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (A-F6): the read-back reads the tag files whole too, so zipfile checks their CRCs."""
    root = tmp_path / "records"
    _files(root, {"a.md": b"a"})
    real_verify = records_snapshot._verify_bag

    def _manifest_damaged(temp: Path, bag: str, plan: SnapshotPlan, digests: dict[str, str]) -> str:
        with zipfile.ZipFile(temp) as bag_zip:
            member = bag_zip.getinfo(f"{bag}/manifest-sha256.txt")
        with open(temp, "r+b") as raw:
            raw.seek(member.header_offset + 26)
            name_length, extra_length = struct.unpack("<HH", raw.read(4))
            raw.seek(member.header_offset + 30 + name_length + extra_length + member.compress_size // 2)
            (byte,) = raw.read(1)
            raw.seek(-1, os.SEEK_CUR)
            raw.write(bytes([byte ^ 0xFF]))
        return real_verify(temp, bag, plan, digests)

    monkeypatch.setattr(records_snapshot, "_verify_bag", _manifest_damaged)
    with pytest.raises((zipfile.BadZipFile, zlib.error, EOFError)):
        _prepare(root, tmp_path / "snaps")
    assert [path for path in (tmp_path / "snaps").rglob("*") if path.is_file()] == []  # the temporary file is removed


def test_a_file_system_without_hard_links_refuses_to_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (A-F4): publication is a hard link, never a rename that may replace; where links fail, it refuses."""
    root = tmp_path / "records"
    _files(root, {"a.md": b"a"})
    prepared = _prepare(root, tmp_path / "snaps")

    def _unsupported(*args: Any, **kwargs: Any) -> None:
        raise OSError(95, "Operation not supported")

    monkeypatch.setattr(records_snapshot.os, "link", _unsupported)
    with pytest.raises(SnapshotRefused, match="hard link"):
        prepared.publish()
    assert not prepared.final_path.exists() and prepared.temp_path.is_file()  # kept for the caller's discard
    prepared.discard()
    assert not prepared.temp_path.exists()


def test_an_erasure_deletes_only_a_regular_file_inside_the_snapshots_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (A-F3): before its marker, the erasure refuses a directory at the snapshot's name and a timeline directory
    that is a link or junction; nothing is marked or deleted."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    (snapshot,) = _snapshot_files(tmp_path)
    snapshot.unlink()
    snapshot.mkdir()  # a directory where the snapshot's file was
    (snapshot / "keep.txt").write_bytes(b"keep")

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="x", yes=True) == 1
    assert (snapshot / "keep.txt").read_bytes() == b"keep" and _erasures(tmp_path) == [(None, "")]

    shutil.rmtree(snapshot.parent)
    outside = tmp_path / "outside"
    _files(outside, {snapshot.name: b"OUTSIDE"})
    _link_dir(snapshot.parent, outside)  # the timeline's directory leads out of the snapshots directory

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="x", yes=True) == 1
    assert (outside / snapshot.name).read_bytes() == b"OUTSIDE" and _erasures(tmp_path) == [(None, "")]


def test_a_dry_run_says_a_full_reset_without_an_instance_id_would_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (A-F5): the dry run and the reset share one preflight; no snapshot is promised that the reset would refuse."""
    data_dir = _data_dir(tmp_path, instance_id="")
    _files(data_dir / "ship-records", {"manuals/m.md": b"---\nauthor: shipyard\n---\nA manual, never a source.\n"})

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True, dry_run=True) == 0

    out = capsys.readouterr().out
    assert "This reset would refuse" in out
    assert "Institutional Knowledge" not in out  # A4 (R2-B1): a refused dry run shows no tier table, reads nothing more
    assert "No instance id: Ship's Records hold 1 file(s)" in out
    assert "would be kept" not in out
    assert not _archive_db(tmp_path).exists()


def test_a_snapshot_is_written_only_into_the_snapshots_directory_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (A-F2): a link or junction at the snapshots directory or the timeline's refuses the snapshot, in
    ``prepare_snapshot`` and in the reset's preflight; at every tier the snapshots directory, resolved, may not be
    inside or around what the reset deletes."""
    root = tmp_path / "records"
    _files(root, {"a.md": b"a"})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _link_dir(tmp_path / "snaps", elsewhere)
    with pytest.raises(SnapshotRefused, match="is a link"):
        _prepare(root, tmp_path / "snaps")
    assert list(elsewhere.rglob("*")) == []

    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    before = _data_files(data_dir)
    _snapshots_dir(tmp_path).mkdir()
    _link_dir(_snapshots_dir(tmp_path) / _SHIP, data_dir / "ship-records" / "reports")  # into what --full deletes

    assert _reset(monkeypatch, config, data_dir, full=True) == 1

    assert _data_files(data_dir) == before
    assert not _archive_db(tmp_path).exists()  # the preflight refused before anything was written

    base = tmp_path / "tier2"
    data2 = _data_dir(base)
    config2 = _config(base)
    _files(data2 / "semantic", {"older.zip": b"an older snapshot"})
    _link_dir(_snapshots_dir(base), data2 / "semantic")  # the snapshots directory is what tier 2 deletes
    capsys.readouterr()

    assert _reset(monkeypatch, config2, data2) == 1

    assert (data2 / "semantic" / "older.zip").read_bytes() == b"an older snapshot"
    assert "the Ship's Archive is inside what this reset deletes" in capsys.readouterr().out


# --- A4: the round-2 repairs ---------------------------------------------------------------------------------------


def _posix_stat() -> Any:
    """A POSIX build's ``stat`` module, stricter: no ``IO_REPARSE_TAG_*`` (Windows-only) and no ``FILE_ATTRIBUTE_*``.

    A5: ``Lib/stat.py`` defines the 17 ``FILE_ATTRIBUTE_*`` constants on every platform; they are removed here too,
    and no S6 module reads either set (X18's scan), so no result depends on the difference (A4).
    Swapped in for ``records_snapshot.stat`` only, never deleted from the interpreter's ``stat``: the standard library
    reads those names itself on Windows (``ntpath.isjunction``)."""
    return types.SimpleNamespace(**{
        name: value for name, value in vars(stat).items()
        if not name.startswith(("_", "IO_REPARSE_TAG_", "FILE_ATTRIBUTE_"))
    })


def test_an_erasure_removes_the_temporary_name_a_publish_could_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A4 (A-R2-F2): a temporary name ``publish`` could not remove after its link is the snapshot's own file under a
    second name. The erasure removes it first, then the snapshot; while either remains it exits 1 and the listing says
    the file remains; the same command finishes it. The denial is injected: POSIX has no sharing violation."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    real_unlink = Path.unlink
    denied: list[Path] = []

    def _shared(self: Path, missing_ok: bool = False) -> None:
        if self.name.endswith(".partial") and len(denied) < 2:  # the publish's removal, then the erasure's first
            denied.append(self)
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _shared)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    snapshot, alias = sorted(_snapshot_files(tmp_path), key=lambda path: path.name.startswith("."))
    assert alias.name == f".{snapshot.name}.partial"
    assert os.path.samestat(os.lstat(snapshot), os.lstat(alias))  # premise: one file, two names
    relative = snapshot.relative_to(_snapshots_dir(tmp_path)).as_posix()
    capsys.readouterr()

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="drill", yes=True) == 1
    assert snapshot.is_file() and alias.is_file()  # the alias first: the final name is still there to find it by
    assert "Run the same command again" in capsys.readouterr().out
    assert _archive(monkeypatch, config, "snapshots") == 0
    assert (
        f"  1: {relative} (erased by the Captain; its file remains: run probos archive erase-snapshot again);"
        in capsys.readouterr().out
    )

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="again", yes=True) == 0
    assert _snapshot_files(tmp_path) == [] and len(denied) == 2
    assert _erasures(tmp_path)[0][1] == "drill"  # the first reason stands
    assert _archive(monkeypatch, config, "snapshots") == 0
    assert f"  1: {relative} (erased by the Captain);" in capsys.readouterr().out


def test_an_erasure_leaves_a_temporary_name_that_is_another_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A4 (A-R2-F2): only the snapshot's own file is removed under its temporary name; another file there (another
    attempt's, or a copy with the same bytes) is never touched. Identity decides, not the name or the content."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    (snapshot,) = _snapshot_files(tmp_path)
    other = snapshot.with_name(f".{snapshot.name}.partial")
    other.write_bytes(snapshot.read_bytes())  # the same bytes, another file
    assert not os.path.samestat(os.lstat(snapshot), os.lstat(other))  # premise

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="drill", yes=True) == 0

    assert _snapshot_files(tmp_path) == [other] and other.read_bytes()[:2] == b"PK"


def test_an_erasure_refuses_a_temporary_name_whose_identity_cannot_be_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A5 (A-R3-F1): ``os.path.samestat`` compares ``st_dev`` and ``st_ino``, and an index of 0 identifies no file.
    With every index reported as 0, another file at the temporary name refuses the erasure before its marker: exit 1,
    both names and the row unchanged. Once the Captain removes it, the same command erases: a zero index with no
    temporary name beside the snapshot is unaffected. Injected at the module's status boundary: no file system is
    known to report 0 where a hard link succeeds (R48). On ``77b65917`` the first erasure removed the other file."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir, full=True) == 0
    (snapshot,) = _snapshot_files(tmp_path)
    other = records_snapshot.temporary_name(snapshot)
    other.write_bytes(b"another attempt's file")
    assert not os.path.samestat(os.lstat(snapshot), os.lstat(other))  # premise: two files, real indices differ
    real_lstat = records_snapshot.lstat_or_none

    def _no_file_index(path: Path) -> Any:
        status = real_lstat(path)
        if status is None:
            return None
        return types.SimpleNamespace(
            st_mode=status.st_mode, st_dev=status.st_dev, st_ino=0,
            st_reparse_tag=getattr(status, "st_reparse_tag", 0),
        )

    monkeypatch.setattr(records_snapshot, "lstat_or_none", _no_file_index)
    capsys.readouterr()

    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="drill", yes=True) == 1
    out = capsys.readouterr().out
    assert "cannot be shown" in out and "Nothing was erased." in out
    assert _snapshot_files(tmp_path) == sorted([snapshot, other])
    assert other.read_bytes() == b"another attempt's file"
    assert _erasures(tmp_path) == [(None, "")]  # refused before the marker

    other.unlink()  # the Captain, having checked it
    assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="again", yes=True) == 0
    assert _snapshot_files(tmp_path) == [] and _erasures(tmp_path)[0][1] == "again"


def test_a_status_is_judged_by_its_mode_and_only_a_junction_s_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """A4 (A-R2-F1): ``is_link_status`` names nothing a POSIX build's ``stat`` lacks. A POSIX status (no
    ``st_reparse_tag``) is judged by its mode; a Windows status is a link by its mode or a junction's tag, and any
    other reparse tag (a cloud placeholder) is not a link. No S6 module names a Windows-only ``stat`` attribute."""
    monkeypatch.setattr(records_snapshot, "stat", _posix_stat())
    status = types.SimpleNamespace

    assert records_snapshot.is_link_status(status(st_mode=stat.S_IFDIR | 0o755)) is False
    assert records_snapshot.is_link_status(status(st_mode=stat.S_IFREG | 0o644)) is False
    assert records_snapshot.is_link_status(status(st_mode=stat.S_IFLNK | 0o777)) is True
    assert records_snapshot.is_link_status(status(st_mode=stat.S_IFDIR, st_reparse_tag=0xA0000003)) is True  # junction
    assert records_snapshot.is_link_status(status(st_mode=stat.S_IFREG, st_reparse_tag=0x9000001A)) is False  # cloud
    for relative in (
        "knowledge/records_snapshot.py", "knowledge/archive_ledger.py", "knowledge/nature_description.py", "__main__.py",
    ):
        path = _SRC / relative
        if relative == "knowledge/nature_description.py" and not path.exists():  # M2's file: absent on M1's tree only
            continue
        text = path.read_text(encoding="utf-8-sig")
        assert re.search(r"\bstat\.(IO_REPARSE_TAG_|FILE_ATTRIBUTE_)|\bst_file_attributes\b", text) is None, relative


@pytest.mark.parametrize("command", ["full", "dry-run", "erasure"])
def test_a_full_reset_its_dry_run_and_an_erasure_need_no_windows_only_name(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A4 (A-R2-F1): the real commands, with ``records_snapshot`` seeing a POSIX build's ``stat``, finish as they do
    on Windows (on ``2a1b6319`` each raised ``AttributeError``; the erasure reported it and exited 1)."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    if command == "erasure":
        assert _reset(monkeypatch, config, data_dir, full=True) == 0  # premise, with the platform's own stat
    monkeypatch.setattr(records_snapshot, "stat", _posix_stat())

    if command == "erasure":
        assert _archive(monkeypatch, config, "erase-snapshot", snapshot_id=1, reason="drill", yes=True) == 0
        assert _snapshot_files(tmp_path) == [] and _erasures(tmp_path)[0][1] == "drill"
    else:
        assert _reset(monkeypatch, config, data_dir, full=True, dry_run=command == "dry-run") == 0
        assert len(_snapshot_files(tmp_path)) == (1 if command == "full" else 0)
        assert (data_dir / "trust.db").exists() is (command == "dry-run")
