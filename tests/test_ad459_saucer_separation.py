"""AD-459: Tests for Saucer Separation (Graceful Degradation)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.config import DegradationConfig
from probos.degradation.manager import DegradationManager, DegradationStatus
from probos.degradation.policy import SheddingPolicy, StressLevel
from probos.degradation.registry import (
    ServiceClassification,
    ServiceTier,
    ServiceTierRegistry,
)
from probos.events import EventType


# ---------------------------------------------------------------------------
# EventTypes & Config
# ---------------------------------------------------------------------------


def test_event_type_service_tier_degraded_exists() -> None:
    assert EventType.SERVICE_TIER_DEGRADED.value == "service_tier_degraded"


def test_event_type_service_tier_restored_exists() -> None:
    assert EventType.SERVICE_TIER_RESTORED.value == "service_tier_restored"


def test_degradation_config_defaults() -> None:
    """v1 has no operator-tunable fields beyond AD-459b transitional flag."""
    cfg = DegradationConfig()
    assert cfg.model_dump() == {"auto_pause_enabled": False}


# ---------------------------------------------------------------------------
# ServiceTierRegistry
# ---------------------------------------------------------------------------


def test_service_tier_registry_default_classifications() -> None:
    reg = ServiceTierRegistry()
    assert reg.get_tier("event_log") == ServiceTier.ESSENTIAL
    assert reg.get_tier("dream_scheduler") == ServiceTier.COGNITIVE
    assert reg.get_tier("red_team_lead") == ServiceTier.NON_ESSENTIAL


def test_service_tier_registry_register_extends_and_preserves_seeds() -> None:
    reg = ServiceTierRegistry()
    reg.register(ServiceClassification("custom_service", ServiceTier.COGNITIVE, "x"))
    # New entry present
    assert reg.get_tier("custom_service") == ServiceTier.COGNITIVE
    # Existing seed entries still present
    assert reg.get_tier("event_log") == ServiceTier.ESSENTIAL
    assert reg.get_tier("dream_scheduler") == ServiceTier.COGNITIVE


def test_service_tier_registry_services_in_tier_sorted() -> None:
    reg = ServiceTierRegistry()
    essential = reg.services_in_tier(ServiceTier.ESSENTIAL)
    # Sorted output for determinism
    assert essential == sorted(essential)
    assert "event_log" in essential
    assert "trust_network" in essential
    assert "registry" in essential
    assert "intent_bus" in essential
    assert "hebbian_router" in essential


# ---------------------------------------------------------------------------
# SheddingPolicy
# ---------------------------------------------------------------------------


def test_shedding_policy_normal_sheds_nothing() -> None:
    assert SheddingPolicy().shed_tiers(StressLevel.NORMAL) == frozenset()


def test_shedding_policy_elevated_sheds_non_essential() -> None:
    sheds = SheddingPolicy().shed_tiers(StressLevel.ELEVATED)
    assert sheds == frozenset({ServiceTier.NON_ESSENTIAL})


def test_shedding_policy_high_sheds_cognitive_and_non_essential() -> None:
    sheds = SheddingPolicy().shed_tiers(StressLevel.HIGH)
    assert sheds == frozenset({ServiceTier.NON_ESSENTIAL, ServiceTier.COGNITIVE})


def test_shedding_policy_critical_matches_high_in_v1() -> None:
    """v1: HIGH and CRITICAL share shed mask. AD-459b will differentiate."""
    high = SheddingPolicy().shed_tiers(StressLevel.HIGH)
    critical = SheddingPolicy().shed_tiers(StressLevel.CRITICAL)
    assert high == critical
    # ESSENTIAL is never in shed mask
    assert ServiceTier.ESSENTIAL not in critical


# ---------------------------------------------------------------------------
# DegradationManager
# ---------------------------------------------------------------------------


def _make_manager(emit: Any | None = None) -> DegradationManager:
    return DegradationManager(
        registry=ServiceTierRegistry(),
        policy=SheddingPolicy(),
        emit_event=emit,
    )


def test_degradation_manager_set_stress_level_emits_tier_degraded() -> None:
    emit = MagicMock()
    mgr = _make_manager(emit)
    mgr.set_stress_level(StressLevel.HIGH)
    # NORMAL -> HIGH adds NON_ESSENTIAL + COGNITIVE
    assert emit.call_count == 2
    event_types = {call.args[0] for call in emit.call_args_list}
    assert event_types == {EventType.SERVICE_TIER_DEGRADED}
    tiers_emitted = {call.args[1]["tier"] for call in emit.call_args_list}
    assert tiers_emitted == {"non_essential", "cognitive"}


def test_degradation_manager_restore_emits_tier_restored() -> None:
    emit = MagicMock()
    mgr = _make_manager(emit)
    mgr.set_stress_level(StressLevel.HIGH)
    emit.reset_mock()
    mgr.set_stress_level(StressLevel.NORMAL)
    assert emit.call_count == 2
    event_types = {call.args[0] for call in emit.call_args_list}
    assert event_types == {EventType.SERVICE_TIER_RESTORED}


def test_degradation_manager_is_shed_returns_correct_state() -> None:
    mgr = _make_manager()
    # NORMAL: nothing shed
    assert mgr.is_shed("dream_scheduler") is False
    # HIGH: dream_scheduler (COGNITIVE) is shed
    mgr.set_stress_level(StressLevel.HIGH)
    assert mgr.is_shed("dream_scheduler") is True
    assert mgr.is_shed("event_log") is False  # ESSENTIAL never shed
    # Unknown service: not shed
    assert mgr.is_shed("nonexistent") is False
