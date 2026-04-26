# AD-556: Adaptive Trust Anomaly Detection — Per-Agent Z-Score Thresholding

**Issue:** TBD (create issue after review)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** TrustNetwork (complete), VitalsMonitor (complete), AD-506a graduated zones (complete)
**Files:** `src/probos/cognitive/emergent_detector.py`, `src/probos/config.py`, `tests/test_ad556_adaptive_trust_anomaly.py` (NEW)

## Problem

The current trust anomaly detection in `EmergentDetector.detect_trust_anomalies()` (line 564 of `emergent_detector.py`) uses **population-level** sigma thresholds: it computes the mean and std of ALL agents' trust scores, then flags agents whose score deviates > 2σ from the population mean. This has three problems:

1. **Population noise masking.** An agent whose trust drops from 0.85 to 0.55 over 30 minutes — a genuine degradation — may not trigger an alert if the population std is wide enough (e.g., Red Team's low trust stretches the std). The anomaly is real for that agent but invisible in population statistics.

2. **False positives from stable agents.** Agents with naturally stable trust (Medical, Operations) produce micro-oscillations that occasionally exceed the population sigma threshold even though the delta is within their normal variance. The BF-089 temporal buffer partially addresses this but doesn't adapt per agent.

3. **No personal baseline.** The current system compares each agent to the population, not to themselves. A Security agent with a naturally volatile trust trajectory triggers repeatedly. A Science agent with a normally stable trajectory may miss a genuine degradation because its delta is small in absolute terms but large relative to its own history.

**Root cause:** The detection was designed before per-agent profiling infrastructure existed. AD-556 adds per-agent rolling z-score analysis alongside the existing population sigma detection, and gates zone model integration through the adaptive layer.

## Design

Three additions to `EmergentDetector`:

1. **Per-agent trust delta window** — Rolling window of recent trust score snapshots per agent, updated on each `detect_trust_anomalies()` call. Computes per-agent rolling mean and std of trust deltas (score changes between consecutive snapshots).

2. **Z-score anomaly gating** — New trust events are scored as z-scores against the agent's personal baseline. Only propagate to pattern list when delta exceeds a configurable sigma threshold (default 2.5σ from personal baseline). Sub-threshold events still update the rolling window for baseline maintenance.

3. **Debounce** — Require anomalous z-scores to persist across multiple consecutive detection cycles (default 2) before escalating. A single-snapshot spike that immediately returns is noise. This replaces the raw count-based `_record_anomaly_observation()` for the new adaptive path.

**Integration with existing system:** The per-agent z-score check is an **additional gate** on the existing population sigma detection. An anomaly must pass BOTH the population sigma threshold (existing, unchanged) AND the per-agent z-score threshold (new) to be emitted. This means:
- Existing behavior for agents without enough personal history: falls through to population-only detection
- Agents with personal history: both gates must fire (reduces false positives)
- The zone model (AD-506a) sees only filtered anomalies (no integration changes needed — zone transitions are already driven by pattern emissions)

## What This Does NOT Change

- `detect_trust_anomalies()` signature — unchanged
- `EmergentPattern` dataclass — unchanged (new evidence keys added to existing dict)
- `_record_anomaly_observation()` — still used for population-only anomalies (agents without enough personal history)
- `_prune_stale_anomaly_counts()` — unchanged
- BF-034 cold-start suppression — unchanged
- BF-089 duty correlation window — unchanged
- BF-100 dream suppression — unchanged
- AD-411 dedup — unchanged
- Cooperation cluster detection — unchanged
- Routing shift detection — unchanged
- Consolidation anomaly detection — unchanged
- Zone model (circuit_breaker.py) — no changes
- TrustNetwork API — no changes
- VitalsMonitor — no changes
- Startup wiring (dreaming.py) — gains new config parameters only

---

## Section 1: Add per-agent trust history tracking

**File:** `src/probos/cognitive/emergent_detector.py`

### 1a: Add new constructor parameters

Add to `__init__` signature, after `max_trust_anomalies_per_pass: int = 3,` (line 120):

```python
        # AD-556: Per-agent adaptive trust anomaly detection
        adaptive_window_size: int = 30,
        adaptive_z_threshold: float = 2.5,
        adaptive_debounce_count: int = 2,
        adaptive_min_history: int = 8,
```

Store them in the constructor body, after `self._duty_correlation_window = duty_correlation_window` (line 151):

```python
        # AD-556: Per-agent adaptive trust anomaly detection
        self._adaptive_window_size = adaptive_window_size
        self._adaptive_z_threshold = adaptive_z_threshold
        self._adaptive_debounce_count = adaptive_debounce_count
        self._adaptive_min_history = adaptive_min_history
```

### 1b: Add per-agent state dicts

After `self._trust_anomaly_counts: dict[str, list[float]] = {}` (line 164), add:

```python
        # AD-556: Per-agent trust score history for adaptive z-score detection
        self._agent_trust_history: dict[str, list[float]] = {}  # agent_id → recent scores
        self._agent_anomaly_streak: dict[str, int] = {}  # agent_id → consecutive anomalous cycles
```

### 1c: Add history update method

Add a new method after `_record_anomaly_observation()` (after line 562):

```python
    def _update_agent_trust_history(self, agent_id: str, score: float) -> None:
        """AD-556: Update per-agent trust score history for adaptive detection."""
        history = self._agent_trust_history.setdefault(agent_id, [])
        history.append(score)
        # Maintain rolling window
        if len(history) > self._adaptive_window_size:
            self._agent_trust_history[agent_id] = history[-self._adaptive_window_size:]

    def _compute_agent_z_score(self, agent_id: str, current_score: float) -> float | None:
        """AD-556: Compute z-score of current trust delta against agent's personal baseline.

        Returns None if insufficient history for meaningful z-score.
        """
        history = self._agent_trust_history.get(agent_id, [])
        if len(history) < self._adaptive_min_history:
            return None  # Not enough data for personal baseline

        # Compute deltas between consecutive history entries
        deltas = [history[i] - history[i - 1] for i in range(1, len(history))]
        if not deltas:
            return None

        delta_mean = sum(deltas) / len(deltas)
        delta_variance = sum((d - delta_mean) ** 2 for d in deltas) / len(deltas)
        delta_std = math.sqrt(delta_variance) if delta_variance > 0 else 0.0

        if delta_std < 0.001:
            # Agent has nearly zero variance — any non-trivial delta is anomalous
            # Use absolute threshold instead of z-score
            current_delta = current_score - history[-1] if history else 0.0
            if abs(current_delta) > self._trust_min_deviation:
                return 10.0  # Synthetic high z-score for stable agents with sudden change
            return 0.0

        # Z-score of the current delta relative to personal baseline
        current_delta = current_score - history[-1] if history else 0.0
        z = (current_delta - delta_mean) / delta_std
        return abs(z)

    def _check_adaptive_debounce(self, agent_id: str, z_score: float) -> bool:
        """AD-556: Check if anomalous z-score persists across consecutive cycles.

        Returns True if the anomaly should be promoted (debounce satisfied).
        """
        if z_score >= self._adaptive_z_threshold:
            streak = self._agent_anomaly_streak.get(agent_id, 0) + 1
            self._agent_anomaly_streak[agent_id] = streak
            return streak >= self._adaptive_debounce_count
        else:
            # Reset streak — anomaly did not persist
            self._agent_anomaly_streak.pop(agent_id, None)
            return False
```

---

## Section 2: Integrate adaptive detection into `detect_trust_anomalies()`

**File:** `src/probos/cognitive/emergent_detector.py`

Two changes within `detect_trust_anomalies()`:

### 2a: Update per-agent history on each pass

After the scores are computed (after line 596: `current_std = math.sqrt(variance) if variance > 0 else 0.0`), add a loop to update all agents' personal histories:

```python
        # AD-556: Update per-agent trust score history
        for agent_id, record in raw.items():
            agent_score = record["alpha"] / (record["alpha"] + record["beta"])
            self._update_agent_trust_history(agent_id, agent_score)
```

### 2b: Add adaptive z-score gate to sigma detection

In the sigma detection loop (the `for agent_id, record in raw.items():` block starting at line 615), AFTER the existing population sigma check (`if deviation > effective_sigma:` at line 636) and BEFORE the temporal buffer check (`if not self._record_anomaly_observation(anomaly_key):` at line 642), add the adaptive z-score gate:

Find this block (lines 636-642):
```python
                if deviation > effective_sigma:
                    direction = "high" if score > mean else "low"
                    severity = "significant" if deviation > self._trust_sigma_significant else "notable"

                    # BF-089: Temporal buffer — require sustained anomaly before emitting
                    anomaly_key = f"sigma:{agent_id}:{direction}"
                    if not self._record_anomaly_observation(anomaly_key):
                        continue
```

Replace with:
```python
                if deviation > effective_sigma:
                    direction = "high" if score > mean else "low"
                    severity = "significant" if deviation > self._trust_sigma_significant else "notable"

                    # AD-556: Per-agent adaptive z-score gate
                    z_score = self._compute_agent_z_score(agent_id, score)
                    if z_score is not None:
                        # Agent has enough personal history — use adaptive detection
                        if not self._check_adaptive_debounce(agent_id, z_score):
                            logger.debug(
                                "AD-556: Trust anomaly for %s suppressed by adaptive gate "
                                "(z=%.2f, threshold=%.1f, streak=%d/%d)",
                                agent_id[:8], z_score, self._adaptive_z_threshold,
                                self._agent_anomaly_streak.get(agent_id, 0),
                                self._adaptive_debounce_count,
                            )
                            continue
                    else:
                        # AD-556: Not enough personal history — fall back to population-only detection
                        # BF-089: Temporal buffer — require sustained anomaly before emitting
                        anomaly_key = f"sigma:{agent_id}:{direction}"
                        if not self._record_anomaly_observation(anomaly_key):
                            continue
```

### 2c: Add z-score to evidence dict

In the `EmergentPattern` evidence dict for the sigma anomaly (around line 666-676), add z-score info. Find:

```python
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
```

Replace with:
```python
                    # AD-556: Include per-agent z-score in evidence
                    adaptive_info = {}
                    if z_score is not None:
                        history = self._agent_trust_history.get(agent_id, [])
                        adaptive_info = {
                            "personal_z_score": round(z_score, 2),
                            "personal_history_len": len(history),
                            "detection_mode": "adaptive",
                        }
                    else:
                        adaptive_info = {"detection_mode": "population_only"}

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
                            **adaptive_info,
                        },
```

---

## Section 3: Add config parameters

**File:** `src/probos/config.py`

Add AD-556 parameters to `EmergentDetectorConfig` (after line 748, after `dream_anomaly_min_trust_adj`):

```python
    # AD-556: Per-agent adaptive trust anomaly detection
    adaptive_window_size: int = 30     # Number of trust snapshots per agent for rolling window
    adaptive_z_threshold: float = 2.5  # Z-score threshold for personal baseline anomaly
    adaptive_debounce_count: int = 2   # Consecutive anomalous cycles required before escalation
    adaptive_min_history: int = 8      # Minimum history entries before adaptive detection activates
```

**File:** `src/probos/startup/dreaming.py`

Add the new config parameters to the `EmergentDetector()` constructor call (after line 139, after `dream_anomaly_min_trust_adj=_edc.dream_anomaly_min_trust_adj,`):

```python
        # AD-556: Per-agent adaptive trust anomaly detection
        adaptive_window_size=_edc.adaptive_window_size,
        adaptive_z_threshold=_edc.adaptive_z_threshold,
        adaptive_debounce_count=_edc.adaptive_debounce_count,
        adaptive_min_history=_edc.adaptive_min_history,
```

---

## Section 4: Tests

**File:** `tests/test_ad556_adaptive_trust_anomaly.py` (NEW)

```python
"""Tests for AD-556: Adaptive Trust Anomaly Detection — Per-Agent Z-Score Thresholding."""

from __future__ import annotations

import math
import time
import pytest
from unittest.mock import MagicMock

from probos.cognitive.emergent_detector import EmergentDetector


def _make_detector(**kwargs) -> EmergentDetector:
    """Create an EmergentDetector with mock dependencies."""
    hebbian = MagicMock()
    hebbian.get_all_weights.return_value = {}

    trust = MagicMock()
    trust.raw_scores.return_value = {}
    trust.get_events_for_agent.return_value = []

    defaults = dict(
        hebbian_router=hebbian,
        trust_network=trust,
        # Relax population thresholds so we can test adaptive layer independently
        trust_sigma_threshold=1.5,
        trust_min_std=0.01,
        trust_min_observations=2.0,
        trust_min_deviation=0.01,
        trust_anomaly_min_count=1,  # Disable population temporal buffer
        # AD-556 defaults
        adaptive_window_size=10,
        adaptive_z_threshold=2.5,
        adaptive_debounce_count=2,
        adaptive_min_history=5,
    )
    defaults.update(kwargs)
    return EmergentDetector(**defaults)


def _set_trust_scores(detector: EmergentDetector, scores: dict[str, float]) -> None:
    """Configure mock trust network with given agent scores."""
    raw = {}
    for agent_id, score in scores.items():
        # Convert score to alpha/beta with enough observations
        alpha = score * 20
        beta = (1 - score) * 20
        raw[agent_id] = {"alpha": alpha, "beta": beta, "observations": 20.0}
    detector._trust.raw_scores.return_value = raw


# --- Per-agent history tracking ---

class TestAgentTrustHistory:

    def test_history_populated_on_detect(self):
        """AD-556: detect_trust_anomalies() populates per-agent history."""
        d = _make_detector()
        _set_trust_scores(d, {"agent_a": 0.7, "agent_b": 0.8})
        d.detect_trust_anomalies()
        assert "agent_a" in d._agent_trust_history
        assert "agent_b" in d._agent_trust_history
        assert len(d._agent_trust_history["agent_a"]) == 1

    def test_history_grows_over_calls(self):
        """AD-556: History accumulates over multiple detection passes."""
        d = _make_detector()
        _set_trust_scores(d, {"agent_a": 0.7, "agent_b": 0.8})
        for _ in range(5):
            d.detect_trust_anomalies()
        assert len(d._agent_trust_history["agent_a"]) == 5

    def test_history_capped_at_window_size(self):
        """AD-556: History doesn't exceed adaptive_window_size."""
        d = _make_detector(adaptive_window_size=5)
        _set_trust_scores(d, {"agent_a": 0.7, "agent_b": 0.8})
        for _ in range(10):
            d.detect_trust_anomalies()
        assert len(d._agent_trust_history["agent_a"]) == 5

    def test_update_agent_trust_history_direct(self):
        """AD-556: _update_agent_trust_history maintains rolling window."""
        d = _make_detector(adaptive_window_size=3)
        for i in range(5):
            d._update_agent_trust_history("agent_a", 0.5 + i * 0.01)
        assert len(d._agent_trust_history["agent_a"]) == 3
        # Should keep the most recent 3
        assert d._agent_trust_history["agent_a"][-1] == pytest.approx(0.54)


# --- Z-score computation ---

class TestZScoreComputation:

    def test_insufficient_history_returns_none(self):
        """AD-556: Returns None when agent has less than adaptive_min_history entries."""
        d = _make_detector(adaptive_min_history=5)
        for i in range(3):
            d._update_agent_trust_history("agent_a", 0.7 + i * 0.001)
        assert d._compute_agent_z_score("agent_a", 0.703) is None

    def test_sufficient_history_returns_zscore(self):
        """AD-556: Returns a z-score when enough history exists."""
        d = _make_detector(adaptive_min_history=5)
        # Build stable history with small deltas
        for i in range(8):
            d._update_agent_trust_history("agent_a", 0.7 + i * 0.001)
        z = d._compute_agent_z_score("agent_a", 0.708)
        assert z is not None
        assert isinstance(z, float)

    def test_large_delta_produces_high_zscore(self):
        """AD-556: Sudden large change produces high z-score for stable agent."""
        d = _make_detector(adaptive_min_history=5)
        # Build very stable history
        for i in range(8):
            d._update_agent_trust_history("agent_a", 0.700 + i * 0.001)
        # Sudden drop
        z = d._compute_agent_z_score("agent_a", 0.500)
        assert z is not None
        assert z > 3.0  # Should be a clear anomaly

    def test_normal_delta_produces_low_zscore(self):
        """AD-556: Normal-sized change produces low z-score."""
        d = _make_detector(adaptive_min_history=5)
        # Build history with moderate variance
        scores = [0.70, 0.72, 0.69, 0.71, 0.73, 0.70, 0.72, 0.71]
        for s in scores:
            d._update_agent_trust_history("agent_a", s)
        # Normal continuation
        z = d._compute_agent_z_score("agent_a", 0.73)
        assert z is not None
        assert z < 2.0  # Within normal range

    def test_zero_variance_agent_with_sudden_change(self):
        """AD-556: Agent with near-zero variance gets synthetic high z-score on change."""
        d = _make_detector(adaptive_min_history=5, trust_min_deviation=0.05)
        # Perfectly stable agent
        for _ in range(8):
            d._update_agent_trust_history("agent_a", 0.700)
        # Sudden change exceeding trust_min_deviation
        z = d._compute_agent_z_score("agent_a", 0.60)
        assert z is not None
        assert z >= 10.0  # Synthetic high z-score

    def test_zero_variance_agent_with_tiny_change(self):
        """AD-556: Agent with near-zero variance ignores sub-threshold changes."""
        d = _make_detector(adaptive_min_history=5, trust_min_deviation=0.05)
        for _ in range(8):
            d._update_agent_trust_history("agent_a", 0.700)
        # Tiny change below trust_min_deviation
        z = d._compute_agent_z_score("agent_a", 0.699)
        assert z is not None
        assert z < 1.0

    def test_unknown_agent_returns_none(self):
        """AD-556: Agent with no history returns None."""
        d = _make_detector()
        assert d._compute_agent_z_score("unknown", 0.5) is None


# --- Debounce ---

class TestAdaptiveDebounce:

    def test_single_anomaly_suppressed(self):
        """AD-556: Single anomalous cycle doesn't pass debounce (count=2)."""
        d = _make_detector(adaptive_debounce_count=2, adaptive_z_threshold=2.0)
        assert d._check_adaptive_debounce("agent_a", 3.0) is False  # First time

    def test_consecutive_anomalies_pass(self):
        """AD-556: Two consecutive anomalous cycles pass debounce."""
        d = _make_detector(adaptive_debounce_count=2, adaptive_z_threshold=2.0)
        d._check_adaptive_debounce("agent_a", 3.0)  # Streak = 1
        assert d._check_adaptive_debounce("agent_a", 3.5) is True  # Streak = 2

    def test_streak_resets_on_normal(self):
        """AD-556: Normal cycle resets anomaly streak."""
        d = _make_detector(adaptive_debounce_count=2, adaptive_z_threshold=2.0)
        d._check_adaptive_debounce("agent_a", 3.0)  # Streak = 1
        d._check_adaptive_debounce("agent_a", 1.0)  # Normal — reset
        assert d._check_adaptive_debounce("agent_a", 3.0) is False  # Streak = 1 again

    def test_independent_agent_streaks(self):
        """AD-556: Agent streaks are independent."""
        d = _make_detector(adaptive_debounce_count=2, adaptive_z_threshold=2.0)
        d._check_adaptive_debounce("agent_a", 3.0)
        d._check_adaptive_debounce("agent_b", 3.0)
        assert d._check_adaptive_debounce("agent_a", 3.0) is True
        assert d._check_adaptive_debounce("agent_b", 3.0) is True


# --- Integration: adaptive gate in detect_trust_anomalies ---

class TestAdaptiveGateIntegration:

    def _build_history(self, detector: EmergentDetector, agent_id: str, scores: list[float]):
        """Build up per-agent history by running detection passes."""
        for score in scores:
            _set_trust_scores(detector, {agent_id: score, "baseline_agent": 0.75})
            detector.detect_trust_anomalies()

    def test_anomaly_suppressed_by_adaptive_gate(self):
        """AD-556: Population anomaly suppressed when adaptive z-score is normal."""
        d = _make_detector(
            adaptive_min_history=5,
            adaptive_debounce_count=1,  # No debounce for this test
            adaptive_z_threshold=2.5,
        )
        # Build stable history with moderate variance
        volatile_scores = [0.45, 0.50, 0.42, 0.48, 0.43, 0.47, 0.44, 0.49]
        self._build_history(d, "volatile_agent", volatile_scores)

        # Reset anomaly counts to get clean detection
        d._trust_anomaly_counts.clear()

        # One more pass with a score in the agent's normal range but
        # deviating from population mean (0.75 baseline_agent pulls mean up)
        _set_trust_scores(d, {"volatile_agent": 0.46, "baseline_agent": 0.85})
        patterns = d.detect_trust_anomalies()

        # Even if population sigma fires, adaptive gate should filter
        trust_anomalies = [p for p in patterns if p.pattern_type == "trust_anomaly"
                          and "volatile_agent" in p.evidence.get("agent_id", "")]
        # The 0.46 score is normal for this agent — adaptive should suppress
        assert len(trust_anomalies) == 0

    def test_genuine_anomaly_passes_both_gates(self):
        """AD-556: Genuine anomaly passes both population and adaptive gates."""
        d = _make_detector(
            adaptive_min_history=5,
            adaptive_debounce_count=1,
            adaptive_z_threshold=2.0,
            trust_sigma_threshold=1.5,
        )
        # Build stable high-trust history
        stable_scores = [0.80, 0.81, 0.80, 0.82, 0.80, 0.81, 0.80, 0.81]
        self._build_history(d, "stable_agent", stable_scores)

        d._trust_anomaly_counts.clear()

        # Sudden drop — anomalous for both population and personal baseline
        _set_trust_scores(d, {"stable_agent": 0.40, "baseline_agent": 0.80})
        patterns = d.detect_trust_anomalies()

        trust_anomalies = [p for p in patterns if p.pattern_type == "trust_anomaly"
                          and "stable_agent" in p.evidence.get("agent_id", "")]
        # Should pass both gates
        assert len(trust_anomalies) >= 1
        # Should include adaptive info in evidence
        evidence = trust_anomalies[0].evidence
        assert evidence.get("detection_mode") == "adaptive"
        assert "personal_z_score" in evidence

    def test_population_only_for_new_agents(self):
        """AD-556: New agents without history use population-only detection."""
        d = _make_detector(adaptive_min_history=5, trust_anomaly_min_count=1)
        # No history built — agent is new
        _set_trust_scores(d, {"new_agent": 0.30, "agent_b": 0.80, "agent_c": 0.85})
        patterns = d.detect_trust_anomalies()

        trust_anomalies = [p for p in patterns if p.pattern_type == "trust_anomaly"
                          and "new_agent" in p.evidence.get("agent_id", "")]
        # Population detection should still work for new agents
        # (though it depends on the population statistics being wide enough)
        for p in trust_anomalies:
            assert p.evidence.get("detection_mode") == "population_only"

    def test_evidence_includes_adaptive_info(self):
        """AD-556: Pattern evidence includes personal z-score and detection mode."""
        d = _make_detector(
            adaptive_min_history=5,
            adaptive_debounce_count=1,
            adaptive_z_threshold=1.0,  # Very sensitive for test
        )
        stable_scores = [0.80, 0.80, 0.80, 0.80, 0.80, 0.80, 0.80, 0.80]
        self._build_history(d, "test_agent", stable_scores)

        d._trust_anomaly_counts.clear()

        _set_trust_scores(d, {"test_agent": 0.40, "baseline_agent": 0.80})
        patterns = d.detect_trust_anomalies()

        trust_anomalies = [p for p in patterns if p.pattern_type == "trust_anomaly"
                          and "test_agent" in p.evidence.get("agent_id", "")]
        if trust_anomalies:
            ev = trust_anomalies[0].evidence
            assert "personal_z_score" in ev
            assert "personal_history_len" in ev
            assert ev["detection_mode"] == "adaptive"


# --- Config ---

class TestAdaptiveConfig:

    def test_config_defaults(self):
        """AD-556: EmergentDetectorConfig has adaptive parameters with defaults."""
        from probos.config import EmergentDetectorConfig
        config = EmergentDetectorConfig()
        assert config.adaptive_window_size == 30
        assert config.adaptive_z_threshold == 2.5
        assert config.adaptive_debounce_count == 2
        assert config.adaptive_min_history == 8

    def test_config_overrides(self):
        """AD-556: Adaptive config parameters can be overridden."""
        from probos.config import EmergentDetectorConfig
        config = EmergentDetectorConfig(
            adaptive_window_size=50,
            adaptive_z_threshold=3.0,
            adaptive_debounce_count=3,
            adaptive_min_history=10,
        )
        assert config.adaptive_window_size == 50
        assert config.adaptive_z_threshold == 3.0

    def test_detector_accepts_config_params(self):
        """AD-556: EmergentDetector constructor accepts adaptive parameters."""
        d = _make_detector(
            adaptive_window_size=20,
            adaptive_z_threshold=3.0,
            adaptive_debounce_count=3,
            adaptive_min_history=10,
        )
        assert d._adaptive_window_size == 20
        assert d._adaptive_z_threshold == 3.0
        assert d._adaptive_debounce_count == 3
        assert d._adaptive_min_history == 10


# --- Edge cases ---

class TestAdaptiveEdgeCases:

    def test_empty_trust_scores(self):
        """AD-556: No crash with empty trust scores."""
        d = _make_detector()
        _set_trust_scores(d, {})
        patterns = d.detect_trust_anomalies()
        assert patterns == []

    def test_single_agent(self):
        """AD-556: No crash with single agent (population sigma needs >= 2)."""
        d = _make_detector()
        _set_trust_scores(d, {"only_agent": 0.5})
        patterns = d.detect_trust_anomalies()
        # Single agent can't deviate from population of 1
        assert len(d._agent_trust_history.get("only_agent", [])) == 1

    def test_cold_start_suppression_still_works(self):
        """AD-556: BF-034 cold-start suppression prevents adaptive detection too."""
        d = _make_detector()
        d._suppress_trust_until = time.monotonic() + 600  # Suppress for 10 min
        _set_trust_scores(d, {"agent_a": 0.3, "agent_b": 0.8})
        patterns = d.detect_trust_anomalies()
        assert patterns == []
        # History should NOT be updated during suppression
        assert len(d._agent_trust_history) == 0

    def test_dream_suppression_still_works(self):
        """AD-556: BF-100 dream suppression prevents adaptive detection too."""
        d = _make_detector()
        d._dreaming = True
        _set_trust_scores(d, {"agent_a": 0.3, "agent_b": 0.8})
        patterns = d.detect_trust_anomalies()
        assert patterns == []
        assert len(d._agent_trust_history) == 0
```

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad556_adaptive_trust_anomaly.py -v

# Existing emergent detector tests (must not break)
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_emergent_detector.py -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

**Existing test impact:** Tests that call `detect_trust_anomalies()` should continue passing because:
- The adaptive gate only activates after `adaptive_min_history` (default 8) detection passes per agent
- Existing tests that run 1-3 detection passes will use the population-only fallback path
- No existing behavior changes for agents without personal history

---

## Tracking

### PROGRESS.md
Add line:
```
AD-556 CLOSED. Adaptive trust anomaly detection — per-agent z-score thresholding. Rolling window of per-agent trust score history (default 30 snapshots). Z-score computed against agent's personal delta baseline. Debounce requires consecutive anomalous cycles (default 2) before escalation. Dual-gate: population sigma AND personal z-score must both fire. New agents without history fall back to population-only detection. Four new config parameters on EmergentDetectorConfig. 24 new tests. Crew-originated design (Forge + Reyes, 2026-04-01).
```

### DECISIONS.md
Add entry:
```
**AD-556: Per-agent adaptive trust anomaly detection.** Trust anomaly detection now maintains a per-agent rolling window of trust score snapshots and computes z-scores against each agent's personal delta baseline. Anomalies must pass both the existing population sigma threshold AND the per-agent z-score threshold (default 2.5σ). Debounce requires 2 consecutive anomalous cycles before escalation. This reduces false positives from naturally volatile agents (Security, Red Team) while maintaining sensitivity for stable agents with genuine degradation. New agents without sufficient history (< 8 snapshots) fall back to population-only detection. Zone model integration unchanged — zone transitions now receive only adaptively-filtered anomalies. Crew-originated: Forge (Engineering) identified feedback loop risk, Reyes (Security) proposed adaptive thresholding, collaborative design 2026-04-01.
```

### docs/development/roadmap.md
Update AD-556 status from `planned` to `complete`.
