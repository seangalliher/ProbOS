"""AD-571b + AD-571c v1: Operational status + Hebbian scope reduction tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.config import OperationalStatusConfig
from probos.mesh.routing import (
    HebbianRouter,
    REL_AGENT,
    REL_INTENT,
    REL_SOCIAL,
)
from probos.substrate.agent_tier import AgentTier, AgentTierRegistry
from probos.substrate.operational_status import (
    OperationalStatus,
    OperationalStatusTracker,
    ReliabilityMetrics,
)


def _registry_with(**tiers: AgentTier) -> AgentTierRegistry:
    reg = AgentTierRegistry()
    for agent_id, tier in tiers.items():
        reg.register(agent_id, tier)
    return reg


# ---------------- AD-571b: OperationalStatus / Tracker ----------------


def test_status_enum_has_four_values() -> None:
    assert {s.value for s in OperationalStatus} == {
        "available", "degraded", "offline", "maintenance",
    }


def test_tracker_no_samples_returns_available() -> None:
    tracker = OperationalStatusTracker(OperationalStatusConfig())
    assert tracker.get_status("tool-1") is OperationalStatus.AVAILABLE
    assert tracker.get_metrics("tool-1") is None


def test_tracker_records_metrics_for_utility_agent() -> None:
    cfg = OperationalStatusConfig(sample_window_size=10)
    tracker = OperationalStatusTracker(cfg)
    for _ in range(5):
        tracker.record_call("tool-1", True, latency_ms=100.0)
    m = tracker.get_metrics("tool-1")
    assert isinstance(m, ReliabilityMetrics)
    assert m.sample_count == 5
    assert m.success_rate == 1.0
    assert m.p50_latency_ms == 100.0


def test_tracker_silently_ignores_crew_agent() -> None:
    cfg = OperationalStatusConfig()
    reg = _registry_with(crew_1=AgentTier.CREW)
    tracker = OperationalStatusTracker(cfg, tier_registry=reg)
    tracker.record_call("crew_1", True, latency_ms=50.0)
    assert tracker.get_metrics("crew_1") is None  # DLog #3


def test_tracker_status_degraded_on_low_success_rate() -> None:
    cfg = OperationalStatusConfig(available_success_rate=0.85)
    tracker = OperationalStatusTracker(cfg)
    for _ in range(8):
        tracker.record_call("tool-1", True, 10.0)
    for _ in range(2):
        tracker.record_call("tool-1", False, 10.0)
    # 8/10 = 0.8 < 0.85 → DEGRADED
    assert tracker.get_status("tool-1") is OperationalStatus.DEGRADED


def test_tracker_status_degraded_on_high_p95_latency() -> None:
    cfg = OperationalStatusConfig(degraded_p95_latency_ms=500.0)
    tracker = OperationalStatusTracker(cfg)
    for _ in range(19):
        tracker.record_call("tool-1", True, 100.0)
    tracker.record_call("tool-1", True, 5000.0)  # tail latency spike
    assert tracker.get_status("tool-1") is OperationalStatus.DEGRADED


def test_tracker_status_offline_on_consecutive_errors() -> None:
    cfg = OperationalStatusConfig(offline_consecutive_errors=3)
    tracker = OperationalStatusTracker(cfg)
    tracker.record_call("tool-1", True, 10.0)
    for _ in range(3):
        tracker.record_call("tool-1", False, 10.0)
    assert tracker.get_status("tool-1") is OperationalStatus.OFFLINE


def test_tracker_maintenance_is_sticky() -> None:
    tracker = OperationalStatusTracker(OperationalStatusConfig())
    tracker.set_maintenance("tool-1")
    for _ in range(50):
        tracker.record_call("tool-1", True, 10.0)
    assert tracker.get_status("tool-1") is OperationalStatus.MAINTENANCE
    tracker.clear_maintenance("tool-1")
    assert tracker.get_status("tool-1") is OperationalStatus.AVAILABLE


def test_tracker_late_bind_tier_registry() -> None:
    tracker = OperationalStatusTracker(OperationalStatusConfig())
    tracker.record_call("crew_1", True, 10.0)  # records before registry set
    assert tracker.get_metrics("crew_1") is not None
    tracker.set_tier_registry(_registry_with(crew_1=AgentTier.CREW))
    # New calls after registry set are no-op'd.
    tracker.record_call("crew_1", True, 10.0)
    m = tracker.get_metrics("crew_1")
    assert m is not None and m.sample_count == 1


# ---------------- AD-571c: per-rel_type decay + utility-utility prune ----------------


def test_router_social_decay_rate_falls_back_to_decay_rate() -> None:
    router = HebbianRouter(decay_rate=0.9)
    assert router.social_decay_rate == 0.9


def test_router_social_decay_rate_explicit_value() -> None:
    router = HebbianRouter(decay_rate=0.9, social_decay_rate=0.999)
    assert router.social_decay_rate == 0.999


def test_decay_all_uses_per_rel_type_rate() -> None:
    router = HebbianRouter(decay_rate=0.5, social_decay_rate=0.99, reward=0.1)
    router.record_interaction("a", "b", success=True, rel_type=REL_INTENT)
    router.record_interaction("a", "b", success=True, rel_type=REL_SOCIAL)
    intent_before = router.get_weight("a", "b", rel_type=REL_INTENT)
    social_before = router.get_weight("a", "b", rel_type=REL_SOCIAL)
    router.decay_all()
    intent_after = router.get_weight("a", "b", rel_type=REL_INTENT)
    social_after = router.get_weight("a", "b", rel_type=REL_SOCIAL)
    # Intent decayed harder than social.
    assert intent_after < social_after
    assert intent_after == pytest.approx(intent_before * 0.5, rel=1e-3)
    assert social_after == pytest.approx(social_before * 0.99, rel=1e-3)


def test_utility_utility_intent_pair_is_pruned() -> None:
    reg = _registry_with(tool_a=AgentTier.UTILITY, tool_b=AgentTier.UTILITY)
    router = HebbianRouter(decay_rate=0.9, reward=0.1)
    router.set_tier_registry(reg)
    w = router.record_interaction("tool_a", "tool_b", success=True, rel_type=REL_INTENT)
    assert w == 0.0
    assert router.get_weight("tool_a", "tool_b", rel_type=REL_INTENT) == 0.0


def test_utility_utility_rel_agent_still_records() -> None:
    """REL_AGENT (verification) is NOT pruned — DLog #7."""
    reg = _registry_with(tool_a=AgentTier.UTILITY, tool_b=AgentTier.UTILITY)
    router = HebbianRouter(decay_rate=0.9, reward=0.1)
    router.set_tier_registry(reg)
    w = router.record_interaction("tool_a", "tool_b", success=True, rel_type=REL_AGENT)
    assert w > 0.0


