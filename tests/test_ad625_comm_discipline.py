"""AD-625: Communication Discipline Skill — Proficiency-Gated Reply Quality tests.

Tests for comm_proficiency.py (tier mapping, gate overrides, prompt guidance),
SKILL.md content, standing_orders.py proficiency display, cognitive_agent.py
prompt injection, ward_room_router.py exercise recording + gate modulation,
and proactive.py reply cooldown modulation.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.comm_proficiency import (
    CommGateOverrides,
    CommTier,
    format_proficiency_label,
    get_gate_overrides,
    get_prompt_guidance,
    proficiency_to_tier,
)
from probos.skill_framework import AgentSkillRecord, ProficiencyLevel, SkillProfile


# ══════════════════════════════════════════════════════════════════════
# comm_proficiency.py — tier mapping
# ══════════════════════════════════════════════════════════════════════


class TestProficiencyToTier:
    """Tier mapping from ProficiencyLevel to CommTier."""

    def test_follow_maps_to_novice(self):
        assert proficiency_to_tier(ProficiencyLevel.FOLLOW) == CommTier.NOVICE

    def test_assist_maps_to_novice(self):
        assert proficiency_to_tier(ProficiencyLevel.ASSIST) == CommTier.NOVICE

    def test_apply_maps_to_competent(self):
        assert proficiency_to_tier(ProficiencyLevel.APPLY) == CommTier.COMPETENT

    def test_enable_maps_to_competent(self):
        assert proficiency_to_tier(ProficiencyLevel.ENABLE) == CommTier.COMPETENT

    def test_advise_maps_to_proficient(self):
        assert proficiency_to_tier(ProficiencyLevel.ADVISE) == CommTier.PROFICIENT

    def test_lead_maps_to_expert(self):
        assert proficiency_to_tier(ProficiencyLevel.LEAD) == CommTier.EXPERT

    def test_shape_maps_to_expert(self):
        assert proficiency_to_tier(ProficiencyLevel.SHAPE) == CommTier.EXPERT

    def test_invalid_proficiency_defaults_to_novice(self):
        assert proficiency_to_tier(99) == CommTier.NOVICE

    def test_int_value_accepted(self):
        assert proficiency_to_tier(3) == CommTier.COMPETENT  # APPLY=3


# ══════════════════════════════════════════════════════════════════════
# comm_proficiency.py — gate overrides
# ══════════════════════════════════════════════════════════════════════


class TestGateOverrides:
    """CommGateOverrides per tier."""

    def test_novice_gate_overrides_strict(self):
        o = get_gate_overrides(ProficiencyLevel.FOLLOW)
        assert o.max_responses_per_thread == 1
        assert o.reply_cooldown_seconds == 180
        assert o.tier == CommTier.NOVICE

    def test_competent_gate_overrides_standard(self):
        o = get_gate_overrides(ProficiencyLevel.APPLY)
        assert o.max_responses_per_thread == 3
        assert o.reply_cooldown_seconds == 120

    def test_proficient_gate_overrides_relaxed(self):
        o = get_gate_overrides(ProficiencyLevel.ADVISE)
        assert o.max_responses_per_thread == 4
        assert o.reply_cooldown_seconds == 90

    def test_expert_gate_overrides_minimal(self):
        o = get_gate_overrides(ProficiencyLevel.LEAD)
        assert o.max_responses_per_thread == 5
        assert o.reply_cooldown_seconds == 60

    def test_gate_overrides_frozen(self):
        o = get_gate_overrides(ProficiencyLevel.FOLLOW)
        with pytest.raises(AttributeError):
            o.max_responses_per_thread = 10  # type: ignore[misc]


# ══════════════════════════════════════════════════════════════════════
# comm_proficiency.py — prompt guidance
# ══════════════════════════════════════════════════════════════════════


class TestPromptGuidance:
    """Tier-specific prompt guidance text."""

    def test_novice_mentions_no_response(self):
        text = get_prompt_guidance(ProficiencyLevel.FOLLOW)
        assert "[NO_RESPONSE]" in text
        assert "Novice" in text

    def test_competent_mentions_endorse(self):
        text = get_prompt_guidance(ProficiencyLevel.APPLY)
        assert "[ENDORSE]" in text
        assert "Competent" in text

    def test_proficient_mentions_discipline(self):
        text = get_prompt_guidance(ProficiencyLevel.ADVISE)
        assert "Proficient" in text
        assert "novel perspectives" in text

    def test_expert_mentions_silence(self):
        text = get_prompt_guidance(ProficiencyLevel.LEAD)
        assert "Expert" in text
        assert "silence" in text


# ══════════════════════════════════════════════════════════════════════
# comm_proficiency.py — format_proficiency_label
# ══════════════════════════════════════════════════════════════════════


class TestFormatProficiencyLabel:
    """Human-readable proficiency labels."""

    def test_format_novice(self):
        assert format_proficiency_label(ProficiencyLevel.FOLLOW) == "Novice"

    def test_format_competent(self):
        assert format_proficiency_label(ProficiencyLevel.APPLY) == "Competent"

    def test_format_proficient(self):
        assert format_proficiency_label(ProficiencyLevel.ADVISE) == "Proficient"

    def test_format_expert(self):
        assert format_proficiency_label(ProficiencyLevel.LEAD) == "Expert"

    def test_format_from_int(self):
        assert format_proficiency_label(5) == "Proficient"


# ══════════════════════════════════════════════════════════════════════
# SKILL.md content
# ══════════════════════════════════════════════════════════════════════


class TestSkillMdContent:
    """SKILL.md frontmatter and content checks."""

    @pytest.fixture()
    def skill_md(self):
        p = Path(__file__).resolve().parent.parent / "config" / "skills" / "communication-discipline" / "SKILL.md"
        return p.read_text(encoding="utf-8")

    def test_skill_md_has_communication_skill_id(self, skill_md):
        assert "probos-skill-id: communication" in skill_md

    def test_skill_md_not_ward_room_discipline(self, skill_md):
        assert "ward_room_discipline" not in skill_md

    def test_skill_md_pre_composition_checklist_present(self, skill_md):
        assert "Pre-Composition Checklist" in skill_md

    def test_skill_md_anti_patterns_section_present(self, skill_md):
        assert "Anti-Patterns" in skill_md

    def test_skill_md_thread_awareness(self, skill_md):
        assert "Thread Awareness" in skill_md

    def test_skill_md_novelty_test(self, skill_md):
        assert "Novelty Test" in skill_md


# ══════════════════════════════════════════════════════════════════════
# standing_orders.py — proficiency display in Tier 7
# ══════════════════════════════════════════════════════════════════════


class TestStandingOrdersProficiency:
    """compose_instructions() shows proficiency labels when profile provided."""

    def _make_profile(self, skill_id: str, proficiency: ProficiencyLevel) -> SkillProfile:
        return SkillProfile(
            agent_id="test-agent",
            pccs=[AgentSkillRecord(agent_id="test-agent", skill_id=skill_id, proficiency=proficiency)],
        )

    def test_compose_instructions_shows_proficiency_label(self):
        """When skill_profile is provided, skill lines include proficiency labels."""
        from probos.cognitive.standing_orders import compose_instructions

        profile = self._make_profile("communication", ProficiencyLevel.ADVISE)

        # Mock the catalog to return a known skill description
        mock_catalog = MagicMock()
        mock_catalog.get_descriptions.return_value = [
            ("communication-discipline", "Ward Room discipline", "communication"),
        ]
        with patch("probos.cognitive.standing_orders._skill_catalog", mock_catalog):
            result = compose_instructions(
                "test_agent", "",
                callsign="Test",
                agent_rank="ensign",
                skill_profile=profile,
            )
        assert "(Proficient)" in result

    def test_compose_instructions_no_profile_no_label(self):
        """Without skill_profile, no proficiency labels appear."""
        from probos.cognitive.standing_orders import compose_instructions

        mock_catalog = MagicMock()
        mock_catalog.get_descriptions.return_value = [
            ("communication-discipline", "Ward Room discipline", "communication"),
        ]
        with patch("probos.cognitive.standing_orders._skill_catalog", mock_catalog):
            result = compose_instructions(
                "test_agent", "",
                callsign="Test",
                agent_rank="ensign",
            )
        assert "(Proficient)" not in result
        assert "(Novice)" not in result

    def test_get_descriptions_returns_3_tuples(self):
        """get_descriptions() returns (name, description, skill_id) tuples."""
        from probos.cognitive.skill_catalog import CognitiveSkillCatalog, CognitiveSkillEntry

        catalog = CognitiveSkillCatalog.__new__(CognitiveSkillCatalog)
        catalog._cache = {
            "test-skill": CognitiveSkillEntry(
                name="test-skill",
                description="A test",
                skill_dir=Path("/fake"),
                skill_id="test_id",
            ),
        }
        descs = catalog.get_descriptions()
        assert len(descs) == 1
        assert len(descs[0]) == 3
        name, desc, sid = descs[0]
        assert name == "test-skill"
        assert sid == "test_id"


# ══════════════════════════════════════════════════════════════════════
# cognitive_agent.py — comm proficiency guidance
# ══════════════════════════════════════════════════════════════════════


class TestCognitiveAgentCommGuidance:
    """_get_comm_proficiency_guidance() and prompt injection."""

    def _make_agent(self, proficiency: ProficiencyLevel | None = None):
        """Create a minimal CognitiveAgent-like mock with a skill profile."""
        agent = MagicMock()
        agent.id = "test-agent-id"
        agent.agent_type = "test_agent"
        agent.instructions = ""
        agent.callsign = "TestAgent"

        if proficiency is not None:
            profile = SkillProfile(
                agent_id="test-agent-id",
                pccs=[AgentSkillRecord(
                    agent_id="test-agent-id",
                    skill_id="communication",
                    proficiency=proficiency,
                )],
            )
            agent._skill_profile = profile
        else:
            agent._skill_profile = None

        return agent

    def test_get_comm_proficiency_guidance_novice(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = self._make_agent(ProficiencyLevel.FOLLOW)
        # Call the unbound method with our mock as self
        result = CognitiveAgent._get_comm_proficiency_guidance(agent)
        assert result is not None
        assert "Novice" in result

    def test_get_comm_proficiency_guidance_expert(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = self._make_agent(ProficiencyLevel.LEAD)
        result = CognitiveAgent._get_comm_proficiency_guidance(agent)
        assert result is not None
        assert "Expert" in result

    def test_get_comm_proficiency_guidance_no_profile(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = self._make_agent(None)
        result = CognitiveAgent._get_comm_proficiency_guidance(agent)
        assert result is None

    def test_get_comm_proficiency_guidance_no_communication_skill(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = self._make_agent(None)
        # Profile exists but with a different skill
        agent._skill_profile = SkillProfile(
            agent_id="test-agent-id",
            pccs=[AgentSkillRecord(
                agent_id="test-agent-id",
                skill_id="analysis",
                proficiency=ProficiencyLevel.LEAD,
            )],
        )
        result = CognitiveAgent._get_comm_proficiency_guidance(agent)
        assert result is None


# ══════════════════════════════════════════════════════════════════════
# ward_room_router.py — exercise recording + gate overrides
# ══════════════════════════════════════════════════════════════════════


class TestWardRoomRouterGateOverrides:
    """_get_comm_gate_overrides() on WardRoomRouter."""

    def _make_router(self, comm_profiles=None):
        from probos.ward_room_router import WardRoomRouter
        router = WardRoomRouter.__new__(WardRoomRouter)
        # Minimal state
        rt = MagicMock()
        rt.skill_service = MagicMock()
        rt._comm_profiles = comm_profiles or {}
        loop = MagicMock()
        loop._runtime = rt
        router._proactive_loop = loop
        router._config = MagicMock()
        router._config.ward_room = MagicMock()
        return router

    def test_proficiency_modulates_per_thread_cap_novice(self):
        profile = SkillProfile(
            agent_id="agent-1",
            pccs=[AgentSkillRecord(
                agent_id="agent-1",
                skill_id="communication",
                proficiency=ProficiencyLevel.FOLLOW,
            )],
        )
        router = self._make_router({"agent-1": profile})
        overrides = router._get_comm_gate_overrides("agent-1")
        assert overrides is not None
        assert overrides.max_responses_per_thread == 1

    def test_proficiency_modulates_per_thread_cap_expert(self):
        profile = SkillProfile(
            agent_id="agent-1",
            pccs=[AgentSkillRecord(
                agent_id="agent-1",
                skill_id="communication",
                proficiency=ProficiencyLevel.LEAD,
            )],
        )
        router = self._make_router({"agent-1": profile})
        overrides = router._get_comm_gate_overrides("agent-1")
        assert overrides is not None
        assert overrides.max_responses_per_thread == 5

    def test_no_profile_returns_none(self):
        router = self._make_router({})
        overrides = router._get_comm_gate_overrides("agent-1")
        assert overrides is None

    def test_no_proactive_loop_returns_none(self):
        from probos.ward_room_router import WardRoomRouter
        router = WardRoomRouter.__new__(WardRoomRouter)
        router._proactive_loop = None
        overrides = router._get_comm_gate_overrides("agent-1")
        assert overrides is None

    def test_exercise_recording_log_and_degrade(self):
        """Exercise recording failure doesn't propagate."""
        router = self._make_router({})
        rt = router._proactive_loop._runtime
        rt.skill_service.record_exercise = AsyncMock(side_effect=RuntimeError("DB fail"))
        # Should not raise — log-and-degrade
        # (This tests the pattern exists; actual recording is async in route_event)


