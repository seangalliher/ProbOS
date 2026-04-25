# AD-380: EmergentDetector Trend Regression

## Goal

Add multi-snapshot trend analysis to the EmergentDetector. Today it only compares current vs previous snapshot (pairwise). The ring buffer holds 100 `SystemDynamicsSnapshot` entries — enough data for slope computation, but no trend regression exists. This AD computes derivatives over the buffer so the system can distinguish real emergence from per-snapshot noise.

## Architecture

**Pattern:** Extend the existing `EmergentDetector` in `src/probos/cognitive/emergent_detector.py`. Add a new `TrendReport` dataclass and a `compute_trends()` method. Wire into the existing `detect_anomalies()` output.

## Reference Files (read these first)

- `src/probos/cognitive/emergent_detector.py` — current detector with ring buffer, 5 algorithms, `SystemDynamicsSnapshot`
- `tests/test_emergent_detector.py` — existing tests

## Changes

### Modify `src/probos/cognitive/emergent_detector.py`

Add the following after the existing `SystemDynamicsSnapshot` dataclass:

```python
@dataclass
class TrendDirection(str, Enum):
    RISING = "rising"
    STABLE = "stable"
    FALLING = "falling"

@dataclass
class MetricTrend:
    """Trend analysis for a single metric over N snapshots."""
    metric_name: str
    direction: TrendDirection
    slope: float  # rate of change per snapshot
    r_squared: float  # goodness of fit (0-1), indicates confidence
    current_value: float
    window_size: int  # how many snapshots were used
    significant: bool  # slope magnitude > threshold AND r_squared > 0.5

@dataclass
class TrendReport:
    """Multi-metric trend analysis over the snapshot ring buffer."""
    tc_n: MetricTrend
    routing_entropy: MetricTrend
    cluster_count: MetricTrend  # number of cooperation clusters
    trust_spread: MetricTrend  # std dev of trust distribution
    capability_count: MetricTrend
    significant_trends: list[MetricTrend]  # only trends where significant=True
    window_size: int
    timestamp: float
```

Add a `compute_trends()` method to `EmergentDetector`:

```python
def compute_trends(self, min_window: int = 20) -> TrendReport | None:
    """Compute trend regression over the snapshot ring buffer.

    Returns None if fewer than min_window snapshots are available.
    Uses simple linear regression (no numpy dependency).
    """
```

Implementation requirements:
- **Linear regression**: Implement `_linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float, float]` as a private helper. Returns `(slope, intercept, r_squared)`. Use the standard formula — no numpy. `xs` are sequential indices (0, 1, 2, ...), `ys` are metric values.
- **Metric extraction**: For each snapshot in `self._history[-min_window:]`, extract: `tc_n`, `routing_entropy`, `len(cooperation_clusters)`, `trust_distribution["std"]`, `capability_count`.
- **Direction classification**: `RISING` if slope > threshold, `FALLING` if slope < -threshold, `STABLE` otherwise. Threshold is configurable via constructor (`trend_threshold`, default `0.005`).
- **Significance test**: A trend is significant if `abs(slope) > trend_threshold` AND `r_squared > 0.5` AND `window_size >= min_window`.
- **`significant_trends`**: Filter to only `MetricTrend` entries where `significant=True`.

Also add a `trend_threshold: float = 0.005` parameter to the `EmergentDetector.__init__()`.

Replace the `self._history` list with `collections.deque(maxlen=max_history)` for proper ring buffer behavior.

### Wire into existing `detect_anomalies()`

At the end of `detect_anomalies()`, after the existing 5 detectors, call `compute_trends()` and add an entry to the anomalies dict if there are significant trends:

```python
trend_report = self.compute_trends()
if trend_report and trend_report.significant_trends:
    result["emergence_trends"] = {
        "trends": [
            {
                "metric": t.metric_name,
                "direction": t.direction.value,
                "slope": round(t.slope, 6),
                "r_squared": round(t.r_squared, 3),
                "current": round(t.current_value, 4),
            }
            for t in trend_report.significant_trends
        ],
        "window_size": trend_report.window_size,
    }
```

### Create `tests/test_emergent_trends.py` (~120 lines)

Test cases:

1. **`test_trend_report_none_insufficient_data`** — Fewer than `min_window` snapshots → returns `None`
2. **`test_linear_regression_perfect_line`** — xs=[0,1,2,3,4], ys=[0,2,4,6,8] → slope=2.0, r_squared≈1.0
3. **`test_linear_regression_flat`** — ys all the same → slope=0.0
4. **`test_trend_rising_tc_n`** — Feed 25 snapshots with linearly increasing `tc_n` (0.1 to 0.6) → MetricTrend direction=RISING, significant=True
5. **`test_trend_falling_entropy`** — Feed 25 snapshots with linearly decreasing `routing_entropy` → direction=FALLING
6. **`test_trend_stable`** — Feed 25 snapshots with near-constant values (small random noise around 0.5) → direction=STABLE, significant=False
7. **`test_significant_trends_filtered`** — Mix of rising/stable metrics → `significant_trends` only contains the rising ones
8. **`test_trend_threshold_configurable`** — Large threshold (0.1) makes small slopes non-significant
9. **`test_deque_maxlen_respected`** — Add 150 snapshots → buffer stays at 100
10. **`test_detect_anomalies_includes_trends`** — After 25+ snapshots with rising tc_n, `detect_anomalies()` output contains `emergence_trends` key
11. **`test_r_squared_low_noisy_data`** — Noisy data with no clear trend → r_squared < 0.5, significant=False
12. **`test_trend_with_missing_trust_std`** — Snapshot with empty trust_distribution (no "std" key) → gracefully handles missing data (uses 0.0)

Use `_make_snapshot()` helper that creates a `SystemDynamicsSnapshot` with configurable `tc_n`, `routing_entropy`, `cooperation_clusters`, `trust_distribution`, `capability_count`. Default values for non-varied fields.

## Constraints

- No numpy or scipy — pure Python linear regression
- Do not modify the 5 existing detection algorithms
- Backward compatible — `detect_anomalies()` output unchanged if no significant trends
- Import `collections.deque` at module level
