"""AD-596c: Skill-Registry Bridge tests.

Tests for SkillBridge (T2↔T3 coordinator), proficiency gating,
exercise recording, gap resolution, and serialization fixes.
"""

from __future__ import annotations

import asyncio
from dataclasses import field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.skill_bridge import SkillBridge
from probos.cognitive.skill_catalog import CognitiveSkillEntry
from probos.cognitive.procedures import Procedure, ProcedureStep


# ── Helpers ──────────────────────────────────────────────────────────


def make_entry(
    name: str = "test_skill",
    skill_id: str = "",
    min_proficiency: int = 1,
    intents: list[str] | None = None,
) -> CognitiveSkillEntry:
    return CognitiveSkillEntry(
        name=name,
        description=f"Test {name}",
        skill_dir=Path("."),
        skill_id=skill_id,
        min_proficiency=min_proficiency,
        intents=intents or [],
    )


def make_bridge(
    entries: list[CognitiveSkillEntry] | None = None,
    registered_ids: list[str] | None = None,
) -> SkillBridge:
    catalog = MagicMock()
    catalog.list_entries.return_value = entries or []
    catalog.find_by_intent = MagicMock(
        side_effect=lambda i: [e for e in (entries or []) if i in e.intents]
    )
    catalog.get_instructions = MagicMock(return_value="do the thing")

    registry = MagicMock()
    skills = []
    for sid in (registered_ids or []):
        s = MagicMock()
        s.skill_id = sid
        skills.append(s)
    registry.list_skills.return_value = skills

    service = AsyncMock()
    return SkillBridge(catalog=catalog, skill_registry=registry, skill_service=service)


def make_profile(skill_records: list[tuple[str, int]] | None = None):
    """Create a mock SkillProfile with given (skill_id, proficiency) pairs."""
    profile = MagicMock()
    records = []
    for sid, prof in (skill_records or []):
        r = MagicMock()
        r.skill_id = sid
        r.proficiency = prof
        records.append(r)
    profile.all_skills = records
    return profile


# ── validate_and_sync() ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_and_sync_all_matched():
    """All entries have skill_ids that exist in registry."""
    entries = [
        make_entry("a", skill_id="skill_a"),
        make_entry("b", skill_id="skill_b"),
    ]
    bridge = make_bridge(entries, registered_ids=["skill_a", "skill_b"])
    result = await bridge.validate_and_sync()
    assert result["matched"] == 2
    assert result["unmatched"] == 0
    assert result["no_skill_id"] == 0


@pytest.mark.asyncio
async def test_validate_and_sync_some_unmatched():
    """Entry has skill_id not found in registry."""
    entries = [
        make_entry("a", skill_id="skill_a"),
        make_entry("b", skill_id="skill_missing"),
    ]
    bridge = make_bridge(entries, registered_ids=["skill_a"])
    result = await bridge.validate_and_sync()
    assert result["matched"] == 1
    assert result["unmatched"] == 1
    assert result["unmatched_names"] == ["b"]


@pytest.mark.asyncio
async def test_validate_and_sync_no_skill_id():
    """Entries without skill_id are counted as no_skill_id."""
    entries = [
        make_entry("a"),
        make_entry("b"),
    ]
    bridge = make_bridge(entries)
    result = await bridge.validate_and_sync()
    assert result["no_skill_id"] == 2
    assert result["matched"] == 0
    assert result["unmatched"] == 0


@pytest.mark.asyncio
async def test_validate_and_sync_empty_catalog():
    """Empty catalog returns all zeros."""
    bridge = make_bridge()
    result = await bridge.validate_and_sync()
    assert result["matched"] == 0
    assert result["unmatched"] == 0
    assert result["no_skill_id"] == 0


@pytest.mark.asyncio
async def test_validate_and_sync_mixed():
    """Mixed scenario: some matched, some unmatched, some ungoverned."""
    entries = [
        make_entry("matched", skill_id="skill_a"),
        make_entry("unmatched", skill_id="skill_missing"),
        make_entry("ungoverned"),
    ]
    bridge = make_bridge(entries, registered_ids=["skill_a"])
    result = await bridge.validate_and_sync()
    assert result["matched"] == 1
    assert result["unmatched"] == 1
    assert result["no_skill_id"] == 1


# ── check_proficiency_gate() ────────────────────────────────────────


def test_proficiency_gate_no_skill_id():
    """Ungoverned skill (no skill_id) always passes."""
    bridge = make_bridge()
    entry = make_entry(skill_id="")
    assert bridge.check_proficiency_gate("agent_1", entry, None) is True


def test_proficiency_gate_min_proficiency_one():
    """Default threshold (min_proficiency=1) always passes."""
    bridge = make_bridge()
    entry = make_entry(skill_id="some_skill", min_proficiency=1)
    assert bridge.check_proficiency_gate("agent_1", entry, None) is True


def test_proficiency_gate_agent_meets():
    """Agent meets proficiency requirement."""
    bridge = make_bridge()
    entry = make_entry(skill_id="skill_a", min_proficiency=3)
    profile = make_profile([("skill_a", 4)])
    assert bridge.check_proficiency_gate("agent_1", entry, profile) is True


def test_proficiency_gate_agent_below():
    """Agent below proficiency requirement."""
    bridge = make_bridge()
    entry = make_entry(skill_id="skill_a", min_proficiency=3)
    profile = make_profile([("skill_a", 2)])
    assert bridge.check_proficiency_gate("agent_1", entry, profile) is False


