"""Episodic-to-procedural bridge for cross-cycle dream patterns (AD-572)."""

from __future__ import annotations

import inspect
import logging
import time
import uuid
from typing import Any

from probos.cognitive.episode_clustering import EpisodeCluster
from probos.cognitive.procedures import Procedure

logger = logging.getLogger(__name__)


class EpisodicProceduralBridge:
    """Bridges episodic clusters to procedural memory across dream cycles."""

    def __init__(
        self,
        config: Any,
        procedure_store: Any = None,
        episodic_memory: Any = None,
    ) -> None:
        self._config = config
        self._procedure_store = procedure_store
        self._episodic_memory = episodic_memory

    def scan_for_procedures(
        self,
        clusters: list[EpisodeCluster],
        existing_procedures: list[Procedure],
        episodes: list[Any] | None = None,
    ) -> list[Procedure]:
        """Return new procedures for novel success-dominant cross-cycle clusters."""
        if not getattr(self._config, "enabled", True):
            return []

        bridged: list[Procedure] = []
        min_episodes = getattr(self._config, "min_cross_cycle_episodes", 5)
        for cluster in clusters:
            if not getattr(cluster, "is_success_dominant", False):
                continue
            if getattr(cluster, "episode_count", 0) < min_episodes:
                continue

            matching = self._matching_procedure(cluster, existing_procedures)
            if matching is not None:
                self._merge_cross_cycle(cluster, matching)
                continue

            bridged.append(self._create_procedure(cluster, episodes or []))
        return bridged

    async def bridge_episodes_to_procedures(
        self,
        episodes: list[Any],
        clusters: list[EpisodeCluster],
    ) -> list[Procedure]:
        """Load existing procedures, scan clusters, and return newly bridged procedures."""
        if not getattr(self._config, "enabled", True) or self._procedure_store is None:
            return []

        existing = await self._load_existing_procedures()
        return self.scan_for_procedures(clusters, existing, episodes=episodes)

    def _is_novel_pattern(self, cluster: EpisodeCluster, existing: list[Procedure]) -> bool:
        """Return True when no existing procedure covers this cluster's provenance."""
        return self._matching_procedure(cluster, existing) is None

    def _merge_cross_cycle(self, cluster: EpisodeCluster, existing_procedure: Procedure) -> Procedure:
        """Merge cross-cycle episode evidence into an existing procedure."""
        merged = sorted(set(existing_procedure.provenance) | set(cluster.episode_ids))
        existing_procedure.provenance = merged
        existing_procedure.success_count += int(cluster.success_rate * cluster.episode_count)
        return existing_procedure

    async def _load_existing_procedures(self) -> list[Procedure]:
        store = self._procedure_store
        if store is None:
            return []

        if hasattr(store, "list_all"):
            result = store.list_all()
            if inspect.isawaitable(result):
                result = await result
            return [proc for proc in result if isinstance(proc, Procedure)]

        if not hasattr(store, "list_active") or not hasattr(store, "get"):
            return []

        active = store.list_active()
        if inspect.isawaitable(active):
            active = await active

        procedures: list[Procedure] = []
        for entry in active or []:
            procedure_id = entry.get("id", "") if isinstance(entry, dict) else getattr(entry, "id", "")
            if not procedure_id:
                continue
            procedure = store.get(procedure_id)
            if inspect.isawaitable(procedure):
                procedure = await procedure
            if isinstance(procedure, Procedure):
                procedures.append(procedure)
        return procedures

    def _matching_procedure(self, cluster: EpisodeCluster, existing: list[Procedure]) -> Procedure | None:
        threshold = 1.0 - getattr(self._config, "novelty_threshold", 0.3)
        cluster_ids = set(cluster.episode_ids)
        cluster_intents = set(getattr(cluster, "intent_types", []))

        for procedure in existing:
            if procedure.origin_cluster_id and procedure.origin_cluster_id == cluster.cluster_id:
                return procedure

            if not cluster_ids:
                continue
            overlap_ratio = len(cluster_ids & set(procedure.provenance)) / len(cluster_ids)
            intent_overlap = not cluster_intents or bool(cluster_intents & set(procedure.intent_types))
            if intent_overlap and overlap_ratio >= threshold:
                return procedure
        return None

    def _create_procedure(self, cluster: EpisodeCluster, episodes: list[Any]) -> Procedure:
        intent_types = list(getattr(cluster, "intent_types", [])) or self._intent_types_from_episodes(cluster, episodes)
        return Procedure(
            id=uuid.uuid4().hex,
            name=f"Bridge: {cluster.cluster_id[:16]}",
            description=f"Cross-cycle pattern from {cluster.episode_count} episodes",
            intent_types=intent_types,
            origin_cluster_id=cluster.cluster_id,
            origin_agent_ids=list(getattr(cluster, "participating_agents", [])),
            provenance=list(cluster.episode_ids),
            extraction_date=time.time(),
            evolution_type="BRIDGED",
        )

    def _intent_types_from_episodes(self, cluster: EpisodeCluster, episodes: list[Any]) -> list[str]:
        cluster_ids = set(cluster.episode_ids)
        intents: set[str] = set()
        for episode in episodes:
            if getattr(episode, "id", "") not in cluster_ids:
                continue
            for outcome in getattr(episode, "outcomes", []):
                intent = outcome.get("intent", "")
                if intent:
                    intents.add(intent)
        return sorted(intents)