def test_crew_to_utility_intent_records() -> None:
    reg = _registry_with(crew_1=AgentTier.CREW, tool_b=AgentTier.UTILITY)
    router = HebbianRouter(decay_rate=0.9, reward=0.1)
    router.set_tier_registry(reg)
    w = router.record_interaction("crew_1", "tool_b", success=True, rel_type=REL_INTENT)
    assert w > 0.0


def test_core_infrastructure_pair_records() -> None:
    """CORE-CORE intent pair is NOT pruned — DLog #8."""
    reg = _registry_with(
        core_a=AgentTier.CORE_INFRASTRUCTURE,
        core_b=AgentTier.CORE_INFRASTRUCTURE,
    )
    router = HebbianRouter(decay_rate=0.9, reward=0.1)
    router.set_tier_registry(reg)
    w = router.record_interaction("core_a", "core_b", success=True, rel_type=REL_INTENT)
    assert w > 0.0


# ---------------- finalize wiring (mock runtime per dispatch hard-stop) ----------------


def test_finalize_wires_tier_registry_into_tracker() -> None:
    """Section 5 wiring fires through hasattr() guard. SimpleNamespace per AD-571a precedent.

    Verified anchors at HEAD 4d0242a:
    - finalize signature: `_populate_agent_tiers(*, runtime, config)` (kw-only)
    - agent registry: `runtime.registry` (not `agent_registry`)
    - config field: `config.agent_tiers` (plural)
    """
    from probos.config import AgentTierConfig
    from probos.startup.finalize import _populate_agent_tiers

    tracker = OperationalStatusTracker(OperationalStatusConfig())

    runtime = SimpleNamespace(
        registry=SimpleNamespace(all=lambda: []),
        trust_network=None,
        emergence_metrics_engine=None,
        hebbian_router=None,
        operational_status_tracker=tracker,
    )
    config = SimpleNamespace(agent_tiers=AgentTierConfig())
    _populate_agent_tiers(runtime=runtime, config=config)
    assert tracker._tier_registry is runtime._tier_registry  # type: ignore[attr-defined]
