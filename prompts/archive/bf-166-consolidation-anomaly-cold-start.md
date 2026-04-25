# BF-166: Consolidation Anomaly False Positives After Stasis

## Problem

`detect_consolidation_anomalies()` in `src/probos/cognitive/emergent_detector.py` fires false
positive `consolidation_anomaly` patterns immediately after stasis recovery. Crew-identified:
Atlas and Lynx observed 7 consecutive anomaly events in rapid succession post-stasis, generating
noise that distracts from genuine emergent behavior detection.

### Root Cause (Three Defects)

1. **Minimum history gate too low (line 822):** `if len(self._dream_history) < 2` — with only 1
   prior dream report as baseline, any variance appears as >2x deviation. Compare with
   `compute_trends()` which requires 20+ snapshots, or `detect_cooperation_clusters()` which
   requires 10+ episodes (AD-288). The gate should require at least 5 reports before flagging.

2. **No cold-start suppression:** `set_cold_start_suppression()` (line 205–214) sets
   `_suppress_trust_until` (BF-034) and `_suppress_clusters_until` (BF-126) but does NOT set any
   suppression for dream anomaly detection. Post-stasis dream cycles consolidate stale state and
   should be suppressed during the cold-start window.

3. **Unbounded `_dream_history`:** Line 175 uses `list[dict]` — grows without bound for the
   process lifetime. The snapshot ring buffer `_history` (line 166) uses
   `collections.deque(maxlen=max_history)`. `_dream_history` should follow the same pattern.

## Fix

All changes in `src/probos/cognitive/emergent_detector.py` unless stated otherwise.

### Part A: Raise minimum history gate

**Line 822:** Change `< 2` to `< 5`. This gives the detector enough intra-session variance to
establish a meaningful baseline before comparing. Five reports ensure at least 4 data points in
the historical average, which is enough to identify genuine 2x deviations versus normal variance.

```python
# Before:
if len(self._dream_history) < 2:
    return patterns

# After:
# BF-166: Require 5 dream reports for a meaningful baseline.
# With only 1-2 reports, any variance triggers a false 2x anomaly.
if len(self._dream_history) < 5:
    return patterns
```

### Part B: Add cold-start suppression

**Line 175 area** — Add a new suppression field:

```python
# BF-166: Post-stasis suppression for consolidation anomaly detection
self._suppress_dreams_until: float = 0.0
```

**`set_cold_start_suppression()` (line 205–214)** — Add dream suppression alongside trust and
clusters:

```python
def set_cold_start_suppression(self, duration_seconds: float) -> None:
    """Suppress trust anomaly, cooperation cluster, and dream consolidation
    anomaly detection after a cold start.

    BF-034: Trust anomalies suppressed since baseline trust (0.5) is expected.
    BF-126: Cooperation clusters suppressed since synchronized agent startup
    creates correlated Hebbian activity that looks like cooperation but is
    just simultaneous initialization. Routing shifts still fire.
    BF-166: Dream consolidation anomalies suppressed since first post-stasis
    dream cycles consolidate stale state with no meaningful baseline.
    """
    self._suppress_trust_until = time.monotonic() + duration_seconds
    self._suppress_clusters_until = time.monotonic() + duration_seconds
    self._suppress_dreams_until = time.monotonic() + duration_seconds
```

**`detect_consolidation_anomalies()` — Add suppression check as first gate (before line 801):**

```python
def detect_consolidation_anomalies(self, dream_report: Any = None) -> list[EmergentPattern]:
    """Detect unusual dream consolidation patterns ..."""
    patterns: list[EmergentPattern] = []

    # BF-166: Suppress during post-stasis window — first dream cycles
    # consolidate stale state with no meaningful baseline
    if time.monotonic() < self._suppress_dreams_until:
        return patterns

    if dream_report is None:
        return patterns
    # ... rest unchanged
```

### Part C: Bound `_dream_history` with deque

