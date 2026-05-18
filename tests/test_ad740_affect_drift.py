"""Tests for AD-740: affect-vs-intent drift trend summariser.

Real ``SystemConfig()`` per BF-287. Hand-rolled ``_FakeRuntime`` and
``_FakeEntry`` dataclasses to mirror the AD-722a-5 ring buffer shape
without MagicMock at the substrate boundary (BF-286/287).
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from typing import Any

import pytest

from probos.avatars.affect_drift import get_affect_drift
from probos.config import SystemConfig


@dataclass
class _FakeResult:
    match_score: float


@dataclass
class _FakeEntry:
    result: _FakeResult


@dataclass
class _FakeRuntime:
    config: Any
    divergence_history: Any  # dict[str, deque] | None | object


def _runtime_with_config(history: Any = None) -> _FakeRuntime:
    return _FakeRuntime(config=SystemConfig(), divergence_history=history)


def _make_bucket(scores: list[float]) -> collections.deque[_FakeEntry]:
    return collections.deque(_FakeEntry(_FakeResult(s)) for s in scores)


def test_no_runtime_history_returns_insufficient_data() -> None:
    runtime = _FakeRuntime(config=SystemConfig(), divergence_history=None)
    result = get_affect_drift(runtime, "agent-x")
    assert result == {"insufficient_data": True, "samples": 0}


def test_missing_agent_bucket_returns_insufficient_data() -> None:
    runtime = _runtime_with_config({"other-agent": _make_bucket([0.9, 0.8])})
    result = get_affect_drift(runtime, "agent-x")
    assert result == {"insufficient_data": True, "samples": 0}


def test_single_entry_returns_insufficient_data() -> None:
    runtime = _runtime_with_config({"agent-x": _make_bucket([0.9])})
    result = get_affect_drift(runtime, "agent-x")
    assert result == {"insufficient_data": True, "samples": 1}


def test_steady_high_score_returns_zero_below_zero_streak() -> None:
    runtime = _runtime_with_config({"agent-x": _make_bucket([0.95] * 8)})
    result = get_affect_drift(runtime, "agent-x")
    assert result["samples"] == 8
    assert result["below_threshold_count"] == 0
    assert result["longest_divergent_streak"] == 0
    assert result["mean_match_score"] == pytest.approx(0.95)
    assert result["threshold"] == pytest.approx(0.7)
    assert result["window"] == 8


def test_injected_divergent_streak_returns_expected_streak_length() -> None:
    # Scores: [0.9, 0.9, 0.4, 0.3, 0.2, 0.9, 0.4, 0.3]
    # Below threshold 0.7: indices 2,3,4 (streak 3) then 6,7 (streak 2).
    scores = [0.9, 0.9, 0.4, 0.3, 0.2, 0.9, 0.4, 0.3]
    runtime = _runtime_with_config({"agent-x": _make_bucket(scores)})
    result = get_affect_drift(runtime, "agent-x")
    assert result["samples"] == 8
    assert result["below_threshold_count"] == 5
    assert result["longest_divergent_streak"] == 3


def test_window_smaller_than_bucket_only_reads_last_n() -> None:
    # First 12 entries high, last 4 low. window=4 should see all-low tail.
    scores = [0.95] * 12 + [0.2, 0.2, 0.2, 0.2]
    runtime = _runtime_with_config({"agent-x": _make_bucket(scores)})
    result = get_affect_drift(runtime, "agent-x", window=4)
    assert result["samples"] == 4
    assert result["below_threshold_count"] == 4
    assert result["longest_divergent_streak"] == 4
    assert result["mean_match_score"] == pytest.approx(0.2)


def test_threshold_override_via_kwarg() -> None:
    scores = [0.85, 0.6, 0.55, 0.65, 0.4]
    runtime = _runtime_with_config({"agent-x": _make_bucket(scores)})
    low_result = get_affect_drift(runtime, "agent-x", threshold=0.5)
    high_result = get_affect_drift(runtime, "agent-x", threshold=0.9)
    assert low_result["below_threshold_count"] == 1  # only 0.4
    assert high_result["below_threshold_count"] == 5  # all below 0.9


def test_config_defaults_used_when_kwargs_omitted() -> None:
    cfg = SystemConfig()
    assert cfg.avatars.affect_drift_default_window == 8
    assert cfg.avatars.affect_drift_threshold == pytest.approx(0.7)

    runtime = _runtime_with_config({"agent-x": _make_bucket([0.95] * 3)})
    runtime.config = cfg
    result = get_affect_drift(runtime, "agent-x")
    assert result["window"] == 8
    assert result["threshold"] == pytest.approx(0.7)
    assert result["samples"] == 3
