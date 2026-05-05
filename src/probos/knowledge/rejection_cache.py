"""AD-690: Rejection cache for Dream Step 7i relationship inference.

Persists `(source_id, target_id, relation, reason, rejected_at)` rows so the
nightly dream cycle does not re-ask the LLM about the same agent pair every
run. Mirrors the SQLiteKnowledgeEdgeStore lifecycle (start/stop bootstrap).

Surface kept deliberately narrow: `was_rejected` for the read path,
`record_rejection` for the write path. No update or delete in v1 — entries
are append-only and persist for the life of the database.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol, runtime_checkable

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dream_step10_rejections (
    source_id  TEXT NOT NULL,
    target_id  TEXT NOT NULL,
    relation   TEXT,
    reason     TEXT,
    rejected_at REAL NOT NULL,
    PRIMARY KEY (source_id, target_id)
);
"""


@runtime_checkable
class RejectionCacheStorage(Protocol):
    """Public read+write surface used by AD-690 Step 7i."""

    async def was_rejected(self, source_id: str, target_id: str) -> bool: ...
    async def record_rejection(
        self,
        *,
        source_id: str,
        target_id: str,
        relation: str | None,
        reason: str,
    ) -> None: ...


class SQLiteRejectionCache:
    """Concrete SQLite-backed rejection cache.

    Lifecycle parallels SQLiteKnowledgeEdgeStore: pass a path; call ``start()``
    to bootstrap schema; call ``stop()`` on shutdown. ``was_rejected`` checks
    BOTH directions — `(a, b)` and `(b, a)` — since pairs are undirected at
    classification time.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        if self._db is not None:
            return
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def was_rejected(self, source_id: str, target_id: str) -> bool:
        if self._db is None:
            return False
        try:
            async with self._db.execute(
                "SELECT 1 FROM dream_step10_rejections "
                "WHERE (source_id = ? AND target_id = ?) "
                "   OR (source_id = ? AND target_id = ?) LIMIT 1",
                (source_id, target_id, target_id, source_id),
            ) as cur:
                row = await cur.fetchone()
            return row is not None
        except Exception:
            logger.debug("AD-690: rejection cache read failed", exc_info=True)
            return False

    async def record_rejection(
        self,
        *,
        source_id: str,
        target_id: str,
        relation: str | None,
        reason: str,
    ) -> None:
        if self._db is None:
            return
        try:
            await self._db.execute(
                "INSERT OR REPLACE INTO dream_step10_rejections "
                "(source_id, target_id, relation, reason, rejected_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (source_id, target_id, relation, reason, time.time()),
            )
            await self._db.commit()
        except Exception:
            logger.debug("AD-690: rejection cache write failed", exc_info=True)
