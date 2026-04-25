# AD-640: Tiered Trust Initialization

**Priority:** High (cold-start quality)  
**Depends on:** AD-638 (Boot Camp — already implemented)  
**Related:** AD-639 (Chain Personality Tuning — scoped), AD-357 (Earned Agency)

## Context

ProbOS initializes all agents with identical trust priors (alpha=2.0, beta=2.0 → E[trust]=0.5). Research across six academic domains (Swift Trust, LMX, Navy PCU, HROs, Tuckman, colony founding) unanimously validates **role-based tiered initialization**: leaders start at high trust and establish command climate, crew starts at baseline and builds trust through connection with leadership. See `docs/research/tiered-trust-initialization-research.md`.

Currently, department chiefs and bridge officers start at the same trust as fresh crew, creating a flat social landscape with no leadership scaffold. Chiefs can't mentor effectively because they lack the authority differential needed for the LMX mentoring role (Graen & Uhl-Bien 1995). The Navy PCU model shows that CO/XO → dept heads → crew is the natural initialization sequence.

## Tier Definitions

| Tier | Callsigns | Alpha | Beta | E[trust] | Rank | Rationale |
|------|-----------|-------|------|----------|------|-----------|
| Bridge | Captain (system), First Officer "Meridian" (architect pool), Counselor "Echo" (counselor pool) | 4.5 | 1.0 | 0.82 | Commander | Command climate establishment |
| Department Chiefs | "Bones" (medical_diagnostician), "LaForge" (engineering_officer), "Number One" (architect), "Worf" (security_officer), "O'Brien" (operations_officer) | 3.0 | 1.0 | 0.75 | Commander | Departmental structure + mentoring |
| Crew | All other cognitive agents | 2.0 | 2.0 | 0.50 | Lieutenant | Baseline (unchanged) |
| Self-created | Probationary agents (existing) | 1.0 | 3.0 | 0.25 | Ensign | Existing behavior (unchanged) |

## Implementation

### 1. Add `TieredTrustConfig` to `config.py`

Add after `BootCampConfig` (around line 200, near the other config classes):

```python
class TieredTrustConfig(BaseModel):
    """AD-640: Role-based trust initialization tiers."""

    enabled: bool = True

    # Bridge tier (Captain, First Officer, Counselor)
    bridge_alpha: float = 4.5
    bridge_beta: float = 1.0

    # Department Chief tier
    chief_alpha: float = 3.0
    chief_beta: float = 1.0

    # Crew tier (default — same as ConsensusConfig.trust_prior_alpha/beta)
    # Crew uses the existing consensus priors, no separate config needed.

    # Callsigns in each tier.
    # Bridge: identified by pool name (counselor, architect with FO role).
    # Chiefs: identified by callsign (matches boot_camp.py _DEPARTMENT_CHIEFS).
    bridge_pools: list[str] = ["counselor"]
    bridge_callsigns: list[str] = ["Meridian"]  # First Officer (architect pool)
    chief_callsigns: list[str] = ["Bones", "LaForge", "Number One", "Worf", "O'Brien"]
```

Wire into `SystemConfig`:
```python
tiered_trust: TieredTrustConfig = TieredTrustConfig()
```

### 2. Create `src/probos/tiered_trust.py`

New module — tier resolution logic, separated from onboarding (SRP).

