"""EmergentDetector — population-level dynamics analysis for emergent behavior patterns.

AD-236: Monitors system-wide dynamics across ALL agents for emergent behavior:
- Hebbian weight topology → cooperation clusters
- Trust score trajectories → change-point detection
- Routing patterns → intent distribution shifts
- Dream consolidation → unusual strengthening/pruning
- Capability growth → rate of new intent types

Unlike BehavioralMonitor (which tracks individual self-created agents),
EmergentDetector analyzes population-level patterns. It is purely
observational — a reader, not a writer.
"""

from __future__ import annotations

import collections
import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.consensus.trust import TrustNetwork  # AD-399: allowed edge — reads trust for emergent pattern detection
from probos.mesh.routing import HebbianRouter, REL_INTENT

logger = logging.getLogger(__name__)


@dataclass
class EmergentPattern:
    """A detected emergent behavior pattern."""

    pattern_type: str       # "cooperation_cluster", "trust_anomaly",
                            # "routing_shift", "consolidation_anomaly",
                            # "capability_growth"
    description: str        # Human-readable description
    confidence: float       # 0.0-1.0
    evidence: dict = field(default_factory=dict)  # Supporting data
    timestamp: float = 0.0  # time.monotonic() when detected
    severity: str = "info"  # "info", "notable", "significant"


@dataclass
class SystemDynamicsSnapshot:
    """Point-in-time snapshot of system-level metrics."""

    timestamp: float = 0.0
    tc_n: float = 0.0                                       # Total correlation proxy
    cooperation_clusters: list[dict] = field(default_factory=list)  # Agent groups that co-succeed
    trust_distribution: dict = field(default_factory=dict)   # mean, std, min, max, skew
    routing_entropy: float = 0.0                             # How evenly intents are distributed
    capability_count: int = 0                                # Number of distinct intent types handled
    dream_consolidation_rate: float = 0.0                    # Weights changed per dream cycle


class TrendDirection(str, Enum):
    RISING = "rising"
    STABLE = "stable"
    FALLING = "falling"


@dataclass
class MetricTrend:
    """Trend analysis for a single metric over N snapshots."""
    metric_name: str
    direction: TrendDirection
    slope: float  # rate of change per snapshot
    r_squared: float  # goodness of fit (0-1), indicates confidence
    current_value: float
    window_size: int  # how many snapshots were used
    significant: bool  # slope magnitude > threshold AND r_squared > 0.5


@dataclass
class TrendReport:
    """Multi-metric trend analysis over the snapshot ring buffer."""
    tc_n: MetricTrend
    routing_entropy: MetricTrend
    cluster_count: MetricTrend  # number of cooperation clusters
    trust_spread: MetricTrend  # std dev of trust distribution
    capability_count: MetricTrend
    significant_trends: list[MetricTrend]  # only trends where significant=True
    window_size: int
    timestamp: float


