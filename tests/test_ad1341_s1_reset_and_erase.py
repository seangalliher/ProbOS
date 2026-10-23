"""AD-1341 S1 M3 (#1569): ``probos reset`` promotes what the crew published before it deletes anything, and
``probos archive erase`` is the Captain's erasure.

Real objects throughout: the real ``_cmd_reset``, ``_cmd_archive`` and ``main`` on a temporary data directory; a
real ``SystemConfig`` whose archive is ``tmp_path / "archive.db"`` and whose knowledge repo is a temporary
directory, so no test touches ``~/.probos``; Ship's Records written by the store's own producers; the real
``ArchiveStore``, AD-816 pidfile and ``OracleService``. The config loader is the one stand-in: it returns that
``SystemConfig`` instead of reading YAML (``main``'s dispatch test also replaces the command it dispatches to).
A4's parser tests read a named YAML file with the real loader, and its guard test runs two real processes. A6's
vessel tests run the real ``_serve`` in a child process with its runtime, web server and browser replaced, and its
lock tests make the platform's lock call fail with a chosen errno, as M3's round-2 reviewer did.
The tests are synchronous because ``_cmd_reset`` runs its own event loop, as the CLI does.
"""

from __future__ import annotations

import ast
import asyncio
import errno
import os
import sqlite3
import sys
import time
from argparse import Namespace as _Namespace
from pathlib import Path
from subprocess import Popen as _Popen
from threading import Thread as _Thread
from typing import Any

import pytest

import probos
from probos import __main__ as cli
from probos.cognitive.oracle_service import OracleService
from probos.config import ArchiveConfig, KnowledgeConfig, RecordsConfig, SystemConfig
from probos.knowledge.archive_store import ArchiveStore
from probos.knowledge.records_store import RecordsStore
from probos.pidfile_guard import (
    AnotherInstanceRunning,
    PidfileLockUnavailable,
    _read_pid_from,
    acquire_pidfile,
    assert_no_other_instance,
    is_pid_alive,
)
from probos.storage.sqlite_factory import default_factory

_SRC = Path(probos.__file__).resolve().parent
_SHIP = "ship-did-alpha-0001"
_NEXT_SHIP = "ship-did-beta-0002"
_CONVERGENCE = "reports/convergence/convergence-20261022-000000.md"
_CLAIM = {"claim_id": "c0ffee02c0ffee02", "contest_state": "uncontested"}
_real_loader = cli._load_config_with_fallback  # A4: kept before any test replaces it

# A4 (F2): one acquirer of the AD-816 pidfile, as a separate process. "slow" judges the stale PID dead a second
# late, as a loaded machine might; each process waits for the test's signal files, and a holder stays alive.
_ACQUIRER = '''
import os
import sys
import time
from pathlib import Path

from probos import pidfile_guard

data_dir, name, signals = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])


def _wait_for(flag):
    deadline = time.monotonic() + 30
    while not (signals / flag).exists():
        if time.monotonic() > deadline:
            sys.exit(9)
        time.sleep(0.01)


if name == "slow":
    judge = pidfile_guard.is_pid_alive

    def _slowly(pid):
        time.sleep(1.0)
        return judge(pid)

    pidfile_guard.is_pid_alive = _slowly
(signals / f"ready-{name}").write_text("", encoding="utf-8")
_wait_for(f"go-{name}")
try:
    pidfile_guard.acquire_pidfile(data_dir)
    outcome = "acquired"
except pidfile_guard.AnotherInstanceRunning:
    outcome = "refused"
# A5: the outcome, this process's own PID (what acquire_pidfile writes; the pid the test holds may be that of a
# venv launcher) and the guard module it ran, space-separated with the path last
report = " ".join([outcome, str(os.getpid()), pidfile_guard.__file__])
(signals / f"{name}.part").write_text(report, encoding="utf-8")
os.replace(signals / f"{name}.part", signals / f"outcome-{name}")
_wait_for("release")
'''

# A6 (F1): a vessel: the real ``_serve`` in a separate process, so its ``os._exit`` ends only that process. Its
# runtime, web server and browser are replaced; the runtime holds a real SQLite writer open from boot until its
# ``stop()`` returns, and ``stop()`` waits for the test's "release" (mode "clean") or raises (mode "failing").
_VESSEL = '''
import asyncio
import os
import sqlite3
import sys
import time
import webbrowser
from pathlib import Path

import uvicorn

import probos
import probos.api
from probos import __main__ as cli
from probos.config import SystemConfig

data_dir, mode, signals = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])


class _Runtime:
    def __init__(self):
        self.writer = sqlite3.connect(str(data_dir / "scheduled_tasks.db"))
        self.writer.execute("CREATE TABLE IF NOT EXISTS vessel_writes (n INTEGER)")
        self.writer.commit()

    async def stop(self):
        # its own PID (what acquire_pidfile wrote) and the probos it ran, written whole
        report = " ".join([str(os.getpid()), probos.__file__])
        (signals / "stopping.part").write_text(report, encoding="utf-8")
        os.replace(signals / "stopping.part", signals / "stopping")
        if mode == "failing":
            raise RuntimeError("the runtime did not stop")
        deadline = time.monotonic() + 30
        while not (signals / "release").exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        self.writer.close()


class _Server:
    def __init__(self, config):
        self.should_exit = False

    async def serve(self):
        return None  # the server ends at once, as Ctrl+C ends it


async def _boot(config_path, fresh, data_dir_arg, console, verbose=False):
    return _Runtime(), SystemConfig(), console


cli._boot_runtime = _boot
probos.api.create_app = lambda runtime: None
uvicorn.Config = lambda *args, **kwargs: None
uvicorn.Server = _Server
webbrowser.open = lambda *args, **kwargs: True
asyncio.run(cli._serve(data_dir=data_dir))
sys.exit(9)  # not reached: _serve ends in os._exit
'''


