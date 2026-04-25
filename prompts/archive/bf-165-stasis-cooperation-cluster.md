# BF-165: Cooperation Cluster False Positives During Stasis

**Priority:** Medium
**Issue:** #TBD
**Connects to:** BF-126 (post-stasis cluster suppression — time-bounded), BF-124 (cluster calibration), AD-411 (dedup)
**Crew-identified by:** Chapel (14-day forensic investigation)

## Root Cause

`detect_cooperation_clusters()` in `emergent_detector.py:364` reads the Hebbian weight graph via `self._router.all_weights_typed()` and runs union-find for connected components above `_cluster_edge_threshold`. The problem: **Hebbian weights are persistent state, not activity indicators.** During stasis — zero cognitive activity, no agents running, no `record_interaction()` calls — the weights still exist in the graph. The detector runs on a timer (via `analyze()` called from dream_adapter and IntrospectAgent), finds the same static clusters, and fires alerts every cooldown expiry (1800s default).

BF-126 added `_suppress_clusters_until` (300s post-stasis window), but that's time-bounded — after 5 minutes, detection resumes against stale weights. The result: mechanically-timed cooperation cluster alerts during periods of zero cognitive activity, as Chapel's forensic investigation documented.

**The core error:** The detector conflates "what cooperated historically" (persistent weights) with "what is cooperating now" (active behavior). No mechanism checks whether any cognitive activity has occurred since the last detection pass.

## Fix

Add a cognitive activity gate to `detect_cooperation_clusters()`. Track when the Hebbian router last recorded an interaction. If no interactions have occurred within a configurable window, skip cluster detection entirely — the weights haven't changed, so any clusters found are stale reruns.

### Change 1: Activity tracking on `EmergentDetector`

In `src/probos/cognitive/emergent_detector.py`:

**Add to `__init__()` (after the BF-126 `_suppress_clusters_until` line at ~185):**

```python
# BF-165: Cognitive activity gate — suppress cluster detection when
# no Hebbian interactions have occurred within the activity window.
# Prevents false positives from stale weights during stasis.
self._last_activity_time: float = 0.0
self._cluster_activity_window: float = cluster_activity_window
```

**Add `cluster_activity_window` parameter to `__init__()` signature (after `cluster_cooldown_seconds`):**

```python
cluster_activity_window: float = 900.0,  # BF-165: 15 minutes
```

**Add public method (after `set_dreaming()`, ~line 218):**

```python
def record_activity(self) -> None:
    """Record that cognitive activity occurred (Hebbian interaction).

    BF-165: Called when the Hebbian router records an interaction,
    signaling that agents are actively processing — cooperation
    clusters found in this window reflect current behavior, not
    stale historical weights.
    """
    self._last_activity_time = time.monotonic()
```

**Add activity gate at top of `detect_cooperation_clusters()` (after the BF-126 check at line 373, before the AD-288 episode total guard):**

```python
# BF-165: Skip cluster detection if no cognitive activity within window.
# Hebbian weights are persistent — without recent interactions, any
# clusters found are stale reruns of historical cooperation patterns.
if self._cluster_activity_window > 0:
    since_activity = time.monotonic() - self._last_activity_time
    if since_activity > self._cluster_activity_window:
        return []
```

### Change 2: Wire activity signal from runtime

In `src/probos/runtime.py`, after the existing `hebbian_router.record_interaction()` call at line 1518-1522:

```python
# BF-165: Signal cognitive activity to emergent detector
if getattr(self, '_emergent_detector', None):
    self._emergent_detector.record_activity()
```

This is the single point where Hebbian weights change via intent processing. The detector already lives on `runtime._emergent_detector` (set from `DreamingResult` in `startup/results.py`).

### Change 3: Config field

In `src/probos/config.py`, add to `EmergentDetectorConfig` (after `cluster_cooldown_seconds`):

```python
cluster_activity_window: float = 900.0  # BF-165: seconds without Hebbian interaction before suppressing cluster detection (0 = disabled)
```

### Change 4: Pass config to constructor

In `src/probos/startup/dreaming.py`, add to the `EmergentDetector()` constructor call (after `cluster_cooldown_seconds`):

```python
cluster_activity_window=_edc.cluster_activity_window,
```

## Deliberate Exclusions

