# AD-494: Trait-Adaptive Circuit Breaker

**Issue:** (AD-494)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-488 (Cognitive Circuit Breaker — complete), AD-506a (Graduated Zones — complete), AD-376 (CrewProfile + PersonalityTraits — complete)
**Files:** `src/probos/cognitive/circuit_breaker.py` (EDIT), `src/probos/config.py` (EDIT), `src/probos/proactive.py` (EDIT), `tests/test_ad494_trait_adaptive_circuit_breaker.py` (NEW)

## Problem

The cognitive circuit breaker (AD-488, AD-506a) uses uniform thresholds for all agents. Every agent has the same velocity threshold (8 events / 5 min), the same similarity threshold (0.6), the same base cooldown (15 min), and the same amber/red zone triggers. This is a one-size-fits-all model applied to agents with dramatically different personalities.

Consider:
- **Wesley** (Scout): Openness 0.9, Neuroticism 0.2 — a highly curious, calm explorer. The circuit breaker trips too aggressively on his natural exploration behavior, treating curiosity as rumination.
- **Worf** (Security Officer): Openness 0.4, Neuroticism 0.5, Conscientiousness 0.9 — vigilant, disciplined, threat-focused. He *should* trip sooner on repetitive threat assessments because his high conscientiousness means repetition signals a genuine cognitive loop, not thoroughness.
- **Troi** (Counselor): Extraversion 0.8, Agreeableness 0.85 — naturally communicative and empathetic. High event velocity is normal for her role; the velocity threshold should be more lenient.

AD-494 makes the circuit breaker personality-aware. Each agent gets individualized thresholds computed from their Big Five personality profile. The adaptation is deterministic — a pure mathematical function of personality scores applied as multipliers to the base thresholds in `CircuitBreakerConfig`. No machine learning, no opaque inference.

**What this does NOT include:**
- Dynamic threshold adjustment based on runtime behavior (future — could integrate with dream consolidation)
- Counselor-initiated threshold overrides (future — Counselor could temporarily adjust thresholds for agents under therapeutic intervention)
- HXI visibility into per-agent threshold adjustments (future — dashboard could show adapted vs base thresholds)

---

## Section 1: TraitAdaptiveThresholds — Per-Agent Threshold Calculator

**File:** `src/probos/cognitive/circuit_breaker.py` (EDIT — add new dataclass + function above `CognitiveCircuitBreaker`)

Add after the `AgentBreakerState` dataclass and before the `CognitiveCircuitBreaker` class:

