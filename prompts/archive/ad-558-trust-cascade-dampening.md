# AD-558: Trust Cascade Dampening

**Priority:** High
**Prerequisites:** BF-099 (trust engine concurrency safety) — COMPLETE
**Depends on:** AD-502–506 (Cognitive Self-Regulation) — COMPLETE, AD-495 (Counselor circuit breaker bridge) — COMPLETE
**Related:** AD-493 (Novelty Gate, not built — complementary), AD-494 (Trait-Adaptive Thresholds, not built — complementary)

## Context

BF-099 fixed the concurrency bugs in TrustNetwork (locks, WAL mode, transactions). But the trust engine still has zero dampening: every `record_outcome()` call applies full weight regardless of frequency, direction, or system state. The crew identified this gap — Medical team diagnosed a recurring "stuck calculation" with ~72-hour recurrence (same symptoms, same fix, same recurrence). Engineering (Forge + Reyes) independently designed adaptive thresholding.

**The open-loop problem:** Detection systems (EmergentDetector, Counselor, VitalsMonitor) observe trust anomalies but cannot intervene. The only protective mechanism is `decay_all()` which runs during dream cycles — hours apart. Between dreams, trust can cascade to near-zero with no circuit breaker.

**Cold-start amplification:** When `alpha + beta` is small (< 20), a single outcome swings trust dramatically. Early interactions compound: a few bad verifications can permanently damage an agent's trust before enough data exists for stability.

## Existing State (Post BF-099)

**`record_outcome()` (trust.py ~line 156):**
- Takes `agent_id`, `success`, `weight=1.0`, `intent_type`, `episode_id`, `verifier_id`, `source`
- If success: `alpha += weight`. If failure: `beta += weight`
- Appends `TrustEvent` to ring buffer (`deque(maxlen=500)`)
- Returns new score
- **Zero dampening, zero rate limiting, zero floor**

**Event emission:**
- `TRUST_UPDATE` events emitted ONLY from `runtime.py` (2 call sites: consensus verification, QA smoke tests)
- Dream consolidation (`dreaming.py _consolidate_trust()`) calls `record_outcome()` but does NOT emit events
- This is a third unmonitored trust update pathway

**Config constants available (config.py):**
- `TRUST_SENIOR = 0.85`, `TRUST_COMMANDER = 0.7`, `TRUST_LIEUTENANT = 0.5`, `TRUST_DEFAULT = 0.5`
- `TRUST_FLOOR_CONN = 0.6`, `TRUST_FLOOR_CREDIBILITY = 0.3`, `TRUST_DEGRADED = 0.2`
- `trust_prior_alpha = 2.0`, `trust_prior_beta = 2.0`, `trust_decay_rate = 0.999`
- `trust_delta_threshold = 0.15` (Counselor)
- `trust_drop_threshold = 0.15`, `trust_drop_alert_threshold = 0.25` (Bridge alerts)

**Department awareness:** TrustNetwork has zero knowledge of agent departments. VesselOntologyService has this mapping.

**Counselor trust handling (`counselor.py _on_trust_update()`):**
- Subscribes to `TRUST_UPDATE` events
- Reacts when delta exceeds 0.15 from baseline
- Runs assessment + therapeutic DM
- **Purely observational** — never intervenes to dampen or prevent trust updates

**Circuit breaker infrastructure (`circuit_breaker.py`):**
- `CognitiveCircuitBreaker` with `BreakerState` (CLOSED/OPEN/HALF_OPEN) and `CognitiveZone` (GREEN/AMBER/RED/CRITICAL)
- Operates on **output repetition patterns** (Jaccard similarity), NOT trust updates
- Completely orthogonal — do NOT reuse this class for trust dampening

## What to Build

Six sub-features, all within `trust.py` unless noted. Approach: keep dampening logic inside TrustNetwork. Department lookup and event emission are the only external dependencies.

---

### Part 0: Configuration (`config.py`)

Add `TrustDampeningConfig` dataclass to `config.py`, following the pattern of `CircuitBreakerConfig`:

```python
@dataclass
class TrustDampeningConfig:
    """Configuration for trust cascade dampening (AD-558)."""
    # Progressive dampening
    dampening_window_seconds: float = 300.0  # Time window for consecutive same-direction tracking
    dampening_geometric_factors: tuple = (1.0, 0.75, 0.5, 0.25)  # Weight multipliers: 1st, 2nd, 3rd, 4th+ consecutive
    dampening_floor: float = 0.25  # Minimum dampening factor (4th+ consecutive)

    # Hard trust floor
    hard_trust_floor: float = 0.05  # Below this, negative updates silently absorbed

    # Network circuit breaker
    cascade_agent_threshold: int = 3  # M agents with anomalous movement
    cascade_department_threshold: int = 2  # Across N departments
    cascade_delta_threshold: float = 0.15  # Delta from baseline considered anomalous
    cascade_window_seconds: float = 300.0  # Time window for cascade detection
    cascade_global_dampening: float = 0.5  # Ship-wide dampening factor when tripped
    cascade_cooldown_seconds: float = 600.0  # Global dampening duration

    # Cold-start scaling
    cold_start_observation_threshold: float = 20.0  # alpha + beta below this = cold start
    cold_start_dampening_floor: float = 0.5  # More aggressive dampening during cold start
```

Add `dampening` field to the main config (either `ConsensusConfig` or top-level `ProbOSConfig`), defaulting to `TrustDampeningConfig()`.

Add constant:
```python
TRUST_HARD_FLOOR = 0.05  # Protective minimum — below this, negative updates silently absorbed
```

---

### Part 1: Progressive Dampening (`trust.py`)

Add per-agent dampening state tracking to `TrustNetwork`:

```python
@dataclass
class _DampeningState:
    """Per-agent dampening tracker for consecutive same-direction trust updates."""
    consecutive_count: int = 0
    direction: str = ""  # "positive" or "negative"
    first_timestamp: float = 0.0
    last_timestamp: float = 0.0
```

Implementation in `TrustNetwork`:
- Add `self._dampening: dict[str, _DampeningState] = {}` to `__init__`
- In `record_outcome()`, BEFORE applying the weight:
  1. Determine direction: `"positive"` if success else `"negative"`
  2. Get or create dampening state for agent
  3. If same direction AND within window: increment consecutive count
  4. If different direction OR window expired: reset to count=1
  5. Look up geometric factor: `factors[min(count-1, len(factors)-1)]`
  6. If cold start (`alpha + beta < cold_start_threshold`): use `max(factor, cold_start_dampening_floor)` — i.e., MORE aggressive dampening
  7. `effective_weight = weight * dampening_factor`
  8. Apply `effective_weight` instead of `weight`
  9. Record the dampening factor in the `TrustEvent` (add `dampening_factor` field to `TrustEvent`)

**Critical:** `effective_weight = weight * dampening_factor`. This preserves Shapley attribution (the `weight` parameter carries domain meaning).

**Note on concurrency:** `record_outcome()` is sync and runs on a single event loop. `_dampening` dict mutations are GIL-protected. No additional locking needed beyond BF-099's existing `self._lock`.

---

### Part 2: Hard Trust Floor (`trust.py`)

In `record_outcome()`, AFTER computing `effective_weight` and BEFORE applying it:

```python
current_score = self.get_score(agent_id)
if not success and current_score <= self._config.dampening.hard_trust_floor:
    # Below floor — absorb negative update, log it, still record the event
    # Add floor_hit=True to TrustEvent
    # DO NOT apply the weight
    return current_score
```

Add `floor_hit: bool = False` field to `TrustEvent`.

**Design choice:** Positive updates always apply even below the floor. Only negative updates are absorbed. This allows recovery.

---

### Part 3: Network-Level Circuit Breaker (`trust.py`)

Add cascade detection to `TrustNetwork`:

```python
@dataclass
class _CascadeState:
    """Network-level trust cascade circuit breaker."""
    recent_anomalies: list  # List of (timestamp, agent_id, department, delta) tuples
    tripped: bool = False
    tripped_at: float = 0.0
    cooldown_until: float = 0.0
```

Implementation:
- Add `self._cascade = _CascadeState(recent_anomalies=[])` to `__init__`
- Add `self._get_department: Callable[[str], str | None] | None = None` — a department lookup function injected at startup
- In `record_outcome()`, AFTER applying the update:
  1. Compute delta from baseline (pre-update score vs post-update score — the delta is already available from the TrustEvent)
  2. If `abs(delta) > cascade_delta_threshold`: add anomaly to `recent_anomalies`
  3. Prune anomalies outside the window
  4. Count unique agents and unique departments in window
  5. If agents >= M AND departments >= N: trip the breaker
    - Set `tripped = True`, `tripped_at = now`, `cooldown_until = now + cooldown`
    - Emit `TRUST_CASCADE_WARNING` event (see Part 4)
  6. While tripped and within cooldown: apply `cascade_global_dampening` as an additional multiplier on ALL trust updates (multiply into `effective_weight` for every agent, not just the anomalous ones)
  7. After cooldown expires: reset breaker, clear anomalies

