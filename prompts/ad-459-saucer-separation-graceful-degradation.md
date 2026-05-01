# AD-459: Saucer Separation — Graceful Degradation

**Status:** Ready for builder
**Dependencies:** None hard. Independent of `bridge_alerts.py` (verified — `bridge_alerts.py:24 AlertSeverity` is severity-based, not tier-based; AD-459's three-tier service classification is orthogonal). **AD-459 OWNS `src/probos/degradation/__init__.py` directory creation** (mirroring AD-455's `security/` precedent).
**Estimated tests:** ~13
**Risk:** High — cross-cutting (touches `runtime.py`, `startup/finalize.py`, alert paths). Wave-6 inter-prompt full gate must verify no shedding of degradable test surfaces.

---

## Problem

When critical systems fail (LLM provider down, ChromaDB corruption, NATS reconnect storm), ProbOS today either keeps trying with full functionality (wasting cycles, cascading failures) or crashes (loses all state).

There is no service-tier classification:

- **Essential** — file ops, shell, IntentBus routing, trust reads, event logging. Always survive.
- **Cognitive** — LLM-dependent paths (CognitiveAgents, dreaming, decomposition). Gracefully degrade: queue requests, switch to cached responses, defer dream cycles.
- **Non-essential** — analytics, telemetry, periodic introspection. First to shed.

`grep -rn "ServiceTier\|degradation\|saucer_separation" src/probos/` returns no matches. The existing `bridge_alerts.AlertSeverity` (verified at `bridge_alerts.py:24`) handles **incident severity** — info/warning/critical — for operator notification. It does NOT classify services into tiers; the two systems are orthogonal.

What is needed:

1. **`ServiceTier`** enum — ESSENTIAL / COGNITIVE / NON_ESSENTIAL.
2. **`ServiceTierRegistry`** — maps known runtime services to their tier. Pre-populated for known services; runtime-extensible for designed services.
3. **`SheddingPolicy`** — given a system stress level (low / medium / high / critical), returns the set of tiers that should be shed.
4. **`DegradationManager`** — read-only coordinator (v1). Inventories registered services, reports current shedding state, emits `EventType.SERVICE_TIER_DEGRADED` when policy says a tier should shed. **Does NOT mutate any service** — actual shedding is each subsystem's responsibility (e.g., dreaming engine reads `runtime.degradation_manager.is_shed("cognitive")` and skips its cycle).

This is the **coordinator-then-dispatch pattern** from the Wave 5 retrospective. v1 ships the read-only coordinator + registry + policy. Sub-AD AD-459b would add active shedding (subsystem hooks that call `degradation_manager.report_shed_action(...)`).

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
SERVICE_TIER_DEGRADED = "service_tier_degraded"  # AD-459
SERVICE_TIER_RESTORED = "service_tier_restored"  # AD-459
```

Two new values. Verified absent via `grep -n "SERVICE_TIER" src/probos/events.py` (no matches).

---

## Section 1: Create `src/probos/degradation/` package

**IMPORTANT:** `src/probos/degradation/` does NOT exist. Create `src/probos/degradation/__init__.py` (empty docstring file) before any other module — same pattern as AD-455's `security/` and AD-676's `governance/`.

```python
# src/probos/degradation/__init__.py
"""Saucer Separation — Graceful Degradation (AD-459)."""
```

---

## Section 2: `ServiceTier` and registry

**File:** `src/probos/degradation/registry.py` (new)

```python
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


# Default classifications. The registry seeds with these and accepts
# runtime additions. Names match attribute names on ProbOSRuntime where
# possible to make grep-confirmation easy for operators.
_DEFAULT_CLASSIFICATIONS: tuple[ServiceClassification, ...] = (
    ServiceClassification("event_log", ServiceTier.ESSENTIAL, "audit log"),
    ServiceClassification("trust_network", ServiceTier.ESSENTIAL, "trust reads"),
    ServiceClassification("registry", ServiceTier.ESSENTIAL, "agent registry"),
    ServiceClassification("intent_bus", ServiceTier.ESSENTIAL, "intent dispatch"),
    ServiceClassification("hebbian_router", ServiceTier.ESSENTIAL, "routing weights"),
    ServiceClassification("cognitive_agent", ServiceTier.COGNITIVE, "LLM-driven agents"),
    ServiceClassification("dreaming", ServiceTier.COGNITIVE, "dream consolidation"),
    ServiceClassification("decomposer", ServiceTier.COGNITIVE, "intent decomposition"),
    ServiceClassification("proactive_loop", ServiceTier.COGNITIVE, "proactive cognition"),
    ServiceClassification("emergence_metrics_engine", ServiceTier.NON_ESSENTIAL, "emergence analytics"),
    ServiceClassification("emergent_leadership_detector", ServiceTier.NON_ESSENTIAL, "AD-439 analytics"),
    ServiceClassification("introspection_agent", ServiceTier.NON_ESSENTIAL, "diagnostic introspection"),
    ServiceClassification("red_team_lead", ServiceTier.NON_ESSENTIAL, "red team campaigns"),
)


