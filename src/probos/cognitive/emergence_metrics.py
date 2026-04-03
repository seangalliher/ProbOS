"""Emergence Metrics — Information-Theoretic Collaborative Intelligence Measurement (AD-557).

Implements Partial Information Decomposition (PID) from Riedl (2025,
arXiv:2510.05174v3) to quantify collaborative emergence in Ward Room
conversations.  Pure Python — no numpy/scipy dependency.

Three key metrics:
  - **emergence_capacity**: Median pairwise synergy across agent pairs
  - **coordination_balance**: Synergy × Redundancy interaction (Riedl's predictor)
  - **tom_effectiveness**: Complementarity trend slope over time
"""

from __future__ import annotations

import logging
import math
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from probos.config import EmergenceMetricsConfig
from probos.knowledge.embeddings import embed_text, compute_similarity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PIDResult:
    """Partial Information Decomposition result for an agent pair."""

    agent_i: str
    agent_j: str
    unique_i: float  # Information unique to agent i
    unique_j: float  # Information unique to agent j
    redundancy: float  # Shared/overlapping information
    synergy: float  # Information only available from combination
    total_mi: float  # Total mutual information
    n_contributions: int  # Number of contributions analyzed
    p_value: float  # Significance via permutation test
    is_significant: bool  # p_value < threshold


@dataclass
class EmergenceSnapshot:
    """Ship-level emergence metrics at a point in time."""

    timestamp: float = 0.0
    emergence_capacity: float = 0.0  # Median pairwise synergy
    coordination_balance: float = 0.0  # Synergy × Redundancy interaction
    redundancy_ratio: float = 0.0  # Mean redundancy / (redundancy + synergy)
    synergy_ratio: float = 0.0  # Mean synergy / (redundancy + synergy)
    threads_analyzed: int = 0
    pairs_analyzed: int = 0
    significant_pairs: int = 0
    top_synergy_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    per_department: dict[str, dict[str, float]] = field(default_factory=dict)
    groupthink_risk: bool = False
    fragmentation_risk: bool = False
    tom_effectiveness: float | None = None
    hebbian_synergy_correlation: float | None = None
    provenance_independence: float | None = None  # Reserved for AD-559

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Pure-Python math utilities
# ---------------------------------------------------------------------------

def _safe_log2(x: float) -> float:
    """log2 with protection against log(0)."""
    return math.log2(max(x, 1e-10))


def _mutual_information_binary(joint: list[list[float]]) -> float:
    """Compute MI(X; Y) from a 2×2 joint probability table.

    joint[x][y] = P(X=x, Y=y).  Rows = X states, Cols = Y states.
    """
    mi = 0.0
    # Marginals
    p_x = [sum(joint[x]) for x in range(2)]
    p_y = [sum(joint[x][y] for x in range(2)) for y in range(2)]

    for x in range(2):
        for y in range(2):
            pxy = joint[x][y]
            if pxy > 1e-10 and p_x[x] > 1e-10 and p_y[y] > 1e-10:
                mi += pxy * _safe_log2(pxy / (p_x[x] * p_y[y]))
    return max(mi, 0.0)


def _joint_mi_binary(joint_3d: list[list[list[float]]]) -> float:
    """Compute MI(X_i, X_j; Y) from a 2×2×2 joint probability table.

    joint_3d[xi][xj][y] = P(X_i=xi, X_j=xj, Y=y).
    """
    mi = 0.0
    # Marginal P(xi, xj)
    p_xixj = [[sum(joint_3d[xi][xj]) for xj in range(2)] for xi in range(2)]
    # Marginal P(y)
    p_y = [0.0, 0.0]
    for xi in range(2):
        for xj in range(2):
            for y in range(2):
                p_y[y] += joint_3d[xi][xj][y]

    for xi in range(2):
        for xj in range(2):
            for y in range(2):
                p = joint_3d[xi][xj][y]
                if p > 1e-10 and p_xixj[xi][xj] > 1e-10 and p_y[y] > 1e-10:
                    mi += p * _safe_log2(p / (p_xixj[xi][xj] * p_y[y]))
    return max(mi, 0.0)