```python
@dataclass(frozen=True)
class TraitAdaptiveThresholds:
    """Per-agent circuit breaker thresholds adapted from personality traits.

    Each field is a multiplier applied to the corresponding base threshold
    in CircuitBreakerConfig. Values > 1.0 make the threshold more lenient
    (harder to trip), values < 1.0 make it more sensitive (easier to trip).

    The multipliers are computed deterministically from Big Five scores.
    Default multipliers (all 1.0) reproduce the original uniform behavior.
    """
    velocity_multiplier: float = 1.0       # Applied to velocity_threshold
    similarity_multiplier: float = 1.0     # Applied to similarity_threshold
    cooldown_multiplier: float = 1.0       # Applied to base_cooldown_seconds
    amber_sensitivity_multiplier: float = 1.0  # Applied to amber ratios (inverted — lower = more sensitive)


def compute_trait_thresholds(
    openness: float = 0.5,
    conscientiousness: float = 0.5,
    extraversion: float = 0.5,
    agreeableness: float = 0.5,
    neuroticism: float = 0.5,
) -> TraitAdaptiveThresholds:
    """Compute per-agent circuit breaker multipliers from Big Five scores.

    All trait values are 0.0-1.0. The function is pure (no side effects)
    and deterministic (same inputs always produce same outputs).

    Mapping rationale (each trait influences the parameter it most naturally
    maps to, with a bounded multiplier range to prevent extreme behavior):

    **Openness → velocity_multiplier**
    High openness agents explore more diverse topics, producing higher event
    velocity that is natural, not pathological. Range: 0.8-1.4.
    Formula: 1.0 + (openness - 0.5) * 0.8

    **Neuroticism → similarity_multiplier (inverted)**
    High neuroticism agents are more prone to anxiety-driven rumination.
    Lower similarity threshold = trip sooner on repetitive content.
    Range: 0.8-1.2 (inverted: high N → lower multiplier → lower effective threshold).
    Formula: 1.0 - (neuroticism - 0.5) * 0.4

    **Conscientiousness → cooldown_multiplier**
    High conscientiousness agents take recovery seriously and are more likely
    to genuinely recover during cooldown. Shorter cooldowns are sufficient.
    Low conscientiousness agents need longer cooldowns to break the pattern.
    Range: 0.7-1.3 (inverted: high C → lower multiplier → shorter cooldown).
    Formula: 1.0 - (conscientiousness - 0.5) * 0.6

    **Extraversion → amber_sensitivity_multiplier**
    High extraversion agents naturally produce more frequent communications.
    The amber zone pre-warning should be less sensitive for them.
    Range: 0.8-1.4.
    Formula: 1.0 + (extraversion - 0.5) * 0.8

    Agreeableness has no direct circuit breaker mapping — it affects
    social interaction patterns (Ward Room routing), not cognitive loops.

    Parameters
    ----------
    openness, conscientiousness, extraversion, agreeableness, neuroticism : float
        Big Five personality scores, each 0.0-1.0.

    Returns
    -------
    TraitAdaptiveThresholds
        Multipliers to apply to base CircuitBreakerConfig values.
    """
    # Clamp inputs to valid range (defensive)
    o = max(0.0, min(1.0, openness))
    c = max(0.0, min(1.0, conscientiousness))
    e = max(0.0, min(1.0, extraversion))
    n = max(0.0, min(1.0, neuroticism))

    velocity_multiplier = 1.0 + (o - 0.5) * 0.8       # 0.8 at O=0.0, 1.4 at O=1.0
    similarity_multiplier = 1.0 - (n - 0.5) * 0.4     # 1.2 at N=0.0, 0.8 at N=1.0
    cooldown_multiplier = 1.0 - (c - 0.5) * 0.6       # 1.3 at C=0.0, 0.7 at C=1.0
    amber_sensitivity_multiplier = 1.0 + (e - 0.5) * 0.8  # 0.8 at E=0.0, 1.4 at E=1.0

    return TraitAdaptiveThresholds(
        velocity_multiplier=round(velocity_multiplier, 4),
        similarity_multiplier=round(similarity_multiplier, 4),
        cooldown_multiplier=round(cooldown_multiplier, 4),
        amber_sensitivity_multiplier=round(amber_sensitivity_multiplier, 4),
    )
```

**Builder note:** `agreeableness` is accepted as a parameter (for API completeness and future use) but is unused in the current formulas. If the linter flags it, use `_agreeableness` prefix or add `# noqa: ARG001`.

---

## Section 2: CognitiveCircuitBreaker — Personality-Aware Threshold Application

**File:** `src/probos/cognitive/circuit_breaker.py` (EDIT — modify existing class)

### 2a: Add per-agent trait threshold storage

Add a new dict to `__init__` (after `self._trip_reasons`):

```python
        self._trait_thresholds: dict[str, TraitAdaptiveThresholds] = {}
```

### 2b: Add `set_agent_traits()` method

Add this public method after `_get_state()`:

```python
    def set_agent_traits(
        self,
        agent_id: str,
        openness: float = 0.5,
        conscientiousness: float = 0.5,
        extraversion: float = 0.5,
        agreeableness: float = 0.5,
        neuroticism: float = 0.5,
    ) -> None:
        """Register personality-based threshold multipliers for an agent.

        Call this once at agent initialization (or when personality evolves).
        If never called for an agent, default multipliers (all 1.0) apply —
        preserving the original uniform behavior.
        """
        self._trait_thresholds[agent_id] = compute_trait_thresholds(
            openness=openness,
            conscientiousness=conscientiousness,
            extraversion=extraversion,
            agreeableness=agreeableness,
            neuroticism=neuroticism,
        )
        logger.debug(
            "AD-494: Set trait thresholds for %s: velocity=%.2f, similarity=%.2f, "
            "cooldown=%.2f, amber=%.2f",
            agent_id,
            self._trait_thresholds[agent_id].velocity_multiplier,
            self._trait_thresholds[agent_id].similarity_multiplier,
            self._trait_thresholds[agent_id].cooldown_multiplier,
            self._trait_thresholds[agent_id].amber_sensitivity_multiplier,
        )
```

