"""BF-906 (#1594) - the ``crew_enrollment`` doctor check and the read-only open it reads through (milestone M3).

``probos doctor`` must say, without asking the vessel, whether every crew member holds an ACM lifecycle row
and a commissioning (or skills), and it must never change what it reads. These tests build the three stores
the check reads (identity.db, acm.db, skills.db) with the real store classes on ``tmp_path`` and run the real
check against them, so the SQL the check holds is tested against the schemas the stores create, not against a
copy. Where a test needs a state no honest API produces (a pre-BF-906 ACM file, a transferred-in slot, a
locked store) it edits the file with ``sqlite3`` and says so. Nothing here reads or writes a live data
directory, sleeps, or waits without a bound.

- D1   no identity store: OK, and nothing is created
- D2   crew but no ACM store: FAIL, listing the ids
- D3   a pre-BF-906 ACM file (no ``commissioning_records``): skilled agents pass
- D4   a store held by ``BEGIN EXCLUSIVE``: WARN, within the busy timeout (amended by A1)
- D5   a decommissioned agent needs no commissioning
- D6   registered once, and the AD-1327 order holds
- D7   a transferred-in slot is crew
- D8   the adapter's ``read_only`` open reads and refuses writes
- D9   the ``read_only`` open never creates a missing file
- D10  the default open is unchanged (the one test here that also passes before BF-906: a boundary)
- D11  the doctor opens every store read-only
- D12  a WAL store opened read-only never changes the database file (A2)

The check module is imported inside each test that needs it, so while it does not exist each test fails on
its own instead of the whole module failing to collect.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from probos.acm import AgentCapitalService
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.identity import AgentIdentityRegistry
from probos.skill_framework import AgentSkillService, SkillCategory, SkillDefinition, SkillRegistry
from probos.storage.sqlite_factory import default_factory

_INSTANCE = "bf906-inst"
_VESSEL = "BF906 Test Vessel"
_NEVER = "Never commissioned"
_NO_LIFECYCLE = "No ACM lifecycle record"


# ---------------------------------------------------------------------------
# Helpers: the check under test, and real stores on tmp_path
# ---------------------------------------------------------------------------


def _check_module() -> Any:
    """The doctor module, imported when a test needs it (a missing module fails that test, not the collection)."""
    from probos.doctor.checks import crew_enrollment_check

    return crew_enrollment_check


def _ctx(data_dir: Path) -> DoctorContext:
    return DoctorContext(config=None, home_dir=data_dir.parent, data_dir=data_dir, config_path=None)


async def _run(data_dir: Path) -> CheckResult:
    return await _check_module()._CrewEnrollmentCheck().run(_ctx(data_dir))


def _listed(result: CheckResult, heading: str) -> list[str]:
    """The ids the remediation lists under ``heading`` (``none`` is the empty list)."""
    prefix = f"{heading}: "
    for line in result.remediation.splitlines():
        if line.startswith(prefix):
            names = line.removeprefix(prefix)
            return [] if names == "none" else names.split(", ")
    raise AssertionError(f"no {heading!r} line in the remediation {result.remediation!r}")


def _names(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir()}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _seed_identity(data_dir: Path, slots: Sequence[str]) -> None:
    """A real identity.db: one native birth certificate for each slot (the slot id is the agent id)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    registry = AgentIdentityRegistry(data_dir=data_dir)
    await registry.start(instance_id=_INSTANCE, vessel_name=_VESSEL, version="v0")
    try:
        for slot in slots:
            await registry.issue_birth_certificate(
                agent_type="scout", callsign=f"Scout {slot}", instance_id=_INSTANCE, vessel_name=_VESSEL,
                department="science", post_id="scout_officer", baseline_version="v0", slot_id=slot,
            )
    finally:
        await registry.stop()


