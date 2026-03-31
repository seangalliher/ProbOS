# BF-089: Emergent Detector Trust Anomaly False Positives

## Context

The emergent detector (`src/probos/cognitive/emergent_detector.py`) fires trust anomaly alerts during normal duty cycle completions. Crew independently reported (Forge + Reyes, confirmed across two observation periods) that seven trust anomaly alerts cluster around duty cycle boundaries — Hebbian weight adjustments during peer evaluation are flagged as pathological behavior. The detector evaluates each trust delta in isolation with no temporal smoothing, treating normal operational variance as anomalies.

## Problem

`detect_trust_anomalies()` (lines 381-520) has three sub-detectors that all operate on point-in-time snapshots with no temporal context:

1. **Sigma outlier** (line 423): Flags agents where `abs(score - mean) / std > 2.0`. No smoothing — a single duty cycle trust bump can trigger if it exceeds 2 sigma at that moment.
2. **Change-point** (line 501): Flags agents where `abs(current - previous) > 0.15`. Compares only to the immediately preceding snapshot. A normal duty cycle completion that bumps trust by 0.16 triggers an alert.
3. **No temporal buffer**: The `_is_duplicate_pattern()` dedup (10-minute cooldown, line 132) prevents *identical* patterns from repeating, but does NOT prevent the detector from firing 7 different agents' trust changes as 7 separate alerts in the same analysis pass.

Additionally, all detection thresholds are hardcoded with no configuration exposure.

## Requirements

### 1. Temporal Buffer for Trust Anomalies

Add a configurable temporal buffer that requires sustained deviation before alerting.

In `detect_trust_anomalies()`:
- Track per-agent anomaly observations in a new `_trust_anomaly_counts: dict[str, list[float]]` that records timestamps when an agent triggered the sigma or change-point detector.
- Only promote to an `EmergentPattern` if the agent has triggered **N times within a window** (default: 3 occurrences within 600 seconds / 10 minutes).
- Single occurrences are logged at DEBUG level but not emitted as patterns.
- Add a cleanup method `_prune_stale_anomaly_counts()` called at the start of `detect_trust_anomalies()` to remove entries older than the window.

### 2. Duty Cycle Correlation Awareness

Add logic to suppress trust anomaly alerts that correlate with duty cycle completions.

- Accept an optional `duty_completions: list[tuple[str, float]]` parameter in `analyze()` — list of `(agent_id, completion_timestamp)` pairs for duties completed since last analysis.
- In `detect_trust_anomalies()`, if an agent's trust change is detected AND that agent completed a duty within the last 120 seconds, downgrade the anomaly: skip it entirely for change-point detection; for sigma detection, only emit if the deviation exceeds 3.0 sigma (significant) rather than 2.0 (notable).
- The `DreamAdapter.on_post_dream()` caller should pass recent duty completions to `analyze()`. Wire this by adding a `get_recent_completions(since: float)` method call on the proactive loop or duty schedule tracker if available. If no duty data is available, pass an empty list — the detector degrades gracefully.

### 3. Adaptive Baselines for Sigma Detection

Replace the per-snapshot population mean/std with an exponential moving average.

- Add `_ema_trust_mean: float | None` and `_ema_trust_std: float | None` instance attributes, initialized to `None`.
- On each `detect_trust_anomalies()` call, compute the current population mean/std as today, but then update the EMAs:
  ```python
  alpha = 0.3  # Smoothing factor — configurable via constructor
  if self._ema_trust_mean is None:
      self._ema_trust_mean = current_mean
      self._ema_trust_std = current_std
  else:
      self._ema_trust_mean = alpha * current_mean + (1 - alpha) * self._ema_trust_mean
      self._ema_trust_std = alpha * current_std + (1 - alpha) * self._ema_trust_std
  ```
- Use `self._ema_trust_mean` and `self._ema_trust_std` for the sigma outlier detection instead of the raw per-snapshot values.
- This prevents a single noisy snapshot from defining what "normal" is.

### 4. Per-Analysis Batch Limiting

Limit trust anomaly alerts per analysis pass to prevent alert floods.

- Add `max_trust_anomalies_per_pass: int = 3` constructor parameter.
- After collecting all candidate anomalies, sort by confidence descending and keep only the top N.
- Log a summary line if anomalies were truncated: `"Trust anomaly detection: {total} candidates, reporting top {max}"`.

### 5. Configuration Exposure