def _config(tmp_path: Path, *, archive_enabled: bool = True, archive_path: Path | None = None) -> SystemConfig:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    section = ArchiveConfig(enabled=archive_enabled, db_path=str(archive_path or tmp_path / "archive.db"))
    return SystemConfig(knowledge=KnowledgeConfig(repo_path=str(knowledge)), archive=section)


def _data_dir(tmp_path: Path, *, instance_id: str = _SHIP, name: str = "data") -> Path:
    """A stopped vessel's data directory: one file of each tier and, unless empty, the ship's instance id. ``name``
    is the directory's name under ``tmp_path`` (A7: R23 names it as Rich markup)."""
    data_dir = tmp_path / name
    (data_dir / "ontology").mkdir(parents=True)
    if instance_id:
        (data_dir / "ontology" / "instance_id").write_text(f"{instance_id}\n", encoding="utf-8")
    for name in ("events.db", "trust.db", "ward_room.db"):  # tiers 1, 2 and 3
        (data_dir / name).write_text(name, encoding="utf-8")
    return data_dir


def _records(data_dir: Path) -> RecordsStore:
    return RecordsStore(RecordsConfig(repo_path=str(data_dir / "ship-records"), auto_commit=False))


async def _write_records(data_dir: Path) -> None:
    """Two sources the reset promotes and one the read rule withholds, written as the vessel writes them."""
    writer = _records(data_dir)
    await writer.write_entry(
        author="system", path=_CONVERGENCE,
        content="## Convergence Report\n\nThree officers independently traced the coolant drift.",
        message="AD-551: Convergence report (coolant)", classification="ship", tags=["convergence", "ad-551"],
    )
    await writer.append_captains_log("Set course for the Briar Patch; coolant drift logged.")
    await writer.write_notebook(
        callsign="Chapel", topic_slug="private-coolant-c0ffee02", content="Claim: a private coolant note.",
        classification="private", extra_frontmatter=dict(_CLAIM),
    )


def _archive_store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _reset(monkeypatch: pytest.MonkeyPatch, config: SystemConfig, data_dir: Path, **flags: Any) -> Any:
    """The real ``_cmd_reset`` with the loader returning ``config``; returns what it returns."""
    monkeypatch.setenv("COLUMNS", "200")  # Rich wraps at 80 columns off a terminal; the assertions read lines
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    values: dict[str, Any] = {
        "yes": True, "soft": False, "full": False, "dry_run": False, "wipe_records": False, "config": None,
        "data_dir": data_dir, "skip_promotion": None,
    }
    values.update(flags)
    return cli._cmd_reset(_Namespace(**values))


def _erase(
    monkeypatch: pytest.MonkeyPatch, config: SystemConfig, entry_id: int, reason: str, *, yes: bool = True,
) -> Any:
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (config, None))
    return cli._cmd_archive(_Namespace(archive_cmd="erase", entry_id=entry_id, reason=reason, yes=yes, config=None))


def _nothing_deleted(data_dir: Path) -> bool:
    return all((data_dir / name).is_file() for name in ("events.db", "trust.db", "ward_room.db"))


async def _oracle_query(tmp_path: Path, text: str) -> list[Any]:
    later = _archive_store(tmp_path)  # the next generation's boot opens the same file
    await later.initialize()
    try:
        return await OracleService(archive_store=later).query(text, tiers=["archive"])
    finally:
        await later.close()


def _archive_store_at(path: Path) -> ArchiveStore:
    return ArchiveStore(str(path), connection_factory=default_factory)


async def _create_archive(path: Path) -> None:
    """A4 (F3): a real, initialised, empty Ship's Archive at ``path``: history a reset must not destroy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.unlink()  # the archive is configured to be one of the reset's own files
    store = _archive_store_at(path)
    await store.initialize()
    await store.close()


def _named_config_file(tmp_path: Path) -> Path:
    """A4 (F1): the YAML a Captain names with ``--config``: this test's archive and knowledge repo."""
    (tmp_path / "knowledge").mkdir(exist_ok=True)
    named = tmp_path / "named-config.yaml"
    named.write_text(
        f"archive:\n  enabled: true\n  db_path: '{(tmp_path / 'archive.db').as_posix()}'\n"
        f"knowledge:\n  repo_path: '{(tmp_path / 'knowledge').as_posix()}'\n",
        encoding="utf-8",
    )
    return named