def _seed_transferred_in_slot(data_dir: Path, slot_id: str) -> None:
    """A slot held by a transferred-in agent: the columns ``import_transfer_certificate`` writes, and the mapping.

    The signed import needs a second ship's chain, so the foreign row is inserted into the store the real
    ``AgentIdentityRegistry`` already created.
    """
    agent_uuid = f"foreign-uuid-{slot_id}"
    with contextlib.closing(sqlite3.connect(data_dir / "identity.db")) as conn:
        conn.execute(
            "INSERT INTO foreign_birth_certificates (agent_uuid, did, agent_type, callsign, instance_id, "
            "vessel_name, birth_timestamp, department, post_id, baseline_version, certificate_hash, "
            "certificate_vc_json, origin_ship_did, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent_uuid, f"did:probos:other-inst:{agent_uuid}", "scout", "Visitor", "other-inst", "Other Ship",
                1.0, "science", "scout_officer", "v0", f"hash-{agent_uuid}", "{}", "did:probos:other-ship", 2.0,
            ),
        )
        conn.execute("INSERT OR REPLACE INTO slot_mappings (slot_id, agent_uuid) VALUES (?, ?)", (slot_id, agent_uuid))
        conn.commit()


async def _seed_acm(
    data_dir: Path, *, onboarded: Sequence[str], commissioned: Sequence[str] = (), decommissioned: Sequence[str] = (),
) -> None:
    """A real acm.db: a lifecycle row for each onboarded agent, a commissioning record for each commissioned one."""
    data_dir.mkdir(parents=True, exist_ok=True)
    acm = AgentCapitalService(data_dir=data_dir)
    await acm.start()
    try:
        for agent_id in onboarded:
            await acm.onboard(agent_id, "scout", "science", "science")
        for agent_id in commissioned:
            recorded = await acm.record_commissioning(
                agent_id=agent_id, agent_type="scout", source="birth", role_template=None,
                skills=("doctor_probe",), tools=(),
            )
            assert recorded is True, f"seed: {agent_id} already had a commissioning record"
        for agent_id in decommissioned:
            await acm.decommission(agent_id, reason="BF-906 doctor seed", initiated_by="system")
    finally:
        await acm.stop()


