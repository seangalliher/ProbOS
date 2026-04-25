# BF-124: Cooperation Cluster Detection Calibration

## Context

Crew-identified issue across four departments (Operations, Science, Medical, Engineering): the EmergentDetector's cooperation cluster detection fires persistent false positives, especially after stasis recovery. The detector interprets routine Hebbian weight activity (agents doing normal work) as emergent cooperation clusters, generating Ward Room bridge alerts every ~10 minutes (600-second dedup cooldown cycles).

BF-126 partially addressed post-stasis false positives by adding a 300-second suppression window. But the underlying problem persists beyond the suppression window: the **edge threshold of 0.1 is too low** — routine Hebbian weight accumulation from normal agent interactions exceeds this threshold quickly, causing union-find to connect agents who are simply doing their jobs into "cooperation clusters."

Crew proposals (chronological):
- Cassian (Operations): Recalibrate thresholds, oversensitive after extended operation
- Lynx (Science): Alerts persist despite analytical resolution — no feedback loop
- Chapel (Medical): False positives every 10-15 min, degrading signal-to-noise
- Forge (Engineering): Use stasis restoration pattern as calibration data

**BF-124 remaining scope (from roadmap):** Two fixes needed: (1) Post-stasis cooldown in emergence detection. (2) Divergence alert dedup — same agent pair + same topic should not re-alert until content materially changes.

This prompt addresses fix (1) — threshold calibration + configurable parameters. Fix (2) — divergence alert dedup — is a separate concern.

## Root Cause Analysis

1. **Edge threshold too low:** `threshold = 0.1` hardcoded at `emergent_detector.py:382`. Hebbian weights increase with each successful intent routing. After even moderate operation, many agent-intent pairs exceed 0.1, causing the union-find to connect large portions of the graph into a single mega-cluster. This is normal system behavior, not emergent cooperation.

2. **No minimum cluster quality:** A cluster of 2 nodes with avg_weight 0.11 is reported the same as a cluster of 8 nodes with avg_weight 0.95. No filtering for cluster significance.

3. **No configurable parameters:** Unlike trust anomaly detection (BF-089, 12 configurable params), cooperation cluster detection has zero configurable parameters. The threshold, minimum size, and minimum avg_weight are all hardcoded or absent.

4. **Micro-dream path doesn't fire alerts but accumulates patterns:** `on_post_micro_dream()` (dream_adapter.py:245) calls `analyze()` every ~10s but doesn't pass results to BridgeAlertService. However, patterns still accumulate in `_all_patterns`. The full dream path (`on_post_dream()`, dream_adapter.py:139) calls `analyze()` AND passes to `bridge_alerts.check_emergent_patterns()` — this is where Ward Room alerts originate.

## Prerequisites

Verify before building:

```bash
# 1. Cooperation cluster detection method
grep -n "def detect_cooperation_clusters" src/probos/cognitive/emergent_detector.py
# Expected: line ~346

# 2. Hardcoded threshold
grep -n "threshold = 0.1" src/probos/cognitive/emergent_detector.py
# Expected: line ~382

# 3. analyze() wraps clusters as EmergentPattern
grep -n "cooperation_cluster" src/probos/cognitive/emergent_detector.py
# Expected: lines ~255-267 (pattern creation), line ~258 (dedup)

# 4. BF-126 suppression
grep -n "_suppress_clusters_until" src/probos/cognitive/emergent_detector.py
# Expected: lines ~174, ~196, ~355

# 5. Constructor params (BF-089 pattern to follow)
grep -n "def __init__" src/probos/cognitive/emergent_detector.py
# Expected: line ~103, 12 keyword params for trust anomaly detection

# 6. BridgeAlertService cooperation_cluster handling
grep -n "cooperation_cluster" src/probos/bridge_alerts.py
# Expected: line ~231-244

# 7. Config — no EmergentDetectorConfig exists
grep -n "class.*Config.*BaseModel" src/probos/config.py
# Expected: NO EmergentDetectorConfig class

# 8. Wiring in startup
grep -n "EmergentDetector" src/probos/startup/dreaming.py
# Expected: line ~126, constructor call with no threshold params

# 9. Existing cluster tests
grep -n "class TestCooperationCluster" tests/test_emergent_detector.py
# Expected: line ~212

# 10. Pattern cooldown default
grep -n "_pattern_cooldown_seconds" src/probos/cognitive/emergent_detector.py
# Expected: line ~166, 600.0 seconds
```

## Implementation

### Phase 1: Add Configurable Cooperation Cluster Parameters

**File: `src/probos/cognitive/emergent_detector.py`**

Add three new constructor parameters alongside the existing BF-089 trust params (after line ~121):

```python
# BF-124: Configurable cooperation cluster thresholds
cluster_edge_threshold: float = 0.3,
cluster_min_size: int = 3,
cluster_min_avg_weight: float = 0.25,
cluster_cooldown_seconds: float = 1800.0,
```

