"""Append-only event log — SQLite-backed lifecycle and system event log."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    category        TEXT    NOT NULL,
    event           TEXT    NOT NULL,
    agent_id        TEXT,
    agent_type      TEXT,
    pool            TEXT,
    detail          TEXT,
    correlation_id  TEXT,
    parent_event_id INTEGER,
    data            TEXT
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

    def __init__(self, db_path: str | Path, connection_factory: ConnectionFactory | None = None) -> None:
        self.db_path = str(db_path)
        self._db: DatabaseConnection | None = None
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await self._connection_factory.connect(self.db_path)
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        # AD-664: Migrate existing databases — add new columns if missing
        await self._migrate_ad664()
        logger.info("EventLog opened: %s", self.db_path)

    async def _migrate_ad664(self) -> None:
        """Add correlation_id, parent_event_id, data columns if missing (AD-664)."""
        if not self._db:
            return
        try:
            async with self._db.execute("PRAGMA table_info(events)") as cursor:
                columns = {row[1] async for row in cursor}
            migrations = []
            if "correlation_id" not in columns:
                migrations.append("ALTER TABLE events ADD COLUMN correlation_id TEXT")
            if "parent_event_id" not in columns:
                migrations.append("ALTER TABLE events ADD COLUMN parent_event_id INTEGER")
            if "data" not in columns:
                migrations.append("ALTER TABLE events ADD COLUMN data TEXT")
            for sql in migrations:
                await self._db.execute(sql)
            # Always ensure indexes exist — IF NOT EXISTS makes this idempotent
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_correlation ON events (correlation_id)"
            )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_parent ON events (parent_event_id)"
            )
            if migrations:
                await self._db.commit()
                logger.info("AD-664: Migrated EventLog schema (%d columns added)", len(migrations))
        except Exception:
            logger.debug("AD-664: EventLog migration check failed", exc_info=True)

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
        *,
        correlation_id: str | None = None,
        parent_event_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        """Append an event to the log.

        Returns the inserted row ID (for parent_event_id chaining),
        or None if the database is not available.

        AD-664: New keyword-only params:
        - correlation_id: groups causally related events
        - parent_event_id: references the preceding event's row ID
        - data: structured payload (dict, JSON-serialized on write)
        """
        if not self._db:
            return None
        now = datetime.now(timezone.utc).isoformat()
        data_json = json.dumps(data, default=str) if data is not None else None
        cursor = await self._db.execute(
            "INSERT INTO events "
            "(timestamp, category, event, agent_id, agent_type, pool, detail, "
            " correlation_id, parent_event_id, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now, category, event, agent_id, agent_type, pool, detail,
             correlation_id, parent_event_id, data_json),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def query(
        self,
        category: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query recent events, optionally filtered.

        AD-664: Results now include correlation_id, parent_event_id, and
        data (deserialized from JSON).
        """
        if not self._db:
            return []

        sql = ("SELECT id, timestamp, category, event, agent_id, agent_type, "
               "pool, detail, correlation_id, parent_event_id, data "
               "FROM events")
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
                rows.append(self._row_to_dict(row))
        return rows

    async def query_structured(
        self,
        *,
        correlation_id: str | None = None,
        category: str | None = None,
        event: str | None = None,
        parent_event_id: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query events with structured filtering (AD-664).

        Supports querying by correlation_id (causal chain), event name,
        and parent_event_id (direct predecessor).

        Returns same dict shape as query(), with deserialized data field.
        """
        if not self._db:
            return []

        sql = ("SELECT id, timestamp, category, event, agent_id, agent_type, "
               "pool, detail, correlation_id, parent_event_id, data "
               "FROM events")
        conditions = []
        params: list = []

        if correlation_id is not None:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)
        if category is not None:
            conditions.append("category = ?")
            params.append(category)
        if event is not None:
            conditions.append("event = ?")
            params.append(event)
        if parent_event_id is not None:
            conditions.append("parent_event_id = ?")
            params.append(parent_event_id)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = []
        async with self._db.execute(sql, params) as cursor:
            async for row in cursor:
                rows.append(self._row_to_dict(row))
        return rows

    async def get_event_chain(self, event_id: int, max_depth: int = 20) -> list[dict]:
        """Walk the parent_event_id chain from a given event upward (AD-664).

        Returns events from the given event up to the root (parent_event_id is NULL),
        ordered from root to leaf. Stops at max_depth to prevent infinite loops
        from data corruption.
        """
        if not self._db:
            return []

        chain: list[dict] = []
        current_id: int | None = event_id

        for _ in range(max_depth):
            if current_id is None:
                break
            sql = ("SELECT id, timestamp, category, event, agent_id, agent_type, "
                   "pool, detail, correlation_id, parent_event_id, data "
                   "FROM events WHERE id = ?")
            async with self._db.execute(sql, (current_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                break
            chain.append(self._row_to_dict(row))
            current_id = row[9]  # parent_event_id

        chain.reverse()  # root-to-leaf order
        return chain

    @staticmethod
    def _row_to_dict(row: tuple) -> dict:
        """Convert a SELECT row (11 columns) to a dict with JSON-parsed data."""
        data_raw = row[10]
        try:
            data_parsed = json.loads(data_raw) if data_raw else None
        except (ValueError, TypeError):
            data_parsed = None
        return {
            "id": row[0],
            "timestamp": row[1],
            "category": row[2],
            "event": row[3],
            "agent_id": row[4],
            "agent_type": row[5],
            "pool": row[6],
            "detail": row[7],
            "correlation_id": row[8],
            "parent_event_id": row[9],
            "data": data_parsed,
        }

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

    async def count_all(self) -> int:
        """Total event count."""
        return await self.count()

    async def prune(self, retention_days: int = 7, max_rows: int = 100_000) -> int:
        """Delete events older than retention_days and enforce max_rows cap.

        Returns number of rows deleted.
        """
        if not self._db:
            return 0

        deleted = 0

        # Age-based pruning
        if retention_days > 0:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
            cursor = await self._db.execute(
                "DELETE FROM events WHERE timestamp < ?", (cutoff,)
            )
            deleted += cursor.rowcount

        # Row-count cap
        if max_rows > 0:
            cursor = await self._db.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            total = row[0] if row else 0
            if total > max_rows:
                excess = total - max_rows
                cursor = await self._db.execute(
                    "DELETE FROM events WHERE id IN "
                    "(SELECT id FROM events ORDER BY id ASC LIMIT ?)",
                    (excess,)
                )
                deleted += cursor.rowcount

        if deleted > 0:
            await self._db.commit()
            logger.info("EventLog pruned: %d events removed", deleted)

        return deleted

    async def wipe(self) -> None:
        """Delete all events. Used by probos reset."""
        if not self._db:
            return
        try:
            await self._db.execute("DELETE FROM events")
            await self._db.commit()
        except Exception:
            logger.debug("EventLog wipe failed", exc_info=True)
