"""Cognitive Journal — append-only LLM reasoning trace store.

Records every LLM call with agent, tier, model, tokens, latency, and
intent linkage.  Ship's Computer infrastructure service (no identity).
AD-431.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
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
    response_length  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_journal_agent ON journal(agent_id);
CREATE INDEX IF NOT EXISTS idx_journal_timestamp ON journal(timestamp);
CREATE INDEX IF NOT EXISTS idx_journal_intent ON journal(intent);
"""


class CognitiveJournal:
    """Append-only SQLite journal for LLM reasoning traces."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path
        self._db: Any = None

    async def start(self) -> None:
        if not self.db_path:
            return
        import aiosqlite
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = __import__("aiosqlite").Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

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
                    prompt_hash, response_length)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, 1 if success else 0,
                    1 if cached else 0, request_id,
                    prompt_hash, response_length,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("Journal record failed", exc_info=True)

    async def get_reasoning_chain(
        self, agent_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return recent journal entries for an agent, most recent first."""
        if not self._db:
            return []
        try:
            cursor = await self._db.execute(
                """SELECT * FROM journal
                   WHERE agent_id = ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (agent_id, limit),
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
