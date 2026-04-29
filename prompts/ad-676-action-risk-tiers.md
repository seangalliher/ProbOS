# AD-676: Action Risk Tiers

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~10

---

## Problem

ProbOS has fragmented action classification. `ActionType` in `initiative.py`
covers remediation actions (diagnose/scale/recycle/patch). `_ACTION_TIERS` in
`earned_agency.py` covers Ward Room actions (endorse/reply/dm/lock/pin).
`ToolPermission` in `tools/protocol.py` covers tool access (NONE→FULL).

There's no unified risk tier system that classifies ALL agent actions —
whether they're Ward Room interactions, tool invocations, or system operations —
into risk tiers with consistent authorization requirements.

## Fix

### Section 1: Create `RiskTier` enum and `ActionRiskRegistry`

**File:** `src/probos/governance/risk_tiers.py` (new file)

**IMPORTANT:** The `src/probos/governance/` directory does not yet exist.
Create `src/probos/governance/__init__.py` (empty file) before creating this file.

```python
"""Action Risk Tiers — unified risk classification (AD-676).

Classifies all agent actions into three risk tiers with
consistent authorization requirements:

- ROUTINE: No additional authorization needed. Default for most actions.
- ELEVATED: Requires agent rank ≥ LIEUTENANT or explicit ClearanceGrant.
- CRITICAL: Requires agent rank ≥ COMMANDER + trust ≥ 0.70, or Captain override.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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
    min_rank_ordinal: int  # 0=Ensign, 1=Lieutenant, 2=Commander, 3=Senior
    min_trust: float  # Minimum trust score (0.0 = no requirement)
    requires_quorum: bool = False  # Future: multi-agent consensus
    description: str = ""


# Default policies per tier
TIER_POLICIES: dict[RiskTier, RiskPolicy] = {
    RiskTier.ROUTINE: RiskPolicy(
        tier=RiskTier.ROUTINE,
        min_rank_ordinal=0,
        min_trust=0.0,
        description="No additional authorization needed",
    ),
    RiskTier.ELEVATED: RiskPolicy(
        tier=RiskTier.ELEVATED,
        min_rank_ordinal=1,  # Lieutenant
        min_trust=0.0,
        description="Requires rank ≥ Lieutenant or ClearanceGrant",
    ),
    RiskTier.CRITICAL: RiskPolicy(
        tier=RiskTier.CRITICAL,
        min_rank_ordinal=2,  # Commander
        min_trust=0.70,
        description="Requires rank ≥ Commander + trust ≥ 0.70, or Captain override",
    ),
}


class ActionRiskRegistry:
    """Registry mapping action names to risk tiers (AD-676).

    Provides a centralized lookup for action risk classification.
    Actions not registered default to ROUTINE.
    """

    def __init__(self) -> None:
        self._registry: dict[str, RiskTier] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default action risk classifications."""
        # Ward Room actions — aligned with earned_agency.py _ACTION_TIERS
        # "reply"/"endorse" require Rank.LIEUTENANT in earned_agency.py,
        # so they map to ELEVATED here (min_rank_ordinal=1 = Lieutenant).
        # "dm" requires Rank.ENSIGN → ROUTINE. "lock"/"pin" require SENIOR → CRITICAL.
        self._registry.update({
            "reply": RiskTier.ELEVATED,
            "endorse": RiskTier.ELEVATED,
            "dm": RiskTier.ROUTINE,
            "lock": RiskTier.CRITICAL,
            "pin": RiskTier.CRITICAL,
        })
        # Remediation actions (from initiative.py ActionType)
        self._registry.update({
            "diagnose": RiskTier.ROUTINE,
            "scale": RiskTier.ROUTINE,
            "alert_captain": RiskTier.ROUTINE,
            "recycle": RiskTier.ELEVATED,
            "patch": RiskTier.CRITICAL,
        })
        # System operations
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
        return TIER_POLICIES[tier]

    def register(self, action: str, tier: RiskTier) -> None:
        """Register or override an action's risk tier."""
        self._registry[action] = tier
        logger.debug("AD-676: Registered action '%s' as %s", action, tier.value)

    def check_authorization(
        self,
        action: str,
        *,
        rank_ordinal: int,
        trust_score: float = 1.0,
        has_clearance_grant: bool = False,
        is_captain_override: bool = False,
    ) -> bool:
        """Check if an agent is authorized for an action.

        Returns True if authorized, False otherwise.
        """
        if is_captain_override:
            return True

        policy = self.get_policy(action)

        if has_clearance_grant and policy.tier == RiskTier.ELEVATED:
            return True  # ClearanceGrant satisfies ELEVATED

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
```

### Section 2: Add `ACTION_RISK_CHECK` event type

**File:** `src/probos/events.py`

Add in the tool/action events section (near `TOOL_PERMISSION_DENIED`, line 165):

SEARCH:
```python
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
```

REPLACE:
```python
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
    ACTION_RISK_DENIED = "action_risk_denied"  # AD-676
```

### Section 3: Add `RiskTierConfig` to SystemConfig

**File:** `src/probos/config.py`