def _only_what_the_captain_named(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The real loader for a named file. Selecting the fallback configuration or the platform data directory fails
    the test instead of reaching ``~/.probos`` or a real vessel. Returns the paths the command asked to load."""
    asked: list[Any] = []

    def _load(path: Any) -> Any:
        asked.append(path)
        assert path is not None, "the fallback configuration was selected"
        return _real_loader(path)

    def _no_default() -> Path:
        pytest.fail("the platform data directory was selected")  # A5: Failed, which no except Exception swallows

    monkeypatch.setattr(cli, "_load_config_with_fallback", _load)
    monkeypatch.setattr(cli, "_default_data_dir", _no_default)
    return asked


def _main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> Any:
    """The real ``main`` with ``argv``; returns its exit code."""
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # no repository .env into the worker
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: None)  # main sets one on Windows
    monkeypatch.setattr("sys.argv", ["probos", *argv])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    return exited.value.code


def _dead_process() -> _Popen[bytes]:
    """A process that has exited; its PID is what a vessel that died uncleanly leaves in its pidfile. The caller
    keeps the object until the test ends: its open handle stops Windows reusing the PID meanwhile (A5)."""
    finished = _Popen([sys.executable, "-c", "pass"])
    finished.wait(timeout=60)
    return finished


def _await_signal(path: Path) -> str:
    deadline = time.monotonic() + 30
    while not path.exists():
        assert time.monotonic() < deadline, f"no {path.name} within 30 seconds"
        time.sleep(0.01)
    return path.read_text(encoding="utf-8")


def _vessel(tmp_path: Path, data_dir: Path, mode: str) -> tuple[_Popen[bytes], Path]:
    """A6 (F1): ``_VESSEL`` on ``data_dir``, importing this tree's probos (A5's lesson); its output goes to
    ``vessel.log``. Returns the process and its signal directory."""
    signals = tmp_path / "signals"
    signals.mkdir()
    script = tmp_path / "vessel.py"
    script.write_text(_VESSEL, encoding="utf-8")
    env = {
        **os.environ, "PYTHONPATH": str(_SRC.parent), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "COLUMNS": "200", "PROBOS_SKIP_EPISODIC_HEALTH_CHECK": "1",  # no ChromaDB probe subprocess
    }
    argv = [sys.executable, str(script), str(data_dir), mode, str(signals)]
    with (tmp_path / "vessel.log").open("wb") as log:
        vessel = _Popen(argv, env=env, stdout=log, stderr=log)
    return vessel, signals


def _vessel_log(tmp_path: Path) -> str:
    return (tmp_path / "vessel.log").read_text(encoding="utf-8", errors="replace")


def _files(root: Path) -> set[Path]:
    """A6 (F1): every file under ``root``, relative to it."""
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def _refuse_locks(monkeypatch: pytest.MonkeyPatch, number: int) -> list[int]:
    """A6 (F2): the platform's lock call fails with errno ``number``, as M3's round-2 reviewer injected it. Returns
    the descriptor of every attempt."""
    attempts: list[int] = []

    def _refuse(fd: int, *_args: Any) -> None:
        attempts.append(fd)
        raise OSError(number, os.strerror(number))

    if sys.platform == "win32":
        import msvcrt

        monkeypatch.setattr(msvcrt, "locking", _refuse)
    else:
        import fcntl

        monkeypatch.setattr(fcntl, "flock", _refuse)
    return attempts


# --- R1, R2: the reset promotes before it deletes ----------------------------------------------------------------


def test_a_tier2_reset_archives_under_the_ship_it_closes_then_deletes_its_instance_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0

    archive = tmp_path / "archive.db"
    assert set(_rows(archive, "SELECT timeline_id, source_kind FROM archive")) == {
        (_SHIP, "convergence_report"), (_SHIP, "captains_log"),
    }
    assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE source_ref = ?", (_CONVERGENCE,)) == [(1,)]
    assert _rows(
        archive, "SELECT timeline_id, reset_tier, outcome, created_count, withheld_count FROM generations",
    ) == [(_SHIP, 2, "promoted", 2, 1)]
    assert not (data_dir / "ontology" / "instance_id").exists()  # then the tier loop ran
    assert not (data_dir / "trust.db").exists()
    assert (data_dir / "ship-records" / _CONVERGENCE).is_file()  # tier 2 keeps Ship's Records
    assert not (data_dir / "probos.pid").exists()  # the reset released its pidfile


def test_a_full_reset_archives_before_ship_records_are_wiped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    assert (data_dir / "ship-records" / _CONVERGENCE).is_file()  # premise

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 0

    assert not list((data_dir / "ship-records").rglob("*.md"))  # tier 3 wiped Ship's Records ...
    archive = tmp_path / "archive.db"
    assert _rows(archive, "SELECT timeline_id FROM archive WHERE source_ref = ?", (_CONVERGENCE,)) == [(_SHIP,)]
    assert _rows(archive, "SELECT reset_tier, outcome FROM generations") == [(3, "promoted")]  # ... after promoting


# --- R3, R4, R4b: failure, the audited skip, and a skip without a reason ---------------------------------------


def test_a_failed_promotion_refuses_the_reset_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    connection = sqlite3.connect(str(tmp_path / "archive.db"))
    connection.execute("PRAGMA user_version = 7")  # an archive this ProbOS does not read: initialize refuses it
    connection.commit()
    connection.close()

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 1

    assert "RuntimeError" in capsys.readouterr().out
    assert _rows(tmp_path / "archive.db", "PRAGMA user_version") == [(7,)]
    assert _nothing_deleted(data_dir)
    assert (data_dir / "ontology" / "instance_id").read_text(encoding="utf-8").strip() == _SHIP
    assert not (data_dir / "probos.pid").exists()  # released on the refusal too


def test_skip_promotion_records_the_generation_and_archives_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir, skip_promotion="  drill: nothing to keep ") == 0

    archive = tmp_path / "archive.db"
    assert _rows(archive, "SELECT COUNT(*) FROM archive") == [(0,)]
    assert _rows(archive, "SELECT timeline_id, reset_tier, outcome, reason FROM generations") == [
        (_SHIP, 2, "skipped", "drill: nothing to keep"),
    ]
    assert not (data_dir / "trust.db").exists()


@pytest.mark.parametrize(
    "flags",
    [{"skip_promotion": "   "}, {"skip_promotion": "x" * 501}, {"skip_promotion": "drill", "soft": True}],
    ids=["blank", "too-long", "soft"],
)
def test_a_skip_without_a_usable_reason_exits_2_and_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: dict[str, Any],
) -> None:
    data_dir = _data_dir(tmp_path)

    assert _reset(monkeypatch, _config(tmp_path), data_dir, **flags) == 2

    assert _nothing_deleted(data_dir)
    assert not (tmp_path / "archive.db").exists()
    assert not (data_dir / "probos.pid").exists()  # refused before the pidfile


# --- R5, R6: tier 1 and the dry run never write the archive ----------------------------------------------------


def test_a_soft_reset_never_opens_the_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir, soft=True) == 0

    assert not (data_dir / "events.db").exists()  # premise: the soft reset ran
    assert not (tmp_path / "archive.db").exists()
    assert (data_dir / "ontology" / "instance_id").is_file()


def test_a_dry_run_lists_the_plan_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    owner = str(os.getppid())
    (data_dir / "probos.pid").write_text(owner, encoding="utf-8")  # a live vessel: a dry run takes no pidfile

    assert _reset(monkeypatch, _config(tmp_path), data_dir, dry_run=True) == 0

    out = capsys.readouterr().out
    assert "2 to promote, 1 withheld" in out
    assert "+ captains-log/" in out
    assert not (tmp_path / "archive.db").exists()
    assert _nothing_deleted(data_dir) and (data_dir / "ontology" / "instance_id").is_file()
    assert (data_dir / "probos.pid").read_text(encoding="utf-8") == owner


# --- R7, R8, R9: a live vessel, the archive disabled, no instance id -------------------------------------------


@pytest.mark.parametrize("flags", [{"soft": True}, {}, {"full": True}], ids=["soft", "default", "full"])
def test_a_live_vessel_refuses_every_executing_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: dict[str, Any],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    owner = os.getppid()
    assert owner != os.getpid() and is_pid_alive(owner)  # premise: a live process that is not this one
    (data_dir / "probos.pid").write_text(str(owner), encoding="utf-8")

    assert _reset(monkeypatch, _config(tmp_path), data_dir, **flags) == 1

    assert _nothing_deleted(data_dir)
    assert (data_dir / "probos.pid").read_text(encoding="utf-8") == str(owner)  # the owner's pidfile is kept
    assert not (tmp_path / "archive.db").exists()


def test_with_the_archive_disabled_the_reset_proceeds_and_erase_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path, archive_enabled=False)

    assert _reset(monkeypatch, config, data_dir) == 0

    assert "Ship's Archive is disabled" in capsys.readouterr().out
    assert not (data_dir / "trust.db").exists()
    assert not (tmp_path / "archive.db").exists()
    assert _erase(monkeypatch, config, 1, "superseded") == 2


@pytest.mark.parametrize("with_records", [True, False], ids=["with-records", "nothing-to-promote"])
def test_without_an_instance_id_records_to_promote_refuse_the_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_records: bool,
) -> None:
    data_dir = _data_dir(tmp_path, instance_id="")
    if with_records:
        asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir) == (1 if with_records else 0)

    assert (data_dir / "trust.db").is_file() is with_records
    assert not (tmp_path / "archive.db").exists()  # nothing attributed, and no generation recorded


# --- R10, R10b: the Captain's erasure ----------------------------------------------------------------------------


def test_the_captain_erases_an_entry_and_the_next_reset_does_not_bring_it_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir) == 0
    archive = tmp_path / "archive.db"
    (entry_id,) = _rows(archive, "SELECT id FROM archive WHERE source_ref = ?", (_CONVERGENCE,))[0]

    assert _erase(monkeypatch, config, entry_id, "superseded by the Captain") == 0

    assert "will not be promoted again" in capsys.readouterr().out
    assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE id = ?", (entry_id,)) == [(0,)]
    assert _rows(archive, "SELECT entry_id, timeline_id, source_kind, source_ref, reason FROM archive_erasures") == [
        (entry_id, _SHIP, "convergence_report", _CONVERGENCE, "superseded by the Captain"),
    ]

    # The next crew's reset reads the same Ship's Records (tier 2 kept them) and does not archive it again.
    (data_dir / "ontology" / "instance_id").write_text(_NEXT_SHIP, encoding="utf-8")
    assert _reset(monkeypatch, config, data_dir) == 0
    assert _rows(archive, "SELECT COUNT(*) FROM archive WHERE source_ref = ?", (_CONVERGENCE,)) == [(0,)]
    assert _rows(
        archive, "SELECT timeline_id, created_count, present_count, erased_count FROM generations ORDER BY id",
    ) == [(_SHIP, 2, 0, 0), (_NEXT_SHIP, 0, 1, 1)]


@pytest.mark.parametrize(
    ("entry_id", "reason", "answer", "code"),
    [(999, "superseded", "y", 1), (0, "superseded", "y", 2), (None, "   ", "y", 2), (None, "superseded", "n", 0)],
    ids=["no-such-entry", "zero-id", "blank-reason", "declined"],
)
def test_an_erasure_that_cannot_or_should_not_happen_erases_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_id: int | None, reason: str, answer: str, code: int,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    config = _config(tmp_path)
    assert _reset(monkeypatch, config, data_dir) == 0
    archive = tmp_path / "archive.db"
    (existing,) = _rows(archive, "SELECT id FROM archive WHERE source_ref = ?", (_CONVERGENCE,))[0]
    monkeypatch.setattr("builtins.input", lambda _prompt: answer)

    assert _erase(monkeypatch, config, existing if entry_id is None else entry_id, reason, yes=False) == code

    assert _rows(archive, "SELECT COUNT(*) FROM archive") == [(2,)]
    assert _rows(archive, "SELECT COUNT(*) FROM archive_erasures") == [(0,)]


# --- R11, R12, R13: the census, the chain, the parser ------------------------------------------------------------


def test_only_the_cli_erases_an_entry_or_closes_a_generation() -> None:
    """``erase_entry`` and ``record_generation`` are named in ``src`` (called, referenced or spelled as a string)
    by ``__main__.py`` alone, beside the store's definitions: no agent or service erases or closes a generation."""
    naming: dict[str, set[str]] = {"erase_entry": set(), "record_generation": set()}
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in naming:
                naming[node.attr].add(path.relative_to(_SRC).as_posix())
            elif isinstance(node, ast.Constant) and type(node.value) is str and node.value in naming:
                naming[node.value].add(path.relative_to(_SRC).as_posix())
    assert naming == {"erase_entry": {"__main__.py"}, "record_generation": {"__main__.py"}}


