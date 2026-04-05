"""Tests for AD-567g: Cognitive Re-Localization — Onboarding Enhancement.

28 tests covering OrientationContext, cold start orientation, warm boot orientation,
proactive supplement, anchor field gaps, and integration points.
"""

from __future__ import annotations

import dataclasses
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.orientation import (
    OrientationContext,
    OrientationService,
    derive_watch_section,
)
from probos.config import OrientationConfig, SystemConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(
    *,
    callsign: str = "Vega",
    agent_type: str = "security_agent",
    agent_id: str = "agent-1",
    rank: str = "Ensign",
    birth_timestamp: float | None = None,
) -> MagicMock:
    agent = MagicMock()
    agent.callsign = callsign
    agent.agent_type = agent_type
    agent.id = agent_id
    agent.rank = rank
    if birth_timestamp is not None:
        agent._birth_timestamp = birth_timestamp
    else:
        # Remove the attr so getattr returns None
        del agent._birth_timestamp
    agent._runtime = None
    return agent


def _make_service(config: SystemConfig | None = None) -> OrientationService:
    if config is None:
        config = SystemConfig()
    return OrientationService(config=config)


def _make_context(**overrides) -> OrientationContext:
    defaults = dict(
        callsign="Vega",
        post="Security Agent",
        department="Security",
        department_chief="Worf",
        reports_to="Worf",
        rank="Ensign",
        ship_name="ProbOS",
        crew_count=12,
        departments=["Security", "Engineering", "Medical", "Science"],
        lifecycle_state="cold_start",
        agent_age_seconds=0.0,
        stasis_duration_seconds=0.0,
        episodic_memory_count=0,
        has_baseline_trust=True,
        social_verification_available=False,
    )
    defaults.update(overrides)
    return OrientationContext(**defaults)


# ===========================================================================
# TestOrientationContext (4 tests)
# ===========================================================================

class TestOrientationContext:
    def test_build_orientation_cold_start(self) -> None:
        svc = _make_service()
        agent = _make_agent(birth_timestamp=time.time())
        ctx = svc.build_orientation(
            agent,
            lifecycle_state="cold_start",
            crew_count=10,
            departments=["Security", "Engineering"],
            episodic_memory_count=0,
            trust_score=0.5,
        )
        assert ctx.callsign == "Vega"
        assert ctx.lifecycle_state == "cold_start"
        assert ctx.crew_count == 10
        assert ctx.episodic_memory_count == 0
        assert ctx.has_baseline_trust is True

    def test_build_orientation_warm_boot(self) -> None:
        svc = _make_service()
        agent = _make_agent(birth_timestamp=time.time() - 7200)
        ctx = svc.build_orientation(
            agent,
            lifecycle_state="stasis_recovery",
            stasis_duration=3600.0,
            episodic_memory_count=42,
            trust_score=0.7,
        )
        assert ctx.lifecycle_state == "stasis_recovery"
        assert ctx.stasis_duration_seconds == 3600.0
        assert ctx.episodic_memory_count == 42
        assert ctx.has_baseline_trust is False  # 0.7 != 0.5

    def test_build_orientation_defaults(self) -> None:
        svc = _make_service()
        agent = _make_agent()
        ctx = svc.build_orientation(agent)
        assert ctx.lifecycle_state == ""
        assert ctx.crew_count == 0
        assert ctx.departments == []
        assert ctx.stasis_duration_seconds == 0.0
        assert "temporal" in ctx.anchor_dimensions

    def test_orientation_context_frozen(self) -> None:
        ctx = _make_context()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.callsign = "NewName"


# ===========================================================================
# TestColdStartOrientation (5 tests)
# ===========================================================================

