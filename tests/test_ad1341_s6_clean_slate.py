"""AD-1341 S6 (#1569), M3: ``probos reset --clean-slate`` clears nature, recorded first, and nothing else.

Real objects: the real ``_cmd_reset`` and ``main`` on a temporary data directory, a ``procedures.db`` with the
procedure store's own schema, the real ``ArchiveStore`` and ``ArchiveLedger``. The config loader is the one stand-in;
a deletion or a marker that fails is injected, because the platform cannot fail one on demand. No test reaches a real
data directory (the autouse fixture), and nothing here clears anything outside ``tmp_path``.
"""

from __future__ import annotations

import ast
import asyncio
import io
import os
import sqlite3
import stat
import sys
import types
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import probos
from probos import __main__ as cli
from probos.knowledge.archive_ledger import ArchiveLedger, NatureClearanceRecord
from probos.cognitive.procedure_store import _SCHEMA as _PROCEDURE_SCHEMA
from probos.config import ArchiveConfig, KnowledgeConfig, SystemConfig
from probos.knowledge.archive_promotion import promote_nature_description
from probos.knowledge import records_snapshot
from probos.knowledge.archive_store import ArchiveStore
from probos.knowledge.nature_description import PROCEDURES_DB, describe_nature
from probos.storage.sqlite_factory import default_factory

_SRC = Path(probos.__file__).resolve().parent
_SHIP = "ship-did-alpha-0001"
_BOOT = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
_B = _BOOT.timestamp()
_ROWS = (
    {"id": "p-0", "name": "Inherited routine", "created_at": _B - 86400.0},
    {"id": "p-1", "name": "Coolant drift triage", "created_at": _B + 60.0, "total_completions": 8},
    {"id": "p-2", "name": "Sensor first", "evolution_type": "FIX", "created_at": _B + 120.0},
    {"id": "p-3", "name": "Purge before isolating", "is_negative": 1, "created_at": _B + 180.0},
)
#: Data-directory files no reset tier lists and the clean slate must leave alone.
_KEPT_STORES = ("cognitive_skills.db", "skill_grants.db", "profile_qualifications.db")


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


def _config(tmp_path: Path, *, archive_enabled: bool = True) -> SystemConfig:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    (tmp_path / "archive").mkdir(exist_ok=True)
    section = ArchiveConfig(enabled=archive_enabled, db_path=str(_archive_db(tmp_path)))
    return SystemConfig(knowledge=KnowledgeConfig(repo_path=str(knowledge)), archive=section)


def _data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "ontology").mkdir(parents=True)
    id_file = data_dir / "ontology" / "instance_id"
    id_file.write_text(f"{_SHIP}\n", encoding="utf-8")
    os.utime(id_file, (_B, _B))  # the ship's first boot
    for name in ("events.db", "trust.db", "ward_room.db"):  # tiers 1, 2 and 3
        (data_dir / name).write_text(name, encoding="utf-8")
    return data_dir


def _nature(data_dir: Path) -> None:
    """The procedure store's directory as the vessel leaves it: the index, the challenger ledger, the semantic index."""
    path = data_dir / PROCEDURES_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(_PROCEDURE_SCHEMA)
        for row in _ROWS:
            columns, marks = ", ".join(row), ", ".join("?" for _ in row)
            connection.execute(f"INSERT INTO procedure_records ({columns}) VALUES ({marks})", tuple(row.values()))
        connection.commit()
    finally:
        connection.close()
    (path.parent / "procedures_challenges.db").write_bytes(b"ledger")
    (path.parent / "chroma").mkdir()
    (path.parent / "chroma" / "index.bin").write_bytes(b"index")


def _tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()
    }


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
        "data_dir": data_dir, "skip_promotion": None, "clean_slate": False,
    }
    values.update(flags)
    return cli._cmd_reset(Namespace(**values))


def _link_dir(link: Path, target: Path) -> None:
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"this host cannot create a directory link: {exc}")


async def _an_earlier_entry(tmp_path: Path, archive: Path | None = None) -> None:
    store = ArchiveStore(str(archive or _archive_db(tmp_path)), connection_factory=default_factory)
    await store.initialize()
    try:
        await promote_nature_description(store, describe_nature("ship-did-earlier-0000", _BOOT, (), developed=1, active=0))
    finally:
        await store.close()


