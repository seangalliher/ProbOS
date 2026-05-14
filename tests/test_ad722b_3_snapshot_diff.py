"""AD-722b-3: boundary tests for snapshot diff."""
from __future__ import annotations

from probos.avatars.snapshot_diff import DEFAULT_SKIP_FIELDS, compute_diff


def _base_snap() -> dict[str, object]:
    return {
        "agent_id": "ezri",
        "expression_resting": None,
        "current_signals": {
            "trust_delta": 0.0,
            "load": 0.0,
            "working_state": "idle",
            "tier3_alert": False,
        },
        "mouth_active": False,
        "applied_modulation": None,
        "dsl_summary": None,
        "last_observed_at": 1000.0,
        "degraded_reasons": [],
        "sampling_rate_ms": 2000,
        "sampling_tier": "normal",
    }


def test_diff_first_frame_returns_all_fields_minus_skip() -> None:
    snap = _base_snap()
    diff = compute_diff(None, snap)
    assert "last_observed_at" not in diff
    expected = set(snap.keys()) - DEFAULT_SKIP_FIELDS
    assert set(diff.keys()) == expected


def test_diff_identical_returns_empty() -> None:
    snap = _base_snap()
    diff = compute_diff(dict(snap), snap)
    assert diff == {}


def test_diff_numeric_below_threshold_skipped() -> None:
    prev = {"x": 1.0}
    nxt = {"x": 1.02}
    assert compute_diff(prev, nxt, threshold=0.05) == {}


def test_diff_numeric_above_threshold_included() -> None:
    prev = {"x": 1.0}
    nxt = {"x": 1.10}
    diff = compute_diff(prev, nxt, threshold=0.05)
    assert diff == {"x": 1.10}


def test_diff_nested_dict_recurses_one_level() -> None:
    prev = _base_snap()
    nxt = _base_snap()
    nxt["current_signals"] = {  # type: ignore[assignment]
        "trust_delta": 0.5,  # large change
        "load": 0.0,
        "working_state": "idle",
        "tier3_alert": False,
    }
    diff = compute_diff(prev, nxt)
    assert "current_signals" in diff


def test_diff_skip_fields_excluded_even_when_changed() -> None:
    prev = _base_snap()
    nxt = _base_snap()
    nxt["last_observed_at"] = 2000.0
    diff = compute_diff(prev, nxt)
    assert "last_observed_at" not in diff
    assert diff == {}
