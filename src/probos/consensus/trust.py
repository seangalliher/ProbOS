"""Trust network — Bayesian reputation scoring for agents."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from probos.config import format_trust
from probos.consensus.crew_trust_effect import CrewTrustEffect
from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.types import AgentID

# AD-702: Diplomatic Relations — discounted trust transitivity tunables.
# Per Nooplex §4.3.4: T(A→C) = T(A→B) × T(B→C) × δ, with safety-critical
# override (no transitivity for destructive intents) and 90-day decay
# toward the network neutral baseline.
DEFAULT_TRANSITIVE_DISCOUNT: float = 0.85
DEFAULT_TRANSITIVE_MAX_HOPS: int = 3
DEFAULT_TRANSITIVE_DECAY_DAYS: float = 90.0
TRANSITIVE_NEUTRAL: float = 0.5  # Beta(2,2) mean

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trust_scores (
    agent_id TEXT PRIMARY KEY,
    alpha    REAL NOT NULL DEFAULT 2.0,
    beta     REAL NOT NULL DEFAULT 2.0,
    updated  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trust_outcome_receipts (
    outcome_id       TEXT PRIMARY KEY,
    payload_json     TEXT NOT NULL,
    payload_sha256   TEXT NOT NULL,
    agent_id         TEXT NOT NULL,
    session_id       TEXT NOT NULL,
    session_revision INTEGER NOT NULL,
    evidence_sha256  TEXT NOT NULL,
    result_alpha     REAL NOT NULL,
    result_beta      REAL NOT NULL,
    created_at       TEXT NOT NULL
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


@dataclass(frozen=True, slots=True)
class TrustOutcomeWriteResult:
    """Durable outcome disposition and resulting raw Beta parameters."""

    disposition: Literal["applied", "duplicate"]
    alpha: float
    beta: float

    def __post_init__(self) -> None:
        if (
            self.disposition not in {"applied", "duplicate"}
            or type(self.alpha) is not float
            or type(self.beta) is not float
            or not math.isfinite(self.alpha)
            or not math.isfinite(self.beta)
            or self.alpha <= 0.0
            or self.beta <= 0.0
        ):
            raise ValueError("trust_outcome_result_invalid")


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


@dataclass(frozen=True, slots=True)
class _OutcomePlan:
    agent_id: str
    alpha: float
    beta: float
    skipped: bool
    dampening: _DampeningState | None
    cascade_before_detection: _CascadeState
    cascade: _CascadeState
    event: TrustEvent | None
    emissions: tuple[tuple[str, dict[str, Any]], ...]
    floor_hit_delta: int
    cascade_reset: bool
    cascade_tripped: bool


@dataclass(frozen=True, slots=True)
class _TrustOutcomeInput:
    agent_id: AgentID
    success: bool
    weight: float
    intent_type: str
    episode_id: str
    verifier_id: str
    source: str


@dataclass(frozen=True, slots=True)
class _OutcomeSnapshot:
    receipt_result: tuple[float, float]
    current_raw: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class _OutcomeReconciliation:
    effect: CrewTrustEffect
    payload_json: str
    payload_sha256: str
    plan: _OutcomePlan
    write_error: BaseException


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
        self._outcome_transaction_inflight = False
        self._outcome_reconciliation: _OutcomeReconciliation | None = None
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
            await self._db.executescript(_SCHEMA)
            await self._migrate_outcome_receipt_results()
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
            database = self._db
            try:
                await self._save_to_db()
            finally:
                await database.close()
                if self._db is database:
                    self._db = None

    def get_or_create(self, agent_id: AgentID) -> TrustRecord:
        """Get an agent's trust record, creating with priors if new."""
        self._require_sync_mutation_available()
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
        self._require_sync_mutation_available()
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
        self._require_sync_mutation_available()
        outcome = _TrustOutcomeInput(
            agent_id=agent_id,
            success=success,
            weight=weight,
            intent_type=intent_type,
            episode_id=episode_id,
            verifier_id=verifier_id,
            source=source,
        )
        return self._record_outcome_now(outcome)

    def _require_sync_mutation_available(self) -> None:
        if (
            self._outcome_transaction_inflight
            or self._outcome_reconciliation is not None
        ):
            raise RuntimeError("trust_write_in_progress")

    def _record_outcome_now(self, outcome: _TrustOutcomeInput) -> float:
        plan = self._plan_outcome(outcome)
        self._publish_outcome_plan(plan)
        return plan.alpha / (plan.alpha + plan.beta)

    def _plan_outcome(self, outcome: _TrustOutcomeInput) -> _OutcomePlan:
        agent_id = outcome.agent_id
        existing = self._records.get(agent_id)
        alpha = existing.alpha if existing is not None else self.prior_alpha
        beta = existing.beta if existing is not None else self.prior_beta
        if self._tier_registry:
            from probos.substrate.agent_tier import AgentTier
            if self._tier_registry.get_tier(agent_id) == AgentTier.CORE_INFRASTRUCTURE:
                return _OutcomePlan(
                    agent_id=agent_id,
                    alpha=float(alpha),
                    beta=float(beta),
                    skipped=True,
                    dampening=None,
                    cascade_before_detection=self._copy_cascade(),
                    cascade=self._copy_cascade(),
                    event=None,
                    emissions=(),
                    floor_hit_delta=0,
                    cascade_reset=False,
                    cascade_tripped=False,
                )

        cfg = self._dampening_config
        old_score = alpha / (alpha + beta)
        now = time.monotonic()
        current_state = self._dampening.get(agent_id)
        state = _DampeningState(
            consecutive_count=(current_state.consecutive_count if current_state else 0),
            direction=(current_state.direction if current_state else ""),
            first_timestamp=(current_state.first_timestamp if current_state else 0.0),
            last_timestamp=(current_state.last_timestamp if current_state else 0.0),
        )
        direction = "positive" if outcome.success else "negative"
        if (
            state.direction == direction
            and (now - state.first_timestamp) < cfg.dampening_window_seconds
        ):
            state.consecutive_count += 1
        else:
            state.consecutive_count = 1
            state.direction = direction
            state.first_timestamp = now
        state.last_timestamp = now
        factors = cfg.dampening_geometric_factors
        dampening_factor = factors[
            min(state.consecutive_count - 1, len(factors) - 1)
        ]
        if (alpha + beta) < cfg.cold_start_observation_threshold:
            dampening_factor = max(
                dampening_factor,
                cfg.cold_start_dampening_floor,
            )

        cascade = self._copy_cascade()
        cascade_reset = False
        if cascade.tripped:
            if now < cascade.cooldown_until:
                dampening_factor *= cfg.cascade_global_dampening
            else:
                cascade.tripped = False
                cascade.recent_anomalies.clear()
                cascade_reset = True
        cascade_before_detection = self._clone_cascade(cascade)

        emissions: list[tuple[str, dict[str, Any]]] = []
        if not outcome.success and old_score <= cfg.hard_trust_floor:
            event = TrustEvent(
                timestamp=now,
                agent_id=agent_id,
                success=outcome.success,
                old_score=old_score,
                new_score=old_score,
                weight=outcome.weight,
                intent_type=outcome.intent_type,
                episode_id=outcome.episode_id,
                verifier_id=outcome.verifier_id,
                dampening_factor=dampening_factor,
                floor_hit=True,
            )
            emissions.append(("trust_update", {
                "agent_id": agent_id,
                "old_score": old_score,
                "new_score": old_score,
                "success": outcome.success,
                "dampening_factor": dampening_factor,
                "floor_hit": True,
            }))
            return _OutcomePlan(
                agent_id=agent_id,
                alpha=float(alpha),
                beta=float(beta),
                skipped=False,
                dampening=state,
                cascade_before_detection=cascade_before_detection,
                cascade=cascade,
                event=event,
                emissions=tuple(emissions),
                floor_hit_delta=1,
                cascade_reset=cascade_reset,
                cascade_tripped=False,
            )

        effective_weight = outcome.weight * dampening_factor
        if outcome.success:
            alpha += effective_weight
        else:
            beta += effective_weight
        new_score = alpha / (alpha + beta)
        event = TrustEvent(
            timestamp=now,
            agent_id=agent_id,
            success=outcome.success,
            old_score=old_score,
            new_score=new_score,
            weight=outcome.weight,
            intent_type=outcome.intent_type,
            episode_id=outcome.episode_id,
            verifier_id=outcome.verifier_id,
            dampening_factor=dampening_factor,
            floor_hit=False,
        )
        emissions.append(("trust_update", {
            "agent_id": agent_id,
            "old_score": old_score,
            "new_score": new_score,
            "success": outcome.success,
            "dampening_factor": dampening_factor,
            "floor_hit": False,
        }))

        cascade_tripped = False
        delta = abs(new_score - old_score)
        if delta > cfg.cascade_delta_threshold:
            department = None
            if self._get_department:
                try:
                    department = self._get_department(agent_id)
                except Exception:
                    pass
            cascade.recent_anomalies.append((now, agent_id, department, delta))
            cutoff = now - cfg.cascade_window_seconds
            cascade.recent_anomalies = [
                anomaly
                for anomaly in cascade.recent_anomalies
                if anomaly[0] >= cutoff
            ]
            if not cascade.tripped:
                unique_agents = {
                    anomaly[1] for anomaly in cascade.recent_anomalies
                }
                if self._tier_registry:
                    unique_agents = {
                        candidate
                        for candidate in unique_agents
                        if self._tier_registry.is_crew(candidate)
                    }
                unique_departments = {
                    anomaly[2]
                    for anomaly in cascade.recent_anomalies
                    if anomaly[2] is not None
                }
                if (
                    len(unique_agents) >= cfg.cascade_agent_threshold
                    and (
                        len(unique_departments) >= cfg.cascade_department_threshold
                        if self._get_department
                        else True
                    )
                ):
                    cascade.tripped = True
                    cascade.tripped_at = now
                    cascade.cooldown_until = now + cfg.cascade_cooldown_seconds
                    cascade_tripped = True
                    emissions.append(("trust_cascade_warning", {
                        "anomalous_agents": list(unique_agents),
                        "departments_affected": list(unique_departments),
                        "global_dampening_factor": cfg.cascade_global_dampening,
                        "cooldown_seconds": cfg.cascade_cooldown_seconds,
                    }))
        return _OutcomePlan(
            agent_id=agent_id,
            alpha=float(alpha),
            beta=float(beta),
            skipped=False,
            dampening=state,
            cascade_before_detection=cascade_before_detection,
            cascade=cascade,
            event=event,
            emissions=tuple(emissions),
            floor_hit_delta=0,
            cascade_reset=cascade_reset,
            cascade_tripped=cascade_tripped,
        )

    def _copy_cascade(self) -> _CascadeState:
        return self._clone_cascade(self._cascade)

    @staticmethod
    def _clone_cascade(state: _CascadeState) -> _CascadeState:
        return _CascadeState(
            recent_anomalies=list(state.recent_anomalies),
            tripped=state.tripped,
            tripped_at=state.tripped_at,
            cooldown_until=state.cooldown_until,
        )

    def _publish_outcome_plan(
        self,
        plan: _OutcomePlan,
        *,
        publish_raw: bool = True,
    ) -> None:
        if plan.skipped:
            return
        if publish_raw:
            record = self._records.get(plan.agent_id)
            if record is None:
                record = TrustRecord(agent_id=plan.agent_id)
                self._records[plan.agent_id] = record
            record.alpha = plan.alpha
            record.beta = plan.beta
        if plan.dampening is not None:
            self._dampening[plan.agent_id] = plan.dampening
        self._cascade = plan.cascade_before_detection
        self._floor_hit_count += plan.floor_hit_delta
        if plan.event is not None:
            self._event_log.append(plan.event)
            if plan.event.floor_hit:
                logger.info(
                    "AD-558: Hard floor hit for agent=%s score=%.3f — negative update absorbed",
                    plan.agent_id[:8],
                    plan.event.new_score,
                )
            else:
                logger.debug(
                    "Trust updated: agent=%s success=%s alpha=%.2f beta=%.2f "
                    "score=%.3f dampening=%.2f",
                    plan.agent_id[:8],
                    plan.event.success,
                    plan.alpha,
                    plan.beta,
                    plan.event.new_score,
                    plan.event.dampening_factor,
                )
        if plan.cascade_reset:
            logger.info("AD-558: Trust cascade breaker reset after cooldown")
        if self._emit_event and plan.emissions:
            event_type, payload = plan.emissions[0]
            self._emit_event(event_type, payload)
        self._cascade = plan.cascade
        if plan.cascade_tripped:
            logger.warning(
                "AD-558: Trust cascade breaker TRIPPED — %d agents across %d "
                "departments, global dampening=%.2f for %.0fs",
                len({item[1] for item in plan.cascade.recent_anomalies}),
                len({
                    item[2]
                    for item in plan.cascade.recent_anomalies
                    if item[2] is not None
                }),
                self._dampening_config.cascade_global_dampening,
                self._dampening_config.cascade_cooldown_seconds,
            )
        if self._emit_event:
            for event_type, payload in plan.emissions[1:]:
                self._emit_event(event_type, payload)

    async def record_outcome_once(
        self,
        effect: CrewTrustEffect,
    ) -> TrustOutcomeWriteResult:
        """Atomically apply one exact durable CrewSession outcome once."""
        if type(effect) is not CrewTrustEffect:
            raise ValueError("crew_trust_effect_invalid")
        canonical = effect.canonical_bytes()
        payload_json = canonical.decode("utf-8")
        payload_sha = hashlib.sha256(canonical).hexdigest()
        if self._db is None:
            raise RuntimeError("trust_outcome_store_not_started")

        async with self._lock:
            self._outcome_transaction_inflight = True
            try:
                reservation = self._outcome_reconciliation
                if reservation is not None:
                    if not self._reservation_matches(
                        reservation,
                        effect=effect,
                        payload_json=payload_json,
                        payload_sha=payload_sha,
                    ):
                        raise RuntimeError(
                            "trust_outcome_reconciliation_required",
                        )
                    return await self._reconcile_reserved_outcome(reservation)
                return await self._record_outcome_once_locked(
                    effect=effect,
                    payload_json=payload_json,
                    payload_sha=payload_sha,
                )
            finally:
                self._outcome_transaction_inflight = False

    async def _record_outcome_once_locked(
        self,
        *,
        effect: CrewTrustEffect,
        payload_json: str,
        payload_sha: str,
    ) -> TrustOutcomeWriteResult:
        if self._db is None:
            raise RuntimeError("trust_outcome_store_not_started")
        plan: _OutcomePlan | None = None
        try:
            await self._db.execute("BEGIN IMMEDIATE")
            row = await self._fetch_outcome_snapshot_row(effect.outcome_id)
            if row is not None:
                snapshot = self._validate_outcome_snapshot(
                    row,
                    effect=effect,
                    payload_json=payload_json,
                    payload_sha=payload_sha,
                )
                await self._db.execute("ROLLBACK")
                self._reconcile_raw_record(effect.agent_id, snapshot.current_raw)
                return TrustOutcomeWriteResult(
                    disposition="duplicate",
                    alpha=snapshot.receipt_result[0],
                    beta=snapshot.receipt_result[1],
                )

            plan = self._plan_outcome(_TrustOutcomeInput(
                agent_id=effect.agent_id,
                success=effect.success,
                weight=effect.weight,
                intent_type=effect.intent_type,
                episode_id=effect.outcome_id,
                verifier_id=effect.verifier_id,
                source=effect.source,
            ))
            if not plan.skipped:
                await self._db.execute(
                    "INSERT INTO trust_scores (agent_id, alpha, beta, updated) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(agent_id) DO UPDATE SET "
                    "alpha = excluded.alpha, beta = excluded.beta, "
                    "updated = excluded.updated",
                    (
                        effect.agent_id,
                        plan.alpha,
                        plan.beta,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            await self._db.execute(
                "INSERT INTO trust_outcome_receipts "
                "(outcome_id, payload_json, payload_sha256, agent_id, "
                "session_id, session_revision, evidence_sha256, result_alpha, "
                "result_beta, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    effect.outcome_id,
                    payload_json,
                    payload_sha,
                    effect.agent_id,
                    effect.session_id,
                    effect.session_revision,
                    effect.evidence_sha256,
                    plan.alpha,
                    plan.beta,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await self._db.commit()
        except BaseException as write_error:
            try:
                await self._db.execute("ROLLBACK")
            except Exception:
                pass
            if plan is None:
                raise
            try:
                snapshot = await self._read_outcome_snapshot(
                    effect=effect,
                    payload_json=payload_json,
                    payload_sha=payload_sha,
                )
            except BaseException:
                self._outcome_reconciliation = _OutcomeReconciliation(
                    effect=effect,
                    payload_json=payload_json,
                    payload_sha256=payload_sha,
                    plan=plan,
                    write_error=write_error,
                )
                raise write_error
            if snapshot is None:
                raise write_error
            self._reconcile_raw_record(effect.agent_id, snapshot.current_raw)
            self._publish_outcome_plan(plan, publish_raw=False)
            if isinstance(write_error, asyncio.CancelledError):
                raise write_error
            return TrustOutcomeWriteResult(
                disposition="applied",
                alpha=snapshot.receipt_result[0],
                beta=snapshot.receipt_result[1],
            )

        if plan is None:
            raise RuntimeError("trust_outcome_plan_missing")
        self._publish_outcome_plan(plan)
        return TrustOutcomeWriteResult(
            disposition="applied",
            alpha=plan.alpha,
            beta=plan.beta,
        )

    async def _reconcile_reserved_outcome(
        self,
        reservation: _OutcomeReconciliation,
    ) -> TrustOutcomeWriteResult:
        try:
            snapshot = await self._read_outcome_snapshot(
                effect=reservation.effect,
                payload_json=reservation.payload_json,
                payload_sha=reservation.payload_sha256,
            )
        except BaseException:
            raise reservation.write_error
        if snapshot is None:
            self._outcome_reconciliation = None
            return await self._record_outcome_once_locked(
                effect=reservation.effect,
                payload_json=reservation.payload_json,
                payload_sha=reservation.payload_sha256,
            )
        self._reconcile_raw_record(
            reservation.effect.agent_id,
            snapshot.current_raw,
        )
        self._outcome_reconciliation = None
        self._publish_outcome_plan(reservation.plan, publish_raw=False)
        return TrustOutcomeWriteResult(
            disposition="applied",
            alpha=snapshot.receipt_result[0],
            beta=snapshot.receipt_result[1],
        )

    @staticmethod
    def _receipt_matches(
        row: Any,
        *,
        effect: CrewTrustEffect,
        payload_json: str,
        payload_sha: str,
    ) -> bool:
        return (
            row is not None
            and len(row) >= 6
            and type(row[0]) is str
            and row[0] == payload_json
            and type(row[1]) is str
            and row[1] == payload_sha
            and type(row[2]) is str
            and row[2] == effect.agent_id
            and type(row[3]) is str
            and row[3] == effect.session_id
            and type(row[4]) is int
            and row[4] == effect.session_revision
            and type(row[5]) is str
            and row[5] == effect.evidence_sha256
        )

    @staticmethod
    def _reservation_matches(
        reservation: _OutcomeReconciliation,
        *,
        effect: CrewTrustEffect,
        payload_json: str,
        payload_sha: str,
    ) -> bool:
        return (
            reservation.effect.outcome_id == effect.outcome_id
            and reservation.payload_json == payload_json
            and reservation.payload_sha256 == payload_sha
        )

    async def _fetch_outcome_snapshot_row(self, outcome_id: str) -> Any | None:
        if self._db is None:
            raise RuntimeError("trust_outcome_store_not_started")
        cursor = await self._db.execute(
            "SELECT r.payload_json, r.payload_sha256, r.agent_id, r.session_id, "
            "r.session_revision, r.evidence_sha256, r.result_alpha, r.result_beta, "
            "s.agent_id, s.alpha, s.beta FROM trust_outcome_receipts AS r "
            "LEFT JOIN trust_scores AS s ON s.agent_id = r.agent_id "
            "WHERE r.outcome_id = ?",
            (outcome_id,),
        )
        return await cursor.fetchone()

    async def _read_outcome_snapshot(
        self,
        *,
        effect: CrewTrustEffect,
        payload_json: str,
        payload_sha: str,
    ) -> _OutcomeSnapshot | None:
        if self._db is None:
            raise RuntimeError("trust_outcome_store_not_started")
        await self._db.execute("BEGIN")
        try:
            row = await self._fetch_outcome_snapshot_row(effect.outcome_id)
            snapshot = (
                None
                if row is None
                else self._validate_outcome_snapshot(
                    row,
                    effect=effect,
                    payload_json=payload_json,
                    payload_sha=payload_sha,
                )
            )
            await self._db.execute("ROLLBACK")
            return snapshot
        except BaseException:
            try:
                await self._db.execute("ROLLBACK")
            except Exception:
                pass
            raise

    def _validate_outcome_snapshot(
        self,
        row: Any,
        *,
        effect: CrewTrustEffect,
        payload_json: str,
        payload_sha: str,
    ) -> _OutcomeSnapshot:
        if (
            row is None
            or len(row) != 11
            or not self._receipt_matches(
                row,
                effect=effect,
                payload_json=payload_json,
                payload_sha=payload_sha,
            )
        ):
            raise ValueError("trust_outcome_identity_conflict")
        if row[6] is None or row[7] is None:
            raise ValueError("trust_outcome_receipt_result_missing")
        receipt_result = self._validated_raw_pair(
            row[6],
            row[7],
            error="trust_outcome_receipt_result_invalid",
        )
        if row[8] is None:
            if row[9] is not None or row[10] is not None:
                raise ValueError("trust_outcome_current_state_invalid")
            current_raw = None
        else:
            if type(row[8]) is not str or row[8] != effect.agent_id:
                raise ValueError("trust_outcome_current_state_invalid")
            current_raw = self._validated_raw_pair(
                row[9],
                row[10],
                error="trust_outcome_current_state_invalid",
            )
        return _OutcomeSnapshot(
            receipt_result=receipt_result,
            current_raw=current_raw,
        )

    @staticmethod
    def _validated_raw_pair(
        alpha: Any,
        beta: Any,
        *,
        error: str,
    ) -> tuple[float, float]:
        if (
            type(alpha) not in (int, float)
            or type(beta) not in (int, float)
            or not math.isfinite(float(alpha))
            or not math.isfinite(float(beta))
            or float(alpha) <= 0.0
            or float(beta) <= 0.0
        ):
            raise ValueError(error)
        return (float(alpha), float(beta))

    def _reconcile_raw_record(
        self,
        agent_id: str,
        current_raw: tuple[float, float] | None,
    ) -> None:
        if current_raw is None:
            self._records.pop(agent_id, None)
            return
        self._records[agent_id] = TrustRecord(
            agent_id=agent_id,
            alpha=current_raw[0],
            beta=current_raw[1],
        )

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
        self._require_sync_mutation_available()
        for record in self._records.values():
            # Decay toward priors
            record.alpha = self.prior_alpha + (record.alpha - self.prior_alpha) * self.decay_rate
            record.beta = self.prior_beta + (record.beta - self.prior_beta) * self.decay_rate

    def remove(self, agent_id: AgentID) -> None:
        """Remove an agent's trust record. Delegates to remove_agent."""
        self.remove_agent(agent_id)

    def remove_agent(self, agent_id: AgentID) -> None:
        """Remove an agent's trust record. Public API for AD-514."""
        self._require_sync_mutation_available()
        if agent_id in self._records:
            del self._records[agent_id]
            logger.info("Trust record removed for agent %s", agent_id)

    def reconcile(self, active_agent_ids: set[str]) -> int:
        """Remove trust records for agents not in the active set. Returns count removed."""
        self._require_sync_mutation_available()
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
        self._require_sync_mutation_available()
        self._floor_hit_count = 0

    # ------------------------------------------------------------------
    # SQLite persistence
    # ------------------------------------------------------------------

    async def _migrate_outcome_receipt_results(self) -> None:
        if not self._db:
            return
        cursor = await self._db.execute(
            "PRAGMA table_info(trust_outcome_receipts)",
        )
        columns = {row[1] for row in await cursor.fetchall()}
        if "result_alpha" not in columns:
            await self._db.execute(
                "ALTER TABLE trust_outcome_receipts ADD COLUMN result_alpha REAL",
            )
        if "result_beta" not in columns:
            await self._db.execute(
                "ALTER TABLE trust_outcome_receipts ADD COLUMN result_beta REAL",
            )

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
        if self._outcome_reconciliation is not None:
            raise RuntimeError("trust_outcome_reconciliation_required")
        if not self._db:
            return
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            if self._outcome_reconciliation is not None:
                raise RuntimeError("trust_outcome_reconciliation_required")
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

    # ── AD-702: Diplomatic Relations (discounted trust transitivity) ──

    def set_intent_descriptor_lookup(
        self, fn: Callable[[str], Any | None]
    ) -> None:
        """AD-702: Inject intent-descriptor resolution.

        The injected callable returns an ``IntentDescriptor`` (or any
        object with a ``requires_consensus: bool`` attribute) for a given
        intent name, or ``None`` if unknown. Wired by the runtime once the
        intent registry is built. Mirrors ``set_department_lookup``.
        """
        self._get_intent_descriptor = fn

    def _best_bridge(
        self,
        observer: AgentID,
        target: AgentID,
        discount: float,
    ) -> tuple[float | None, AgentID | None]:
        """AD-702 (R4 DRY): single-hop strongest-bridge search.

        Returns ``(composed_score, via_agent_id)`` for the strongest 1-hop
        intermediary, or ``(None, None)`` if no chain exists. Used by both
        ``transitive_score`` and ``chain_path``.
        """
        end = self._records.get(target)
        if end is None or end.observations <= 0:
            return (None, None)
        best: float | None = None
        best_via: AgentID | None = None
        for cand_id, cand_rec in self._records.items():
            if cand_id in (observer, target):
                continue
            if cand_rec.observations <= 0:
                continue
            composed = cand_rec.score * end.score * discount
            if best is None or composed > best:
                best = composed
                best_via = cand_id
        return (best, best_via)

    def transitive_score(
        self,
        observer: AgentID,
        target: AgentID,
        *,
        intent: str | None = None,
        via: AgentID | None = None,
        max_hops: int = DEFAULT_TRANSITIVE_MAX_HOPS,
        discount: float = DEFAULT_TRANSITIVE_DISCOUNT,
        safety_critical: bool = False,
    ) -> float | None:
        """AD-702: Discounted transitive trust along the strongest chain.

        Returns the multiplicatively-composed score, or ``None`` if no
        chain exists within ``max_hops``. Direct trust always wins when
        present (observer == target -> 1.0; direct record present -> that
        score with decay applied).

        Safety-critical override: when ``safety_critical=True`` (or the
        intent is registered with ``requires_consensus=True``), the
        method refuses to fall back to transitive composition and returns
        ``None`` if no direct record exists.

        Sybil resistance: ``discount`` is applied per hop. A 2-hop chain
        at default discount caps at ``0.85 * bridge.score * end.score`` —
        longer chains decay faster.

        Decay: scores age toward ``TRANSITIVE_NEUTRAL`` linearly after
        ``DEFAULT_TRANSITIVE_DECAY_DAYS`` since the target's last event.
        """
        # 0. Hop budget — v1 only supports >=2 hops; <2 is a no-op.
        if max_hops < 2:
            return None

        # 1. Identity / direct lookup.
        if observer == target:
            return 1.0
        direct = self._records.get(target)
        if direct is not None and direct.observations > 0:
            return self._apply_decay(direct.score, target)

        # 1b. Safety-critical / destructive-intent override (adjacent gates).
        #     These run BEFORE any transitive composition. If either trips,
        #     refuse to fall back.
        if safety_critical:
            return None
        if intent and getattr(self, "_get_intent_descriptor", None) is not None:
            desc = self._get_intent_descriptor(intent)
            if desc is not None and getattr(desc, "requires_consensus", False):
                if direct is None or direct.observations <= 0:
                    return None

        # 2. Optional explicit bridge.
        if via is not None:
            bridge = self._records.get(via)
            end = self._records.get(target)
            if (
                bridge is None
                or end is None
                or bridge.observations <= 0
                or end.observations <= 0
            ):
                return None
            composed = bridge.score * end.score * discount
            return self._apply_decay(composed, target)

        # 3. Auto bridge: strongest 1-hop intermediary in the network.
        best, _via = self._best_bridge(observer, target, discount)
        if best is None:
            return None
        return self._apply_decay(best, target)

    def chain_path(
        self,
        observer: AgentID,
        target: AgentID,
        *,
        discount: float = DEFAULT_TRANSITIVE_DISCOUNT,
    ) -> list[AgentID]:
        """AD-702: Return the agent chain producing the best transitive score.

        Returns ``[observer]`` for self-target, ``[observer, target]``
        for a direct record, ``[observer, via, target]`` for the strongest
        1-hop bridge, or ``[]`` if no chain exists.
        """
        if observer == target:
            return [observer]
        direct = self._records.get(target)
        if direct is not None and direct.observations > 0:
            return [observer, target]
        _best, best_via = self._best_bridge(observer, target, discount)
        if best_via is None:
            return []
        return [observer, best_via, target]

    def _apply_decay(self, raw_score: float, agent_id: AgentID) -> float:
        """AD-702: Linear decay toward TRANSITIVE_NEUTRAL after the decay window.

        Looks up the most recent ``TrustEvent`` for ``agent_id`` in
        ``self._event_log`` (bounded at ``maxlen=500``; flagged for
        AD-702b graph search if longer histories are needed).
        Returns ``raw_score`` unchanged if no event is found or the
        window has not elapsed.
        """
        last_seen: float | None = None
        for ev in reversed(self._event_log):
            if ev.agent_id == agent_id:
                last_seen = ev.timestamp
                break
        if last_seen is None:
            return raw_score
        age_days = max(0.0, (time.time() - last_seen) / 86400.0)
        if age_days <= DEFAULT_TRANSITIVE_DECAY_DAYS:
            return raw_score
        # Linear interpolation toward neutral over a second 90-day window.
        over = age_days - DEFAULT_TRANSITIVE_DECAY_DAYS
        progress = min(1.0, over / DEFAULT_TRANSITIVE_DECAY_DAYS)
        return raw_score + (TRANSITIVE_NEUTRAL - raw_score) * progress
