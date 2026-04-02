"""Trust network — Bayesian reputation scoring for agents."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from probos.config import format_trust
from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.types import AgentID

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trust_scores (
    agent_id TEXT PRIMARY KEY,
    alpha    REAL NOT NULL DEFAULT 2.0,
    beta     REAL NOT NULL DEFAULT 2.0,
    updated  TEXT NOT NULL
);
"""


@dataclass
class TrustRecord:
    """Bayesian trust record for an agent.

    Uses a Beta distribution parameterized by (alpha, beta) where:
    - alpha = prior + observed successes
    - beta = prior + observed failures
    - E[trust] = alpha / (alpha + beta)
    - Variance decreases with more observations (higher certainty)
    """

    agent_id: AgentID
    alpha: float = 2.0  # Prior + successes
    beta: float = 2.0  # Prior + failures

    @property
    def score(self) -> float:
        """Expected trust score: E[Beta(alpha, beta)] = alpha / (alpha + beta)."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def observations(self) -> float:
        """Total observations (excluding prior)."""
        return (self.alpha - 2.0) + (self.beta - 2.0)

    @property
    def uncertainty(self) -> float:
        """Uncertainty in the trust estimate. High when few observations."""
        n = self.alpha + self.beta
        if n <= 0:
            return 1.0
        return math.sqrt((self.alpha * self.beta) / (n * n * (n + 1)))


@dataclass
class TrustEvent:
    """A single trust change with causal context."""

    timestamp: float
    agent_id: str
    success: bool
    old_score: float
    new_score: float
    weight: float  # Shapley weight used
    intent_type: str  # which intent was being processed
    episode_id: str  # which episode this belongs to
    verifier_id: str  # which red-team agent verified


class TrustNetwork:
    """Network-wide Bayesian trust scoring.

    Each agent has a Beta(alpha, beta) trust distribution. The expected
    value alpha/(alpha+beta) is their trust score. Observations (success/failure)
    shift the distribution. Trust decays slowly over time to allow recovery.

    Persists to SQLite so trust survives across restarts.
    """

    def __init__(
        self,
        prior_alpha: float = 2.0,
        prior_beta: float = 2.0,
        decay_rate: float = 0.999,
        db_path: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta
        self.decay_rate = decay_rate
        self.db_path = db_path
        self._records: dict[AgentID, TrustRecord] = {}
        self._db: DatabaseConnection | None = None
        self._event_log: deque[TrustEvent] = deque(maxlen=500)
        self._lock = asyncio.Lock()  # BF-099: concurrency protection
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        """Initialize — load trust scores from SQLite if configured."""
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA foreign_keys = ON")
            await self._db.execute(_SCHEMA)
            await self._db.commit()
            await self._load_from_db()
            logger.info(
                "TrustNetwork loaded %d records from %s",
                len(self._records),
                self.db_path,
            )

    async def stop(self) -> None:
        """Persist trust scores and close DB."""
        if self._db:
            await self._save_to_db()
            await self._db.close()
            self._db = None

    def get_or_create(self, agent_id: AgentID) -> TrustRecord:
        """Get an agent's trust record, creating with priors if new."""
        if agent_id not in self._records:
            self._records[agent_id] = TrustRecord(
                agent_id=agent_id,
                alpha=self.prior_alpha,
                beta=self.prior_beta,
            )
        return self._records[agent_id]

    def create_with_prior(self, agent_id: AgentID, alpha: float, beta: float) -> None:
        """Create a trust record with a custom Beta prior.

        Used for probationary agents (e.g., self-created with alpha=1, beta=3).
        If the agent already has a trust record, this is a no-op.
        """
        if agent_id not in self._records:
            self._records[agent_id] = TrustRecord(
                agent_id=agent_id,
                alpha=alpha,
                beta=beta,
            )

    def record_outcome(
        self,
        agent_id: AgentID,
        success: bool,
        weight: float = 1.0,
        intent_type: str = "",
        episode_id: str = "",
        verifier_id: str = "",
        source: str = "verification",
    ) -> float:
        """Record an observation and return the updated trust score.

        A successful outcome increases alpha. A failure increases beta.
        The weight parameter scales the update (partial trust/distrust).
        """
        record = self.get_or_create(agent_id)
        old_score = record.score
        if success:
            record.alpha += weight
        else:
            record.beta += weight

        new_score = record.score

        # Append causal event to the ring buffer
        self._event_log.append(TrustEvent(
            timestamp=time.monotonic(),
            agent_id=agent_id,
            success=success,
            old_score=old_score,
            new_score=new_score,
            weight=weight,
            intent_type=intent_type,
            episode_id=episode_id,
            verifier_id=verifier_id,
        ))

        logger.debug(
            "Trust updated: agent=%s success=%s alpha=%.2f beta=%.2f score=%.3f",
            agent_id[:8],
            success,
            record.alpha,
            record.beta,
            record.score,
        )
        return record.score

    def get_score(self, agent_id: AgentID) -> float:
        """Get an agent's current trust score."""
        record = self._records.get(agent_id)
        if record is None:
            return self.prior_alpha / (self.prior_alpha + self.prior_beta)
        return record.score

    def get_record(self, agent_id: AgentID) -> TrustRecord | None:
        """Get the full trust record for an agent."""
        return self._records.get(agent_id)

    def get_recent_events(self, n: int = 50) -> list[TrustEvent]:
        """Return last N trust events."""
        events = list(self._event_log)
        return events[-n:]

    def get_events_for_agent(self, agent_id: str, n: int = 20) -> list[TrustEvent]:
        """Return last N trust events for a specific agent."""
        filtered = [e for e in self._event_log if e.agent_id == agent_id]
        return filtered[-n:]

    def get_events_since(self, timestamp: float) -> list[TrustEvent]:
        """Return all trust events since a given monotonic timestamp."""
        return [e for e in self._event_log if e.timestamp >= timestamp]

    def decay_all(self) -> None:
        """Apply decay to all trust records, pulling them toward the prior.

        This allows agents to recover trust over time if they stop failing.
        """
        for record in self._records.values():
            # Decay toward priors
            record.alpha = self.prior_alpha + (record.alpha - self.prior_alpha) * self.decay_rate
            record.beta = self.prior_beta + (record.beta - self.prior_beta) * self.decay_rate

    def remove(self, agent_id: AgentID) -> None:
        """Remove an agent's trust record. Delegates to remove_agent."""
        self.remove_agent(agent_id)

    def remove_agent(self, agent_id: AgentID) -> None:
        """Remove an agent's trust record. Public API for AD-514."""
        if agent_id in self._records:
            del self._records[agent_id]
            logger.info("Trust record removed for agent %s", agent_id)

    def reconcile(self, active_agent_ids: set[str]) -> int:
        """Remove trust records for agents not in the active set. Returns count removed."""
        stale = [aid for aid in self._records if aid not in active_agent_ids]
        for aid in stale:
            del self._records[aid]
        return len(stale)

    @property
    def agent_count(self) -> int:
        return len(self._records)

    def all_scores(self) -> dict[AgentID, float]:
        """Return all agent trust scores."""
        return {aid: r.score for aid, r in self._records.items()}

    def raw_scores(self) -> dict[AgentID, dict[str, float]]:
        """Return raw Beta distribution parameters for all agents (AD-168).

        Returns {agent_id: {"alpha": float, "beta": float, "observations": float}}.
        These are the raw parameters, not derived mean scores.
        """
        return {
            aid: {
                "alpha": r.alpha,
                "beta": r.beta,
                "observations": r.observations,
            }
            for aid, r in self._records.items()
        }

    def summary(self) -> list[dict[str, Any]]:
        """Return a summary of all trust records."""
        return [
            {
                "agent_id": r.agent_id,
                "score": format_trust(r.score),
                "alpha": format_trust(r.alpha, 2),
                "beta": format_trust(r.beta, 2),
                "uncertainty": format_trust(r.uncertainty),
                "observations": round(r.observations, 1),
            }
            for r in sorted(
                self._records.values(), key=lambda r: r.score, reverse=True
            )
        ]

    # ------------------------------------------------------------------
    # SQLite persistence
    # ------------------------------------------------------------------

    async def _load_from_db(self) -> None:
        if not self._db:
            return
        async with self._lock:
            async with self._db.execute(
                "SELECT agent_id, alpha, beta FROM trust_scores"
            ) as cursor:
                async for row in cursor:
                    self._records[row[0]] = TrustRecord(
                        agent_id=row[0],
                        alpha=row[1],
                        beta=row[2],
                    )

    async def _save_to_db(self) -> None:
        if not self._db:
            return
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            await self._db.execute("BEGIN IMMEDIATE")
            try:
                await self._db.execute("DELETE FROM trust_scores")
                for record in self._records.values():
                    await self._db.execute(
                        "INSERT INTO trust_scores (agent_id, alpha, beta, updated) "
                        "VALUES (?, ?, ?, ?)",
                        (record.agent_id, record.alpha, record.beta, now),
                    )
                await self._db.commit()
            except Exception:
                await self._db.execute("ROLLBACK")
                raise
        logger.debug("Saved %d trust records to disk", len(self._records))

    async def save(self) -> None:
        """Manually trigger a save to disk."""
        await self._save_to_db()
