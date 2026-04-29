"""AD-609: Multi-Faceted Distillation - Failure and comparative analysis.

Structural analysis of failure-dominant clusters and comparison against
success clusters on the same intent types. No LLM dependency; analysis is
derived from cluster metadata fields.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ComparativeInsight:
    """Result of comparing success and failure clusters on the same intent."""

    intent_type: str
    success_pattern: str
    failure_pattern: str
    differentiating_factor: str
    confidence: float


class FailureDistiller:
    """Extracts structured failure patterns and comparative insights."""

    def __init__(
        self,
        config: Any,
        procedure_store: Any = None,
    ) -> None:
        self._min_cluster_size: int = config.min_failure_cluster_size
        self._comparative_enabled: bool = config.comparative_enabled
        self._procedure_store = procedure_store

    def distill_failure_patterns(
        self,
        clusters: list[Any],
    ) -> list[Any]:
        """Extract structured failure patterns from failure-dominant clusters."""
        from probos.cognitive.procedures import Procedure, ProcedureStep

        results: list[Any] = []
        for cluster in clusters:
            if not cluster.is_failure_dominant:
                continue
            if cluster.episode_count < self._min_cluster_size:
                continue

            signals = self._extract_failure_signals(cluster)
            intent_types = cluster.intent_types
            if not intent_types:
                continue

            description_parts = [
                f"Failure pattern on intent(s): {', '.join(intent_types)}.",
            ]
            if signals.get("departments"):
                description_parts.append(
                    f"Commonly involves department(s): {', '.join(signals['departments'])}."
                )
            if signals.get("agent_count", 0) > 0:
                description_parts.append(
                    f"Involves {signals['agent_count']} participating agent(s)."
                )
            if signals.get("trigger_types"):
                description_parts.append(
                    f"Common trigger type(s): {', '.join(signals['trigger_types'])}."
                )
            description_parts.append(
                f"Failure rate: {(1 - cluster.success_rate):.0%} across {cluster.episode_count} episodes."
            )
            description = " ".join(description_parts)

            procedure = Procedure(
                id=uuid.uuid4().hex,
                name=f"Failure: {intent_types[0]}",
                description=description,
                intent_types=list(intent_types),
                origin_cluster_id=cluster.cluster_id,
                origin_agent_ids=list(cluster.participating_agents),
                extraction_date=time.time(),
                is_negative=True,
                steps=[
                    ProcedureStep(
                        step_number=1,
                        action=f"Avoid: {intent_types[0]}",
                        expected_input="Failure-prone structural context is present",
                        expected_output="The failure pattern is avoided or escalated",
                        fallback_action="Escalate for human review before repeating the pattern",
                    )
                ],
            )
            results.append(procedure)

            logger.debug(
                "AD-609: Extracted failure pattern from cluster %s as %s",
                cluster.cluster_id[:8],
                procedure.name,
            )

        return results

    def distill_comparative(
        self,
        success_clusters: list[Any],
        failure_clusters: list[Any],
    ) -> list[ComparativeInsight]:
        """Compare success and failure clusters on shared intent types."""
        if not self._comparative_enabled:
            return []

        if not success_clusters or not failure_clusters:
            return []

        success_by_intent: dict[str, list[Any]] = {}
        for cluster in success_clusters:
            for intent in cluster.intent_types:
                success_by_intent.setdefault(intent, []).append(cluster)

        failure_by_intent: dict[str, list[Any]] = {}
        for cluster in failure_clusters:
            for intent in cluster.intent_types:
                failure_by_intent.setdefault(intent, []).append(cluster)

        shared_intents = set(success_by_intent) & set(failure_by_intent)

        insights: list[ComparativeInsight] = []
        for intent in sorted(shared_intents):
            success_for_intent = success_by_intent[intent]
            failure_for_intent = failure_by_intent[intent]

            success_signals = self._aggregate_signals(success_for_intent)
            failure_signals = self._aggregate_signals(failure_for_intent)
            differentiators: list[str] = []

            if success_signals["avg_agent_count"] != failure_signals["avg_agent_count"]:
                if success_signals["avg_agent_count"] > failure_signals["avg_agent_count"]:
                    differentiators.append(
                        "Success involves more agents "
                        f"({success_signals['avg_agent_count']:.1f} vs "
                        f"{failure_signals['avg_agent_count']:.1f})"
                    )
                else:
                    differentiators.append(
                        "Failure involves more agents "
                        f"({failure_signals['avg_agent_count']:.1f} vs "
                        f"{success_signals['avg_agent_count']:.1f})"
                    )

            success_departments = set(success_signals.get("departments", []))
            failure_departments = set(failure_signals.get("departments", []))
            unique_to_failure = sorted(failure_departments - success_departments)
            if unique_to_failure:
                differentiators.append(
                    f"Failure-specific departments: {', '.join(unique_to_failure)}"
                )

            if success_signals["avg_variance"] < failure_signals["avg_variance"]:
                differentiators.append(
                    "Success clusters are tighter "
                    f"(variance {success_signals['avg_variance']:.3f} vs "
                    f"{failure_signals['avg_variance']:.3f})"
                )

            if not differentiators:
                differentiators.append("No clear structural differentiator found")

            success_episode_count = sum(cluster.episode_count for cluster in success_for_intent)
            failure_episode_count = sum(cluster.episode_count for cluster in failure_for_intent)

            insight = ComparativeInsight(
                intent_type=intent,
                success_pattern=(
                    f"{len(success_for_intent)} success cluster(s), "
                    f"{success_episode_count} episodes"
                ),
                failure_pattern=(
                    f"{len(failure_for_intent)} failure cluster(s), "
                    f"{failure_episode_count} episodes"
                ),
                differentiating_factor="; ".join(differentiators),
                confidence=min(success_episode_count, failure_episode_count)
                / max(success_episode_count + failure_episode_count, 1),
            )
            insights.append(insight)

            logger.debug(
                "AD-609: Comparative insight for %s: %s",
                intent,
                insight.differentiating_factor[:80],
            )

        return insights

    def _extract_failure_signals(self, cluster: Any) -> dict[str, Any]:
        """Extract common failure indicators from a cluster."""
        anchor_summary = cluster.anchor_summary or {}
        return {
            "departments": anchor_summary.get("departments", []),
            "trigger_types": anchor_summary.get("trigger_types", []),
            "agent_count": len(cluster.participating_agents),
            "episode_count": cluster.episode_count,
            "success_rate": cluster.success_rate,
        }

    def _aggregate_signals(self, clusters: list[Any]) -> dict[str, Any]:
        """Aggregate structural signals across clusters."""
        all_departments: list[str] = []
        total_agents = 0
        total_variance = 0.0
        for cluster in clusters:
            summary = cluster.anchor_summary or {}
            all_departments.extend(summary.get("departments", []))
            total_agents += len(cluster.participating_agents)
            total_variance += cluster.variance

        cluster_count = max(len(clusters), 1)
        return {
            "departments": sorted(set(all_departments)),
            "avg_agent_count": total_agents / cluster_count,
            "avg_variance": total_variance / cluster_count,
        }