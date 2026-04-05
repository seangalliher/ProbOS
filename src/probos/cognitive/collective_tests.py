"""AD-566e: Tier 3 Collective Qualification Tests.

Five crew-wide qualification tests measuring collective intelligence —
properties that emerge from crew collaboration, not individual agent
capability.  These validate ProbOS's core thesis: "Architecture is a
multiplier orthogonal to model scale."

All probes are **read-only consumers** of existing infrastructure.
No LLM calls, no triggering new computations.

Probes:
    CoordinationBreakevenProbe  — CBS (Zhao et al.)
    ScaffoldDecompositionProbe  — IRT proxy (Ge et al.)
    CollectiveIntelligenceProbe — Woolley c-factor adaptation
    ConvergenceRateProbe        — cross-agent convergence speed
    EmergenceCapacityProbe      — PID emergence wrapper (Riedl 2025)
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from probos.cognitive.qualification import TestResult

logger = logging.getLogger(__name__)

CREW_AGENT_ID = "__crew__"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gini(values: list[float]) -> float:
    """Gini coefficient.  0 = perfect equality, 1 = perfect inequality."""
    if not values or all(v == 0 for v in values):
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    total = sum(sorted_v)
    cumsum = sum((2 * (i + 1) - n - 1) * v for i, v in enumerate(sorted_v))
    return cumsum / (n * total)


def _skip_result(test_name: str, reason: str) -> TestResult:
    """Return a skip-passing TestResult for a collective test."""
    return TestResult(
        agent_id=CREW_AGENT_ID,
        test_name=test_name,
        tier=3,
        score=0.0,
        passed=True,
        timestamp=time.time(),
        duration_ms=0.0,
        details={"skipped": True, "reason": reason},
    )


def _get_crew_agent_ids(runtime: Any) -> list[str]:
    """Enumerate active crew agent IDs from runtime pools."""
    try:
        from probos.crew_utils import is_crew_agent

        ids: list[str] = []
        pools = getattr(runtime, "pools", {})
        for pool in pools.values():
            for agent in getattr(pool, "healthy_agents", []):
                if is_crew_agent(agent):
                    ids.append(agent.id)
        return ids
    except Exception:
        return []


# ---------------------------------------------------------------------------
# D1 — CoordinationBreakevenProbe
# ---------------------------------------------------------------------------


class CoordinationBreakevenProbe:
    """Coordination Breakeven Spread (AD-566e D1).

    Measures whether multi-agent coordination adds net value above
    transaction costs.  Adapted from Zhao et al. (arXiv:2603.27539).
    """

    name = "coordination_breakeven_spread"
    tier = 3
    description = "Does crew coordination add net value above overhead?"
    threshold = 0.0  # Profile measurement

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()

        engine = getattr(runtime, "_emergence_metrics_engine", None)
        if engine is None:
            return _skip_result(self.name, "no_emergence_engine")

        snapshot = getattr(engine, "latest_snapshot", None)
        if snapshot is None:
            return _skip_result(self.name, "no_emergence_data")

        synergy = snapshot.emergence_capacity

        # Overhead proxy: avg posts per multi-agent thread
        try:
            stats = await runtime.ward_room.get_stats()
        except Exception:
            stats = {}

        total_posts = stats.get("total_posts", 0)
        total_threads = stats.get("total_threads", 1)
        avg_posts_per_thread = total_posts / max(total_threads, 1)

        # Normalize overhead to [0, 1]: 1 post = 0, 20+ posts = 1.0
        overhead = min(1.0, max(0.0, (avg_posts_per_thread - 1) / 19.0))

        # CBS: synergy / (synergy + overhead)
        if synergy + overhead == 0:
            score = 0.5  # Neutral
        else:
            score = synergy / (synergy + overhead)

        duration_ms = (time.time() - t0) * 1000
        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=self.tier,
            score=round(score, 4),
            passed=score >= self.threshold,
            timestamp=time.time(),
            duration_ms=duration_ms,
            details={
                "skipped": False,
                "emergence_capacity": synergy,
                "coordination_balance": snapshot.coordination_balance,
                "avg_posts_per_thread": round(avg_posts_per_thread, 2),
                "overhead_estimate": round(overhead, 4),
                "cbs_score": round(score, 4),
                "threads_analyzed": snapshot.threads_analyzed,
            },
        )


# ---------------------------------------------------------------------------
# D2 — ScaffoldDecompositionProbe
# ---------------------------------------------------------------------------


class ScaffoldDecompositionProbe:
    """IRT-inspired scaffold decomposition (AD-566e D2).

    Measures how much ProbOS scaffold amplifies agent capability
    beyond raw LLM performance.  Adapted from Ge et al.
    (arXiv:2604.00594).
    """

    name = "scaffold_decomposition"
    tier = 3
    description = "Architecture multiplier - scaffold vs raw LLM ability"
    threshold = 0.0  # Profile measurement

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()

        harness = getattr(runtime, "_qualification_harness", None)
        store = getattr(runtime, "_qualification_store", None)
        if harness is None or store is None:
            return _skip_result(self.name, "no_qualification_infrastructure")

        # Gather Tier 1 tests with threshold > 0
        tier1_tests = {
            name: test
            for name, test in harness.registered_tests.items()
            if test.tier == 1 and test.threshold > 0
        }
        if not tier1_tests:
            return _skip_result(self.name, "no_tier1_tests")

        # Get crew agent IDs
        crew_ids = _get_crew_agent_ids(runtime)
        if not crew_ids:
            return _skip_result(self.name, "no_crew_agents")

        # Collect latest scores per agent per test
        actual_scores: list[float] = []
        thresholds: list[float] = []
        per_test_multipliers: dict[str, float] = {}

        for test_name, test in tier1_tests.items():
            test_actuals: list[float] = []
            for cid in crew_ids:
                result = await store.get_latest(cid, test_name)
                if result is not None and result.error is None:
                    test_actuals.append(result.score)
                    actual_scores.append(result.score)
                    thresholds.append(test.threshold)

            if test_actuals:
                mean_actual = sum(test_actuals) / len(test_actuals)
                per_test_multipliers[test_name] = round(
                    mean_actual / max(test.threshold, 0.01), 4
                )

        if not thresholds:
            return _skip_result(self.name, "no_tier1_data")

        # Architecture multiplier
        mean_actual = sum(actual_scores) / len(actual_scores)
        mean_threshold = sum(thresholds) / len(thresholds)
        multiplier = mean_actual / max(mean_threshold, 0.01)

        # Normalize: 2x multiplier = 1.0
        score = min(1.0, multiplier / 2.0)

        duration_ms = (time.time() - t0) * 1000
        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=self.tier,
            score=round(score, 4),
            passed=score >= self.threshold,
            timestamp=time.time(),
            duration_ms=duration_ms,
            details={
                "skipped": False,
                "architecture_multiplier": round(multiplier, 4),
                "mean_actual": round(mean_actual, 4),
                "mean_threshold": round(mean_threshold, 4),
                "agents_measured": len(crew_ids),
                "tests_measured": len(per_test_multipliers),
                "per_test_multipliers": per_test_multipliers,
            },
        )


# ---------------------------------------------------------------------------
# D3 — CollectiveIntelligenceProbe
# ---------------------------------------------------------------------------


class CollectiveIntelligenceProbe:
    """Woolley c-factor for AI agent teams (AD-566e D3).

    First known measurement of collective intelligence factor
    for AI agent teams.  Adapted from Woolley et al. (Science, 2010).
    """

    name = "collective_intelligence_cfactor"
    tier = 3
    description = "Woolley c-factor - collective intelligence measurement"
    threshold = 0.0  # Profile measurement, novel research

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()

        # Get crew agents
        crew_ids = _get_crew_agent_ids(runtime)
        if not crew_ids:
            return _skip_result(self.name, "no_crew_agents")

        # --- Turn-taking equality (Gini of post counts) ---
        post_distribution: dict[str, int] = {}
        try:
            for cid in crew_ids:
                cred = await runtime.ward_room.get_credibility(cid)
                post_distribution[cid] = cred.total_posts if cred else 0
        except Exception:
            pass

        post_counts = list(post_distribution.values())
        if not post_counts or all(c == 0 for c in post_counts):
            return _skip_result(self.name, "no_ward_room_data")

        gini = _gini([float(c) for c in post_counts])
        turn_taking_equality = 1.0 - gini

        # --- Social sensitivity proxy (ToM effectiveness) ---
        engine = getattr(runtime, "_emergence_metrics_engine", None)
        snapshot = getattr(engine, "latest_snapshot", None) if engine else None
        tom_effectiveness = snapshot.tom_effectiveness if snapshot else None

        # --- Personality diversity ---
        personality_diversity = 0.0
        try:
            from probos.crew_profile import PersonalityTraits, load_seed_profile

            traits_list: list[PersonalityTraits] = []
            pools = getattr(runtime, "pools", {})
            for pool in pools.values():
                for agent in getattr(pool, "healthy_agents", []):
                    try:
                        from probos.crew_utils import is_crew_agent
                        if not is_crew_agent(agent):
                            continue
                    except Exception:
                        continue
                    try:
                        profile = load_seed_profile(agent.agent_type)
                        p = profile.get("personality", {})
                        if p:
                            traits_list.append(PersonalityTraits(
                                openness=p.get("openness", 0.5),
                                conscientiousness=p.get("conscientiousness", 0.5),
                                extraversion=p.get("extraversion", 0.5),
                                agreeableness=p.get("agreeableness", 0.5),
                                neuroticism=p.get("neuroticism", 0.5),
                            ))
                    except Exception:
                        continue

            # Mean pairwise distance, normalized by max possible (sqrt(5))
            if len(traits_list) >= 2:
                distances: list[float] = []
                for i in range(len(traits_list)):
                    for j in range(i + 1, len(traits_list)):
                        distances.append(traits_list[i].distance_from(traits_list[j]))
                max_distance = math.sqrt(5)
                personality_diversity = (
                    sum(distances) / len(distances)
                ) / max_distance
                personality_diversity = min(1.0, personality_diversity)
        except Exception:
            pass

        # --- c-factor composite score ---
        tom_score = tom_effectiveness if tom_effectiveness is not None else 0.0
        cfactor = (
            turn_taking_equality * 0.4
            + tom_score * 0.3
            + personality_diversity * 0.3
        )

        duration_ms = (time.time() - t0) * 1000
        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=self.tier,
            score=round(cfactor, 4),
            passed=cfactor >= self.threshold,
            timestamp=time.time(),
            duration_ms=duration_ms,
            details={
                "skipped": False,
                "turn_taking_equality": round(turn_taking_equality, 4),
                "gini_coefficient": round(gini, 4),
                "tom_effectiveness": tom_effectiveness,
                "personality_diversity": round(personality_diversity, 4),
                "agent_count": len(crew_ids),
                "post_distribution": post_distribution,
                "cfactor_score": round(cfactor, 4),
            },
        )


# ---------------------------------------------------------------------------
# D4 — ConvergenceRateProbe
# ---------------------------------------------------------------------------


class ConvergenceRateProbe:
    """Convergence rate measurement (AD-566e D4).

    Measures crew's time-to-agreement across departments.
    Consumes AD-554 convergence detection data via EmergenceSnapshot.
    """

    name = "convergence_rate"
    tier = 3
    description = "Cross-agent convergence speed and quality"
    threshold = 0.0  # Profile measurement

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()

        engine = getattr(runtime, "_emergence_metrics_engine", None)
        if engine is None:
            return _skip_result(self.name, "no_emergence_engine")

        snapshot = getattr(engine, "latest_snapshot", None)
        if snapshot is None:
            return _skip_result(self.name, "no_emergence_data")

        # Primary metric: fraction of analyzed pairs with significant coordination
        if snapshot.pairs_analyzed > 0:
            coordination_rate = snapshot.significant_pairs / snapshot.pairs_analyzed
        else:
            coordination_rate = 0.0

        score = coordination_rate

        duration_ms = (time.time() - t0) * 1000
        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=self.tier,
            score=round(score, 4),
            passed=score >= self.threshold,
            timestamp=time.time(),
            duration_ms=duration_ms,
            details={
                "skipped": False,
                "pairs_analyzed": snapshot.pairs_analyzed,
                "significant_pairs": snapshot.significant_pairs,
                "coordination_rate": round(coordination_rate, 4),
                "threads_analyzed": snapshot.threads_analyzed,
                "groupthink_risk": snapshot.groupthink_risk,
                "fragmentation_risk": snapshot.fragmentation_risk,
            },
        )


# ---------------------------------------------------------------------------
# D5 — EmergenceCapacityProbe
# ---------------------------------------------------------------------------


class EmergenceCapacityProbe:
    """Emergence capacity qualification wrapper (AD-566e D5).

    Packages AD-557 PID emergence metrics as a qualification test
    for longitudinal tracking and drift detection.
    """

    name = "emergence_capacity"
    tier = 3
    description = "PID-based emergence capacity (Riedl 2025)"
    threshold = 0.0  # Profile measurement

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()

        engine = getattr(runtime, "_emergence_metrics_engine", None)
        if engine is None:
            return _skip_result(self.name, "no_emergence_engine")

        snapshot = getattr(engine, "latest_snapshot", None)
        if snapshot is None:
            return _skip_result(self.name, "no_emergence_data")

        score = snapshot.emergence_capacity

        duration_ms = (time.time() - t0) * 1000
        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=self.tier,
            score=round(score, 4),
            passed=score >= self.threshold,
            timestamp=time.time(),
            duration_ms=duration_ms,
            details={
                "skipped": False,
                "emergence_capacity": snapshot.emergence_capacity,
                "coordination_balance": snapshot.coordination_balance,
                "synergy_ratio": snapshot.synergy_ratio,
                "redundancy_ratio": snapshot.redundancy_ratio,
                "hebbian_synergy_correlation": snapshot.hebbian_synergy_correlation,
                "tom_effectiveness": snapshot.tom_effectiveness,
                "groupthink_risk": snapshot.groupthink_risk,
                "fragmentation_risk": snapshot.fragmentation_risk,
                "threads_analyzed": snapshot.threads_analyzed,
                "pairs_analyzed": snapshot.pairs_analyzed,
            },
        )