**Line 175** — Replace plain list with deque using `max_history` (same parameter used for
`_history` on line 166):

```python
# Before:
self._dream_history: list[dict] = []

# After:
# BF-166: Bounded ring buffer (matches _history pattern on line 166)
self._dream_history: collections.deque[dict] = collections.deque(maxlen=max_history)
```

No other code changes needed — `list.append()` and `deque.append()` share the same API, and
slice operations (`[:-1]`, `[-1]`) also work on deque.

### Part D: Add `dream_min_history` to `EmergentDetectorConfig`

**`src/probos/config.py` — `EmergentDetectorConfig` class (line 643):**

```python
class EmergentDetectorConfig(BaseModel):
    """BF-124: Emergent detector calibration parameters."""
    cluster_edge_threshold: float = 0.3
    cluster_min_size: int = 3
    cluster_min_avg_weight: float = 0.25
    cluster_cooldown_seconds: float = 1800.0
    cluster_activity_window: float = 900.0  # BF-165
    dream_min_history: int = 5  # BF-166: minimum dream reports before anomaly detection fires
```

**`src/probos/cognitive/emergent_detector.py` constructor** — Add `dream_min_history` parameter:

```python
def __init__(
    self,
    hebbian_router: HebbianRouter,
    trust_network: TrustNetwork,
    episodic_memory: Any = None,
    max_history: int = 100,
    trend_threshold: float = 0.7,
    # ... existing params ...
    cluster_activity_window: float = 900.0,  # BF-165: 15 minutes
    dream_min_history: int = 5,  # BF-166
) -> None:
```

Store it:

```python
self._dream_min_history = dream_min_history
```

**Usage in `detect_consolidation_anomalies()`:**

```python
if len(self._dream_history) < self._dream_min_history:
    return patterns
```

**Wiring** — `src/probos/startup/dreaming.py` line 127–136 passes `EmergentDetectorConfig`
fields to the constructor. Add `dream_min_history=_edc.dream_min_history` after line 135
(follows `cluster_activity_window` pattern).

## Config

**`config/system.yaml`** — If `emergent_detector` section exists, document the new field. If not,
the default (5) applies. No YAML change required unless there's an existing section.

## Tests

**New test file: `tests/test_bf166_consolidation_cold_start.py`**

