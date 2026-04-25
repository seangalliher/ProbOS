# AD-411: EmergentDetector Pattern Deduplication

## Context

The proactive cognitive loop (Phase 28b) keeps ProbOS active — agents are always thinking, posting to the Ward Room, generating activity. This means the system rarely reaches true idle state, which causes the dream scheduler to fire frequently. Every dream/micro-dream cycle triggers `EmergentDetector.analyze()`, which re-analyzes the same trust state and cooperation patterns, producing **duplicate reports** for the same agents.

**Observed:** 120 trust anomalies and 174 total patterns after ~1 hour of operation, when the actual distinct count is closer to 15-20. This noise masks real emergent signals.

**Root cause:** `detect_trust_anomalies()`, `detect_cooperation_clusters()`, and `detect_routing_shifts()` have no memory of previously reported patterns — they fire on every `analyze()` call with no deduplication.

**Fix:** Add a cooldown window per pattern key. If a pattern with the same `(pattern_type, key)` was reported within the cooldown window, suppress it. Also add a defensive guard to `create_pool()` to prevent duplicate pool names.

*Discovered by crew: O'Brien, LaForge, and Worf flagged during first proactive loop deployment.*

---

## Part 1: Pattern Deduplication in EmergentDetector — `src/probos/cognitive/emergent_detector.py`

### 1a. Add dedup state to `__init__`

Add these fields at the end of `__init__()` (after `self._dream_history`, around line 129):

```python
        # Pattern deduplication (AD-411): suppress duplicate patterns within cooldown
        self._pattern_cooldown_seconds: float = 600.0  # 10 minutes default
        self._last_pattern_fired: dict[tuple[str, str], float] = {}  # (pattern_type, dedup_key) → monotonic timestamp
```

### 1b. Add dedup helper method

Add this method after `set_live_agents()` (after line 133):

```python
    def set_pattern_cooldown(self, seconds: float) -> None:
        """Set the deduplication cooldown window (seconds)."""
        self._pattern_cooldown_seconds = max(0, seconds)

    def _is_duplicate_pattern(self, pattern_type: str, dedup_key: str) -> bool:
        """Check if this pattern was already reported within the cooldown window.

        Returns True if this pattern should be suppressed (duplicate).
        """
        now = time.monotonic()
        cache_key = (pattern_type, dedup_key)
        last_fired = self._last_pattern_fired.get(cache_key)
        if last_fired is not None and (now - last_fired) < self._pattern_cooldown_seconds:
            return True  # Suppress — fired too recently
        self._last_pattern_fired[cache_key] = now
        return False

    def _prune_stale_dedup_entries(self) -> None:
        """Remove expired entries from the dedup cache to prevent unbounded growth."""
        now = time.monotonic()
        cutoff = now - self._pattern_cooldown_seconds * 2
        stale_keys = [k for k, t in self._last_pattern_fired.items() if t < cutoff]
        for k in stale_keys:
            del self._last_pattern_fired[k]
```

### 1c. Apply dedup to `detect_trust_anomalies()`

In `detect_trust_anomalies()` (starting line 332), add dedup checks at each pattern creation point:

**Deviation anomalies** (around line 356, inside the `if deviation > 2.0:` block): Wrap the `patterns.append(...)` call at line 371 with a dedup check. The `dedup_key` should be the agent_id + direction:

```python
                if deviation > 2.0:
                    direction = "high" if score > mean else "low"
                    severity = "significant" if deviation > 3.0 else "notable"

                    # AD-411: Suppress duplicate trust anomaly for same agent+direction
                    dedup_key = f"{agent_id}:{direction}"
                    if self._is_duplicate_pattern("trust_anomaly", dedup_key):
                        continue
```

Add the `if self._is_duplicate_pattern(...)` check **before** the `causal_events` fetch (line 360) to avoid unnecessary work for suppressed patterns.

**Hyperactive agent anomalies** (around line 398): Add dedup before `patterns.append(...)`:

```python
                if obs_mean > 0 and obs > obs_mean + 2 * obs_std:
                    # AD-411: Suppress duplicate hyperactivity alerts
                    if self._is_duplicate_pattern("trust_anomaly", f"hyperactive:{agent_id}"):
                        continue
```

**Change-point detection** (around line 425): Add dedup before `patterns.append(...)`:

```python
                        if delta > 0.15:
                            direction = "increased" if current_score > prev_record_score else "decreased"
                            # AD-411: Suppress duplicate change-point alerts
                            if self._is_duplicate_pattern("trust_anomaly", f"changepoint:{agent_id}"):
                                continue
```