```python
class RiskTierConfig(BaseModel):
    """Action Risk Tier configuration (AD-676)."""

    enabled: bool = True
    elevated_min_trust: float = 0.0  # Override for ELEVATED tier
    critical_min_trust: float = 0.70  # Override for CRITICAL tier
```

Add `risk_tiers: RiskTierConfig = RiskTierConfig()` to `SystemConfig`.

### Section 4: Wire into startup

**File:** `src/probos/startup/finalize.py`

Add `ActionRiskRegistry` initialization. Find the section near trust dampening
wiring (lines 276-283):

```python
    # AD-676: Action Risk Tiers
    if config.risk_tiers.enabled:
        from probos.governance.risk_tiers import ActionRiskRegistry, TIER_POLICIES, RiskPolicy, RiskTier
        risk_registry = ActionRiskRegistry()
        # Apply config overrides
        if config.risk_tiers.critical_min_trust != 0.70:
            TIER_POLICIES[RiskTier.CRITICAL] = RiskPolicy(
                tier=RiskTier.CRITICAL,
                min_rank_ordinal=2,
                min_trust=config.risk_tiers.critical_min_trust,
                description=TIER_POLICIES[RiskTier.CRITICAL].description,
            )
        runtime._risk_registry = risk_registry
        logger.info("AD-676: ActionRiskRegistry initialized with %d actions", len(risk_registry.list_actions()))
```

## Tests

**File:** `tests/test_ad676_action_risk_tiers.py`

10 tests:

1. `test_risk_tier_enum_values` — verify ROUTINE, ELEVATED, CRITICAL exist
2. `test_default_action_classifications` — verify "dm"→ROUTINE, "reply"→ELEVATED,
   "lock"→CRITICAL, "patch"→CRITICAL
3. `test_unregistered_action_defaults_to_routine` — unknown action → ROUTINE
4. `test_check_authorization_routine` — Ensign (ordinal 0) can do ROUTINE actions
5. `test_check_authorization_elevated_denied` — Ensign denied ELEVATED actions
6. `test_check_authorization_elevated_with_clearance` — Ensign with clearance_grant
   can do ELEVATED actions
7. `test_check_authorization_critical` — Commander (ordinal 2) with trust 0.75
   authorized for CRITICAL
8. `test_check_authorization_critical_low_trust` — Commander with trust 0.50
   denied CRITICAL
9. `test_captain_override_bypasses_all` — is_captain_override=True always passes
10. `test_register_custom_action` — register a new action, verify it's classified

## What This Does NOT Change

- No changes to `earned_agency.py` `_ACTION_TIERS` — that system remains for
  backward compatibility. Risk tiers are a parallel, more granular system.
- No changes to `tools/registry.py` `resolve_permission()` — tool permissions
  are a separate concern. Future AD can bridge the two systems.
- No changes to `initiative.py` ActionType/ActionGate — those remain for
  remediation proposals. Risk tiers classify all action types uniformly.
- Does NOT add quorum-based authorization (future enhancement via `requires_quorum`)
- Does NOT modify existing Counselor intervention paths (AD-561 handles that)

## Tracking

- `PROGRESS.md`: Add AD-676 as COMPLETE
- `docs/development/roadmap.md`: Update AD-676 status

## Acceptance Criteria

- `RiskTier` enum with ROUTINE/ELEVATED/CRITICAL exists
- `ActionRiskRegistry` with default action classifications exists
- `check_authorization()` correctly enforces rank + trust requirements
- `ClearanceGrant` satisfies ELEVATED tier
- Captain override bypasses all tiers
- `EventType.ACTION_RISK_DENIED` exists
- All 10 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# Existing action classification systems
grep -n "class ActionType" src/probos/initiative.py
  24: class ActionType(str, Enum): DIAGNOSE, SCALE, RECYCLE, PATCH, ALERT_CAPTAIN

grep -n "_ACTION_TIERS" src/probos/earned_agency.py
  189-195: _ACTION_TIERS = {"endorse": Rank.LIEUTENANT, "reply": Rank.LIEUTENANT,
           "dm": Rank.ENSIGN, "lock": Rank.SENIOR, "pin": Rank.SENIOR}
  # Risk tiers ALIGNED: LIEUTENANT→ELEVATED, ENSIGN→ROUTINE, SENIOR→CRITICAL

grep -n "class ToolPermission" src/probos/tools/protocol.py
  29: class ToolPermission(str, Enum): NONE, OBSERVE, READ, WRITE, FULL

# Permission chain
grep -n "def resolve_permission\|def check_and_invoke" src/probos/tools/registry.py
  191: def resolve_permission(...)
  269: async def check_and_invoke(...)

# ClearanceGrant
grep -n "class ClearanceGrant" src/probos/earned_agency.py
  37: @dataclass ClearanceGrant

# Tool event
grep -n "TOOL_PERMISSION_DENIED" src/probos/events.py
  165: TOOL_PERMISSION_DENIED = "tool_permission_denied"

# No existing governance directory — AD-676 creates it
find . -path "*/governance/*" → empty (new directory)
# Builder must create src/probos/governance/__init__.py first

# EarnedAgencyConfig
grep -n "class EarnedAgencyConfig" src/probos/config.py
  1099: class EarnedAgencyConfig
```