def _specific_information(
    joint: list[list[float]], y_val: int,
) -> float:
    """Compute I_spec(X; Y=y) = Σ_x P(x|y) * log2(P(x|y) / P(x)).

    joint[x][y] = P(X=x, Y=y).
    """
    p_y = sum(joint[x][y_val] for x in range(2))
    if p_y < 1e-10:
        return 0.0
    p_x = [sum(joint[x]) for x in range(2)]

    i_spec = 0.0
    for x in range(2):
        p_x_given_y = joint[x][y_val] / p_y
        if p_x_given_y > 1e-10 and p_x[x] > 1e-10:
            i_spec += p_x_given_y * _safe_log2(p_x_given_y / p_x[x])
    return max(i_spec, 0.0)


def _williams_beer_imin(
    joint_xi_y: list[list[float]],
    joint_xj_y: list[list[float]],
) -> float:
    """Compute I_min (Williams-Beer redundancy).

    I_min(Y; X_i, X_j) = Σ_y min(I_spec(X_i; Y=y), I_spec(X_j; Y=y))
    """
    imin = 0.0
    for y in range(2):
        spec_i = _specific_information(joint_xi_y, y)
        spec_j = _specific_information(joint_xj_y, y)
        imin += min(spec_i, spec_j)
    return imin


def _quantile_bin(values: list[float], k: int = 2) -> list[int]:
    """Quantile-bin continuous values into k discrete bins.

    For k=2: below median → 0, above median → 1.
    """
    if not values:
        return []
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    thresholds = [sorted_vals[int(n * (i + 1) / k) - 1] for i in range(k - 1)]

    result = []
    for v in values:
        b = 0
        for t in thresholds:
            if v > t:
                b += 1
        result.append(min(b, k - 1))
    return result


def compute_pid(
    sims_i: list[float],
    sims_j: list[float],
    k: int = 2,
) -> tuple[float, float, float, float, float]:
    """Compute PID decomposition from similarity-to-outcome vectors.

    Args:
        sims_i: Agent i's contribution similarities to outcome.
        sims_j: Agent j's contribution similarities to outcome.
        k: Number of quantile bins (default 2 for binary).

    Returns:
        (unique_i, unique_j, redundancy, synergy, total_mi)
    """
    n = len(sims_i)
    if n < 2 or len(sims_j) != n:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    # Discretize into bins
    xi_bins = _quantile_bin(sims_i, k)
    xj_bins = _quantile_bin(sims_j, k)

    # Outcome variable: combined similarity (mean of both agents)
    combined = [(a + b) / 2.0 for a, b in zip(sims_i, sims_j)]
    y_bins = _quantile_bin(combined, k)

    # Build joint probability tables (frequency-based)
    # For k=2, we use 2×2 tables
    joint_xi_y = [[0.0] * 2 for _ in range(2)]
    joint_xj_y = [[0.0] * 2 for _ in range(2)]
    joint_3d = [[[0.0] * 2 for _ in range(2)] for _ in range(2)]

    for idx in range(n):
        xi = min(xi_bins[idx], 1)
        xj = min(xj_bins[idx], 1)
        y = min(y_bins[idx], 1)
        joint_xi_y[xi][y] += 1.0
        joint_xj_y[xj][y] += 1.0
        joint_3d[xi][xj][y] += 1.0

    # Normalize to probabilities
    for x in range(2):
        for y in range(2):
            joint_xi_y[x][y] /= n
            joint_xj_y[x][y] /= n
    for xi in range(2):
        for xj in range(2):
            for y in range(2):
                joint_3d[xi][xj][y] /= n

    # Compute components
    mi_xi_y = _mutual_information_binary(joint_xi_y)
    mi_xj_y = _mutual_information_binary(joint_xj_y)
    mi_joint = _joint_mi_binary(joint_3d)
    i_min = _williams_beer_imin(joint_xi_y, joint_xj_y)

    redundancy = i_min
    unique_i = max(mi_xi_y - i_min, 0.0)
    unique_j = max(mi_xj_y - i_min, 0.0)
    synergy = max(mi_joint - mi_xi_y - mi_xj_y + i_min, 0.0)
    total_mi = mi_joint

    return unique_i, unique_j, redundancy, synergy, total_mi