def test_a_later_crews_oracle_reads_what_the_reset_archived_under_the_old_timeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))

    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=True) == 0

    results = asyncio.run(_oracle_query(tmp_path, "coolant drift"))
    assert results, "premise: the query reaches the archive tier"
    assert {result.metadata["timeline_id"] for result in results} == {_SHIP}
    assert any("coolant drift" in result.content for result in results)


@pytest.mark.parametrize(
    ("argv", "command", "attribute", "value"),
    [
        (["reset", "--yes", "--skip-promotion", "drill"], "_cmd_reset", "skip_promotion", "drill"),
        (["archive", "erase", "7", "--reason", "superseded", "--yes"], "_cmd_archive", "entry_id", 7),
    ],
    ids=["reset", "archive-erase"],
)
def test_main_parses_the_new_arguments_and_exits_with_the_command_code(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], command: str, attribute: str, value: Any,
) -> None:
    seen: list[_Namespace] = []

    def _command(args: _Namespace) -> int:
        seen.append(args)
        return 3

    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # no repository .env into the worker
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: None)  # main sets one on Windows
    monkeypatch.setattr(cli, command, _command)
    monkeypatch.setattr("sys.argv", ["probos", *argv])

    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert exited.value.code == 3
    assert [getattr(args, attribute) for args in seen] == [value]


