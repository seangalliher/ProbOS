"""AD-459: Degradation manager — read-only shedding coordinator (v1).

v1 surfaces the policy decision via `is_shed(service_name)` and `is_tier_shed(tier)`.
Subsystems consult these and self-degrade. v1 does NOT mutate any subsystem
state directly. Active shedding (subsystem hooks) is deferred to AD-459b.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.degradation.policy import SheddingPolicy, StressLevel
from probos.degradation.registry import ServiceTier, ServiceTierRegistry
from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DegradationStatus:
    """Snapshot of current degradation state."""

    stress_level: StressLevel
    shed_tiers: frozenset[ServiceTier]
    shed_services: list[str]
    updated_at: float


class DegradationManager:
    """Coordinates the registry + policy.

    Public surface:
      - set_stress_level(level): updates internal level, emits transition events.
      - is_shed(service_name) -> bool: subsystems consult before doing work.
      - is_tier_shed(tier) -> bool: tier-level query.
      - status() -> DegradationStatus.

    No background task in v1. Caller updates stress level in response to
    health signals (AD-457 PERFORMANCE_THRESHOLD_BREACHED, BF-246 LLM
    health, etc.).
    """

    def __init__(
        self,
        *,
        registry: ServiceTierRegistry,
        policy: SheddingPolicy,
        emit_event: Any | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._emit_event = emit_event
        self._level = StressLevel.NORMAL
        self._updated_at = time.time()

    def set_stress_level(self, level: StressLevel) -> None:
        if level == self._level:
            return
        previous = self._level
        self._level = level
        self._updated_at = time.time()
        prev_shed = self._policy.shed_tiers(previous)
        new_shed = self._policy.shed_tiers(level)
        for tier in new_shed - prev_shed:
            self._emit_tier_change(tier, shed=True)
        for tier in prev_shed - new_shed:
            self._emit_tier_change(tier, shed=False)

    def is_shed(self, service_name: str) -> bool:
        tier = self._registry.get_tier(service_name)
        if tier is None:
            return False
        return tier in self._policy.shed_tiers(self._level)

    def is_tier_shed(self, tier: ServiceTier) -> bool:
        return tier in self._policy.shed_tiers(self._level)

    def status(self) -> DegradationStatus:
        shed = self._policy.shed_tiers(self._level)
        services: list[str] = []
        for tier in shed:
            services.extend(self._registry.services_in_tier(tier))
        return DegradationStatus(
            stress_level=self._level,
            shed_tiers=shed,
            shed_services=sorted(services),
            updated_at=self._updated_at,
        )

    def _emit_tier_change(self, tier: ServiceTier, *, shed: bool) -> None:
        if not self._emit_event:
            return
        et = EventType.SERVICE_TIER_DEGRADED if shed else EventType.SERVICE_TIER_RESTORED
        try:
            self._emit_event(
                et,
                {
                    "tier": tier.value,
                    "stress_level": self._level.value,
                    "services": self._registry.services_in_tier(tier),
                },
            )
        except Exception:
            logger.warning(
                "AD-459: %s emit failed (tier=%s, level=%s, shed=%s)",
                et.value, tier.value, self._level.value, shed,
                exc_info=True,
            )
        logger.info(
            "AD-459: tier %s %s (stress=%s)",
            tier.value, "shed" if shed else "restored", self._level.value,
        )
