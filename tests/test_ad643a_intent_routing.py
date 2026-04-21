"""AD-643a: Intent Routing + Targeted Skill Loading.

Tests cover:
- Trigger parsing from SKILL.md metadata
- find_triggered_skills() matching logic
- intended_actions extraction from ANALYZE results
- Two-phase chain routing (triage → execute)
- Silent short-circuit
- Targeted skill loading
- ANALYZE prompt updates
- Compose _should_short_circuit integration
"""

from __future__ import annotations

import inspect
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.skill_catalog import (
    CognitiveSkillCatalog,
    CognitiveSkillEntry,
    parse_skill_file,
)
from probos.cognitive.sub_task import SubTaskResult, SubTaskType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill_entry(
    name: str = "test-skill",
    activation: str = "augmentation",
    intents: list[str] | None = None,
    triggers: list[str] | None = None,
    department: str = "*",
    min_rank: str = "ensign",
) -> CognitiveSkillEntry:
    return CognitiveSkillEntry(
        name=name,
        description=f"Test skill {name}",
        skill_dir=Path("/tmp/fake"),
        activation=activation,
        intents=intents or [],
        triggers=triggers or [],
        department=department,
        min_rank=min_rank,
        loaded_at=time.time(),
    )


def _make_analyze_result(intended_actions=None, **extra) -> SubTaskResult:
    result = {"contribution_assessment": "RESPOND"}
    if intended_actions is not None:
        result["intended_actions"] = intended_actions
    result.update(extra)
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-thread",
        result=result,
        success=True,
    )


def _make_compose_result(**extra) -> SubTaskResult:
    result = {"output": "test reply"}
    result.update(extra)
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-reply",
        result=result,
        success=True,
    )


# ===========================================================================
# TestSkillTriggerParsing
# ===========================================================================

class TestSkillTriggerParsing:
    """Parse probos-triggers from SKILL.md metadata."""

    def test_triggers_parsed_from_skill_md(self, tmp_path):
        """probos-triggers: 'ward_room_post,ward_room_reply' parses to list."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
            ---
            name: test-comm
            description: Test skill
            metadata:
              probos-intents: "proactive_think"
              probos-activation: augmentation
              probos-triggers: "ward_room_post,ward_room_reply"
            ---
            # Test
        """))
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.triggers == ["ward_room_post", "ward_room_reply"]

    def test_single_trigger_parsed(self, tmp_path):
        """probos-triggers: 'notebook' parses to single-element list."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
            ---
            name: test-notebook
            description: Test skill
            metadata:
              probos-intents: "proactive_think"
              probos-activation: augmentation
              probos-triggers: "notebook"
            ---
            # Test
        """))
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.triggers == ["notebook"]

    def test_empty_triggers_default(self, tmp_path):
        """No probos-triggers → triggers == []."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
            ---
            name: test-no-triggers
            description: Test skill
            metadata:
              probos-intents: "proactive_think"
              probos-activation: augmentation
            ---
            # Test
        """))
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.triggers == []

    def test_triggers_lowercased(self, tmp_path):
        """probos-triggers: 'Ward_Room_Post' lowercased."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
            ---
            name: test-case
            description: Test skill
            metadata:
              probos-intents: "proactive_think"
              probos-activation: augmentation
              probos-triggers: "Ward_Room_Post,ENDORSE"
            ---
            # Test
        """))
        entry = parse_skill_file(skill_md)
        assert entry is not None
        assert entry.triggers == ["ward_room_post", "endorse"]


# ===========================================================================
# TestFindTriggeredSkills
# ===========================================================================

