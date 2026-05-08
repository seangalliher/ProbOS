"""AD-507b + AD-509b/c/d: tests for curriculum progression + boot-camp extensions."""
from __future__ import annotations

import pytest

from probos.crew_development.boot_camp_extensions import (
    ASchoolCurriculum,
    CompletionCriteriaGate,
    CurriculumProgressionTracker,
    GraduatedStimuliMonitor,
)


# ---------------------------------------------------------------------------
# AD-507b
# ---------------------------------------------------------------------------


def test_progression_mark_and_query() -> None:
    t = CurriculumProgressionTracker()
    t.mark_completed("alpha", "identity_grounding")
    assert t.is_completed("alpha", "identity_grounding")
    assert not t.is_completed("alpha", "communication")
    assert t.completion_count("alpha") == 1


def test_progression_empty_inputs_ignored() -> None:
    t = CurriculumProgressionTracker()
    t.mark_completed("", "x")
    t.mark_completed("alpha", "")
    assert t.completion_count("alpha") == 0


def test_progression_completed_modules_sorted() -> None:
    t = CurriculumProgressionTracker()
    t.mark_completed("alpha", "communication")
    t.mark_completed("alpha", "ethics_boundaries")
    t.mark_completed("alpha", "identity_grounding")
    assert t.completed_modules("alpha") == ("communication", "ethics_boundaries", "identity_grounding")


def test_progression_reset() -> None:
    t = CurriculumProgressionTracker()
    t.mark_completed("alpha", "x")
    assert t.reset_agent("alpha") is True
    assert t.completion_count("alpha") == 0
    assert t.reset_agent("alpha") is False


# ---------------------------------------------------------------------------
# AD-509b
# ---------------------------------------------------------------------------


def test_aschool_returns_known_track() -> None:
    a = ASchoolCurriculum()
    assert "identity_grounding" in a.modules_for("medical")
    assert a.modules_for("nonexistent") == ()


def test_aschool_register_track() -> None:
    a = ASchoolCurriculum()
    a.register_track("test_dept", ("m1", "m2"))
    assert a.modules_for("test_dept") == ("m1", "m2")


def test_aschool_next_module_returns_first_incomplete() -> None:
    progression = CurriculumProgressionTracker()
    a = ASchoolCurriculum()
    progression.mark_completed("alpha", "identity_grounding")
    nxt = a.next_module_for("medical", progression, "alpha")
    assert nxt == "communication"


def test_aschool_next_module_none_when_all_complete() -> None:
    progression = CurriculumProgressionTracker()
    a = ASchoolCurriculum()
    a.register_track("dept", ("m1", "m2"))
    progression.mark_completed("alpha", "m1")
    progression.mark_completed("alpha", "m2")
    assert a.next_module_for("dept", progression, "alpha") is None


# ---------------------------------------------------------------------------
# AD-509c
# ---------------------------------------------------------------------------


def test_stimuli_minimal_during_orientation() -> None:
    m = GraduatedStimuliMonitor()
    rec = m.recommend(agent_id="a", boot_camp_phase="orientation", cognitive_load=0.2)
    assert rec.level == "minimal"


def test_stimuli_ship_wide_after_integration() -> None:
    m = GraduatedStimuliMonitor()
    rec = m.recommend(agent_id="a", boot_camp_phase="integration", cognitive_load=0.2)
    assert rec.level == "ship_wide"


def test_stimuli_high_load_clamps_to_minimal() -> None:
    m = GraduatedStimuliMonitor()
    rec = m.recommend(agent_id="a", boot_camp_phase="integration", cognitive_load=0.9)
    assert rec.level == "minimal"
    assert "high cognitive load" in rec.reason


def test_stimuli_unknown_phase_defaults_minimal() -> None:
    m = GraduatedStimuliMonitor()
    rec = m.recommend(agent_id="a", boot_camp_phase="weird")
    assert rec.level == "minimal"


# ---------------------------------------------------------------------------
# AD-509d
# ---------------------------------------------------------------------------


def test_gate_blocks_advance_when_module_missing() -> None:
    p = CurriculumProgressionTracker()
    g = CompletionCriteriaGate(progression=p)
    p.mark_completed("alpha", "identity_grounding")
    decision = g.evaluate(agent_id="alpha", current_phase="core_knowledge")
    assert decision.advance is False
    assert "communication" in decision.missing


def test_gate_allows_advance_when_complete() -> None:
    p = CurriculumProgressionTracker()
    for m in ("identity_grounding", "communication", "trust_basics"):
        p.mark_completed("alpha", m)
    g = CompletionCriteriaGate(progression=p)
    decision = g.evaluate(agent_id="alpha", current_phase="core_knowledge")
    assert decision.advance is True
    assert decision.missing == ()


def test_gate_unknown_phase_passes_through() -> None:
    g = CompletionCriteriaGate(progression=CurriculumProgressionTracker())
    decision = g.evaluate(agent_id="a", current_phase="unknown_phase")
    assert decision.advance is True


def test_gate_register_requirements() -> None:
    p = CurriculumProgressionTracker()
    g = CompletionCriteriaGate(progression=p)
    g.register_requirements("custom_phase", ("alpha_module",))
    decision = g.evaluate(agent_id="a", current_phase="custom_phase")
    assert decision.advance is False
    assert decision.missing == ("alpha_module",)
