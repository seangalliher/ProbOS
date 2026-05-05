"""AD-459 / AD-459b: Degradation manager — shedding coordinator.

AD-459 v1 surfaced the policy decision via ``is_shed(service_name)`` and
``is_tier_shed(tier)``. Subsystems consulted these and self-degraded.

AD-459b adds active shedding: subsystems register via
``register_subsystem(name, subsystem)`` and the manager invokes their
``pause()`` / ``resume()`` callbacks on tier-mask transitions. Every
invocation is fire-and-forget (``asyncio.create_task(...)``) and wrapped
in tier-2 log-and-degrade — a subsystem-side failure NEVER propagates.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.degradation.policy import SheddingPolicy, StressLevel
from probos.degradation.registry import ServiceTier, ServiceTierRegistry
from probos.degradation.subsystem import SheddableSubsystem
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
        # AD-459b: registered subsystems (by service_name) + fire-and-forget
        # task references per Standing Order on async hygiene.
        self._subsystems: dict[str, SheddableSubsystem] = {}
        self._lifecycle_tasks: set[asyncio.Task[None]] = set()

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
        # AD-459b: schedule subsystem pause/resume tasks for tier-mask deltas.
        # Stays fire-and-forget so callers keep the AD-459 v1 sync API.
        self._schedule_subsystem_transitions(
            pause_tiers=new_shed - prev_shed,
            resume_tiers=prev_shed - new_shed,
        )

    def _schedule_subsystem_transitions(
        self,
        *,
        pause_tiers: frozenset[ServiceTier],
        resume_tiers: frozenset[ServiceTier],
    ) -> None:
        """AD-459b: schedule async pause/resume tasks; tier-2 log-and-degrade.

        Skips silently when there is no running event loop (e.g., a sync
        test that does not drive the manager via ``asyncio.run(...)``).
        """
        if not self._subsystems:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "AD-459b: no running event loop; subsystem transitions skipped",
            )
            return
        for tier in pause_tiers:
            for name, subsystem in self._subsystems.items():
                if self._registry.get_tier(name) == tier:
                    self._spawn_lifecycle_task(
                        loop, self._invoke_pause(name, subsystem, tier),
                    )
        for tier in resume_tiers:
            for name, subsystem in self._subsystems.items():
                if self._registry.get_tier(name) == tier:
                    self._spawn_lifecycle_task(
                        loop, self._invoke_resume(name, subsystem, tier),
                    )

    def _spawn_lifecycle_task(
        self, loop: asyncio.AbstractEventLoop, coro: Any,
    ) -> None:
        task = loop.create_task(coro)
        self._lifecycle_tasks.add(task)
        task.add_done_callback(self._lifecycle_tasks.discard)

    async def _invoke_pause(
        self, name: str, subsystem: SheddableSubsystem, tier: ServiceTier,
    ) -> None:
        try:
            await subsystem.pause()
        except Exception:
            logger.warning(
                "AD-459b: %s.pause() failed (tier=%s, level=%s)",
                name, tier.value, self._level.value, exc_info=True,
            )
            return
        self._emit_subsystem_event(EventType.SUBSYSTEM_PAUSED, name, tier)

    async def _invoke_resume(
        self, name: str, subsystem: SheddableSubsystem, tier: ServiceTier,
    ) -> None:
        try:
            await subsystem.resume()
        except Exception:
            logger.warning(
                "AD-459b: %s.resume() failed (tier=%s, level=%s)",
                name, tier.value, self._level.value, exc_info=True,
            )
            return
        self._emit_subsystem_event(EventType.SUBSYSTEM_RESUMED, name, tier)

    def _emit_subsystem_event(
        self, event_type: EventType, name: str, tier: ServiceTier,
    ) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                event_type,
                {
                    "service": name,
                    "tier": tier.value,
                    "stress_level": self._level.value,
                },
            )
        except Exception:
            logger.warning(
                "AD-459b: %s emit failed (service=%s, tier=%s)",
                event_type.value, name, tier.value, exc_info=True,
            )

    def is_shed(self, service_name: str) -> bool:
        tier = self._registry.get_tier(service_name)
        if tier is None:
            return False
        return tier in self._policy.shed_tiers(self._level)

    def is_tier_shed(self, tier: ServiceTier) -> bool:
        return tier in self._policy.shed_tiers(self._level)

    def register_subsystem(
        self, service_name: str, subsystem: SheddableSubsystem,
    ) -> None:
        """AD-459b: register a subsystem for active pause/resume.

        Raises ValueError if ``service_name`` is not classified in the
        registry — the manager refuses to manage an unclassified subsystem
        because it would not know which tier mask gates the lifecycle.

        Replacing an existing registration logs a WARNING and overwrites
        (mirrors ToolRegistry / ProcessChainRegistry precedent — useful
        for hot-reload and test isolation).
        """
        if self._registry.get_tier(service_name) is None:
            raise ValueError(
                f"AD-459b: service_name {service_name!r} not classified "
                f"in ServiceTierRegistry; classify before registering.",
            )
        if service_name in self._subsystems:
            logger.warning(
                "AD-459b: subsystem %r already registered; replacing",
                service_name,
            )
        self._subsystems[service_name] = subsystem

    def unregister_subsystem(self, service_name: str) -> bool:
        """AD-459b: remove a subsystem; returns False if absent."""
        return self._subsystems.pop(service_name, None) is not None

    def registered_subsystems(self) -> list[str]:
        """AD-459b: sorted list of registered service names (for inspection)."""
        return sorted(self._subsystems.keys())

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
