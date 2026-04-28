"""Trust network — Bayesian reputation scoring for agents."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

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
    dampening_factor: float = 1.0  # AD-558: applied dampening multiplier
    floor_hit: bool = False  # AD-558: True if update was absorbed by hard floor


# ---------------------------------------------------------------------------
# AD-558: Dampening state tracking
# ---------------------------------------------------------------------------

@dataclass
class _DampeningState:
    """Per-agent dampening tracker for consecutive same-direction trust updates."""
    consecutive_count: int = 0
    direction: str = ""  # "positive" or "negative"
    first_timestamp: float = 0.0
    last_timestamp: float = 0.0


@dataclass
class _CascadeState:
    """Network-level trust cascade circuit breaker."""
    recent_anomalies: list = field(default_factory=list)  # (timestamp, agent_id, department, delta)
    tripped: bool = False
    tripped_at: float = 0.0
    cooldown_until: float = 0.0


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
        dampening_config: Any | None = None,
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

        # AD-558: Dampening state
        self._dampening: dict[str, _DampeningState] = {}
        self._cascade = _CascadeState()
        self._get_department: Callable[[str], str | None] | None = None
        self._emit_event: Callable[[str, Any], None] | None = None
        self._floor_hit_count: int = 0
        self._tier_registry: Any = None

        # AD-558: Dampening config — use defaults if not provided
        if dampening_config is not None:
            self._dampening_config = dampening_config
        else:
            from probos.config import TrustDampeningConfig
            self._dampening_config = TrustDampeningConfig()

    def set_department_lookup(self, fn: Callable[[str], str | None]) -> None:
        """Inject department resolution for cascade detection. Called by runtime during startup."""
        self._get_department = fn

    def set_event_callback(self, fn: Callable[[str, Any], None]) -> None:
        """Inject event emission for trust updates. Called by runtime during startup."""
        self._emit_event = fn

    def set_tier_registry(self, registry: Any) -> None:
        """Inject agent tier registry for tier-aware filtering (AD-571)."""
        self._tier_registry = registry

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
        AD-558: Applies progressive dampening, hard floor, and cascade dampening.
        """
        cfg = self._dampening_config
        if self._tier_registry:
            from probos.substrate.agent_tier import AgentTier
            if self._tier_registry.get_tier(agent_id) == AgentTier.CORE_INFRASTRUCTURE:
                return self.get_score(agent_id)

        record = self.get_or_create(agent_id)
        old_score = record.score
        now = time.monotonic()

        # --- AD-558 Part 1: Progressive dampening ---
        direction = "positive" if success else "negative"
        state = self._dampening.get(agent_id)
        if state is None:
            state = _DampeningState()
            self._dampening[agent_id] = state

        if state.direction == direction and (now - state.first_timestamp) < cfg.dampening_window_seconds:
            state.consecutive_count += 1
        else:
            state.consecutive_count = 1
            state.direction = direction
            state.first_timestamp = now
        state.last_timestamp = now

        factors = cfg.dampening_geometric_factors
        dampening_factor = factors[min(state.consecutive_count - 1, len(factors) - 1)]

        # Cold-start scaling: more aggressive dampening when few observations
        if (record.alpha + record.beta) < cfg.cold_start_observation_threshold:
            dampening_factor = max(dampening_factor, cfg.cold_start_dampening_floor)

        # --- AD-558 Part 3: Global cascade dampening multiplier ---
        if self._cascade.tripped:
            if now < self._cascade.cooldown_until:
                dampening_factor *= cfg.cascade_global_dampening
            else:
                # Cooldown expired — reset breaker
                self._cascade.tripped = False
                self._cascade.recent_anomalies.clear()
                logger.info("AD-558: Trust cascade breaker reset after cooldown")

        effective_weight = weight * dampening_factor

        # --- AD-558 Part 2: Hard trust floor ---
        floor_hit = False
        current_score = record.score
        if not success and current_score <= cfg.hard_trust_floor:
            floor_hit = True
            self._floor_hit_count += 1
            logger.info(
                "AD-558: Hard floor hit for agent=%s score=%.3f — negative update absorbed",
                agent_id[:8], current_score,
            )
            # Record event but do NOT apply weight
            self._event_log.append(TrustEvent(
                timestamp=now,
                agent_id=agent_id,
                success=success,
                old_score=old_score,
                new_score=current_score,
                weight=weight,
                intent_type=intent_type,
                episode_id=episode_id,
                verifier_id=verifier_id,
                dampening_factor=dampening_factor,
                floor_hit=True,
            ))
            # Emit event even for floor hits
            if self._emit_event:
                self._emit_event("trust_update", {
                    "agent_id": agent_id,
                    "old_score": old_score,
                    "new_score": current_score,
                    "success": success,
                    "dampening_factor": dampening_factor,
                    "floor_hit": True,
                })
            return current_score

        # Apply effective weight
        if success:
            record.alpha += effective_weight
        else:
            record.beta += effective_weight

        new_score = record.score

        # Append causal event to the ring buffer
        self._event_log.append(TrustEvent(
            timestamp=now,
            agent_id=agent_id,
            success=success,
            old_score=old_score,
            new_score=new_score,
            weight=weight,
            intent_type=intent_type,
            episode_id=episode_id,
            verifier_id=verifier_id,
            dampening_factor=dampening_factor,
            floor_hit=False,
        ))

        logger.debug(
            "Trust updated: agent=%s success=%s alpha=%.2f beta=%.2f score=%.3f dampening=%.2f",
            agent_id[:8],
            success,
            record.alpha,
            record.beta,
            record.score,
            dampening_factor,
        )

        # --- AD-558 Part 4: Event emission ---
        if self._emit_event:
            self._emit_event("trust_update", {
                "agent_id": agent_id,
                "old_score": old_score,
                "new_score": new_score,
                "success": success,
                "dampening_factor": dampening_factor,
                "floor_hit": False,
            })

        # --- AD-558 Part 3: Cascade detection ---
        delta = abs(new_score - old_score)
        if delta > cfg.cascade_delta_threshold:
            dept = None
            if self._get_department:
                try:
                    dept = self._get_department(agent_id)
                except Exception:
                    pass
            self._cascade.recent_anomalies.append((now, agent_id, dept, delta))
            # Prune anomalies outside window
            cutoff = now - cfg.cascade_window_seconds
            self._cascade.recent_anomalies = [
                a for a in self._cascade.recent_anomalies if a[0] >= cutoff
            ]
            # Check trip conditions
            if not self._cascade.tripped:
                unique_agents = {a[1] for a in self._cascade.recent_anomalies}
                if self._tier_registry:
                    unique_agents = {a for a in unique_agents if self._tier_registry.is_crew(a)}
                unique_depts = {a[2] for a in self._cascade.recent_anomalies if a[2] is not None}
                agent_count_met = len(unique_agents) >= cfg.cascade_agent_threshold
                # If no department lookup, skip department check
                dept_count_met = (
                    len(unique_depts) >= cfg.cascade_department_threshold
                    if self._get_department
                    else True
                )
                if agent_count_met and dept_count_met:
                    self._cascade.tripped = True
                    self._cascade.tripped_at = now
                    self._cascade.cooldown_until = now + cfg.cascade_cooldown_seconds
                    logger.warning(
                        "AD-558: Trust cascade breaker TRIPPED — %d agents across %d departments, "
                        "global dampening=%.2f for %.0fs",
                        len(unique_agents), len(unique_depts),
                        cfg.cascade_global_dampening, cfg.cascade_cooldown_seconds,
                    )
                    # Emit cascade warning event
                    if self._emit_event:
                        self._emit_event("trust_cascade_warning", {
                            "anomalous_agents": list(unique_agents),
                            "departments_affected": list(unique_depts),
                            "global_dampening_factor": cfg.cascade_global_dampening,
                            "cooldown_seconds": cfg.cascade_cooldown_seconds,
                        })

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

    def all_scores(self, crew_only: bool = False) -> dict[AgentID, float]:
        """Return all agent trust scores."""
        if crew_only and self._tier_registry:
            return {
                aid: r.score
                for aid, r in self._records.items()
                if self._tier_registry.is_crew(aid)
            }
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
    # AD-558: Dampening telemetry
    # ------------------------------------------------------------------

    def get_dampening_telemetry(self) -> dict:
        """Return current dampening state for vitals/telemetry."""
        cfg = self._dampening_config
        now = time.monotonic()
        return {
            "per_agent": {
                agent_id: {
                    "dampening_factor": cfg.dampening_geometric_factors[
                        min(state.consecutive_count - 1, len(cfg.dampening_geometric_factors) - 1)
                    ] if state.consecutive_count > 0 else 1.0,
                    "consecutive_count": state.consecutive_count,
                    "direction": state.direction,
                }
                for agent_id, state in self._dampening.items()
            },
            "cascade_breaker": {
                "tripped": self._cascade.tripped,
                "cooldown_remaining": max(0.0, self._cascade.cooldown_until - now),
                "anomaly_count": len(self._cascade.recent_anomalies),
            },
            "floor_hits": self._floor_hit_count,
        }

    def reset_floor_hit_count(self) -> None:
        """Reset the floor hit counter (called after dream cycles)."""
        self._floor_hit_count = 0

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