| Excluded | Why |
|----------|-----|
| Per-agent activity tracking within clusters | Adds computational overhead during normal operations for marginal benefit. A simple global activity gate is sufficient — if any agent is active, detection is valid. Lynx concurs. |
| Modifying HebbianRouter to track timestamps | HebbianRouter is a core consensus module. Adding timestamp state there is invasive. The activity signal flows outward from the call site in runtime.py — no HebbianRouter changes needed. |
| Extending BF-126 suppression window | BF-126's time-bounded approach is fundamentally wrong for this — stasis duration is unpredictable. Activity gating is duration-independent. |
| Trust anomaly gating | Trust anomalies use different data sources (trust scores, not Hebbian weights) and have their own suppression mechanisms (BF-034, BF-100). Not affected by this bug. |

## Engineering Principles Applied

- **SOLID (S):** `record_activity()` is a focused method — records activity timestamp, nothing else. Cluster detection checks it as a precondition, nothing else.
- **SOLID (O):** New `cluster_activity_window` parameter extends behavior without modifying existing suppression mechanisms (BF-126, AD-411 dedup, cooldown).
- **Fail Fast:** Activity window of 0 disables the gate entirely — backward compatible default behavior without code changes.
- **Law of Demeter:** Runtime calls `self._emergent_detector.record_activity()` — no reaching through internal state. Detector reads its own `_last_activity_time`.
- **DRY:** Reuses existing `time.monotonic()` pattern already established by BF-126 and BF-034 suppression.

## Test Specification

Create `tests/test_bf165_stasis_cluster.py` with the following tests:

### Class: `TestActivityGate` (4 tests)

1. **`test_no_activity_suppresses_clusters`** — Create EmergentDetector with mocked HebbianRouter that has strong weights. Call `detect_cooperation_clusters()` WITHOUT calling `record_activity()` first. Assert returns empty list.

2. **`test_recent_activity_allows_clusters`** — Same setup. Call `record_activity()`, then `detect_cooperation_clusters()`. Assert returns non-empty list (clusters detected normally).

3. **`test_activity_expires_after_window`** — Call `record_activity()`, then set `_last_activity_time` to `time.monotonic() - 1000` (past the 900s window). Call `detect_cooperation_clusters()`. Assert returns empty list.

4. **`test_activity_window_zero_disables_gate`** — Create EmergentDetector with `cluster_activity_window=0`. Do NOT call `record_activity()`. Call `detect_cooperation_clusters()`. Assert returns non-empty list (gate disabled, existing behavior preserved).

### Class: `TestConfigField` (2 tests)

5. **`test_cluster_activity_window_config_exists`** — Verify `cluster_activity_window` field exists on `EmergentDetectorConfig` with default value 900.0.

6. **`test_activity_window_passed_to_constructor`** — Structural: verify the `dreaming.py` source passes `cluster_activity_window` to `EmergentDetector()`.

### Class: `TestRuntimeWiring` (1 test)

7. **`test_record_activity_called_from_runtime`** — Structural: inspect `runtime.py` source for `record_activity()` call near `record_interaction()`.

### Class: `TestRecordActivityMethod` (1 test)

8. **`test_record_activity_updates_timestamp`** — Create EmergentDetector, verify `_last_activity_time` is 0.0, call `record_activity()`, verify `_last_activity_time` > 0.

## Files Modified

| File | Change |
|------|--------|
| `src/probos/cognitive/emergent_detector.py` | Add `_last_activity_time`, `_cluster_activity_window`, `record_activity()` method, activity gate in `detect_cooperation_clusters()` |
| `src/probos/runtime.py` | Add `record_activity()` call after `record_interaction()` |
| `src/probos/config.py` | Add `cluster_activity_window` to `EmergentDetectorConfig` |
| `src/probos/startup/dreaming.py` | Pass `cluster_activity_window` to constructor |
| `tests/test_bf165_stasis_cluster.py` | **NEW** — 8 tests across 4 classes |

## Verification

After building:
1. Run `pytest tests/test_bf165_stasis_cluster.py -v` — all 8 must pass.
2. Run `pytest tests/test_emergent_detector.py -v` — existing tests must pass.
3. Run `pytest tests/ -x --timeout=60` — full regression, no failures.