def test_proficiency_gate_no_profile():
    """No profile → fail closed."""
    bridge = make_bridge()
    entry = make_entry(skill_id="skill_a", min_proficiency=3)
    assert bridge.check_proficiency_gate("agent_1", entry, None) is False


def test_proficiency_gate_skill_not_in_profile():
    """Agent has profile but not the required skill."""
    bridge = make_bridge()
    entry = make_entry(skill_id="skill_a", min_proficiency=3)
    profile = make_profile([("other_skill", 5)])
    assert bridge.check_proficiency_gate("agent_1", entry, profile) is False


def test_proficiency_gate_exact_threshold():
    """Proficiency exactly at threshold → passes."""
    bridge = make_bridge()
    entry = make_entry(skill_id="skill_a", min_proficiency=3)
    profile = make_profile([("skill_a", 3)])
    assert bridge.check_proficiency_gate("agent_1", entry, profile) is True


# ── record_skill_exercise() ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_exercise_no_skill_id():
    """No skill_id → no-op (service not called)."""
    bridge = make_bridge()
    entry = make_entry(skill_id="")
    await bridge.record_skill_exercise("agent_1", entry)
    bridge._service.record_exercise.assert_not_called()


@pytest.mark.asyncio
async def test_record_exercise_happy_path():
    """record_exercise returns a record → done."""
    bridge = make_bridge()
    bridge._service.record_exercise.return_value = MagicMock()
    entry = make_entry(skill_id="skill_a")
    await bridge.record_skill_exercise("agent_1", entry)
    bridge._service.record_exercise.assert_called_once_with("agent_1", "skill_a")


@pytest.mark.asyncio
async def test_record_exercise_auto_acquire():
    """record_exercise returns None → auto-acquire at FOLLOW → record again."""
    bridge = make_bridge()
    bridge._service.record_exercise.side_effect = [None, MagicMock()]
    entry = make_entry(skill_id="skill_a")
    await bridge.record_skill_exercise("agent_1", entry)
    bridge._service.acquire_skill.assert_called_once()
    assert bridge._service.record_exercise.call_count == 2


@pytest.mark.asyncio
async def test_record_exercise_error_degrades():
    """Error in service → log-and-degrade, no exception raised."""
    bridge = make_bridge()
    bridge._service.record_exercise.side_effect = RuntimeError("db fail")
    entry = make_entry(skill_id="skill_a")
    # Must not raise
    await bridge.record_skill_exercise("agent_1", entry)


# ── resolve_skill_for_gap() ─────────────────────────────────────────


def test_resolve_gap_catalog_match_with_skill_id():
    """Catalog match with skill_id → returns that skill_id."""
    entries = [make_entry("a", skill_id="skill_a", intents=["analyze"])]
    bridge = make_bridge(entries, registered_ids=["other"])
    result = bridge.resolve_skill_for_gap(["analyze"])
    assert result == "skill_a"


def test_resolve_gap_catalog_match_no_skill_id():
    """Catalog match without skill_id → falls through to registry."""
    entries = [make_entry("a", skill_id="", intents=["analyze"])]
    bridge = make_bridge(entries, registered_ids=["analyze"])
    result = bridge.resolve_skill_for_gap(["analyze"])
    assert result == "analyze"


def test_resolve_gap_registry_match():
    """No catalog match → registry exact match."""
    bridge = make_bridge(entries=[], registered_ids=["monitor"])
    result = bridge.resolve_skill_for_gap(["monitor"])
    assert result == "monitor"


def test_resolve_gap_no_match():
    """No matches → duty_execution fallback."""
    bridge = make_bridge(entries=[], registered_ids=[])
    result = bridge.resolve_skill_for_gap(["unknown_intent"])
    assert result == "duty_execution"


# ── Serialization tests ─────────────────────────────────────────────


def test_procedure_step_to_dict_includes_required_tools():
    """ProcedureStep.to_dict() includes required_tools field."""
    step = ProcedureStep(
        step_number=1,
        action="do thing",
        required_tools=["tool_a", "tool_b"],
    )
    d = step.to_dict()
    assert "required_tools" in d
    assert d["required_tools"] == ["tool_a", "tool_b"]


def test_procedure_to_dict_includes_source_skill_id():
    """Procedure.to_dict() includes source_skill_id field."""
    proc = Procedure(name="test", source_skill_id="cognitive_analysis")
    d = proc.to_dict()
    assert "source_skill_id" in d
    assert d["source_skill_id"] == "cognitive_analysis"


def test_procedure_from_dict_round_trip_source_skill_id():
    """Procedure.from_dict() preserves source_skill_id in round-trip."""
    proc = Procedure(
        name="test",
        description="a test procedure",
        source_skill_id="my_skill",
        steps=[ProcedureStep(step_number=1, action="step1")],
        intent_types=["analyze"],
    )
    d = proc.to_dict()
    restored = Procedure.from_dict(d)
    assert restored.source_skill_id == "my_skill"
    assert restored.name == "test"
    assert len(restored.steps) == 1


def test_procedure_from_dict_default_source_skill_id():
    """Procedure.from_dict() defaults source_skill_id to empty string."""
    d = {"name": "old_proc", "steps": []}
    restored = Procedure.from_dict(d)
    assert restored.source_skill_id == ""
