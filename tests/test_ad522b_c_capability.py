"""AD-522b + AD-522c: Cp/Cpk indices + graduated-response zone mapping."""
from __future__ import annotations

from probos.cognitive.spc.calibration_profile import (
    AgentCalibrationProfile,
    graduated_response_for_value,
    spc_zone_to_response_color,
)


def _profile_with(values: list[float]) -> AgentCalibrationProfile:
    p = AgentCalibrationProfile(agent_id="alpha", sample_window=100)
    for v in values:
        p.record_observation(v)
    return p


# ---------------------------------------------------------------------------
# AD-522b
# ---------------------------------------------------------------------------


def test_cp_returns_none_with_zero_stdev() -> None:
    p = _profile_with([5.0, 5.0, 5.0, 5.0])
    assert p.cp(lower_spec=0, upper_spec=10) is None


def test_cp_returns_none_with_too_few_samples() -> None:
    p = _profile_with([5.0])
    assert p.cp(lower_spec=0, upper_spec=10) is None


def test_cp_basic_computation() -> None:
    # values clustered at 5 with stdev ~ 1; spec range 0..10
    p = _profile_with([4, 5, 6, 5, 4, 6, 5, 5])
    cp = p.cp(lower_spec=0, upper_spec=10)
    assert cp is not None
    assert cp > 0


def test_cpk_smaller_when_off_center() -> None:
    # Center at 8 inside spec 0..10 — closer to upper limit, so cpk < cp
    p = _profile_with([7, 8, 9, 8, 7, 9, 8, 8])
    cp = p.cp(lower_spec=0, upper_spec=10)
    cpk = p.cpk(lower_spec=0, upper_spec=10)
    assert cp is not None and cpk is not None
    assert cpk < cp


def test_cpk_invalid_spec_range_returns_none() -> None:
    p = _profile_with([5, 6, 4, 5])
    assert p.cpk(lower_spec=10, upper_spec=10) is None
    assert p.cpk(lower_spec=10, upper_spec=5) is None


def test_capability_summary_classification() -> None:
    # Tight distribution -> capable or excellent
    p = _profile_with([5.0, 5.1, 4.9, 5.05, 4.95, 5.0, 5.0, 5.02, 4.98, 5.0])
    summary = p.capability_summary(lower_spec=0, upper_spec=10)
    assert summary["classification"] in {"excellent", "capable", "marginal"}
    assert summary["cp"] is not None
    assert summary["cpk"] is not None


def test_capability_summary_unknown_when_insufficient() -> None:
    p = _profile_with([5.0])
    summary = p.capability_summary(lower_spec=0, upper_spec=10)
    assert summary["classification"] == "unknown"


# ---------------------------------------------------------------------------
# AD-522c
# ---------------------------------------------------------------------------


def test_zone_color_mapping() -> None:
    assert spc_zone_to_response_color("beyond_3sigma") == "red"
    assert spc_zone_to_response_color("zone_a") == "amber"
    assert spc_zone_to_response_color("zone_b") == "green"
    assert spc_zone_to_response_color("zone_c") == "green"
    assert spc_zone_to_response_color("unknown") == "green"


def test_graduated_response_helper_returns_zone_and_color() -> None:
    p = _profile_with([5.0] * 10 + [5.5, 4.5])
    result = graduated_response_for_value(p, 5.0)
    assert "zone" in result and "color" in result


def test_graduated_response_red_for_extreme_value() -> None:
    p = _profile_with([5.0, 5.05, 4.95] * 5)  # tight stdev
    result = graduated_response_for_value(p, 100.0)
    assert result["color"] == "red"