```python
"""BF-166: Consolidation anomaly false positives after stasis."""
import collections
import time

from probos.cognitive.emergent_detector import EmergentDetector
from probos.types import DreamReport

# Re-use the existing test helper for creating detectors with mock deps.
# _make_detector() in test_emergent_detector.py passes **kwargs through to
# EmergentDetector, so dream_min_history can be set via kwargs.
from tests.test_emergent_detector import _make_detector


class TestConsolidationMinHistory:
    """Part A: Minimum history gate raised to 5."""

    def test_no_anomaly_with_fewer_than_5_reports(self):
        """4 reports should never trigger anomalies, even with variance."""
        d = _make_detector()
        # First 3 reports: low values
        for _ in range(3):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=1, weights_pruned=1, trust_adjustments=0)
            )
        # 4th report: 100x spike — should NOT fire because < 5 history
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=100, weights_pruned=100, trust_adjustments=100)
        )
        assert patterns == []

    def test_anomaly_fires_after_5_reports(self):
        """With 5 baseline reports, a spike on the 6th should fire."""
        d = _make_detector()
        for _ in range(5):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=5, weights_pruned=3, trust_adjustments=2)
            )
        # 6th report: big spike
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=50, weights_pruned=30, trust_adjustments=20)
        )
        assert len(patterns) > 0
        assert all(p.pattern_type == "consolidation_anomaly" for p in patterns)

    def test_configurable_min_history(self):
        """dream_min_history parameter controls the gate."""
        d = _make_detector(dream_min_history=3)
        for _ in range(3):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=5, weights_pruned=3, trust_adjustments=2)
            )
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=50, weights_pruned=3, trust_adjustments=2)
        )
        assert len(patterns) > 0


class TestConsolidationColdStartSuppression:
    """Part B: Cold-start suppression for dream anomalies."""

    def test_suppressed_during_cold_start_window(self):
        """No dream anomalies during suppression window."""
        d = _make_detector()
        d.set_cold_start_suppression(300.0)
        # Build enough history
        for _ in range(6):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=5, weights_pruned=3, trust_adjustments=2)
            )
        # Spike during suppression — should be suppressed
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=50, weights_pruned=3, trust_adjustments=2)
        )
        assert patterns == []

    def test_fires_after_suppression_expires(self):
        """Dream anomalies fire after suppression window expires."""
        d = _make_detector()
        d.set_cold_start_suppression(0.01)  # Near-instant expiry
        time.sleep(0.02)
        # Build baseline after suppression expires
        for _ in range(5):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=5, weights_pruned=3, trust_adjustments=2)
            )
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=50, weights_pruned=3, trust_adjustments=2)
        )
        assert len(patterns) > 0

    def test_cold_start_suppression_includes_dreams(self):
        """set_cold_start_suppression() sets _suppress_dreams_until."""
        d = _make_detector()
        d.set_cold_start_suppression(300.0)
        assert d._suppress_dreams_until > time.monotonic()


class TestDreamHistoryBounded:
    """Part C: _dream_history uses deque with maxlen."""

    def test_dream_history_is_bounded(self):
        """_dream_history should not grow beyond max_history."""
        d = _make_detector()
        assert isinstance(d._dream_history, collections.deque)
        assert d._dream_history.maxlen is not None

    def test_dream_history_evicts_oldest(self):
        """Old entries are evicted when maxlen exceeded."""
        d = _make_detector(max_history=10)
        for i in range(20):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=i, weights_pruned=0, trust_adjustments=0)
            )
        assert len(d._dream_history) == 10
        # Oldest entries evicted — first entry should NOT be 0
        assert d._dream_history[0]["weights_strengthened"] >= 10
```

## Existing Test Updates

**`tests/test_emergent_detector.py` — `TestConsolidationAnomalies` class:**

The existing tests `test_high_strengthened_anomaly`, `test_high_pruned_anomaly` build baselines
with only 3 reports (lines 432–434, 444–446). These must be updated to build 5 reports to
satisfy the new minimum history gate. Change `range(3)` to `range(5)` in the baseline loops for
these tests. Also update `test_normal_dream_report_no_anomalies` which uses only 2 reports — it
should still pass (no anomaly), but for the right reason (below minimum, not normal variance).
Add a comment clarifying this.

## Verification

```bash
pytest tests/test_bf166_consolidation_cold_start.py tests/test_emergent_detector.py -v
```

## Engineering Principles Checklist

- **DRY:** Follows established suppression pattern from BF-034/BF-126/BF-165. Same
  `set_cold_start_suppression()` entry point, same `time.monotonic()` comparison pattern.
- **Fail Fast / Log-and-Degrade:** When suppressed, returns empty list (log-and-degrade —
  graceful degradation, no crash, no log spam). Matches existing trust/cluster suppression.
- **Open/Closed:** New `dream_min_history` parameter extends behavior via config without
  modifying default behavior (default=5 preserves backward compatibility).
- **Defense in Depth:** Three layers: (1) cold-start time suppression, (2) minimum history gate,
  (3) bounded storage prevents resource exhaustion. Any single layer failing doesn't cause harm.
- **Cloud-Ready Storage:** No storage changes — in-memory ring buffer, matches existing pattern.

## Files Modified

1. `src/probos/cognitive/emergent_detector.py` — 3 changes (suppression field + constructor
   param + deque + gate + suppress check)
2. `src/probos/config.py` — 1 field added to `EmergentDetectorConfig`
3. `tests/test_bf166_consolidation_cold_start.py` — NEW (8 tests)
4. `tests/test_emergent_detector.py` — Update baseline counts in `TestConsolidationAnomalies`
