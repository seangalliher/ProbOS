"""AD-459: Shedding policy — maps stress level to shed tiers."""

from __future__ import annotations

from enum import Enum

from probos.degradation.registry import ServiceTier


class StressLevel(str, Enum):
    """System stress level. Higher = more aggressive shedding."""

    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


class SheddingPolicy:
    """Maps stress level to the set of tiers that should be shed.

    Default policy (v1 -- read-only coordinator; ESSENTIAL is hardcoded
    never-shed at every level):

        NORMAL    -> shed nothing
        ELEVATED  -> shed NON_ESSENTIAL
        HIGH      -> shed NON_ESSENTIAL + COGNITIVE
        CRITICAL  -> shed NON_ESSENTIAL + COGNITIVE
                     (same shed mask as HIGH; AD-459b will add
                     active-shedding hooks that differentiate CRITICAL --
                     e.g. cancel long-running cognitive tasks, pause
                     async queues -- beyond the read-only is_shed signal)
    """

    def shed_tiers(self, level: StressLevel) -> frozenset[ServiceTier]:
        if level == StressLevel.NORMAL:
            return frozenset()
        if level == StressLevel.ELEVATED:
            return frozenset({ServiceTier.NON_ESSENTIAL})
        # HIGH or CRITICAL -- same read-only shed mask in v1; CRITICAL adds
        # active-shedding hooks in AD-459b
        return frozenset(
            {ServiceTier.NON_ESSENTIAL, ServiceTier.COGNITIVE},
        )
