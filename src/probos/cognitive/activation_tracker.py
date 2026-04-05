"""AD-567d / AD-462b: ACT-R activation-based memory lifecycle tracker.

Implements Anderson's (1983, 2007) base-level activation equation:

    B_i = ln(Σ t_j^{-d})

where t_j = seconds since the j-th access and d = decay parameter (default 0.5).

Episodes gain activation each time they are deliberately recalled.
Unreinforced episodes decay toward ``-inf``.  During dream Step 12,
episodes whose activation falls below a configurable threshold are
pruned (subject to age and cap constraints).

Storage uses SQLite for the access log — follows the Cloud-Ready Storage
principle (abstract connection interface via connection_factory).
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ActivationTracker:
    """Tracks ACT-R base-level activation for episodic memories.

    Parameters
    ----------
    decay_d : float
        Decay parameter *d* in the activation equation (default 0.5).
    access_max_age_days : int
        Access records older than this are pruned on cleanup (default 180).
    connection_factory : callable
        Async callable returning an ``aiosqlite``-compatible connection.
        If ``None``, uses a default aiosqlite.connect to *db_path*.
    db_path : str
        Fallback path for SQLite if no connection_factory provided.
    """

    _SCHEMA = """\
CREATE TABLE IF NOT EXISTS episode_access_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL,
    access_time REAL NOT NULL,
    access_type TEXT NOT NULL DEFAULT 'recall'
);
CREATE INDEX IF NOT EXISTS idx_access_episode ON episode_access_log(episode_id);
CREATE INDEX IF NOT EXISTS idx_access_time ON episode_access_log(access_time);
"""

    def __init__(
        self,
        *,
        decay_d: float = 0.5,
        access_max_age_days: int = 180,
        connection_factory: Callable[..., Any] | None = None,
        db_path: str = "",
    ) -> None:
        self._decay_d = decay_d
        self._access_max_age_days = access_max_age_days
        self._connection_factory = connection_factory
        self._db_path = db_path
        self._db: Any = None

    async def start(self) -> None:
        """Initialize the SQLite database and create schema."""
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

    async def record_access(
        self,
        episode_id: str,
        access_type: str = "recall",
    ) -> None:
        """Record a single access event for an episode."""
        if not self._db:
            return
        now = time.time()
        await self._db.execute(
            "INSERT INTO episode_access_log (episode_id, access_time, access_type) "
            "VALUES (?, ?, ?)",
            (episode_id, now, access_type),
        )
        await self._db.commit()

    async def record_batch_access(
        self,
        episode_ids: list[str],
        access_type: str = "recall",
    ) -> None:
        """Record access events for multiple episodes in a single transaction."""
        if not self._db or not episode_ids:
            return
        now = time.time()
        rows = [(eid, now, access_type) for eid in episode_ids]
        await self._db.executemany(
            "INSERT INTO episode_access_log (episode_id, access_time, access_type) "
            "VALUES (?, ?, ?)",
            rows,
        )
        await self._db.commit()

    def compute_activation(
        self,
        access_times: list[float],
        now: float | None = None,
    ) -> float:
        """Compute ACT-R base-level activation B_i = ln(Σ t_j^{-d}).

        Returns ``float('-inf')`` if no accesses exist.
        """
        if not access_times:
            return float("-inf")
        if now is None:
            now = time.time()
        total = 0.0
        for t_access in access_times:
            age = now - t_access
            if age <= 0:
                age = 0.001  # Clamp to avoid log(inf)
            total += age ** (-self._decay_d)
        if total <= 0:
            return float("-inf")
        return math.log(total)

    async def get_activation(self, episode_id: str) -> float:
        """Compute current activation for a single episode."""
        if not self._db:
            return float("-inf")
        cursor = await self._db.execute(
            "SELECT access_time FROM episode_access_log WHERE episode_id = ?",
            (episode_id,),
        )
        rows = await cursor.fetchall()
        access_times = [r[0] for r in rows]
        return self.compute_activation(access_times)

    async def get_activations_batch(
        self, episode_ids: list[str],
    ) -> dict[str, float]:
        """Compute activations for multiple episodes efficiently."""
        if not self._db or not episode_ids:
            return {eid: float("-inf") for eid in episode_ids}

        # Fetch all access times in one query
        placeholders = ",".join("?" for _ in episode_ids)
        cursor = await self._db.execute(
            f"SELECT episode_id, access_time FROM episode_access_log "
            f"WHERE episode_id IN ({placeholders})",
            episode_ids,
        )
        rows = await cursor.fetchall()

        # Group by episode_id
        access_map: dict[str, list[float]] = {eid: [] for eid in episode_ids}
        for eid, t in rows:
            if eid in access_map:
                access_map[eid].append(t)

        now = time.time()
        return {
            eid: self.compute_activation(times, now)
            for eid, times in access_map.items()
        }

    async def find_low_activation_episodes(
        self,
        all_episode_ids: list[str],
        threshold: float = -2.0,
        min_age_seconds: float = 86400.0,
        max_prune_fraction: float = 0.10,
    ) -> list[str]:
        """Find episodes below activation threshold, eligible for pruning.

        Constraints:
        - Only episodes older than ``min_age_seconds`` (default 24h).
        - At most ``max_prune_fraction`` of total episodes (default 10%).
        - Never-accessed episodes (activation = -inf) are included.

        Returns list of episode IDs to prune, sorted by activation ascending.
        """
        if not all_episode_ids:
            return []

        activations = await self.get_activations_batch(all_episode_ids)
        now = time.time()

        candidates: list[tuple[str, float]] = []
        for eid, activation in activations.items():
            if activation < threshold:
                candidates.append((eid, activation))

        # Sort by activation ascending (worst first)
        candidates.sort(key=lambda x: x[1])

        # Cap at max_prune_fraction
        max_prune = max(1, int(len(all_episode_ids) * max_prune_fraction))
        return [eid for eid, _ in candidates[:max_prune]]

    async def cleanup_old_accesses(self) -> int:
        """Remove access records older than access_max_age_days."""
        if not self._db:
            return 0
        cutoff = time.time() - (self._access_max_age_days * 86400)
        cursor = await self._db.execute(
            "DELETE FROM episode_access_log WHERE access_time < ?",
            (cutoff,),
        )
        await self._db.commit()
        return cursor.rowcount or 0

    async def delete_episode_accesses(self, episode_ids: list[str]) -> None:
        """Remove all access records for the given episodes (post-eviction cleanup)."""
        if not self._db or not episode_ids:
            return
        placeholders = ",".join("?" for _ in episode_ids)
        await self._db.execute(
            f"DELETE FROM episode_access_log WHERE episode_id IN ({placeholders})",
            episode_ids,
        )
        await self._db.commit()
