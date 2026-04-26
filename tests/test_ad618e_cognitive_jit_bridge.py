"""AD-618e: Cognitive JIT Bridge tests.

Tests BillJITBridge — mapping resolution, event handling (happy path + edge
cases), custom mappings, and stats.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

from probos.skill_framework import ProficiencyLevel
from probos.sop.jit_bridge import (
    BillJITBridge,
    StepSkillMapping,
    DEFAULT_STEP_SKILL_MAPPINGS,
)


# ---------------------------------------------------------------------------
# Stubs / fixtures
# ---------------------------------------------------------------------------

@dataclass
class FakeCognitiveSkillEntry:
    """Minimal stub matching CognitiveSkillEntry shape."""
    name: str = "test_skill"
    skill_id: str = "duty_execution"
    description: str = "Test skill"
    skill_dir: str = ""
    department: str = ""
    min_proficiency: ProficiencyLevel = ProficiencyLevel.FOLLOW
    intents: list[str] = field(default_factory=list)
    activation: str = "manual"
    triggers: list[str] = field(default_factory=list)


def _make_bridge(
    *,
    catalog_entries: list | None = None,
    record_exercise_return=None,
    mappings: list[StepSkillMapping] | None = None,
) -> tuple[BillJITBridge, AsyncMock, MagicMock, AsyncMock]:
    """Build a BillJITBridge with mock dependencies.

    Returns (bridge, skill_bridge_mock, catalog_mock, skill_service_mock).
    """
    skill_bridge = AsyncMock()
    skill_bridge.record_skill_exercise = AsyncMock()

    catalog = MagicMock()
    catalog.list_entries = MagicMock(return_value=catalog_entries or [])

    skill_service = AsyncMock()
    skill_service.record_exercise = AsyncMock(return_value=record_exercise_return)
    skill_service.acquire_skill = AsyncMock()

    bridge = BillJITBridge(
        skill_bridge=skill_bridge,
        catalog=catalog,
        skill_service=skill_service,
        mappings=mappings,
    )
    return bridge, skill_bridge, catalog, skill_service


def _envelope(
    bill_id: str = "gq",
    step_id: str = "s1",
    action: str = "cognitive_skill",
    agent_id: str = "agent_1",
    **extra,
) -> dict:
    """Build a full BILL_STEP_COMPLETED event envelope."""
    data = {"bill_id": bill_id, "step_id": step_id, "action": action, "agent_id": agent_id}
    data.update(extra)
    return {
        "type": "bill_step_completed",
        "data": data,
        "timestamp": 1234567890.0,
    }


# ===========================================================================
# Mapping resolution (6 tests)
# ===========================================================================

class TestMappingResolution:
    """Tests for BillJITBridge.resolve_mapping()."""

    def test_resolve_exact_match(self):
        exact = StepSkillMapping(skill_id="special", bill_id="gq", step_id="s1")
        bridge, *_ = _make_bridge(mappings=[
            StepSkillMapping(skill_id="general", action="cognitive_skill"),
            exact,
        ])
        result = bridge.resolve_mapping("gq", "s1", "cognitive_skill")
        assert result is exact

    def test_resolve_bill_scoped_action(self):
        scoped = StepSkillMapping(skill_id="scoped", bill_id="gq", action="tool")
        bridge, *_ = _make_bridge(mappings=[
            StepSkillMapping(skill_id="global", action="tool"),
            scoped,
        ])
        result = bridge.resolve_mapping("gq", "any_step", "tool")
        assert result is scoped

    def test_resolve_global_action(self):
        global_m = StepSkillMapping(skill_id="duty_execution", action="cognitive_skill")
        bridge, *_ = _make_bridge(mappings=[global_m])
        result = bridge.resolve_mapping("any_bill", "any_step", "cognitive_skill")
        assert result is global_m

    def test_resolve_priority_exact_over_action(self):
        exact = StepSkillMapping(skill_id="exact", bill_id="gq", step_id="s1")
        scoped = StepSkillMapping(skill_id="scoped", bill_id="gq", action="cognitive_skill")
        global_m = StepSkillMapping(skill_id="global", action="cognitive_skill")
        bridge, *_ = _make_bridge(mappings=[global_m, scoped, exact])
        result = bridge.resolve_mapping("gq", "s1", "cognitive_skill")
        assert result is exact

    def test_resolve_no_match(self):
        bridge, *_ = _make_bridge(mappings=[
            StepSkillMapping(skill_id="duty", action="cognitive_skill"),
        ])
        result = bridge.resolve_mapping("gq", "s1", "unknown_action")
        assert result is None

    def test_resolve_empty_mappings(self):
        # Construct directly with empty list to bypass the `or` default
        bridge = BillJITBridge(
            skill_bridge=AsyncMock(),
            catalog=MagicMock(list_entries=MagicMock(return_value=[])),
            skill_service=AsyncMock(),
        )
        bridge._mappings = []
        result = bridge.resolve_mapping("gq", "s1", "cognitive_skill")
        assert result is None


# ===========================================================================
# Event handling — happy path (5 tests)
# ===========================================================================

class TestEventHandlingHappyPath:
    """Tests for on_step_completed happy paths."""

    @pytest.mark.asyncio
    async def test_on_step_completed_exercises_skill_via_catalog(self):
        entry = FakeCognitiveSkillEntry(skill_id="duty_execution")
        bridge, skill_bridge, _, _ = _make_bridge(catalog_entries=[entry])
        await bridge.on_step_completed(_envelope(action="cognitive_skill"))
        skill_bridge.record_skill_exercise.assert_awaited_once_with("agent_1", entry)

    @pytest.mark.asyncio
    async def test_on_step_completed_exercises_skill_direct(self):
        # No catalog entry → direct path via skill_service
        bridge, skill_bridge, _, skill_service = _make_bridge(
            catalog_entries=[],
            record_exercise_return=MagicMock(),  # agent has skill
        )
        await bridge.on_step_completed(_envelope(action="cognitive_skill"))
        skill_bridge.record_skill_exercise.assert_not_awaited()
        skill_service.record_exercise.assert_awaited_once_with("agent_1", "duty_execution")

    @pytest.mark.asyncio
    async def test_on_step_completed_auto_acquires(self):
        # No catalog entry + record_exercise returns None → auto-acquire
        bridge, _, _, skill_service = _make_bridge(
            catalog_entries=[],
            record_exercise_return=None,
        )
        await bridge.on_step_completed(_envelope(action="cognitive_skill"))
        skill_service.acquire_skill.assert_awaited_once_with(
            "agent_1",
            "duty_execution",
            source="bill_step_completion",
            proficiency=ProficiencyLevel.FOLLOW,
        )
        # record_exercise called twice: once to check, once after acquire
        assert skill_service.record_exercise.await_count == 2

    @pytest.mark.asyncio
    async def test_on_step_completed_increments_count(self):
        entry = FakeCognitiveSkillEntry(skill_id="duty_execution")
        bridge, *_ = _make_bridge(catalog_entries=[entry])
        assert bridge.exercise_count == 0
        await bridge.on_step_completed(_envelope())
        assert bridge.exercise_count == 1
        await bridge.on_step_completed(_envelope())
        assert bridge.exercise_count == 2

    @pytest.mark.asyncio
    async def test_on_step_completed_with_default_mappings(self):
        entry = FakeCognitiveSkillEntry(skill_id="duty_execution")
        bridge = BillJITBridge(
            skill_bridge=AsyncMock(),
            catalog=MagicMock(list_entries=MagicMock(return_value=[entry])),
            skill_service=AsyncMock(),
        )
        await bridge.on_step_completed(_envelope(action="cognitive_skill"))
        assert bridge.exercise_count == 1


# ===========================================================================
# Event handling — edge cases (7 tests)
# ===========================================================================

class TestEventHandlingEdgeCases:
    """Tests for on_step_completed edge cases — log-and-degrade."""

    @pytest.mark.asyncio
    async def test_on_step_completed_no_agent_id(self):
        bridge, skill_bridge, _, _ = _make_bridge()
        await bridge.on_step_completed(_envelope(agent_id=""))
        skill_bridge.record_skill_exercise.assert_not_awaited()
        assert bridge.exercise_count == 0

    @pytest.mark.asyncio
    async def test_on_step_completed_no_mapping(self):
        bridge, skill_bridge, _, _ = _make_bridge(mappings=[
            StepSkillMapping(skill_id="x", action="something_else"),
        ])
        await bridge.on_step_completed(_envelope(action="cognitive_skill"))
        skill_bridge.record_skill_exercise.assert_not_awaited()
        assert bridge.exercise_count == 0

    @pytest.mark.asyncio
    async def test_on_step_completed_bridge_call_raises_degrades(self):
        entry = FakeCognitiveSkillEntry(skill_id="duty_execution")
        bridge, skill_bridge, _, _ = _make_bridge(catalog_entries=[entry])
        skill_bridge.record_skill_exercise.side_effect = RuntimeError("boom")
        # Must not raise
        await bridge.on_step_completed(_envelope(action="cognitive_skill"))
        # exercise_count NOT incremented because exception happened before increment
        assert bridge.exercise_count == 0

    @pytest.mark.asyncio
    async def test_on_step_completed_service_error_degrades(self):
        bridge, _, _, skill_service = _make_bridge(
            catalog_entries=[],
            record_exercise_return=None,
        )
        skill_service.acquire_skill.side_effect = RuntimeError("db down")
        # Must not raise — _record_direct_exercise catches Exception
        await bridge.on_step_completed(_envelope(action="cognitive_skill"))
        # exercise_count IS incremented because _record_direct_exercise catches
        # its own errors internally, and on_step_completed increments after the call
        assert bridge.exercise_count == 1

    @pytest.mark.asyncio
    async def test_on_step_completed_empty_event_data(self):
        bridge, *_ = _make_bridge()
        # Empty dict — no agent_id, should skip gracefully
        await bridge.on_step_completed({})
        assert bridge.exercise_count == 0
        # With data key but empty
        await bridge.on_step_completed({"data": {}})
        assert bridge.exercise_count == 0

    @pytest.mark.asyncio
    async def test_record_direct_exercise_prerequisite_not_met(self):
        bridge, _, _, skill_service = _make_bridge(
            catalog_entries=[],
            record_exercise_return=None,
        )
        skill_service.acquire_skill.side_effect = ValueError("prerequisite not met")
        # Must not crash
        await bridge.on_step_completed(_envelope(action="cognitive_skill"))
        # exercise_count incremented because ValueError is caught inside _record_direct
        assert bridge.exercise_count == 1

    @pytest.mark.asyncio
    async def test_on_step_completed_unwraps_envelope(self):
        """Regression pin: bridge must unwrap event['data'], not use event directly."""
        entry = FakeCognitiveSkillEntry(skill_id="duty_execution")
        bridge, skill_bridge, _, _ = _make_bridge(catalog_entries=[entry])
        # Full envelope — the format runtime actually delivers
        envelope = {
            "type": "bill_step_completed",
            "data": {
                "bill_id": "general_quarters",
                "step_id": "set_condition",
                "action": "cognitive_skill",
                "agent_id": "agent_1",
            },
            "timestamp": 1234567890.0,
        }
        await bridge.on_step_completed(envelope)
        skill_bridge.record_skill_exercise.assert_awaited_once_with("agent_1", entry)
        assert bridge.exercise_count == 1


# ===========================================================================
# Custom mappings (2 tests)
# ===========================================================================

class TestCustomMappings:
    """Tests for runtime mapping management."""

    def test_add_mapping_runtime(self):
        bridge, *_ = _make_bridge()
        initial_count = len(bridge._mappings)
        custom = StepSkillMapping(skill_id="nav", action="navigation")
        bridge.add_mapping(custom)
        assert len(bridge._mappings) == initial_count + 1
        assert bridge._mappings[-1] is custom

    @pytest.mark.asyncio
    async def test_custom_mapping_overrides_default(self):
        entry = FakeCognitiveSkillEntry(skill_id="special_duty")
        bridge, skill_bridge, _, _ = _make_bridge(catalog_entries=[entry])
        # Add exact-match custom mapping that should override the default
        custom = StepSkillMapping(
            skill_id="special_duty",
            bill_id="gq",
            step_id="s1",
        )
        bridge.add_mapping(custom)
        await bridge.on_step_completed(_envelope(bill_id="gq", step_id="s1", action="cognitive_skill"))
        # Should have used the custom mapping's skill_id, not the default
        skill_bridge.record_skill_exercise.assert_awaited_once_with("agent_1", entry)


# ===========================================================================
# Stats (2 tests)
# ===========================================================================

class TestStats:
    """Tests for get_stats()."""

    def test_get_stats_initial(self):
        bridge, *_ = _make_bridge()
        stats = bridge.get_stats()
        assert stats["exercise_count"] == 0
        assert stats["mapping_count"] == len(DEFAULT_STEP_SKILL_MAPPINGS)
        assert stats["custom_mappings"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_after_exercises(self):
        entry = FakeCognitiveSkillEntry(skill_id="duty_execution")
        bridge, *_ = _make_bridge(catalog_entries=[entry])
        # Add a custom mapping with bill_id
        bridge.add_mapping(StepSkillMapping(skill_id="nav", bill_id="gq", action="tool"))
        await bridge.on_step_completed(_envelope())
        await bridge.on_step_completed(_envelope())
        stats = bridge.get_stats()
        assert stats["exercise_count"] == 2
        assert stats["mapping_count"] == len(DEFAULT_STEP_SKILL_MAPPINGS) + 1
        assert stats["custom_mappings"] == 1