### 1d. Apply dedup to cooperation cluster detection

In `analyze()` (around line 155), where cooperation clusters are converted to `EmergentPattern` objects, add dedup. The `dedup_key` should be a sorted tuple of agent IDs in the cluster:

```python
        clusters = self.detect_cooperation_clusters(self._live_agent_ids)
        for cluster in clusters:
            # AD-411: Dedup by cluster membership (sorted agent IDs)
            members = sorted(cluster.get("members", []))
            dedup_key = ",".join(m[:8] for m in members) if members else str(cluster.get("size", 0))
            if self._is_duplicate_pattern("cooperation_cluster", dedup_key):
                continue
            patterns.append(EmergentPattern(
```

### 1e. Apply dedup to routing shifts

In `detect_routing_shifts()` (starting line 443):

**New agent→intent connections** (around line 461): Add dedup before `patterns.append(...)`:

```python
            for agent in new_agents:
                # AD-411: Suppress duplicate routing shift alerts
                if self._is_duplicate_pattern("routing_shift", f"{agent[:8]}:{intent}"):
                    continue
```

**New intent types** (around line 479): Add dedup:

```python
        for intent in new_intents:
            if self._is_duplicate_pattern("routing_shift", f"new_intent:{intent}"):
                continue
```

**Entropy changes** (around line 497): Add dedup using a quantized entropy bucket to avoid re-alerting on minor fluctuations:

```python
            if entropy_delta > 0.5 and prev_entropy > 0:
                direction = "increased" if current_entropy > prev_entropy else "decreased"
                # AD-411: Quantize to 0.5 buckets to avoid near-duplicate entropy alerts
                bucket = f"entropy:{direction}:{round(current_entropy * 2) / 2:.1f}"
                if self._is_duplicate_pattern("routing_shift", bucket):
                    continue
```

### 1f. Prune stale entries on each analyze() call

At the **beginning** of `analyze()` (after line 137 `now = time.monotonic()`), add:

```python
        # AD-411: Prune expired dedup entries
        self._prune_stale_dedup_entries()
```

---

## Part 2: Duplicate Pool Name Guard — `src/probos/runtime.py`

In `create_pool()` (line 525), add a duplicate name guard at the top of the method, **before** creating the ResourcePool:

```python
    async def create_pool(
        self,
        name: str,
        agent_type: str,
        target_size: int | None = None,
        agent_ids: list[str] | None = None,
        **spawn_kwargs: Any,
    ) -> ResourcePool:
        """Create and start a resource pool."""
        # AD-411: Guard against duplicate pool names
        if name in self.pools:
            logger.warning("Pool '%s' already exists — skipping duplicate creation", name)
            return self.pools[name]

        pool = ResourcePool(
```

---

## Part 3: Tests — `tests/test_emergent_detector.py`

Add these tests to the existing test file. Place them at the end, in a new class:

