# AD-571: Agent Tier Trust Separation — Crew vs Non-Crew Trust Boundaries

**Status:** Ready for builder
**Issue:** #21
**Dependencies:** AD-558 (trust cascade dampening), AD-557 (emergence metrics)
**Estimated tests:** 14

---

## Problem

Trust infrastructure (TrustNetwork, HebbianRouter, EmergenceMetricsEngine, cascade dampening) is tier-agnostic. All agents are tracked identically. Utility and infrastructure agents at static ~0.5 trust dilute metrics, contribute to cascade false positives via `cascade_agent_threshold` counting, and add emergence noise to pairwise synergy computation. There is no code-level concept of agent tiers despite AD-398 establishing the design concept.

## Solution

Add an `AgentTierRegistry` that classifies agents into three tiers: `CORE_INFRASTRUCTURE`, `UTILITY`, and `CREW`. Wire it into TrustNetwork, EmergenceMetricsEngine, and HebbianRouter so that trust recording, cascade threshold counting, emergence computation, and weight reporting can filter by tier.

---

## Implementation

### 1. AgentTier Enum and AgentTierRegistry

**New file:** `src/probos/substrate/agent_tier.py`

Create `AgentTier` as a `StrEnum` with three values: `CORE_INFRASTRUCTURE`, `UTILITY`, `CREW`.

Create `AgentTierRegistry` class:
- Constructor: `__init__(self)` — initializes an empty `dict[str, AgentTier]` mapping agent_id to tier.
- `register(agent_id: str, tier: AgentTier) -> None` — register an agent's tier. Overwrites if already registered.
- `get_tier(agent_id: str) -> AgentTier` — return the registered tier. If not registered, return `AgentTier.UTILITY` as default.
- `is_crew(agent_id: str) -> bool` — convenience: `get_tier(agent_id) == AgentTier.CREW`.
- `crew_agents() -> list[str]` — return sorted list of all agent IDs registered as `CREW`.
- `all_registered() -> dict[str, AgentTier]` — return a copy of the full mapping.

### 2. AgentTierConfig

**File:** `src/probos/config.py`

Add `AgentTierConfig(BaseModel)`:
```python
class AgentTierConfig(BaseModel):
    """Agent tier classification for trust separation (AD-571)."""
    crew_types: list[str] = [
        "architect", "builder", "code_reviewer", "counselor",
        "diagnostician", "surgeon", "pharmacist", "pathologist",
        "red_team", "system_qa", "scout",
        "data_analyst", "systems_analyst", "research_specialist",
    ]
    core_types: list[str] = ["event_log", "vitals_monitor", "introspect"]
```

Add to `SystemConfig`:
```python
agent_tiers: AgentTierConfig = AgentTierConfig()
```

Classification rule: if `agent_type` in `core_types` -> `CORE_INFRASTRUCTURE`; if `agent_type` in `crew_types` -> `CREW`; all others -> `UTILITY`.

### 3. Wire into TrustNetwork

**File:** `src/probos/consensus/trust.py`

Add a new method to `TrustNetwork`:
```python
def set_tier_registry(self, registry: Any) -> None:
    """Inject agent tier registry for tier-aware filtering (AD-571)."""
    self._tier_registry = registry
```

Initialize `self._tier_registry: Any = None` in `__init__()` (add after `self._floor_hit_count`).

Modify `all_scores()` (currently at line ~441):
```python
def all_scores(self, crew_only: bool = False) -> dict[AgentID, float]:
    """Return all agent trust scores.

    Args:
        crew_only: If True and a tier registry is set, return only CREW agents.
    """
    if crew_only and self._tier_registry:
        return {
            aid: r.score for aid, r in self._records.items()
            if self._tier_registry.is_crew(aid)
        }
    return {aid: r.score for aid, r in self._records.items()}
```

Modify `record_outcome()` — at the top of the method, after `cfg = self._dampening_config`, add an early return for CORE_INFRASTRUCTURE agents:
```python
# AD-571: Skip trust recording for core infrastructure agents
if self._tier_registry:
    from probos.substrate.agent_tier import AgentTier
    if self._tier_registry.get_tier(agent_id) == AgentTier.CORE_INFRASTRUCTURE:
        record = self.get_or_create(agent_id)
        return record.score
```

Modify cascade threshold counting — in the cascade trip check (around line ~355-357), where `unique_agents` is computed, filter to exclude non-CREW:
```python
unique_agents = {a[1] for a in self._cascade.recent_anomalies}
if self._tier_registry:
    unique_agents = {a for a in unique_agents if self._tier_registry.is_crew(a)}
```

### 4. Wire into EmergenceMetricsEngine

**File:** `src/probos/cognitive/emergence_metrics.py`

Add to `EmergenceMetricsEngine.__init__()`:
```python
self._tier_registry: Any = None
```

Add method:
```python
def set_tier_registry(self, registry: Any) -> None:
    """Inject agent tier registry for crew-only emergence computation (AD-571)."""
    self._tier_registry = registry
```

In `compute_emergence_metrics()` method, where agent pairs are constructed for PID analysis, filter to crew-only agents when a registry is set. Locate where the `authors` set is built from thread posts. After building the author set, add:
```python
if self._tier_registry:
    authors = {a for a in authors if self._tier_registry.is_crew(a)}
```