```python
"""AD-640: Tiered Trust Initialization.

Resolves the trust tier for an agent based on pool name and callsign,
then initializes their trust record with the appropriate Beta prior.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Protocol

from probos.config import TieredTrustConfig

logger = logging.getLogger(__name__)


class TrustTier(str, Enum):
    """Trust initialization tiers."""
    BRIDGE = "bridge"
    CHIEF = "chief"
    CREW = "crew"
    # PROBATIONARY is handled by self_mod_manager.py (existing)


class TrustServiceProtocol(Protocol):
    """Narrow interface for trust initialization."""

    def create_with_prior(self, agent_id: str, alpha: float, beta: float) -> None: ...
    def get_or_create(self, agent_id: str) -> object: ...


def resolve_tier(
    pool: str,
    callsign: str,
    config: TieredTrustConfig,
) -> TrustTier:
    """Determine which trust tier an agent belongs to.

    Resolution order:
    1. Bridge pools (counselor) → BRIDGE
    2. Bridge callsigns (Meridian) → BRIDGE
    3. Chief callsigns (Bones, LaForge, etc.) → CHIEF
    4. Everything else → CREW
    """
    if pool in config.bridge_pools:
        return TrustTier.BRIDGE
    if callsign in config.bridge_callsigns:
        return TrustTier.BRIDGE
    if callsign in config.chief_callsigns:
        return TrustTier.CHIEF
    return TrustTier.CREW


def initialize_trust(
    agent_id: str,
    pool: str,
    callsign: str,
    trust_network: TrustServiceProtocol,
    config: TieredTrustConfig,
    consensus_alpha: float = 2.0,
    consensus_beta: float = 2.0,
) -> TrustTier:
    """Initialize an agent's trust record based on their tier.

    Returns the resolved tier for logging/boot camp integration.
    """
    if not config.enabled:
        trust_network.get_or_create(agent_id)
        return TrustTier.CREW

    tier = resolve_tier(pool, callsign, config)

    if tier == TrustTier.BRIDGE:
        trust_network.create_with_prior(agent_id, config.bridge_alpha, config.bridge_beta)
        logger.info("AD-640: %s (%s) → BRIDGE tier (α=%.1f, β=%.1f)",
                     callsign, agent_id, config.bridge_alpha, config.bridge_beta)
    elif tier == TrustTier.CHIEF:
        trust_network.create_with_prior(agent_id, config.chief_alpha, config.chief_beta)
        logger.info("AD-640: %s (%s) → CHIEF tier (α=%.1f, β=%.1f)",
                     callsign, agent_id, config.chief_alpha, config.chief_beta)
    else:
        # Crew — use default consensus priors (existing behavior)
        trust_network.create_with_prior(agent_id, consensus_alpha, consensus_beta)
        logger.debug("AD-640: %s (%s) → CREW tier (default)", callsign, agent_id)

    return tier
```

### 3. Modify `agent_onboarding.py` — Use Tiered Initialization

**File:** `src/probos/agent_onboarding.py`

Replace lines 155-156:
```python
        # Initialize trust record
        self._trust_network.get_or_create(agent.id)
```

With:
```python
        # AD-640: Initialize trust record with role-based tier
        from probos.tiered_trust import initialize_trust
        tier = initialize_trust(
            agent_id=agent.id,
            pool=agent.pool,
            callsign=agent.callsign,
            trust_network=self._trust_network,
            config=self._config.tiered_trust,
            consensus_alpha=self._config.consensus.trust_prior_alpha,
            consensus_beta=self._config.consensus.trust_prior_beta,
        )
```

### 4. Integrate with Boot Camp (AD-638)

**File:** `src/probos/boot_camp.py`

Currently boot camp enrolls all agents in cold-start. With tiered trust:
- **Bridge agents** (BRIDGE tier): Skip boot camp entirely — they start above Commander threshold and establish command climate.
- **Department Chiefs** (CHIEF tier): Skip boot camp — they start at Commander and begin mentoring crew immediately.
- **Crew** (CREW tier): Enrolled in boot camp as before.

In `BootCampCoordinator`, add a tier check to the enrollment method. The coordinator needs to know the resolved tier. Two approaches:

**Option A (recommended):** Boot camp checks trust score at enrollment time. Bridge/Chief agents will have trust > 0.7 (above `BootCampConfig.min_trust_score` default of 0.55), so they naturally skip enrollment if the enrollment condition checks current trust:

In the enrollment logic, add a trust-score check:
```python
# Skip agents already above graduation trust threshold
current_trust = self._trust_service.get_trust_score(agent_id)
if current_trust >= self._config.boot_camp.min_trust_score:
    logger.info("AD-640: %s trust=%.2f — skips boot camp (above graduation threshold)",
                callsign, current_trust)
    return  # Already trusted enough
```

This is the cleanest integration — boot camp doesn't need to know about tiers, it just sees that Bridge/Chief agents already meet graduation criteria.

**Option B:** Pass the tier explicitly. More coupling, less recommended.

### 5. Emit TIERED_TRUST_INITIALIZED Event

**File:** `src/probos/events.py`

Add to EventType enum:
```python
TIERED_TRUST_INITIALIZED = "tiered_trust_initialized"
```

Emit from `initialize_trust()` — but since tiered_trust.py is a pure function module, emit from the call site in `agent_onboarding.py` instead:

After the `initialize_trust()` call:
```python
        # AD-640: Emit tiered trust event
        self._event_emitter(EventType.TIERED_TRUST_INITIALIZED, {
            "agent_id": agent.id,
            "callsign": agent.callsign,
            "pool": agent.pool,
            "tier": tier.value,
            "trust": format_trust(self._trust_network.get_score(agent.id)),
        })
```

### 6. Update Agent State Event

