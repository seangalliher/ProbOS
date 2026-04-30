"""Ship's Archive — cross-reset generational knowledge persistence (AD-524).

Stores curated knowledge entries that survive resets. Entries are append-only
(no updates, no deletes). Each entry records which timeline (instance) it
came from and when it was archived.

Storage location: {archive_dir}/archive.db (outside instance data_dir).
Default archive_dir: platform-specific ProbOS home / archive/.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArchiveEntry:
    """A single archived knowledge entry."""

    id: int
    timeline_id: str
    category: str
    title: str
    content: str
    author_agent_type: str
    author_callsign: str
    archived_at: float
    metadata: dict[str, Any] = field(default_factory=dict)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author_agent_type TEXT NOT NULL DEFAULT '',
    author_callsign TEXT NOT NULL DEFAULT '',
    archived_at REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_archive_category ON archive(category);
CREATE INDEX IF NOT EXISTS idx_archive_timeline ON archive(timeline_id);
"""


class ArchiveStore:
    """Append-only cross-reset knowledge store (AD-524).

    Uses ConnectionFactory protocol for cloud-ready storage.
    """

    def __init__(self, db_path: str, *, connection_factory: ConnectionFactory) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._db: Any = None

    async def initialize(self) -> None:
        """Open database and create schema."""
        self._db = await self._connection_factory.connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("AD-524: ArchiveStore initialized at %s", self._db_path)

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def append(
        self,
        *,
        timeline_id: str,
        category: str,
        title: str,
        content: str,
        author_agent_type: str = "",
        author_callsign: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Append an entry to the archive. Returns the entry ID.

        This is the ONLY write operation. No updates, no deletes.
        """
        if not self._db:
            raise RuntimeError("ArchiveStore not initialized")

        now = time.time()
        meta_json = json.dumps(metadata or {})

        cursor = await self._db.execute(
            """INSERT INTO archive
               (timeline_id, category, title, content, author_agent_type,
                author_callsign, archived_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timeline_id,
                category,
                title,
                content,
                author_agent_type,
                author_callsign,
                now,
                meta_json,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def search(
        self,
        query: str,
        *,
        category: str = "",
        limit: int = 10,
    ) -> list[ArchiveEntry]:
        """Search archive entries by keyword match on title and content.

        Simple LIKE-based search. Future: full-text search or vector embeddings.
        """
        if not self._db:
            return []

        _escaped = query.replace("%", "\\%").replace("_", "\\_")
        conditions = ["(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')"]
        params: list[Any] = [f"%{_escaped}%", f"%{_escaped}%"]

        if category:
            conditions.append("category = ?")
            params.append(category)

        sql = f"""SELECT id, timeline_id, category, title, content,
                         author_agent_type, author_callsign, archived_at, metadata
                  FROM archive
                  WHERE {' AND '.join(conditions)}
                  ORDER BY archived_at DESC
                  LIMIT ?"""
        params.append(limit)

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()

        return [self._row_to_entry(row) for row in rows]

    async def get_recent(self, limit: int = 20) -> list[ArchiveEntry]:
        """Get the most recent archive entries (no filter)."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            """SELECT id, timeline_id, category, title, content,
                     author_agent_type, author_callsign, archived_at, metadata
              FROM archive ORDER BY archived_at DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(row) for row in rows]

    async def count(self) -> int:
        """Return total number of archive entries."""
        if not self._db:
            return 0
        cursor = await self._db.execute("SELECT COUNT(*) FROM archive")
        row = await cursor.fetchone()
        return row[0] if row else 0

    @staticmethod
    def _row_to_entry(row: Any) -> ArchiveEntry:
        return ArchiveEntry(
            id=row[0],
            timeline_id=row[1],
            category=row[2],
            title=row[3],
            content=row[4],
            author_agent_type=row[5],
            author_callsign=row[6],
            archived_at=row[7],
            metadata=json.loads(row[8]) if row[8] else {},
        )
