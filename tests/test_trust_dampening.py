"""Tests for AD-558: Trust Cascade Dampening."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import TrustDampeningConfig
from probos.consensus.trust import TrustNetwork, TrustEvent, _DampeningState, _CascadeState
from probos.events import EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_network(**overrides) -> TrustNetwork:
    """Create a TrustNetwork with dampening config, optionally overriding config fields."""
    cfg = TrustDampeningConfig(**overrides) if overrides else TrustDampeningConfig()
    return TrustNetwork(dampening_config=cfg)


# ===========================================================================
# Progressive dampening
# ===========================================================================


class TestProgressiveDampening:
    """Part 1: Progressive dampening tests."""

    def test_first_update_full_weight(self):
        """First update in a direction applies full weight (factor 1.0)."""
        tn = _make_network()
        tn.record_outcome("a1", success=True, weight=1.0)
        record = tn.get_or_create("a1")
        assert record.alpha == 3.0  # 2.0 prior + 1.0 * 1.0

    def test_second_consecutive_dampened(self):
        """Second consecutive same-direction update applies 0.75x weight."""
        tn = _make_network()
        tn.record_outcome("a1", success=True, weight=1.0)
        tn.record_outcome("a1", success=True, weight=1.0)
        record = tn.get_or_create("a1")
        assert record.alpha == pytest.approx(3.75)  # 2.0 + 1.0 + 0.75

    def test_third_consecutive_dampened(self):
        """Third consecutive applies 0.5x weight."""
        tn = _make_network()
        tn.record_outcome("a1", success=True, weight=1.0)
        tn.record_outcome("a1", success=True, weight=1.0)
        tn.record_outcome("a1", success=True, weight=1.0)
        record = tn.get_or_create("a1")
        assert record.alpha == pytest.approx(4.25)  # 2.0 + 1.0 + 0.75 + 0.5

    def test_fourth_consecutive_floor(self):
        """Fourth+ consecutive applies 0.25x weight (floor) when not cold-start."""
        tn = _make_network(cold_start_observation_threshold=0.0)  # Disable cold-start
        for _ in range(4):
            tn.record_outcome("a1", success=True, weight=1.0)
        record = tn.get_or_create("a1")
        assert record.alpha == pytest.approx(4.5)  # 2.0 + 1.0 + 0.75 + 0.5 + 0.25

    def test_fifth_consecutive_stays_at_floor(self):
        """Fifth consecutive stays at 0.25x floor when not cold-start."""
        tn = _make_network(cold_start_observation_threshold=0.0)  # Disable cold-start
        for _ in range(5):
            tn.record_outcome("a1", success=True, weight=1.0)
        record = tn.get_or_create("a1")
        assert record.alpha == pytest.approx(4.75)  # 4.5 + 0.25

    def test_direction_reversal_resets(self):
        """Direction change resets dampening count."""
        tn = _make_network()
        tn.record_outcome("a1", success=True, weight=1.0)   # 1st positive, factor 1.0
        tn.record_outcome("a1", success=True, weight=1.0)   # 2nd positive, factor 0.75
        tn.record_outcome("a1", success=False, weight=1.0)  # 1st negative, factor 1.0 (reset)
        record = tn.get_or_create("a1")
        assert record.alpha == pytest.approx(3.75)  # 2.0 + 1.0 + 0.75
        assert record.beta == pytest.approx(3.0)    # 2.0 + 1.0

    def test_window_expiry_resets(self):
        """Expired window resets dampening count."""
        tn = _make_network(dampening_window_seconds=0.01)
        tn.record_outcome("a1", success=True, weight=1.0)
        time.sleep(0.02)  # Exceed window
        tn.record_outcome("a1", success=True, weight=1.0)
        record = tn.get_or_create("a1")
        # Both should be full weight (1.0 each) since window expired
        assert record.alpha == pytest.approx(4.0)  # 2.0 + 1.0 + 1.0

    def test_different_agents_independent(self):
        """Different agents have independent dampening state."""
        tn = _make_network()
        tn.record_outcome("a1", success=True, weight=1.0)  # 1st for a1
        tn.record_outcome("a1", success=True, weight=1.0)  # 2nd for a1, dampened
        tn.record_outcome("a2", success=True, weight=1.0)  # 1st for a2, NOT dampened
        r1 = tn.get_or_create("a1")
        r2 = tn.get_or_create("a2")
        assert r1.alpha == pytest.approx(3.75)  # 2.0 + 1.0 + 0.75
        assert r2.alpha == pytest.approx(3.0)   # 2.0 + 1.0

    def test_dampening_factor_in_event(self):
        """Dampening factor is recorded in TrustEvent."""
        tn = _make_network()
        tn.record_outcome("a1", success=True, weight=1.0)
        tn.record_outcome("a1", success=True, weight=1.0)
        events = tn.get_events_for_agent("a1")
        assert events[0].dampening_factor == 1.0
        assert events[1].dampening_factor == 0.75


# ===========================================================================
# Cold-start scaling
# ===========================================================================


class TestColdStartDampening:
    """Cold-start scaling tests."""

    def test_cold_start_applies_floor(self):
        """Agent with alpha+beta < 20 gets cold-start dampening floor (0.5)."""
        tn = _make_network()
        # alpha=2.0, beta=2.0 → total=4.0 < 20 → cold start
        tn.record_outcome("a1", success=True, weight=1.0)
        # Cold-start floor is 0.5, first update factor is 1.0 → max(1.0, 0.5) = 1.0
        # But second consecutive update: factor = 0.75 → max(0.75, 0.5) = 0.75
        tn.record_outcome("a1", success=True, weight=1.0)
        record = tn.get_or_create("a1")
        # 3rd consecutive: normal factor=0.5, cold-start floor=0.5 → max(0.5, 0.5) = 0.5
        tn.record_outcome("a1", success=True, weight=1.0)
        # 4th consecutive: normal factor=0.25, cold-start floor=0.5 → max(0.25, 0.5) = 0.5
        tn.record_outcome("a1", success=True, weight=1.0)
        record = tn.get_or_create("a1")
        # alpha = 2.0 + 1.0 + 0.75 + 0.5 + 0.5 = 4.75
        assert record.alpha == pytest.approx(4.75)

    def test_mature_agent_no_cold_start(self):
        """Agent with alpha+beta >= 20 uses normal progression."""
        tn = _make_network()
        # Manually set high alpha to exceed cold-start threshold
        record = tn.get_or_create("a1")
        record.alpha = 18.0  # alpha+beta = 18+2 = 20 → NOT cold start
        for _ in range(4):
            tn.record_outcome("a1", success=True, weight=1.0)
        record = tn.get_or_create("a1")
        # 1.0 + 0.75 + 0.5 + 0.25 = 2.5
        assert record.alpha == pytest.approx(20.5)  # 18.0 + 2.5

    def test_cold_start_threshold_configurable(self):
        """Cold-start threshold is configurable."""
        tn = _make_network(cold_start_observation_threshold=5.0)
        # alpha=2 + beta=2 = 4 < 5 → cold start
        record = tn.get_or_create("a1")
        assert (record.alpha + record.beta) < 5.0
        # After a few updates, it crosses the threshold
        tn.record_outcome("a1", success=True, weight=1.0)  # total now 5.0 → no longer cold start
        # Next update should use normal dampening
        tn.record_outcome("a1", success=True, weight=1.0)
        events = tn.get_events_for_agent("a1")
        # Second update: consecutive=2, factor=0.75, no cold-start floor
        assert events[1].dampening_factor == 0.75


# ===========================================================================
# Hard trust floor
# ===========================================================================


class TestHardTrustFloor:
    """Part 2: Hard trust floor tests."""

    def test_negative_above_floor_applies(self):
        """Negative update at score above floor applies normally."""
        tn = _make_network()
        initial = tn.get_score("a1")
        assert initial > 0.05
        tn.record_outcome("a1", success=False, weight=1.0)
        record = tn.get_or_create("a1")
        assert record.beta == pytest.approx(3.0)

    def test_negative_at_floor_absorbed(self):
        """Negative update at score at/below floor is silently absorbed."""
        tn = _make_network(hard_trust_floor=0.5)  # Set high floor for testing
        # With default alpha=2, beta=2, score=0.5 → at floor
        score = tn.record_outcome("a1", success=False, weight=1.0)
        # Score should stay at 0.5 since it's at the floor
        assert score == pytest.approx(0.5)
        record = tn.get_or_create("a1")
        assert record.beta == pytest.approx(2.0)  # Not changed

    def test_positive_below_floor_applies(self):
        """Positive update at score below floor still applies (allows recovery)."""
        tn = _make_network()
        record = tn.get_or_create("a1")
        record.alpha = 0.1
        record.beta = 10.0  # Score ≈ 0.01, well below floor
        assert record.score < 0.05
        tn.record_outcome("a1", success=True, weight=1.0)
        assert record.alpha == pytest.approx(1.1)  # Applied

    def test_floor_hit_recorded_in_event(self):
        """Floor hit is recorded in TrustEvent."""
        tn = _make_network(hard_trust_floor=0.5)
        tn.record_outcome("a1", success=False, weight=1.0)
        events = tn.get_events_for_agent("a1")
        assert len(events) == 1
        assert events[0].floor_hit is True

    def test_floor_configurable(self):
        """Floor value is configurable."""
        tn = _make_network(hard_trust_floor=0.3)
        record = tn.get_or_create("a1")
        record.alpha = 1.0
        record.beta = 5.0  # Score ≈ 0.167, below 0.3
        score = tn.record_outcome("a1", success=False, weight=1.0)
        assert record.beta == pytest.approx(5.0)  # Not changed — absorbed

    def test_floor_hit_count_increments(self):
        """Floor hit counter increments on each absorbed update."""
        tn = _make_network(hard_trust_floor=0.5)
        tn.record_outcome("a1", success=False, weight=1.0)
        tn.record_outcome("a1", success=False, weight=1.0)
        assert tn._floor_hit_count == 2

    def test_floor_hit_count_resets(self):
        """Floor hit counter resets via reset method."""
        tn = _make_network(hard_trust_floor=0.5)
        tn.record_outcome("a1", success=False, weight=1.0)
        tn.reset_floor_hit_count()
        assert tn._floor_hit_count == 0


# ===========================================================================
# Network circuit breaker
# ===========================================================================


class TestCascadeBreaker:
    """Part 3: Network-level circuit breaker tests."""

    def test_single_agent_no_trip(self):
        """Single agent anomaly does not trip breaker."""
        tn = _make_network(cascade_agent_threshold=3, cascade_delta_threshold=0.01)
        # One agent with big delta
        tn.record_outcome("a1", success=False, weight=5.0)
        assert not tn._cascade.tripped

    def test_m_agents_one_dept_no_trip(self):
        """M agents in 1 department does not trip breaker (need N departments)."""
        tn = _make_network(
            cascade_agent_threshold=2,
            cascade_department_threshold=2,
            cascade_delta_threshold=0.01,
        )
        tn.set_department_lookup(lambda aid: "engineering")
        tn.record_outcome("a1", success=False, weight=5.0)
        tn.record_outcome("a2", success=False, weight=5.0)
        assert not tn._cascade.tripped

    def test_m_agents_n_depts_trips(self):
        """M agents across N departments within window trips breaker."""
        tn = _make_network(
            cascade_agent_threshold=2,
            cascade_department_threshold=2,
            cascade_delta_threshold=0.01,
        )
        tn.set_department_lookup(
            lambda aid: "engineering" if "1" in aid else "science"
        )
        tn.record_outcome("a1", success=False, weight=5.0)
        tn.record_outcome("a2", success=False, weight=5.0)
        assert tn._cascade.tripped

    def test_anomalies_outside_window_pruned(self):
        """Anomalies outside window are pruned."""
        tn = _make_network(
            cascade_agent_threshold=2,
            cascade_department_threshold=2,
            cascade_delta_threshold=0.01,
            cascade_window_seconds=0.01,
        )
        tn.set_department_lookup(
            lambda aid: "engineering" if "1" in aid else "science"
        )
        tn.record_outcome("a1", success=False, weight=5.0)
        time.sleep(0.02)  # Exceed window
        tn.record_outcome("a2", success=False, weight=5.0)
        assert not tn._cascade.tripped  # First anomaly expired

    def test_tripped_applies_global_dampening(self):
        """While tripped: all trust updates get global dampening multiplier."""
        tn = _make_network(
            cascade_agent_threshold=2,
            cascade_department_threshold=1,
            cascade_delta_threshold=0.01,
            cascade_global_dampening=0.5,
            cascade_cooldown_seconds=60.0,
        )
        # Trip the breaker
        tn.record_outcome("a1", success=False, weight=5.0)
        tn.record_outcome("a2", success=False, weight=5.0)
        assert tn._cascade.tripped

        # Now a new update for a3 should get global dampening
        tn.record_outcome("a3", success=True, weight=1.0)
        events = tn.get_events_for_agent("a3")
        # dampening_factor should include the 0.5 global multiplier
        assert events[0].dampening_factor == pytest.approx(0.5)  # 1.0 * 0.5

    def test_cooldown_resets_breaker(self):
        """After cooldown: breaker resets, normal weight resumes."""
        tn = _make_network(
            cascade_agent_threshold=2,
            cascade_department_threshold=1,
            cascade_delta_threshold=0.01,
            cascade_cooldown_seconds=0.01,  # Very short cooldown
        )
        tn.record_outcome("a1", success=False, weight=5.0)
        tn.record_outcome("a2", success=False, weight=5.0)
        assert tn._cascade.tripped
        time.sleep(0.02)
        # Next update should reset the breaker
        tn.record_outcome("a3", success=True, weight=1.0)
        assert not tn._cascade.tripped
        events = tn.get_events_for_agent("a3")
        assert events[0].dampening_factor == pytest.approx(1.0)

    def test_cascade_emits_warning_event(self):
        """Cascade emits TRUST_CASCADE_WARNING event."""
        tn = _make_network(
            cascade_agent_threshold=2,
            cascade_department_threshold=1,
            cascade_delta_threshold=0.01,
        )
        events_emitted = []
        tn.set_event_callback(lambda t, d: events_emitted.append((t, d)))
        tn.record_outcome("a1", success=False, weight=5.0)
        tn.record_outcome("a2", success=False, weight=5.0)
        cascade_events = [e for e in events_emitted if e[0] == "trust_cascade_warning"]
        assert len(cascade_events) == 1
        data = cascade_events[0][1]
        assert "a1" in data["anomalous_agents"]
        assert "a2" in data["anomalous_agents"]

    def test_without_department_lookup_agent_only(self):
        """Without department lookup: only agent count threshold used."""
        tn = _make_network(
            cascade_agent_threshold=2,
            cascade_delta_threshold=0.01,
        )
        # No department lookup set
        tn.record_outcome("a1", success=False, weight=5.0)
        tn.record_outcome("a2", success=False, weight=5.0)
        assert tn._cascade.tripped  # Agent count alone triggers

    def test_department_lookup_injection(self):
        """Department lookup injection works correctly."""
        tn = _make_network()
        lookup = MagicMock(return_value="engineering")
        tn.set_department_lookup(lookup)
        assert tn._get_department is lookup


# ===========================================================================
# Event emission
# ===========================================================================


class TestEventEmission:
    """Part 4: Event emission tests."""

    def test_record_outcome_emits_trust_update(self):
        """record_outcome() emits TRUST_UPDATE when callback is set."""
        tn = _make_network()
        events_emitted = []
        tn.set_event_callback(lambda t, d: events_emitted.append((t, d)))
        tn.record_outcome("a1", success=True, weight=1.0)
        trust_events = [e for e in events_emitted if e[0] == "trust_update"]
        assert len(trust_events) == 1

    def test_no_callback_no_crash(self):
        """record_outcome() does NOT crash when callback is not set."""
        tn = _make_network()
        score = tn.record_outcome("a1", success=True, weight=1.0)
        assert score > 0  # Just works

    def test_emitted_payload_structure(self):
        """Emitted event payload has agent_id, old_score, new_score, success."""
        tn = _make_network()
        events_emitted = []
        tn.set_event_callback(lambda t, d: events_emitted.append((t, d)))
        tn.record_outcome("a1", success=True, weight=1.0)
        data = events_emitted[0][1]
        assert "agent_id" in data
        assert "old_score" in data
        assert "new_score" in data
        assert "success" in data
        assert data["agent_id"] == "a1"
        assert data["success"] is True

    def test_floor_hit_emits_event(self):
        """Floor hit still emits event."""
        tn = _make_network(hard_trust_floor=0.5)
        events_emitted = []
        tn.set_event_callback(lambda t, d: events_emitted.append((t, d)))
        tn.record_outcome("a1", success=False, weight=1.0)
        assert len(events_emitted) == 1
        assert events_emitted[0][1]["floor_hit"] is True

    def test_dampening_factor_in_emitted_event(self):
        """Emitted event includes dampening_factor."""
        tn = _make_network()
        events_emitted = []
        tn.set_event_callback(lambda t, d: events_emitted.append((t, d)))
        tn.record_outcome("a1", success=True, weight=1.0)
        tn.record_outcome("a1", success=True, weight=1.0)
        assert events_emitted[1][1]["dampening_factor"] == pytest.approx(0.75)


# ===========================================================================
# Telemetry
# ===========================================================================


class TestDampeningTelemetry:
    """Part 6: Dampening telemetry tests."""

    def test_telemetry_per_agent_state(self):
        """get_dampening_telemetry() returns correct per-agent state."""
        tn = _make_network()
        tn.record_outcome("a1", success=True, weight=1.0)
        tn.record_outcome("a1", success=True, weight=1.0)
        telemetry = tn.get_dampening_telemetry()
        assert "a1" in telemetry["per_agent"]
        agent_data = telemetry["per_agent"]["a1"]
        assert agent_data["consecutive_count"] == 2
        assert agent_data["direction"] == "positive"
        assert agent_data["dampening_factor"] == pytest.approx(0.75)

    def test_telemetry_cascade_breaker_state(self):
        """get_dampening_telemetry() returns cascade breaker state."""
        tn = _make_network()
        telemetry = tn.get_dampening_telemetry()
        assert "cascade_breaker" in telemetry
        assert telemetry["cascade_breaker"]["tripped"] is False
        assert telemetry["cascade_breaker"]["cooldown_remaining"] == 0.0
        assert telemetry["cascade_breaker"]["anomaly_count"] == 0

    def test_telemetry_floor_hits(self):
        """get_dampening_telemetry() returns floor hit count."""
        tn = _make_network(hard_trust_floor=0.5)
        tn.record_outcome("a1", success=False, weight=1.0)
        telemetry = tn.get_dampening_telemetry()
        assert telemetry["floor_hits"] == 1


# ===========================================================================
# Integration / stacking
# ===========================================================================


class TestDampeningIntegration:
    """Integration tests for dampening + cascade stacking."""

    def test_dampening_and_cascade_stack(self):
        """Progressive dampening + cascade breaker stack multiplicatively."""
        tn = _make_network(
            cascade_agent_threshold=2,
            cascade_department_threshold=1,
            cascade_delta_threshold=0.01,
            cascade_global_dampening=0.5,
            cascade_cooldown_seconds=60.0,
        )
        # Trip the breaker
        tn.record_outcome("a1", success=False, weight=5.0)
        tn.record_outcome("a2", success=False, weight=5.0)
        assert tn._cascade.tripped

        # Now a3 gets: agent dampening (1st, factor=1.0) * global dampening (0.5) = 0.5
        tn.record_outcome("a3", success=True, weight=1.0)
        events = tn.get_events_for_agent("a3")
        assert events[0].dampening_factor == pytest.approx(0.5)

        # a3 2nd consecutive: agent dampening (0.75) * global (0.5) = 0.375
        tn.record_outcome("a3", success=True, weight=1.0)
        events = tn.get_events_for_agent("a3")
        assert events[1].dampening_factor == pytest.approx(0.375)

    def test_full_cascade_scenario(self):
        """Full cascade scenario: rapid negatives → dampening → cascade → recovery."""
        tn = _make_network(
            cascade_agent_threshold=2,
            cascade_department_threshold=1,
            cascade_delta_threshold=0.01,
            cascade_global_dampening=0.5,
            cascade_cooldown_seconds=0.01,
        )

        # Phase 1: Rapid negatives trigger cascade
        tn.record_outcome("a1", success=False, weight=5.0)
        tn.record_outcome("a2", success=False, weight=5.0)
        assert tn._cascade.tripped

        # Phase 2: During cascade, updates are dampened
        tn.record_outcome("a3", success=True, weight=1.0)
        r3 = tn.get_or_create("a3")
        assert r3.alpha == pytest.approx(2.5)  # 2.0 + 1.0*0.5

        # Phase 3: After cooldown, recovery
        time.sleep(0.02)
        tn.record_outcome("a4", success=True, weight=1.0)
        r4 = tn.get_or_create("a4")
        assert not tn._cascade.tripped
        assert r4.alpha == pytest.approx(3.0)  # Full weight restored

    def test_bf099_lock_still_works(self):
        """BF-099 lock still works correctly with dampening (no deadlock)."""
        tn = _make_network()
        assert hasattr(tn, '_lock')
        assert isinstance(tn._lock, asyncio.Lock)
        # Sync record_outcome doesn't use the lock (lock is for async DB ops)
        tn.record_outcome("a1", success=True, weight=1.0)
        assert tn.get_score("a1") > 0.5

    @pytest.mark.asyncio
    async def test_counselor_receives_cascade_warning(self):
        """Counselor-style handler receives TRUST_CASCADE_WARNING data."""
        tn = _make_network(
            cascade_agent_threshold=2,
            cascade_department_threshold=1,
            cascade_delta_threshold=0.01,
        )
        cascade_data = []
        tn.set_event_callback(
            lambda t, d: cascade_data.append(d) if t == "trust_cascade_warning" else None
        )
        tn.record_outcome("a1", success=False, weight=5.0)
        tn.record_outcome("a2", success=False, weight=5.0)
        assert len(cascade_data) == 1
        assert "anomalous_agents" in cascade_data[0]
        assert "departments_affected" in cascade_data[0]
        assert "global_dampening_factor" in cascade_data[0]
        assert "cooldown_seconds" in cascade_data[0]


# ===========================================================================
# Config
# ===========================================================================


class TestTrustDampeningConfig:
    """Config validation tests."""

    def test_default_config_values(self):
        """Default TrustDampeningConfig has expected values."""
        cfg = TrustDampeningConfig()
        assert cfg.dampening_window_seconds == 300.0
        assert cfg.dampening_geometric_factors == (1.0, 0.75, 0.5, 0.25)
        assert cfg.dampening_floor == 0.25
        assert cfg.hard_trust_floor == 0.05
        assert cfg.cascade_agent_threshold == 3
        assert cfg.cascade_department_threshold == 2
        assert cfg.cascade_delta_threshold == 0.15
        assert cfg.cascade_window_seconds == 300.0
        assert cfg.cascade_global_dampening == 0.5
        assert cfg.cascade_cooldown_seconds == 600.0
        assert cfg.cold_start_observation_threshold == 20.0
        assert cfg.cold_start_dampening_floor == 0.5

    def test_config_in_system_config(self):
        """TrustDampeningConfig is accessible from SystemConfig."""
        from probos.config import SystemConfig
        sc = SystemConfig()
        assert hasattr(sc, 'trust_dampening')
        assert isinstance(sc.trust_dampening, TrustDampeningConfig)

    def test_trust_hard_floor_constant(self):
        """TRUST_HARD_FLOOR constant exists."""
        from probos.config import TRUST_HARD_FLOOR
        assert TRUST_HARD_FLOOR == 0.05


# ===========================================================================
# Event types
# ===========================================================================


class TestEventTypes:
    """Event type registration tests."""

    def test_trust_cascade_warning_event_type(self):
        """TRUST_CASCADE_WARNING event type exists."""
        assert hasattr(EventType, 'TRUST_CASCADE_WARNING')
        assert EventType.TRUST_CASCADE_WARNING.value == "trust_cascade_warning"

    def test_trust_cascade_event_dataclass(self):
        """TrustCascadeEvent dataclass exists and serializes."""
        from probos.events import TrustCascadeEvent
        evt = TrustCascadeEvent(
            anomalous_agents=["a1", "a2"],
            departments_affected=["engineering", "science"],
            global_dampening_factor=0.5,
            cooldown_seconds=600.0,
        )
        d = evt.to_dict()
        assert d["type"] == "trust_cascade_warning"
        assert "a1" in d["data"]["anomalous_agents"]