### 2c: Add `has_agent_traits()` public query

Add this public method after `set_agent_traits()`:

```python
    def has_agent_traits(self, agent_id: str) -> bool:
        """Return True if personality-based trait thresholds are registered for this agent."""
        return agent_id in self._trait_thresholds
```

### 2d: Add `_effective_thresholds()` helper

Add this private method after `has_agent_traits()`:

```python
    def _effective_thresholds(self, agent_id: str) -> dict[str, float]:
        """Return effective thresholds for an agent, applying trait multipliers.

        If the agent has no registered traits, returns the base thresholds
        unchanged (backward-compatible).
        """
        traits = self._trait_thresholds.get(agent_id)
        if traits is None:
            return {
                "velocity_threshold": self._velocity_threshold,
                "similarity_threshold": self._similarity_threshold,
                "base_cooldown": self._base_cooldown,
                "amber_similarity_ratio": self._amber_similarity_ratio,
                "amber_velocity_ratio": self._amber_velocity_ratio,
            }
        return {
            "velocity_threshold": max(2, round(self._velocity_threshold * traits.velocity_multiplier)),
            "similarity_threshold": max(0.3, min(0.95, self._similarity_threshold * traits.similarity_multiplier)),
            "base_cooldown": max(120.0, self._base_cooldown * traits.cooldown_multiplier),
            "amber_similarity_ratio": max(0.1, min(0.8, self._amber_similarity_ratio * traits.amber_sensitivity_multiplier)),
            "amber_velocity_ratio": max(0.3, min(0.95, self._amber_velocity_ratio * traits.amber_sensitivity_multiplier)),
        }
```

**Builder note on clamping:** The `max`/`min` bounds prevent degenerate thresholds:
- `velocity_threshold` minimum 2 (below 2, normal conversation triggers trips)
- `similarity_threshold` range 0.3-0.95 (below 0.3 trips on unrelated content; above 0.95 never trips)
- `base_cooldown` minimum 120s (2 minutes — below this, cooldown is meaningless)
- `amber_similarity_ratio` range 0.1-0.8 (prevents amber from being permanently on or permanently off)
- `amber_velocity_ratio` range 0.3-0.95 (same rationale)

**Follow-up note:** If `_effective_thresholds()` becomes a hot path (profiling shows repeated calls per think cycle), cache the computed dict on `AgentBreakerState` and invalidate in `set_agent_traits()`. Not needed now — the computation is trivial arithmetic.

### 2e: Modify `_compute_signals()` to use effective thresholds

Replace the current `_compute_signals()` method body. The change is to use `_effective_thresholds(agent_id)` instead of `self._velocity_threshold` and `self._similarity_threshold` directly.

The method signature stays the same: `def _compute_signals(self, agent_id: str) -> dict:`

Replace the body with:

```python
    def _compute_signals(self, agent_id: str) -> dict:
        """Analyze recent events and return signal strengths.

        AD-494: Uses per-agent effective thresholds (personality-adapted)
        instead of uniform base thresholds.

        Returns dict with:
            velocity_count: int — events in window
            velocity_ratio: float — fraction of velocity threshold
            similarity_ratio: float — fraction of similar pairs (0.0-1.0)
            velocity_fired: bool — velocity threshold exceeded
            similarity_fired: bool — similarity threshold exceeded
            reason: str — human-readable trip reason
        """
        state = self._get_state(agent_id)
        now = time.monotonic()

        # AD-494: Per-agent effective thresholds
        eff = self._effective_thresholds(agent_id)
        eff_velocity = eff["velocity_threshold"]
        eff_similarity = eff["similarity_threshold"]

        velocity_fired = False
        similarity_fired = False
        reason = ""

        # --- Signal 1: Velocity (event burst) ---
        window_start = now - self._velocity_window
        recent = [e for e in state.events if e.timestamp >= window_start]
        # AD-576: Exclude infrastructure-correlated events from cognitive signal computation
        recent_cognitive = [e for e in recent if not e.infrastructure_degraded]
        velocity_count = len(recent_cognitive)
        velocity_ratio = velocity_count / eff_velocity if eff_velocity > 0 else 0.0

        if velocity_count >= eff_velocity:
            velocity_fired = True
            reason = f"velocity ({velocity_count} events in {self._velocity_window:.0f}s)"

        # --- Signal 2: Similarity (content rumination) ---
        similarity_ratio = 0.0
        if len(recent_cognitive) >= self._similarity_min_events:
            fingerprints = [e.content_fingerprint for e in recent_cognitive if e.content_fingerprint]
            if len(fingerprints) >= self._similarity_min_events:
                similar_pairs = 0
                total_pairs = 0
                for j in range(len(fingerprints)):
                    for k in range(j + 1, len(fingerprints)):
                        total_pairs += 1
                        sim = jaccard_similarity(fingerprints[j], fingerprints[k])
                        if sim >= eff_similarity:
                            similar_pairs += 1
                if total_pairs > 0:
                    similarity_ratio = similar_pairs / total_pairs
                    if similarity_ratio >= 0.5:
                        similarity_fired = True
                        if velocity_fired:
                            reason += f" + rumination ({similar_pairs}/{total_pairs} pairs)"
                        else:
                            reason = f"rumination ({similar_pairs}/{total_pairs} pairs above {eff_similarity} threshold)"

        signals = {
            "velocity_count": velocity_count,
            "velocity_ratio": velocity_ratio,
            "similarity_ratio": similarity_ratio,
            "velocity_fired": velocity_fired,
            "similarity_fired": similarity_fired,
            "reason": reason,
        }

        # Cache signals on state for get_status() access
        state.last_signals = signals
        return signals
```

### 2f: Modify `_update_zone()` to use effective thresholds

In the `_update_zone()` method, the amber signal detection uses `self._amber_similarity_ratio` and `self._amber_velocity_ratio`. Change these to use the effective thresholds.

Replace these lines:

```python
            amber_signals = (
                signals.get("similarity_ratio", 0.0) > self._amber_similarity_ratio
                or signals.get("velocity_ratio", 0.0) > self._amber_velocity_ratio
            )
```

With:

```python
            # AD-494: Per-agent amber thresholds
            eff = self._effective_thresholds(agent_id)
            amber_signals = (
                signals.get("similarity_ratio", 0.0) > eff["amber_similarity_ratio"]
                or signals.get("velocity_ratio", 0.0) > eff["amber_velocity_ratio"]
            )
```

### 2g: Modify `_trip()` to use effective cooldown

In the `_trip()` method, the cooldown calculation uses `self._base_cooldown`. Change to use the effective base cooldown.

Replace:

```python
        # Escalating cooldown: base × 2^(trip_count - 1), capped
        cooldown = min(
            self._base_cooldown * (2 ** (state.trip_count - 1)),
            self._max_cooldown,
        )
```

With:

```python
        # AD-494: Per-agent base cooldown from trait adaptation
        eff_base_cooldown = self._effective_thresholds(agent_id)["base_cooldown"]
        # Escalating cooldown: base × 2^(trip_count - 1), capped
        cooldown = min(
            eff_base_cooldown * (2 ** (state.trip_count - 1)),
            self._max_cooldown,
        )
```

### 2h: Add trait info to `get_status()`

In the `get_status()` method, add the trait thresholds to the returned dict for API/diagnostics visibility. Add these entries at the end of the returned dict (before the closing `}`):

```python
            # AD-494: Trait-adaptive thresholds
            "trait_adapted": self.has_agent_traits(agent_id),
            "effective_velocity_threshold": self._effective_thresholds(agent_id)["velocity_threshold"],
            "effective_similarity_threshold": self._effective_thresholds(agent_id)["similarity_threshold"],
```

### 2i: Modify `reset_agent()` to clear trait thresholds

In `reset_agent()`, add after the `self._trip_reasons.pop(agent_id, None)` line:

```python
        self._trait_thresholds.pop(agent_id, None)
```

### 2j: Modify `reset_all()` to clear trait thresholds

In `reset_all()`, add after `self._trip_reasons.clear()`:

```python
        self._trait_thresholds.clear()
```

---

## Section 3: Wire Personality into Circuit Breaker at Agent Initialization

**File:** `src/probos/proactive.py` (EDIT)

The circuit breaker needs to receive personality data for each agent. The cleanest integration point is when the proactive loop first encounters an agent in its think cycle. The loop already has access to the runtime (which has the agent registry), and from the agent we can load its seed personality.

