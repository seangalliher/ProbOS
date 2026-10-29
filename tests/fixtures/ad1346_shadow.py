"""AD-1346 M3b (#1604): shared values for the shadow store, recorder, report and boot tests.

``T0`` is 2026-10-28T12:00:00Z. ``admit`` and ``refuse`` build ``AdmissionVerdict`` values directly, so a
test needs no identity registry. ``rows`` reads a SQLite file with a connection of its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from probos.admission import AdmissionVerdict
from probos.storage.sqlite_factory import default_factory

T0 = 1_793_188_800.0
HOUR = 3_600


def admit(*, work_kind: str = "intent", seam: str = "intent") -> AdmissionVerdict:
    """An admitted verdict for the allow-listed system principal."""
    return AdmissionVerdict(
        outcome="admit", reason_code="admitted", check="", cause="admitted", key="system:ship_computer",
        principal_kind="system", principal=None, presented_id="system:ship_computer", work_kind=work_kind,
        seam=seam, origin="system", origin_id="system:ship_computer", stop_id="",
    )


def refuse(*, work_kind: str = "intent", seam: str = "intent") -> AdmissionVerdict:
    """A would-refuse ``identity_unresolved`` verdict for the presented id ``nobody``."""
    return AdmissionVerdict(
        outcome="would_refuse", reason_code="identity_unresolved", check="principal", cause="no identity for nobody",
        key="nobody", principal_kind="unresolved", principal=None, presented_id="nobody", work_kind=work_kind,
        seam=seam, origin="captain", origin_id="captain", stop_id="",
    )


async def rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """The rows of ``sql`` on ``path``, read with a connection this call opens and closes."""
    db = await default_factory.connect(str(path))
    try:
        async with db.execute(sql, params) as cursor:
            return [tuple(row) for row in await cursor.fetchall()]
    finally:
        await db.close()
