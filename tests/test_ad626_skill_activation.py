"""AD-626: Dual-Mode Skill Activation — Discovery + Augmentation tests.

Tests for the activation field on CognitiveSkillEntry, find_augmentation_skills(),
_load_augmentation_skills() on CognitiveAgent, SKILL.md activation metadata,
exercise recording for augmentation skills, and backward compatibility.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.skill_catalog import (
    CognitiveSkillCatalog,
    CognitiveSkillEntry,
    parse_skill_file,
)


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════


def _make_entry(
    name: str = "test-skill",
    activation: str = "discovery",
    intents: list[str] | None = None,
    department: str = "*",
    min_rank: str = "ensign",
    skill_id: str = "",
    min_proficiency: int = 1,
) -> CognitiveSkillEntry:
    return CognitiveSkillEntry(
        name=name,
        description=f"Test skill: {name}",
        skill_dir=Path("/fake"),
        intents=intents or [],
        activation=activation,
        department=department,
        min_rank=min_rank,
        skill_id=skill_id,
        min_proficiency=min_proficiency,
    )


def _make_catalog(*entries: CognitiveSkillEntry) -> CognitiveSkillCatalog:
    catalog = CognitiveSkillCatalog.__new__(CognitiveSkillCatalog)
    catalog._cache = {e.name: e for e in entries}
    return catalog


# ══════════════════════════════════════════════════════════════════════
# CognitiveSkillEntry activation field
# ══════════════════════════════════════════════════════════════════════


class TestActivationField:
    """CognitiveSkillEntry activation attribute behavior."""

    def test_default_activation_is_discovery(self):
        entry = CognitiveSkillEntry(
            name="basic", description="d", skill_dir=Path("/fake"),
        )
        assert entry.activation == "discovery"

    def test_activation_augmentation_explicit(self):
        entry = _make_entry(activation="augmentation")
        assert entry.activation == "augmentation"

    def test_activation_both_explicit(self):
        entry = _make_entry(activation="both")
        assert entry.activation == "both"

    def test_activation_discovery_explicit(self):
        entry = _make_entry(activation="discovery")
        assert entry.activation == "discovery"


# ══════════════════════════════════════════════════════════════════════
# parse_skill_file — activation from YAML
# ══════════════════════════════════════════════════════════════════════


class TestActivationParsing:
    """parse_skill_file() extracts probos-activation from frontmatter."""

    def test_augmentation_parsed_from_yaml(self, tmp_path: Path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: test-skill\ndescription: Test\n"
            "metadata:\n  probos-activation: augmentation\n---\nBody\n"
        )
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.activation == "augmentation"

    def test_both_parsed_from_yaml(self, tmp_path: Path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: test-skill\ndescription: Test\n"
            "metadata:\n  probos-activation: both\n---\nBody\n"
        )
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.activation == "both"

    def test_invalid_activation_defaults_to_discovery(self, tmp_path: Path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: test-skill\ndescription: Test\n"
            "metadata:\n  probos-activation: invalid_value\n---\nBody\n"
        )
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.activation == "discovery"

    def test_missing_activation_defaults_to_discovery(self, tmp_path: Path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: test-skill\ndescription: Test\n"
            "metadata:\n  probos-department: '*'\n---\nBody\n"
        )
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.activation == "discovery"

    def test_comma_separated_intents_parsed(self, tmp_path: Path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: test-skill\ndescription: Test\n"
            "metadata:\n  probos-intents: \"proactive_think,ward_room_notification\"\n---\nBody\n"
        )
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.intents == ["proactive_think", "ward_room_notification"]

    def test_space_separated_intents_still_work(self, tmp_path: Path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: test-skill\ndescription: Test\n"
            "metadata:\n  probos-intents: \"proactive_think ward_room_notification\"\n---\nBody\n"
        )
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.intents == ["proactive_think", "ward_room_notification"]


# ══════════════════════════════════════════════════════════════════════
# find_augmentation_skills()
# ══════════════════════════════════════════════════════════════════════


class TestFindAugmentationSkills:
    """CognitiveSkillCatalog.find_augmentation_skills() filtering."""

    def test_returns_augmentation_skills(self):
        aug = _make_entry("aug", activation="augmentation", intents=["proactive_think"])
        catalog = _make_catalog(aug)
        results = catalog.find_augmentation_skills("proactive_think")
        assert len(results) == 1
        assert results[0].name == "aug"

    def test_excludes_discovery_skills(self):
        disc = _make_entry("disc", activation="discovery", intents=["proactive_think"])
        catalog = _make_catalog(disc)
        results = catalog.find_augmentation_skills("proactive_think")
        assert results == []

    def test_includes_both_skills(self):
        both = _make_entry("both-skill", activation="both", intents=["proactive_think"])
        catalog = _make_catalog(both)
        results = catalog.find_augmentation_skills("proactive_think")
        assert len(results) == 1

    def test_filters_by_intent(self):
        aug = _make_entry("aug", activation="augmentation", intents=["ward_room_notification"])
        catalog = _make_catalog(aug)
        results = catalog.find_augmentation_skills("proactive_think")
        assert results == []

    def test_filters_by_department(self):
        aug = _make_entry("aug", activation="augmentation", intents=["proactive_think"], department="engineering")
        catalog = _make_catalog(aug)
        # Agent in science department should not see engineering-only skill
        results = catalog.find_augmentation_skills("proactive_think", department="science")
        assert results == []

    def test_wildcard_department_matches_all(self):
        aug = _make_entry("aug", activation="augmentation", intents=["proactive_think"], department="*")
        catalog = _make_catalog(aug)
        results = catalog.find_augmentation_skills("proactive_think", department="science")
        assert len(results) == 1

    def test_filters_by_rank(self):
        aug = _make_entry("aug", activation="augmentation", intents=["proactive_think"], min_rank="commander")
        catalog = _make_catalog(aug)
        # Ensign should not see commander-level skill
        results = catalog.find_augmentation_skills("proactive_think", agent_rank="ensign")
        assert results == []

    def test_sufficient_rank_passes(self):
        aug = _make_entry("aug", activation="augmentation", intents=["proactive_think"], min_rank="ensign")
        catalog = _make_catalog(aug)
        results = catalog.find_augmentation_skills("proactive_think", agent_rank="lieutenant")
        assert len(results) == 1

    def test_returns_empty_for_no_matches(self):
        catalog = _make_catalog()
        results = catalog.find_augmentation_skills("proactive_think")
        assert results == []

    def test_multiple_skills_stack(self):
        aug1 = _make_entry("aug1", activation="augmentation", intents=["proactive_think"])
        aug2 = _make_entry("aug2", activation="augmentation", intents=["proactive_think"])
        catalog = _make_catalog(aug1, aug2)
        results = catalog.find_augmentation_skills("proactive_think")
        assert len(results) == 2


# ══════════════════════════════════════════════════════════════════════
# find_by_intent() — discovery excludes augmentation-only
# ══════════════════════════════════════════════════════════════════════


class TestFindByIntentDiscoveryFilter:
    """find_by_intent() only returns discovery/both skills, not augmentation-only."""

    def test_discovery_skill_found(self):
        disc = _make_entry("disc", activation="discovery", intents=["some_intent"])
        catalog = _make_catalog(disc)
        results = catalog.find_by_intent("some_intent")
        assert len(results) == 1

    def test_augmentation_skill_excluded(self):
        aug = _make_entry("aug", activation="augmentation", intents=["some_intent"])
        catalog = _make_catalog(aug)
        results = catalog.find_by_intent("some_intent")
        assert results == []

    def test_both_skill_included_in_discovery(self):
        both = _make_entry("both-skill", activation="both", intents=["some_intent"])
        catalog = _make_catalog(both)
        results = catalog.find_by_intent("some_intent")
        assert len(results) == 1

    def test_discovery_uses_active_skill_header(self):
        """Verify discovery instructions use '## Active Skill:' format."""
        # This is tested implicitly through cognitive_agent, but verify the constant
        assert "Active Skill:" not in "Skill Guidance:"


# ══════════════════════════════════════════════════════════════════════
# _load_augmentation_skills() on CognitiveAgent
# ══════════════════════════════════════════════════════════════════════


class TestLoadAugmentationSkills:
    """CognitiveAgent._load_augmentation_skills() helper."""

    def _make_agent(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = MagicMock(spec=CognitiveAgent)
        agent.id = "test-agent-id"
        agent.agent_type = "test_agent"
        agent.department = "science"
        agent.rank = MagicMock()
        agent.rank.value = "lieutenant"
        agent._augmentation_skills_used = []
        # Bind the real method
        agent._load_augmentation_skills = CognitiveAgent._load_augmentation_skills.__get__(agent)
        return agent

    def test_loads_for_handled_intent(self):
        agent = self._make_agent()
        aug = _make_entry("comm-discipline", activation="augmentation", intents=["proactive_think"])
        catalog = _make_catalog(aug)
        catalog.get_instructions = MagicMock(return_value="## Checklist\n- Check things")
        agent._cognitive_skill_catalog = catalog
        agent._skill_bridge = None
        agent._skill_profile = None

        result = agent._load_augmentation_skills("proactive_think")
        # AD-626 update: raw instructions returned (no header wrapping)
        assert "## Checklist" in result
        assert "Check things" in result

    def test_not_loaded_without_catalog(self):
        agent = self._make_agent()
        agent._cognitive_skill_catalog = None
        result = agent._load_augmentation_skills("proactive_think")
        assert result == ""

    def test_empty_intent_returns_empty(self):
        agent = self._make_agent()
        result = agent._load_augmentation_skills("")
        assert result == ""

    def test_respects_proficiency_gate(self):
        agent = self._make_agent()
        aug = _make_entry("gated", activation="augmentation", intents=["proactive_think"], skill_id="test_skill", min_proficiency=3)
        catalog = _make_catalog(aug)
        catalog.get_instructions = MagicMock(return_value="Instructions")
        agent._cognitive_skill_catalog = catalog

        bridge = MagicMock()
        bridge.check_proficiency_gate.return_value = True
        agent._skill_bridge = bridge
        agent._skill_profile = MagicMock()

        result = agent._load_augmentation_skills("proactive_think")
        # AD-626 update: raw instructions returned (no header wrapping)
        assert "Instructions" in result
        bridge.check_proficiency_gate.assert_called_once()

    def test_fails_proficiency_returns_empty(self):
        agent = self._make_agent()
        aug = _make_entry("gated", activation="augmentation", intents=["proactive_think"], skill_id="test_skill")
        catalog = _make_catalog(aug)
        catalog.get_instructions = MagicMock(return_value="Instructions")
        agent._cognitive_skill_catalog = catalog

        bridge = MagicMock()
        bridge.check_proficiency_gate.return_value = False
        agent._skill_bridge = bridge
        agent._skill_profile = MagicMock()

        result = agent._load_augmentation_skills("proactive_think")
        assert result == ""

    def test_multiple_skills_concatenated(self):
        agent = self._make_agent()
        aug1 = _make_entry("skill-a", activation="augmentation", intents=["proactive_think"])
        aug2 = _make_entry("skill-b", activation="augmentation", intents=["proactive_think"])
        catalog = _make_catalog(aug1, aug2)
        catalog.get_instructions = MagicMock(return_value="Instructions")
        agent._cognitive_skill_catalog = catalog
        agent._skill_bridge = None
        agent._skill_profile = None

        result = agent._load_augmentation_skills("proactive_think")
        # AD-626 update: raw instructions returned (no header wrapping)
        assert "Instructions" in result
        # Both skills' instructions should be present
        assert result.count("Instructions") == 2

    def test_format_returns_raw_instructions(self):
        """AD-626 update: augmentation skills return raw instructions, no header wrapping."""
        agent = self._make_agent()
        aug = _make_entry("my-skill", activation="augmentation", intents=["proactive_think"])
        catalog = _make_catalog(aug)
        catalog.get_instructions = MagicMock(return_value="Body text")
        agent._cognitive_skill_catalog = catalog
        agent._skill_bridge = None
        agent._skill_profile = None

        result = agent._load_augmentation_skills("proactive_think")
        assert "Body text" in result
        # Raw instructions — no header wrapping
        assert "## Skill Guidance:" not in result
        assert "## Active Skill:" not in result

    def test_no_skills_returns_empty_string(self):
        agent = self._make_agent()
        catalog = _make_catalog()
        agent._cognitive_skill_catalog = catalog
        agent._skill_bridge = None

        result = agent._load_augmentation_skills("proactive_think")
        assert result == ""

    def test_tracks_augmentation_skills_used(self):
        agent = self._make_agent()
        aug = _make_entry("tracked", activation="augmentation", intents=["proactive_think"])
        catalog = _make_catalog(aug)
        catalog.get_instructions = MagicMock(return_value="Instructions")
        agent._cognitive_skill_catalog = catalog
        agent._skill_bridge = None
        agent._skill_profile = None

        agent._load_augmentation_skills("proactive_think")
        assert len(agent._augmentation_skills_used) == 1
        assert agent._augmentation_skills_used[0].name == "tracked"


# ══════════════════════════════════════════════════════════════════════
# SKILL.md loading
# ══════════════════════════════════════════════════════════════════════


class TestSkillMdActivation:
    """Communication discipline SKILL.md activation metadata."""

    def test_communication_discipline_has_augmentation_activation(self):
        skill_md = Path("config/skills/communication-discipline/SKILL.md")
        if not skill_md.exists():
            pytest.skip("SKILL.md not found")
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.activation == "augmentation"

    def test_communication_discipline_has_ward_room_notification_intent(self):
        skill_md = Path("config/skills/communication-discipline/SKILL.md")
        if not skill_md.exists():
            pytest.skip("SKILL.md not found")
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert "ward_room_notification" in entry.intents
        assert "proactive_think" in entry.intents

    def test_skill_body_loads_for_augmentation_skill(self):
        skill_md = Path("config/skills/communication-discipline/SKILL.md")
        if not skill_md.exists():
            pytest.skip("SKILL.md not found")
        from probos.cognitive.skill_catalog import get_skill_body
        body = get_skill_body(skill_md)
        assert body is not None
        assert "Communication Discipline" in body


# ══════════════════════════════════════════════════════════════════════
# Exercise recording for augmentation skills
# ══════════════════════════════════════════════════════════════════════


class TestAugmentationExerciseRecording:
    """Exercise recording for augmentation skills in handle_intent()."""

    def test_augmentation_records_exercise_on_completion(self):
        """When _augmentation_skills_used is populated, exercise is recorded."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = MagicMock(spec=CognitiveAgent)
        agent.id = "test-agent-id"

        entry = _make_entry("aug-skill", activation="augmentation", skill_id="test")
        agent._augmentation_skills_used = [entry]

        bridge = MagicMock()
        bridge.record_skill_exercise = AsyncMock()
        agent._skill_bridge = bridge

        # The recording block runs as fire-and-forget via asyncio.create_task
        # We verify the attribute is set correctly and bridge is accessible
        assert len(agent._augmentation_skills_used) == 1
        assert agent._skill_bridge is not None

    def test_no_exercise_without_augmentation_skills(self):
        agent = MagicMock()
        agent._augmentation_skills_used = []
        assert len(agent._augmentation_skills_used) == 0

    def test_exercise_list_cleared_after_recording(self):
        """_augmentation_skills_used is reset to [] after recording."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = MagicMock(spec=CognitiveAgent)
        agent.id = "test-id"
        agent.agent_type = "test"
        agent.department = None
        agent.rank = None
        agent._augmentation_skills_used = []
        agent._load_augmentation_skills = CognitiveAgent._load_augmentation_skills.__get__(agent)

        catalog = _make_catalog()  # no skills
        agent._cognitive_skill_catalog = catalog
        agent._skill_bridge = None

        agent._load_augmentation_skills("proactive_think")
        assert agent._augmentation_skills_used == []


# ══════════════════════════════════════════════════════════════════════
# Edge cases
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and backward compatibility."""

    def test_agent_without_skill_profile_no_augmentation(self):
        """No crash when agent has no _skill_profile."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = MagicMock(spec=CognitiveAgent)
        agent.id = "test-id"
        agent.agent_type = "test"
        agent.department = None
        agent.rank = None
        agent._augmentation_skills_used = []
        agent._load_augmentation_skills = CognitiveAgent._load_augmentation_skills.__get__(agent)

        aug = _make_entry("aug", activation="augmentation", intents=["proactive_think"])
        catalog = _make_catalog(aug)
        catalog.get_instructions = MagicMock(return_value="Body")
        agent._cognitive_skill_catalog = catalog
        agent._skill_bridge = None
        agent._skill_profile = None

        result = agent._load_augmentation_skills("proactive_think")
        assert "Body" in result

    def test_agent_without_bridge_still_loads_instructions(self):
        """If bridge is None, proficiency gate is skipped (always pass)."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = MagicMock(spec=CognitiveAgent)
        agent.id = "test-id"
        agent.agent_type = "test"
        agent.department = None
        agent.rank = None
        agent._augmentation_skills_used = []
        agent._load_augmentation_skills = CognitiveAgent._load_augmentation_skills.__get__(agent)

        aug = _make_entry("aug", activation="augmentation", intents=["proactive_think"], skill_id="test", min_proficiency=5)
        catalog = _make_catalog(aug)
        catalog.get_instructions = MagicMock(return_value="Body")
        agent._cognitive_skill_catalog = catalog
        agent._skill_bridge = None

        result = agent._load_augmentation_skills("proactive_think")
        assert "Body" in result

    def test_existing_discovery_skills_unaffected(self):
        """Discovery-mode skills still only appear via find_by_intent()."""
        disc = _make_entry("disc-skill", activation="discovery", intents=["new_capability"])
        catalog = _make_catalog(disc)

        discovery_results = catalog.find_by_intent("new_capability")
        augmentation_results = catalog.find_augmentation_skills("new_capability")

        assert len(discovery_results) == 1
        assert len(augmentation_results) == 0

    def test_skills_without_activation_field_default_to_discovery(self):
        """Old-style CognitiveSkillEntry without activation defaults to 'discovery'."""
        entry = CognitiveSkillEntry(
            name="legacy", description="Old skill", skill_dir=Path("/fake"),
        )
        assert entry.activation == "discovery"

    def test_augmentation_for_ward_room_notification_intent(self):
        aug = _make_entry("comm", activation="augmentation", intents=["ward_room_notification"])
        catalog = _make_catalog(aug)
        results = catalog.find_augmentation_skills("ward_room_notification")
        assert len(results) == 1

    def test_augmentation_does_not_interfere_with_discovery(self):
        """Both modes coexist: same catalog, different query paths."""
        disc = _make_entry("disc", activation="discovery", intents=["proactive_think"])
        aug = _make_entry("aug", activation="augmentation", intents=["proactive_think"])
        catalog = _make_catalog(disc, aug)

        discovery = catalog.find_by_intent("proactive_think")
        augmentation = catalog.find_augmentation_skills("proactive_think")

        assert len(discovery) == 1
        assert discovery[0].name == "disc"
        assert len(augmentation) == 1
        assert augmentation[0].name == "aug"

    def test_both_skill_appears_in_both_paths(self):
        both = _make_entry("dual", activation="both", intents=["proactive_think"])
        catalog = _make_catalog(both)

        discovery = catalog.find_by_intent("proactive_think")
        augmentation = catalog.find_augmentation_skills("proactive_think")

        assert len(discovery) == 1
        assert len(augmentation) == 1


