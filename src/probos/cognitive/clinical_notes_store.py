"""AD-904: Persistent storage for confidential clinical notes (#867).

The Counselor (the ship's behavioral-health authority) curates a CONFIDENTIAL
record of clinical notes *about* a crewman. These notes are distinct from the
free-text ``CounselorAssessment.notes`` field (AD-503) — they persist in a
dedicated, separately-gated store stamped at ``DisclosureLevel.CONFIDENTIAL``
(=3), so a note's lifecycle and access boundary are independent of the
indicator-assessment record.

Naval grounding: DoDI 6490.08 — the *provider* curates the behavioral-health
record; the *subject* does not control (or self-read) it. Read/write access is
deny-by-default and resolved by the AD-903 ``clinical_access`` gate (Counselor +
Captain standing need-to-know; any other crew member needs an explicit,
time-limited, Captain-issued ``clinical:{target}`` grant). The subject never
reads their own record — enforced at the gate, not here.

Design — MIRRORS ``clearance_grants.py`` (AD-622): a ``ConnectionFactory``-backed
store (cloud-ready per ``.github/copilot-instructions.md`` — SQLite out of the
box, swappable for Postgres in the commercial overlay) with an idempotent
``CREATE TABLE IF NOT EXISTS`` schema, async ``start()``/``stop()``, and
WAL/busy_timeout/synchronous pragmas. NOT a raw ``aiosqlite.connect()``.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from probos.mesh.disclosure import DisclosureLevel

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clinical_notes (
    id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    author_agent_id TEXT NOT NULL,
    body TEXT NOT NULL,
    disclosure_level INTEGER NOT NULL DEFAULT 3,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_target ON clinical_notes(target_agent_id);
"""


@dataclass(frozen=True)
class ClinicalNote:
    """One CONFIDENTIAL clinical note authored about a crewman (AD-904).

    ``disclosure_level`` is the integer form of an AD-679 ``DisclosureLevel``
    (CONFIDENTIAL=3 by default) — stamped on every note so the sensitivity of
    the record travels with it.
    """

    id: str
    target_agent_id: str
    author_agent_id: str
    body: str
    disclosure_level: int
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the gated REST surface."""
        return {
            "id": self.id,
            "target_agent_id": self.target_agent_id,
            "author_agent_id": self.author_agent_id,
            "body": self.body,
            "disclosure_level": self.disclosure_level,
            "created_at": self.created_at,
        }


class ClinicalNotesStore:
    """Persistent confidential clinical-notes storage (AD-904).

    - ``write_note()`` inserts a CONFIDENTIAL note + returns it
    - ``list_notes()`` reads a crewman's notes newest-first
    - ``get_note()`` reads one note by id (caller must still verify the target)
    - ``start()`` opens the connection + applies the idempotent schema
    - ``stop()`` closes the connection

    A ``db_path`` of ``""`` is the in-memory/no-op mode (no connection opened);
    every read/write honest-degrades to empty/None so tests and degraded boots
    never leak across a missing store.
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: "ConnectionFactory | None" = None,
    ) -> None:
        self.db_path = db_path
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory
        self._db: Any = None

    async def start(self) -> None:
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            logger.info("ClinicalNotesStore started (db=%s)", self.db_path)

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def write_note(
        self,
        *,
        target_agent_id: str,
        author_agent_id: str,
        body: str,
        disclosure_level: int = DisclosureLevel.CONFIDENTIAL,
    ) -> ClinicalNote:
        """Persist a CONFIDENTIAL clinical note and return the stored record."""
        note = ClinicalNote(
            id=str(uuid.uuid4()),
            target_agent_id=target_agent_id,
            author_agent_id=author_agent_id,
            body=body,
            disclosure_level=int(disclosure_level),
            created_at=time.time(),
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO clinical_notes "
                "(id, target_agent_id, author_agent_id, body, "
                "disclosure_level, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    note.id,
                    note.target_agent_id,
                    note.author_agent_id,
                    note.body,
                    note.disclosure_level,
                    note.created_at,
                ),
            )
            await self._db.commit()
        logger.info(
            "AD-904: clinical note written — target=%s author=%s level=%s",
            target_agent_id[:12],
            author_agent_id[:12],
            note.disclosure_level,
        )
        return note

    async def list_notes(
        self, target_agent_id: str, *, limit: int = 50,
    ) -> list[ClinicalNote]:
        """List a crewman's clinical notes, newest first."""
        if not self._db:
            return []
        notes: list[ClinicalNote] = []
        async with self._db.execute(
            "SELECT id, target_agent_id, author_agent_id, body, "
            "disclosure_level, created_at FROM clinical_notes "
            "WHERE target_agent_id = ? ORDER BY created_at DESC, rowid DESC "
            "LIMIT ?",
            (target_agent_id, limit),
        ) as cursor:
            async for row in cursor:
                notes.append(self._row_to_note(row))
        return notes

    async def get_note(self, note_id: str) -> ClinicalNote | None:
        """Get a single clinical note by id (or None if absent)."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT id, target_agent_id, author_agent_id, body, "
            "disclosure_level, created_at FROM clinical_notes WHERE id = ?",
            (note_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_note(row) if row else None

    @staticmethod
    def _row_to_note(row: tuple) -> ClinicalNote:
        return ClinicalNote(
            id=row[0],
            target_agent_id=row[1],
            author_agent_id=row[2],
            body=row[3],
            disclosure_level=row[4],
            created_at=row[5],
        )