def _permutation_test(
    sims_i: list[float],
    sims_j: list[float],
    observed_synergy: float,
    n_shuffles: int = 50,
    k: int = 2,
) -> float:
    """Permutation significance test for synergy.

    Shuffles agent labels B times and computes synergy.
    Returns p-value = fraction of shuffled synergies >= observed.
    """
    if n_shuffles < 1 or observed_synergy <= 0.0:
        return 1.0

    count_ge = 0
    combined = sims_i + sims_j
    n = len(sims_i)

    rng = random.Random(42)  # Deterministic for reproducibility
    for _ in range(n_shuffles):
        rng.shuffle(combined)
        shuffled_i = combined[:n]
        shuffled_j = combined[n:]
        _, _, _, shuffled_synergy, _ = compute_pid(shuffled_i, shuffled_j, k)
        if shuffled_synergy >= observed_synergy:
            count_ge += 1

    return count_ge / n_shuffles


def compute_complementarity(posts: list[dict[str, Any]]) -> float:
    """Semantic dissimilarity between consecutive contributions by different agents.

    Higher = more complementary (agents adding new information).
    Lower = more redundant (agents echoing each other).

    Args:
        posts: List of dicts with at least 'author_id' and 'body' keys.
    """
    if len(posts) < 2:
        return 0.0

    scores: list[float] = []
    for i in range(1, len(posts)):
        if posts[i]["author_id"] != posts[i - 1]["author_id"]:
            sim = compute_similarity(posts[i - 1]["body"], posts[i]["body"])
            scores.append(1.0 - sim)

    return sum(scores) / len(scores) if scores else 0.0


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Simple linear regression. Returns (slope, intercept, r_squared).

    Pure Python — copied from EmergentDetector._linear_regression().
    """
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0

    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)

    denom = n * sum_x2 - sum_x * sum_x
    if abs(denom) < 1e-15:
        return 0.0, sum_y / n if n else 0.0, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    y_mean = sum_y / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))

    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-15 else 0.0
    r_squared = max(0.0, min(1.0, r_squared))

    return slope, intercept, r_squared


def _pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation coefficient. Returns None if insufficient data."""
    n = len(xs)
    if n < 3 or len(ys) != n:
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))

    if std_x < 1e-10 or std_y < 1e-10:
        return None
    return cov / (std_x * std_y)


# ---------------------------------------------------------------------------
# Emergence Metrics Engine
# ---------------------------------------------------------------------------