# --- R4c, R14 to R17 (Amendment A4) ----------------------------------------------------------------------------


def test_a_bad_skip_reason_exits_2_before_the_configuration_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F4: the reason is checked before the configuration loads, so a malformed configuration cannot turn exit 2
    into a traceback."""
    data_dir = _data_dir(tmp_path)

    def _unreadable(_path: Any) -> Any:
        pytest.fail("the configuration was read before --skip-promotion was checked")  # A5: not swallowable

    monkeypatch.setattr(cli, "_load_config_with_fallback", _unreadable)
    args = _Namespace(
        yes=True, soft=False, full=False, dry_run=False, wipe_records=False, config=None, data_dir=data_dir,
        skip_promotion="   ",
    )

    assert cli._cmd_reset(args) == 2

    assert _nothing_deleted(data_dir)


@pytest.mark.parametrize("leading", [True, False], ids=["config-first", "config-last"])
def test_erase_uses_the_configuration_the_captain_named_in_either_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leading: bool,
) -> None:
    """F1: a ``--config`` before ``archive erase`` was replaced by the subcommand's own default, so the erasure ran
    on the fallback configuration's archive."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0
    archive = tmp_path / "archive.db"
    (entry_id,) = _rows(archive, "SELECT id FROM archive WHERE source_ref = ?", (_CONVERGENCE,))[0]
    named = _named_config_file(tmp_path)
    asked = _only_what_the_captain_named(monkeypatch)
    erase = ["archive", "erase", str(entry_id), "--reason", "superseded", "--yes"]

    code = _main(monkeypatch, ["--config", str(named), *erase] if leading else [*erase, "--config", str(named)])

    assert (code, asked) == (0, [named])
    assert _rows(archive, "SELECT id FROM archive WHERE id = ?", (entry_id,)) == []


