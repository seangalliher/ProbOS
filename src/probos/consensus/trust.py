"""Trust network — Bayesian reputation scoring for agents."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import aiosqlite

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
    ) -> None:
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta
        self.decay_rate = decay_rate
        self.db_path = db_path
        self._records: dict[AgentID, TrustRecord] = {}
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        """Initialize — load trust scores from SQLite if configured."""
        if self.db_path:
            self._db = await aiosqlite.connect(self.db_path)
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
    ) -> float:
        """Record an observation and return the updated trust score.

        A successful outcome increases alpha. A failure increases beta.
        The weight parameter scales the update (partial trust/distrust).
        """
        record = self.get_or_create(agent_id)
        if success:
            record.alpha += weight
        else:
            record.beta += weight

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

    def decay_all(self) -> None:
        """Apply decay to all trust records, pulling them toward the prior.

        This allows agents to recover trust over time if they stop failing.
        """
        for record in self._records.values():
            # Decay toward priors
            record.alpha = self.prior_alpha + (record.alpha - self.prior_alpha) * self.decay_rate
            record.beta = self.prior_beta + (record.beta - self.prior_beta) * self.decay_rate

    def remove(self, agent_id: AgentID) -> None:
        """Remove an agent's trust record (agent recycled)."""
        self._records.pop(agent_id, None)

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
                "score": round(r.score, 4),
                "alpha": round(r.alpha, 2),
                "beta": round(r.beta, 2),
                "uncertainty": round(r.uncertainty, 4),
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
        await self._db.execute("DELETE FROM trust_scores")
        for record in self._records.values():
            await self._db.execute(
                "INSERT INTO trust_scores (agent_id, alpha, beta, updated) "
                "VALUES (?, ?, ?, ?)",
                (record.agent_id, record.alpha, record.beta, now),
            )
        await self._db.commit()
        logger.debug("Saved %d trust records to disk", len(self._records))

    async def save(self) -> None:
        """Manually trigger a save to disk."""
        await self._save_to_db()