### 3a: Add trait registration method

Add this method to `ProactiveCognitiveLoop` (after the `set_config` method):

```python
    def _ensure_agent_traits_registered(self, agent: Any) -> None:
        """AD-494: Register personality traits for an agent's circuit breaker thresholds.

        Called lazily on first proactive think for each agent. Loads personality
        from seed profile YAML. If no personality data exists, the circuit breaker
        uses default multipliers (all 1.0) — backward-compatible.

        Traits are registered once and cached in the circuit breaker. If personality
        evolves (dream consolidation), the caller can re-register.
        """
        # Skip if already registered
        if self._circuit_breaker.has_agent_traits(agent.id):
            return

        try:
            from probos.crew_profile import load_seed_profile, PersonalityTraits
            seed = load_seed_profile(agent.agent_type)
            personality_data = seed.get("personality", {})
            if personality_data:
                traits = PersonalityTraits.from_dict(personality_data)
                self._circuit_breaker.set_agent_traits(
                    agent.id,
                    openness=traits.openness,
                    conscientiousness=traits.conscientiousness,
                    extraversion=traits.extraversion,
                    agreeableness=traits.agreeableness,
                    neuroticism=traits.neuroticism,
                )
        except Exception:
            # Log-and-degrade: trait registration failure must never block thinking
            logger.debug(
                "AD-494: Failed to load personality traits for %s",
                agent.agent_type, exc_info=True,
            )
```

**Builder note:** The `has_agent_traits()` public method (Section 2c) is used here instead of reaching into `_trait_thresholds` directly. This keeps `ProactiveCognitiveLoop` decoupled from the circuit breaker's internal storage.

### 3b: Call trait registration in the think loop

In the proactive think loop, add a call to `_ensure_agent_traits_registered()` just before the existing circuit breaker gate check. Find the comment:

```python
            # AD-488: Circuit breaker gate — skip agents in cognitive cooldown
            if not self._circuit_breaker.should_allow_think(agent.id):
```

Add immediately before it:

```python
            # AD-494: Ensure agent personality traits are registered for adaptive thresholds
            self._ensure_agent_traits_registered(agent)
```

---

## Section 4: TraitAdaptiveConfig — Config Extension

**File:** `src/probos/config.py` (EDIT)

Add a new config section for trait-adaptive control. Place after `CircuitBreakerConfig` (find the `CircuitBreakerConfig` class, add after it):

```python
class TraitAdaptiveConfig(BaseModel):
    """AD-494: Trait-adaptive circuit breaker — personality-aware thresholds."""
    enabled: bool = True
```

Add `trait_adaptive: TraitAdaptiveConfig = TraitAdaptiveConfig()` to the `SystemConfig` class, after the `circuit_breaker` field.

**File:** `src/probos/proactive.py` (EDIT)

Add `self._trait_adaptive_enabled: bool = True` to `ProactiveCognitiveLoop.__init__()`.

Modify `set_config()` signature to accept the trait config:

```python
    def set_config(self, config: ProactiveCognitiveConfig, cb_config: Any = None, trait_config: Any = None) -> None:
        """Store ProactiveCognitiveConfig for trust signal weights (AD-414)."""
        self._config = config
        if trait_config is not None:
            self._trait_adaptive_enabled = getattr(trait_config, 'enabled', True)
        if cb_config:
            from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
            self._circuit_breaker = CognitiveCircuitBreaker(config=cb_config)
```

Then `_ensure_agent_traits_registered()` checks `self._trait_adaptive_enabled`:

```python
    def _ensure_agent_traits_registered(self, agent: Any) -> None:
        """AD-494: Register personality traits for an agent's circuit breaker thresholds."""
        if not self._trait_adaptive_enabled:
            return
        # ... rest of method
```

**File:** `src/probos/startup/finalize.py` (EDIT)

Update the existing `set_config` call (find `proactive_loop.set_config(config.proactive_cognitive, cb_config=config.circuit_breaker)`) to add `trait_config`:

```python
        proactive_loop.set_config(
            config.proactive_cognitive,
            cb_config=config.circuit_breaker,
            trait_config=config.trait_adaptive,
        )
```

---

## Section 5: Tests

**File:** `tests/test_ad494_trait_adaptive_circuit_breaker.py` (NEW)