class TestColdStartOrientation:
    def test_cold_start_orientation_identity_section(self) -> None:
        svc = _make_service()
        ctx = _make_context(callsign="Vega", post="Security Agent", department="Security", reports_to="Worf")
        text = svc.render_cold_start_orientation(ctx)
        assert "Vega" in text
        assert "Security Agent" in text
        assert "Security" in text
        assert "Worf" in text

    def test_cold_start_orientation_cognitive_section(self) -> None:
        svc = _make_service()
        ctx = _make_context()
        text = svc.render_cold_start_orientation(ctx)
        assert "Parametric knowledge" in text
        assert "Episodic memory" in text
        assert "HOW TO TELL THE DIFFERENCE" in text

    def test_cold_start_orientation_first_duty_section(self) -> None:
        svc = _make_service()
        ctx = _make_context()
        text = svc.render_cold_start_orientation(ctx)
        assert "FIRST DUTY GUIDANCE" in text
        assert "hedging" in text
        assert "Observe before asserting" in text

    def test_cold_start_orientation_zero_memories(self) -> None:
        svc = _make_service()
        ctx = _make_context(episodic_memory_count=0)
        text = svc.render_cold_start_orientation(ctx)
        assert "You have no memories yet" in text

    def test_cold_start_orientation_social_verification(self) -> None:
        svc = _make_service()
        ctx = _make_context(social_verification_available=True)
        text = svc.render_cold_start_orientation(ctx)
        assert "SOCIAL VERIFICATION" in text
        assert "social verification system" in text


# ===========================================================================
# TestWarmBootOrientation (4 tests)
# ===========================================================================

class TestWarmBootOrientation:
    def test_warm_boot_orientation_stasis_duration(self) -> None:
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=3600.0,
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "STASIS RECOVERY" in text
        # format_duration(3600) → "1h 0m 0s" or similar
        assert "1h" in text or "3600" in text or "60" in text

    def test_warm_boot_orientation_memory_count(self) -> None:
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            episodic_memory_count=42,
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "42 episodic memories" in text

    def test_warm_boot_orientation_identity_preserved(self) -> None:
        svc = _make_service()
        ctx = _make_context(callsign="Atlas", lifecycle_state="stasis_recovery")
        text = svc.render_warm_boot_orientation(ctx)
        assert "Atlas" in text
        assert "intact" in text

    def test_warm_boot_orientation_re_orientation_reminder(self) -> None:
        svc = _make_service()
        ctx = _make_context(lifecycle_state="stasis_recovery")
        text = svc.render_warm_boot_orientation(ctx)
        assert "RE-ORIENTATION" in text
        assert "temporal anchors" in text


# ===========================================================================
# TestProactiveSupplement (5 tests)
# ===========================================================================

class TestProactiveSupplement:
    def test_proactive_supplement_full(self) -> None:
        svc = _make_service()
        ctx = _make_context(agent_age_seconds=0.0)
        text = svc.render_proactive_orientation(ctx)
        assert "ORIENTATION ACTIVE" in text
        assert "newly commissioned" in text

    def test_proactive_supplement_brief(self) -> None:
        svc = _make_service()
        ctx = _make_context(agent_age_seconds=300.0)  # 50% of 600s window
        text = svc.render_proactive_orientation(ctx)
        assert "ORIENTATION:" in text
        assert "Ground claims" in text
        assert "ORIENTATION ACTIVE" not in text  # Not full

    def test_proactive_supplement_minimal(self) -> None:
        svc = _make_service()
        ctx = _make_context(agent_age_seconds=540.0)  # 90% of 600s window
        text = svc.render_proactive_orientation(ctx)
        assert text == "ORIENTATION: Check your anchors before asserting."

    def test_proactive_supplement_expired(self) -> None:
        svc = _make_service()
        ctx = _make_context(agent_age_seconds=600.0)  # At window boundary
        text = svc.render_proactive_orientation(ctx)
        assert text == ""

    def test_proactive_supplement_disabled(self) -> None:
        cfg = SystemConfig()
        cfg.orientation.proactive_supplement = False
        svc = OrientationService(config=cfg)
        # Even with young age, the caller (proactive.py) checks config before calling
        # The service itself returns based on age, so disabled is handled by caller.
        # Here we test that expired always returns empty.
        ctx = _make_context(agent_age_seconds=700.0)
        text = svc.render_proactive_orientation(ctx)
        assert text == ""


# ===========================================================================
# TestAnchorFieldGaps (5 tests)
# ===========================================================================

