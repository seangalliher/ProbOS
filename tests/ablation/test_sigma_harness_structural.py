"""AD-1143 — structural-mode self-tests for the Σ ablation harness.

Zero LLM calls, zero network, seconds to run. These are the tests that prove
the harness itself is sound: the flag single-source-of-truth still resolves
against a live ``SystemConfig``, the goal set still satisfies the fairness
criterion, the statistics are correct at hand-computable boundaries, the judge
is blind and fails honestly, the artifact round-trips, and the comparison guard
actually fires.

Collected only when ``PROBOS_ABLATION`` is ``structural`` or ``live``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from probos.config import SystemConfig

from tests.ablation import sigma_judge, sigma_report, sigma_stats
from tests.ablation.sigma_flags import (
    ARM_NAMES,
    ARMS,
    CONTROL_ARM,
    SIGMA_OFF,
    SIGMA_ON,
    TREATMENT_ARM,
    apply_flags,
    flag_snapshot,
    resolve_flag,
)
from tests.ablation.sigma_goals import (
    DISCRIMINATORS,
    GOALSET_SMOKE_PATH,
    GOALSET_V1_PATH,
    load_goalset,
    sha256_file,
    validate_goalset,
)
from tests.ablation.sigma_rig import (
    ScriptedCrewLLM,
    ScriptedJudgeLLM,
    arm_config,
    build_base_config,
    crew_rig,
    run_goal,
    sigma_reachability_problems,
)


# --------------------------------------------------------------------- flags


def test_sigma_arms_declare_the_same_knobs() -> None:
    """The arms differ in values, never in which knobs exist."""
    assert set(SIGMA_ON) == set(SIGMA_OFF)
    assert SIGMA_ON != SIGMA_OFF
    assert set(ARMS) == set(ARM_NAMES)


def test_every_sigma_flag_path_resolves_to_a_bool_on_a_live_config() -> None:
    """DD-6's reason for existing: a rename in config.py must go red here.

    If AD-1141 renames one of these fields, this test fails rather than the
    flag becoming a no-op that quietly turns the treatment arm into a second
    control arm.
    """
    config = SystemConfig()
    assert SIGMA_OFF, "the flag set must not be empty"
    for path in SIGMA_OFF:
        value = resolve_flag(config, path)
        assert type(value) is bool, (
            f"{path} resolves to {type(value).__name__}, not bool"
        )


def test_resolve_flag_names_the_failing_segment() -> None:
    config = SystemConfig()
    with pytest.raises(AttributeError, match="no attribute 'nope_not_here'"):
        resolve_flag(config, "records.nope_not_here")
    with pytest.raises(ValueError, match="sigma_flag_path_empty"):
        resolve_flag(config, "")


def test_apply_flags_returns_a_new_config_and_leaves_the_source_untouched() -> None:
    source = SystemConfig()
    assert source.records.semantic_index_enabled is False

    applied = apply_flags(source, SIGMA_ON)

    assert applied is not source
    assert applied.records.semantic_index_enabled is True
    assert applied.agentic_tools.oracle_query_enabled is True
    assert source.records.semantic_index_enabled is False
    assert source.agentic_tools.oracle_query_enabled is False


def test_apply_flags_rejects_a_non_bool_value() -> None:
    with pytest.raises(TypeError, match="only toggles boolean gates"):
        apply_flags(SystemConfig(), {"records.semantic_index_enabled": 1})


def test_apply_flags_rejects_a_path_that_is_not_a_gate() -> None:
    with pytest.raises(TypeError, match="not bool"):
        apply_flags(SystemConfig(), {"records.repo_path": True})


def test_flag_snapshot_reads_runtime_values_not_the_arm_dict() -> None:
    config = apply_flags(SystemConfig(), SIGMA_ON)
    config.records.semantic_index_enabled = False  # simulate a failed apply
    snapshot = flag_snapshot(config)
    assert snapshot["records.semantic_index_enabled"] is False
    assert snapshot["agentic_tools.oracle_query_enabled"] is True


# ------------------------------------------------------------------ fixtures


def test_measurement_goalset_has_twelve_fair_goals() -> None:
    goalset = load_goalset(GOALSET_V1_PATH)
    assert goalset.version == "v1"
    assert len(goalset) == 12
    assert len({goal.id for goal in goalset.goals}) == 12
    for goal in goalset.goals:
        assert goal.discriminator in DISCRIMINATORS
        assert goal.solo_solvable is False
        assert goal.discriminator_note.strip()
        assert goal.children_hint >= 1
        if goal.discriminator == "cross_session":
            assert goal.seed_records, (
                f"{goal.id} is cross_session with no seed_records; there would "
                f"be nothing for a later session to retrieve"
            )


def test_smoke_goalset_is_schema_valid_and_distinctly_versioned() -> None:
    smoke = load_goalset(GOALSET_SMOKE_PATH)
    measurement = load_goalset(GOALSET_V1_PATH)
    assert smoke.version == "smoke-v1"
    assert smoke.version != measurement.version
    assert smoke.sha256 != measurement.sha256


def test_goalset_hash_is_the_file_bytes() -> None:
    goalset = load_goalset(GOALSET_V1_PATH)
    assert goalset.sha256 == hashlib.sha256(
        GOALSET_V1_PATH.read_bytes()
    ).hexdigest()
    assert goalset.sha256 == sha256_file(GOALSET_V1_PATH)


def _valid_goal(**overrides: Any) -> dict[str, Any]:
    entry = {
        "id": "x01",
        "goal": "Do the composite thing.",
        "children_hint": 2,
        "discriminator": "cross_child",
        "discriminator_note": "B needs A's output.",
        "solo_solvable": False,
        "seed_records": [],
    }
    entry.update(overrides)
    return entry


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"solo_solvable": True}, "solo_solvable"),
        ({"discriminator": "vibes"}, "discriminator"),
        ({"discriminator_note": "   "}, "discriminator_note"),
        ({"children_hint": 0}, "children_hint"),
        ({"goal": ""}, "empty goal text"),
        ({"discriminator": "cross_session"}, "no seed_records"),
    ],
)
def test_validate_goalset_rejects_each_schema_breach(
    overrides: dict[str, Any],
    expected: str,
) -> None:
    payload = {"goalset_version": "t", "goals": [_valid_goal(**overrides)]}
    with pytest.raises(ValueError, match=expected):
        validate_goalset(payload, source="test")


def test_validate_goalset_rejects_duplicate_ids_and_missing_version() -> None:
    with pytest.raises(ValueError, match="duplicate goal id"):
        validate_goalset(
            {"goalset_version": "t", "goals": [_valid_goal(), _valid_goal()]},
            source="test",
        )
    with pytest.raises(ValueError, match="goalset_version"):
        validate_goalset({"goals": [_valid_goal()]}, source="test")
    with pytest.raises(ValueError, match="non-empty list"):
        validate_goalset({"goalset_version": "t", "goals": []}, source="test")


# --------------------------------------------------------------------- stats


def test_cohens_dz_matches_a_hand_computed_value() -> None:
    # differences: 0.2, 0.4, 0.6  -> mean 0.4, sample sd 0.2 -> d_z = 2.0
    pairs = [(0.6, 0.4), (0.8, 0.4), (1.0, 0.4)]
    assert sigma_stats.cohens_dz(pairs) == pytest.approx(2.0, abs=1e-9)


def test_cohens_dz_is_zero_when_every_difference_is_zero() -> None:
    assert sigma_stats.cohens_dz([(0.5, 0.5), (0.7, 0.7)]) == 0.0


def test_cohens_dz_refuses_a_zero_variance_non_zero_effect() -> None:
    # Exact binary fractions, so every difference is exactly 0.25 and the
    # dispersion really is zero rather than a float artefact.
    with pytest.raises(ValueError, match="zero_variance"):
        sigma_stats.cohens_dz([(0.5, 0.25), (0.75, 0.5), (1.0, 0.75)])


def test_cohens_dz_needs_two_pairs() -> None:
    with pytest.raises(ValueError, match="at_least_two_pairs"):
        sigma_stats.cohens_dz([(0.6, 0.4)])


def test_bootstrap_ci_is_reproducible_for_a_fixed_seed() -> None:
    pairs = [(0.6, 0.4), (0.8, 0.5), (0.55, 0.6), (0.9, 0.5), (0.7, 0.65)]
    first = sigma_stats.bootstrap_ci(pairs, iterations=500)
    second = sigma_stats.bootstrap_ci(pairs, iterations=500)
    assert first == second
    other = sigma_stats.bootstrap_ci(pairs, iterations=500, seed=7)
    assert other != first


def test_bootstrap_ci_validates_its_arguments() -> None:
    pairs = [(0.6, 0.4), (0.8, 0.5)]
    with pytest.raises(ValueError, match="positive_iterations"):
        sigma_stats.bootstrap_ci(pairs, iterations=0)
    with pytest.raises(ValueError, match="alpha_out_of_range"):
        sigma_stats.bootstrap_ci(pairs, alpha=1.0)
    with pytest.raises(ValueError, match="at_least_two_pairs"):
        sigma_stats.bootstrap_ci([(0.6, 0.4)])


def test_interpret_returns_inconclusive_when_the_interval_spans_zero() -> None:
    assert sigma_stats.interpret(1.9, (-0.4, 2.2)) == sigma_stats.INCONCLUSIVE
    assert sigma_stats.interpret(1.9, (0.2, 2.2)) == sigma_stats.FAVOURS_SIGMA
    assert sigma_stats.interpret(-1.9, (-2.2, -0.2)) == sigma_stats.FAVOURS_CONTROL


def test_interpret_is_vetoed_by_dominant_variance_however_large_the_effect() -> None:
    assert sigma_stats.interpret(
        9.9, (5.0, 15.0), variance_dominates=True,
    ) == sigma_stats.INCONCLUSIVE


def test_variance_dominates_triggers_at_or_above_the_arm_delta() -> None:
    assert sigma_stats.variance_dominates(0.2, 0.1) is True
    assert sigma_stats.variance_dominates(0.1, 0.1) is True
    assert sigma_stats.variance_dominates(0.05, 0.1) is False


def test_pooled_sd_ignores_cells_that_cannot_have_a_spread() -> None:
    assert sigma_stats.pooled_sd([[0.5], [0.7]]) == 0.0
    assert sigma_stats.pooled_sd([[0.4, 0.6]]) == pytest.approx(
        sigma_stats.stdev([0.4, 0.6]), abs=1e-12,
    )


def test_mean_and_stdev_boundaries() -> None:
    with pytest.raises(ValueError, match="at_least_one_observation"):
        sigma_stats.mean([])
    with pytest.raises(ValueError, match="at_least_two_observations"):
        sigma_stats.stdev([1.0])
    assert sigma_stats.mean([1.0, 2.0, 3.0]) == pytest.approx(2.0, abs=1e-12)


# --------------------------------------------------------------------- judge


def test_rubric_hash_is_the_file_bytes() -> None:
    rubric = sigma_judge.load_rubric()
    assert rubric.sha256 == hashlib.sha256(
        sigma_judge.RUBRIC_V1_PATH.read_bytes()
    ).hexdigest()
    assert rubric.version == sigma_judge.RUBRIC_VERSION == "sigma-ablation-v1"


def test_rendered_judge_prompt_is_blind() -> None:
    """Assert on the actual rendered string, not on the template."""
    rubric = sigma_judge.load_rubric()
    goalset = load_goalset(GOALSET_V1_PATH)
    for goal in goalset.goals:
        prompt, truncated = sigma_judge.render_judge_prompt(
            goal_text=goal.goal,
            artifact="### Part 1\nA neutral produced artifact.",
            rubric=rubric,
        )
        assert truncated is False
        assert sigma_judge.blindness_violations(prompt) == (), (
            f"{goal.id} renders a prompt that would unblind the judge"
        )
        for arm in ARM_NAMES:
            assert arm not in prompt


def test_load_rubric_refuses_a_rubric_that_would_unblind(tmp_path: Path) -> None:
    leaky = tmp_path / "leaky.md"
    leaky.write_text("Score the treatment arm.", encoding="utf-8")
    with pytest.raises(ValueError, match="unblind"):
        sigma_judge.load_rubric(leaky)


def test_render_judge_prompt_refuses_goal_text_that_would_unblind() -> None:
    with pytest.raises(ValueError, match="unblind"):
        sigma_judge.render_judge_prompt(
            goal_text="Compare the sigma arm to the baseline.",
            artifact="x",
            rubric=sigma_judge.load_rubric(),
        )


def test_render_judge_prompt_records_truncation() -> None:
    rubric = sigma_judge.load_rubric()
    oversized = "x" * (sigma_judge.ARTIFACT_MAX_CHARS + 10)
    prompt, truncated = sigma_judge.render_judge_prompt(
        goal_text="Do the thing.", artifact=oversized, rubric=rubric,
    )
    assert truncated is True
    assert "x" * sigma_judge.ARTIFACT_MAX_CHARS in prompt
    assert oversized not in prompt


def test_blind_order_is_seeded_stable_and_covers_both_arms() -> None:
    first = sigma_judge.blind_order("g01")
    assert first == sigma_judge.blind_order("g01")
    assert set(first) == set(ARM_NAMES)
    orders = {goal_id: sigma_judge.blind_order(goal_id) for goal_id in
              (f"g{n:02d}" for n in range(1, 13))}
    # A seeded shuffle that never varies would be a constant, not a blind.
    assert len(set(orders.values())) == 2
    assert sigma_judge.blind_position("g01", first[0]) == 1
    assert sigma_judge.blind_position("g01", first[1]) == 2
    with pytest.raises(ValueError, match="unknown arm"):
        sigma_judge.blind_position("g01", "nope")


class _StubResponse:
    def __init__(self, content: str, *, error: str | None = None) -> None:
        self.content = content
        self.model = "stub-model"
        self.tier = "deep"
        self.error = error
        self.content_blocks: list[Any] = []


class _StubLLM:
    def __init__(self, response: Any = None, *, raises: bool = False) -> None:
        self._response = response
        self._raises = raises
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> Any:
        self.requests.append(request)
        if self._raises:
            raise RuntimeError("judge exploded")
        return self._response


async def test_judge_scores_a_well_formed_payload() -> None:
    payload = {name: 0.5 for name in sigma_judge.DIMENSIONS}
    payload["coordination_quality"] = 1.0
    outcome = await sigma_judge.score_artifact(
        _StubLLM(_StubResponse(json.dumps(payload))),
        goal_text="Do the thing.",
        artifact="an artifact",
        rubric=sigma_judge.load_rubric(),
    )
    assert outcome.judge_failed is False
    assert outcome.composite == pytest.approx((1.0 + 0.5 * 3) / 4, abs=1e-12)
    assert outcome.judge_model == "stub-model"
    assert outcome.judge_tier == "deep"


@pytest.mark.parametrize(
    ("client", "reason"),
    [
        (_StubLLM(raises=True), "llm_exception"),
        (_StubLLM(_StubResponse("not json at all")), "json_parse_failed"),
        (_StubLLM(_StubResponse("")), "empty_content"),
        (_StubLLM(_StubResponse("{}", error="boom")), "llm_error"),
        (
            _StubLLM(_StubResponse(json.dumps({
                "coordination_quality": 1.4,
                "reasoning_depth": 0.5,
                "knowledge_retention": 0.5,
                "artifact_correctness": 0.5,
            }))),
            "score_out_of_range",
        ),
        (
            _StubLLM(_StubResponse(json.dumps({
                "coordination_quality": "high",
                "reasoning_depth": 0.5,
                "knowledge_retention": 0.5,
                "artifact_correctness": 0.5,
            }))),
            "non_numeric_score",
        ),
        (
            _StubLLM(_StubResponse(json.dumps({"reasoning_depth": 0.5}))),
            "missing_dimension",
        ),
    ],
)
async def test_judge_failure_is_never_a_zero_score(
    client: Any,
    reason: str,
) -> None:
    """A zero is indistinguishable from a genuinely terrible artifact."""
    outcome = await sigma_judge.score_artifact(
        client,
        goal_text="Do the thing.",
        artifact="an artifact",
        rubric=sigma_judge.load_rubric(),
    )
    assert outcome.judge_failed is True
    assert outcome.failure_reason is not None
    assert reason in outcome.failure_reason
    assert outcome.scores is None
    assert outcome.composite is None
    assert outcome.judge_tier


async def test_judge_without_a_client_fails_rather_than_scoring_zero() -> None:
    outcome = await sigma_judge.score_artifact(
        None,
        goal_text="Do the thing.",
        artifact="an artifact",
        rubric=sigma_judge.load_rubric(),
    )
    assert outcome.judge_failed is True
    assert outcome.failure_reason == "no_llm_client"
    assert outcome.composite is None


# -------------------------------------------------------------------- report


def _row(
    goal_id: str,
    arm: str,
    trial: int,
    composite: float | None,
    *,
    failed: bool = False,
) -> sigma_report.ResultRow:
    scores = (
        None if composite is None
        else {name: composite for name in sigma_judge.DIMENSIONS}
    )
    return sigma_report.ResultRow(
        goal_id=goal_id,
        arm=arm,
        trial=trial,
        judge_failed=failed,
        judge_model="stub-model",
        judge_tier="deep",
        blind_position=1 if arm == CONTROL_ARM else 2,
        scores=scores,
        composite=composite,
        failure_reason="llm_exception" if failed else None,
    )


def _rows(deltas: dict[str, tuple[float, float]]) -> list[sigma_report.ResultRow]:
    rows: list[sigma_report.ResultRow] = []
    for goal_id, (treatment, control) in deltas.items():
        rows.append(_row(goal_id, TREATMENT_ARM, 0, treatment))
        rows.append(_row(goal_id, CONTROL_ARM, 0, control))
    return rows


def test_report_carries_the_headline_fields_and_the_power_note() -> None:
    summary = sigma_report.summarize(
        rows=_rows({
            "g01": (0.70, 0.50),
            "g02": (0.80, 0.55),
            "g03": (0.65, 0.60),
            "g04": (0.90, 0.50),
        }),
        trials_per_goal=1,
        bootstrap_iterations=200,
    )
    report = sigma_report.render_report(summary, mode="structural")
    assert "direction=" in report
    assert "d_z=" in report
    assert "ci95=[" in report
    assert f"n_pairs={summary.n_pairs}" in report
    assert 'power_note="' in report
    assert sigma_stats.POWER_NOTE in report
    assert sigma_report.REPORT_DISCLAIMER in report


def test_report_never_implies_a_hypothesis_test() -> None:
    summary = sigma_report.summarize(
        rows=_rows({
            "g01": (0.70, 0.50),
            "g02": (0.80, 0.55),
            "g03": (0.65, 0.60),
        }),
        trials_per_goal=1,
        bootstrap_iterations=200,
    )
    report = sigma_report.render_report(summary, mode="structural").lower()
    for forbidden in sigma_report.FORBIDDEN_REPORT_SUBSTRINGS:
        assert forbidden not in report
    assert "significant" not in report


def test_render_report_refuses_to_emit_a_leaked_claim() -> None:
    summary = sigma_report.summarize(
        rows=_rows({"g01": (0.7, 0.5), "g02": (0.8, 0.5), "g03": (0.6, 0.5)}),
        trials_per_goal=1,
        bootstrap_iterations=200,
    )
    with pytest.raises(ValueError, match="statistical claim"):
        sigma_report.render_report(
            summary, mode="structural", extra_notes=["the result is significant"],
        )


def test_variance_veto_banners_the_report_and_forces_inconclusive() -> None:
    """Three trials per cell with wide spread, and a large but noisy effect."""
    rows: list[sigma_report.ResultRow] = []
    for index, goal_id in enumerate(("g01", "g02", "g03", "g04")):
        base = 0.10 + index * 0.02
        for trial, offset in enumerate((-0.30, 0.0, 0.30)):
            rows.append(_row(goal_id, TREATMENT_ARM, trial, 0.50 + base + offset))
            rows.append(_row(goal_id, CONTROL_ARM, trial, 0.50 + offset))

    summary = sigma_report.summarize(
        rows=rows, trials_per_goal=3, bootstrap_iterations=200,
    )
    assert summary.between_trial_sd_measured is True
    assert summary.between_trial_sd >= summary.between_arm_delta
    assert summary.variance_dominates is True
    assert summary.d_z is not None and abs(summary.d_z) > 1.0
    assert summary.direction == sigma_stats.INCONCLUSIVE

    report = sigma_report.render_report(summary, mode="structural")
    assert report.startswith("VARIANCE_DOMINATES")


def test_unmeasured_trial_noise_is_reported_as_unmeasured_not_zero() -> None:
    summary = sigma_report.summarize(
        rows=_rows({"g01": (0.7, 0.5), "g02": (0.8, 0.55), "g03": (0.6, 0.5)}),
        trials_per_goal=1,
        bootstrap_iterations=200,
    )
    assert summary.between_trial_sd_measured is False
    report = sigma_report.render_report(summary, mode="structural")
    assert "between_trial_sd=unmeasured" in report
    assert "NOT measured" in report


def test_judge_failures_are_excluded_from_the_aggregate() -> None:
    rows = [
        _row("g01", TREATMENT_ARM, 0, 0.8),
        _row("g01", TREATMENT_ARM, 1, None, failed=True),
        _row("g01", CONTROL_ARM, 0, 0.4),
    ]
    aggregate = sigma_report.aggregate_rows(
        [row for row in rows if row.arm == TREATMENT_ARM],
    )
    assert aggregate["n_judge_failures"] == 1
    assert aggregate["mean_composite"] == pytest.approx(0.8, abs=1e-12)
    assert sigma_report.goal_means(rows, TREATMENT_ARM) == {"g01": 0.8}


def test_a_goal_with_no_usable_trial_is_unpaired_not_scored_zero() -> None:
    rows = [
        _row("g01", TREATMENT_ARM, 0, 0.8),
        _row("g01", CONTROL_ARM, 0, 0.4),
        _row("g02", TREATMENT_ARM, 0, 0.7),
        _row("g02", CONTROL_ARM, 0, None, failed=True),
        _row("g03", TREATMENT_ARM, 0, 0.6),
        _row("g03", CONTROL_ARM, 0, 0.5),
    ]
    summary = sigma_report.summarize(
        rows=rows, trials_per_goal=1, bootstrap_iterations=200,
    )
    assert summary.unpaired_goal_ids == ("g02",)
    assert summary.n_pairs == 2
    report = sigma_report.render_report(summary, mode="structural")
    assert "unpaired goals" in report and "g02" in report


# ------------------------------------------------------------------ artifact


def _artifact(**overrides: Any) -> dict[str, Any]:
    goalset = load_goalset(GOALSET_SMOKE_PATH)
    rubric = sigma_judge.load_rubric()
    artifact = sigma_report.build_artifact(
        arm=CONTROL_ARM,
        rows=[_row("s01", CONTROL_ARM, 0, 0.5)],
        goalset_version=goalset.version,
        goalset_sha256=goalset.sha256,
        rubric_version=rubric.version,
        rubric_sha256=rubric.sha256,
        flags=dict(SIGMA_OFF),
        judge_model="stub-model",
        judge_tier="deep",
        judge_temperature=0.0,
        trials_per_goal=1,
        mode="structural",
        probos_commit="c" * 40,
        captured_utc="2026-07-25T00:00:00Z",
    )
    artifact.update(overrides)
    return artifact


def test_artifact_round_trips_with_every_required_key(tmp_path: Path) -> None:
    artifact = _artifact()
    assert sigma_report.ARTIFACT_KEYS <= set(artifact)
    path = sigma_report.write_artifact(artifact, tmp_path / "a.json")
    restored = sigma_report.read_artifact(path)
    assert restored == artifact
    assert restored["disclaimer"] == sigma_report.DISCLAIMER
    assert restored["results"][0]["judge_model"] == "stub-model"
    assert restored["results"][0]["judge_tier"] == "deep"
    assert restored["results"][0]["blind_position"] == 1


def test_read_artifact_rejects_a_missing_required_key(tmp_path: Path) -> None:
    artifact = _artifact()
    del artifact["config_fingerprint"]
    path = tmp_path / "b.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="config_fingerprint"):
        sigma_report.read_artifact(path)


def test_disclaimer_is_verbatim_in_the_module_docstring() -> None:
    from tests.ablation import test_sigma_ablation

    assert sigma_report.__doc__ is not None
    assert sigma_report.DISCLAIMER in sigma_report.__doc__
    assert test_sigma_ablation.__doc__ is not None
    assert sigma_report.DISCLAIMER in test_sigma_ablation.__doc__


def test_config_fingerprint_pins_every_recent_agentic_loop_field() -> None:
    config = SystemConfig()
    for path, value in sigma_report.PINNED_AGENTIC_LOOP.items():
        current = resolve_flag(config, path)
        assert type(current) is type(value), (
            f"{path} resolves to {type(current).__name__}, pinned as "
            f"{type(value).__name__}"
        )
    pinned = sigma_report.apply_pinned_config(config)
    assert pinned is not config
    for path, value in sigma_report.PINNED_AGENTIC_LOOP.items():
        assert resolve_flag(pinned, path) == value
    assert sigma_report.config_fingerprint(
        sigma_report.PINNED_AGENTIC_LOOP
    ) == sigma_report.config_fingerprint(sigma_report.PINNED_AGENTIC_LOOP)
    moved = dict(sigma_report.PINNED_AGENTIC_LOOP)
    moved["agentic_loop.max_parallel_tool_calls"] = 9
    assert sigma_report.config_fingerprint(moved) != sigma_report.config_fingerprint(
        sigma_report.PINNED_AGENTIC_LOOP
    )


@pytest.mark.parametrize("field_name", sigma_report.GATED_COMPARISON_FIELDS)
def test_compare_to_baseline_raises_naming_the_diverging_field(
    field_name: str,
) -> None:
    baseline = _artifact()
    current = _artifact(**{field_name: "0" * 64})
    with pytest.raises(ValueError, match=field_name):
        sigma_report.compare_to_baseline(baseline, current)


def test_compare_to_baseline_surfaces_commit_and_judge_drift_without_raising() -> None:
    baseline = _artifact()
    current = _artifact(
        probos_commit="d" * 40,
        judge={"model": "other-model", "tier": "deep", "temperature": 0.0},
    )
    comparison = sigma_report.compare_to_baseline(baseline, current)
    assert comparison.commit_changed is True
    assert comparison.judge_model_changed is True
    assert len(comparison.differences) == 2

    summary = sigma_report.summarize(
        rows=_rows({"g01": (0.7, 0.5), "g02": (0.8, 0.55), "g03": (0.6, 0.5)}),
        trials_per_goal=1,
        bootstrap_iterations=200,
    )
    report = sigma_report.render_report(
        summary, mode="structural", comparison=comparison,
    )
    assert "baseline comparison:" in report
    assert "probos_commit changed" in report
    assert "judge.model changed" in report


def test_compare_to_baseline_accepts_an_identical_artifact() -> None:
    baseline = _artifact()
    comparison = sigma_report.compare_to_baseline(baseline, _artifact())
    assert comparison.differences == ()


def test_baseline_filename_encodes_the_versions_and_the_date() -> None:
    name = sigma_report.baseline_filename(
        arm=CONTROL_ARM,
        goalset_version="v1",
        rubric_version="sigma-ablation-v1",
        captured_utc="2026-07-25T11:22:33Z",
    )
    assert name == "sigma_off_v1_sigma-ablation-v1_20260725.json"


# ----------------------------------------------------------------------- rig


async def test_both_arms_construct_and_the_orchestrator_sees_different_flags(
    tmp_path: Path,
) -> None:
    """Assert on the config the orchestrator received, not on the arm dict."""
    base = build_base_config(tmp_path / "base")
    observed: dict[str, dict[str, Any]] = {}
    for arm in ARM_NAMES:
        async with crew_rig(
            arm=arm,
            workspace=tmp_path / arm,
            llm_client=ScriptedCrewLLM(arm=arm),
            base_config=base,
        ) as rig:
            assert rig.runtime.config is rig.config
            observed[arm] = dict(rig.runtime_flags)

    assert observed[CONTROL_ARM] != observed[TREATMENT_ARM]
    assert set(observed[CONTROL_ARM]) == set(observed[TREATMENT_ARM])
    assert all(value is False for value in observed[CONTROL_ARM].values())
    assert all(value is True for value in observed[TREATMENT_ARM].values())


async def test_arm_config_never_mutates_the_shared_base(tmp_path: Path) -> None:
    base = build_base_config(tmp_path / "base")
    treatment = arm_config(base, TREATMENT_ARM)
    control = arm_config(base, CONTROL_ARM)
    assert treatment.records.semantic_index_enabled is True
    assert control.records.semantic_index_enabled is False
    assert base.records.semantic_index_enabled is False
    with pytest.raises(ValueError, match="unknown arm"):
        arm_config(base, "sigma_maybe")


async def test_control_arm_leaves_the_shared_surface_unreachable(
    tmp_path: Path,
) -> None:
    """The treatment arm registers the consult tool; the control arm does not.

    This is the ablation itself: the seeded records exist in both arms, and
    only the access mechanism differs.
    """
    base = build_base_config(tmp_path / "base")
    seeds = ({"title": "Retention", "body": "72 hours."},)
    reachable: dict[str, bool] = {}
    for arm in ARM_NAMES:
        async with crew_rig(
            arm=arm,
            workspace=tmp_path / f"reach-{arm}",
            llm_client=ScriptedCrewLLM(arm=arm),
            base_config=base,
            seed_records=seeds,
        ) as rig:
            reachable[arm] = rig.runtime.tool_registry.get("oracle_query") is not None
            assert sigma_reachability_problems(rig) == ()
    assert reachable[TREATMENT_ARM] is True
    assert reachable[CONTROL_ARM] is False


async def test_a_crew_run_produces_a_judgeable_artifact_with_no_network(
    tmp_path: Path,
) -> None:
    goalset = load_goalset(GOALSET_SMOKE_PATH)
    goal = goalset.goals[0]
    client = ScriptedCrewLLM(arm=CONTROL_ARM, seed="unit")
    async with crew_rig(
        arm=CONTROL_ARM,
        workspace=tmp_path / "run",
        llm_client=client,
        base_config=build_base_config(tmp_path / "base"),
    ) as rig:
        outcome = await run_goal(rig, goal, trial=0)

    assert outcome.completed is True
    assert outcome.total_count == goal.children_hint
    assert outcome.accepted_count == goal.children_hint
    assert outcome.llm_calls == len(client.requests) > 0
    assert outcome.final_output.count("### Part ") == goal.children_hint
    assert outcome.runtime_flags == dict(SIGMA_OFF)


async def test_the_same_goal_and_arm_replays_byte_identically(
    tmp_path: Path,
) -> None:
    """Structural mode must be fully deterministic, or nothing below it is."""
    goal = load_goalset(GOALSET_SMOKE_PATH).goals[0]
    base = build_base_config(tmp_path / "base")
    outputs: list[str] = []
    for attempt in range(2):
        async with crew_rig(
            arm=TREATMENT_ARM,
            workspace=tmp_path / f"replay-{attempt}",
            llm_client=ScriptedCrewLLM(arm=TREATMENT_ARM, seed="replay"),
            base_config=base,
        ) as rig:
            outputs.append((await run_goal(rig, goal, trial=0)).final_output)
    assert outputs[0] == outputs[1]


async def test_the_scripted_judge_is_deterministic_and_blind() -> None:
    rubric = sigma_judge.load_rubric()
    first = await sigma_judge.score_artifact(
        ScriptedJudgeLLM(),
        goal_text="Do the thing.",
        artifact="### Part 1\nsome content",
        rubric=rubric,
    )
    second = await sigma_judge.score_artifact(
        ScriptedJudgeLLM(),
        goal_text="Do the thing.",
        artifact="### Part 1\nsome content",
        rubric=rubric,
    )
    different = await sigma_judge.score_artifact(
        ScriptedJudgeLLM(),
        goal_text="Do the thing.",
        artifact="### Part 1\nother content",
        rubric=rubric,
    )
    assert first.scores == second.scores
    assert first.scores != different.scores
    assert first.judge_failed is False


async def test_a_raising_scripted_judge_produces_an_excluded_row() -> None:
    outcome = await sigma_judge.score_artifact(
        ScriptedJudgeLLM(failures=1),
        goal_text="Do the thing.",
        artifact="an artifact",
        rubric=sigma_judge.load_rubric(),
    )
    assert outcome.judge_failed is True
    assert outcome.composite is None