@pytest.mark.parametrize("leading", [True, False], ids=["options-first", "options-last"])
def test_reset_uses_the_configuration_and_data_directory_the_captain_named_in_either_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leading: bool,
) -> None:
    """F1: ``--config`` and ``--data-dir`` before ``reset`` were replaced by the subcommand's defaults, so the
    reset read the fallback configuration and reset the platform data directory."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    named = _named_config_file(tmp_path)
    asked = _only_what_the_captain_named(monkeypatch)
    options = ["--config", str(named), "--data-dir", str(data_dir)]

    code = _main(monkeypatch, [*options, "reset", "--yes"] if leading else ["reset", "--yes", *options])

    assert (code, asked) == (0, [named])
    assert not (data_dir / "trust.db").exists()
    assert _rows(tmp_path / "archive.db", "SELECT timeline_id FROM generations") == [(_SHIP,)]


def test_two_acquirers_of_a_stale_pidfile_never_both_hold_it(tmp_path: Path) -> None:
    """F2: two real processes find the same stale pidfile, and the first takes a second to judge it dead. Before A4
    the second replaced the stale file meanwhile, the first then removed that fresh file by name and created its
    own, and both held the guard. Now the second waits for the takeover lock, finds the first alive, and refuses."""
    data_dir = tmp_path / "data"
    signals = tmp_path / "signals"
    data_dir.mkdir()
    signals.mkdir()
    script = tmp_path / "acquirer.py"
    script.write_text(_ACQUIRER, encoding="utf-8")
    stale = _dead_process()  # held to the end of the test (A5)
    (data_dir / "probos.pid").write_text(str(stale.pid), encoding="utf-8")  # a vessel that died uncleanly
    env = {**os.environ, "PYTHONPATH": str(_SRC.parent)}  # A5: the children import the probos under test
    acquirers = {
        name: _Popen([sys.executable, str(script), str(data_dir), name, str(signals)], env=env)
        for name in ("slow", "fast")
    }
    try:
        for name in acquirers:
            _await_signal(signals / f"ready-{name}")
        (signals / "go-slow").write_text("", encoding="utf-8")
        time.sleep(0.3)  # the slow acquirer is judging the stale PID
        (signals / "go-fast").write_text("", encoding="utf-8")
        reports = {name: _await_signal(signals / f"outcome-{name}").split(" ", 2) for name in acquirers}
        holder = (data_dir / "probos.pid").read_text(encoding="utf-8")
    finally:
        (signals / "release").write_text("", encoding="utf-8")
        for process in acquirers.values():
            process.wait(timeout=60)

    # A5: premise first (the AD-1137 precedent): both children ran this tree's guard, not another install's.
    assert {Path(module).resolve() for _outcome, _pid, module in reports.values()} == {_SRC / "pidfile_guard.py"}
    # The stagger makes the pre-A4 race show (both acquire). Which acquirer wins is the scheduler's, so the test
    # asserts that exactly one does and that the pidfile names it, by the PID the winner itself reported: on a
    # Windows venv the pid the test's handle reports is the launcher's, not the interpreter's.
    assert sorted(outcome for outcome, _pid, _module in reports.values()) == ["acquired", "refused"]
    (winner,) = [pid for outcome, pid, _module in reports.values() if outcome == "acquired"]
    assert holder == winner


@pytest.mark.parametrize(
    ("place", "flags", "enabled", "code"),
    [
        (("semantic", "archive.db"), {}, True, 1),
        (("ontology", "..", "semantic", "archive.db"), {}, True, 1),
        (("ship-records", "archive.db"), {"full": True}, True, 1),
        (("semantic", "archive.db"), {"dry_run": True}, True, 1),
        (("checkpoints", "archive.db"), {"soft": True}, True, 1),
        (("trust.db",), {}, True, 1),
        (("ship-records", "archive.db"), {}, True, 0),
        ((), {}, True, 0),
        (("semantic", "archive.db"), {}, False, 0),
    ],
    ids=[
        "semantic", "dotdot", "ship-records-full", "dry-run", "checkpoints-soft", "target-file",
        "ship-records-default", "outside", "disabled",
    ],
)
def test_an_archive_inside_what_the_reset_deletes_refuses_the_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    place: tuple[str, ...], flags: dict[str, Any], enabled: bool, code: int,
) -> None:
    """F3: with ``archive.db_path`` inside a reset target, the reset promoted into the archive, then deleted it with
    its tier. It now refuses first, at every tier and in a dry run, with nothing touched. A target of a higher tier,
    a path outside the data directory and a disabled archive (D13) do not refuse."""
    data_dir = _data_dir(tmp_path)
    asyncio.run(_write_records(data_dir))
    history = data_dir.joinpath(*place) if place else tmp_path / "archive.db"
    asyncio.run(_create_archive(history))
    config = _config(tmp_path, archive_enabled=enabled, archive_path=history)

    assert _reset(monkeypatch, config, data_dir, **flags) == code

    if code == 1:
        assert "the Ship's Archive is inside what this reset deletes" in capsys.readouterr().out
        assert _nothing_deleted(data_dir) and history.is_file()
        assert _rows(history, "SELECT id FROM archive") == []  # refused before the promotion
        assert not (data_dir / "probos.pid").exists()  # and before the pidfile
    else:
        assert not (data_dir / "trust.db").exists()  # premise: the reset ran
        if enabled:
            assert len(_rows(history, "SELECT id FROM archive")) == 2  # promoted, and kept


# --- R18 to R21 (Amendment A6) ---------------------------------------------------------------------------------


def test_a_stopping_vessel_keeps_its_pidfile_until_its_writers_have_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A6 (F1): ``_serve`` removed its pidfile before it stopped anything, so a reset run while the vessel was still
    closing its databases took the guard and deleted beside an open writer. The real ``_serve`` runs in a child
    whose runtime holds a real SQLite writer open until the test releases its ``stop()``."""
    data_dir = _data_dir(tmp_path)
    pidfile = data_dir / "probos.pid"
    vessel, signals = _vessel(tmp_path, data_dir, "clean")
    try:
        vessel_pid, module = _await_signal(signals / "stopping").split(" ", 1)
        held = pidfile.read_text(encoding="utf-8") if pidfile.is_file() else None
        before = _files(data_dir)
        code = _reset(monkeypatch, _config(tmp_path), data_dir)
        after = _files(data_dir)
    finally:
        (signals / "release").write_text("", encoding="utf-8")
        vessel.wait(timeout=60)

    assert Path(module).resolve() == _SRC / "__init__.py"  # premise: the vessel ran this tree's probos
    assert held == vessel_pid  # the pidfile names the vessel while runtime.stop() runs
    assert code == 1 and "stop the vessel first" in capsys.readouterr().out
    assert before <= after  # every file the stopping vessel had is still there
    assert vessel.returncode == 0, _vessel_log(tmp_path)
    assert not pidfile.exists()  # released once the runtime had stopped


def test_a_vessel_whose_runtime_fails_to_stop_leaves_its_pidfile_for_the_stale_pid_recovery(tmp_path: Path) -> None:
    """A6 (F1): a ``runtime.stop()`` that fails (or times out) may leave a writer open, so ``_serve`` keeps the
    pidfile and the process ends; the next acquirer finds the dead PID and recovers it (AD-816's stale case)."""
    data_dir = _data_dir(tmp_path)
    vessel, signals = _vessel(tmp_path, data_dir, "failing")
    try:
        vessel_pid, module = _await_signal(signals / "stopping").split(" ", 1)
    finally:
        (signals / "release").write_text("", encoding="utf-8")
        vessel.wait(timeout=60)

    assert Path(module).resolve() == _SRC / "__init__.py"  # premise: the vessel ran this tree's probos
    assert vessel.returncode == 0, _vessel_log(tmp_path)  # _serve still ends in os._exit(0)
    assert (data_dir / "probos.pid").read_text(encoding="utf-8") == vessel_pid  # kept for the stale-PID recovery