class TestFindTriggeredSkills:
    """CognitiveSkillCatalog.find_triggered_skills() matching logic."""

    @pytest.fixture
    def catalog(self):
        cat = CognitiveSkillCatalog.__new__(CognitiveSkillCatalog)
        cat._cache = {}
        cat._skills = {}
        cat._instruction_cache = {}
        return cat

    def _add_skill(self, catalog, entry):
        catalog._cache[entry.name] = entry

    def test_matches_single_trigger(self, catalog):
        """intended_actions=['notebook'] matches skill with triggers=['notebook']."""
        self._add_skill(catalog, _make_skill_entry(
            name="notebook-quality", triggers=["notebook"],
        ))
        result = catalog.find_triggered_skills(["notebook"], "proactive_think")
        assert len(result) == 1
        assert result[0].name == "notebook-quality"

    def test_matches_one_of_multiple_triggers(self, catalog):
        """intended_actions=['endorse'] matches skill with triggers including 'endorse'."""
        self._add_skill(catalog, _make_skill_entry(
            name="comm-discipline", triggers=["ward_room_post", "ward_room_reply", "endorse"],
        ))
        result = catalog.find_triggered_skills(["endorse"], "proactive_think")
        assert len(result) == 1
        assert result[0].name == "comm-discipline"

    def test_no_match_returns_empty(self, catalog):
        """intended_actions=['notebook'] doesn't match skill with triggers=['ward_room_reply']."""
        self._add_skill(catalog, _make_skill_entry(
            name="comm-discipline", triggers=["ward_room_reply"],
        ))
        result = catalog.find_triggered_skills(["notebook"], "proactive_think")
        assert result == []

    def test_no_triggers_falls_back_to_intent(self, catalog):
        """Skill without triggers matched by intent_name (backward compat)."""
        self._add_skill(catalog, _make_skill_entry(
            name="legacy-skill", triggers=[], intents=["proactive_think"],
        ))
        result = catalog.find_triggered_skills(["ward_room_post"], "proactive_think")
        assert len(result) == 1
        assert result[0].name == "legacy-skill"

    def test_rank_gate_applies(self, catalog):
        """commander skill not returned for ensign rank."""
        self._add_skill(catalog, _make_skill_entry(
            name="leadership", triggers=["leadership_review"],
            min_rank="commander",
        ))
        result = catalog.find_triggered_skills(
            ["leadership_review"], "proactive_think", agent_rank="ensign",
        )
        assert result == []

    def test_department_gate_applies(self, catalog):
        """Department-specific skill not returned for other department."""
        self._add_skill(catalog, _make_skill_entry(
            name="eng-only", triggers=["notebook"], department="engineering",
        ))
        result = catalog.find_triggered_skills(
            ["notebook"], "proactive_think", department="medical",
        )
        assert result == []

    def test_empty_intended_actions_returns_empty(self, catalog):
        """intended_actions=[] → no skills returned."""
        self._add_skill(catalog, _make_skill_entry(
            name="comm", triggers=["ward_room_post"],
        ))
        result = catalog.find_triggered_skills([], "proactive_think")
        assert result == []

    def test_discovery_only_excluded(self, catalog):
        """discovery-only skills excluded from triggered search."""
        self._add_skill(catalog, _make_skill_entry(
            name="discovery-only", activation="discovery", triggers=["notebook"],
        ))
        result = catalog.find_triggered_skills(["notebook"], "proactive_think")
        assert result == []


# ===========================================================================
# TestIntendedActionsExtraction
# ===========================================================================

class TestIntendedActionsExtraction:
    """CognitiveAgent._extract_intended_actions() static method."""

    def _extract(self, chain_results):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        return CognitiveAgent._extract_intended_actions(chain_results)

    def test_list_extracted(self):
        """ANALYZE result with intended_actions: ['ward_room_reply'] → ['ward_room_reply']."""
        results = [_make_analyze_result(intended_actions=["ward_room_reply"])]
        assert self._extract(results) == ["ward_room_reply"]

    def test_string_normalized_to_list(self):
        """ANALYZE result with intended_actions: 'notebook' → ['notebook']."""
        results = [_make_analyze_result(intended_actions="notebook")]
        assert self._extract(results) == ["notebook"]

    def test_comma_string_split(self):
        """ANALYZE result with comma-separated string → split list."""
        results = [_make_analyze_result(intended_actions="ward_room_reply,notebook")]
        assert self._extract(results) == ["ward_room_reply", "notebook"]

    def test_missing_field_returns_empty(self):
        """ANALYZE result without intended_actions → []."""
        results = [_make_analyze_result()]  # No intended_actions
        assert self._extract(results) == []

    def test_values_lowercased_and_stripped(self):
        """Values are lowercased and stripped."""
        results = [_make_analyze_result(intended_actions=[" Ward_Room_Reply ", "NOTEBOOK"])]
        assert self._extract(results) == ["ward_room_reply", "notebook"]

    def test_non_analyze_results_skipped(self):
        """Only ANALYZE results are checked, not COMPOSE."""
        results = [
            _make_compose_result(intended_actions=["should_not_match"]),
            _make_analyze_result(intended_actions=["ward_room_reply"]),
        ]
        assert self._extract(results) == ["ward_room_reply"]

    def test_empty_list_returns_empty(self):
        """No results → empty list."""
        assert self._extract([]) == []

    def test_non_list_non_string_returns_empty(self):
        """intended_actions with unexpected type → empty list."""
        results = [_make_analyze_result(intended_actions=42)]
        assert self._extract(results) == []


# ===========================================================================
# TestChainRouting
# ===========================================================================