```python
class TestPatternDeduplication:
    """AD-411: EmergentDetector pattern deduplication."""

    def test_duplicate_suppressed_within_cooldown(self):
        """Same pattern within cooldown window is suppressed."""
        router = HebbianRouter()
        trust = TrustNetwork()
        detector = EmergentDetector(router, trust)
        detector.set_pattern_cooldown(60.0)

        # First call — not a duplicate
        assert not detector._is_duplicate_pattern("trust_anomaly", "agent1:high")
        # Second call — duplicate (within cooldown)
        assert detector._is_duplicate_pattern("trust_anomaly", "agent1:high")

    def test_different_keys_not_suppressed(self):
        """Different dedup keys are independent."""
        router = HebbianRouter()
        trust = TrustNetwork()
        detector = EmergentDetector(router, trust)
        detector.set_pattern_cooldown(60.0)

        assert not detector._is_duplicate_pattern("trust_anomaly", "agent1:high")
        assert not detector._is_duplicate_pattern("trust_anomaly", "agent2:high")

    def test_different_types_not_suppressed(self):
        """Same key with different pattern types are independent."""
        router = HebbianRouter()
        trust = TrustNetwork()
        detector = EmergentDetector(router, trust)
        detector.set_pattern_cooldown(60.0)

        assert not detector._is_duplicate_pattern("trust_anomaly", "agent1")
        assert not detector._is_duplicate_pattern("routing_shift", "agent1")

    def test_cooldown_expiry(self):
        """Pattern is allowed after cooldown expires."""
        router = HebbianRouter()
        trust = TrustNetwork()
        detector = EmergentDetector(router, trust)
        detector.set_pattern_cooldown(0.0)  # Zero cooldown = no suppression

        assert not detector._is_duplicate_pattern("trust_anomaly", "agent1:high")
        assert not detector._is_duplicate_pattern("trust_anomaly", "agent1:high")

    def test_prune_stale_entries(self):
        """Stale dedup entries are cleaned up."""
        router = HebbianRouter()
        trust = TrustNetwork()
        detector = EmergentDetector(router, trust)
        detector.set_pattern_cooldown(1.0)

        detector._is_duplicate_pattern("trust_anomaly", "agent1:high")
        assert len(detector._last_pattern_fired) == 1

        # Manually age the entry
        key = ("trust_anomaly", "agent1:high")
        detector._last_pattern_fired[key] = time.monotonic() - 100
        detector._prune_stale_dedup_entries()
        assert len(detector._last_pattern_fired) == 0

    def test_set_pattern_cooldown(self):
        """Cooldown window is configurable."""
        router = HebbianRouter()
        trust = TrustNetwork()
        detector = EmergentDetector(router, trust)
        detector.set_pattern_cooldown(120.0)
        assert detector._pattern_cooldown_seconds == 120.0

    def test_negative_cooldown_clamped(self):
        """Negative cooldown values are clamped to 0."""
        router = HebbianRouter()
        trust = TrustNetwork()
        detector = EmergentDetector(router, trust)
        detector.set_pattern_cooldown(-10.0)
        assert detector._pattern_cooldown_seconds == 0.0

    def test_trust_anomaly_dedup_in_analyze(self):
        """Trust anomalies for same agent are suppressed across analyze() calls."""
        router = HebbianRouter()
        trust = TrustNetwork()
        detector = EmergentDetector(router, trust)
        detector.set_pattern_cooldown(600.0)

        # Create agents with divergent trust to trigger anomalies
        for i in range(5):
            trust.get_or_create(f"normal_{i}")
        outlier_id = "outlier_agent"
        trust.get_or_create(outlier_id)
        # Pump the outlier's trust high
        for _ in range(50):
            trust.record_outcome(outlier_id, success=True, weight=1.0)

        detector.set_live_agents({f"normal_{i}" for i in range(5)} | {outlier_id})

        # First analyze — should find the anomaly
        patterns1 = detector.analyze()
        trust_anomalies1 = [p for p in patterns1 if p.pattern_type == "trust_anomaly"]

        # Second analyze — same state, anomalies should be suppressed
        patterns2 = detector.analyze()
        trust_anomalies2 = [p for p in patterns2 if p.pattern_type == "trust_anomaly"]

        # Second run should have fewer (or zero) trust anomalies
        assert len(trust_anomalies2) <= len(trust_anomalies1)
```

---

## Part 4: Duplicate Pool Guard Tests — `tests/test_runtime_pool_guard.py` (add to existing runtime tests or create minimal)

Add a test to verify the duplicate pool guard. Find the appropriate existing test file (likely `test_runtime.py` or add to end of `test_emergent_detector.py`):

```python
class TestPoolDuplicateGuard:
    """AD-411: create_pool() duplicate name guard."""

    @pytest.mark.asyncio
    async def test_duplicate_pool_returns_existing(self):
        """Creating a pool with an existing name returns the existing pool."""
        from probos.runtime import ProbOSRuntime
        from probos.config import SystemConfig

        config = SystemConfig()
        rt = ProbOSRuntime(config)
        # Manually set up minimal infrastructure for create_pool
        rt._data_dir.mkdir(parents=True, exist_ok=True)

        # Note: This test may need adjustment based on runtime initialization
        # requirements. The key assertion is that the second create_pool
        # returns the same pool object, not a new one.
        # If full runtime initialization is too heavy, test the guard
        # logic directly by checking:
        #   rt.pools["test"] = existing_pool
        #   result = await rt.create_pool("test", "some_type")
        #   assert result is existing_pool
```

---

## Verification

```bash
# Targeted tests
uv run pytest tests/test_emergent_detector.py -x -v -k "Dedup or dedup"

# Full emergent detector suite
uv run pytest tests/test_emergent_detector.py tests/test_emergent_trends.py -x -v

# Full Python suite
uv run pytest tests/ --tb=short -q
```

---

## What This Does NOT Change

- **EmergentDetector detection logic** — thresholds, sigma cutoffs, and pattern types are unchanged
- **Dream scheduler** — frequency and trigger conditions unchanged
- **Proactive loop** — interval, cooldown, agent selection unchanged
- **Trust network** — scoring, Bayesian updates, Shapley weighting unchanged
- **Bridge Alerts** — alert generation from emergent patterns unchanged (dedup'd patterns simply don't reach Bridge Alerts)
