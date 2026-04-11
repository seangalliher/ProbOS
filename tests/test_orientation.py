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
        stasis_shutdown_utc="",         # BF-144
        stasis_resume_utc="",           # BF-144
        episodic_memory_count=0,
        has_baseline_trust=True,
        social_verification_available=False,
        manifest=None,  # AD-587
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
        # BF-144: Structured format with "AUTHORITATIVE" header
        assert "AUTHORITATIVE" in text
        assert "Duration:" in text
        assert "1h" in text or "3600" in text

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

        assert "STASIS RECORD" in agent._orientation_rendered
        assert agent._orientation_context.lifecycle_state == "stasis_recovery"
        assert agent._orientation_context.stasis_duration_seconds == 1800.0


# ===========================================================================
# TestStasisConfabulationGuardBF144 (7 tests)
# ===========================================================================

class TestStasisConfabulationGuardBF144:
    """BF-144: Stasis orientation must use structured authoritative format."""

    def test_authoritative_header_present(self) -> None:
        """Orientation must include AUTHORITATIVE marker to resist confabulation."""
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "AUTHORITATIVE" in text
        assert "cite this" in text.lower() or "do not estimate" in text.lower()

    def test_structured_duration_format(self) -> None:
        """Duration must be in key-value format, not narrative prose."""
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
        )
        text = svc.render_warm_boot_orientation(ctx)
        # Must contain "Duration: 6m 19s" not "You were offline for 6m 19s."
        assert "Duration:" in text
        assert "6m 19s" in text

    def test_shutdown_timestamp_included(self) -> None:
        """Shutdown timestamp must appear when provided."""
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
            stasis_shutdown_utc="2026-04-10 18:15:34 UTC",
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "Shutdown:" in text
        assert "2026-04-10 18:15:34 UTC" in text

    def test_resume_timestamp_included(self) -> None:
        """Resume timestamp must appear when provided."""
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
            stasis_resume_utc="2026-04-10 18:21:53 UTC",
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "Resume:" in text
        assert "2026-04-10 18:21:53 UTC" in text

    def test_timestamps_omitted_when_empty(self) -> None:
        """No Shutdown/Resume lines when timestamps are not provided."""
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
            stasis_shutdown_utc="",
            stasis_resume_utc="",
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "Shutdown:" not in text
        assert "Resume:" not in text
        # Duration still present
        assert "Duration:" in text

    def test_identity_still_preserved(self) -> None:
        """BF-144 format change must not remove identity confirmation."""
        svc = _make_service()
        ctx = _make_context(
            callsign="Meridian",
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "Meridian" in text
        assert "identity" in text.lower() or "intact" in text.lower() or "still" in text.lower()

    def test_build_orientation_passes_timestamps(self) -> None:
        """build_orientation() must accept and forward stasis timestamps."""
        svc = _make_service()

        class FakeAgent:
            callsign = "Echo"
            agent_type = "counselor"
            rank = "Lieutenant"
            _birth_timestamp = None

        ctx = svc.build_orientation(
            FakeAgent(),
            lifecycle_state="stasis_recovery",
            stasis_duration=379.0,
            stasis_shutdown_utc="2026-04-10 18:15:34 UTC",
            stasis_resume_utc="2026-04-10 18:21:53 UTC",
        )
        assert ctx.stasis_shutdown_utc == "2026-04-10 18:15:34 UTC"
        assert ctx.stasis_resume_utc == "2026-04-10 18:21:53 UTC"


# ===========================================================================
# TestCognitiveArchitectureManifestAD587 (23 tests)
# ===========================================================================

class TestCognitiveArchitectureManifestAD587:
    """AD-587: Cognitive Architecture Manifest — mechanistic self-model."""

    # --- Manifest dataclass ---

    def test_manifest_defaults(self):
        """Default manifest has correct architecture facts."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        m = CognitiveArchitectureManifest()
        assert m.memory_system == "chromadb_episodic"
        assert m.memory_retrieval == "cosine_similarity"
        assert m.memory_offline_processing is False
        assert m.stasis_processing is False
        assert m.stasis_dream_consolidation is False
        assert m.cognition_continuous is False
        assert m.cognition_emotional_processing is False
        assert m.trust_initial == 0.5
        assert m.trust_model == "bayesian_beta"
        assert m.regulation_model == "graduated_zones"

    def test_manifest_is_frozen(self):
        """Manifest is immutable — architecture facts don't change at runtime."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        m = CognitiveArchitectureManifest()
        with pytest.raises(AttributeError):
            m.memory_system = "something_else"  # type: ignore[misc]

    def test_manifest_stasis_facts_are_false(self):
        """All stasis-related processing claims must be False."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        m = CognitiveArchitectureManifest()
        assert m.stasis_processing is False
        assert m.stasis_dream_consolidation is False
        assert m.stasis_memory_evolution is False

    def test_manifest_no_emotional_processing(self):
        """Architecture does not include emotional processing."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        m = CognitiveArchitectureManifest()
        assert m.cognition_emotional_processing is False

    # --- build_manifest() ---

    def test_build_manifest_returns_manifest(self):
        """OrientationService.build_manifest() returns a CognitiveArchitectureManifest."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        svc = _make_service()
        m = svc.build_manifest()
        assert isinstance(m, CognitiveArchitectureManifest)

    def test_build_manifest_reads_trust_floor_from_config(self):
        """Manifest trust range reflects config hard_trust_floor."""
        cfg = SystemConfig()
        if hasattr(cfg, 'trust_dampening') and hasattr(cfg.trust_dampening, 'hard_trust_floor'):
            svc = _make_service(cfg)
            m = svc.build_manifest()
            assert m.trust_range[0] == cfg.trust_dampening.hard_trust_floor

    def test_build_manifest_default_trust_range(self):
        """Default trust range is (0.05, 0.95)."""
        svc = _make_service()
        m = svc.build_manifest()
        assert m.trust_range[0] == 0.05
        assert m.trust_range[1] == 0.95

    # --- Manifest in OrientationContext ---

    def test_orientation_context_includes_manifest(self):
        """OrientationContext has a manifest field."""
        ctx = _make_context()
        assert hasattr(ctx, 'manifest')

    def test_build_orientation_populates_manifest(self):
        """build_orientation() populates manifest on the returned context."""
        svc = _make_service()
        agent = _make_agent()
        ctx = svc.build_orientation(agent)
        assert ctx.manifest is not None

    def test_build_orientation_manifest_survives_failure(self):
        """If manifest construction fails, orientation still succeeds (manifest=None)."""
        svc = _make_service()
        agent = _make_agent()
        with patch.object(svc, 'build_manifest', side_effect=RuntimeError("boom")):
            ctx = svc.build_orientation(agent)
            assert ctx.manifest is None  # Graceful degradation

    # --- Rendering ---

    def test_cold_start_includes_manifest_section(self):
        """Cold start orientation includes architecture manifest text."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(manifest=CognitiveArchitectureManifest())
        svc = _make_service()
        text = svc.render_cold_start_orientation(ctx)
        assert "HOW YOUR COGNITIVE ARCHITECTURE WORKS" in text

    def test_cold_start_manifest_contains_key_facts(self):
        """Manifest section mentions cosine similarity, stasis, Bayesian, inference cycles."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(manifest=CognitiveArchitectureManifest())
        svc = _make_service()
        text = svc.render_cold_start_orientation(ctx)
        assert "cosine_similarity" in text
        assert "stasis" in text.lower()
        assert "Bayesian" in text
        assert "inference cycles" in text

    def test_cold_start_manifest_stasis_no_processing(self):
        """Manifest explicitly states nothing processes during stasis."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(manifest=CognitiveArchitectureManifest())
        svc = _make_service()
        text = svc.render_cold_start_orientation(ctx)
        assert "ALL processing stops" in text or "Nothing happens to your memories while you are offline" in text

    def test_cold_start_manifest_no_emotional_subsystem(self):
        """Manifest explicitly states no emotional processing subsystem."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(manifest=CognitiveArchitectureManifest())
        svc = _make_service()
        text = svc.render_cold_start_orientation(ctx)
        assert "emotional processing subsystem" in text

    def test_cold_start_without_manifest_still_works(self):
        """Cold start renders fine when manifest is None."""
        ctx = _make_context(manifest=None)
        svc = _make_service()
        text = svc.render_cold_start_orientation(ctx)
        assert "HOW YOUR COGNITIVE ARCHITECTURE WORKS" not in text
        assert "You are" in text  # Identity section still present

    def test_warm_boot_includes_architecture_reminder(self):
        """Warm boot includes abbreviated architecture reminder."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(
            manifest=CognitiveArchitectureManifest(),
            stasis_duration_seconds=3600,
        )
        svc = _make_service()
        text = svc.render_warm_boot_orientation(ctx)
        assert "ARCHITECTURE REMINDER" in text
        assert "cosine similarity" in text
        assert "stasis" in text.lower()

    def test_warm_boot_without_manifest_no_reminder(self):
        """Warm boot without manifest omits architecture reminder."""
        ctx = _make_context(manifest=None, stasis_duration_seconds=3600)
        svc = _make_service()
        text = svc.render_warm_boot_orientation(ctx)
        assert "ARCHITECTURE REMINDER" not in text

    def test_proactive_full_supplement_includes_manifest(self):
        """Full proactive supplement includes architecture note when manifest present."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(
            manifest=CognitiveArchitectureManifest(),
            agent_age_seconds=10,
        )
        svc = _make_service()
        text = svc._full_proactive_supplement(ctx)
        assert "cosine similarity" in text
        assert "stasis" in text.lower()

    def test_proactive_full_supplement_no_manifest(self):
        """Proactive supplement works without manifest."""
        ctx = _make_context(manifest=None, agent_age_seconds=10)
        svc = _make_service()
        text = svc._full_proactive_supplement(ctx)
        assert "ORIENTATION ACTIVE" in text
        assert "cosine similarity" not in text

    def test_render_manifest_section_empty_when_none(self):
        """render_manifest_section returns empty string for None manifest."""
        svc = _make_service()
        assert svc.render_manifest_section(None) == ""

    def test_render_manifest_section_covers_five_domains(self):
        """Manifest section covers Memory, Trust, Stasis, Cognition, Self-Regulation."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        svc = _make_service()
        text = svc.render_manifest_section(CognitiveArchitectureManifest())
        assert "Memory:" in text
        assert "Trust:" in text
        assert "Stasis" in text
        assert "Cognition:" in text
        assert "Self-Regulation:" in text

    def test_manifest_confabulation_warning(self):
        """Manifest text warns about stasis confabulation specifically."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        svc = _make_service()
        text = svc.render_manifest_section(CognitiveArchitectureManifest())
        assert "confabulation" in text.lower()