Store them as instance variables (same pattern as BF-089 trust params):

```python
# BF-124: Cooperation cluster detection thresholds
self._cluster_edge_threshold = cluster_edge_threshold
self._cluster_min_size = cluster_min_size
self._cluster_min_avg_weight = cluster_min_avg_weight
```

**Threshold justification:**
- `cluster_edge_threshold: 0.3` (was 0.1) — Hebbian weights start at 0.0 and grow via `strengthen()`. A weight of 0.1 means roughly 1-2 successful routings. A weight of 0.3 means sustained, repeated cooperation — a much stronger signal of genuine emergent cooperation vs routine work.
- `cluster_min_size: 3` (was 0, effectively any cluster) — A cluster of 2 nodes is just one connection. Require at least 3 nodes for a meaningful cooperation topology. The `severity` already treats size >= 3 as "notable" (line 266); this makes it a hard filter.
- `cluster_min_avg_weight: 0.25` (new) — Even if edges are above threshold, require the cluster average to be meaningful. Filters out clusters where one strong edge pulls in a chain of weak ones.
- `cluster_cooldown_seconds: 1800.0` (30 min, was 600.0) — Reduce alert frequency for cooperation clusters specifically. Cooperation clusters are structural, not transient — they don't need 10-minute re-alerting.

### Phase 2: Update `detect_cooperation_clusters()`

**File: `src/probos/cognitive/emergent_detector.py`**

Replace the hardcoded threshold at line ~382:

```python
# Before:
threshold = 0.1

# After (BF-124):
threshold = self._cluster_edge_threshold
```

Add cluster quality filtering after the union-find builds clusters (after line ~436, before the return):

```python
# BF-124: Filter clusters by minimum size and average weight
clusters = [
    c for c in clusters
    if c["size"] >= self._cluster_min_size
    and c["avg_weight"] >= self._cluster_min_avg_weight
]
```

### Phase 3: Per-Pattern-Type Cooldown

**File: `src/probos/cognitive/emergent_detector.py`**

Currently `_pattern_cooldown_seconds` is a single value (600s) applied to all pattern types. Cooperation clusters are structural patterns that change slowly — they shouldn't re-alert as often as transient trust anomalies.

Add a per-type cooldown lookup. In `_is_duplicate_pattern()` (line ~209), replace:

```python
# Before:
if last is not None and now - last < self._pattern_cooldown_seconds:

# After (BF-124):
cooldown = self._pattern_cooldown_seconds
if pattern_type == "cooperation_cluster":
    cooldown = self._cluster_cooldown_seconds
if last is not None and now - last < cooldown:
```

Also update `_prune_stale_dedup_entries()` to use the max cooldown for pruning:

```python
# Before:
cutoff = now - self._pattern_cooldown_seconds * 2

# After (BF-124):
max_cooldown = max(self._pattern_cooldown_seconds, self._cluster_cooldown_seconds)
cutoff = now - max_cooldown * 2
```

### Phase 4: Add `EmergentDetectorConfig` to SystemConfig

**File: `src/probos/config.py`**

Add a new config class (follow the `BridgeAlertConfig` pattern, insert after it):

```python
class EmergentDetectorConfig(BaseModel):
    """BF-124: Emergent detector calibration parameters."""
    cluster_edge_threshold: float = 0.3
    cluster_min_size: int = 3
    cluster_min_avg_weight: float = 0.25
    cluster_cooldown_seconds: float = 1800.0
```

Add the field to `SystemConfig`:

```python
emergent_detector: EmergentDetectorConfig = Field(default_factory=EmergentDetectorConfig)
```

### Phase 5: Wire Config to EmergentDetector Construction

**File: `src/probos/startup/dreaming.py`**

Update the EmergentDetector construction (line ~126) to pass config params:

```python
# Before:
emergent_detector = EmergentDetector(
    hebbian_router=hebbian_router,
    trust_network=trust_network,
    episodic_memory=episodic_memory,
)

# After (BF-124):
_edc = config.emergent_detector
emergent_detector = EmergentDetector(
    hebbian_router=hebbian_router,
    trust_network=trust_network,
    episodic_memory=episodic_memory,
    cluster_edge_threshold=_edc.cluster_edge_threshold,
    cluster_min_size=_edc.cluster_min_size,
    cluster_min_avg_weight=_edc.cluster_min_avg_weight,
    cluster_cooldown_seconds=_edc.cluster_cooldown_seconds,
)
```

Verify that `config` (the `SystemConfig` instance) is available in this startup module — check how the DreamingConfig is accessed in the same file for the pattern.

### Phase 6: Divergence Alert Dedup (BF-124 fix #2)

**File: `src/probos/bridge_alerts.py`**

The crew reported 7 identical divergence alerts (same agent pair, same topic) in 3 hours. The current dedup key for emergent patterns is `f"emergent:{ptype}"` (line 238) — a single static key per pattern type. This means ALL cooperation clusters share one cooldown slot, which is actually fine. But divergence alerts (from `check_divergence()`) need topic-aware dedup.

