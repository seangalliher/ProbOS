"""AD-1143 DD-4 — paired-design statistics for the Σ ablation.

Pure functions. No I/O, no production imports, no scipy/numpy/pandas — same
dependency posture as ``tests/benchmarks/probos_bench.py``.

Both arms run the **same goal**, so the design is paired and this module uses
it: Cohen's *d_z* over within-pair differences is materially more powerful than
two independent samples at n = 12, and it is free.

**This module never computes a p-value and never reports a hypothesis test.**
A paired design needs roughly 15 pairs to detect *d_z* = 0.8 at α = .05 with
80% power; n = 12 gives roughly 70%. The direction and rough magnitude are
reportable; statistical significance is not, and is never claimed.
"""

from __future__ import annotations

import math
import random

#: A ``(treatment, control)`` observation pair for one goal.
Pair = tuple[float, float]

FAVOURS_SIGMA = "favours_sigma"
FAVOURS_CONTROL = "favours_control"
INCONCLUSIVE = "inconclusive"

#: ASCII on purpose. This string is rendered to a terminal, and a Windows
#: console under cp1252 cannot encode an arrow — a report that cannot be
#: printed on the platform the repo is developed on is a defect.
POWER_NOTE = "n=12 -> ~70% power for d_z=0.8; directional only"


def mean(xs: list[float] | tuple[float, ...]) -> float:
    """Arithmetic mean. Raises ``ValueError`` on an empty sample."""
    values = list(xs)
    if not values:
        raise ValueError("mean_requires_at_least_one_observation")
    return math.fsum(values) / len(values)


def stdev(xs: list[float] | tuple[float, ...]) -> float:
    """Sample standard deviation (n − 1). Raises ``ValueError`` when n < 2."""
    values = list(xs)
    if len(values) < 2:
        raise ValueError("stdev_requires_at_least_two_observations")
    centre = mean(values)
    variance = math.fsum((x - centre) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def differences(pairs: list[Pair]) -> list[float]:
    """Within-pair differences, ``treatment - control``."""
    return [float(treatment) - float(control) for treatment, control in pairs]


def cohens_dz(pairs: list[Pair]) -> float:
    """Paired Cohen's *d_z*: mean within-pair difference ÷ SD of differences.

    Zero-variance boundaries are handled explicitly rather than by returning a
    number that reads as a result:

    - every difference is exactly 0 ⇒ ``0.0`` (no effect, and no dispersion to
      standardise against — the honest answer is zero, not undefined).
    - the differences are all identical and non-zero ⇒ ``ValueError``. *d_z* is
      unbounded there; emitting ``inf`` would serialise as a broken artifact
      and reporting a large finite number would be a fabrication.
    """
    if len(pairs) < 2:
        raise ValueError("cohens_dz_requires_at_least_two_pairs")
    diffs = differences(pairs)
    spread = stdev(diffs)
    centre = mean(diffs)
    if spread == 0.0:
        if centre == 0.0:
            return 0.0
        raise ValueError("cohens_dz_undefined_zero_variance")
    return centre / spread


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile of an already-sorted sample."""
    if not sorted_values:
        raise ValueError("percentile_requires_at_least_one_observation")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def bootstrap_ci(
    pairs: list[Pair],
    *,
    iterations: int = 10_000,
    seed: int = 1143,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap CI for *d_z*, resampling **pairs**.

    Pairs are the unit of resampling — resampling individual observations would
    destroy the pairing the design depends on. The seed is fixed so the
    interval is byte-reproducible across calls and across machines.

    Degenerate resamples (every drawn pair identical, so the difference SD is
    zero and *d_z* is undefined) are **skipped**, not coerced to a number. With
    real data these are vanishingly rare; with a tiny or synthetic sample they
    are not, and the exclusion is stated here rather than hidden. If every
    resample is degenerate the CI cannot be formed and ``ValueError`` is
    raised.
    """
    if len(pairs) < 2:
        raise ValueError("bootstrap_ci_requires_at_least_two_pairs")
    if iterations < 1:
        raise ValueError("bootstrap_ci_requires_positive_iterations")
    if not 0.0 < alpha < 1.0:
        raise ValueError("bootstrap_ci_alpha_out_of_range")

    rng = random.Random(seed)
    size = len(pairs)
    estimates: list[float] = []
    for _ in range(iterations):
        resample = [pairs[rng.randrange(size)] for _ in range(size)]
        try:
            estimates.append(cohens_dz(resample))
        except ValueError:
            continue
    if not estimates:
        raise ValueError("bootstrap_ci_all_resamples_degenerate")
    estimates.sort()
    return (
        _percentile(estimates, alpha / 2.0),
        _percentile(estimates, 1.0 - alpha / 2.0),
    )


def spans_zero(ci: tuple[float, float]) -> bool:
    """Whether the interval includes 0 (inclusive at both ends)."""
    low, high = ci
    return low <= 0.0 <= high


def interpret(
    d: float,
    ci: tuple[float, float],
    *,
    variance_dominates: bool = False,
) -> str:
    """Direction of the effect — never a significance verdict.

    Returns ``inconclusive`` whenever the CI spans 0, and unconditionally when
    ``variance_dominates`` is set (DD-5: a run whose between-trial noise meets
    or exceeds its between-arm delta is not readable as a result, however large
    *d_z* happens to be).
    """
    if variance_dominates:
        return INCONCLUSIVE
    if spans_zero(ci):
        return INCONCLUSIVE
    return FAVOURS_SIGMA if d > 0.0 else FAVOURS_CONTROL


def pooled_sd(groups: list[list[float]]) -> float:
    """Pooled within-group SD across ``groups``, ignoring groups with n < 2.

    Used for DD-5's ``between_trial_sd``: each group is the trial scores of one
    ``(goal, arm)`` cell, so the result is the trial-to-trial noise with the
    goal and arm effects removed. Returns ``0.0`` when no group has enough
    observations to have a spread (one trial per cell is a valid, if noisy,
    configuration and must not raise).
    """
    total_ss = 0.0
    total_df = 0
    for group in groups:
        if len(group) < 2:
            continue
        centre = mean(group)
        total_ss += math.fsum((x - centre) ** 2 for x in group)
        total_df += len(group) - 1
    if total_df == 0:
        return 0.0
    return math.sqrt(total_ss / total_df)


def variance_dominates(between_trial_sd: float, between_arm_delta: float) -> bool:
    """DD-5 veto: trial noise at or above the arm delta invalidates the run."""
    return float(between_trial_sd) >= float(between_arm_delta)
