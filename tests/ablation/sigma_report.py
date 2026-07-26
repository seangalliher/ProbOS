"""AD-1143 DD-5/DD-7 — run provenance, the results artifact, and the report.

This harness produces a directional signal, not a publishable effect size. The
shipped goal set is 12 items, not the ≥100 that Nooplex §8.5 asks for, because
each item costs a full live crew run. Cohen's d and its confidence interval are
reported so the direction and rough magnitude of the Σ effect are visible; the
harness never claims statistical significance and never prints the word
"significant". §8.5 compliance is not claimed.

Three things live here:

- **Config pinning and the fingerprint.** Every ``agentic_loop`` field the
  recent ADs added is pinned explicitly rather than inherited, and the pinned
  set is hashed into the artifact. An unrelated default change then surfaces as
  a fingerprint mismatch at comparison time instead of silently moving the
  numbers.
- **The artifact.** Content-hashed against its goal set, rubric and pinned
  config. ``compare_to_baseline`` **raises** on any of those three diverging —
  a quietly-invalid comparison is worse than no comparison. A differing commit
  or judge model is recorded and surfaced, not fatal: comparing across commits
  is the entire point.
- **The report.** Reports direction, *d_z*, a bootstrap interval and the per-arm
  means. It performs no hypothesis test, prints no p-value, and refuses to
  render if one ever leaks in. The paragraph above is the artifact's
  ``disclaimer`` field verbatim; the report carries ``REPORT_DISCLAIMER``, an
  equivalent restatement that avoids the substrings a report must never
  contain.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probos.config import SystemConfig

from tests.ablation import sigma_stats
from tests.ablation.sigma_flags import CONTROL_ARM, TREATMENT_ARM

BASELINES_DIR = Path(__file__).resolve().parent / "baselines"

#: The disclaimer, verbatim, for the artifact and the DECISIONS.md entry. It is
#: the second paragraph of this module's docstring, byte for byte — a test
#: asserts that, so the two cannot drift. It quotes the forbidden word and
#: therefore never appears in a rendered report; ``REPORT_DISCLAIMER`` is the
#: report-safe restatement.
DISCLAIMER = (
    "This harness produces a directional signal, not a publishable effect "
    "size. The\nshipped goal set is 12 items, not the \u2265100 that Nooplex "
    "\u00a78.5 asks for, because\neach item costs a full live crew run. "
    "Cohen's d and its confidence interval are\nreported so the direction and "
    "rough magnitude of the \u03a3 effect are visible; the\nharness never "
    "claims statistical significance and never prints the word\n"
    "\"significant\". \u00a78.5 compliance is not claimed."
)

REPORT_DISCLAIMER = (
    "Directional signal, not a publishable effect size. The goal set is 12 "
    "items, not the >=100 Nooplex 8.5 asks for, because each item costs a "
    "full live crew run. Cohen's d_z and its interval show direction and "
    "rough magnitude only. No hypothesis test is performed and no statistical "
    "claim is made. Nooplex 8.5 compliance is NOT claimed."
)

#: Judge and system under test share a model family; this is stated on every run.
JUDGE_FAMILY_CAVEAT = (
    "Judge and system under test share a model family. A human-evaluation "
    "panel (Nooplex 8.4) is out of scope for this AD. Blinding, a fixed "
    "temperature and per-row judge model/tier recording are the affordable "
    "mitigations."
)

#: Local embeddings bias the run *against* the treatment arm; say so explicitly
#: so a reader cannot infer the opposite.
LOCAL_EMBEDDINGS_CAVEAT = (
    "PROBOS_EMBEDDINGS=local makes the embedding function lexical, not "
    "semantic, so AD-1138's index is measurably weaker here than it would be "
    "with real embeddings. That biases the run against the treatment arm: a "
    "positive result under local embeddings is a floor, not a ceiling."
)

#: ASCII on purpose — see the note on ``sigma_stats.POWER_NOTE``.
VARIANCE_DOMINATES_BANNER = "VARIANCE_DOMINATES - this run is not interpretable"

#: Substrings a report must never contain. n = 12 is roughly 70% powered; the
#: result is directional only and must not read as a hypothesis test.
FORBIDDEN_REPORT_SUBSTRINGS: tuple[str, ...] = (
    "significant",
    "p=",
    "p <",
    "p-value",
)

#: DD-5 pinning. Every ``agentic_loop`` field AD-1146/1147/1148/1151 added is
#: pinned explicitly — defaults are not inherited.
PINNED_AGENTIC_LOOP: dict[str, Any] = {
    "agentic_loop.structured_tool_messages": False,
    "agentic_loop.tool_result_max_chars": 0,
    "agentic_loop.tool_result_head_chars": 4000,
    "agentic_loop.tool_result_tail_chars": 2000,
    "agentic_loop.parallel_tool_calls_enabled": False,
    "agentic_loop.max_parallel_tool_calls": 3,
    "agentic_loop.tool_trace_output_max_chars": 8192,
    "agentic_loop.tool_trace_max_bytes": 262144,
}

#: Every key DD-7 requires in a results artifact.
ARTIFACT_KEYS: frozenset[str] = frozenset({
    "arm",
    "probos_commit",
    "captured_utc",
    "goalset_version",
    "goalset_sha256",
    "rubric_version",
    "rubric_sha256",
    "config_fingerprint",
    "flags",
    "judge",
    "embeddings",
    "trials_per_goal",
    "results",
    "aggregate",
    "disclaimer",
})

#: Fields whose divergence makes a comparison invalid.
GATED_COMPARISON_FIELDS: tuple[str, ...] = (
    "goalset_sha256",
    "rubric_sha256",
    "config_fingerprint",
)


def config_fingerprint(pinned: dict[str, Any]) -> str:
    """SHA-256 over the pinned config values, key-sorted for stability."""
    return hashlib.sha256(
        json.dumps(pinned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def apply_pinned_config(config: SystemConfig) -> SystemConfig:
    """Return a new config with every DD-5 pinned field set explicitly."""
    from tests.ablation.sigma_flags import set_paths

    return set_paths(config, PINNED_AGENTIC_LOOP)


def git_commit(repo_root: Path | None = None) -> str:
    """``git rev-parse HEAD``, or ``"unknown"`` when it cannot be read.

    A missing commit is recorded honestly rather than raising: the commit is
    provenance metadata, and a comparison across differing commits is allowed
    by design.
    """
    root = repo_root or Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def utc_now_iso() -> str:
    """Current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ResultRow:
    """One judged trial.

    ``scores`` and ``composite`` are ``None`` exactly when ``judge_failed`` is
    ``True``. A failed judge call is never recorded as ``0.0`` — a zero is
    indistinguishable from a genuinely terrible artifact and would bias
    whichever arm's call failed.
    """

    goal_id: str
    arm: str
    trial: int
    judge_failed: bool
    judge_model: str
    judge_tier: str
    blind_position: int
    scores: dict[str, float] | None = None
    composite: float | None = None
    failure_reason: str | None = None
    artifact_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "arm": self.arm,
            "trial": self.trial,
            "scores": dict(self.scores) if self.scores is not None else None,
            "composite": self.composite,
            "judge_model": self.judge_model,
            "judge_tier": self.judge_tier,
            "judge_failed": self.judge_failed,
            "blind_position": self.blind_position,
            "failure_reason": self.failure_reason,
            "artifact_truncated": self.artifact_truncated,
        }


