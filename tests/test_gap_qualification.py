"""AD-539: Gap qualification tests."""
import pytest

from unittest.mock import AsyncMock, MagicMock

from probos.cognitive.gap_predictor import (
    GapReport,
    trigger_qualification_if_needed,
    check_gap_closure,
    map_gap_to_skill,
)


def _make_gap(**overrides) -> GapReport:
    defaults = dict(
        id="gap:test:1",
        agent_id="agent1",
        agent_type="TestAgent",
        gap_type="knowledge",
        description="Test gap",
        affected_intent_types=["read_file"],
        failure_rate=0.5,
        episode_count=10,
        mapped_skill_id="duty_execution",
        current_proficiency=1,
        target_proficiency=3,
    )
    defaults.update(overrides)
    return GapReport(**defaults)


@pytest.mark.asyncio
async def test_trigger_qualification_for_knowledge_gap():
    """Knowledge gap below target proficiency triggers qualification."""
    gap = _make_gap()
    skill_service = AsyncMock()
    skill_service.get_qualification_record = AsyncMock(return_value=None)
    skill_service.start_qualification = AsyncMock()

    result = await trigger_qualification_if_needed(gap, skill_service)
    assert result.qualification_path_id == "gap_qualification:duty_execution"
    skill_service.start_qualification.assert_called_once()


@pytest.mark.asyncio
async def test_skip_qualification_for_capability_gap():
    """Capability gap does not trigger qualification."""
    gap = _make_gap(gap_type="capability")
    skill_service = AsyncMock()
    result = await trigger_qualification_if_needed(gap, skill_service)
    assert result.qualification_path_id == ""


@pytest.mark.asyncio
async def test_skip_qualification_for_data_gap():
    """Data gap does not trigger qualification."""
    gap = _make_gap(gap_type="data")
    skill_service = AsyncMock()
    result = await trigger_qualification_if_needed(gap, skill_service)
    assert result.qualification_path_id == ""


@pytest.mark.asyncio
async def test_skip_qualification_if_proficient():
    """Gap at target proficiency skips qualification."""
    gap = _make_gap(current_proficiency=3, target_proficiency=3)
    skill_service = AsyncMock()
    result = await trigger_qualification_if_needed(gap, skill_service)
    assert result.qualification_path_id == ""


@pytest.mark.asyncio
async def test_skip_if_qualification_exists():
    """Existing qualification record links without creating duplicate."""
    gap = _make_gap()
    skill_service = AsyncMock()
    skill_service.get_qualification_record = AsyncMock(return_value={"status": "in_progress"})
    skill_service.start_qualification = AsyncMock()

    result = await trigger_qualification_if_needed(gap, skill_service)
    assert result.qualification_path_id == "gap_qualification:duty_execution"
    skill_service.start_qualification.assert_not_called()


@pytest.mark.asyncio
async def test_gap_closure_proficiency_reached():
    """Proficiency at target with no procedure evidence → gap resolved."""
    gap = _make_gap(
        evidence_sources=["episode:low_confidence"],
        mapped_skill_id="code_review",
    )
    skill_service = AsyncMock()
    profile = MagicMock()
    profile.pccs = []
    profile.role_skills = []

    class FakeSkillRecord:
        skill_id = "code_review"
        proficiency = 3

    profile.acquired_skills = [FakeSkillRecord()]
    skill_service.get_profile = AsyncMock(return_value=profile)

    result = await check_gap_closure(gap, skill_service, None)
    assert result is True
    assert gap.resolved is True


@pytest.mark.asyncio
async def test_gap_closure_partial():
    """One signal positive but not the other → gap still open."""
    gap = _make_gap(
        evidence_sources=["procedure_health:FIX:high_fallback_rate:p1"],
        mapped_skill_id="code_review",
    )
    # Skill signal: proficiency NOT reached
    skill_service = AsyncMock()
    profile = MagicMock()
    profile.pccs = []
    profile.role_skills = []
    profile.acquired_skills = []
    skill_service.get_profile = AsyncMock(return_value=profile)

    # Procedure signal: effective_rate improved
    procedure_store = AsyncMock()
    procedure_store.get_quality_metrics = AsyncMock(return_value={"effective_rate": 0.9})

    result = await check_gap_closure(gap, skill_service, procedure_store)
    assert result is False
    assert gap.resolved is False


@pytest.mark.asyncio
async def test_gap_closure_effective_rate_improved():
    """Procedure effective rate improved + no skill mapping → gap resolved."""
    gap = _make_gap(
        evidence_sources=["procedure_health:FIX:low_completion:p1"],
        mapped_skill_id="",  # no skill mapping
    )
    procedure_store = AsyncMock()
    procedure_store.get_quality_metrics = AsyncMock(return_value={"effective_rate": 0.85})

    result = await check_gap_closure(gap, None, procedure_store)
    assert result is True
    assert gap.resolved is True