@pytest.mark.parametrize(
    ("number", "contention"),
    [
        (errno.EACCES, True), (errno.EAGAIN, True), (errno.EWOULDBLOCK, True),
        (errno.ENOSYS, False), (errno.ENOLCK, False), (errno.EOPNOTSUPP, False), (errno.EINVAL, False),
    ],
    ids=["EACCES", "EAGAIN", "EWOULDBLOCK", "ENOSYS", "ENOLCK", "EOPNOTSUPP", "EINVAL"],
)
def test_the_takeover_lock_tells_contention_from_a_filesystem_that_cannot_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, number: int, contention: bool,
) -> None:
    """A6 (F2): every error from the lock call counted as contention, so a filesystem without file locks waited
    10 s and reported "Another ProbOS instance (PID -1)", its cause lost. Contention still waits and refuses as a
    live owner does; any other error refuses at once with the lock file and the original error."""
    attempts = _refuse_locks(monkeypatch, number)
    monkeypatch.setattr("probos.pidfile_guard._TAKEOVER_WAIT_S", 0.2)
    lock_path = tmp_path / "probos.pid.lock"

    with pytest.raises((AnotherInstanceRunning, PidfileLockUnavailable)) as refused:
        acquire_pidfile(tmp_path)

    if contention:
        assert refused.type is AnotherInstanceRunning and refused.value.pidfile == lock_path
        assert len(attempts) > 1  # it waited for the holder
    else:
        assert refused.type is PidfileLockUnavailable and refused.value.lock_path == lock_path
        assert refused.value.__cause__ is refused.value.error and refused.value.error.errno == number
        assert str(lock_path) in str(refused.value) and str(refused.value.error) in str(refused.value)
        assert len(attempts) == 1  # no wait: waiting cannot cure it
    assert not (tmp_path / "probos.pid").exists()


@pytest.mark.parametrize("command", ["serve", "reset"])
def test_a_filesystem_that_cannot_lock_refuses_serve_and_reset_with_its_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str,
) -> None:
    """A6 (F2): ``probos serve`` (exit 2) and ``probos reset`` (exit 1) refuse a data directory whose filesystem
    cannot lock, naming the lock file and the error instead of a PID -1 instance to stop. Nothing is touched."""
    data_dir = _data_dir(tmp_path)
    _refuse_locks(monkeypatch, errno.ENOSYS)
    monkeypatch.setattr("probos.pidfile_guard._TAKEOVER_WAIT_S", 0.2)  # a mutant that waits stays fast
    monkeypatch.setenv("COLUMNS", "200")

    if command == "serve":
        with pytest.raises(SystemExit) as exited:
            asyncio.run(cli._serve(data_dir=data_dir))
        code = exited.value.code
    else:
        code = _reset(monkeypatch, _config(tmp_path), data_dir)

    out = capsys.readouterr().out
    assert code == (2 if command == "serve" else 1)
    assert str(data_dir / "probos.pid.lock") in out and os.strerror(errno.ENOSYS) in out
    assert "PID -1" not in out and "stop the vessel first" not in out
    assert _nothing_deleted(data_dir) and not (data_dir / "probos.pid").exists()


# --- R22, R23 (Amendment A7) -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        b"\xff\xfe\xfa",
        "\u00b2".encode("utf-8"),
        b"99999999999999999999",
        b"9" * 4301,
        b"0" * 5000 + b"1",
        b"not-a-pid",
        b"",
    ],
    ids=[
        "not-utf8",
        "superscript-two",
        "beyond-any-pid",
        "over-int-limit",
        "over-bound-leading-zeros",
        "ascii-garbage",
        "empty",
    ],
)
def test_a_malformed_pidfile_is_garbage_every_guarded_command_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes,
) -> None:
    """A7 (F3): AD-816 recovered only from ASCII garbage. Content that is not UTF-8 raised a decoding error, a
    superscript two passed ``isdigit`` and failed ``int``, and a number beyond any PID went to ``is_pid_alive``, so
    the acquire (``serve``, ``reset``) and the probe (``backup-reclaim --force``, ``rebuild-episodic``) failed on
    every retry while the marker stayed. A8 (F3): a digit run longer than CPython's integer-string limit (4,300)
    still raised from ``int``, with or without leading zeros. Each is garbage now, as ASCII garbage and an empty
    file (the controls) already were: the probe ignores it, the acquire replaces it, and a tier 1 reset runs and
    releases."""
    data_dir = _data_dir(tmp_path)
    pidfile = data_dir / "probos.pid"
    plain = tmp_path / "plain.pid"
    plain.write_bytes(b"12345\n")
    assert _read_pid_from(plain) == 12345  # control: a plain PID is still read
    pidfile.write_bytes(content)

    assert _read_pid_from(pidfile) is None
    assert_no_other_instance(data_dir)  # the probe neither refuses nor raises
    assert acquire_pidfile(data_dir) == pidfile  # the acquire replaces the marker
    assert pidfile.read_text(encoding="utf-8") == str(os.getpid())

    pidfile.write_bytes(content)  # the reset, the new consumer, end to end
    assert _reset(monkeypatch, _config(tmp_path), data_dir, soft=True) == 0
    assert not (data_dir / "events.db").exists()  # premise: the tier 1 reset ran
    assert not pidfile.exists()  # released by path