### Test infrastructure

Import:
```python
from probos.cognitive.circuit_breaker import (
    CognitiveCircuitBreaker,
    TraitAdaptiveThresholds,
    compute_trait_thresholds,
    BreakerState,
    CognitiveZone,
)
```

Helper: create a `_make_breaker()` factory that returns a `CognitiveCircuitBreaker` with short test-friendly parameters (velocity_threshold=4, velocity_window_seconds=60.0, similarity_threshold=0.6, similarity_min_events=3, base_cooldown_seconds=60.0, max_cooldown_seconds=300.0).

Helper: `_record_similar_events(breaker, agent_id, n, content="the same repeated thought about systems")` — records `n` events with the same content string to trigger similarity detection.

Helper: `_record_diverse_events(breaker, agent_id, n)` — records `n` events each with unique content (e.g., `f"unique thought number {i} about topic {i}"`) to produce velocity without similarity.

### Test categories (28 tests):

**compute_trait_thresholds — pure function (8 tests):**

1. `test_default_traits_produce_unit_multipliers` — all traits at 0.5 → all multipliers 1.0
2. `test_high_openness_increases_velocity_multiplier` — O=1.0 → velocity_multiplier > 1.0 (expect 1.4)
3. `test_low_openness_decreases_velocity_multiplier` — O=0.0 → velocity_multiplier < 1.0 (expect 0.6)
4. `test_high_neuroticism_decreases_similarity_multiplier` — N=1.0 → similarity_multiplier < 1.0 (expect 0.8)
5. `test_low_neuroticism_increases_similarity_multiplier` — N=0.0 → similarity_multiplier > 1.0 (expect 1.2)
6. `test_high_conscientiousness_decreases_cooldown_multiplier` — C=1.0 → cooldown_multiplier < 1.0 (expect 0.7)
7. `test_high_extraversion_increases_amber_multiplier` — E=1.0 → amber_sensitivity_multiplier > 1.0 (expect 1.4)
8. `test_clamped_inputs` — values outside 0.0-1.0 are clamped (e.g., openness=2.0 treated as 1.0, neuroticism=-1.0 treated as 0.0)

**TraitAdaptiveThresholds dataclass (2 tests):**

9. `test_frozen_dataclass` — instance is immutable (assigning to a field raises `FrozenInstanceError`)
10. `test_default_values` — default TraitAdaptiveThresholds() has all multipliers = 1.0

**set_agent_traits + _effective_thresholds (6 tests):**

11. `test_no_traits_returns_base_thresholds` — agent without registered traits gets base values
12. `test_set_traits_modifies_effective_velocity` — register high openness (0.9) → effective velocity_threshold > base
13. `test_set_traits_modifies_effective_similarity` — register high neuroticism (0.8) → effective similarity_threshold < base
14. `test_set_traits_modifies_effective_cooldown` — register high conscientiousness (0.9) → effective base_cooldown < base
15. `test_effective_thresholds_clamped` — extreme personality (all 0.0 or all 1.0) stays within bounds (velocity >= 2, similarity in 0.3-0.95, cooldown >= 120)
16. `test_set_traits_idempotent` — calling `set_agent_traits` twice with same values produces same effective thresholds

**Behavioral integration — trip behavior changes with personality (6 tests):**

17. `test_high_openness_agent_needs_more_events_to_trip` — agent with O=0.9 needs more events to velocity-trip than default agent
18. `test_high_neuroticism_agent_trips_on_lower_similarity` — agent with N=0.9 trips on lower similarity content overlap than default agent
19. `test_high_conscientiousness_agent_gets_shorter_cooldown` — after trip, agent with C=0.9 has shorter cooldown than default
20. `test_high_extraversion_agent_less_amber_sensitive` — agent with E=0.9 stays green with amber-level signals that would turn a default agent amber
21. `test_default_personality_matches_uniform_behavior` — agent with all 0.5 traits behaves identically to agent without traits registered
22. `test_wesley_profile_more_tolerant` — using Wesley's actual seed values (O=0.9, C=0.7, E=0.4, A=0.5, N=0.2), verify effective velocity threshold is *higher than* the base velocity threshold and effective similarity threshold is *higher than* the base similarity threshold. Use relative comparisons (`assert eff_velocity > base_velocity`), not absolute value assertions — the test must not break if YAML seed values change.