def usable(rows: list[ResultRow]) -> list[ResultRow]:
    """Rows that carry a real score."""
    return [row for row in rows if not row.judge_failed and row.composite is not None]


def trial_groups(rows: list[ResultRow]) -> list[list[float]]:
    """Composite scores grouped by ``(goal_id, arm)`` cell."""
    cells: dict[tuple[str, str], list[float]] = {}
    for row in usable(rows):
        cells.setdefault((row.goal_id, row.arm), []).append(float(row.composite or 0.0))
    return [cells[key] for key in sorted(cells)]


def goal_means(rows: list[ResultRow], arm: str) -> dict[str, float]:
    """Per-goal mean composite for one arm, over its non-failed trials."""
    cells: dict[str, list[float]] = {}
    for row in usable(rows):
        if row.arm == arm:
            cells.setdefault(row.goal_id, []).append(float(row.composite or 0.0))
    return {
        goal_id: sigma_stats.mean(values)
        for goal_id, values in sorted(cells.items())
    }


def aggregate_rows(rows: list[ResultRow]) -> dict[str, Any]:
    """DD-7 ``aggregate`` block for one arm's rows."""
    scored = usable(rows)
    composites = [float(row.composite or 0.0) for row in scored]
    groups = trial_groups(rows)
    aggregate = {
        "mean_composite": sigma_stats.mean(composites) if composites else None,
        "between_trial_sd": sigma_stats.pooled_sd(groups),
        "between_trial_sd_measured": any(len(g) >= 2 for g in groups),
        "n_goals": len({row.goal_id for row in rows}),
        "n_trials": len(rows),
        "n_judge_failures": sum(1 for row in rows if row.judge_failed),
    }
    return aggregate