In `agent_onboarding.py` lines 158-165, the `AGENT_STATE` event already emits `trust`. Since tiered trust initialization happens on line 156 (before the event), the trust value will already reflect the tier. No change needed.

## Files Changed

| File | Change |
|------|--------|
| `src/probos/config.py` | Add `TieredTrustConfig`, wire into `SystemConfig` |
| `src/probos/tiered_trust.py` | **NEW** — tier resolution + initialization |
| `src/probos/agent_onboarding.py` | Replace `get_or_create()` with `initialize_trust()`, emit event |
| `src/probos/events.py` | Add `TIERED_TRUST_INITIALIZED` event type |
| `src/probos/boot_camp.py` | Add trust-score check to enrollment (skip high-trust agents) |
| `tests/test_ad640_tiered_trust.py` | **NEW** — tests |

## Tests (`tests/test_ad640_tiered_trust.py`)

### Tier Resolution Tests
1. **test_resolve_tier_bridge_pool** — counselor pool → BRIDGE
2. **test_resolve_tier_bridge_callsign** — "Meridian" → BRIDGE
3. **test_resolve_tier_chief_callsign** — each chief callsign → CHIEF
4. **test_resolve_tier_crew_default** — unknown pool/callsign → CREW
5. **test_resolve_tier_case_sensitive** — "bones" (lowercase) → CREW (callsigns are case-sensitive)

### Trust Initialization Tests
6. **test_initialize_bridge_trust** — Bridge agent gets alpha=4.5, beta=1.0
7. **test_initialize_chief_trust** — Chief agent gets alpha=3.0, beta=1.0
8. **test_initialize_crew_trust** — Crew agent gets default alpha=2.0, beta=2.0
9. **test_initialize_disabled** — When `enabled=False`, all agents get default (get_or_create path)
10. **test_initialize_returns_tier** — Return value matches resolved tier

### Integration Tests
11. **test_onboarding_uses_tiered_trust** — AgentOnboardingService calls `initialize_trust` (not bare `get_or_create`)
12. **test_tiered_trust_event_emitted** — TIERED_TRUST_INITIALIZED event fires with correct tier/trust
13. **test_boot_camp_skips_high_trust** — Bridge/Chief agents skip boot camp enrollment
14. **test_boot_camp_enrolls_crew** — Crew agents still enrolled in boot camp
15. **test_probationary_agents_unchanged** — Self-mod agents still use probationary priors (alpha=1.0, beta=3.0)

### Config Tests
16. **test_tiered_trust_config_defaults** — Default values match research recommendation
17. **test_tiered_trust_config_customizable** — Values can be overridden via config
18. **test_system_config_includes_tiered_trust** — `SystemConfig().tiered_trust` exists

## Engineering Principles Compliance

- **SRP:** Tier resolution logic in its own module (`tiered_trust.py`), not stuffed into onboarding or trust network.
- **OCP:** New tiers can be added to config lists without modifying `resolve_tier()` logic (bridge_pools, bridge_callsigns, chief_callsigns are config-driven).
- **DIP:** `TrustServiceProtocol` — tiered_trust depends on a Protocol, not the concrete TrustNetwork class.
- **Law of Demeter:** `initialize_trust()` takes flat parameters, doesn't reach through objects.
- **Fail Fast:** Invalid config values caught by Pydantic validation.
- **DRY:** Reuses existing `create_with_prior()` — no duplication of trust record creation logic.
- **Cloud-Ready:** Config-driven — commercial overlay can customize tier membership and priors.

## Verification Checklist (for builder)

- [ ] `TrustNetwork.create_with_prior(agent_id, alpha, beta)` signature matches `consensus/trust.py:190`
- [ ] `TrustNetwork.get_or_create(agent_id)` signature matches `consensus/trust.py:180`
- [ ] `TrustNetwork.get_score(agent_id)` exists — verify method name
- [ ] `agent.pool` and `agent.callsign` attributes exist on BaseAgent (`substrate/agent.py:35,164`)
- [ ] `EventType` enum is in `events.py`
- [ ] `format_trust` imported from `probos.config`
- [ ] `BootCampCoordinator` enrollment method name — check `boot_camp.py` for actual method
- [ ] `SystemConfig` field naming convention (snake_case, `BaseModel`)
- [ ] Import `tiered_trust` at call site (inside function) to avoid circular imports

## Builder Instructions

```
Read and execute the build prompt in d:\ProbOS\prompts\ad-640-tiered-trust-initialization.md
```

Run targeted tests after:
```
python -m pytest tests/test_ad640_tiered_trust.py -v
```