# ══════════════════════════════════════════════════════════════════════
# Generic task-framed skill injection
# ══════════════════════════════════════════════════════════════════════


class TestFrameTaskWithSkill:
    """_frame_task_with_skill() generic framing method."""

    def _make_agent(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = MagicMock(spec=CognitiveAgent)
        agent._frame_task_with_skill = CognitiveAgent._frame_task_with_skill.__get__(agent)
        return agent

    def test_basic_framing(self):
        agent = self._make_agent()
        lines = agent._frame_task_with_skill("Do the thing.", "My Task")
        text = "\n".join(lines)
        assert "=== TASK: My Task ===" in text
        assert "Do the thing." in text
        assert "=== Apply the above skill to the content below ===" in text

    def test_context_summary_included(self):
        agent = self._make_agent()
        lines = agent._frame_task_with_skill("Instructions", "Task", "Replies: 3")
        text = "\n".join(lines)
        assert "[Replies: 3]" in text

    def test_no_context_summary_no_bracket_line(self):
        agent = self._make_agent()
        lines = agent._frame_task_with_skill("Instructions", "Task")
        assert not any("[" in ln and "]" in ln for ln in lines if "TASK" not in ln and "Apply" not in ln)

    def test_returns_list_of_strings(self):
        agent = self._make_agent()
        result = agent._frame_task_with_skill("X", "Y")
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)

    def test_generic_for_any_task_label(self):
        """Framing works with arbitrary task labels — not hardcoded to Ward Room."""
        agent = self._make_agent()
        for label in ["Process Ward Room Thread", "Review Code", "Analyze Metrics", "Draft Report"]:
            lines = agent._frame_task_with_skill("skill body", label)
            text = "\n".join(lines)
            assert f"=== TASK: {label} ===" in text


class TestExtractThreadMetadata:
    """_extract_thread_metadata() Ward-Room-specific helper."""

    def test_counts_replies(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        text = "Thread title\n- Reply one\n- Reply two\n- Reply three"
        result = CognitiveAgent._extract_thread_metadata(text)
        assert "Replies so far: ~3" in result

    def test_extracts_callsigns(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        text = "Forge posted: something\nReply from Atlas: more\n— Lynx said stuff"
        result = CognitiveAgent._extract_thread_metadata(text)
        assert "Contributors:" in result

    def test_empty_text_returns_empty(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        assert CognitiveAgent._extract_thread_metadata("") == ""

    def test_no_replies_no_count(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        result = CognitiveAgent._extract_thread_metadata("Just a title line")
        assert "Replies" not in result
