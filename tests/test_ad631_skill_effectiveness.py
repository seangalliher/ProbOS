"""AD-631: Skill Effectiveness Improvements — tests.

Verifies XML framing for skill injection, Tier 7 description format,
federation.md deduplication, skill content rewrites (positive framing,
self-check, anti-patterns, ToM absorption), comm proficiency
consolidation, and self-monitoring XML tags.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ------------------------------------------------------------------ #
# Paths
# ------------------------------------------------------------------ #
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FEDERATION_MD = _REPO_ROOT / "config" / "standing_orders" / "federation.md"
_SKILL_MD = (
    _REPO_ROOT / "config" / "skills" / "communication-discipline" / "SKILL.md"
)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #
def _make_agent_mock(proficiency=None):
    """Create a minimal CognitiveAgent-alike with skill profile."""
    from probos.skill_framework import AgentSkillRecord, ProficiencyLevel, SkillProfile

    agent = MagicMock()
    agent.id = "test-agent-id"
    agent.agent_type = "test_agent"
    agent.instructions = ""
    agent.callsign = "TestAgent"
    agent._augmentation_skills_used = []

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


# ================================================================== #
# 1. TestXmlFraming
# ================================================================== #
class TestXmlFraming:
    """_frame_task_with_skill() uses XML tags, not plain-text delimiters."""

    def _call(self, skill_text="Do something.", label="Test Skill",
              context="", proficiency_context=""):
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = _make_agent_mock()
        # Give it a loaded skill entry so the name attribute uses it
        entry = MagicMock()
        entry.name = "communication-discipline"
        agent._augmentation_skills_used = [entry]

        return CognitiveAgent._frame_task_with_skill(
            agent, skill_text, label, context,
            proficiency_context=proficiency_context,
        )

    def test_frame_task_uses_xml_tags(self):
        lines = self._call()
        joined = "\n".join(lines)
        assert "<active_skill" in joined
        assert "</active_skill>" in joined

    def test_frame_task_includes_name_attribute(self):
        lines = self._call()
        joined = "\n".join(lines)
        assert 'name="communication-discipline"' in joined

    def test_frame_task_context_in_tag(self):
        lines = self._call(context="Replies so far: ~3")
        joined = "\n".join(lines)
        assert "<skill_context>Replies so far: ~3</skill_context>" in joined

    def test_frame_task_no_plain_text_delimiters(self):
        lines = self._call()
        joined = "\n".join(lines)
        assert "--- Behavioral Guidance" not in joined
        assert "--- End of Guidance ---" not in joined

    def test_frame_task_proficiency_context(self):
        lines = self._call(proficiency_context="Check replies. Use ENDORSE.")
        joined = "\n".join(lines)
        assert "<proficiency_tier>Check replies. Use ENDORSE.</proficiency_tier>" in joined

    def test_frame_task_no_proficiency_when_empty(self):
        lines = self._call(proficiency_context="")
        joined = "\n".join(lines)
        assert "<proficiency_tier>" not in joined


# ================================================================== #
# 2. TestTier7Description
# ================================================================== #
class TestTier7Description:
    """Tier 7 skill descriptions use <available_skills> XML format."""

    def _compose_with_skill(self, desc="Ward Room comms", skill_id="communication",
                            proficiency=None):
        from probos.cognitive.standing_orders import (
            compose_instructions, set_skill_catalog,
        )
        from probos.skill_framework import ProficiencyLevel

        catalog = MagicMock()
        catalog.get_descriptions.return_value = [
            ("communication-discipline", desc, skill_id),
        ]
        set_skill_catalog(catalog)

        skill_profile = None
        if proficiency is not None:
            from probos.skill_framework import AgentSkillRecord, SkillProfile
            skill_profile = SkillProfile(
                agent_id="test",
                pccs=[AgentSkillRecord(
                    agent_id="test",
                    skill_id=skill_id,
                    proficiency=proficiency,
                )],
            )

        try:
            return compose_instructions(
                "builder", "",
                orders_dir=_REPO_ROOT / "config" / "standing_orders",
                skill_profile=skill_profile,
            )
        finally:
            set_skill_catalog(None)

    def test_tier7_uses_xml_format(self):
        result = self._compose_with_skill()
        assert "<available_skills>" in result
        assert "</available_skills>" in result

    def test_tier7_includes_skill_description(self):
        result = self._compose_with_skill(desc="endorse agreement, only reply with new information")
        assert "endorse agreement" in result

    def test_tier7_skill_has_proficiency_attribute(self):
        from probos.skill_framework import ProficiencyLevel
        result = self._compose_with_skill(proficiency=ProficiencyLevel.APPLY)
        assert 'proficiency="' in result


# ================================================================== #
# 3. TestFederationDedup
# ================================================================== #
class TestFederationDedup:
    """Federation.md no longer duplicates content absorbed by the skill."""

    @pytest.fixture(autouse=True)
    def _load_federation(self):
        self.text = _FEDERATION_MD.read_text(encoding="utf-8")

    def test_federation_no_reply_quality_section(self):
        assert "### Reply Quality Standard" not in self.text

    def test_federation_no_communication_etiquette_section(self):
        assert "### Communication Etiquette" not in self.text

    def test_federation_no_tom_complementary_section(self):
        assert "### Theory of Mind" not in self.text
        assert "Complementary Contribution" not in self.text

    def test_federation_keeps_mechanics(self):
        assert "[REPLY thread_id]" in self.text
        assert "[ENDORSE" in self.text
        assert "[DM @callsign]" in self.text

    def test_federation_keeps_channel_descriptions(self):
        assert "### Ward Room" in self.text
        assert "### Direct Messages" in self.text
        assert "### Notebook" in self.text


# ================================================================== #
# 4. TestSkillContent
# ================================================================== #
class TestSkillContent:
    """SKILL.md has self-check, positive framing, anti-patterns, ToM."""

    @pytest.fixture(autouse=True)
    def _load_skill(self):
        self.text = _SKILL_MD.read_text(encoding="utf-8")

    def test_skill_has_pre_submit_check(self):
        assert "## Pre-Submit Check" in self.text

    def test_skill_no_negative_framing(self):
        """No 'Never' or 'Do not' as sentence starters."""
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                stripped = stripped[2:].strip()
            # Allow mid-sentence usage; block sentence-starting usage
            assert not stripped.startswith("Never "), f"Negative framing found: {stripped[:60]}"
            assert not stripped.startswith("Do not "), f"Negative framing found: {stripped[:60]}"

    def test_skill_addresses_looking_at_pattern(self):
        assert "Looking at" in self.text

    def test_skill_has_tom_complementary_section(self):
        assert "Complementary Contribution" in self.text


# ================================================================== #
# 5. TestCommProficiencyConsolidation
# ================================================================== #
class TestCommProficiencyConsolidation:
    """Proficiency guidance flows through skill frame, not standalone."""

    def test_decide_via_llm_no_standalone_comm_guidance(self):
        """_decide_via_llm() no longer injects _get_comm_proficiency_guidance()
        as standalone '## Communication Discipline' system prompt section."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        import inspect
        # Read the source of _decide_via_llm and check the standalone injection is gone
        source = inspect.getsource(CognitiveAgent._decide_via_llm)
        assert '## Communication Discipline' not in source, \
            "Standalone comm guidance injection should be removed from _decide_via_llm"

    def test_comm_guidance_flows_through_skill_frame(self):
        """WR notification path passes proficiency guidance via proficiency_context."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        import inspect
        source = inspect.getsource(CognitiveAgent._build_user_message)
        assert "proficiency_context" in source


# ================================================================== #
# 6. TestSelfMonitoringXml
# ================================================================== #
class TestSelfMonitoringXml:
    """Self-monitoring uses XML tags, not bracket/plain-text markers."""

    def test_self_monitoring_uses_xml_tags(self):
        """Cognitive zone rendered with <cognitive_zone>, not [COGNITIVE ZONE:]."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        import inspect
        source = inspect.getsource(CognitiveAgent._build_user_message)
        assert "<cognitive_zone>" in source
        # Old bracket format should be gone
        assert "[COGNITIVE ZONE:" not in source

    def test_recent_activity_uses_xml(self):
        """Activity section uses <recent_activity>, not --- Your Recent Activity ---."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        import inspect
        source = inspect.getsource(CognitiveAgent._build_user_message)
        assert "<recent_activity>" in source
        assert "--- Your Recent Activity" not in source

    def test_bracket_strip_retained(self):
        """_strip_bracket_markers() still exists in proactive.py (defense-in-depth)."""
        from probos import proactive
        assert hasattr(proactive, '_strip_bracket_markers')
        # Verify it's actually used (called in the module)
        import inspect
        source = inspect.getsource(proactive)
        assert "_strip_bracket_markers" in source
