"""AD-539: Gap classification tests."""
import pytest

from probos.cognitive.gap_predictor import (
    GapReport,
    classify_gap,
    _intent_to_skill_id,
)


def test_classify_knowledge_gap():
    """Default classification is knowledge."""
    result = classify_gap("low_confidence", 0.5, 10)
    assert result == "knowledge"


def test_classify_capability_gap():
    """High failure + many episodes → capability."""
    result = classify_gap("failure_cluster", 0.85, 15)
    assert result == "capability"


def test_classify_data_gap():
    """Repeated fallback evidence → data."""
    result = classify_gap("repeated_fallback", 0.5, 5)
    assert result == "data"


def test_classify_boundary_failure_rate():
    """Exactly at 80% threshold is NOT capability (> needed, not >=)."""
    result = classify_gap("failure_cluster", 0.80, 15)
    assert result == "knowledge"


def test_classify_boundary_episode_count():
    """Exactly at 10 episodes with high failure: capability needs >80% AND >=10."""
    result = classify_gap("failure_cluster", 0.85, 10)
    assert result == "capability"

    # Below 10 episodes → knowledge even with high failure
    result = classify_gap("failure_cluster", 0.85, 9)
    assert result == "knowledge"


def test_gap_report_includes_classification():
    """GapReport.gap_type is populated correctly."""
    gap = GapReport(
        id="g1", agent_id="a1", agent_type="t",
        gap_type=classify_gap("low_confidence", 0.4, 20),
        description="test",
    )
    assert gap.gap_type == "knowledge"


def test_map_gap_to_skill_exact_match():
    """Intent matching skill_id directly returns that skill."""
    class FakeSkill:
        def __init__(self, sid):
            self.skill_id = sid

    skills = [FakeSkill("code_review"), FakeSkill("static_analysis")]
    result = _intent_to_skill_id(["static_analysis", "other"], skills)
    assert result == "static_analysis"


def test_map_gap_to_skill_fallback():
    """No match falls back to duty_execution."""
    result = _intent_to_skill_id(["some_unknown_intent"])
    assert result == "duty_execution"
