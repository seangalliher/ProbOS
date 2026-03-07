"""Append-only event log — SQLite-backed lifecycle and system event log."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT    NOT NULL,
    category  TEXT    NOT NULL,
    event     TEXT    NOT NULL,
    agent_id  TEXT,
    agent_type TEXT,
    pool      TEXT,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_category ON events (category);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events (agent_id);
"""


class EventLog:
    """Append-only event log persisted to SQLite.

    Records agent lifecycle events (spawn, active, degraded, recycled),
    mesh events (intent broadcast, intent resolved, gossip exchange),
    and system events (startup, shutdown, pool health check).
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("EventLog opened: %s", self.db_path)

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def log(
        self,
        category: str,
        event: str,
        agent_id: str | None = None,
        agent_type: str | None = None,
        pool: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Append an event to the log."""
        if not self._db:
            return
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO events (timestamp, category, event, agent_id, agent_type, pool, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, category, event, agent_id, agent_type, pool, detail),
        )
        await self._db.commit()

    async def query(
        self,
        category: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query recent events, optionally filtered."""
        if not self._db:
            return []

        sql = "SELECT id, timestamp, category, event, agent_id, agent_type, pool, detail FROM events"
        conditions = []
        params: list[str] = []

        if category:
            conditions.append("category = ?")
            params.append(category)
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(str(limit))

        rows = []
        async with self._db.execute(sql, params) as cursor:
            async for row in cursor:
                rows.append({
                    "id": row[0],
                    "timestamp": row[1],
                    "category": row[2],
                    "event": row[3],
                    "agent_id": row[4],
                    "agent_type": row[5],
                    "pool": row[6],
                    "detail": row[7],
                })
        return rows

    async def count(self, category: str | None = None) -> int:
        """Count events, optionally filtered by category."""
        if not self._db:
            return 0
        if category:
            sql = "SELECT COUNT(*) FROM events WHERE category = ?"
            params: tuple = (category,)
        else:
            sql = "SELECT COUNT(*) FROM events"
            params = ()
        async with self._db.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
