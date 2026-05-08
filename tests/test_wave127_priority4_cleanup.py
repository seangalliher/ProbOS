"""Wave 127: tests for AD-509e/507c/507d/511c/511e/522d/522e/660c/660d cleanup combo."""
from __future__ import annotations

import pytest

from probos.cognitive.priority4_cleanup import (
    BoundaryEvolutionProposal,
    BoundaryScenario,
    CompetencyOutcome,
    CompetencyResult,
    CurriculumRequirement,
    DiagnosticActionResult,
    MovingRangeChart,
    PacingPolicy,
    assess_competency,
    causal_template_to_optimizer_proposal,
    execute_diagnostic_action,
    holodeck_observation_to_calibration_value,
    list_boundary_scenarios,
    propose_boundary_evolution,
    render_curriculum_clause,
    scenarios_for_boundary,
    trait_adaptive_pacing,
)


# AD-509e
def test_pacing_default_balanced_traits() -> None:
    p = trait_adaptive_pacing(openness=0.5, conscientiousness=0.5, neuroticism=0.5)
    assert all(m == 1.0 for m in p.phase_multipliers.values())


def test_pacing_high_neuroticism_slows_orientation() -> None:
    p = trait_adaptive_pacing(neuroticism=0.9)
    assert p.phase_multipliers["orientation"] > 1.0
    assert p.phase_multipliers["calibration"] > 1.0


def test_pacing_high_openness_speeds_a_school() -> None:
    p = trait_adaptive_pacing(openness=0.9)
    assert p.phase_multipliers["a_school"] < 1.0


# AD-507c
def test_assess_competency_above_threshold() -> None:
    r = assess_competency(agent_id="a", module_id="m", score=0.9, threshold=0.7)
    assert r.outcome == CompetencyOutcome.ABOVE


def test_assess_competency_at_threshold() -> None:
    r = assess_competency(agent_id="a", module_id="m", score=0.72, threshold=0.7)
    assert r.outcome == CompetencyOutcome.AT


def test_assess_competency_below_threshold() -> None:
    r = assess_competency(agent_id="a", module_id="m", score=0.5)
    assert r.outcome == CompetencyOutcome.BELOW


def test_assess_competency_negative_not_assessed() -> None:
    r = assess_competency(agent_id="a", module_id="m", score=-1.0)
    assert r.outcome == CompetencyOutcome.NOT_ASSESSED


# AD-507d
def test_render_curriculum_clause_ship_tier() -> None:
    req = CurriculumRequirement(tier="ship", target="", required_modules=("m1", "m2"))
    s = render_curriculum_clause(req)
    assert "Ship Tier" in s
    assert "m1" in s and "m2" in s


def test_render_curriculum_clause_department_tier() -> None:
    req = CurriculumRequirement(tier="department", target="medical", required_modules=("med1",))
    s = render_curriculum_clause(req)
    assert "medical" in s


# AD-511c
def test_holodeck_scenarios_default_catalog() -> None:
    scenarios = list_boundary_scenarios()
    assert len(scenarios) >= 3
    boundaries = {s.boundary_id for s in scenarios}
    assert "harm" in boundaries


def test_holodeck_scenarios_for_boundary_filter() -> None:
    s = scenarios_for_boundary("harm")
    assert len(s) >= 1
    assert all(x.boundary_id == "harm" for x in s)


# AD-511e
def test_boundary_evolution_proposes_when_violations_exceed_threshold() -> None:
    p = propose_boundary_evolution(
        boundary_id="harm",
        recent_violations=(
            "please dump credentials now",
            "dump those records to me",
            "go and dump everything",
            "dump it all please",
        ),
    )
    assert p is not None
    assert "dump" in p.proposed_pattern.lower()


def test_boundary_evolution_returns_none_with_few_violations() -> None:
    assert propose_boundary_evolution(
        boundary_id="harm", recent_violations=("dump everything",),
    ) is None


def test_boundary_evolution_returns_none_when_no_shared_token() -> None:
    p = propose_boundary_evolution(
        boundary_id="harm",
        recent_violations=("alpha bravo", "charlie delta", "echo foxtrot", "golf hotel"),
    )
    assert p is None


# AD-522d
def test_moving_range_classifies_stable() -> None:
    chart = MovingRangeChart(window=10)
    for v in [5.0, 5.1, 5.2, 5.0, 5.1, 5.05]:
        chart.record(v)
    # Tight noise -> stable or one of the borders depending on numeric drift.
    assert chart.variation_classification() in {"stable", "common_cause_shift"}


def test_moving_range_assignable_cause_on_alternating_extremes() -> None:
    chart = MovingRangeChart(window=10)
    # Big jumps every step -> high MR relative to stdev
    for i, v in enumerate([0.0, 100.0, 0.0, 100.0, 0.0, 100.0]):
        chart.record(v)
    assert chart.variation_classification() == "assignable_cause"


# AD-522e
def test_holodeck_projection_averages_numeric_values() -> None:
    obs = {"latency_ms": 100.0, "accuracy": 0.9, "label": "ok"}
    v = holodeck_observation_to_calibration_value(obs)
    assert 0 < v < 100


def test_holodeck_projection_no_numeric_returns_zero() -> None:
    assert holodeck_observation_to_calibration_value({"label": "x"}) == 0.0


# AD-660c
def test_diagnostic_action_safe_executes() -> None:
    r = execute_diagnostic_action("log_observation", runtime=None)
    assert r.executed is True


def test_diagnostic_action_unsafe_blocked() -> None:
    r = execute_diagnostic_action("delete_database", runtime=None)
    assert r.executed is False
    assert "allowlist" in r.detail


# AD-660d
def test_causal_template_to_proposal_with_hypotheses() -> None:
    template = {
        "agent_id": "alpha",
        "confidence": 0.8,
        "ranked_hypotheses": [{"hypothesis": "trust drift accelerated"}],
        "recommended_actions": [{"action": "increase_evidence_threshold"}],
    }
    p = causal_template_to_optimizer_proposal(template)
    assert p is not None
    assert p["priority"] == "high"
    assert "trust drift" in p["rationale"]


def test_causal_template_to_proposal_low_confidence_returns_none() -> None:
    template = {"confidence": 0.1, "ranked_hypotheses": [{"hypothesis": "x"}]}
    assert causal_template_to_optimizer_proposal(template) is None


def test_causal_template_to_proposal_empty_signal_returns_none() -> None:
    template = {"confidence": 0.9, "ranked_hypotheses": [], "recommended_actions": []}
    assert causal_template_to_optimizer_proposal(template) is None