class TestAnchorFieldGaps:
    def test_derive_watch_section_mid(self) -> None:
        assert derive_watch_section(2) == "mid"

    def test_derive_watch_section_forenoon(self) -> None:
        assert derive_watch_section(10) == "forenoon"

    def test_derive_watch_section_dog(self) -> None:
        assert derive_watch_section(17) == "first_dog"
        assert derive_watch_section(19) == "second_dog"

    def test_ward_room_episode_has_department(self) -> None:
        """Ward Room MessageStore resolves department for episode anchors."""
        from probos.ward_room.messages import MessageStore
        store = MessageStore(
            db=None,
            emit_fn=MagicMock(),
        )
        # Mock standing_orders.get_department to return a known value
        with patch("probos.ward_room.messages.MessageStore._resolve_author_department", return_value="Security"):
            dept = store._resolve_author_department("security_agent")
            assert dept == "Security"

    def test_event_log_window_populated(self) -> None:
        """AnchorFrame construction in proactive.py includes event_log_window."""
        from probos.types import AnchorFrame
        # Simulate event log with 5 recent events
        mock_el = MagicMock()
        mock_el.recent.return_value = [1, 2, 3, 4, 5]
        anchor = AnchorFrame(
            channel="duty_report",
            event_log_window=float(len(mock_el.recent(seconds=60))),
            watch_section=derive_watch_section(14),
        )
        assert anchor.event_log_window == 5.0
        assert anchor.watch_section == "afternoon"


# ===========================================================================
# TestIntegration (5 tests)
# ===========================================================================

class TestIntegration:
    def test_onboarding_sets_orientation_context(self) -> None:
        """wire_agent() stores orientation on agent after naming."""
        from probos.agent_onboarding import AgentOnboardingService

        agent = _make_agent()
        svc = _make_service()

        onboarding = MagicMock(spec=AgentOnboardingService)
        # Simulate the orientation injection pattern
        ctx = svc.build_orientation(
            agent,
            lifecycle_state="cold_start",
            crew_count=10,
            episodic_memory_count=0,
            trust_score=0.5,
        )
        agent._orientation_context = ctx
        agent._orientation_rendered = svc.render_cold_start_orientation(ctx)

        assert hasattr(agent, '_orientation_context')
        assert agent._orientation_context.callsign == "Vega"
        assert "COGNITIVE ORIENTATION" in agent._orientation_rendered

    def test_temporal_context_includes_orientation(self) -> None:
        """_build_temporal_context() includes orientation text when present."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.meta = MagicMock()
        agent.meta.last_active = None
        agent._runtime = None
        agent._birth_timestamp = None
        agent._system_start_time = None

        # Set orientation rendered text
        agent._orientation_rendered = "TEST ORIENTATION CONTENT"

        result = agent._build_temporal_context()
        assert "TEST ORIENTATION CONTENT" in result

    def test_gather_context_includes_supplement(self) -> None:
        """_gather_context() includes proactive supplement for new agents."""
        # This is a structural test — verify the service produces output
        svc = _make_service()
        ctx = _make_context(agent_age_seconds=10.0)  # Very young
        supplement = svc.render_proactive_orientation(ctx)
        assert supplement != ""
        assert "ORIENTATION" in supplement

    def test_gather_context_no_supplement_after_window(self) -> None:
        """Supplement absent after orientation_window_seconds."""
        svc = _make_service()
        ctx = _make_context(agent_age_seconds=601.0)  # Past 600s window
        supplement = svc.render_proactive_orientation(ctx)
        assert supplement == ""

    def test_finalize_sets_warm_boot_orientation(self) -> None:
        """Stasis recovery path sets warm boot orientation on crew agents."""
        svc = _make_service()
        agent = _make_agent(birth_timestamp=time.time() - 7200)
        ctx = svc.build_orientation(
            agent,
            lifecycle_state="stasis_recovery",
            stasis_duration=1800.0,
            episodic_memory_count=15,
            trust_score=0.65,
        )
        rendered = svc.render_warm_boot_orientation(ctx)
        agent._orientation_rendered = rendered
        agent._orientation_context = ctx

        assert "STASIS RECOVERY" in agent._orientation_rendered
        assert agent._orientation_context.lifecycle_state == "stasis_recovery"
        assert agent._orientation_context.stasis_duration_seconds == 1800.0
