"""Action Risk Tiers — unified risk classification (AD-676).

Classifies all agent actions into three risk tiers with
consistent authorization requirements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class RiskTier(str, Enum):
    """Risk classification for agent actions."""

    ROUTINE = "routine"
    ELEVATED = "elevated"
    CRITICAL = "critical"


@dataclass(frozen=True)
class RiskPolicy:
    """Authorization requirements for a risk tier."""

    tier: RiskTier
    min_rank_ordinal: int
    min_trust: float
    requires_quorum: bool = False
    description: str = ""


TIER_POLICIES: dict[RiskTier, RiskPolicy] = {
    RiskTier.ROUTINE: RiskPolicy(
        tier=RiskTier.ROUTINE,
        min_rank_ordinal=0,
        min_trust=0.0,
        description="No additional authorization needed",
    ),
    RiskTier.ELEVATED: RiskPolicy(
        tier=RiskTier.ELEVATED,
        min_rank_ordinal=1,
        min_trust=0.0,
        description="Requires rank >= Lieutenant or ClearanceGrant",
    ),
    RiskTier.CRITICAL: RiskPolicy(
        tier=RiskTier.CRITICAL,
        min_rank_ordinal=2,
        min_trust=0.70,
        description="Requires rank >= Commander + trust >= 0.70, or Captain override",
    ),
}


class ActionRiskRegistry:
    """Registry mapping action names to risk tiers (AD-676)."""

    def __init__(self, *, policies: dict[RiskTier, RiskPolicy] | None = None) -> None:
        self._registry: dict[str, RiskTier] = {}
        self._policies = dict(policies or TIER_POLICIES)
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default action risk classifications."""
        self._registry.update({
            "reply": RiskTier.ELEVATED,
            "endorse": RiskTier.ELEVATED,
            "dm": RiskTier.ROUTINE,
            "lock": RiskTier.CRITICAL,
            "pin": RiskTier.CRITICAL,
        })
        self._registry.update({
            "diagnose": RiskTier.ROUTINE,
            "scale": RiskTier.ROUTINE,
            "alert_captain": RiskTier.ROUTINE,
            "recycle": RiskTier.ELEVATED,
            "patch": RiskTier.CRITICAL,
        })
        self._registry.update({
            "force_dream": RiskTier.ELEVATED,
            "issue_directive": RiskTier.ELEVATED,
            "modify_standing_orders": RiskTier.CRITICAL,
            "trust_override": RiskTier.CRITICAL,
        })

    def get_tier(self, action: str) -> RiskTier:
        """Get the risk tier for an action. Defaults to ROUTINE."""
        return self._registry.get(action, RiskTier.ROUTINE)

    def get_policy(self, action: str) -> RiskPolicy:
        """Get the authorization policy for an action."""
        tier = self.get_tier(action)
        return self._policies[tier]

    def register(self, action: str, tier: RiskTier) -> None:
        """Register or override an action's risk tier."""
        self._registry[action] = tier
        logger.debug("AD-676: Registered action %s as %s", action, tier.value)

    def check_authorization(
        self,
        action: str,
        *,
        rank_ordinal: int,
        trust_score: float = 1.0,
        has_clearance_grant: bool = False,
        is_captain_override: bool = False,
    ) -> bool:
        """Check if an agent is authorized for an action."""
        if is_captain_override:
            return True

        policy = self.get_policy(action)

        if has_clearance_grant and policy.tier == RiskTier.ELEVATED:
            return True

        if rank_ordinal < policy.min_rank_ordinal:
            return False
        if trust_score < policy.min_trust:
            return False
        return True

    def list_actions(self, tier: RiskTier | None = None) -> dict[str, RiskTier]:
        """List registered actions, optionally filtered by tier."""
        if tier is None:
            return dict(self._registry)
        return {k: v for k, v in self._registry.items() if v == tier}
