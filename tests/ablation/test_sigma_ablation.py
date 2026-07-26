"""AD-1143 — the with/without-Σ ablation runner (Nooplex §8.3).

This harness produces a directional signal, not a publishable effect size. The
shipped goal set is 12 items, not the ≥100 that Nooplex §8.5 asks for, because
each item costs a full live crew run. Cohen's d and its confidence interval are
reported so the direction and rough magnitude of the Σ effect are visible; the
harness never claims statistical significance and never prints the word
"significant". §8.5 compliance is not claimed.

**This module is never collected by the default gate.** ``conftest.py`` in this
directory ignores ``test_*.py`` unless ``PROBOS_ABLATION`` is ``structural`` or
``live``. See ``tests/test_ad1143_ablation_gating.py`` for the guard that proves
it, including the AST-level ``compile()`` sweep that keeps syntax rot visible in
a file CI never opens.

Modes (DD-8):

===========  ====================================  ==========================
``PROBOS_ABLATION``  LLM                            Goal set
===========  ====================================  ==========================
``structural``  none — deterministic scripted client  ``sigma_goals_smoke.json``
``live``        real client via the proxy             ``sigma_goals_v1.json``
===========  ====================================  ==========================

``structural`` is the Builder's acceptance gate and burns zero LLM calls.
``live`` costs real money and real time and is run only on explicit
instruction.

Optional environment overrides::

    PROBOS_ABLATION_TRIALS=<n>           override trials per goal
    PROBOS_ABLATION_CAPTURE_BASELINE=1   also write the sigma_off artifact into
                                         tests/ablation/baselines/
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.ablation import sigma_judge, sigma_report
from tests.ablation.sigma_flags import (
    ARM_NAMES,
    CONTROL_ARM,
    TREATMENT_ARM,
)
from tests.ablation.sigma_goals import (
    GOALSET_SMOKE_PATH,
    GOALSET_V1_PATH,
    Goal,
    GoalSet,
    load_goalset,
)
from tests.ablation.sigma_rig import (
    SYNTHESIS_STRATEGY,
    ScriptedCrewLLM,
    ScriptedJudgeLLM,
    build_base_config,
    crew_rig,
    run_goal,
    sigma_reachability_problems,
)

MODE = os.environ.get("PROBOS_ABLATION", "")
STRUCTURAL = "structural"
LIVE = "live"

_DEFAULT_TRIALS = {STRUCTURAL: 1, LIVE: 3}


def _trials_per_goal() -> int:
    override = os.environ.get("PROBOS_ABLATION_TRIALS", "").strip()
    if override:
        value = int(override)
        if value < 1:
            raise ValueError("PROBOS_ABLATION_TRIALS must be >= 1")
        return value
    return _DEFAULT_TRIALS.get(MODE, 1)


def _goalset() -> GoalSet:
    return load_goalset(GOALSET_SMOKE_PATH if MODE == STRUCTURAL else GOALSET_V1_PATH)


def _live_skip_reason() -> str | None:
    """Named reason live mode must not run, or ``None``.

    Never a silent degrade: live mode either runs under the exact declared
    conditions or says precisely why it did not.
    """
    embeddings = os.environ.get("PROBOS_EMBEDDINGS", "")
    if embeddings != "local":
        return (
            f"live mode requires PROBOS_EMBEDDINGS=local (BF-657) so the run "
            f"never reaches for a remote embedding model; found "
            f"{embeddings or '<unset>'}"
        )
    return None


async def _build_live_clients(config: Any) -> tuple[Any, Any, str | None]:
    """Construct the real client for both roles, or return a skip reason."""
    try:
        from probos.cognitive.llm_client import OpenAICompatibleClient
    except Exception as exc:  # pragma: no cover - import shape guard
        return None, None, f"live mode cannot import the LLM client: {exc}"
    try:
        client = OpenAICompatibleClient(config=config.cognitive)
    except Exception as exc:
        return None, None, f"live mode cannot construct the LLM client: {exc}"

    from probos.types import LLMRequest

    try:
        probe = await client.complete(LLMRequest(
            prompt="Reply with the single word: ready",
            tier=sigma_judge.JUDGE_TIER,
            max_tokens=8,
            temperature=0.0,
        ))
    except Exception as exc:
        return None, None, f"live mode found no reachable LLM endpoint: {exc}"
    if getattr(probe, "error", None):
        return None, None, (
            f"live mode found no reachable LLM endpoint: {probe.error}"
        )
    return client, client, None


async def _judge_rows(
    *,
    judge_client: Any,
    rubric: sigma_judge.Rubric,
    goal: Goal,
    artifacts_by_arm: dict[str, list[str]],
) -> tuple[list[sigma_report.ResultRow], tuple[str, ...]]:
    """Score one goal's artifacts blind, in the seeded presentation order."""
    order = sigma_judge.blind_order(goal.id)
    rows: list[sigma_report.ResultRow] = []
    for position, arm in enumerate(order, start=1):
        for trial, artifact in enumerate(artifacts_by_arm.get(arm, [])):
            outcome = await sigma_judge.score_artifact(
                judge_client,
                goal_text=goal.goal,
                artifact=artifact,
                rubric=rubric,
            )
            rows.append(sigma_report.ResultRow(
                goal_id=goal.id,
                arm=arm,
                trial=trial,
                judge_failed=outcome.judge_failed,
                judge_model=outcome.judge_model,
                judge_tier=outcome.judge_tier,
                blind_position=position,
                scores=outcome.scores,
                composite=outcome.composite,
                failure_reason=outcome.failure_reason,
                artifact_truncated=outcome.artifact_truncated,
            ))
    return rows, order