@dataclass
class ServiceTierRegistry:
    """Maps service names to ServiceTier. Seed + runtime extensions."""

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
        return [
            c.service_name for c in self._classifications.values() if c.tier == tier
        ]

    def all_classifications(self) -> list[ServiceClassification]:
        return list(self._classifications.values())
```

---

## Section 3: `SheddingPolicy`

**File:** `src/probos/degradation/policy.py` (new)

```python
"""AD-459: Shedding policy — maps stress level to shed tiers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from probos.degradation.registry import ServiceTier


class StressLevel(str, Enum):
    """System stress level. Higher = more aggressive shedding."""

    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SheddingPolicy:
    """Maps stress level to the set of tiers that should be shed.

    Default policy:
        NORMAL    -> shed nothing
        ELEVATED  -> shed NON_ESSENTIAL
        HIGH      -> shed NON_ESSENTIAL + COGNITIVE
        CRITICAL  -> shed NON_ESSENTIAL + COGNITIVE (ESSENTIAL never shed)
    """

    def shed_tiers(self, level: StressLevel) -> frozenset[ServiceTier]:
        if level == StressLevel.NORMAL:
            return frozenset()
        if level == StressLevel.ELEVATED:
            return frozenset({ServiceTier.NON_ESSENTIAL})
        if level == StressLevel.HIGH:
            return frozenset(
                {ServiceTier.NON_ESSENTIAL, ServiceTier.COGNITIVE},
            )
        # CRITICAL — same as HIGH; ESSENTIAL never shed
        return frozenset(
            {ServiceTier.NON_ESSENTIAL, ServiceTier.COGNITIVE},
        )
```

---

## Section 4: `DegradationManager` (read-only coordinator)

**File:** `src/probos/degradation/manager.py` (new)

```python
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
                "AD-459: %s emit failed", et.value, exc_info=True,
            )
        logger.info(
            "AD-459: tier %s %s (stress=%s)",
            tier.value, "shed" if shed else "restored", self._level.value,
        )
```

---

## Section 5: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    PERFORMANCE_THRESHOLD_BREACHED = "performance_threshold_breached"  # AD-457
```

REPLACE:
```python
    PERFORMANCE_THRESHOLD_BREACHED = "performance_threshold_breached"  # AD-457
    SERVICE_TIER_DEGRADED = "service_tier_degraded"  # AD-459
    SERVICE_TIER_RESTORED = "service_tier_restored"  # AD-459
```

> Builder note: this assumes AD-457 lands first. If AD-457 has not landed, anchor on `AGENT_SELF_NAMED = "agent_self_named"  # AD-499` instead.

---

## Section 6: Add `DegradationConfig`

**File:** `src/probos/config.py`

```python
class DegradationConfig(BaseModel):
    """Saucer separation / graceful degradation (AD-459)."""

    enabled: bool = True
```

Wire into `SystemConfig`:

SEARCH:
```python
    pre_flight: PreFlightConfig = PreFlightConfig()  # AD-458
```

REPLACE:
```python
    pre_flight: PreFlightConfig = PreFlightConfig()  # AD-458
    degradation: DegradationConfig = DegradationConfig()  # AD-459
```

> Builder note: anchor depends on AD-458 landing first. If not, anchor on the AD-457 `engineering:` line.

---

## Section 7: Wire into startup

**File:** `src/probos/startup/finalize.py`

```python
    # AD-459: Saucer separation — graceful degradation
    if config.degradation.enabled:
        from probos.degradation.manager import DegradationManager
        from probos.degradation.policy import SheddingPolicy
        from probos.degradation.registry import ServiceTierRegistry
        runtime.degradation_manager = DegradationManager(
            registry=ServiceTierRegistry(),
            policy=SheddingPolicy(),
            emit_event=runtime.emit_event,
        )
        logger.info("AD-459: DegradationManager wired (stress=normal)")
```

> Verify-first: `runtime.degradation_manager` is published as a public attribute (no underscore) per Wave 5 retrospective convention.

---

## Tests

**File:** `tests/test_ad459_saucer_separation.py`

13 tests:

1. `test_event_type_service_tier_degraded_exists`
2. `test_event_type_service_tier_restored_exists`
3. `test_degradation_config_defaults` — `DegradationConfig()` defaults to `enabled=True`.
4. `test_service_tier_registry_default_classifications` — registry contains `event_log` (ESSENTIAL), `dreaming` (COGNITIVE), `red_team_lead` (NON_ESSENTIAL).
5. `test_service_tier_registry_register_extends` — `register(...)` adds a new classification.
6. `test_service_tier_registry_services_in_tier` — `services_in_tier(ESSENTIAL)` returns expected list.
7. `test_shedding_policy_normal_sheds_nothing` — `SheddingPolicy().shed_tiers(NORMAL) == frozenset()`.
8. `test_shedding_policy_elevated_sheds_non_essential` — only NON_ESSENTIAL.
9. `test_shedding_policy_high_sheds_cognitive_and_non_essential` — both.
10. `test_shedding_policy_critical_never_sheds_essential` — ESSENTIAL never in shed set.
11. `test_degradation_manager_set_stress_level_emits_tier_degraded` — transition NORMAL → HIGH emits two `SERVICE_TIER_DEGRADED` (NON_ESSENTIAL + COGNITIVE).
12. `test_degradation_manager_restore_emits_tier_restored` — transition HIGH → NORMAL emits `SERVICE_TIER_RESTORED` for both shed tiers.
13. `test_degradation_manager_is_shed_returns_correct_state` — `is_shed("dreaming")` is True at HIGH, False at NORMAL.

---

## What This Does NOT Change

- **No subsystem mutation.** v1 is read-only — subsystems consult the manager and self-degrade.
- **No background task.** Caller updates stress level. AD-459b will add health-driven auto-update.
- **`bridge_alerts.AlertSeverity` is untouched.** Severity (incident reporting) and tier (service classification) are orthogonal.
- **Active shedding hooks are deferred to AD-459b** — Wave 6 should NOT add `if degradation.is_shed(...)` checks throughout `cognitive/` modules; that's AD-459b scope.
- **No HXI panel.**
- **ESSENTIAL is hardcoded never-shed** — even in CRITICAL, ESSENTIAL services keep running. Operator override would require an AD.

---

## Tracking

- `PROGRESS.md`: add `AD-459 CLOSED. Saucer Separation — Graceful Degradation. ...`
- `docs/development/roadmap.md`: flip AD-459 status from `*(planned)*` to `*(complete)*` near line 4152.
- `DECISIONS.md`: optional entry recording the read-only-v1 + AD-459b deferral pattern.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/degradation/__init__.py`: 2 lines (new — owns directory).
- `src/probos/degradation/registry.py`: ~75 lines (new).
- `src/probos/degradation/policy.py`: ~45 lines (new).
- `src/probos/degradation/manager.py`: ~110 lines (new).
- `src/probos/events.py`: 2 lines added.
- `src/probos/config.py`: ~6 lines added.
- `src/probos/startup/finalize.py`: ~12 lines added.
- `tests/test_ad459_saucer_separation.py`: ~250 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 13 tests pass under `pytest tests/test_ad459_saucer_separation.py -v -n 0`.
- Full parallel gate non-decreasing.
- 2 new EventTypes in `events.py` exactly once.
- `src/probos/degradation/__init__.py` exists. AD-459 owns directory creation.
- `runtime.degradation_manager` published as public attribute.
- `bridge_alerts.AlertSeverity` is unchanged.
- No subsystem files in `src/probos/cognitive/` are modified — v1 is read-only coordinator.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-01)

```
ls src/probos/degradation/
  (does NOT exist — AD-459 creates it)

grep -n "class AlertSeverity\|class BridgeAlert" src/probos/bridge_alerts.py
  24: class AlertSeverity(str, Enum):
  32: class BridgeAlert:
  47: class BridgeAlertService:
  (severity-based incident reporting — orthogonal to AD-459 service tiers)

grep -rn "ServiceTier\|degradation\|saucer_separation" src/probos/
  (no matches — AD-459 introduces these)

grep -n "SERVICE_TIER" src/probos/events.py
  (no matches — names are free)

grep -n "AGENT_SELF_NAMED" src/probos/events.py
  190:    AGENT_SELF_NAMED = "agent_self_named"  # AD-499

ls src/probos/agents/medical/
  (precedent for new package layout — see AD-457 verification)
```
