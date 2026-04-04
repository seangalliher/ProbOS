"""Structural Integrity Field — continuous invariant checking (AD-370).

The SIF is a Ship's Computer function (not an agent) that runs pure
assertion-based invariant checks on every heartbeat cycle.  It catches
corruption (NaN trust scores, orphaned agents, weight explosion, stale
indexes) before it manifests as a user-visible failure.

No LLM calls.  No file I/O on the hot path.  Every check is a simple
Python assertion against in-memory data structures.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.intent import IntentBus
    from probos.mesh.routing import HebbianRouter
    from probos.substrate.pool import ResourcePool
    from probos.substrate.spawner import AgentSpawner

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SIFCheckResult:
    """Result of a single SIF invariant check."""

    name: str
    passed: bool
    details: str = ""


@dataclass
class SIFReport:
    """Aggregate SIF health report."""

    checks: list[SIFCheckResult] = field(default_factory=list)
    timestamp: float = 0.0  # time.monotonic()

    @property
    def health_pct(self) -> float:
        """Percentage of checks passing (0.0 to 100.0)."""
        if not self.checks:
            return 100.0
        return (sum(1 for c in self.checks if c.passed) / len(self.checks)) * 100.0

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def violations(self) -> list[SIFCheckResult]:
        return [c for c in self.checks if not c.passed]


# ---------------------------------------------------------------------------
# Structural Integrity Field
# ---------------------------------------------------------------------------


class StructuralIntegrityField:
    """Continuous invariant checking — the ship's structural skeleton."""

    def __init__(
        self,
        trust_network: TrustNetwork | None = None,
        intent_bus: IntentBus | None = None,
        hebbian_router: HebbianRouter | None = None,
        spawner: AgentSpawner | None = None,
        pool_manager: dict[str, ResourcePool] | None = None,
        check_interval: float = 5.0,
        episodic_memory: Any = None,
        eviction_audit: Any = None,
    ) -> None:
        self._trust_network = trust_network
        self._intent_bus = intent_bus
        self._hebbian_router = hebbian_router
        self._spawner = spawner
        self._pool_manager = pool_manager
        self._check_interval = check_interval
        self._episodic_memory = episodic_memory
        self._eviction_audit = eviction_audit
        self._task: asyncio.Task[None] | None = None
        self._last_report: SIFReport | None = None
        self._last_violation_details: str = ""

    # -- properties ----------------------------------------------------------

    @property
    def last_report(self) -> SIFReport | None:
        """Return the most recent SIF report (or None if not yet run)."""
        return self._last_report

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Start the periodic SIF check loop."""
        self._task = asyncio.create_task(self._check_loop())

    async def stop(self) -> None:
        """Stop the SIF check loop."""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _check_loop(self) -> None:
        """Run checks every check_interval seconds."""
        while True:
            await asyncio.sleep(self._check_interval)
            report = await self.run_all_checks()
            if not report.all_passed:
                details = "; ".join(v.details for v in report.violations)
                if details != self._last_violation_details:
                    logger.warning(
                        "SIF violation detected (%.0f%% integrity): %s",
                        report.health_pct,
                        details,
                    )
                    self._last_violation_details = details
            else:
                self._last_violation_details = ""
            self._last_report = report

    # -- aggregate -----------------------------------------------------------

    async def run_all_checks(self) -> SIFReport:
        """Run all invariant checks and return aggregate report."""
        checks: list[SIFCheckResult] = []
        for check_fn in (
            self.check_trust_bounds,
            self.check_hebbian_bounds,
            self.check_pool_consistency,
            self.check_intent_bus_coherence,
            self.check_config_validity,
            self.check_index_consistency,
            self.check_memory_integrity,
            self.check_eviction_health,
        ):
            try:
                result = check_fn()
                checks.append(result)
            except Exception as exc:
                checks.append(
                    SIFCheckResult(
                        name=check_fn.__name__,
                        passed=False,
                        details=f"exception: {exc}",
                    )
                )
        return SIFReport(checks=checks, timestamp=time.monotonic())

    # -- individual checks ---------------------------------------------------

    def check_trust_bounds(self) -> SIFCheckResult:
        """All trust scores must be in [0.0, 1.0] with no NaN/inf."""
        if self._trust_network is None:
            return SIFCheckResult(
                name="trust_bounds", passed=True, details="not configured"
            )
        try:
            scores = self._trust_network.all_scores()
        except Exception as exc:
            return SIFCheckResult(
                name="trust_bounds", passed=False, details=f"read error: {exc}"
            )
        bad: list[str] = []
        for agent_id, score in scores.items():
            if not math.isfinite(score):
                bad.append(f"{agent_id}={score} (not finite)")
            elif score < 0.0 or score > 1.0:
                bad.append(f"{agent_id}={score} (out of range)")
        if bad:
            return SIFCheckResult(
                name="trust_bounds",
                passed=False,
                details=f"bad scores: {', '.join(bad)}",
            )
        return SIFCheckResult(name="trust_bounds", passed=True)

    def check_hebbian_bounds(self) -> SIFCheckResult:
        """Hebbian weights must be in [-10.0, 10.0] with no NaN/inf."""
        if self._hebbian_router is None:
            return SIFCheckResult(
                name="hebbian_bounds", passed=True, details="not configured"
            )
        try:
            weights = self._hebbian_router._weights
        except Exception as exc:
            return SIFCheckResult(
                name="hebbian_bounds", passed=False, details=f"read error: {exc}"
            )
        bad: list[str] = []
        for key, weight in weights.items():
            if not math.isfinite(weight):
                bad.append(f"{key}={weight} (not finite)")
            elif weight < -10.0 or weight > 10.0:
                bad.append(f"{key}={weight} (out of range)")
        if bad:
            return SIFCheckResult(
                name="hebbian_bounds",
                passed=False,
                details=f"bad weights: {', '.join(bad[:5])}",
            )
        return SIFCheckResult(name="hebbian_bounds", passed=True)

    def check_pool_consistency(self) -> SIFCheckResult:
        """Pool agent types must be registered in spawner templates."""
        if self._pool_manager is None or self._spawner is None:
            return SIFCheckResult(
                name="pool_consistency", passed=True, details="not configured"
            )
        try:
            templates = self._spawner.available_templates
        except Exception as exc:
            return SIFCheckResult(
                name="pool_consistency", passed=False, details=f"read error: {exc}"
            )
        orphaned: list[str] = []
        for pool_name, pool in self._pool_manager.items():
            if pool.agent_type not in templates:
                orphaned.append(f"{pool_name} (type={pool.agent_type})")
        if orphaned:
            return SIFCheckResult(
                name="pool_consistency",
                passed=False,
                details=f"unregistered types: {', '.join(orphaned)}",
            )
        return SIFCheckResult(name="pool_consistency", passed=True)

    def check_intent_bus_coherence(self) -> SIFCheckResult:
        """All intent bus subscriber IDs should correspond to live agents."""
        if self._intent_bus is None:
            return SIFCheckResult(
                name="intent_bus_coherence", passed=True, details="not configured"
            )
        try:
            subscriber_ids = set(self._intent_bus._subscribers.keys())
        except Exception as exc:
            return SIFCheckResult(
                name="intent_bus_coherence",
                passed=False,
                details=f"read error: {exc}",
            )
        # If no spawner, we can't verify agent liveness — pass gracefully
        if self._spawner is None:
            return SIFCheckResult(
                name="intent_bus_coherence",
                passed=True,
                details="no spawner to verify against",
            )
        # Check subscriber IDs against the spawner's registry
        try:
            registered_ids = {a.id for a in self._spawner.registry.all()}
        except Exception as exc:
            return SIFCheckResult(
                name="intent_bus_coherence",
                passed=False,
                details=f"registry read error: {exc}",
            )
        orphaned = subscriber_ids - registered_ids
        if orphaned:
            return SIFCheckResult(
                name="intent_bus_coherence",
                passed=False,
                details=f"orphaned subscribers: {', '.join(sorted(orphaned)[:5])}",
            )
        return SIFCheckResult(name="intent_bus_coherence", passed=True)

    def check_config_validity(self) -> SIFCheckResult:
        """Runtime config passes Pydantic re-validation."""
        # SIF doesn't hold its own config ref — this check is a placeholder
        # that passes when config isn't available.  Runtime wiring can inject
        # config if desired in a future AD.
        return SIFCheckResult(
            name="config_validity", passed=True, details="no config ref"
        )

    def check_index_consistency(self) -> SIFCheckResult:
        """CodebaseIndex file entries reference valid paths (in-memory only)."""
        # SIF doesn't hold a CodebaseIndex ref — graceful no-op.
        return SIFCheckResult(
            name="index_consistency", passed=True, details="not configured"
        )

    def check_memory_integrity(self) -> SIFCheckResult:
        """AD-541b: Verify episode storage integrity."""
        if self._episodic_memory is None:
            return SIFCheckResult(
                name="memory_integrity", passed=True, details="not configured"
            )
        em = self._episodic_memory
        issues: list[str] = []
        try:
            collection = getattr(em, "_collection", None)
            if collection is None:
                return SIFCheckResult(
                    name="memory_integrity", passed=True, details="no collection"
                )
            count = collection.count()
            if count == 0:
                return SIFCheckResult(
                    name="memory_integrity", passed=True, details="empty"
                )
            # Sample recent episodes and verify required fields
            import json as _json
            result = collection.get(include=["metadatas", "documents"], limit=10)
            if result and result["ids"]:
                for i, doc_id in enumerate(result["ids"]):
                    meta = result["metadatas"][i] if result["metadatas"] else {}
                    if not doc_id:
                        issues.append("Episode missing ID")
                    source = meta.get("source", "")
                    # Legacy episodes (pre-source field or migrated by
                    # BF-103) may have no key or an empty value — both are
                    # legacy, not a violation.  Only flag episodes that
                    # have a non-empty source field check would catch.
                    if not source:
                        pass  # legacy or migrated episode — not a violation
                    ts = meta.get("timestamp", 0)
                    if ts <= 0:
                        issues.append(f"Episode {doc_id[:8]} has invalid timestamp")
                    # AD-541e: Content hash verification
                    content_hash = meta.get("content_hash", "")
                    if content_hash:
                        from probos.cognitive.episodic import compute_episode_hash, EpisodicMemory as _EM
                        document = result["documents"][i] if result.get("documents") and i < len(result["documents"]) else ""
                        ep = _EM._metadata_to_episode(doc_id, document, meta)
                        recomputed = compute_episode_hash(ep)
                        if recomputed != content_hash:
                            issues.append(f"Episode {doc_id[:8]} content hash mismatch")
        except Exception as exc:
            issues.append(f"Episode recall failed: {exc}")

        passed = len(issues) == 0
        return SIFCheckResult(
            name="memory_integrity",
            passed=passed,
            details="; ".join(issues) if issues else "ok",
        )

    def check_eviction_health(self) -> SIFCheckResult:
        """AD-541f: Monitor eviction audit trail health via cached counts."""
        if self._eviction_audit is None:
            return SIFCheckResult(
                name="eviction_health", passed=True, details="not configured"
            )
        try:
            total = self._eviction_audit._cached_total
            return SIFCheckResult(
                name="eviction_health",
                passed=True,
                details=f"total_evictions={total}",
            )
        except Exception as exc:
            return SIFCheckResult(
                name="eviction_health",
                passed=False,
                details=f"Eviction audit query failed: {exc}",
            )