async def _seed_skills(data_dir: Path, registry_dir: Path, agent_ids: Sequence[str]) -> None:
    """A real skills.db: one acquired skill for each agent (the skill registry lives apart, off the data dir)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry = SkillRegistry(db_path=str(registry_dir / "registry.db"))
    await registry.start()
    try:
        await registry.register_skill(SkillDefinition(
            skill_id="doctor_probe", name="Doctor Probe", category=SkillCategory.ROLE,
            description="BF-906 doctor seed", domain="*",
        ))
        service = AgentSkillService(db_path=str(data_dir / "skills.db"), registry=registry)
        await service.start()
        try:
            for agent_id in agent_ids:
                await service.acquire_skill(agent_id, "doctor_probe")
        finally:
            await service.stop()
    finally:
        await registry.stop()


def _seed_plain_db(path: Path, *, wal: bool = False) -> None:
    """A one-table database holding the row 42, closed cleanly (optionally in WAL mode)."""
    with contextlib.closing(sqlite3.connect(path)) as conn:
        if wal:
            assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        conn.commit()


# ---------------------------------------------------------------------------
# D1 - D7: the check, against real stores
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("data_dir_exists", [True, False], ids=["empty_data_dir", "missing_data_dir"])
async def test_no_identity_store_is_ok_and_creates_nothing(tmp_path: Path, data_dir_exists: bool) -> None:
    """D1: no identity.db means no crew yet: OK, and the check creates no file (nor the directory)."""
    data_dir = tmp_path / "data"
    if data_dir_exists:
        data_dir.mkdir()

    result = await _run(data_dir)

    assert result.outcome is CheckOutcome.OK
    assert result.message == "Crew enrollment: no crew yet (identity store not initialized)"
    assert data_dir.exists() is data_dir_exists
    if data_dir_exists:
        assert list(data_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_identity_store_without_birth_certificates_is_ok_and_says_so(tmp_path: Path) -> None:
    """HA17: an identity.db that exists but holds no birth certificate is OK, with its own message (not 'all 0 crew')."""
    data_dir = tmp_path / "data"
    await _seed_identity(data_dir, [])
    assert (data_dir / "identity.db").exists()  # premise: the identity store exists and is empty

    result = await _run(data_dir)

    assert result.outcome is CheckOutcome.OK
    assert "no crew have birth certificates yet" in result.message


@pytest.mark.asyncio
async def test_crew_without_an_acm_store_fails_listing_every_id(tmp_path: Path) -> None:
    """D2: crew hold birth certificates but acm.db was never made: every one is missing a lifecycle row."""
    data_dir = tmp_path / "data"
    await _seed_identity(data_dir, ["crew-b", "crew-a"])
    assert not (data_dir / "acm.db").exists()  # premise: the ACM store was never made

    result = await _run(data_dir)

    assert result.outcome is CheckOutcome.FAIL
    assert result.message == "Crew enrollment: 2 of 2 crew fail the BF-906 invariant"
    assert _listed(result, _NO_LIFECYCLE) == ["crew-a", "crew-b"]
    assert _listed(result, _NEVER) == ["crew-a", "crew-b"]
    assert not (data_dir / "acm.db").exists()  # reading a store that is not there does not make it


@pytest.mark.asyncio
async def test_pre_bf906_acm_store_without_commissioning_records_passes_skilled_agents(tmp_path: Path) -> None:
    """D3: with no ``commissioning_records`` table the agents are judged by their skills, and by nothing less."""
    data_dir = tmp_path / "data"
    await _seed_identity(data_dir, ["crew-a", "crew-b"])
    await _seed_acm(data_dir, onboarded=["crew-a", "crew-b"])
    await _seed_skills(data_dir, tmp_path / "skill-registry", ["crew-a", "crew-b"])
    with contextlib.closing(sqlite3.connect(data_dir / "acm.db")) as conn:  # make it a pre-BF-906 file
        conn.execute("DROP TABLE commissioning_records")
        conn.commit()
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "lifecycle" in tables and "commissioning_records" not in tables  # premise

    skilled = await _run(data_dir)

    assert skilled.outcome is CheckOutcome.OK, skilled
    assert skilled.message == "Crew enrollment: all 2 crew have an ACM lifecycle record and a commissioning"

    # Control: the OK came from the skills. Take crew-a's away and the same file is a failure for crew-a alone.
    with contextlib.closing(sqlite3.connect(data_dir / "skills.db")) as conn:
        assert conn.execute("DELETE FROM agent_skills WHERE agent_id = ?", ("crew-a",)).rowcount == 1
        conn.commit()

    unskilled = await _run(data_dir)

    assert unskilled.outcome is CheckOutcome.FAIL
    assert unskilled.message == "Crew enrollment: 1 of 2 crew fail the BF-906 invariant"
    assert _listed(unskilled, _NEVER) == ["crew-a"]
    assert _listed(unskilled, _NO_LIFECYCLE) == []


@pytest.mark.asyncio
async def test_acm_store_held_by_an_exclusive_transaction_warns_within_the_busy_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4 (amended by A1): a locked store is WARN, never a false OK, and the wait is the busy timeout."""
    module = _check_module()
    data_dir = tmp_path / "data"
    await _seed_identity(data_dir, ["crew-a"])
    await _seed_acm(data_dir, onboarded=["crew-a"], commissioned=["crew-a"])
    monkeypatch.setattr(module, "_BUSY_TIMEOUT_S", 0.1)
    unlocked = await _run(data_dir)
    assert unlocked.outcome is CheckOutcome.OK, unlocked  # premise: the same stores read fine when nobody holds them

    holder = sqlite3.connect(data_dir / "acm.db", isolation_level=None)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        locked = await _run(data_dir)
        elapsed = time.monotonic() - started
    finally:
        holder.close()  # closing the connection rolls the open transaction back

    assert locked.outcome is CheckOutcome.WARN, locked
    assert "could not read acm.db" in locked.message
    assert elapsed < 2.0, f"the WARN took {elapsed:.2f}s: the 0.1 s busy timeout was not applied to the read"

    released = await _run(data_dir)
    assert released.outcome is CheckOutcome.OK, released  # the lock, and nothing else, caused the WARN