@pytest.mark.timeout(3600)
async def test_sigma_ablation_run(tmp_path: Path) -> None:
    """Run both arms over the mode's goal set and emit the artifacts + report."""
    assert MODE in {STRUCTURAL, LIVE}, (
        f"PROBOS_ABLATION={MODE!r} is not a mode; conftest.py should have "
        f"prevented collection"
    )
    if MODE == LIVE:
        reason = _live_skip_reason()
        if reason:
            pytest.skip(reason)

    goalset = _goalset()
    rubric = sigma_judge.load_rubric()
    trials = _trials_per_goal()
    base_config = build_base_config(tmp_path / "base")

    live_client: Any = None
    if MODE == LIVE:
        live_client, _judge, skip_reason = await _build_live_clients(base_config)
        if skip_reason:
            pytest.skip(skip_reason)

    judge_client: Any = ScriptedJudgeLLM() if MODE == STRUCTURAL else live_client
    crew_clients: list[Any] = []
    rows: list[sigma_report.ResultRow] = []
    blind_map: dict[str, tuple[str, ...]] = {}
    calls_per_goal: dict[str, int] = {}
    observed_flags: dict[str, dict[str, Any]] = {}
    observed_wiring: dict[str, tuple[str, ...]] = {}

    for goal in goalset.goals:
        artifacts_by_arm: dict[str, list[str]] = {arm: [] for arm in ARM_NAMES}
        goal_calls = 0
        for arm in ARM_NAMES:
            for trial in range(trials):
                if MODE == STRUCTURAL:
                    crew_client: Any = ScriptedCrewLLM(
                        arm=arm, seed=f"{goal.id}:{trial}",
                    )
                    crew_clients.append(crew_client)
                else:
                    crew_client = live_client
                workspace = tmp_path / "runs" / goal.id / arm / f"trial-{trial}"
                async with crew_rig(
                    arm=arm,
                    workspace=workspace,
                    llm_client=crew_client,
                    base_config=base_config,
                    seed_records=goal.seed_records,
                    max_parallel=3,
                    agent_count=max(2, goal.children_hint),
                ) as rig:
                    observed_flags[arm] = dict(rig.runtime_flags)
                    observed_wiring[arm] = rig.sigma_wiring
                    if MODE == LIVE:
                        problems = sigma_reachability_problems(rig)
                        if problems:
                            pytest.skip(
                                f"live mode refuses arm {arm}: the shared-"
                                f"knowledge surface is not reachable "
                                f"({list(problems)}); scoring it would record "
                                f"a silently degraded arm as a null effect"
                            )
                    outcome = await run_goal(rig, goal, trial=trial)
                artifacts_by_arm[arm].append(outcome.final_output)
                goal_calls += outcome.llm_calls
                assert outcome.total_count == goal.children_hint, (
                    f"{goal.id}/{arm}/trial {trial}: expected "
                    f"{goal.children_hint} child results, got "
                    f"{outcome.total_count}"
                )
                assert outcome.final_output.strip(), (
                    f"{goal.id}/{arm}/trial {trial} produced an empty artifact; "
                    f"there is nothing to judge"
                )
        calls_per_goal[goal.id] = goal_calls
        goal_rows, order = await _judge_rows(
            judge_client=judge_client,
            rubric=rubric,
            goal=goal,
            artifacts_by_arm=artifacts_by_arm,
        )
        rows.extend(goal_rows)
        blind_map[goal.id] = order

    # DD-6: the arms must differ in what the orchestrator actually saw, not
    # merely in the dicts the harness passed around.
    assert observed_flags[TREATMENT_ARM] != observed_flags[CONTROL_ARM], (
        f"both arms saw identical runtime flags {observed_flags}; the "
        f"treatment arm has silently become a second control arm"
    )
    assert all(observed_flags[CONTROL_ARM][path] is False
               for path in observed_flags[CONTROL_ARM])
    assert all(observed_flags[TREATMENT_ARM][path] is True
               for path in observed_flags[TREATMENT_ARM])

    if MODE == STRUCTURAL:
        # Zero live LLM calls: every completion in the run came from a scripted
        # client, and their counts account for all of them.
        scripted_crew_calls = sum(len(c.requests) for c in crew_clients)
        scripted_judge_calls = len(judge_client.requests)
        assert scripted_crew_calls == sum(calls_per_goal.values())
        assert scripted_judge_calls == len(rows)
        assert scripted_crew_calls > 0 and scripted_judge_calls > 0

    judge_models = sorted({row.judge_model for row in rows})
    judge_tiers = sorted({row.judge_tier for row in rows})
    assert all(row.judge_tier for row in rows), (
        "every result row must carry the tier that actually answered, so a "
        "mid-run tier fallback is visible"
    )

    run_notes = [
        f"synthesis={SYNTHESIS_STRATEGY}: accepted child outputs are "
        f"concatenated in a stable order rather than folded by an LLM, so the "
        f"coordination seams survive to the judge.",
        f"measured crew LLM calls per goal (B-2), summed over both arms and "
        f"all {trials} trial(s), judge calls excluded: "
        f"{json.dumps(calls_per_goal, sort_keys=True)}",
        f"judge LLM calls: {len(rows)} (one per scored artifact).",
        f"blind presentation order is seeded at {sigma_judge.BLIND_SEED} and "
        f"recorded per goal so the unblinding is auditable.",
    ]
    if MODE == STRUCTURAL:
        run_notes.insert(0, (
            "STRUCTURAL MODE. Scores come from a deterministic scripted client "
            "and mean nothing about the effect of shared knowledge flow. This "
            "artifact proves the harness, not a result."
        ))
    # The two standing caveats are rendered by the report itself; the artifact
    # carries them explicitly because it is read on its own.
    artifact_notes = [
        sigma_report.JUDGE_FAMILY_CAVEAT,
        sigma_report.LOCAL_EMBEDDINGS_CAVEAT,
        *run_notes,
    ]

    run_dir = tmp_path / "artifacts"
    artifacts: dict[str, dict[str, Any]] = {}
    for arm in ARM_NAMES:
        arm_rows = [row for row in rows if row.arm == arm]
        artifact = sigma_report.build_artifact(
            arm=arm,
            rows=arm_rows,
            goalset_version=goalset.version,
            goalset_sha256=goalset.sha256,
            rubric_version=rubric.version,
            rubric_sha256=rubric.sha256,
            flags=observed_flags[arm],
            judge_model=judge_models[0] if len(judge_models) == 1 else
            ",".join(judge_models),
            judge_tier=judge_tiers[0] if len(judge_tiers) == 1 else
            ",".join(judge_tiers),
            judge_temperature=sigma_judge.JUDGE_TEMPERATURE,
            trials_per_goal=trials,
            mode=MODE,
            embeddings=os.environ.get("PROBOS_EMBEDDINGS", "") or "unset",
            notes=artifact_notes + [f"sigma_wiring={list(observed_wiring[arm])}"],
        )
        path = run_dir / sigma_report.baseline_filename(
            arm=arm,
            goalset_version=goalset.version,
            rubric_version=rubric.version,
            captured_utc=artifact["captured_utc"],
        )
        sigma_report.write_artifact(artifact, path)
        artifacts[arm] = sigma_report.read_artifact(path)

    # DD-7: the hash-validation path is exercised on every run — a self-compare
    # must pass, and a tampered goal-set hash must raise naming the field.
    sigma_report.compare_to_baseline(artifacts[CONTROL_ARM], artifacts[CONTROL_ARM])
    tampered = dict(artifacts[CONTROL_ARM])
    tampered["goalset_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="goalset_sha256"):
        sigma_report.compare_to_baseline(artifacts[CONTROL_ARM], tampered)

    summary = sigma_report.summarize(
        rows=rows,
        trials_per_goal=trials,
        blind_map=blind_map,
        bootstrap_iterations=2_000 if MODE == STRUCTURAL else 10_000,
    )
    report = sigma_report.render_report(
        summary,
        mode=MODE,
        embeddings=os.environ.get("PROBOS_EMBEDDINGS", "") or "unset",
        judge_tier=sigma_judge.JUDGE_TIER,
        extra_notes=run_notes,
    )
    for forbidden in sigma_report.FORBIDDEN_REPORT_SUBSTRINGS:
        assert forbidden not in report.lower()
    assert "power_note=" in report
    assert f"n_pairs={summary.n_pairs}" in report
    (run_dir / "report.txt").write_text(report + "\n", encoding="utf-8")

    if os.environ.get("PROBOS_ABLATION_CAPTURE_BASELINE", "") == "1":
        control = artifacts[CONTROL_ARM]
        target = sigma_report.BASELINES_DIR / sigma_report.baseline_filename(
            arm=CONTROL_ARM,
            goalset_version=goalset.version,
            rubric_version=rubric.version,
            captured_utc=control["captured_utc"],
        )
        sigma_report.write_artifact(control, target)
        (target.with_suffix(".report.txt")).write_text(
            report + "\n", encoding="utf-8",
        )
        # The committed baseline must survive the same gate a future run does.
        sigma_report.compare_to_baseline(
            sigma_report.read_artifact(target), control,
        )

    print("\n" + report)
