"""AD-635b: ClinicalAuditStore — SQLite-backed durable store for clinical
audit entries.

Mirrors the AD-542 ConnectionFactory pattern (cf. activation_tracker.py):
constructor accepts an optional callable returning an aiosqlite-compatible
connection; default uses ``aiosqlite.connect(db_path)`` directly. Commercial
overlays inject a Postgres / cloud factory without changing call sites.

Lifecycle:

  * ``__init__`` is sync and does NOT touch disk. The SQLite file is
    created on first ``append(...)`` via ``_ensure_open()``.
  * No explicit ``close()`` in v1 — Python GC closes file handles on
    process exit. Explicit close is part of AD-635b-1 (restore-on-boot).

Schema (v1):

  CREATE TABLE clinical_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      requester_agent_id TEXT NOT NULL,
      query_type TEXT NOT NULL,
      granted INTEGER NOT NULL,        -- 0 / 1 (SQLite has no native bool)
      result_count INTEGER NOT NULL,
      target_agent_id TEXT
  );
  CREATE INDEX idx_clinical_audit_ts ON clinical_audit(ts DESC);
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS clinical_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    requester_agent_id TEXT NOT NULL,
    query_type TEXT NOT NULL,
    granted INTEGER NOT NULL,
    result_count INTEGER NOT NULL,
    target_agent_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_clinical_audit_ts ON clinical_audit(ts DESC);
"""


class ClinicalAuditStore:
    """AD-635b: SQLite-backed audit store for ClinicalTelemetryService."""

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
        """Persist one audit row.

        ``entry`` must contain ``ts``, ``requester_agent_id``, ``query_type``,
        ``granted``, ``result_count``. ``target_agent_id`` is optional.
        """
        await self._ensure_open()
        await self._db.execute(
            "INSERT INTO clinical_audit "
            "(ts, requester_agent_id, query_type, granted, result_count, target_agent_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                float(entry["ts"]),
                str(entry["requester_agent_id"]),
                str(entry["query_type"]),
                1 if entry["granted"] else 0,
                int(entry["result_count"]),
                entry.get("target_agent_id"),
            ),
        )
        await self._db.commit()

    async def recent(self, limit: int) -> list[dict[str, Any]]:
        """Return up to ``limit`` most-recent rows (highest ``ts`` first)."""
        if limit <= 0:
            return []
        await self._ensure_open()
        cursor = await self._db.execute(
            "SELECT ts, requester_agent_id, query_type, granted, result_count, "
            "target_agent_id FROM clinical_audit ORDER BY ts DESC LIMIT ?",
            (int(limit),),
        )
        rows = await cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            entry: dict[str, Any] = {
                "ts": row[0],
                "requester_agent_id": row[1],
                "query_type": row[2],
                "granted": bool(row[3]),
                "result_count": row[4],
            }
            if row[5] is not None:
                entry["target_agent_id"] = row[5]
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