**Department lookup injection:** During `TrustNetwork.start()` or via a `set_department_lookup(fn)` method, inject a callable that maps `agent_id → department_name`. The runtime wires this from VesselOntologyService during startup. If not set, skip the department count check and only use the agent count threshold.

```python
def set_department_lookup(self, fn: Callable[[str], str | None]) -> None:
    """Inject department resolution for cascade detection. Called by runtime during startup."""
    self._get_department = fn
```

---

### Part 4: Event Emission (`trust.py`, `events.py`, `types.py`)

**New event type** in `events.py`:
```python
TRUST_CASCADE_WARNING = "trust_cascade_warning"
```

**New typed event** in `types.py`:
```python
@dataclass
class TrustCascadeEvent:
    """Emitted when the trust cascade circuit breaker trips."""
    timestamp: float
    anomalous_agents: list[str]
    departments_affected: list[str]
    global_dampening_factor: float
    cooldown_seconds: float
```

**Event emission from `record_outcome()`:**

Add an optional event emission callback to TrustNetwork:
```python
def set_event_callback(self, fn: Callable[[str, Any], None]) -> None:
    """Inject event emission for trust updates. Called by runtime during startup."""
    self._emit_event = fn
```

In `record_outcome()`, AFTER applying the update:
- Emit `TRUST_UPDATE` event with the `TrustEvent` data (this centralizes emission — remove the 2 emission sites in `runtime.py` that currently emit `TRUST_UPDATE` after calling `record_outcome()`)
- If cascade breaker trips: emit `TRUST_CASCADE_WARNING` with `TrustCascadeEvent`

**Important migration:** After adding emission inside `record_outcome()`, remove the `_emit(EventType.TRUST_UPDATE, ...)` calls in `runtime.py` (search for the 2 call sites). All trust events now flow through one path. Verify that the event payload structure matches what `counselor.py _on_trust_update()` expects (it reads `event_data.get("agent_id")`, `event_data.get("new_score")`, `event_data.get("old_score")`).

---

### Part 5: Counselor Integration (`counselor.py`)

Add subscription to `TRUST_CASCADE_WARNING`:

```python
# In _setup_event_subscriptions():
self._subscribe(EventType.TRUST_CASCADE_WARNING, self._on_trust_cascade)
```

Handler:
```python
async def _on_trust_cascade(self, event_data: dict) -> None:
    """Respond to trust cascade warning — run ship-wide wellness sweep."""
    # Log the cascade event
    # Run wellness sweep across all affected agents
    # Issue Counselor directive if patterns are concerning
    # Rate-limit: one sweep per cascade cooldown period
```

---

### Part 6: Dampening Telemetry (`trust.py`)

Add a method to expose dampening state for VitalsMonitor:

```python
def get_dampening_telemetry(self) -> dict:
    """Return current dampening state for vitals/telemetry."""
    return {
        "per_agent": {
            agent_id: {
                "dampening_factor": self._current_factor(agent_id),
                "consecutive_count": state.consecutive_count,
                "direction": state.direction,
            }
            for agent_id, state in self._dampening.items()
        },
        "cascade_breaker": {
            "tripped": self._cascade.tripped,
            "cooldown_remaining": max(0, self._cascade.cooldown_until - time.time()),
            "anomaly_count": len(self._cascade.recent_anomalies),
        },
        "floor_hits": self._floor_hit_count,  # Simple counter, reset each dream cycle
    }
```

---

### Part 7: Runtime Wiring (`runtime.py` or appropriate startup module)

During startup, wire the TrustNetwork dependencies:

```python
# After trust_network.start():
trust_network.set_department_lookup(
    lambda agent_id: ontology_service.get_agent_department(agent_id)
)
trust_network.set_event_callback(
    lambda event_type, data: self._emit(event_type, data)
)
```

Check which startup module handles trust initialization (likely `startup/services.py` or similar post-decomposition). Wire there.

**Remove the 2 existing `TRUST_UPDATE` emission sites in `runtime.py`** after confirming `record_outcome()` now emits internally. Search for:
- Line ~1467: after consensus verification
- Line ~2822: after QA smoke tests

Verify the emitted payload dict matches what `counselor.py _on_trust_update()` reads.

---

## Tests

### File: `tests/test_trust_dampening.py` (~35-40 tests)

**Progressive dampening:**
1. First update in a direction applies full weight (factor 1.0)
2. Second consecutive same-direction update applies 0.75x weight
3. Third consecutive applies 0.5x weight
4. Fourth+ consecutive applies 0.25x weight (floor)
5. Direction reversal resets dampening count
6. Window expiry resets dampening count
7. Different agents have independent dampening state
8. Cold-start scaling applies more aggressive dampening when alpha+beta < 20
9. Cold-start dampening floor is 0.5 (not the normal 0.25)
10. Dampening factor is recorded in TrustEvent

