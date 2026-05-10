"""AD-722f: per-agent avatar-telemetry sampling state machine tests."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from probos.avatars.sampling_state import (
    TIER_HIGH,
    TIER_LOW,
    TIER_NORMAL,
    AvatarSamplingStateMachine,
)
from probos.config import AvatarTelemetryConfig, SamplingRatesConfig


# ── Construction & defaults ─────────────────────────────────────────────


def test_state_machine_defaults_to_low_for_unknown_agent():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    assert sm.current_tier("agent-007") == TIER_LOW
    assert sm.current_rate_ms("agent-007") == 10000


def test_default_rates_match_addendum_sketch():
    rates = SamplingRatesConfig()
    assert rates.high_ms == 250
    assert rates.normal_ms == 2000
    assert rates.low_ms == 10000


def test_custom_rates_propagate_through_state_machine():
    rates = SamplingRatesConfig(high_ms=500, normal_ms=3000, low_ms=15000)
    sm = AvatarSamplingStateMachine(rates=rates)
    sm.enter_dm("a")
    assert sm.current_rate_ms("a") == 500
    sm.exit_dm("a")
    sm.enter_chain("a")
    assert sm.current_rate_ms("a") == 3000


# ── Tier transitions ────────────────────────────────────────────────────


def test_dm_enter_promotes_to_high():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_dm("a")
    assert sm.current_tier("a") == TIER_HIGH
    sm.exit_dm("a")
    assert sm.current_tier("a") == TIER_LOW


def test_chain_enter_promotes_to_normal():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_chain("a")
    assert sm.current_tier("a") == TIER_NORMAL
    sm.exit_chain("a")
    assert sm.current_tier("a") == TIER_LOW


def test_concurrent_dm_and_chain_resolve_to_high():
    """DM > chain by priority. Chain entered first then DM still resolves HIGH."""
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_chain("a")
    assert sm.current_tier("a") == TIER_NORMAL
    sm.enter_dm("a")
    assert sm.current_tier("a") == TIER_HIGH
    sm.exit_dm("a")
    # Chain still active → revert to NORMAL.
    assert sm.current_tier("a") == TIER_NORMAL
    sm.exit_chain("a")
    assert sm.current_tier("a") == TIER_LOW


def test_refcount_handles_concurrent_dm_to_same_agent():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_dm("a")
    sm.enter_dm("a")
    sm.exit_dm("a")
    # Still one DM active.
    assert sm.current_tier("a") == TIER_HIGH
    sm.exit_dm("a")
    assert sm.current_tier("a") == TIER_LOW


def test_spurious_exit_clamps_to_zero(caplog):
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    with caplog.at_level("WARNING"):
        sm.exit_dm("a")
    assert sm.current_tier("a") == TIER_LOW
    assert any("spurious exit_dm" in r.message for r in caplog.records)
    # Should not poison subsequent enters.
    sm.enter_dm("a")
    assert sm.current_tier("a") == TIER_HIGH


def test_spurious_exit_chain_clamps_to_zero(caplog):
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    with caplog.at_level("WARNING"):
        sm.exit_chain("a")
    assert sm.current_tier("a") == TIER_LOW
    assert any("spurious exit_chain" in r.message for r in caplog.records)


# ── Per-agent isolation ─────────────────────────────────────────────────


def test_per_agent_state_does_not_leak():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_dm("a")
    assert sm.current_tier("a") == TIER_HIGH
    assert sm.current_tier("b") == TIER_LOW


# ── Config integration ──────────────────────────────────────────────────


def test_avatar_telemetry_config_includes_sampling_rates():
    cfg = AvatarTelemetryConfig()
    assert isinstance(cfg.sampling_rates, SamplingRatesConfig)
    assert cfg.sampling_rates.high_ms == 250


def test_sampling_rates_validator_rejects_below_floor():
    with pytest.raises(ValueError, match="must be >= 250"):
        SamplingRatesConfig(high_ms=100)


def test_sampling_rates_validator_rejects_inverted_ordering():
    with pytest.raises(ValueError, match="high_ms <= normal_ms <= low_ms"):
        SamplingRatesConfig(high_ms=3000, normal_ms=500, low_ms=10000)


# ── No phantom WR API (per AD-722 addendum (h)) ─────────────────────────


def test_state_machine_does_not_expose_wr_methods():
    """AD-722 addendum (h): WR is peer communication, not Captain-facing
    self-presentation. The state machine MUST NOT expose enter_wr/exit_wr."""
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    assert not hasattr(sm, "enter_wr")
    assert not hasattr(sm, "exit_wr")


# ── Restart semantics (state is volatile by design) ─────────────────────


def test_fresh_instance_starts_low():
    """AD-722f: state is volatile. Restart resets all agents to LOW."""
    sm1 = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm1.enter_dm("a")
    sm1.enter_chain("b")
    # Simulate restart.
    sm2 = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    assert sm2.current_tier("a") == TIER_LOW
    assert sm2.current_tier("b") == TIER_LOW


# ── Snapshot-side integration (telemetry.py) ────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_includes_sampling_rate_and_tier():
    """build_telemetry_snapshot populates sampling_rate_ms + sampling_tier."""
    from probos.avatars.telemetry import build_telemetry_snapshot

    runtime = MagicMock()
    runtime.avatar_sampling_state = AvatarSamplingStateMachine(
        rates=SamplingRatesConfig(),
    )
    runtime.avatar_sampling_state.enter_dm("agent-007")

    # Minimal runtime shape — agent_not_found short-circuits, which is fine
    # because it still resolves sampling on the way out.
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = None

    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.sampling_tier == TIER_HIGH
    assert snap.sampling_rate_ms == 250
    body = snap.to_dict()
    assert body["sampling_rate_ms"] == 250
    assert body["sampling_tier"] == "high"


@pytest.mark.asyncio
async def test_snapshot_degrades_gracefully_when_state_missing():
    """Tier-2: missing avatar_sampling_state → LOW fallback + degraded reason."""
    from probos.avatars.telemetry import build_telemetry_snapshot

    runtime = MagicMock(spec=[])  # no avatar_sampling_state attribute
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = None

    snap = await build_telemetry_snapshot("agent-missing", runtime)
    assert snap.sampling_tier == TIER_LOW
    assert "avatar_sampling_state_unavailable" in snap.degraded_reasons