@pytest.mark.parametrize("full", [False, True], ids=["tier2", "tier3"])
def test_a_clean_slate_describes_records_and_clears_nature_and_touches_nothing_else(
    full: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    for name in _KEPT_STORES:
        (data_dir / name).write_bytes(name.encode("utf-8"))
    (data_dir / "archives").mkdir()
    (data_dir / "archives" / "ward_room_2026-01-01_000000.db").write_bytes(b"an older backup")
    captain = tmp_path / "captain" / "system.yaml"
    captain.parent.mkdir()
    captain.write_text("archive:\n  enabled: true\n", encoding="utf-8")
    config = _config(tmp_path)
    asyncio.run(_an_earlier_entry(tmp_path))
    before = _tree(data_dir)

    assert _reset(monkeypatch, config, data_dir, full=full, clean_slate=True) == 0

    assert not (data_dir / "procedures").exists()
    archive = _archive_db(tmp_path)
    assert _rows(archive, "SELECT timeline_id, reset_tier, cleared, procedure_count FROM nature_clearances") == [
        (_SHIP, 3 if full else 2, '["procedures/"]', 4),
    ]
    assert _rows(archive, "SELECT timeline_id FROM archive WHERE source_kind = 'nature_description' ORDER BY id") == [
        ("ship-did-earlier-0000",), (_SHIP,),
    ]  # the earlier entry kept, and this crew's nature described before it was cleared
    deleted = {"events.db", "trust.db", "ontology/instance_id"} | ({"ward_room.db"} if full else set())
    after = {
        path: content for path, content in _tree(data_dir).items()
        if path != "probos.pid.lock" and not (path.startswith("archives/ward_room_") and path not in before)
    }
    assert after == {
        path: content for path, content in before.items() if path not in deleted and not path.startswith("procedures/")
    }
    assert captain.read_text(encoding="utf-8") == "archive:\n  enabled: true\n"
    assert _tree(tmp_path / "knowledge") == {}
    assert "Nature cleared (--clean-slate): procedures/" in capsys.readouterr().out


@pytest.mark.parametrize("flags", [{"soft": True}, {}, {"full": True}], ids=["tier1", "tier2", "tier3"])
def test_without_clean_slate_nature_persists_at_every_tier(
    flags: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    before = _tree(data_dir / "procedures")

    assert _reset(monkeypatch, _config(tmp_path), data_dir, **flags) == 0

    assert _tree(data_dir / "procedures") == before
    assert "Nature kept: procedures/ (Cognitive JIT procedures)" in capsys.readouterr().out
    if _archive_db(tmp_path).exists():
        assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM nature_clearances") == [(0,)]


@pytest.mark.parametrize("case", ["soft", "archive-disabled"])
def test_a_clean_slate_that_does_not_apply_or_cannot_be_recorded_changes_nothing(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    before = _tree(data_dir)
    config = _config(tmp_path, archive_enabled=case != "archive-disabled")

    assert _reset(monkeypatch, config, data_dir, clean_slate=True, **({"soft": True} if case == "soft" else {})) == 2

    assert _tree(data_dir) == before  # no pidfile lock either: refused before anything is opened
    assert not _archive_db(tmp_path).exists()


def test_an_interrupted_clean_slate_is_finished_by_running_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    config = _config(tmp_path)
    real_rmtree = cli.shutil.rmtree
    calls: list[Path] = []

    def _fails_once(path: Any, *args: Any, **kwargs: Any) -> None:
        calls.append(Path(path))
        if len(calls) == 1:
            (Path(path) / "procedures_challenges.db").unlink()  # part of it went before the failure
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(cli.shutil, "rmtree", _fails_once)

    assert _reset(monkeypatch, config, data_dir, clean_slate=True) == 1
    assert "did not finish" in capsys.readouterr().out
    assert (data_dir / "trust.db").is_file() and (data_dir / "ontology" / "instance_id").is_file()  # no tier loop
    assert (data_dir / PROCEDURES_DB).is_file()
    assert _rows(_archive_db(tmp_path), "SELECT procedure_count FROM nature_clearances") == [(4,)]  # recorded first
    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM generations") == [(0,)]  # A2 (C-F3): not closed yet

    assert _reset(monkeypatch, config, data_dir, clean_slate=True) == 0  # the same command finishes it
    assert not (data_dir / "procedures").exists() and not (data_dir / "trust.db").exists()
    assert _rows(_archive_db(tmp_path), "SELECT procedure_count FROM nature_clearances ORDER BY id") == [(4,), (4,)]
    assert _rows(_archive_db(tmp_path), "SELECT timeline_id, reset_tier, outcome FROM generations") == [
        (_SHIP, 2, "promoted"),
    ]  # closed once, after the clearance finished


def test_a_clean_slate_whose_marker_cannot_be_written_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    before = _tree(data_dir / "procedures")

    async def _refuses(self: ArchiveLedger, clearance: NatureClearanceRecord) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ArchiveLedger, "record_nature_clearance", _refuses)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, clean_slate=True) == 1

    assert "could not be recorded" in capsys.readouterr().out
    assert _tree(data_dir / "procedures") == before
    assert (data_dir / "trust.db").is_file()


def test_the_dry_run_and_the_confirmation_name_what_a_clean_slate_clears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    config = _config(tmp_path)

    assert _reset(monkeypatch, config, data_dir, dry_run=True, clean_slate=True) == 0
    out = capsys.readouterr().out
    assert "Nature (--clean-slate)" in out and "Cognitive JIT procedures, their challengers and index" in out

    assert _reset(monkeypatch, config, data_dir, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "Nature (--clean-slate)" not in out and "Cognitive JIT procedures: nature, kept by design" in out

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert _reset(monkeypatch, config, data_dir, yes=False, clean_slate=True) == 0  # declined
    assert "Nature (--clean-slate)" in capsys.readouterr().out
    assert (data_dir / PROCEDURES_DB).is_file() and not _archive_db(tmp_path).exists()


def _odd_procedures(shape: str, data_dir: Path, tmp_path: Path) -> Path:
    """At ``{data_dir}/procedures``: a junction to a sibling's real procedure store, or a file. Returns what must
    survive: the sibling, or the file."""
    if shape == "junction":
        sibling = tmp_path / "sibling"
        _nature(sibling)
        _link_dir(data_dir / "procedures", sibling / "procedures")
        return sibling
    (data_dir / "procedures").write_bytes(b"not the procedure store")
    return data_dir / "procedures"


def _kept(target: Path) -> Any:
    return _tree(target) if target.is_dir() else target.read_bytes()


def _archive_state(tmp_path: Path) -> list[list[tuple[Any, ...]]]:
    """Every row count a reset could change in the archive's file."""
    return [
        _rows(_archive_db(tmp_path), f"SELECT COUNT(*) FROM {table}")
        for table in ("archive", "generations", "archive_snapshots", "nature_clearances", "archive_vetoes")
    ]


@pytest.mark.parametrize("shape", ["junction", "file"])
def test_a_link_or_a_file_at_the_procedures_name_is_refused_before_anything_is_written(
    shape: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (B-F3, C-F2): refused by the preflight, before the promotion reads the store through it: nothing archived,
    described, recorded or closed, and the link's target or the file unchanged."""
    data_dir = _data_dir(tmp_path)
    config = _config(tmp_path)
    asyncio.run(_an_earlier_entry(tmp_path))
    archive_before = _archive_state(tmp_path)
    target = _odd_procedures(shape, data_dir, tmp_path)
    before = _kept(target)

    assert _reset(monkeypatch, config, data_dir, clean_slate=True) == 1

    assert _archive_state(tmp_path) == archive_before
    assert _kept(target) == before
    assert (data_dir / "trust.db").is_file() and (data_dir / "ontology" / "instance_id").is_file()
    expected = "is a link" if shape == "junction" else "is not the procedure store's directory"
    assert expected in capsys.readouterr().out


@pytest.mark.parametrize("shape", ["junction", "file"])
def test_the_clearance_refuses_a_link_or_a_file_again_where_it_deletes(shape: str, tmp_path: Path) -> None:
    """A2: ``_clear_nature`` asks again (the preflight asked first), so a change between the two is refused before
    the marker, and nothing is followed or deleted."""
    data_dir = _data_dir(tmp_path)
    config = _config(tmp_path)
    target = _odd_procedures(shape, data_dir, tmp_path)
    before = _kept(target)

    assert cli._clear_nature(config, 2, data_dir, Console(file=io.StringIO(), width=200)) is False

    assert not _archive_db(tmp_path).exists()  # no marker
    assert _kept(target) == before


@pytest.mark.parametrize(
    "flags", [{"clean_slate": True}, {"clean_slate": True, "full": True}, {}], ids=["tier2", "tier3", "flag-off"],
)
def test_an_archive_inside_the_procedure_store_refuses_a_clean_slate(
    flags: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (C-F1): ``--clean-slate`` deletes ``procedures/``, so an archive there is inside what the reset deletes, at
    either tier and in the dry run; without the flag ``procedures/`` is kept, and the archive in it."""
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    archive = data_dir / "procedures" / "archive" / "archive.db"
    archive.parent.mkdir()
    (tmp_path / "knowledge").mkdir()
    config = SystemConfig(
        knowledge=KnowledgeConfig(repo_path=str(tmp_path / "knowledge")),
        archive=ArchiveConfig(enabled=True, db_path=str(archive)),
    )
    asyncio.run(_an_earlier_entry(tmp_path, archive))

    if flags:
        assert _reset(monkeypatch, config, data_dir, dry_run=True, **flags) == 1  # the dry run refuses too
        before = _tree(data_dir / "procedures")
        assert _reset(monkeypatch, config, data_dir, **flags) == 1
        assert "the Ship's Archive is inside what this reset deletes" in capsys.readouterr().out
        assert _tree(data_dir / "procedures") == before and (data_dir / "trust.db").is_file()
    else:
        assert _reset(monkeypatch, config, data_dir) == 0
    assert ("ship-did-earlier-0000",) in _rows(archive, "SELECT timeline_id FROM archive")


def test_a_skipped_promotion_is_closed_only_after_its_clean_slate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A2 (C-F3): with ``--skip-promotion`` too, a clearance that fails leaves no generation closed; the rerun
    closes it once, as skipped. A4 (C-R2-F2): the skip's message is printed before the clearance and the close, so
    it says the reason will be recorded, never that it is."""
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    config = _config(tmp_path)
    real_rmtree = cli.shutil.rmtree
    calls: list[Path] = []

    def _fails_once(path: Any, *args: Any, **kwargs: Any) -> None:
        calls.append(Path(path))
        if len(calls) == 1:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(cli.shutil, "rmtree", _fails_once)

    assert _reset(monkeypatch, config, data_dir, clean_slate=True, skip_promotion="drill") == 1
    out = capsys.readouterr().out
    assert "the reason is recorded" not in out  # A4 (C-R2-F2): no generation row holds it yet
    assert "the reason will be recorded with the generation's close: drill" in out
    assert _rows(_archive_db(tmp_path), "SELECT COUNT(*) FROM generations") == [(0,)]

    assert _reset(monkeypatch, config, data_dir, clean_slate=True, skip_promotion="drill") == 0
    assert _rows(_archive_db(tmp_path), "SELECT reset_tier, outcome, reason FROM generations") == [
        (2, "skipped", "drill"),
    ]


@pytest.mark.parametrize("full", [False, True], ids=["tier2", "tier3"])
def test_a_refused_dry_run_reads_nothing_through_the_procedures_link(
    full: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A4 (R2-B1, C-R2-F1): a dry run whose preflight refuses a link at ``procedures`` prints the refusal and nothing
    else. It neither sizes the refused directory nor opens ``procedures.db`` through it, so the link's WAL-mode
    target gains no ``-wal`` or ``-shm`` file and none of its text is shown."""
    data_dir = _data_dir(tmp_path)
    config = _config(tmp_path)
    sibling = _odd_procedures("junction", data_dir, tmp_path)
    store = sibling / PROCEDURES_DB
    connection = sqlite3.connect(str(store))
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)  # premise: the vessel's mode
    finally:
        connection.close()
    names = sorted(os.listdir(store.parent))
    before = _tree(sibling)
    opened: list[str] = []
    sized: list[Path] = []
    real_open, real_size = cli._open_read_only, cli._get_file_size

    async def _counted(path: str) -> Any:
        opened.append(path)
        return await real_open(path)

    def _measured(path: Path) -> str:
        sized.append(path)
        return real_size(path)

    monkeypatch.setattr(cli, "_open_read_only", _counted)
    monkeypatch.setattr(cli, "_get_file_size", _measured)

    assert _reset(monkeypatch, config, data_dir, dry_run=True, clean_slate=True, full=full) == 0

    assert opened == []  # 2a1b6319: procedures.db opened once, through the link, by the promotion plan
    assert [path for path in sized if path.name == "procedures"] == []
    assert sorted(os.listdir(store.parent)) == names and _tree(sibling) == before  # no -wal, no -shm
    out = capsys.readouterr().out
    assert "This reset would refuse" in out and "is a link" in out
    assert "Coolant drift triage" not in out  # none of the target's text
    assert not _archive_db(tmp_path).exists()


def _posix_stat() -> Any:
    """A POSIX build's ``stat`` module, stricter: no ``IO_REPARSE_TAG_*`` (Windows-only) and no ``FILE_ATTRIBUTE_*``.

    A5: ``Lib/stat.py`` defines the 17 ``FILE_ATTRIBUTE_*`` constants on every platform; they are removed here too,
    and no S6 module reads either set, so no result depends on the difference (A4).
    Swapped in for ``records_snapshot.stat`` only, never deleted from the interpreter's ``stat``."""
    return types.SimpleNamespace(**{
        name: value for name, value in vars(stat).items()
        if not name.startswith(("_", "IO_REPARSE_TAG_", "FILE_ATTRIBUTE_"))
    })


def test_a_clean_slate_needs_no_windows_only_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A4 (A-R2-F1): with ``records_snapshot`` seeing a POSIX build's ``stat``, the clean slate's checks judge
    ``procedures/`` by its mode and the reset clears it (on ``2a1b6319`` the preflight raised ``AttributeError``)."""
    data_dir = _data_dir(tmp_path)
    _nature(data_dir)
    monkeypatch.setattr(records_snapshot, "stat", _posix_stat())

    assert _reset(monkeypatch, _config(tmp_path), data_dir, clean_slate=True) == 0

    assert not (data_dir / "procedures").exists()
    assert _rows(_archive_db(tmp_path), "SELECT procedure_count FROM nature_clearances") == [(4,)]


def test_only_the_cli_records_a_clean_slate() -> None:
    naming: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == "record_nature_clearance") or (
                isinstance(node, ast.Constant) and node.value == "record_nature_clearance"
            ):
                naming.add(path.relative_to(_SRC).as_posix())
    assert naming == {"__main__.py"}


def test_main_parses_clean_slate(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Namespace] = []

    def _command(args: Namespace) -> int:
        seen.append(args)
        return 3

    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # no repository .env into the worker
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: None)  # main sets one on Windows
    monkeypatch.setattr(cli, "_cmd_reset", _command)
    monkeypatch.setattr("sys.argv", ["probos", "reset", "--yes", "--clean-slate"])

    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert exited.value.code == 3
    assert [args.clean_slate for args in seen] == [True]


@pytest.mark.parametrize(
    "change",
    [{"reset_tier": 1}, {"reset_tier": 4}, {"reset_tier": True}, {"procedure_count": -2}, {"procedure_count": 1.0},
     {"cleared": ["procedures/"]}, {"cleared": (" ",)}, {"timeline_id": None}],
    ids=["tier-1", "tier-4", "tier-bool", "count-below", "count-float", "cleared-list", "cleared-blank", "timeline"],
)
def test_a_clean_slate_marker_holds_only_what_it_may(change: dict[str, Any]) -> None:
    good: dict[str, Any] = {"timeline_id": _SHIP, "reset_tier": 2, "cleared": ("procedures/",), "procedure_count": 0}
    NatureClearanceRecord(**good)  # premise
    NatureClearanceRecord(**{**good, "timeline_id": "", "procedure_count": -1})  # no instance id; an unread store
    with pytest.raises(ValueError):
        NatureClearanceRecord(**{**good, **change})