class EmergenceMetricsEngine:
    """Computes information-theoretic emergence metrics from Ward Room conversations."""

    def __init__(self, config: EmergenceMetricsConfig | None = None) -> None:
        self._config = config or EmergenceMetricsConfig()
        self._snapshots: deque[EmergenceSnapshot] = deque(maxlen=100)
        self._complementarity_history: list[tuple[float, float]] = []
        self._baseline_established: bool = False
        self._baseline_complementarity: float | None = None

    @property
    def latest_snapshot(self) -> EmergenceSnapshot | None:
        """Return the most recent snapshot, or None."""
        return self._snapshots[-1] if self._snapshots else None

    @property
    def snapshots(self) -> list[EmergenceSnapshot]:
        """Return snapshot history."""
        return list(self._snapshots)

    async def compute_emergence_metrics(
        self,
        ward_room: Any,
        trust_network: Any,
        hebbian_router: Any = None,
        get_department: Callable[[str], str | None] | None = None,
    ) -> EmergenceSnapshot:
        """Full emergence metrics computation. Called during dream Step 9."""
        cfg = self._config
        now = time.time()

        # 1. Retrieve recent threads
        since = now - (cfg.thread_lookback_hours * 3600)
        threads = await ward_room.browse_threads(
            agent_id="",
            channels=None,
            limit=50,
            since=since,
        )

        # 2. Collect posts for qualifying threads
        thread_posts: list[list[dict[str, Any]]] = []
        embedding_cache: dict[str, list[float]] = {}

        for thread in threads:
            thread_data = await ward_room.get_thread(thread.id if hasattr(thread, "id") else thread.get("id", ""))
            if thread_data is None:
                continue

            posts_raw = thread_data.get("posts", []) if isinstance(thread_data, dict) else getattr(thread_data, "posts", [])
            posts: list[dict[str, Any]] = []
            for p in posts_raw:
                if isinstance(p, dict):
                    posts.append(p)
                else:
                    posts.append({
                        "id": getattr(p, "id", ""),
                        "author_id": getattr(p, "author_id", ""),
                        "body": getattr(p, "body", ""),
                        "created_at": getattr(p, "created_at", 0.0),
                    })

            unique_authors = set(p["author_id"] for p in posts if p.get("author_id"))
            if len(unique_authors) < cfg.min_thread_contributors:
                continue
            if len(posts) < cfg.min_thread_posts:
                continue

            thread_posts.append(posts)

        threads_analyzed = len(thread_posts)

        # 3. Compute pairwise PID
        # Group contributions by agent pair across all threads
        pair_data: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        all_complementarity_scores: list[float] = []

        for posts in thread_posts:
            # Complementarity for ToM tracking
            comp_score = compute_complementarity(posts)
            all_complementarity_scores.append(comp_score)

            # Build outcome embedding (concatenated thread body)
            thread_body = " ".join(p["body"] for p in posts if p.get("body"))
            if not thread_body:
                continue

            outcome_key = f"__outcome__{id(posts)}"
            if outcome_key not in embedding_cache:
                embedding_cache[outcome_key] = embed_text(thread_body[:2000])
            outcome_emb = embedding_cache[outcome_key]

            # Per-agent contribution embeddings
            agent_contribs: dict[str, list[float]] = defaultdict(list)
            for p in posts:
                aid = p.get("author_id", "")
                body = p.get("body", "")
                if not aid or not body:
                    continue
                pid = p.get("id", "")
                cache_key = pid or body[:100]
                if cache_key not in embedding_cache:
                    embedding_cache[cache_key] = embed_text(body[:1000])
                post_emb = embedding_cache[cache_key]
                sim = _cosine_sim(post_emb, outcome_emb)
                agent_contribs[aid].append(sim)

            # Build pairs
            agents = sorted(agent_contribs.keys())
            for i_idx in range(len(agents)):
                for j_idx in range(i_idx + 1, len(agents)):
                    ai, aj = agents[i_idx], agents[j_idx]
                    # Pool mean similarity per agent in this thread
                    mean_i = sum(agent_contribs[ai]) / len(agent_contribs[ai])
                    mean_j = sum(agent_contribs[aj]) / len(agent_contribs[aj])
                    pair_data[(ai, aj)].append((mean_i, mean_j))

        # Compute PID for each pair
        pid_results: list[PIDResult] = []
        for (ai, aj), contributions in pair_data.items():
            if len(contributions) < 2:
                continue
            sims_i = [c[0] for c in contributions]
            sims_j = [c[1] for c in contributions]

            unique_i, unique_j, redundancy, synergy, total_mi = compute_pid(
                sims_i, sims_j, cfg.pid_bins,
            )

            p_value = _permutation_test(
                sims_i, sims_j, synergy, cfg.pid_permutation_shuffles, cfg.pid_bins,
            )

            pid_results.append(PIDResult(
                agent_i=ai,
                agent_j=aj,
                unique_i=unique_i,
                unique_j=unique_j,
                redundancy=redundancy,
                synergy=synergy,
                total_mi=total_mi,
                n_contributions=len(contributions),
                p_value=p_value,
                is_significant=p_value < cfg.pid_significance_threshold,
            ))

        # 4. Aggregate ship-level metrics
        significant = [r for r in pid_results if r.is_significant]
        pairs_analyzed = len(pid_results)
        significant_pairs = len(significant)

        if significant:
            synergies = sorted([r.synergy for r in significant])
            mid = len(synergies) // 2
            emergence_capacity = (
                synergies[mid] if len(synergies) % 2 == 1
                else (synergies[mid - 1] + synergies[mid]) / 2.0
            )
        else:
            emergence_capacity = 0.0

        # Coordination balance (Riedl interaction term)
        if pid_results:
            balance_scores = [r.synergy * r.redundancy for r in pid_results]
            coordination_balance = sum(balance_scores) / len(balance_scores)
        else:
            coordination_balance = 0.0

        # Ratios
        if pid_results:
            total_s = sum(r.synergy for r in pid_results)
            total_r = sum(r.redundancy for r in pid_results)
            total_sr = total_s + total_r
            if total_sr > 1e-10:
                redundancy_ratio = total_r / total_sr
                synergy_ratio = total_s / total_sr
            else:
                redundancy_ratio = 0.0
                synergy_ratio = 0.0
        else:
            redundancy_ratio = 0.0
            synergy_ratio = 0.0

        # Top synergy pairs
        sorted_by_synergy = sorted(pid_results, key=lambda r: r.synergy, reverse=True)
        top_synergy_pairs = [
            (r.agent_i, r.agent_j, r.synergy)
            for r in sorted_by_synergy[:5]
        ]

        # 5. Per-department metrics
        per_department: dict[str, dict[str, float]] = {}
        if get_department:
            dept_pairs: dict[str, list[PIDResult]] = defaultdict(list)
            cross_dept_pairs: list[PIDResult] = []
            for r in pid_results:
                dept_i = get_department(r.agent_i)
                dept_j = get_department(r.agent_j)
                if dept_i and dept_j:
                    if dept_i == dept_j:
                        dept_pairs[dept_i].append(r)
                    else:
                        cross_dept_pairs.append(r)
                        dept_pairs.setdefault(dept_i, [])
                        dept_pairs.setdefault(dept_j, [])

            for dept, results in dept_pairs.items():
                if results:
                    dept_synergy = sum(r.synergy for r in results) / len(results)
                    dept_redundancy = sum(r.redundancy for r in results) / len(results)
                    per_department[dept] = {
                        "synergy": dept_synergy,
                        "redundancy": dept_redundancy,
                        "balance": dept_synergy * dept_redundancy,
                        "pairs": len(results),
                    }

            if cross_dept_pairs:
                cross_synergy = sum(r.synergy for r in cross_dept_pairs) / len(cross_dept_pairs)
                cross_redundancy = sum(r.redundancy for r in cross_dept_pairs) / len(cross_dept_pairs)
                per_department["__cross_department__"] = {
                    "synergy": cross_synergy,
                    "redundancy": cross_redundancy,
                    "balance": cross_synergy * cross_redundancy,
                    "pairs": len(cross_dept_pairs),
                }

        # 6. ToM effectiveness
        for score in all_complementarity_scores:
            self._complementarity_history.append((now, score))

        tom_effectiveness: float | None = None
        if len(self._complementarity_history) >= cfg.tom_trend_min_samples:
            xs = [t for t, _ in self._complementarity_history]
            ys = [s for _, s in self._complementarity_history]
            slope, _, _ = _linear_regression(xs, ys)
            tom_effectiveness = slope

        # 7. Hebbian-synergy correlation
        hebbian_synergy_correlation: float | None = None
        if hebbian_router and pid_results:
            heb_weights: list[float] = []
            pid_synergies: list[float] = []
            try:
                all_weights = hebbian_router.all_weights()
            except Exception:
                all_weights = {}

            for r in pid_results:
                w = all_weights.get((r.agent_i, r.agent_j), 0.0)
                if w == 0.0:
                    w = all_weights.get((r.agent_j, r.agent_i), 0.0)
                if w > 0.0 or (r.agent_i, r.agent_j) in all_weights or (r.agent_j, r.agent_i) in all_weights:
                    heb_weights.append(w)
                    pid_synergies.append(r.synergy)

            if len(heb_weights) >= cfg.hebbian_synergy_min_interactions:
                hebbian_synergy_correlation = _pearson_correlation(heb_weights, pid_synergies)

        # 8. Risk flags
        groupthink_risk = redundancy_ratio > cfg.groupthink_redundancy_threshold
        fragmentation_risk = synergy_ratio < cfg.fragmentation_synergy_threshold and pairs_analyzed > 0

        # 9. Create snapshot
        snapshot = EmergenceSnapshot(
            timestamp=now,
            emergence_capacity=emergence_capacity,
            coordination_balance=coordination_balance,
            redundancy_ratio=redundancy_ratio,
            synergy_ratio=synergy_ratio,
            threads_analyzed=threads_analyzed,
            pairs_analyzed=pairs_analyzed,
            significant_pairs=significant_pairs,
            top_synergy_pairs=top_synergy_pairs,
            per_department=per_department,
            groupthink_risk=groupthink_risk,
            fragmentation_risk=fragmentation_risk,
            tom_effectiveness=tom_effectiveness,
            hebbian_synergy_correlation=hebbian_synergy_correlation,
        )
        self._snapshots.append(snapshot)

        return snapshot


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a < 1e-10 or mag_b < 1e-10:
        return 0.0
    return dot / (mag_a * mag_b)
