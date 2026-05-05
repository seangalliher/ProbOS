"""AD-635c: CircuitBreakerHistoryStore — SQLite-backed durable store for
cognitive circuit-breaker state and zone transitions.

Mirrors the AD-635b / AD-542 ConnectionFactory pattern (cf.
``clinical_audit_store.py`` and ``activation_tracker.py``): constructor
accepts an optional callable returning an aiosqlite-compatible
connection; default uses ``aiosqlite.connect(db_path)`` directly.
Commercial overlays inject a Postgres / cloud factory without changing
call sites (AD-635c-5 deferral target).

Lifecycle:

  * ``__init__`` is sync and does NOT touch disk. The SQLite file is
    created on first ``append(...)`` via ``_ensure_open()``.
  * No explicit ``close()`` in v1 — Python GC closes file handles on
    process exit. Explicit close is part of AD-635c-1 (restore-on-boot).

Schema (v1):

  CREATE TABLE circuit_breaker_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      agent_id TEXT NOT NULL,
      transition_kind TEXT NOT NULL,    -- "state" or "zone"
      old_value TEXT NOT NULL,          -- e.g. "closed", "green"
      new_value TEXT NOT NULL,          -- e.g. "open", "amber"
      trip_count INTEGER NOT NULL DEFAULT 0,
      cooldown_seconds REAL NOT NULL DEFAULT 0.0,
      reason TEXT
  );
  CREATE INDEX idx_cbh_ts ON circuit_breaker_history(ts DESC);
  CREATE INDEX idx_cbh_agent_ts ON circuit_breaker_history(agent_id, ts DESC);
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS circuit_breaker_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    agent_id TEXT NOT NULL,
    transition_kind TEXT NOT NULL,
    old_value TEXT NOT NULL,
    new_value TEXT NOT NULL,
    trip_count INTEGER NOT NULL DEFAULT 0,
    cooldown_seconds REAL NOT NULL DEFAULT 0.0,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_cbh_ts ON circuit_breaker_history(ts DESC);
CREATE INDEX IF NOT EXISTS idx_cbh_agent_ts ON circuit_breaker_history(agent_id, ts DESC);
"""


class CircuitBreakerHistoryStore:
    """AD-635c: SQLite-backed history store for CognitiveCircuitBreaker."""

    def __init__(
        self,
        *,
        db_path: str,
        connection_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._db: Any = None

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def is_open(self) -> bool:
        return self._db is not None

    async def append(self, entry: dict[str, Any]) -> None:
        """Persist one transition row.

        ``entry`` must contain ``ts``, ``agent_id``, ``transition_kind``,
        ``old_value``, ``new_value``. Optional: ``trip_count`` (default 0),
        ``cooldown_seconds`` (default 0.0), ``reason`` (default None).
        """
        await self._ensure_open()
        await self._db.execute(
            "INSERT INTO circuit_breaker_history "
            "(ts, agent_id, transition_kind, old_value, new_value, "
            "trip_count, cooldown_seconds, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                float(entry["ts"]),
                str(entry["agent_id"]),
                str(entry["transition_kind"]),
                str(entry["old_value"]),
                str(entry["new_value"]),
                int(entry.get("trip_count", 0)),
                float(entry.get("cooldown_seconds", 0.0)),
                entry.get("reason"),
            ),
        )
        await self._db.commit()

    async def recent(
        self,
        limit: int,
        *,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` most-recent rows (highest ``ts`` first).

        When ``agent_id`` is provided, filters by agent_id (uses the
        composite ``idx_cbh_agent_ts`` index). When None, returns rows
        across all agents (uses the ``idx_cbh_ts`` index).
        """
        if limit <= 0:
            return []
        await self._ensure_open()
        if agent_id is not None:
            cursor = await self._db.execute(
                "SELECT ts, agent_id, transition_kind, old_value, new_value, "
                "trip_count, cooldown_seconds, reason FROM circuit_breaker_history "
                "WHERE agent_id = ? ORDER BY ts DESC LIMIT ?",
                (str(agent_id), int(limit)),
            )
        else:
            cursor = await self._db.execute(
                "SELECT ts, agent_id, transition_kind, old_value, new_value, "
                "trip_count, cooldown_seconds, reason FROM circuit_breaker_history "
                "ORDER BY ts DESC LIMIT ?",
                (int(limit),),
            )
        rows = await cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            entry: dict[str, Any] = {
                "ts": row[0],
                "agent_id": row[1],
                "transition_kind": row[2],
                "old_value": row[3],
                "new_value": row[4],
                "trip_count": row[5],
                "cooldown_seconds": row[6],
            }
            if row[7] is not None:
                entry["reason"] = row[7]
            result.append(entry)
        return result

    async def _ensure_open(self) -> None:
        """Lazy SQLite open + schema bootstrap. Idempotent."""
        if self._db is not None:
            return
        if self._connection_factory is not None:
            self._db = await self._connection_factory()
        else:
            import aiosqlite
            self._db = await aiosqlite.connect(self._db_path)
        for stmt in _SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await self._db.execute(stmt)
        await self._db.commit()