Extract hardcoded thresholds to constructor parameters with sensible defaults:

```python
def __init__(
    self,
    hebbian_router,
    trust_network,
    episodic_memory=None,
    max_history: int = 100,
    trend_threshold: float = 0.005,
    # NEW parameters:
    trust_sigma_threshold: float = 2.0,
    trust_sigma_significant: float = 3.0,
    trust_change_threshold: float = 0.15,
    trust_min_std: float = 0.05,
    trust_min_observations: float = 8.0,
    trust_min_deviation: float = 0.10,
    trust_ema_alpha: float = 0.3,
    trust_anomaly_window: float = 600.0,
    trust_anomaly_min_count: int = 3,
    max_trust_anomalies_per_pass: int = 3,
    duty_correlation_window: float = 120.0,
):
```

Store all as `self._` prefixed attributes. Replace all hardcoded values in `detect_trust_anomalies()` with the corresponding attributes.

### 6. Update DreamAdapter Integration

In `dream_adapter.py`, update `on_post_dream()` and `on_post_micro_dream()` to pass duty completion data to `analyze()`:

- If `self._dream_scheduler` has access to duty completion timestamps (via the runtime or proactive loop), pass them.
- If not readily available, pass `duty_completions=[]` — do NOT add complex wiring. The temporal buffer (requirement 1) and adaptive baselines (requirement 3) are the primary fixes. Duty correlation (requirement 2) is a nice-to-have enhancement.

## Files to Modify

1. **`src/probos/cognitive/emergent_detector.py`** — Primary changes (requirements 1-5)
2. **`src/probos/dream_adapter.py`** — Pass duty_completions to analyze() (requirement 6)
3. **`tests/test_emergent_detector.py`** — New tests (see below)

## Tests Required

Add to `tests/test_emergent_detector.py`:

1. **`test_temporal_buffer_suppresses_single_occurrence`** — A single trust anomaly trigger does NOT produce an EmergentPattern (logged at DEBUG only).
2. **`test_temporal_buffer_promotes_sustained_anomaly`** — An agent triggering 3+ times within the window DOES produce an EmergentPattern.
3. **`test_temporal_buffer_window_expiry`** — Old anomaly counts expire after the window elapses.
4. **`test_adaptive_baseline_smooths_noise`** — EMA mean/std are updated across multiple analyze() calls and produce more stable thresholds than raw per-snapshot values.
5. **`test_batch_limiting`** — When >3 trust anomalies are detected, only top 3 by confidence are emitted.
6. **`test_duty_correlation_suppression`** — Trust change coinciding with a duty completion within 120s is suppressed for change-point detection.
7. **`test_duty_correlation_sigma_elevation`** — Trust sigma anomaly during duty cycle requires 3.0 sigma (significant) instead of 2.0 (notable) to be emitted.
8. **`test_configurable_thresholds`** — Constructor parameters override default thresholds and are used in detection.
9. **`test_cold_start_suppression_still_works`** — Existing BF-034 cold-start suppression is not broken by the new temporal buffer logic.
10. **`test_cooperation_clusters_unaffected`** — Cooperation cluster detection is unchanged by this fix (regression guard).

## Engineering Principles Compliance

- **Fail Fast**: New logging replaces silent suppression. Suppressed anomalies get `logger.debug()`, not silence.
- **SOLID (O)**: New parameters extend behavior without modifying the detect interface contract — `analyze()` gains an optional parameter with a default.
- **DRY**: Threshold values extracted to constructor once, not scattered.
- **Defense in Depth**: Temporal buffer + EMA + batch limiting + duty correlation = four independent noise reduction layers. Any single one reduces false positives; together they eliminate the reported pattern.

## What NOT to Change

- Do NOT modify cooperation cluster detection (`detect_cooperation_clusters()`). It is not part of the false positive pattern.
- Do NOT modify consolidation anomaly detection or routing shift detection.
- Do NOT change the `_pattern_cooldown_seconds` dedup mechanism — it serves a different purpose (cross-analysis dedup vs. within-analysis noise).
- Do NOT add `aiofiles` or any new dependencies.
- Do NOT modify BridgeAlert conversion logic in `bridge_alerts.py`.

## Verification

After implementation:
1. Run `python -m pytest tests/test_emergent_detector.py tests/test_emergent_trends.py -v` — all tests pass including the 10 new ones.
2. Run `python -m pytest tests/ -x -q --timeout=30` — full suite passes, no regressions.