This ensures `pairs_analyzed` reflects crew-only pairs.

### 5. Wire into HebbianRouter

**File:** `src/probos/mesh/routing.py`

Add to `HebbianRouter.__init__()`:
```python
self._tier_registry: Any = None
```

Add method:
```python
def set_tier_registry(self, registry: Any) -> None:
    """Inject agent tier registry for tier-aware reporting (AD-571)."""
    self._tier_registry = registry
```

Add `crew_only` parameter to `all_weights()`:
```python
def all_weights(self, crew_only: bool = False) -> dict[tuple[AgentID, AgentID], float]:
    """Backward-compatible: return (source, target) -> weight."""
    if crew_only and self._tier_registry:
        return {
            (s, t): w for (s, t), w in self._compat_weights.items()
            if self._tier_registry.is_crew(s) or self._tier_registry.is_crew(t)
        }
    return dict(self._compat_weights)
```

No changes to `record_interaction()` — all agents route equally regardless of tier.

### 6. Populate Registry During Startup

**File:** `src/probos/startup/finalize.py`

Add a new helper function `_populate_agent_tiers(runtime, config)`:
```python
def _populate_agent_tiers(*, runtime: Any, config: "SystemConfig") -> int:
    """AD-571: Classify all registered agents into tiers."""
    from probos.substrate.agent_tier import AgentTier, AgentTierRegistry

    registry = AgentTierRegistry()
    crew_types = set(config.agent_tiers.crew_types)
    core_types = set(config.agent_tiers.core_types)

    agent_registry = getattr(runtime, "registry", None)
    if not agent_registry:
        return 0

    for agent_id in agent_registry.all():
        agent = agent_registry.get(agent_id)
        agent_type = getattr(agent, "agent_type", "")
        if agent_type in core_types:
            registry.register(agent_id, AgentTier.CORE_INFRASTRUCTURE)
        elif agent_type in crew_types:
            registry.register(agent_id, AgentTier.CREW)
        else:
            registry.register(agent_id, AgentTier.UTILITY)

    # Wire into trust/emergence/hebbian
    trust = getattr(runtime, "_trust_network", None)
    if trust and hasattr(trust, "set_tier_registry"):
        trust.set_tier_registry(registry)

    emergence = getattr(runtime, "_emergence_metrics_engine", None)
    if emergence and hasattr(emergence, "set_tier_registry"):
        emergence.set_tier_registry(registry)

    router = getattr(runtime, "_router", None)
    if router and hasattr(router, "set_tier_registry"):
        router.set_tier_registry(registry)

    runtime._tier_registry = registry
    return len(registry.all_registered())
```

Call `_populate_agent_tiers(runtime=runtime, config=config)` from `finalize_startup()` — add it after the existing wiring calls (after `_wire_tiered_knowledge_loader` is a good location). Log the count.

---

## Tests

**File:** `tests/test_ad571_tier_separation.py`

14 tests:

1. `test_register_and_get_tier` — register agent, verify get_tier returns correct tier
2. `test_default_tier_utility` — unregistered agent returns UTILITY
3. `test_is_crew` — verify is_crew returns True for CREW, False for others
4. `test_crew_agents_list` — register mixed tiers, verify crew_agents() returns only CREW sorted
5. `test_trust_crew_only_scores` — TrustNetwork with tier registry, all_scores(crew_only=True) filters correctly
6. `test_trust_skip_core_recording` — record_outcome for CORE_INFRASTRUCTURE returns existing score without modifying alpha/beta
7. `test_cascade_excludes_utility` — cascade threshold counting excludes non-CREW agents
8. `test_emergence_crew_only` — EmergenceMetricsEngine filters to crew authors when registry set
9. `test_hebbian_crew_only_report` — all_weights(crew_only=True) filters to crew connections
10. `test_startup_population` — mock runtime with registry, verify _populate_agent_tiers classifies correctly
11. `test_tier_enum_values` — AgentTier has exactly 3 members with expected string values
12. `test_config_crew_types` — AgentTierConfig default crew_types includes 14 types, core_types includes 3
13. `test_mixed_tier_trust_scores` — all_scores(crew_only=False) returns all, crew_only=True returns subset
14. `test_all_agents_classified` — all registered agents appear in all_registered()

Use `_Fake*` stubs for TrustNetwork dependencies. No mocking of private attributes.

---

## What This Does NOT Change

- No dynamic tier reassignment at runtime
- No tier-based routing priority changes in HebbianRouter.record_interaction()
- No HXI tier visualization or API endpoints
- No changes to DreamingEngine — it uses TrustNetwork/EmergenceMetrics which are already filtered
- No changes to EarnedAgency or social verification
- No modification to the `_AGENT_DEPARTMENTS` mapping in standing_orders.py

---

## Tracking

- `PROGRESS.md`: Add AD-571 as CLOSED
- `DECISIONS.md`: Add entry — "AD-571: Three-tier agent classification (CORE_INFRASTRUCTURE/UTILITY/CREW) for trust metric separation. TrustNetwork skips recording for core infrastructure, cascade counts crew only, emergence analyzes crew only."
- `docs/development/roadmap.md`: Update AD-571 row status
