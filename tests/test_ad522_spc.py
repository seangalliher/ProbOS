"""AD-522 v1 — Statistical Process Control (calibration profile + WE rules)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.cognitive.spc import (
    AgentCalibrationProfile,
    RuleViolation,
    SPCCalibrationStore,
    WesternElectricRules,
)
from probos.config import SPCConfig
from probos.events import EventType
from probos.startup.finalize import _wire_spc_calibration


# ---------------------------------------------------------------------------
# Section 0 — EventType
# ---------------------------------------------------------------------------


def test_event_type_spc_rule_violated_exists() -> None:
    assert EventType.SPC_RULE_VIOLATED.value == "spc_rule_violated"


# ---------------------------------------------------------------------------
# Section 5 — Pydantic config
# ---------------------------------------------------------------------------


def test_spc_config_defaults() -> None:
    cfg = SPCConfig()
    assert cfg.enabled is True
    assert cfg.sample_window == 100


# ---------------------------------------------------------------------------
# Section 2 — AgentCalibrationProfile
# ---------------------------------------------------------------------------


def test_calibration_profile_initial_state() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    assert p.sample_count == 0
    assert p.mean == 0.0
    assert p.stdev == 0.0
    assert p.ucl == 0.0
    assert p.lcl == 0.0


def test_calibration_profile_record_observation_appends() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    p.record_observation(1.0)
    p.record_observation(2.0)
    assert p.sample_count == 2


def test_calibration_profile_bounded_window_evicts_oldest() -> None:
    p = AgentCalibrationProfile(agent_id="a", sample_window=3)
    for v in [1.0, 2.0, 3.0, 4.0]:
        p.record_observation(v)
    assert p.sample_count == 3
    assert p.recent_values(3) == (2.0, 3.0, 4.0)


def test_calibration_profile_mean_stdev_ucl_lcl() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
        p.record_observation(v)
    assert p.mean == pytest.approx(3.0)
    # Sample stdev of [1..5] is sqrt(2.5) ≈ 1.5811
    assert p.stdev == pytest.approx(1.5811388, rel=1e-5)
    assert p.ucl == pytest.approx(p.mean + 3.0 * p.stdev)
    assert p.lcl == pytest.approx(p.mean - 3.0 * p.stdev)


def test_calibration_profile_zone_returns_unknown_below_two_samples() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    assert p.zone(5.0) == "unknown"
    p.record_observation(1.0)
    assert p.zone(5.0) == "unknown"


def test_calibration_profile_zone_classification_correct() -> None:
    # Mean=10, stdev=1 (approx) — set values that produce stdev≈1
    p = AgentCalibrationProfile(agent_id="a")
    for v in [9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0]:
        p.record_observation(v)
    mean = p.mean
    stdev = p.stdev
    assert stdev > 0.0
    assert p.zone(mean) == "zone_c"  # within 1σ
    assert p.zone(mean + 1.5 * stdev) == "zone_b"  # 1-2σ
    assert p.zone(mean + 2.5 * stdev) == "zone_a"  # 2-3σ
    assert p.zone(mean + 5.0 * stdev) == "beyond_3sigma"


def test_calibration_profile_recent_values_returns_n() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
        p.record_observation(v)
    assert p.recent_values(3) == (3.0, 4.0, 5.0)
    assert p.recent_values(0) == ()
    # Empty profile
    p2 = AgentCalibrationProfile(agent_id="b")
    assert p2.recent_values(5) == ()


# ---------------------------------------------------------------------------
# Section 3 — WesternElectricRules
# ---------------------------------------------------------------------------


def test_western_electric_rules_no_violations_when_insufficient_samples() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    for v in [1.0, 2.0, 3.0]:
        p.record_observation(v)
    assert WesternElectricRules.check(p) == []


def test_western_electric_rules_no_violations_when_zero_stdev() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    for _ in range(10):
        p.record_observation(5.0)
    assert p.stdev == 0.0
    assert WesternElectricRules.check(p) == []


def test_western_electric_rules_rule_1_beyond_3sigma() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    # 50 in-control samples around mean=10, stdev ~ 1
    for v in [9.0, 10.0, 11.0] * 17:
        p.record_observation(v)
    # Outlier far beyond 3σ (mean stays ~10, stdev stays ~0.82)
    p.record_observation(20.0)
    violations = WesternElectricRules.check(p)
    assert any(v.rule_name == "rule_1_beyond_3sigma" for v in violations)


def test_western_electric_rules_rule_2_two_of_three_zone_a() -> None:
    # Large stable baseline so two outliers don't dominate stats
    p = AgentCalibrationProfile(agent_id="a")
    for v in [9.0, 10.0, 11.0] * 17:
        p.record_observation(v)
    # Two points beyond +2σ within last 3 (mean ~10, stdev ~0.82 → +2σ ~11.6)
    p.record_observation(13.0)
    p.record_observation(13.0)
    violations = WesternElectricRules.check(p)
    assert any(v.rule_name == "rule_2_two_of_three_zone_a" for v in violations)


def test_western_electric_rules_rule_3_four_of_five_zone_b() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    # Large stable baseline (mean ~10, stdev ~0.82)
    for v in [9.0, 10.0, 11.0] * 17:
        p.record_observation(v)
    # 4 of next 5 above +1σ (~+0.82)
    for v in [12.0, 12.0, 12.0, 10.0, 12.0]:
        p.record_observation(v)
    violations = WesternElectricRules.check(p)
    assert any(v.rule_name == "rule_3_four_of_five_zone_b" for v in violations)


def test_western_electric_rules_rule_4_eight_consecutive_same_side() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    # Mixed first to get a centered mean, then 8 above
    for v in [9.0, 11.0, 9.0, 11.0]:
        p.record_observation(v)
    for _ in range(8):
        p.record_observation(11.5)
    violations = WesternElectricRules.check(p)
    assert any(v.rule_name == "rule_4_eight_consecutive_same_side" for v in violations)


def test_western_electric_rules_in_control_signal_yields_no_violations() -> None:
    p = AgentCalibrationProfile(agent_id="a")
    # Stable alternating pattern within ±0.5σ
    for v in [10.0, 10.2, 9.8, 10.1, 9.9, 10.3, 9.7, 10.0, 10.1, 9.9, 10.2, 9.8]:
        p.record_observation(v)
    violations = WesternElectricRules.check(p)
    assert violations == []


# ---------------------------------------------------------------------------
# Section 4 — SPCCalibrationStore
# ---------------------------------------------------------------------------


def test_spc_calibration_store_get_or_create_idempotent() -> None:
    store = SPCCalibrationStore(runtime=SimpleNamespace())
    p1 = store.get_or_create("agent-1")
    p2 = store.get_or_create("agent-1")
    assert p1 is p2
    assert p1.agent_id == "agent-1"


def test_spc_calibration_store_check_rules_emits_event_per_violation() -> None:
    emitted: list[tuple[EventType, dict]] = []

    def emit(event_type: EventType, data: dict) -> None:
        emitted.append((event_type, data))

    store = SPCCalibrationStore(runtime=SimpleNamespace())
    store.emit_event = emit

    # Build profile that violates rule 4 (8 consecutive above)
    for v in [9.0, 11.0, 9.0, 11.0]:
        store.record_observation("a", v)
    for _ in range(8):
        store.record_observation("a", 11.5)

    violations = store.check_rules("a")
    assert len(violations) >= 1
    assert all(et == EventType.SPC_RULE_VIOLATED for et, _ in emitted)
    assert len(emitted) == len(violations)
    assert emitted[0][1]["agent_id"] == "a"
    assert "rule_name" in emitted[0][1]

    # check_rules on unknown agent returns empty without emit
    emitted.clear()
    assert store.check_rules("ghost") == []
    assert emitted == []


def test_spc_calibration_store_all_profiles_returns_tuple() -> None:
    store = SPCCalibrationStore(runtime=SimpleNamespace())
    store.get_or_create("a")
    store.get_or_create("b")
    profiles = store.all_profiles()
    assert isinstance(profiles, tuple)
    assert {p.agent_id for p in profiles} == {"a", "b"}


# ---------------------------------------------------------------------------
# Section 6 — Runtime wiring
# ---------------------------------------------------------------------------


def test_runtime_attribute_set_when_enabled() -> None:
    runtime = MagicMock(spec=["emit_event", "spc_calibration_store"])
    config = SimpleNamespace(spc=SPCConfig(enabled=True))
    wired = _wire_spc_calibration(runtime=runtime, config=config)
    assert wired is True
    assert isinstance(runtime.spc_calibration_store, SPCCalibrationStore)


def test_runtime_attribute_not_set_when_disabled() -> None:
    runtime = SimpleNamespace(emit_event=lambda *a, **k: None)
    config = SimpleNamespace(spc=SPCConfig(enabled=False))
    wired = _wire_spc_calibration(runtime=runtime, config=config)
    assert wired is False
    assert not hasattr(runtime, "spc_calibration_store")