def build_artifact(
    *,
    arm: str,
    rows: list[ResultRow],
    goalset_version: str,
    goalset_sha256: str,
    rubric_version: str,
    rubric_sha256: str,
    flags: dict[str, Any],
    judge_model: str,
    judge_tier: str,
    judge_temperature: float,
    trials_per_goal: int,
    mode: str,
    embeddings: str = "local",
    probos_commit: str | None = None,
    captured_utc: str | None = None,
    notes: list[str] | None = None,
    pinned: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a DD-7 results artifact for one arm."""
    pinned_values = dict(pinned if pinned is not None else PINNED_AGENTIC_LOOP)
    return {
        "ad": "AD-1143",
        "mode": mode,
        "arm": arm,
        "probos_commit": probos_commit if probos_commit is not None else git_commit(),
        "captured_utc": captured_utc or utc_now_iso(),
        "goalset_version": goalset_version,
        "goalset_sha256": goalset_sha256,
        "rubric_version": rubric_version,
        "rubric_sha256": rubric_sha256,
        "config_fingerprint": config_fingerprint(pinned_values),
        "pinned_config": pinned_values,
        "flags": dict(flags),
        "judge": {
            "model": judge_model,
            "tier": judge_tier,
            "temperature": judge_temperature,
        },
        "embeddings": embeddings,
        "trials_per_goal": trials_per_goal,
        "results": [row.to_dict() for row in rows],
        "aggregate": aggregate_rows(rows),
        "notes": list(notes or []),
        "disclaimer": DISCLAIMER,
    }


def baseline_filename(
    *,
    arm: str,
    goalset_version: str,
    rubric_version: str,
    captured_utc: str,
) -> str:
    """DD-7 baseline filename: ``<arm>_<goalset>_<rubric>_<YYYYMMDD>.json``."""
    day = captured_utc[:10].replace("-", "")
    return f"{arm}_{goalset_version}_{rubric_version}_{day}.json"


@dataclass(frozen=True)
class ComparisonReport:
    """Non-fatal differences between a baseline and a current artifact."""

    commit_changed: bool
    baseline_commit: str
    current_commit: str
    judge_model_changed: bool
    baseline_judge_model: str
    current_judge_model: str

    @property
    def differences(self) -> tuple[str, ...]:
        found: list[str] = []
        if self.commit_changed:
            found.append(
                f"probos_commit changed: {self.baseline_commit} -> "
                f"{self.current_commit}"
            )
        if self.judge_model_changed:
            found.append(
                f"judge.model changed: {self.baseline_judge_model} -> "
                f"{self.current_judge_model}"
            )
        return tuple(found)


def compare_to_baseline(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> ComparisonReport:
    """Gate a comparison, or raise ``ValueError`` naming the diverging field.

    ``goalset_sha256``, ``rubric_sha256`` and ``config_fingerprint`` must match
    exactly. Never compare across a changed goal set, rubric or pinned config,
    and never degrade to a warning: a quietly-invalid comparison is worse than
    no comparison.

    ``probos_commit`` and ``judge.model`` differences are recorded and surfaced,
    not fatal — comparing across commits is the whole point.
    """
    for field_name in GATED_COMPARISON_FIELDS:
        baseline_value = baseline.get(field_name)
        current_value = current.get(field_name)
        if baseline_value != current_value:
            raise ValueError(
                f"cannot compare to baseline: {field_name} differs "
                f"({baseline_value!r} != {current_value!r}); a changed goal "
                f"set, rubric or pinned config invalidates the comparison"
            )
    baseline_judge = baseline.get("judge") or {}
    current_judge = current.get("judge") or {}
    baseline_model = str(baseline_judge.get("model", ""))
    current_model = str(current_judge.get("model", ""))
    baseline_commit = str(baseline.get("probos_commit", ""))
    current_commit = str(current.get("probos_commit", ""))
    return ComparisonReport(
        commit_changed=baseline_commit != current_commit,
        baseline_commit=baseline_commit,
        current_commit=current_commit,
        judge_model_changed=baseline_model != current_model,
        baseline_judge_model=baseline_model,
        current_judge_model=current_model,
    )


@dataclass(frozen=True)
class RunSummary:
    """Paired-design summary across both arms."""

    n_pairs: int
    d_z: float | None
    ci: tuple[float, float] | None
    direction: str
    mean_treatment: float | None
    mean_control: float | None
    between_arm_delta: float
    between_trial_sd: float
    between_trial_sd_measured: bool
    variance_dominates: bool
    n_goals: int
    n_judge_failures: int
    trials_per_goal: int
    paired_goal_ids: tuple[str, ...] = ()
    unpaired_goal_ids: tuple[str, ...] = ()
    stats_note: str | None = None
    blind_map: dict[str, tuple[str, ...]] = field(default_factory=dict)


def summarize(
    *,
    rows: list[ResultRow],
    trials_per_goal: int,
    blind_map: dict[str, tuple[str, ...]] | None = None,
    bootstrap_iterations: int = 10_000,
) -> RunSummary:
    """Fold both arms' rows into a paired summary with the DD-5 veto applied."""
    treatment_means = goal_means(rows, TREATMENT_ARM)
    control_means = goal_means(rows, CONTROL_ARM)
    all_goal_ids = sorted({row.goal_id for row in rows})
    paired_ids = tuple(
        goal_id
        for goal_id in all_goal_ids
        if goal_id in treatment_means and goal_id in control_means
    )
    unpaired_ids = tuple(
        goal_id for goal_id in all_goal_ids if goal_id not in paired_ids
    )
    pairs: list[tuple[float, float]] = [
        (treatment_means[goal_id], control_means[goal_id]) for goal_id in paired_ids
    ]

    mean_treatment = (
        sigma_stats.mean([treatment_means[g] for g in paired_ids]) if pairs else None
    )
    mean_control = (
        sigma_stats.mean([control_means[g] for g in paired_ids]) if pairs else None
    )
    delta = (
        abs(mean_treatment - mean_control)
        if mean_treatment is not None and mean_control is not None
        else 0.0
    )
    trial_sd = sigma_stats.pooled_sd(trial_groups(rows))
    trial_sd_measured = any(len(group) >= 2 for group in trial_groups(rows))
    veto = sigma_stats.variance_dominates(trial_sd, delta)

    d_z: float | None = None
    ci: tuple[float, float] | None = None
    stats_note: str | None = None
    if len(pairs) < 2:
        stats_note = (
            f"fewer than two usable pairs ({len(pairs)}); no effect size or "
            f"interval can be formed"
        )
    else:
        try:
            d_z = sigma_stats.cohens_dz(pairs)
            ci = sigma_stats.bootstrap_ci(pairs, iterations=bootstrap_iterations)
        except ValueError as exc:
            d_z = None
            ci = None
            stats_note = (
                f"effect size undefined ({exc}); every within-pair difference "
                f"was identical, so there is no dispersion to standardise "
                f"against"
            )
        else:
            if len(pairs) < 4:
                stats_note = (
                    f"only {len(pairs)} usable pairs; a resampled interval at "
                    f"this n is degenerate and carries no information about "
                    f"the uncertainty of the effect"
                )

    if d_z is None or ci is None:
        direction = sigma_stats.INCONCLUSIVE
    else:
        direction = sigma_stats.interpret(d_z, ci, variance_dominates=veto)

    return RunSummary(
        n_pairs=len(pairs),
        d_z=d_z,
        ci=ci,
        direction=direction,
        mean_treatment=mean_treatment,
        mean_control=mean_control,
        between_arm_delta=delta,
        between_trial_sd=trial_sd,
        between_trial_sd_measured=trial_sd_measured,
        variance_dominates=veto,
        n_goals=len(all_goal_ids),
        n_judge_failures=sum(1 for row in rows if row.judge_failed),
        trials_per_goal=trials_per_goal,
        paired_goal_ids=paired_ids,
        unpaired_goal_ids=unpaired_ids,
        stats_note=stats_note,
        blind_map=dict(blind_map or {}),
    )


def _fmt(value: float | None, digits: int = 3) -> str:
    return "undefined" if value is None else f"{value:.{digits}f}"


def render_report(
    summary: RunSummary,
    *,
    mode: str,
    embeddings: str = "local",
    judge_tier: str = "deep",
    comparison: ComparisonReport | None = None,
    extra_notes: list[str] | None = None,
) -> str:
    """Render the run report.

    The first line is the DD-5 ``VARIANCE_DOMINATES`` banner when trial noise
    meets or exceeds the arm delta. The report performs no hypothesis test and
    the renderer refuses to emit one — see ``FORBIDDEN_REPORT_SUBSTRINGS``.
    """
    lines: list[str] = []
    if summary.variance_dominates:
        lines.append(VARIANCE_DOMINATES_BANNER)
    lines.append("AD-1143 Nooplex 8.3 shared-knowledge ablation")
    lines.append(
        f"direction={summary.direction} "
        f"d_z={_fmt(summary.d_z, 2)} "
        f"ci95=[{_fmt(summary.ci[0], 2) if summary.ci else 'undefined'}, "
        f"{_fmt(summary.ci[1], 2) if summary.ci else 'undefined'}] "
        f"n_pairs={summary.n_pairs} "
        f'power_note="{sigma_stats.POWER_NOTE}"'
    )
    lines.append(
        f"mean[{TREATMENT_ARM}]={_fmt(summary.mean_treatment)} "
        f"mean[{CONTROL_ARM}]={_fmt(summary.mean_control)} "
        f"between_arm_delta={_fmt(summary.between_arm_delta)} "
        f"between_trial_sd="
        + (
            _fmt(summary.between_trial_sd)
            if summary.between_trial_sd_measured
            else "unmeasured"
        )
    )
    lines.append(
        f"mode={mode} embeddings={embeddings} judge_tier={judge_tier} "
        f"goals={summary.n_goals} trials_per_goal={summary.trials_per_goal} "
        f"judge_failures={summary.n_judge_failures}"
    )
    if summary.unpaired_goal_ids:
        lines.append(
            "unpaired goals (excluded from the effect size): "
            + ", ".join(summary.unpaired_goal_ids)
        )
    if not summary.between_trial_sd_measured:
        lines.append(
            "note: trial-to-trial noise was NOT measured - no goal/arm cell "
            "had two or more usable trials. It is unknown, not zero, and the "
            "variance veto could not be evaluated against a real estimate."
        )
    if summary.stats_note:
        lines.append(f"note: {summary.stats_note}")
    if summary.variance_dominates:
        lines.append(
            "note: between-trial noise meets or exceeds the between-arm "
            "delta, so the direction is forced to inconclusive regardless of "
            "the effect size."
        )
    if summary.blind_map:
        lines.append("blind presentation order (arm -> slot):")
        for goal_id in sorted(summary.blind_map):
            order = summary.blind_map[goal_id]
            mapping = ", ".join(
                f"{arm}@{index + 1}" for index, arm in enumerate(order)
            )
            lines.append(f"  {goal_id}: {mapping}")
    if comparison is not None:
        differences = comparison.differences
        lines.append("baseline comparison:")
        if differences:
            lines.extend(f"  {difference}" for difference in differences)
        else:
            lines.append("  no commit or judge-model difference")
    lines.append(f"caveat: {JUDGE_FAMILY_CAVEAT}")
    if embeddings == "local":
        lines.append(f"caveat: {LOCAL_EMBEDDINGS_CAVEAT}")
    for note in extra_notes or []:
        lines.append(f"note: {note}")
    lines.append(REPORT_DISCLAIMER)

    report = "\n".join(lines)
    leaked = [
        term for term in FORBIDDEN_REPORT_SUBSTRINGS if term in report.lower()
    ]
    if leaked:
        raise ValueError(
            f"report would imply a statistical claim it cannot support; it "
            f"contains {leaked}. n=12 is roughly 70% powered and the result is "
            f"directional only."
        )
    if not report.isascii():
        raise ValueError(
            "report contains non-ASCII characters; it is printed to a console "
            "that may be cp1252 and would fail to render"
        )
    return report


def write_artifact(artifact: dict[str, Any], path: Path) -> Path:
    """Write ``artifact`` as pretty JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_artifact(path: Path) -> dict[str, Any]:
    """Read an artifact and verify it carries every DD-7 key."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = ARTIFACT_KEYS - set(payload)
    if missing:
        raise ValueError(
            f"artifact {path.name} is missing required key(s): {sorted(missing)}"
        )
    return payload
