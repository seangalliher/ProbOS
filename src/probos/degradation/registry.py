"""AD-459: Service tier registry — classifies known services into shedding tiers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ServiceTier(str, Enum):
    """Service shedding tier."""

    ESSENTIAL = "essential"
    COGNITIVE = "cognitive"
    NON_ESSENTIAL = "non_essential"


@dataclass(frozen=True)
class ServiceClassification:
    """One service-to-tier mapping."""

    service_name: str
    tier: ServiceTier
    description: str = ""


# Default classifications. Each `service_name` matches an actual public
# attribute on `ProbOSRuntime` (verified via grep at draft time). Subsystems
# pass the same name when consulting `manager.is_shed("name")`.
#
# v1 seeds 11 services that ARE runtime attributes today. Logical-only names
# (e.g. "cognitive_agent" for the agent class, "dreaming" as a logical group)
# are deferred to AD-459b along with the active-shedding hooks.
_DEFAULT_CLASSIFICATIONS: tuple[ServiceClassification, ...] = (
    # ESSENTIAL -- always survive
    ServiceClassification("event_log", ServiceTier.ESSENTIAL, "audit log"),
    ServiceClassification("trust_network", ServiceTier.ESSENTIAL, "trust reads"),
    ServiceClassification("registry", ServiceTier.ESSENTIAL, "agent registry"),
    ServiceClassification("intent_bus", ServiceTier.ESSENTIAL, "intent dispatch"),
    ServiceClassification("hebbian_router", ServiceTier.ESSENTIAL, "routing weights"),
    # COGNITIVE -- gracefully degrade
    ServiceClassification("decomposer", ServiceTier.COGNITIVE, "intent decomposition"),
    ServiceClassification("dream_scheduler", ServiceTier.COGNITIVE, "dream consolidation scheduler"),
    ServiceClassification("proactive_loop", ServiceTier.COGNITIVE, "proactive cognition"),
    # NON_ESSENTIAL -- first to shed
    ServiceClassification("emergence_metrics_engine", ServiceTier.NON_ESSENTIAL, "emergence analytics"),
    ServiceClassification("emergent_leadership_detector", ServiceTier.NON_ESSENTIAL, "AD-439 analytics"),
    ServiceClassification("red_team_lead", ServiceTier.NON_ESSENTIAL, "red team campaigns"),
)


@dataclass
class ServiceTierRegistry:
    """Maps service names to ServiceTier. Seed + runtime extensions.

    `register(...)` adds new classifications and overwrites existing ones
    by service_name (last-write-wins). The default seed is loaded on
    construction; subsequent `register(...)` calls extend the seed.
    """

    _classifications: dict[str, ServiceClassification] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for c in _DEFAULT_CLASSIFICATIONS:
            self._classifications[c.service_name] = c

    def register(self, classification: ServiceClassification) -> None:
        self._classifications[classification.service_name] = classification

    def get_tier(self, service_name: str) -> ServiceTier | None:
        c = self._classifications.get(service_name)
        return c.tier if c else None

    def services_in_tier(self, tier: ServiceTier) -> list[str]:
        return sorted([
            c.service_name for c in self._classifications.values() if c.tier == tier
        ])

    def all_classifications(self) -> list[ServiceClassification]:
        return list(self._classifications.values())
