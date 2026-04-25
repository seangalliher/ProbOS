# BF-036: EmergentDetector Trust Anomaly Flooding

## Problem

After BF-034's 5-minute cold-start suppression expires, the EmergentDetector's sigma-deviation trust anomaly check fires a burst of 10-30+ false positives. Root cause: during early-session transition, most agents are still at trust 0.5, a few have moved to 0.55-0.6 from task successes. Population std is tiny (~0.02), so even small absolute differences register as 4-5 sigma outliers. Each agent has a unique dedup key (`agent_id:direction`), so dedup doesn't help. Agents see these alerts and enter confabulation cascades — fabricating detailed crisis narratives about nonexistent "trust substrate corruption."

## Root Cause

In `src/probos/cognitive/emergent_detector.py`, `detect_trust_anomalies()` line 400:

```python
if std < 0.001:
    # All trust scores nearly identical — skip deviation check
    pass
```

This guard only catches the exact-equality case. The problematic range is `0.001 < std < ~0.05` — where sigma analysis is statistically meaningless because the absolute spread is negligible but relative deviations are enormous.

Example: population mean=0.51, std=0.02. An agent at trust 0.6 (one successful task) is `(0.6-0.51)/0.02 = 4.5 sigma` — flagged as "significant." But the absolute deviation of 0.09 is completely normal early-session variation.

## Fix

Three changes to `detect_trust_anomalies()` in `src/probos/cognitive/emergent_detector.py`:

### Change 1: Raise the std floor guard

Replace the `std < 0.001` check with a minimum std threshold that reflects meaningful population divergence. Trust scores range [0, 1], so std < 0.05 means the entire population is within ~5% of each other — not enough spread for sigma analysis to be informative.

```python
if std < 0.05:
    # Population trust spread too narrow for sigma analysis to be meaningful.
    # With 55 agents and normal early-session variance, small absolute
    # differences produce enormous sigma values. Skip until the population
    # has genuinely diverged.
    pass
```

### Change 2: Add minimum observations guard

Sigma deviation is unreliable when agents haven't accumulated enough history. Add a check that skips firing for agents with very few observations (total alpha + beta close to the prior of 4.0). This prevents flagging agents whose trust moved from 0.5 to 0.6 after a single task success.

Inside the sigma loop (the `for agent_id, record in raw.items():` block), after computing `score` and `deviation`, add:

```python
# Skip agents with too few observations — trust hasn't stabilized
total_observations = record["alpha"] + record["beta"]
if total_observations < 8.0:  # prior is 4.0, so <8 means <4 actual observations
    continue
```

Place this check **before** the `if deviation > 2.0:` condition.

### Change 3: Add minimum absolute deviation guard

Even with sufficient observations and adequate std, a very small absolute deviation from the mean isn't worth alerting on. An agent 3 sigma away but only 0.05 absolute isn't meaningfully different.

Inside the sigma loop, add alongside the observation guard:

```python
# Skip if absolute deviation is negligible regardless of sigma
abs_deviation = abs(score - mean)
if abs_deviation < 0.10:
    continue
```

Place this check **before** the `if deviation > 2.0:` condition, after the observations guard.

### Final structure of the sigma deviation block

After all three changes, the sigma block (currently lines 400-445) should read:

```python
if std < 0.05:
    # Population trust spread too narrow for sigma analysis to be meaningful
    pass
else:
    # Flag agents > 2 std from mean
    for agent_id, record in raw.items():
        score = record["alpha"] / (record["alpha"] + record["beta"])

        # Skip agents with too few observations — trust hasn't stabilized
        total_observations = record["alpha"] + record["beta"]
        if total_observations < 8.0:  # prior is 4.0, so <8 means <4 actual observations
            continue

        # Skip if absolute deviation is negligible regardless of sigma
        abs_deviation = abs(score - mean)
        if abs_deviation < 0.10:
            continue

        deviation = abs_deviation / std

        if deviation > 2.0:
            direction = "high" if score > mean else "low"
            severity = "significant" if deviation > 3.0 else "notable"

            # AD-411: Suppress duplicate trust anomaly for same agent+direction
            dedup_key = f"{agent_id}:{direction}"
            if self._is_duplicate_pattern("trust_anomaly", dedup_key):
                continue

            # Causal back-references (AD-295c)
            recent_events = self._trust.get_events_for_agent(agent_id, n=5)
            causal_events = [
                {
                    "intent_type": event.intent_type,
                    "success": event.success,
                    "weight": round(event.weight, 4),
                    "score_change": round(event.new_score - event.old_score, 4),
                    "episode_id": event.episode_id,
                }
                for event in recent_events
            ]
            patterns.append(EmergentPattern(
                pattern_type="trust_anomaly",
                description=f"Agent {agent_id[:8]} has {direction} trust ({score:.3f}) — {deviation:.1f}σ from mean ({mean:.3f})",
                confidence=min(1.0, deviation / 4.0),
                evidence={
                    "agent_id": agent_id,
                    "score": score,
                    "mean": mean,
                    "std": std,
                    "deviation_sigma": deviation,
                    "direction": direction,
                    "causal_events": causal_events,
                },
                timestamp=now,
                severity=severity,
            ))
```

Note: move the `deviation = abs_deviation / std` computation AFTER the guards so it's only calculated when needed.

---

## Tests

Add tests to `tests/test_emergent_detector.py` in a new `TestBF036TrustFloodingFix` class:

### Test 1: `test_narrow_std_suppresses_sigma_check`
Set up population of 10 agents with trust scores very close together (e.g., all at 0.50 except one at 0.55). Std will be ~0.015. Verify no trust anomalies fire (std < 0.05 guard).

### Test 2: `test_wide_std_allows_sigma_check`
Set up population where one agent has trust 0.9 and the rest 0.5. Std > 0.05. Verify the outlier IS flagged.

### Test 3: `test_low_observations_suppresses_anomaly`
Set up an agent with alpha=2.5, beta=2.0 (only 0.5 observations beyond prior, total=4.5 < 8.0). Even with high std (other agents divergent), this agent should NOT be flagged.

### Test 4: `test_sufficient_observations_allows_anomaly`
Set up an agent with alpha=6.0, beta=2.0 (total=8.0, >= threshold). With sufficient std, this agent should be flagged if deviation > 2 sigma.

### Test 5: `test_small_absolute_deviation_suppresses`
Set up population where std is just above 0.05 but the outlier agent is only 0.08 absolute from mean. Verify no anomaly fires (abs < 0.10 guard).

### Test 6: `test_large_absolute_deviation_fires`
Set up population where the outlier is 0.15 absolute from mean, with > 8 total observations and std > 0.05. Verify anomaly fires.

### Test 7: `test_cold_start_transition_no_flooding`
Simulate a cold-start scenario: 20 agents all start at alpha=2.0, beta=2.0, then a few get 1-3 successes (alpha incremented). Verify that `detect_trust_anomalies()` returns an empty list — the guards collectively prevent the post-suppression spike.

### Test structure

Use the existing test patterns in `test_emergent_detector.py`. The tests create a mock `TrustNetwork` whose `raw_scores()` returns controlled data. You'll need to set `record["alpha"]` and `record["beta"]` directly (not just `record["score"]`) since the fix now reads these fields.

Check existing tests (especially `TestTrustAnomalies` around line 250) for mock patterns. The existing mock `FakeTrustNetwork.raw_scores()` returns dicts with `alpha`, `beta`, `observations` keys.

---

## Verification

1. `uv run pytest tests/test_emergent_detector.py -v` — all existing + 7 new tests pass
2. `uv run pytest tests/test_bf034_cold_start.py -v` — existing cold-start tests pass (no regressions)
3. `uv run pytest` — full suite passes

---

## Files

| File | Action |
|------|--------|
| `src/probos/cognitive/emergent_detector.py` | **MODIFY** — Three guards in `detect_trust_anomalies()`: std floor 0.05, min observations 8.0, min absolute deviation 0.10 |
| `tests/test_emergent_detector.py` | **MODIFY** — 7 new tests in `TestBF036TrustFloodingFix` class |