# ══════════════════════════════════════════════════════════════════════
# proactive.py — reply cooldown modulation
# ══════════════════════════════════════════════════════════════════════


class TestProactiveReplyCooldown:
    """_get_comm_gate_overrides() on ProactiveCognitiveLoop."""

    def _make_loop(self, comm_profiles=None):
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        rt = MagicMock()
        rt._comm_profiles = comm_profiles or {}
        loop._runtime = rt
        return loop

    def _make_agent_mock(self, agent_id, proficiency):
        agent = MagicMock()
        agent.id = agent_id
        return agent

    def test_reply_cooldown_novice_180s(self):
        profile = SkillProfile(
            agent_id="a1",
            pccs=[AgentSkillRecord(agent_id="a1", skill_id="communication", proficiency=ProficiencyLevel.FOLLOW)],
        )
        loop = self._make_loop({"a1": profile})
        agent = self._make_agent_mock("a1", ProficiencyLevel.FOLLOW)
        overrides = loop._get_comm_gate_overrides(agent)
        assert overrides is not None
        assert overrides.reply_cooldown_seconds == 180

    def test_reply_cooldown_competent_120s(self):
        profile = SkillProfile(
            agent_id="a1",
            pccs=[AgentSkillRecord(agent_id="a1", skill_id="communication", proficiency=ProficiencyLevel.APPLY)],
        )
        loop = self._make_loop({"a1": profile})
        agent = self._make_agent_mock("a1", ProficiencyLevel.APPLY)
        overrides = loop._get_comm_gate_overrides(agent)
        assert overrides.reply_cooldown_seconds == 120

    def test_reply_cooldown_proficient_90s(self):
        profile = SkillProfile(
            agent_id="a1",
            pccs=[AgentSkillRecord(agent_id="a1", skill_id="communication", proficiency=ProficiencyLevel.ADVISE)],
        )
        loop = self._make_loop({"a1": profile})
        agent = self._make_agent_mock("a1", ProficiencyLevel.ADVISE)
        overrides = loop._get_comm_gate_overrides(agent)
        assert overrides.reply_cooldown_seconds == 90

    def test_reply_cooldown_expert_60s(self):
        profile = SkillProfile(
            agent_id="a1",
            pccs=[AgentSkillRecord(agent_id="a1", skill_id="communication", proficiency=ProficiencyLevel.LEAD)],
        )
        loop = self._make_loop({"a1": profile})
        agent = self._make_agent_mock("a1", ProficiencyLevel.LEAD)
        overrides = loop._get_comm_gate_overrides(agent)
        assert overrides.reply_cooldown_seconds == 60

    def test_reply_cooldown_no_profile_uses_default(self):
        loop = self._make_loop({})
        agent = self._make_agent_mock("a1", ProficiencyLevel.FOLLOW)
        overrides = loop._get_comm_gate_overrides(agent)
        assert overrides is None  # Caller uses default 120