**Hard trust floor:**
11. Negative update at score above floor applies normally
12. Negative update at score at/below floor is silently absorbed
13. Positive update at score below floor still applies (allows recovery)
14. Floor hit is recorded in TrustEvent
15. Floor value is configurable

**Network circuit breaker:**
16. Single agent anomaly does not trip breaker
17. M agents in 1 department does not trip breaker (need N departments)
18. M agents across N departments within window trips breaker
19. Anomalies outside window are pruned (no false trip)
20. While tripped: all trust updates get global dampening multiplier
21. After cooldown: breaker resets, normal weight resumes
22. Cascade emits TRUST_CASCADE_WARNING event
23. Without department lookup: only agent count threshold used
24. Department lookup injection works correctly

**Event emission:**
25. record_outcome() emits TRUST_UPDATE when callback is set
26. record_outcome() does NOT emit when callback is not set (no crash)
27. Emitted event payload matches Counselor expectations (agent_id, old_score, new_score)
28. Dream consolidation trust updates now emit events (via record_outcome callback)
29. Removing runtime.py emission sites does not break event flow

**Cold-start dampening:**
30. Agent with alpha+beta < 20 gets cold-start dampening floor
31. Agent with alpha+beta >= 20 gets normal dampening
32. Cold-start threshold is configurable

**Telemetry:**
33. get_dampening_telemetry() returns correct per-agent state
34. get_dampening_telemetry() returns cascade breaker state
35. get_dampening_telemetry() returns floor hit count
36. Floor hit count resets (verify mechanism)

**Integration:**
37. Progressive dampening + cascade breaker stack multiplicatively (effective_weight = weight * agent_dampening * global_dampening)
38. Counselor receives TRUST_CASCADE_WARNING and runs sweep
39. Full cascade scenario: rapid negative updates → dampening kicks in → cascade trips → global dampening → cooldown → recovery
40. BF-099 lock still works correctly with dampening (no deadlock)

---

## Implementation Notes

1. **Do NOT reuse `CognitiveCircuitBreaker`** for trust cascades. That class operates on content repetition patterns (Jaccard similarity). Trust cascade detection is structurally different (numeric deltas, multi-agent correlation). Keep them separate.

2. **Preserve `weight` semantics.** The `weight` parameter in `record_outcome()` carries Shapley attribution. Dampening multiplies it, never replaces it: `effective_weight = weight * dampening_factor * global_dampening_factor`.

3. **Event emission migration.** Moving `TRUST_UPDATE` emission into `record_outcome()` is a significant change. The callback approach (`set_event_callback`) keeps TrustNetwork decoupled from the event bus. Verify the payload dict structure matches what `_on_trust_update()` in counselor.py expects before removing the runtime.py emission sites.

4. **The `_get_department` lookup must not fail loudly.** If the ontology service isn't available, cascade detection falls back to agent-count-only. Wrap the lookup: `dept = self._get_department(agent_id) if self._get_department else None`.

5. **Test isolation.** Dampening state is per-TrustNetwork instance. Each test should create a fresh TrustNetwork. Do NOT rely on module-level state.

6. **Config accessibility.** TrustNetwork needs access to `TrustDampeningConfig`. Pass it through the constructor or via a config property. Follow the existing pattern — check how `CircuitBreakerConfig` is accessed by `CognitiveCircuitBreaker`.

7. **Verify `ontology_service.get_agent_department()`** exists or find the correct method name. If no such method exists, add a simple one that returns the department name string for an agent_id, or use whatever department lookup is available in the ontology service.

8. **Logging.** Add structured logging for: dampening factor applied (DEBUG), floor hit (INFO), cascade breaker trip (WARNING), cascade breaker reset (INFO). Follow existing logging patterns in trust.py.

## Acceptance Criteria

- [ ] Progressive dampening reduces weight on consecutive same-direction updates
- [ ] Hard floor prevents trust from dropping below 0.05
- [ ] Network breaker trips on cross-department anomaly clusters
- [ ] TRUST_CASCADE_WARNING event emitted and Counselor responds
- [ ] Dream consolidation trust updates now emit TRUST_UPDATE events
- [ ] Cold-start scaling provides more aggressive dampening for new agents
- [ ] Telemetry endpoint exposes dampening state
- [ ] All 40 tests pass
- [ ] Existing trust/dreaming/hebbian regression (128 tests from BF-099) still passes
- [ ] No changes to TrustNetwork public API signature (backward compatible)
