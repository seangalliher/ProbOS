"""AD-541f: Append-only eviction audit trail for episodic memory.

Logs every episode eviction (capacity, reset, force_update) to an
append-only SQLite table.  Follows the ACM lifecycle_transitions
pattern (acm.py:72) — structured, queryable, no hash-chain.

Audit failures never block eviction — fail-fast tier: log-and-degrade.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Schema -------------------------------------------------------------------

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS eviction_audit (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    reason TEXT NOT NULL,
    process TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    episode_timestamp REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_eviction_agent
    ON eviction_audit(agent_id);

CREATE INDEX IF NOT EXISTS idx_eviction_episode
    ON eviction_audit(episode_id);

CREATE INDEX IF NOT EXISTS idx_eviction_timestamp
    ON eviction_audit(timestamp);
"""


# Data class ---------------------------------------------------------------

@dataclass(frozen=True)
class EvictionRecord:
    """A single eviction audit entry — immutable once created."""

    id: str
    episode_id: str
    agent_id: str
    timestamp: float
    reason: str
    process: str
    details: str = ""
    content_hash: str = ""
    episode_timestamp: float = 0.0


# Audit log ----------------------------------------------------------------

class EvictionAuditLog:
    """Append-only audit trail for episode evictions.

    Follows the ACM lifecycle_transitions pattern (acm.py:72).
    Uses ConnectionFactory protocol for cloud-ready storage.
    """

    def __init__(self, connection_factory: Any = None) -> None:
        from probos.storage.sqlite_factory import default_factory
        self._connection_factory = connection_factory or default_factory
        self._db: Any = None
        # AD-541f: Cached counts for sync SIF access
        self._cached_counts: dict[str, int] = {}
        self._cached_total: int = 0

    async def start(self, db_path: str = "eviction_audit.db") -> None:
        """Initialize DB connection and create schema."""
        self._db = await self._connection_factory.connect(db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        # Warm cache
        await self._refresh_cache()

    async def stop(self) -> None:
        """Close DB connection."""
        if self._db is not None:
            try:
                await self._db.close()
            except Exception:
                pass
            self._db = None

    async def _refresh_cache(self) -> None:
        """Update cached counts from DB."""
        if not self._db:
            return
        try:
            cursor = await self._db.execute(
                "SELECT reason, COUNT(*) FROM eviction_audit GROUP BY reason"
            )
            rows = await cursor.fetchall()
            self._cached_counts = {r[0]: r[1] for r in rows}
            self._cached_total = sum(self._cached_counts.values())
        except Exception:
            pass

    async def record_eviction(
        self,
        episode_id: str,
        agent_id: str,
        reason: str,
        process: str,
        *,
        details: str = "",
        content_hash: str = "",
        episode_timestamp: float = 0.0,
    ) -> None:
        """Record a single eviction event. Append-only INSERT.

        Failure is caught and logged as WARNING — never blocks the
        eviction itself.
        """
        if not self._db:
            return
        try:
            record_id = uuid.uuid4().hex
            await self._db.execute(
                "INSERT INTO eviction_audit "
                "(id, episode_id, agent_id, timestamp, reason, process, "
                "details, content_hash, episode_timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record_id, episode_id, agent_id, time.time(),
                    reason, process, details, content_hash, episode_timestamp,
                ),
            )
            await self._db.commit()
            # Update cache
            self._cached_counts[reason] = self._cached_counts.get(reason, 0) + 1
            self._cached_total += 1
        except Exception as exc:
            logger.warning("Eviction audit record failed: %s", exc)

    async def record_batch_eviction(
        self,
        records: list[dict],
        reason: str,
        process: str,
        *,
        details: str = "",
    ) -> None:
        """Record multiple evictions in a single transaction.

        Each dict in records must have: episode_id, agent_id.
        Optional: content_hash, episode_timestamp.
        """
        if not self._db or not records:
            return
        try:
            now = time.time()
            rows = [
                (
                    uuid.uuid4().hex,
                    r["episode_id"],
                    r["agent_id"],
                    now,
                    reason,
                    process,
                    details,
                    r.get("content_hash", ""),
                    r.get("episode_timestamp", 0.0),
                )
                for r in records
            ]
            await self._db.executemany(
                "INSERT INTO eviction_audit "
                "(id, episode_id, agent_id, timestamp, reason, process, "
                "details, content_hash, episode_timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            await self._db.commit()
            # Update cache
            self._cached_counts[reason] = self._cached_counts.get(reason, 0) + len(records)
            self._cached_total += len(records)
        except Exception as exc:
            logger.warning("Eviction audit batch record failed: %s", exc)

    async def query_by_agent(
        self, agent_id: str, *, limit: int = 50
    ) -> list[EvictionRecord]:
        """Get eviction history for a specific agent. Newest first."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT id, episode_id, agent_id, timestamp, reason, process, "
            "details, content_hash, episode_timestamp "
            "FROM eviction_audit WHERE agent_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (agent_id, limit),
        )
        rows = await cursor.fetchall()
        return [EvictionRecord(*r) for r in rows]

    async def query_by_episode(
        self, episode_id: str
    ) -> EvictionRecord | None:
        """Look up whether a specific episode was evicted."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT id, episode_id, agent_id, timestamp, reason, process, "
            "details, content_hash, episode_timestamp "
            "FROM eviction_audit WHERE episode_id = ? LIMIT 1",
            (episode_id,),
        )
        row = await cursor.fetchone()
        return EvictionRecord(*row) if row else None

    async def query_recent(
        self, *, limit: int = 100
    ) -> list[EvictionRecord]:
        """Get most recent evictions across all agents."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT id, episode_id, agent_id, timestamp, reason, process, "
            "details, content_hash, episode_timestamp "
            "FROM eviction_audit ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [EvictionRecord(*r) for r in rows]

    async def count_by_reason(self) -> dict[str, int]:
        """Aggregate eviction counts by reason. For SIF/VitalsMonitor."""
        if not self._db:
            return {}
        cursor = await self._db.execute(
            "SELECT reason, COUNT(*) FROM eviction_audit GROUP BY reason"
        )
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}

    async def count_by_agent(self, agent_id: str) -> int:
        """Total evictions for an agent."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM eviction_audit WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