**Reset and lifecycle (4 tests):**

23. `test_reset_agent_clears_traits` — after `reset_agent()`, `has_agent_traits(agent_id)` returns False
24. `test_reset_all_clears_all_traits` — `reset_all()` makes `has_agent_traits()` return False for all agents
25. `test_get_status_shows_trait_adapted` — `get_status()` includes `trait_adapted: True` after registration and `trait_adapted: False` before
26. `test_get_status_shows_effective_thresholds` — `get_status()` includes `effective_velocity_threshold` and `effective_similarity_threshold` reflecting personality adaptation

**Config integration (2 tests):**

27. `test_trait_adaptive_disabled_skips_registration` — when `_trait_adaptive_enabled` is False on `ProactiveCognitiveLoop`, `_ensure_agent_traits_registered()` does not register traits. Create a mock agent with `id` and `agent_type` attrs, call `_ensure_agent_traits_registered()`, verify `breaker.has_agent_traits(agent.id)` is False.
28. `test_trait_adaptive_enabled_registers_traits` — when enabled (default), `_ensure_agent_traits_registered()` loads seed profile and registers traits. Mock or stub `load_seed_profile` to return Wesley's personality data. Verify `breaker.has_agent_traits(agent.id)` is True.

**Builder note on test 27/28:** These tests require a `ProactiveCognitiveLoop` instance. Create one with `interval=999, cooldown=999` (values don't matter for these tests). For test 28, use `unittest.mock.patch("probos.crew_profile.load_seed_profile")` to mock the YAML loading — the function is imported locally inside `_ensure_agent_traits_registered()`, so it must be patched in the module where it's defined (`probos.crew_profile`), not where it's imported from.

---

## Engineering Principles Compliance

- **SOLID/S** — `compute_trait_thresholds()` is a pure function. `TraitAdaptiveThresholds` is a value object. No new responsibilities added to `CognitiveCircuitBreaker` — it already manages thresholds; this adds per-agent variation via the same interface.
- **SOLID/O** — The circuit breaker is open for extension (new trait mappings) without modifying its core trip/zone logic. Only the threshold *source* changes (uniform → per-agent lookup), not the *algorithm*.
- **SOLID/D** — Personality data is injected via `set_agent_traits()`, not fetched by the breaker itself. The breaker has no dependency on `CrewProfile`, `ProfileStore`, or YAML loading. Wiring is in `proactive.py`.
- **Fail Fast** — `_ensure_agent_traits_registered()` is log-and-degrade. If profile loading fails, uniform thresholds apply. Personality input values are clamped to 0.0-1.0. Effective thresholds are clamped to safe bounds.
- **Law of Demeter** — The circuit breaker does not reach into agent objects or profile stores. The proactive loop loads profiles and passes scalar values to `set_agent_traits()`. Trait presence is checked via the public `has_agent_traits()` method, not by reaching into `_trait_thresholds`.
- **DRY** — `_effective_thresholds()` is called in exactly four places (`_compute_signals`, `_update_zone`, `_trip`, `get_status`). The multiplier computation is in one place (`compute_trait_thresholds()`).

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   | AD-494 | Trait-Adaptive Circuit Breaker | Per-agent circuit breaker thresholds from Big Five personality. 28 tests. | CLOSED |
   ```

2. **docs/development/roadmap.md** — Update the AD-494 row status to Closed.

3. **DECISIONS.md** — Add entry:
   ```
   ## AD-494: Trait-Adaptive Circuit Breaker

   **Decision:** Circuit breaker thresholds adapt per-agent based on Big Five personality scores. Openness → velocity tolerance, Neuroticism → similarity sensitivity, Conscientiousness → cooldown duration, Extraversion → amber zone sensitivity. Pure deterministic multipliers, no ML.

   **Rationale:** Uniform thresholds penalize naturally curious agents (high O) and under-protect anxious agents (high N). The Navy analogy: a lookout's alertness threshold differs from a helmsman's. Same health protection, different calibration.

   **Alternative considered:** Dynamic threshold learning from runtime behavior patterns. Rejected for V1 — adds complexity and opacity. Personality-based adaptation is explainable, auditable, and deterministic. Dynamic adaptation can layer on top in a future AD.
   ```