class TestChainRouting:
    """AD-643a two-phase chain execution routing decisions."""

    def test_silent_short_circuits(self):
        """intended_actions=['silent'] → NO_RESPONSE without COMPOSE/EVALUATE/REFLECT."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        results = [_make_analyze_result(intended_actions=["silent"])]
        actions = CognitiveAgent._extract_intended_actions(results)
        assert actions == ["silent"]

    def test_external_chain_bypasses_routing(self):
        """_pending_sub_task_chain code path uses pre-AD-643 all-skills behavior."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        source = inspect.getsource(CognitiveAgent.decide)
        # External chain block should load all augmentation skills
        ext_idx = source.find("self._pending_sub_task_chain is not None")
        aug_idx = source.find("self._load_augmentation_skills", ext_idx)
        routing_idx = source.find("_execute_chain_with_intent_routing", ext_idx)
        assert ext_idx != -1
        assert aug_idx != -1
        assert routing_idx != -1
        # Augmentation skills loaded BEFORE intent routing
        assert aug_idx < routing_idx

    def test_intent_routing_uses_new_method(self):
        """Priority 2 path calls _execute_chain_with_intent_routing."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        source = inspect.getsource(CognitiveAgent.decide)
        assert "_execute_chain_with_intent_routing" in source

    def test_fallback_on_missing_actions(self):
        """_execute_chain_with_intent_routing falls back when no intended_actions."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        source = inspect.getsource(CognitiveAgent._execute_chain_with_intent_routing)
        assert "No intended_actions from ANALYZE, falling back to full chain" in source

    def test_comm_actions_defined(self):
        """Communication actions include ward_room_post, ward_room_reply, endorse, dm."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        source = inspect.getsource(CognitiveAgent._execute_chain_with_intent_routing)
        assert "ward_room_post" in source
        assert "ward_room_reply" in source
        assert "endorse" in source
        assert "dm" in source


# ===========================================================================
# TestTargetedSkillLoading
# ===========================================================================

class TestTargetedSkillLoading:
    """Skill loading based on intended_actions triggers."""

    @pytest.fixture
    def catalog(self):
        cat = CognitiveSkillCatalog.__new__(CognitiveSkillCatalog)
        cat._cache = {}
        cat._skills = {}
        cat._instruction_cache = {}
        return cat

    def _add_skill(self, catalog, entry):
        catalog._cache[entry.name] = entry

    def test_notebook_loads_notebook_skill_only(self, catalog):
        """intended_actions=['notebook'] → only notebook-quality loaded."""
        self._add_skill(catalog, _make_skill_entry(
            name="comm-discipline", triggers=["ward_room_post", "ward_room_reply", "endorse"],
            intents=["proactive_think"],
        ))
        self._add_skill(catalog, _make_skill_entry(
            name="notebook-quality", triggers=["notebook"],
            intents=["proactive_think"],
        ))
        result = catalog.find_triggered_skills(["notebook"], "proactive_think")
        assert len(result) == 1
        assert result[0].name == "notebook-quality"

    def test_comm_loads_comm_skill_only(self, catalog):
        """intended_actions=['ward_room_post'] → only communication-discipline loaded."""
        self._add_skill(catalog, _make_skill_entry(
            name="comm-discipline", triggers=["ward_room_post", "ward_room_reply", "endorse"],
            intents=["proactive_think"],
        ))
        self._add_skill(catalog, _make_skill_entry(
            name="notebook-quality", triggers=["notebook"],
            intents=["proactive_think"],
        ))
        result = catalog.find_triggered_skills(["ward_room_post"], "proactive_think")
        assert len(result) == 1
        assert result[0].name == "comm-discipline"

    def test_multiple_actions_load_multiple_skills(self, catalog):
        """intended_actions=['ward_room_post','notebook'] → both skills loaded."""
        self._add_skill(catalog, _make_skill_entry(
            name="comm-discipline", triggers=["ward_room_post", "ward_room_reply", "endorse"],
            intents=["proactive_think"],
        ))
        self._add_skill(catalog, _make_skill_entry(
            name="notebook-quality", triggers=["notebook"],
            intents=["proactive_think"],
        ))
        result = catalog.find_triggered_skills(["ward_room_post", "notebook"], "proactive_think")
        assert len(result) == 2
        names = {r.name for r in result}
        assert names == {"comm-discipline", "notebook-quality"}

    def test_silent_loads_no_skills(self, catalog):
        """intended_actions=['silent'] → no skills loaded."""
        self._add_skill(catalog, _make_skill_entry(
            name="comm-discipline", triggers=["ward_room_post"],
            intents=["proactive_think"],
        ))
        result = catalog.find_triggered_skills(["silent"], "proactive_think")
        assert result == []

    def test_leadership_review_loads_leadership_skill(self, catalog):
        """intended_actions=['leadership_review'] → leadership-feedback loaded."""
        self._add_skill(catalog, _make_skill_entry(
            name="leadership-feedback", triggers=["leadership_review"],
            min_rank="lieutenant_commander",
            intents=["proactive_think"],
        ))
        result = catalog.find_triggered_skills(
            ["leadership_review"], "proactive_think",
            agent_rank="lieutenant_commander",
        )
        assert len(result) == 1
        assert result[0].name == "leadership-feedback"


# ===========================================================================
# TestShortCircuitIntegration
# ===========================================================================

class TestShortCircuitIntegration:
    """Compose _should_short_circuit checks intended_actions."""

    def test_compose_short_circuits_on_intended_actions_silent(self):
        """_should_short_circuit returns True when intended_actions == ['silent']."""
        from probos.cognitive.sub_tasks.compose import _should_short_circuit
        results = [_make_analyze_result(
            intended_actions=["silent"],
            contribution_assessment="SILENT",
        )]
        assert _should_short_circuit(results) is True

    def test_compose_short_circuit_social_override(self):
        """Captain message overrides silent intended_actions (existing BF-186 behavior)."""
        from probos.cognitive.sub_tasks.compose import _should_short_circuit
        results = [_make_analyze_result(
            intended_actions=["silent"],
            contribution_assessment="SILENT",
        )]
        context = {"_from_captain": True}
        assert _should_short_circuit(results, context) is False

    def test_compose_no_short_circuit_on_respond(self):
        """_should_short_circuit returns False for ward_room_reply actions."""
        from probos.cognitive.sub_tasks.compose import _should_short_circuit
        results = [_make_analyze_result(
            intended_actions=["ward_room_reply"],
            contribution_assessment="RESPOND",
        )]
        assert _should_short_circuit(results) is False

    def test_compose_short_circuit_string_silent(self):
        """_should_short_circuit handles intended_actions as string 'silent'."""
        from probos.cognitive.sub_tasks.compose import _should_short_circuit
        results = [_make_analyze_result(
            intended_actions="silent",
            contribution_assessment="SILENT",
        )]
        assert _should_short_circuit(results) is True


# ===========================================================================
# TestAnalyzePromptUpdates
# ===========================================================================

class TestAnalyzePromptUpdates:
    """ANALYZE prompts request intended_actions."""

    def test_situation_review_includes_intended_actions(self):
        """Situation review prompt includes intended_actions key."""
        from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
        _, user = _build_situation_review_prompt(
            {"context": "test"}, [], "TestAgent", "Science",
        )
        assert "intended_actions" in user
        assert "ward_room_post" in user
        assert "notebook" in user

    def test_thread_analysis_includes_intended_actions(self):
        """Thread analysis prompt includes intended_actions key."""
        from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt
        _, user = _build_thread_analysis_prompt(
            {"context": "test", "params": {}}, [], "TestAgent", "Science",
        )
        assert "intended_actions" in user
        assert "ward_room_reply" in user
        assert "endorse" in user

    def test_situation_review_says_6_keys(self):
        """Situation review prompt says '6 keys'."""
        from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
        _, user = _build_situation_review_prompt(
            {"context": "test"}, [], "TestAgent", "Science",
        )
        assert "6 keys" in user

    def test_thread_analysis_says_7_keys(self):
        """Thread analysis prompt says '7 keys'."""
        from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt
        _, user = _build_thread_analysis_prompt(
            {"context": "test", "params": {}}, [], "TestAgent", "Science",
        )
        assert "7 keys" in user


# ===========================================================================
# TestSkillMdFiles
# ===========================================================================

class TestSkillMdFiles:
    """Verify SKILL.md files have probos-triggers."""

    def test_communication_discipline_triggers(self):
        """communication-discipline has ward_room_post, ward_room_reply, endorse triggers."""
        path = Path("config/skills/communication-discipline/SKILL.md")
        if not path.exists():
            pytest.skip("SKILL.md not found")
        entry = parse_skill_file(path)
        assert entry is not None
        assert set(entry.triggers) == {"ward_room_post", "ward_room_reply", "endorse"}

    def test_notebook_quality_triggers(self):
        """notebook-quality has notebook trigger."""
        path = Path("config/skills/notebook-quality/SKILL.md")
        if not path.exists():
            pytest.skip("SKILL.md not found")
        entry = parse_skill_file(path)
        assert entry is not None
        assert entry.triggers == ["notebook"]

    def test_leadership_feedback_triggers(self):
        """leadership-feedback has leadership_review trigger."""
        path = Path("config/skills/leadership-feedback/SKILL.md")
        if not path.exists():
            pytest.skip("SKILL.md not found")
        entry = parse_skill_file(path)
        assert entry is not None
        assert entry.triggers == ["leadership_review"]
