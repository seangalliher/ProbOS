"""BF-906 (#1594): every crew member has an ACM lifecycle record and a commissioning.

Reads identity.db, acm.db and skills.db through the approved ConnectionFactory
adapter's ``read_only`` open (SQLite ``mode=ro``): safe while the vessel runs,
it never creates a file and never writes to a store. The crew are the slots
holding a birth certificate, issued here or transferred in. A crew member needs
a lifecycle row, and a commissioning record or at least one skill, unless ACM
records it as decommissioned. Mirrors ``probos.crew_enrollment.check_crew_invariant``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.storage.sqlite_factory import default_factory

_BUSY_TIMEOUT_S = 2.0
_CREW_SQL = (
    "SELECT s.slot_id FROM slot_mappings s JOIN birth_certificates b ON b.agent_uuid = s.agent_uuid"
)
_FOREIGN_CREW_SQL = (
    "SELECT s.slot_id FROM slot_mappings s "
    "JOIN foreign_birth_certificates f ON f.agent_uuid = s.agent_uuid"
)
_LIFECYCLE_SQL = "SELECT agent_id, state FROM lifecycle"
_COMMISSIONED_SQL = "SELECT agent_id FROM commissioning_records"
_SKILLED_SQL = "SELECT DISTINCT agent_id FROM agent_skills"


class _StoreUnreadable(Exception):
    """A store could not be read (locked by the running vessel, or unreadable)."""


async def _rows(path: Path, sql: str) -> list[tuple] | None:
    """Rows of ``sql`` from the store at ``path``; None when the store or table is absent."""
    if not path.exists():
        return None
    try:
        conn = await default_factory.connect(str(path), read_only=True)
    except sqlite3.Error as exc:
        raise _StoreUnreadable(f"{path.name}: {exc}") from exc
    try:
        await conn.execute(f"PRAGMA busy_timeout = {int(_BUSY_TIMEOUT_S * 1000)}")
        async with conn.execute(sql) as cursor:
            return [tuple(row) for row in await cursor.fetchall()]
    except sqlite3.Error as exc:
        if isinstance(exc, sqlite3.OperationalError) and "no such table" in str(exc):
            return None
        raise _StoreUnreadable(f"{path.name}: {exc}") from exc
    finally:
        await conn.close()


@dataclass(frozen=True)
class _CrewEnrollmentCheck:
    name: str = "crew_enrollment"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        data_dir = ctx.data_dir
        try:
            crew_rows = await _rows(data_dir / "identity.db", _CREW_SQL)
            if crew_rows is None:
                return CheckResult(CheckOutcome.OK, "Crew enrollment: no crew yet (identity store not initialized)")
            foreign_rows = await _rows(data_dir / "identity.db", _FOREIGN_CREW_SQL) or []
            crew = sorted({r[0] for r in crew_rows} | {r[0] for r in foreign_rows})
            lifecycle = {r[0]: r[1] for r in (await _rows(data_dir / "acm.db", _LIFECYCLE_SQL) or [])}
            commissioned = {r[0] for r in (await _rows(data_dir / "acm.db", _COMMISSIONED_SQL) or [])}
            skilled = {r[0] for r in (await _rows(data_dir / "skills.db", _SKILLED_SQL) or [])}
        except _StoreUnreadable as exc:
            return CheckResult(
                CheckOutcome.WARN, f"Crew enrollment: could not read {exc}",
                "The running vessel may be writing to it; rerun `probos doctor`.",
            )
        if not crew:
            return CheckResult(CheckOutcome.OK, "Crew enrollment: no crew have birth certificates yet")
        missing = [a for a in crew if a not in lifecycle]
        never = [
            a for a in crew
            if lifecycle.get(a) != "decommissioned"
            and a not in commissioned and a not in skilled
        ]
        if not missing and not never:
            return CheckResult(
                CheckOutcome.OK,
                f"Crew enrollment: all {len(crew)} crew have an ACM lifecycle record and a commissioning",
            )
        failing = sorted(set(missing) | set(never))
        return CheckResult(
            CheckOutcome.FAIL,
            f"Crew enrollment: {len(failing)} of {len(crew)} crew fail the BF-906 invariant",
            "No ACM lifecycle record: " + (", ".join(missing) or "none") + "\n"
            "Never commissioned: " + (", ".join(never) or "none") + "\n"
            "Restart ProbOS: the startup enrollment pass records them. If this persists, "
            "search the startup log for 'BF-906'.",
        )


register_check(_CrewEnrollmentCheck())
