"""AD-570b: Episode Participant Index — SQLite sidecar junction table.

Indexes both agent_ids (sovereign IDs, role=author) and participants
(callsigns, role=participant) per episode.  Enables O(1) indexed lookups
for "find all episodes involving agent X" — replacing O(N) Python
post-retrieval filters in episodic.py.

Follows the ActivationTracker (AD-567d) / EvictionAudit (AD-541f)
sidecar pattern: abstract connection interface via connection_factory
for Cloud-Ready Storage.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ParticipantIndex:
    """SQLite sidecar that maps episodes ↔ agents/participants.

    Parameters
    ----------
    connection_factory : callable
        Async callable returning an ``aiosqlite``-compatible connection.
        If ``None``, uses a default aiosqlite.connect to *db_path*.
    db_path : str
        Fallback path for SQLite if no connection_factory provided.
    """

    _SCHEMA = """\
CREATE TABLE IF NOT EXISTS episode_participants (
    episode_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    callsign TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'author',
    PRIMARY KEY (episode_id, agent_id, role)
);
CREATE INDEX IF NOT EXISTS idx_ep_part_agent ON episode_participants(agent_id);
CREATE INDEX IF NOT EXISTS idx_ep_part_callsign ON episode_participants(callsign);
CREATE INDEX IF NOT EXISTS idx_ep_part_role ON episode_participants(role);
"""

    def __init__(
        self,
        *,
        connection_factory: Callable[..., Any] | None = None,
        db_path: str = "",
    ) -> None:
        self._connection_factory = connection_factory
        self._db_path = db_path
        self._db: Any = None

    async def start(self) -> None:
        """Initialize SQLite connection and create schema."""
        if self._connection_factory:
            self._db = await self._connection_factory()
        else:
            import aiosqlite
            self._db = await aiosqlite.connect(self._db_path)
        for stmt in self._SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await self._db.execute(stmt)
        await self._db.commit()

    async def stop(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def record_episode(
        self,
        episode_id: str,
        agent_ids: list[str],
        participants: list[str],
    ) -> None:
        """Index all agents and participants for a single episode.

        - For each agent_id in agent_ids: INSERT OR IGNORE with role='author', callsign=''
        - For each participant in participants: INSERT OR IGNORE with role='participant',
          agent_id=participant, callsign=participant
        """
        if not self._db:
            return
        for aid in agent_ids:
            await self._db.execute(
                "INSERT OR IGNORE INTO episode_participants "
                "(episode_id, agent_id, callsign, role) VALUES (?, ?, ?, ?)",
                (episode_id, aid, "", "author"),
            )
        for p in participants:
            await self._db.execute(
                "INSERT OR IGNORE INTO episode_participants "
                "(episode_id, agent_id, callsign, role) VALUES (?, ?, ?, ?)",
                (episode_id, p, p, "participant"),
            )
        await self._db.commit()

    async def record_episode_batch(
        self,
        records: list[tuple[str, list[str], list[str]]],
    ) -> None:
        """Bulk insert for seed/migration. Each tuple is (episode_id, agent_ids, participants)."""
        if not self._db or not records:
            return
        rows: list[tuple[str, str, str, str]] = []
        for episode_id, agent_ids, participants in records:
            for aid in agent_ids:
                rows.append((episode_id, aid, "", "author"))
            for p in participants:
                rows.append((episode_id, p, p, "participant"))
        if rows:
            await self._db.executemany(
                "INSERT OR IGNORE INTO episode_participants "
                "(episode_id, agent_id, callsign, role) VALUES (?, ?, ?, ?)",
                rows,
            )
            await self._db.commit()

    async def get_episode_ids_for_agent(self, agent_id: str) -> list[str]:
        """Return all episode IDs where this sovereign ID appears (any role)."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT DISTINCT episode_id FROM episode_participants WHERE agent_id = ?",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

    async def get_episode_ids_for_callsign(self, callsign: str) -> list[str]:
        """Return all episode IDs where this callsign appears as participant."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT DISTINCT episode_id FROM episode_participants WHERE callsign = ?",
            (callsign,),
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

    async def get_episode_ids_for_participants(
        self,
        participants: list[str],
        require_all: bool = False,
    ) -> list[str]:
        """Return episode IDs matching any (or all) of the given callsigns.

        If require_all=False (default): OR semantics — any participant present.
        If require_all=True: AND semantics — all participants must be present.
        """
        if not self._db or not participants:
            return []
        placeholders = ",".join("?" for _ in participants)
        if require_all:
            cursor = await self._db.execute(
                f"SELECT episode_id FROM episode_participants "
                f"WHERE callsign IN ({placeholders}) "
                f"GROUP BY episode_id "
                f"HAVING COUNT(DISTINCT callsign) = ?",
                (*participants, len(participants)),
            )
        else:
            cursor = await self._db.execute(
                f"SELECT DISTINCT episode_id FROM episode_participants "
                f"WHERE callsign IN ({placeholders})",
                participants,
            )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

    async def count_for_agent(self, agent_id: str) -> int:
        """Return count of episodes for this agent. Replaces O(N) full-collection scan."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "SELECT COUNT(DISTINCT episode_id) FROM episode_participants WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def delete_episodes(self, episode_ids: list[str]) -> None:
        """Remove all participant records for the given episode IDs. For eviction cleanup."""
        if not self._db or not episode_ids:
            return
        # Process in batches of 500 to avoid SQLite variable limit
        batch_size = 500
        for i in range(0, len(episode_ids), batch_size):
            batch = episode_ids[i:i + batch_size]
            placeholders = ",".join("?" for _ in batch)
            await self._db.execute(
                f"DELETE FROM episode_participants WHERE episode_id IN ({placeholders})",
                batch,
            )
        await self._db.commit()