Find the `check_divergence()` method and its dedup key. If the dedup key is generic (e.g., `"divergence"` or `"divergence:{pair}"`), enhance it to include a topic hash:

```python
# Enhanced dedup key for divergence alerts:
key = f"divergence:{agent_a}:{agent_b}:{topic_hash[:8]}"
```

Where `topic_hash` is a hash of the divergence topic text. This ensures the same agent pair on the same topic doesn't re-alert, while new topics for the same pair still fire.

**Note:** Read the `check_divergence()` method first to understand its current dedup key structure before implementing. If it already has agent-pair-aware dedup, the fix is just adding topic awareness.

## Engineering Principles Compliance

| Principle | How Applied |
|-----------|-------------|
| **Single Responsibility** | Threshold calibration stays in EmergentDetector. Config in SystemConfig. Wiring in startup. No new classes needed. |
| **Open/Closed** | Extends cooperation cluster detection with configurable thresholds without changing the detection algorithm (union-find). New parameters, not new logic. |
| **DRY** | Follows exact BF-089 pattern for configurable thresholds — constructor params, instance variables, config model. No duplicate patterns. |
| **Defense in Depth** | Three-layer filtering: (1) edge threshold, (2) minimum cluster size, (3) minimum avg weight. Each independently prevents false positives. |
| **Fail Fast / Degrade** | All threshold defaults chosen to reduce false positives. If config is missing, defaults are safe (higher thresholds = fewer alerts). |
| **Cloud-Ready** | Config stored in SystemConfig, persistable to YAML/JSON. No hardcoded magic numbers. |

## Tests

**File: `tests/test_emergent_detector.py`** — Add to existing test file.

### TestBF124ThresholdCalibration (8 tests)

1. `test_default_cluster_threshold_is_030` — Default `cluster_edge_threshold` is 0.3, not 0.1.
2. `test_cluster_threshold_configurable` — Constructor accepts custom `cluster_edge_threshold`, weights below threshold excluded.
3. `test_cluster_min_size_filters_small` — Clusters with 2 nodes filtered out when `cluster_min_size=3`.
4. `test_cluster_min_avg_weight_filters_weak` — Cluster with avg_weight < 0.25 filtered out.
5. `test_cluster_quality_combined` — Cluster passes edge threshold but fails min_avg_weight → filtered.
6. `test_genuine_cluster_detected` — Strong cluster (5 nodes, avg_weight 0.8) detected correctly.
7. `test_cluster_cooldown_longer_than_default` — Cooperation cluster dedup cooldown is 1800s (30 min), not 600s.
8. `test_cluster_cooldown_per_type` — Trust anomaly uses 600s cooldown, cooperation cluster uses 1800s, in same detector.

### TestBF124Config (3 tests)

9. `test_emergent_detector_config_exists` — `EmergentDetectorConfig` importable from `probos.config`.
10. `test_system_config_has_emergent_detector` — `SystemConfig().emergent_detector` returns `EmergentDetectorConfig` with defaults.
11. `test_config_values_override` — Custom values in YAML/dict override defaults.

### TestBF124DivergenceDedup (3 tests) — if divergence dedup is implemented

12. `test_divergence_same_pair_same_topic_deduped` — Same agent pair + same topic → suppressed within cooldown.
13. `test_divergence_same_pair_new_topic_fires` — Same agent pair + different topic → new alert fires.
14. `test_divergence_different_pair_same_topic_fires` — Different agent pair + same topic → new alert fires.

### TestBF124Regression (2 tests)

15. `test_bf126_suppression_still_works` — Post-stasis suppression window still suppresses even with new thresholds.
16. `test_existing_trust_anomaly_detection_unchanged` — Trust anomaly detection params/behavior unchanged by BF-124.

**Total: 14-16 tests** (depending on divergence dedup scope).

## Build Verification

```bash
# 1. New tests pass
python -m pytest tests/test_emergent_detector.py -v -k "BF124"

# 2. All existing emergent detector tests still pass
python -m pytest tests/test_emergent_detector.py -v

# 3. No import errors
python -c "from probos.config import EmergentDetectorConfig; print('OK')"

# 4. Full suite
python -m pytest tests/ -x -q
```

## Files Modified

| File | Changes |
|------|---------|
| `src/probos/cognitive/emergent_detector.py` | 4 new constructor params, replace hardcoded threshold, add cluster quality filtering, per-type cooldown |
| `src/probos/config.py` | `EmergentDetectorConfig` class, `emergent_detector` field on `SystemConfig` |
| `src/probos/startup/dreaming.py` | Wire config params to EmergentDetector constructor |
| `src/probos/bridge_alerts.py` | Divergence alert topic-aware dedup (if applicable) |
| `tests/test_emergent_detector.py` | 14-16 new tests |
