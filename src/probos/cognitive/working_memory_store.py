"""AD-573: Working memory persistence — freeze/restore across stasis.

SQLite-backed store following the TrustNetwork/HebbianRouter canonical
pattern: ConnectionFactory for Cloud-Ready Storage, start()/stop()
lifecycle, BEGIN IMMEDIATE + asyncio.Lock for concurrency safety.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS working_memory (
    agent_id    TEXT PRIMARY KEY,
    state_json  TEXT NOT NULL,
    updated     REAL NOT NULL
);
"""


class WorkingMemoryStore:
    """SQLite persistence for AgentWorkingMemory state.

    Follows the TrustNetwork/HebbianRouter pattern:
    - ConnectionFactory for Cloud-Ready Storage (swap SQLite → Postgres)
    - start()/stop() lifecycle
    - BEGIN IMMEDIATE + asyncio.Lock for concurrency safety
    """

    def __init__(self, *, connection_factory: Any = None, db_path: str = "") -> None:
        self._factory = connection_factory
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._conn: Any = None

    async def start(self) -> None:
        if self._factory and self._db_path:
            self._conn = await self._factory.connect(self._db_path)
            await self._conn.executescript(_SCHEMA)
            await self._conn.commit()

    async def stop(self) -> None:
        if self._conn:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    async def save(self, agent_id: str, state: dict[str, Any]) -> None:
        """Serialize one agent's working memory to disk."""
        if not self._conn:
            return
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                await self._conn.execute(
                    "INSERT OR REPLACE INTO working_memory (agent_id, state_json, updated) "
                    "VALUES (?, ?, ?)",
                    (agent_id, json.dumps(state), time.time()),
                )
                await self._conn.commit()
            except Exception:
                await self._conn.rollback()
                raise

    async def save_all(self, states: dict[str, dict[str, Any]]) -> None:
        """Batch save all agents' working memory (shutdown path)."""
        if not self._conn:
            return
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                for agent_id, state in states.items():
                    await self._conn.execute(
                        "INSERT OR REPLACE INTO working_memory (agent_id, state_json, updated) "
                        "VALUES (?, ?, ?)",
                        (agent_id, json.dumps(state), time.time()),
                    )
                await self._conn.commit()
            except Exception:
                await self._conn.rollback()
                raise

    async def load(self, agent_id: str) -> dict[str, Any] | None:
        """Load one agent's frozen working memory."""
        if not self._conn:
            return None
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT state_json FROM working_memory WHERE agent_id = ?",
                (agent_id,),
            )
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
        return None

    async def load_all(self) -> dict[str, dict[str, Any]]:
        """Load all agents' frozen working memory (startup path)."""
        if not self._conn:
            return {}
        result: dict[str, dict[str, Any]] = {}
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT agent_id, state_json FROM working_memory"
            )
            rows = await cursor.fetchall()
            for row in rows:
                try:
                    result[row[0]] = json.loads(row[1])
                except Exception:
                    logger.debug("AD-573: Failed to deserialize WM for %s", row[0])
        return result

    async def clear(self) -> None:
        """Clear all working memory state (used on ``probos reset``)."""
        if not self._conn:
            return
        async with self._lock:
            await self._conn.execute("DELETE FROM working_memory")
            await self._conn.commit()