@pytest.mark.asyncio
async def test_decommissioned_agent_without_a_commissioning_is_not_a_failure(tmp_path: Path) -> None:
    """D5: ACM records crew-a as decommissioned, so it needs no commissioning; crew-b is held to the rule."""
    data_dir = tmp_path / "data"
    await _seed_identity(data_dir, ["crew-a", "crew-b"])
    await _seed_acm(
        data_dir, onboarded=["crew-a", "crew-b"], commissioned=["crew-b"], decommissioned=["crew-a"],
    )
    with contextlib.closing(sqlite3.connect(data_dir / "acm.db")) as conn:
        state = conn.execute("SELECT state FROM lifecycle WHERE agent_id = ?", ("crew-a",)).fetchone()
        recorded = conn.execute("SELECT 1 FROM commissioning_records WHERE agent_id = ?", ("crew-a",)).fetchall()
    assert state == ("decommissioned",)  # premise: decommissioned ...
    assert recorded == []  # ... with no commissioning record, and no skills.db at all
    assert not (data_dir / "skills.db").exists()

    result = await _run(data_dir)

    assert result.outcome is CheckOutcome.OK, result
    assert result.message == "Crew enrollment: all 2 crew have an ACM lifecycle record and a commissioning"

    # Control: the exemption is crew-a's alone. Without its record, crew-b is never commissioned.
    with contextlib.closing(sqlite3.connect(data_dir / "acm.db")) as conn:
        assert conn.execute("DELETE FROM commissioning_records WHERE agent_id = ?", ("crew-b",)).rowcount == 1
        conn.commit()

    control = await _run(data_dir)

    assert control.outcome is CheckOutcome.FAIL
    assert _listed(control, _NEVER) == ["crew-b"]
    assert _listed(control, _NO_LIFECYCLE) == []


def test_crew_enrollment_check_is_registered_once_and_keeps_the_extras_to_verifier_order() -> None:
    """D6: importing the doctor package alone registers the check once; the AD-1327 neighbours stay adjacent.

    A fresh interpreter, so that no other test's direct import of the check module can stand in for the
    registration line in ``probos/doctor/checks/__init__.py`` (and no test that resets the registry can hide it).
    """
    import probos

    src_dir = Path(probos.__file__).resolve().parents[1]  # the tree this test runs against
    probe = (
        "import json; from probos.doctor import checks; from probos.doctor.registry import iter_checks; "
        "print(json.dumps([[c.name, type(c).__qualname__] for c in iter_checks()]))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "PYTHONPATH": str(src_dir)},
    )
    assert done.returncode == 0, done.stderr
    registered = json.loads(done.stdout.strip().splitlines()[-1])
    names = [name for name, _ in registered]

    assert [kind for name, kind in registered if name == "crew_enrollment"] == ["_CrewEnrollmentCheck"]
    assert names[names.index("extras") + 1] == "verifier_independence"  # the neighbours this check must not displace


@pytest.mark.asyncio
async def test_a_transferred_in_slot_is_counted_as_crew(tmp_path: Path) -> None:
    """D7: a slot whose certificate sits in ``foreign_birth_certificates`` is crew, held to the same rule."""
    data_dir = tmp_path / "data"
    await _seed_identity(data_dir, ["crew-a"])
    _seed_transferred_in_slot(data_dir, "crew-visitor")
    await _seed_acm(data_dir, onboarded=["crew-a"], commissioned=["crew-a"])

    unenrolled = await _run(data_dir)

    assert unenrolled.outcome is CheckOutcome.FAIL, unenrolled
    assert unenrolled.message == "Crew enrollment: 1 of 2 crew fail the BF-906 invariant"
    assert _listed(unenrolled, _NO_LIFECYCLE) == ["crew-visitor"]
    assert _listed(unenrolled, _NEVER) == ["crew-visitor"]

    await _seed_acm(data_dir, onboarded=["crew-visitor"], commissioned=["crew-visitor"])  # enrol it

    enrolled = await _run(data_dir)

    assert enrolled.outcome is CheckOutcome.OK, enrolled
    assert enrolled.message == "Crew enrollment: all 2 crew have an ACM lifecycle record and a commissioning"