class EmergentDetector:
    """Monitors system dynamics for emergent behavior patterns.

    Unlike BehavioralMonitor (which tracks individual self-created agents),
    EmergentDetector analyzes population-level patterns across ALL agents:
    - Hebbian weight topology → cooperation clusters
    - Trust score trajectories → change-point detection
    - Routing patterns → intent distribution shifts
    - Dream consolidation → unusual strengthening/pruning
    - Capability growth → rate of new intent types
    """

    def __init__(
        self,
        hebbian_router: HebbianRouter,
        trust_network: TrustNetwork,
        episodic_memory: Any = None,
        max_history: int = 100,
        trend_threshold: float = 0.005,
    ) -> None:
        self._router = hebbian_router
        self._trust = trust_network
        self._episodic_memory = episodic_memory
        self._max_history = max_history
        self._trend_threshold = trend_threshold

        # Live agent roster — set via set_live_agents() from runtime at startup.
        # When set, cooperation cluster detection filters out defunct agents.
        self._live_agent_ids: set[str] | None = None

        # Ring buffer of snapshots for trend analysis
        self._history: collections.deque[SystemDynamicsSnapshot] = collections.deque(maxlen=max_history)

        # All detected patterns (historical)
        self._all_patterns: list[EmergentPattern] = []

        # Previous snapshot for change detection
        self._prev_intent_agent_map: dict[str, set[str]] = {}

        # Dream report history for consolidation anomaly baselines
        self._dream_history: list[dict] = []

    def set_live_agents(self, agent_ids: set[str]) -> None:
        """Update the set of live agent IDs from the runtime pool registry."""
        self._live_agent_ids = agent_ids

    def analyze(self, dream_report: Any = None) -> list[EmergentPattern]:
        """Main analysis entry point. Runs all detectors and returns detected patterns."""
        now = time.monotonic()

        # Cache episode total for early-session guards (AD-288)
        if dream_report is not None:
            replayed = getattr(dream_report, 'episodes_replayed', 0)
            if isinstance(dream_report, dict):
                replayed = dream_report.get('episodes_replayed', 0)
            self._cached_episode_total = getattr(self, '_cached_episode_total', 0) + replayed

        # Take snapshot
        snapshot = self.get_snapshot()

        # Store in history ring buffer
        self._history.append(snapshot)

        # Run detectors
        patterns: list[EmergentPattern] = []

        clusters = self.detect_cooperation_clusters(self._live_agent_ids)
        for cluster in clusters:
            patterns.append(EmergentPattern(
                pattern_type="cooperation_cluster",
                description=f"Cooperation cluster: {cluster['size']} nodes, avg weight {cluster['avg_weight']:.3f}",
                confidence=min(1.0, cluster["avg_weight"] * 2),
                evidence=cluster,
                timestamp=now,
                severity="notable" if cluster["size"] >= 3 else "info",
            ))

        patterns.extend(self.detect_trust_anomalies())
        patterns.extend(self.detect_routing_shifts())
        patterns.extend(self.detect_consolidation_anomalies(dream_report))

        # Trend regression over snapshot buffer (AD-380)
        trend_report = self.compute_trends()
        if trend_report and trend_report.significant_trends:
            patterns.append(EmergentPattern(
                pattern_type="emergence_trends",
                description=f"{len(trend_report.significant_trends)} significant trend(s) over {trend_report.window_size} snapshots",
                confidence=max(t.r_squared for t in trend_report.significant_trends),
                evidence={
                    "trends": [
                        {
                            "metric": t.metric_name,
                            "direction": t.direction.value,
                            "slope": round(t.slope, 6),
                            "r_squared": round(t.r_squared, 3),
                            "current": round(t.current_value, 4),
                        }
                        for t in trend_report.significant_trends
                    ],
                    "window_size": trend_report.window_size,
                },
                timestamp=time.monotonic(),
                severity="notable",
            ))

        # Store all detected patterns
        self._all_patterns.extend(patterns)
        # Cap pattern history
        if len(self._all_patterns) > 500:
            self._all_patterns = self._all_patterns[-500:]

        # Update previous intent→agent map for next routing shift detection
        self._prev_intent_agent_map = self._current_intent_agent_map()

        return patterns

    def compute_tc_n(self) -> float:
        """Adapted TC_N for single-mesh ProbOS.

        Computes the fraction of successful DAGs that required multi-pool
        cooperation (2+ distinct pools contributing to the same DAG).
        This is a proxy for system integration.
        """
        if not self._episodic_memory:
            return 0.0

        # We read from the episodic memory's recent episodes synchronously
        # via any cached data. Since episodic memory requires async access,
        # we compute tc_n from Hebbian weights as a synchronous proxy.
        # Multi-pool cooperation is indicated by intent weights spanning
        # multiple pools.
        weights = self._router.all_weights_typed()
        intent_weights = {k: v for k, v in weights.items() if k[2] == REL_INTENT}

        if not intent_weights:
            return 0.0

        # Group by source (intent) to find which pools each intent routes to
        intent_pools: dict[str, set[str]] = {}
        for (source, target, _), weight in intent_weights.items():
            if weight < 0.01:
                continue
            pool = self._extract_pool(target)
            if pool:
                intent_pools.setdefault(source, set()).add(pool)

        if not intent_pools:
            return 0.0

        multi_pool_count = sum(1 for pools in intent_pools.values() if len(pools) >= 2)
        total = len(intent_pools)

        return multi_pool_count / total if total > 0 else 0.0

    def detect_cooperation_clusters(self, live_agent_ids: set[str] | None = None) -> list[dict]:
        """Analyze Hebbian weight graph for agent cooperation clusters.

        If *live_agent_ids* is provided, weights referencing agents not in the
        set are filtered out before cluster detection (prevents ghost clusters
        from agents removed by /reset).
        """
        # Don't detect cooperation clusters until we have enough data (AD-288)
        if self._episodic_memory:
            try:
                # Use cached stats if available; avoid async call from sync method
                total = getattr(self, '_cached_episode_total', 0)
                if total < 10:
                    return []
            except Exception:
                pass

        weights = self._router.all_weights_typed()
        intent_weights = {k: v for k, v in weights.items() if k[2] == REL_INTENT}

        # Filter out weights referencing defunct agents
        if live_agent_ids is not None:
            intent_weights = {
                k: v for k, v in intent_weights.items()
                if k[1] in live_agent_ids or not self._extract_pool(k[1])
            }

        if not intent_weights:
            return []

        # Build adjacency: group by shared source or target above threshold
        threshold = 0.1
        strong_edges: list[tuple[str, str, float]] = []
        for (source, target, _), weight in intent_weights.items():
            if weight >= threshold:
                strong_edges.append((source, target, weight))

        if not strong_edges:
            return []

        # Union-Find for connected components
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        all_nodes: set[str] = set()
        for src, tgt, _ in strong_edges:
            all_nodes.add(src)
            all_nodes.add(tgt)
            union(src, tgt)

        # Collect components
        components: dict[str, list[str]] = {}
        for node in all_nodes:
            root = find(node)
            components.setdefault(root, []).append(node)

        # Build cluster dicts
        clusters: list[dict] = []
        for members in components.values():
            member_set = set(members)
            cluster_weights = [
                w for (s, t, _), w in intent_weights.items()
                if s in member_set or t in member_set
            ]
            avg_weight = sum(cluster_weights) / len(cluster_weights) if cluster_weights else 0.0

            # Separate intents vs agents
            intents = [m for m in members if not self._extract_pool(m)]
            agents = [m for m in members if self._extract_pool(m)]

            clusters.append({
                "intents": intents,
                "agents": agents,
                "avg_weight": avg_weight,
                "size": len(members),
            })

        return clusters

    def detect_trust_anomalies(self) -> list[EmergentPattern]:
        """Detect agents whose trust deviates significantly from the population."""
        now = time.monotonic()
        patterns: list[EmergentPattern] = []

        raw = self._trust.raw_scores()
        if len(raw) < 2:
            return patterns

        # Compute population statistics
        scores = [r["alpha"] / (r["alpha"] + r["beta"]) for r in raw.values()]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        std = math.sqrt(variance) if variance > 0 else 0.0

        if std < 0.001:
            # All trust scores nearly identical — skip deviation check
            pass
        else:
            # Flag agents > 2 std from mean
            for agent_id, record in raw.items():
                score = record["alpha"] / (record["alpha"] + record["beta"])
                deviation = abs(score - mean) / std

                if deviation > 2.0:
                    direction = "high" if score > mean else "low"
                    severity = "significant" if deviation > 3.0 else "notable"
                    # Causal back-references (AD-295c)
                    recent_events = self._trust.get_events_for_agent(agent_id, n=5)
                    causal_events = [
                        {
                            "intent_type": event.intent_type,
                            "success": event.success,
                            "weight": round(event.weight, 4),
                            "score_change": round(event.new_score - event.old_score, 4),
                            "episode_id": event.episode_id,
                        }
                        for event in recent_events
                    ]
                    patterns.append(EmergentPattern(
                        pattern_type="trust_anomaly",
                        description=f"Agent {agent_id[:8]} has {direction} trust ({score:.3f}) — {deviation:.1f}σ from mean ({mean:.3f})",
                        confidence=min(1.0, deviation / 4.0),
                        evidence={
                            "agent_id": agent_id,
                            "score": score,
                            "mean": mean,
                            "std": std,
                            "deviation_sigma": deviation,
                            "direction": direction,
                            "causal_events": causal_events,
                        },
                        timestamp=now,
                        severity=severity,
                    ))

        # Flag hyperactive agents (high observation count relative to population)
        observations = [r["observations"] for r in raw.values()]
        obs_mean = sum(observations) / len(observations) if observations else 0.0
        obs_std = math.sqrt(
            sum((o - obs_mean) ** 2 for o in observations) / len(observations)
        ) if len(observations) > 1 else 0.0

        if obs_std > 0.001:
            for agent_id, record in raw.items():
                obs = record["observations"]
                if obs_mean > 0 and obs > obs_mean + 2 * obs_std:
                    patterns.append(EmergentPattern(
                        pattern_type="trust_anomaly",
                        description=f"Agent {agent_id[:8]} is hyperactive — {obs:.0f} observations vs population mean {obs_mean:.0f}",
                        confidence=0.7,
                        evidence={
                            "agent_id": agent_id,
                            "observations": obs,
                            "population_mean": obs_mean,
                            "population_std": obs_std,
                        },
                        timestamp=now,
                        severity="info",
                    ))

        # Change-point detection: compare against previous snapshot
        if self._history:
            prev_snapshot = self._history[-1]
            prev_trust = prev_snapshot.trust_distribution
            if prev_trust:
                prev_scores = {}
                # Reconstruct previous per-agent scores from raw data
                for agent_id, record in raw.items():
                    prev_record_score = prev_trust.get("per_agent", {}).get(agent_id)
                    if prev_record_score is not None:
                        current_score = record["alpha"] / (record["alpha"] + record["beta"])
                        delta = abs(current_score - prev_record_score)
                        if delta > 0.15:
                            direction = "increased" if current_score > prev_record_score else "decreased"
                            patterns.append(EmergentPattern(
                                pattern_type="trust_anomaly",
                                description=f"Agent {agent_id[:8]} trust {direction} by {delta:.3f} (change point)",
                                confidence=min(1.0, delta / 0.3),
                                evidence={
                                    "agent_id": agent_id,
                                    "previous_score": prev_record_score,
                                    "current_score": current_score,
                                    "delta": delta,
                                },
                                timestamp=now,
                                severity="notable",
                            ))

        return patterns

    def detect_routing_shifts(self) -> list[EmergentPattern]:
        """Detect when agents start handling intent types they haven't handled before."""
        now = time.monotonic()
        patterns: list[EmergentPattern] = []

        current_map = self._current_intent_agent_map()

        if not self._prev_intent_agent_map:
            return patterns

        # Find new connections
        for intent, agents in current_map.items():
            prev_agents = self._prev_intent_agent_map.get(intent, set())
            new_agents = agents - prev_agents
            for agent in new_agents:
                # Include trust and Hebbian context (AD-295c)
                agent_trust = self._trust.get_score(agent)
                hebbian_weight = self._router.get_weight(intent, agent, rel_type=REL_INTENT)
                patterns.append(EmergentPattern(
                    pattern_type="routing_shift",
                    description=f"New routing: agent {agent[:8]} now handles '{intent}'",
                    confidence=0.8,
                    evidence={
                        "intent": intent,
                        "agent": agent,
                        "is_new_connection": True,
                        "agent_trust": round(agent_trust, 4),
                        "hebbian_weight": round(hebbian_weight, 4),
                    },
                    timestamp=now,
                    severity="notable",
                ))

        # Check for new intents that didn't exist before
        new_intents = set(current_map.keys()) - set(self._prev_intent_agent_map.keys())
        for intent in new_intents:
            patterns.append(EmergentPattern(
                pattern_type="routing_shift",
                description=f"New intent type appeared: '{intent}'",
                confidence=0.9,
                evidence={
                    "intent": intent,
                    "agents": list(current_map[intent]),
                    "is_new_intent": True,
                },
                timestamp=now,
                severity="notable",
            ))

        # Entropy change detection
        if len(self._history) >= 2:
            prev_entropy = self._history[-2].routing_entropy
            current_entropy = self.compute_routing_entropy()
            entropy_delta = abs(current_entropy - prev_entropy)
            if entropy_delta > 0.5 and prev_entropy > 0:
                direction = "increased" if current_entropy > prev_entropy else "decreased"
                patterns.append(EmergentPattern(
                    pattern_type="routing_shift",
                    description=f"Routing entropy {direction} by {entropy_delta:.2f} ({prev_entropy:.2f} → {current_entropy:.2f})",
                    confidence=min(1.0, entropy_delta / 1.0),
                    evidence={
                        "previous_entropy": prev_entropy,
                        "current_entropy": current_entropy,
                        "delta": entropy_delta,
                    },
                    timestamp=now,
                    severity="significant" if entropy_delta > 1.0 else "notable",
                ))

        return patterns

    def detect_consolidation_anomalies(self, dream_report: Any = None) -> list[EmergentPattern]:
        """Check dream reports for unusual consolidation patterns."""
        now = time.monotonic()
        patterns: list[EmergentPattern] = []

        if dream_report is None:
            return patterns

        # Store dream report for baseline computation
        if isinstance(dream_report, dict):
            report_data = {
                "weights_strengthened": dream_report.get("weights_strengthened", 0),
                "weights_pruned": dream_report.get("weights_pruned", 0),
                "trust_adjustments": dream_report.get("trust_adjustments", 0),
                "pre_warm_intents": dream_report.get("pre_warm_intents", []),
            }
        else:
            report_data = {
                "weights_strengthened": getattr(dream_report, "weights_strengthened", 0),
                "weights_pruned": getattr(dream_report, "weights_pruned", 0),
                "trust_adjustments": getattr(dream_report, "trust_adjustments", 0),
                "pre_warm_intents": getattr(dream_report, "pre_warm_intents", []),
            }
        self._dream_history.append(report_data)

        # Need at least 2 dream reports for baseline
        if len(self._dream_history) < 2:
            return patterns

        # Compute historical averages (excluding current)
        history = self._dream_history[:-1]
        avg_strengthened = sum(d["weights_strengthened"] for d in history) / len(history)
        avg_pruned = sum(d["weights_pruned"] for d in history) / len(history)
        avg_trust_adj = sum(d["trust_adjustments"] for d in history) / len(history)

        # Flag anomalies: > 2x historical average
        strengthened = report_data["weights_strengthened"]
        if avg_strengthened > 0 and strengthened > 2 * avg_strengthened:
            patterns.append(EmergentPattern(
                pattern_type="consolidation_anomaly",
                description=f"Unusual strengthening: {strengthened} weights (avg: {avg_strengthened:.0f})",
                confidence=min(1.0, strengthened / (3 * avg_strengthened)),
                evidence={
                    "weights_strengthened": strengthened,
                    "historical_average": avg_strengthened,
                    "ratio": strengthened / avg_strengthened,
                },
                timestamp=now,
                severity="notable",
            ))

        pruned = report_data["weights_pruned"]
        if avg_pruned > 0 and pruned > 2 * avg_pruned:
            patterns.append(EmergentPattern(
                pattern_type="consolidation_anomaly",
                description=f"Unusual pruning: {pruned} connections (avg: {avg_pruned:.0f})",
                confidence=min(1.0, pruned / (3 * avg_pruned)),
                evidence={
                    "weights_pruned": pruned,
                    "historical_average": avg_pruned,
                    "ratio": pruned / avg_pruned,
                },
                timestamp=now,
                severity="notable",
            ))

        trust_adj = report_data["trust_adjustments"]
        if avg_trust_adj > 0 and trust_adj > 2 * avg_trust_adj:
            patterns.append(EmergentPattern(
                pattern_type="consolidation_anomaly",
                description=f"Unusual trust adjustments: {trust_adj} (avg: {avg_trust_adj:.0f})",
                confidence=min(1.0, trust_adj / (3 * avg_trust_adj)),
                evidence={
                    "trust_adjustments": trust_adj,
                    "historical_average": avg_trust_adj,
                    "ratio": trust_adj / avg_trust_adj,
                },
                timestamp=now,
                severity="notable",
            ))

        return patterns

    def compute_routing_entropy(self) -> float:
        """Compute Shannon entropy over Hebbian weight distribution across pools."""
        weights = self._router.all_weights_typed()
        intent_weights = {k: v for k, v in weights.items() if k[2] == REL_INTENT}

        # Sum weights by target agent pool
        pool_totals: dict[str, float] = {}
        for (source, target, _), weight in intent_weights.items():
            pool = self._extract_pool(target)
            if pool:
                pool_totals[pool] = pool_totals.get(pool, 0.0) + weight

        total = sum(pool_totals.values())
        if total == 0:
            return 0.0

        entropy = 0.0
        for w in pool_totals.values():
            p = w / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def get_snapshot(self) -> SystemDynamicsSnapshot:
        """Assemble a current snapshot from all metrics."""
        # Trust distribution
        raw_scores = self._trust.raw_scores()
        scores = [r["alpha"] / (r["alpha"] + r["beta"]) for r in raw_scores.values()]

        trust_dist: dict[str, Any] = {}
        per_agent: dict[str, float] = {}
        if scores:
            mean = sum(scores) / len(scores)
            variance = sum((s - mean) ** 2 for s in scores) / len(scores)
            std = math.sqrt(variance) if variance > 0 else 0.0
            trust_dist = {
                "mean": mean,
                "std": std,
                "min": min(scores),
                "max": max(scores),
            }
            for agent_id, record in raw_scores.items():
                per_agent[agent_id] = record["alpha"] / (record["alpha"] + record["beta"])
            trust_dist["per_agent"] = per_agent

        # Capability count from intent weights
        weights = self._router.all_weights_typed()
        intent_types = set()
        for (source, target, rel_type), _ in weights.items():
            if rel_type == REL_INTENT:
                intent_types.add(source)

        # Dream consolidation rate from history
        dream_rate = 0.0
        if self._dream_history:
            last = self._dream_history[-1]
            dream_rate = last.get("weights_strengthened", 0) + last.get("weights_pruned", 0)

        return SystemDynamicsSnapshot(
            timestamp=time.monotonic(),
            tc_n=self.compute_tc_n(),
            cooperation_clusters=self.detect_cooperation_clusters(self._live_agent_ids),
            trust_distribution=trust_dist,
            routing_entropy=self.compute_routing_entropy(),
            capability_count=len(intent_types),
            dream_consolidation_rate=dream_rate,
        )

    def summary(self) -> dict:
        """Return a JSON-serializable summary of the current state."""
        # Get counts from latest analysis or compute fresh
        latest_patterns = self._all_patterns[-5:] if self._all_patterns else []

        # Count by type from latest patterns
        type_counts: dict[str, int] = {}
        for p in self._all_patterns:
            type_counts[p.pattern_type] = type_counts.get(p.pattern_type, 0) + 1

        tc_n = self.compute_tc_n()
        entropy = self.compute_routing_entropy()

        return {
            "tc_n": tc_n,
            "routing_entropy": entropy,
            "cooperation_clusters": type_counts.get("cooperation_cluster", 0),
            "trust_anomalies": type_counts.get("trust_anomaly", 0),
            "routing_shifts": type_counts.get("routing_shift", 0),
            "consolidation_anomalies": type_counts.get("consolidation_anomaly", 0),
            "snapshots_recorded": len(self._history),
            "patterns_detected": len(self._all_patterns),
            "latest_patterns": [
                {
                    "pattern_type": p.pattern_type,
                    "description": p.description,
                    "confidence": p.confidence,
                    "severity": p.severity,
                    "timestamp": p.timestamp,
                }
                for p in latest_patterns
            ],
        }

    # ------------------------------------------------------------------
    # Trend regression (AD-380)
    # ------------------------------------------------------------------

    @staticmethod
    def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
        """Simple linear regression. Returns (slope, intercept, r_squared).

        Pure Python — no numpy dependency.
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

        # R-squared
        y_mean = sum_y / n
        ss_tot = sum((y - y_mean) ** 2 for y in ys)
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))

        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-15 else 0.0
        # Clamp to [0, 1] for numerical stability
        r_squared = max(0.0, min(1.0, r_squared))

        return slope, intercept, r_squared

    def compute_trends(self, min_window: int = 20) -> TrendReport | None:
        """Compute trend regression over the snapshot ring buffer.

        Returns None if fewer than min_window snapshots are available.
        Uses simple linear regression (no numpy dependency).
        """
        history = list(self._history)
        if len(history) < min_window:
            return None

        window = history[-min_window:]
        xs = [float(i) for i in range(len(window))]

        def _extract_series(extract_fn: Any) -> list[float]:
            return [extract_fn(s) for s in window]

        def _make_trend(name: str, values: list[float]) -> MetricTrend:
            slope, _intercept, r_sq = self._linear_regression(xs, values)
            if slope > self._trend_threshold:
                direction = TrendDirection.RISING
            elif slope < -self._trend_threshold:
                direction = TrendDirection.FALLING
            else:
                direction = TrendDirection.STABLE
            significant = (
                abs(slope) > self._trend_threshold
                and r_sq > 0.5
                and len(values) >= min_window
            )
            return MetricTrend(
                metric_name=name,
                direction=direction,
                slope=slope,
                r_squared=r_sq,
                current_value=values[-1],
                window_size=len(values),
                significant=significant,
            )

        tc_n_trend = _make_trend("tc_n", _extract_series(lambda s: s.tc_n))
        entropy_trend = _make_trend("routing_entropy", _extract_series(lambda s: s.routing_entropy))
        cluster_trend = _make_trend("cluster_count", _extract_series(lambda s: float(len(s.cooperation_clusters))))
        trust_spread_trend = _make_trend("trust_spread", _extract_series(
            lambda s: s.trust_distribution.get("std", 0.0) if s.trust_distribution else 0.0
        ))
        capability_trend = _make_trend("capability_count", _extract_series(lambda s: float(s.capability_count)))

        all_trends = [tc_n_trend, entropy_trend, cluster_trend, trust_spread_trend, capability_trend]
        significant = [t for t in all_trends if t.significant]

        return TrendReport(
            tc_n=tc_n_trend,
            routing_entropy=entropy_trend,
            cluster_count=cluster_trend,
            trust_spread=trust_spread_trend,
            capability_count=capability_trend,
            significant_trends=significant,
            window_size=len(window),
            timestamp=time.monotonic(),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pool(agent_id: str) -> str:
        """Extract pool name from a deterministic agent ID.

        Uses parse_agent_id() from identity.py for reliable parsing,
        with a fallback for IDs not in the registry.
        """
        from probos.substrate.identity import parse_agent_id

        parsed = parse_agent_id(agent_id)
        if parsed and parsed.get("pool_name"):
            return parsed["pool_name"]
        # Fallback: return the prefix segments minus last two (index_hash)
        parts = agent_id.split("_")
        if len(parts) >= 4:
            return "_".join(parts[:-2])  # everything except index and hash
        return ""

    def _current_intent_agent_map(self) -> dict[str, set[str]]:
        """Build current mapping of intent -> set of agent IDs from Hebbian weights."""
        weights = self._router.all_weights_typed()
        mapping: dict[str, set[str]] = {}
        for (source, target, rel_type), weight in weights.items():
            if rel_type == REL_INTENT and weight >= 0.01:
                mapping.setdefault(source, set()).add(target)
        return mapping