@pytest.mark.parametrize("command", ["serve", "backup-reclaim", "rebuild-episodic", "reset"])
def test_a_refusal_prints_the_data_directory_as_it_is_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str,
) -> None:
    """A7 (F4): ``serve``, ``backup-reclaim --force`` and ``rebuild-episodic`` printed the guard's refusal as Rich
    markup, so a legal directory named ``[blue]data`` was reported as another path: after a backslash Rich reads an
    escaped bracket and drops the separator, after a slash it reads a style tag and drops it. The refusal itself
    held. On POSIX the name also holds an emoji code, which Rich would replace. ``reset`` already escaped: the
    control."""
    name = "[blue]data" if sys.platform == "win32" else "[blue]:smile:data"  # a Windows name cannot hold ":"
    data_dir = _data_dir(tmp_path, name=name)
    pidfile = data_dir / "probos.pid"
    owner = os.getppid()
    assert owner != os.getpid() and is_pid_alive(owner)  # premise: a live process that is not this one
    assert data_dir == data_dir.resolve()  # premise: the commands that resolve the directory print this same path
    pidfile.write_text(str(owner), encoding="utf-8")
    monkeypatch.setenv("COLUMNS", "200")  # Rich wraps at 80 columns off a terminal; the assertions read lines

    if command == "serve":
        with pytest.raises(SystemExit) as exited:
            asyncio.run(cli._serve(data_dir=data_dir))
        code, expected = exited.value.code, 2
    elif command == "backup-reclaim":
        (tmp_path / "backups").mkdir()
        args = _Namespace(backup_root=str(tmp_path / "backups"), force=True, data_dir=data_dir)
        code, expected = cli._cmd_backup_reclaim(args), 2
    elif command == "rebuild-episodic":
        code, expected = cli._cmd_rebuild_episodic(_Namespace(data_dir=data_dir)), 2
    else:
        code, expected = _reset(monkeypatch, _config(tmp_path), data_dir, soft=True), 1

    out = capsys.readouterr().out
    assert code == expected and "Another ProbOS instance" in out  # premise: the guard refused
    assert str(pidfile) in out  # the pidfile's path exactly as it is on disk
    assert pidfile.read_text(encoding="utf-8") == str(owner) and _nothing_deleted(data_dir)


# --- R24, R25 (Amendment A8) -----------------------------------------------------------------------------------


@pytest.mark.parametrize("width", [64, 65], ids=["at-bound", "beyond-bound"])
def test_a_marker_is_read_up_to_its_bound_and_is_garbage_beyond_it(tmp_path: Path, width: int) -> None:
    """A8 (F3): the reader reads at most ``_MAX_MARKER_BYTES`` (64) of a marker and converts only that, so ``int``
    never meets CPython's 4,300-digit limit. A live owner's PID zero-padded to exactly 64 bytes still keeps the probe
    and the acquire out (leading zeros are allowed); one byte more is garbage, which the probe ignores and the acquire
    replaces. On M3 the 65-byte marker is read as the owner."""
    data_dir = _data_dir(tmp_path)
    pidfile = data_dir / "probos.pid"
    owner = os.getppid()
    assert owner != os.getpid() and is_pid_alive(owner)  # premise: a live process that is not this one
    marker = str(owner).encode("ascii").rjust(width, b"0")
    assert len(marker) == width and marker.startswith(b"0")  # premise: zero-padded to the width
    pidfile.write_bytes(marker)

    if width == 64:
        assert _read_pid_from(pidfile) == owner
        with pytest.raises(AnotherInstanceRunning) as probed:
            assert_no_other_instance(data_dir)
        with pytest.raises(AnotherInstanceRunning) as acquired:
            acquire_pidfile(data_dir)
        assert probed.value.pid == owner and acquired.value.pid == owner
        assert pidfile.read_bytes() == marker  # the owner's marker is left as it was
    else:
        assert _read_pid_from(pidfile) is None
        assert_no_other_instance(data_dir)  # the probe ignores it
        assert acquire_pidfile(data_dir) == pidfile  # the acquire replaces it
        assert pidfile.read_text(encoding="utf-8") == str(os.getpid())


@pytest.mark.skipif(sys.platform == "win32", reason="a FIFO is POSIX-only")
def test_a_pidfile_that_is_a_fifo_is_garbage_and_nothing_blocks_on_it(tmp_path: Path) -> None:
    """A8 (F3): opening a FIFO for reading blocks until a writer appears, so on M3 a FIFO named ``probos.pid`` hung
    the reader, and with it the probe and the acquire of every guarded command. Only a regular file is read now: the
    FIFO is garbage, the probe ignores it and the acquire replaces it. The calls run on a thread with a bound, so a
    regression fails instead of hanging the suite."""
    data_dir = _data_dir(tmp_path)
    pidfile = data_dir / "probos.pid"
    os.mkfifo(pidfile)
    results: dict[str, Any] = {}

    def _guarded() -> None:
        results["read"] = _read_pid_from(pidfile)
        assert_no_other_instance(data_dir)
        results["acquired"] = acquire_pidfile(data_dir)

    worker = _Thread(target=_guarded, daemon=True)
    worker.start()
    worker.join(timeout=10)
    if worker.is_alive():
        os.close(os.open(pidfile, os.O_WRONLY | os.O_NONBLOCK))  # a writer releases the blocked open
        worker.join(timeout=10)
        pytest.fail("the guard blocked on a FIFO pidfile")
    assert results == {"read": None, "acquired": pidfile}
    assert pidfile.is_file() and pidfile.read_text(encoding="utf-8") == str(os.getpid())
