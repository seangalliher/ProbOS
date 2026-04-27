"""Cognitive Journal — append-only LLM reasoning trace store.

Records every LLM call with agent, tier, model, tokens, latency, and
intent linkage.  Ship's Computer infrastructure service (no identity).
AD-431.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)

_SCHEMA_BASE = """
CREATE TABLE IF NOT EXISTS journal (
    id          TEXT PRIMARY KEY,
    timestamp   REAL NOT NULL,
    agent_id    TEXT NOT NULL,
    agent_type  TEXT NOT NULL DEFAULT '',
    tier        TEXT NOT NULL DEFAULT 'standard',
    model       TEXT NOT NULL DEFAULT '',
    prompt_tokens    INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens     INTEGER NOT NULL DEFAULT 0,
    latency_ms       REAL NOT NULL DEFAULT 0.0,
    intent           TEXT NOT NULL DEFAULT '',
    success          INTEGER NOT NULL DEFAULT 1,
    cached           INTEGER NOT NULL DEFAULT 0,
    request_id       TEXT NOT NULL DEFAULT '',
    prompt_hash      TEXT NOT NULL DEFAULT '',
    response_length  INTEGER NOT NULL DEFAULT 0,
    intent_id        TEXT NOT NULL DEFAULT '',
    dag_node_id      TEXT NOT NULL DEFAULT '',
    response_hash    TEXT NOT NULL DEFAULT '',
    procedure_id     TEXT NOT NULL DEFAULT '',
    correlation_id   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_journal_agent ON journal(agent_id);
CREATE INDEX IF NOT EXISTS idx_journal_timestamp ON journal(timestamp);
CREATE INDEX IF NOT EXISTS idx_journal_intent ON journal(intent);
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_journal_intent_id ON journal(intent_id);
CREATE INDEX IF NOT EXISTS idx_journal_correlation_id ON journal(correlation_id);
"""


class CognitiveJournal:
    """Append-only SQLite journal for LLM reasoning traces."""

    def __init__(self, db_path: str | None = None, connection_factory: ConnectionFactory | None = None) -> None:
        self.db_path = db_path
        self._db: Any = None
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        if not self.db_path:
            return
        import aiosqlite
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        self._db = await self._connection_factory.connect(self.db_path)
        await self._db.execute("PRAGMA foreign_keys = ON")
        self._db.row_factory = __import__("aiosqlite").Row
        # AD-432: Migrate columns BEFORE full schema (indexes reference them)
        # Create base table first (without AD-432 columns for pre-existing DBs)
        await self._db.executescript(_SCHEMA_BASE)
        for col, typedef in [
            ("intent_id", "TEXT NOT NULL DEFAULT ''"),
            ("dag_node_id", "TEXT NOT NULL DEFAULT ''"),
            ("response_hash", "TEXT NOT NULL DEFAULT ''"),
            ("procedure_id", "TEXT NOT NULL DEFAULT ''"),  # AD-534: procedure replay tracking
            ("correlation_id", "TEXT NOT NULL DEFAULT ''"),  # AD-492: cognitive correlation ID
        ]:
            try:
                await self._db.execute(f"ALTER TABLE journal ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass  # Column already exists — migration idempotency
        await self._db.commit()
        # Now create indexes that depend on migrated columns
        await self._db.executescript(_SCHEMA_INDEXES)

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def wipe(self) -> None:
        """Delete all journal entries. Used by probos reset."""
        if not self._db:
            return
        try:
            await self._db.execute("DELETE FROM journal")
            await self._db.commit()
        except Exception:
            logger.debug("Journal wipe failed", exc_info=True)

    async def prune(self, retention_days: int = 14, max_rows: int = 500_000) -> int:
        """Delete journal entries older than retention_days and enforce max_rows.

        Returns number of rows deleted.
        """
        if not self._db:
            return 0

        import time as _time
        deleted = 0

        # Age-based pruning (timestamp is Unix epoch float)
        if retention_days > 0:
            cutoff = _time.time() - (retention_days * 86400)
            cursor = await self._db.execute(
                "DELETE FROM journal WHERE timestamp < ?", (cutoff,)
            )
            deleted += cursor.rowcount

        # Row-count cap
        if max_rows > 0:
            cursor = await self._db.execute("SELECT COUNT(*) FROM journal")
            row = await cursor.fetchone()
            total = row[0] if row else 0
            if total > max_rows:
                excess = total - max_rows
                cursor = await self._db.execute(
                    "DELETE FROM journal WHERE id IN "
                    "(SELECT id FROM journal ORDER BY timestamp ASC LIMIT ?)",
                    (excess,)
                )
                deleted += cursor.rowcount

        if deleted > 0:
            await self._db.commit()
            logger.info("CognitiveJournal pruned: %d entries removed", deleted)

        return deleted

    async def record(
        self,
        *,
        entry_id: str,
        timestamp: float,
        agent_id: str,
        agent_type: str = "",
        tier: str = "standard",
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: float = 0.0,
        intent: str = "",
        success: bool = True,
        cached: bool = False,
        request_id: str = "",
        prompt_hash: str = "",
        response_length: int = 0,
        intent_id: str = "",
        dag_node_id: str = "",
        response_hash: str = "",
        procedure_id: str = "",  # AD-534: procedure ID if this was a replay
        correlation_id: str = "",  # AD-492: cognitive cycle correlation ID
    ) -> None:
        """Append a journal entry. Fire-and-forget — never raises."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT OR IGNORE INTO journal
                   (id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, success, cached, request_id,
                    prompt_hash, response_length,
                    intent_id, dag_node_id, response_hash, procedure_id,
                    correlation_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, 1 if success else 0,
                    1 if cached else 0, request_id,
                    prompt_hash, response_length,
                    intent_id, dag_node_id, response_hash, procedure_id,
                    correlation_id,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("Journal record failed", exc_info=True)

    async def get_reasoning_chain(
        self, agent_id: str, *, limit: int = 20,
        since: float | None = None, until: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent journal entries for an agent, most recent first.

        Args:
            agent_id: Agent to query.
            limit: Max entries to return.
            since: Unix timestamp — only entries after this time.
            until: Unix timestamp — only entries before this time.
        """
        if not self._db:
            return []
        try:
            clauses = ["agent_id = ?"]
            params: list[Any] = [agent_id]
            if since is not None:
                clauses.append("timestamp >= ?")
                params.append(since)
            if until is not None:
                clauses.append("timestamp <= ?")
                params.append(until)
            where = " AND ".join(clauses)
            params.append(limit)
            cursor = await self._db.execute(
                f"SELECT * FROM journal WHERE {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Journal query failed", exc_info=True)
            return []

    async def get_token_usage(
        self, agent_id: str | None = None
    ) -> dict[str, Any]:
        """Token usage summary. If agent_id is None, returns ship-wide totals."""
        if not self._db:
            return {"total_tokens": 0, "total_calls": 0}
        try:
            if agent_id:
                cursor = await self._db.execute(
                    """SELECT COUNT(*) as calls,
                              SUM(total_tokens) as tokens,
                              SUM(prompt_tokens) as prompt_tok,
                              SUM(completion_tokens) as comp_tok,
                              AVG(latency_ms) as avg_latency
                       FROM journal WHERE agent_id = ? AND cached = 0""",
                    (agent_id,),
                )
            else:
                cursor = await self._db.execute(
                    """SELECT COUNT(*) as calls,
                              SUM(total_tokens) as tokens,
                              SUM(prompt_tokens) as prompt_tok,
                              SUM(completion_tokens) as comp_tok,
                              AVG(latency_ms) as avg_latency
                       FROM journal WHERE cached = 0""",
                )
            row = await cursor.fetchone()
            if row:
                return {
                    "total_calls": row["calls"] or 0,
                    "total_tokens": row["tokens"] or 0,
                    "prompt_tokens": row["prompt_tok"] or 0,
                    "completion_tokens": row["comp_tok"] or 0,
                    "avg_latency_ms": round(row["avg_latency"] or 0, 1),
                }
            return {"total_tokens": 0, "total_calls": 0}
        except Exception:
            logger.debug("Journal token query failed", exc_info=True)
            return {"total_tokens": 0, "total_calls": 0}

    async def get_token_usage_since(
        self, agent_id: str, since_timestamp: float
    ) -> int:
        """AD-617b: Get total tokens used by an agent since a given timestamp.

        Returns total_tokens (int). Used for hourly budget enforcement.
        Returns 0 on error (fail-open for queries, fail-closed for enforcement
        happens at the caller).
        """
        if not self._db:
            return 0
        try:
            cursor = await self._db.execute(
                """SELECT COALESCE(SUM(total_tokens), 0) as tokens
                   FROM journal
                   WHERE agent_id = ? AND timestamp >= ? AND cached = 0""",
                (agent_id, since_timestamp),
            )
            row = await cursor.fetchone()
            return int(row["tokens"]) if row else 0
        except Exception:
            logger.debug("Journal hourly query failed", exc_info=True)
            return 0

    async def get_token_usage_by(
        self, group_by: str = "model", agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Token usage grouped by a column (model, tier, agent_id, intent).

        Returns a list of dicts with the group key plus token/call stats.
        """
        if not self._db:
            return []
        # Whitelist allowed group columns to prevent SQL injection
        allowed = {"model", "tier", "agent_id", "agent_type", "intent"}
        if group_by not in allowed:
            return []
        try:
            where = "WHERE cached = 0"
            params: list[Any] = []
            if agent_id:
                where += " AND agent_id = ?"
                params.append(agent_id)
            cursor = await self._db.execute(
                f"""SELECT {group_by} as group_key,
                           COUNT(*) as calls,
                           SUM(total_tokens) as tokens,
                           SUM(prompt_tokens) as prompt_tok,
                           SUM(completion_tokens) as comp_tok,
                           AVG(latency_ms) as avg_latency
                    FROM journal {where}
                    GROUP BY {group_by}
                    ORDER BY tokens DESC""",
                params,
            )
            rows = await cursor.fetchall()
            return [
                {
                    group_by: row["group_key"],
                    "total_calls": row["calls"] or 0,
                    "total_tokens": row["tokens"] or 0,
                    "prompt_tokens": row["prompt_tok"] or 0,
                    "completion_tokens": row["comp_tok"] or 0,
                    "avg_latency_ms": round(row["avg_latency"] or 0, 1),
                }
                for row in rows
            ]
        except Exception:
            logger.debug("Journal grouped query failed", exc_info=True)
            return []

    async def get_decision_points(
        self,
        agent_id: str | None = None,
        *,
        min_latency_ms: float | None = None,
        failures_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find notable decision points — high-latency or failed LLM calls.

        Useful for diagnosing slow agents or finding patterns in failures.
        """
        if not self._db:
            return []
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if agent_id:
                clauses.append("agent_id = ?")
                params.append(agent_id)
            if min_latency_ms is not None:
                clauses.append("latency_ms >= ?")
                params.append(min_latency_ms)
            if failures_only:
                clauses.append("success = 0")
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            cursor = await self._db.execute(
                f"""SELECT * FROM journal {where}
                    ORDER BY latency_ms DESC
                    LIMIT ?""",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Journal decision points query failed", exc_info=True)
            return []

    async def get_stats(self) -> dict[str, Any]:
        """Overall journal statistics."""
        if not self._db:
            return {"total_entries": 0}
        try:
            cursor = await self._db.execute("SELECT COUNT(*) FROM journal")
            row = await cursor.fetchone()
            total = row[0] if row else 0

            cursor = await self._db.execute(
                """SELECT agent_type, COUNT(*) as cnt
                   FROM journal GROUP BY agent_type
                   ORDER BY cnt DESC LIMIT 10"""
            )
            by_type = {r["agent_type"]: r["cnt"] for r in await cursor.fetchall()}

            cursor = await self._db.execute(
                """SELECT intent, COUNT(*) as cnt
                   FROM journal GROUP BY intent
                   ORDER BY cnt DESC LIMIT 10"""
            )
            by_intent = {r["intent"]: r["cnt"] for r in await cursor.fetchall()}

            return {
                "total_entries": total,
                "by_agent_type": by_type,
                "by_intent": by_intent,
            }
        except Exception:
            logger.debug("Journal stats failed", exc_info=True)
            return {"total_entries": 0}