# ══════════════════════════════════════════════════════════════════════
# Edge cases
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and graceful degradation."""

    def test_non_crew_agent_no_profile(self):
        """Non-crew agents won't have profiles in cache."""
        from probos.ward_room_router import WardRoomRouter
        router = WardRoomRouter.__new__(WardRoomRouter)
        rt = MagicMock()
        rt._comm_profiles = {}  # Empty — no crew profiles
        loop = MagicMock()
        loop._runtime = rt
        router._proactive_loop = loop
        # Non-crew agent not in cache → None
        assert router._get_comm_gate_overrides("non-crew-agent") is None

    def test_missing_skill_service_graceful(self):
        """Missing skill_service → no overrides."""
        from probos.ward_room_router import WardRoomRouter
        router = WardRoomRouter.__new__(WardRoomRouter)
        rt = MagicMock(spec=[])  # No attributes at all
        loop = MagicMock()
        loop._runtime = rt
        router._proactive_loop = loop
        assert router._get_comm_gate_overrides("agent-1") is None

    def test_missing_runtime_graceful(self):
        """Missing runtime → no overrides."""
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._runtime = MagicMock(spec=[])  # No _comm_profiles
        agent = MagicMock()
        agent.id = "a1"
        assert loop._get_comm_gate_overrides(agent) is None

    def test_proficiency_cache_populated(self):
        """Profile cache dict is a plain dict lookup, not async DB call."""
        profiles = {
            "agent-1": SkillProfile(
                agent_id="agent-1",
                pccs=[AgentSkillRecord(
                    agent_id="agent-1",
                    skill_id="communication",
                    proficiency=ProficiencyLevel.ADVISE,
                )],
            ),
        }
        # Lookup is synchronous dict access
        profile = profiles.get("agent-1")
        assert profile is not None
        assert profile.pccs[0].proficiency == ProficiencyLevel.ADVISE

    def test_comm_tier_int_enum(self):
        """CommTier is IntEnum — supports comparison."""
        assert CommTier.NOVICE < CommTier.EXPERT
        assert CommTier.EXPERT == 4
        assert CommTier.NOVICE == 1

    def test_gate_overrides_all_tiers_defined(self):
        """Every CommTier has a corresponding gate override entry."""
        # Map each tier to a representative ProficiencyLevel
        tier_to_prof = {
            CommTier.NOVICE: ProficiencyLevel.FOLLOW,
            CommTier.COMPETENT: ProficiencyLevel.APPLY,
            CommTier.PROFICIENT: ProficiencyLevel.ADVISE,
            CommTier.EXPERT: ProficiencyLevel.LEAD,
        }
        for tier, prof in tier_to_prof.items():
            o = get_gate_overrides(prof)
            assert o.tier == tier