# ---------------------------------------------------------------------------
# D8 - D12: the adapter's read-only open, and the doctor's use of it (A1.7, A2.7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_open_reads_and_refuses_writes(tmp_path: Path) -> None:
    """D8: ``read_only=True`` returns the committed row, every write raises, and the file is byte-identical."""
    db = tmp_path / "ro.db"
    _seed_plain_db(db)
    digest, listing = _sha256(db), _names(tmp_path)
    assert listing == {"ro.db"}  # premise: a cleanly closed rollback-journal database leaves nothing beside it

    conn = await default_factory.connect(str(db), read_only=True)
    try:
        async with conn.execute("SELECT x FROM t") as cursor:
            rows = [tuple(row) for row in await cursor.fetchall()]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            await conn.execute("INSERT INTO t VALUES (43)")
    finally:
        await conn.close()

    assert rows == [(42,)]
    assert _sha256(db) == digest
    assert _names(tmp_path) == listing


@pytest.mark.asyncio
async def test_read_only_open_never_creates_a_missing_file(tmp_path: Path) -> None:
    """D9: a missing database is an error, never a new empty file."""
    empty = tmp_path / "empty"
    empty.mkdir()
    target = empty / "absent.db"

    with pytest.raises(sqlite3.OperationalError):
        await default_factory.connect(str(target), read_only=True)

    assert not target.exists()
    assert list(empty.iterdir()) == []


@pytest.mark.asyncio
async def test_default_open_is_unchanged(tmp_path: Path) -> None:
    """D10 (boundary): with no keyword, ``connect`` still creates a new file and writes to it."""
    db = tmp_path / "fresh.db"
    assert not db.exists()  # premise

    conn = await default_factory.connect(str(db))
    try:
        await conn.execute("CREATE TABLE t (x INTEGER)")
        await conn.execute("INSERT INTO t VALUES (7)")
        await conn.commit()
    finally:
        await conn.close()

    assert db.is_file()
    with contextlib.closing(sqlite3.connect(db)) as check:
        assert check.execute("SELECT x FROM t").fetchall() == [(7,)]


class _RecordingFactory:
    """Delegates to the real factory and records how each store was opened."""

    def __init__(self) -> None:
        self.opened: list[tuple[str, bool]] = []

    async def connect(self, db_path: str, *, read_only: bool = False) -> Any:
        self.opened.append((Path(db_path).name, read_only))
        return await default_factory.connect(db_path, read_only=read_only)


@pytest.mark.asyncio
async def test_doctor_opens_every_store_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D11: on a seeded data directory every open the check made was read-only, and it opened all three stores."""
    module = _check_module()
    data_dir = tmp_path / "data"
    await _seed_identity(data_dir, ["crew-a"])
    await _seed_acm(data_dir, onboarded=["crew-a"], commissioned=["crew-a"])
    await _seed_skills(data_dir, tmp_path / "skill-registry", ["crew-a"])
    recorder = _RecordingFactory()
    monkeypatch.setattr(module, "default_factory", recorder)

    result = await _run(data_dir)

    assert result.outcome is CheckOutcome.OK, result  # premise: the check got as far as reading every store
    assert {name for name, _ in recorder.opened} == {"identity.db", "acm.db", "skills.db"}
    assert all(read_only is True for _, read_only in recorder.opened), recorder.opened


@pytest.mark.asyncio
async def test_read_only_open_of_a_wal_store_never_changes_the_database_file(tmp_path: Path) -> None:
    """D12 (A2): a WAL store opened read-only returns its row, refuses writes, and its database file is unchanged.

    SQLite may create ``-wal`` and ``-shm`` beside a WAL database when it is read (that depends on the host), so
    the directory may hold those two names and nothing else; the test does not assert that they exist.
    """
    db = tmp_path / "wal.db"
    _seed_plain_db(db, wal=True)
    assert db.read_bytes()[18:20] == b"\x02\x02"  # premise: the file header says WAL (bytes 18-19)
    digest = _sha256(db)

    conn = await default_factory.connect(str(db), read_only=True)
    try:
        async with conn.execute("SELECT x FROM t") as cursor:
            rows = [tuple(row) for row in await cursor.fetchall()]
        with pytest.raises(sqlite3.OperationalError):
            await conn.execute("INSERT INTO t VALUES (43)")
    finally:
        await conn.close()

    assert rows == [(42,)]
    assert _sha256(db) == digest
    assert _names(tmp_path) <= {db.name, f"{db.name}-wal", f"{db.name}-shm"}
