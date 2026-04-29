"""AD-608: Retroactive Memory Evolution.

Store-time metadata propagation: when a new episode is stored, find
semantically similar recent episodes and propagate relational links
and missing anchor fields between them.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvolutionReport:
    """Summary of retroactive evolution for a single store operation."""

    episodes_updated: int = 0
    relations_added: int = 0
    anchor_fields_propagated: int = 0


class RetroactiveEvolver:
    """Evolves existing episode metadata when new episodes are stored."""

    def __init__(
        self,
        config: Any,
        episodic_memory: Any = None,
        agent_id: str = "",
    ) -> None:
        self._episodic_memory = episodic_memory
        self._agent_id: str = agent_id

        self._enabled: bool = config.enabled
        self._neighbor_k: int = config.neighbor_k
        self._similarity_threshold: float = config.similarity_threshold
        self._max_relations: int = config.max_relations_per_episode
        self._propagate_watch_section: bool = config.propagate_watch_section
        self._propagate_department: bool = config.propagate_department

    def set_episodic_memory(self, memory: Any) -> None:
        """Late-bind episodic memory reference."""
        self._episodic_memory = memory

    async def evolve_on_store(self, new_episode: Any) -> EvolutionReport:
        """Evolve metadata for related episodes after a successful store."""
        report = EvolutionReport()

        if not self._enabled:
            return report

        if not self._episodic_memory:
            return report

        neighbors = await self._find_neighbors(new_episode)

        for neighbor in neighbors:
            neighbor_episode = neighbor.episode
            neighbor_id = neighbor_episode.id

            if neighbor_id == new_episode.id:
                continue

            similarity = max(neighbor.composite_score, neighbor.semantic_similarity)
            if similarity < self._similarity_threshold:
                continue

            relation = self._classify_relation(new_episode, neighbor_episode)

            added_forward = await self._propagate_metadata(
                new_episode,
                neighbor_id,
                relation,
            )
            added_reverse = await self._propagate_metadata_reverse(
                neighbor_id,
                new_episode.id,
                relation,
            )

            if added_forward or added_reverse:
                report.relations_added += (1 if added_forward else 0) + (1 if added_reverse else 0)
                report.episodes_updated += 1

            propagated = await self._update_anchor_fields(
                target_id=neighbor_id,
                source_episode=new_episode,
            )
            report.anchor_fields_propagated += propagated

        if report.episodes_updated > 0:
            logger.info(
                "AD-608: Evolved %d episodes; %d relations added and %d anchor fields propagated",
                report.episodes_updated,
                report.relations_added,
                report.anchor_fields_propagated,
            )

        return report

    async def _find_neighbors(
        self,
        episode: Any,
        k: int | None = None,
    ) -> list[Any]:
        """Retrieve semantically similar recent episodes."""
        if not self._episodic_memory:
            return []

        k = k or self._neighbor_k
        query = episode.user_input or ""
        if episode.reflection:
            query += " " + episode.reflection

        if not query.strip():
            return []

        try:
            results = await self._episodic_memory.recall_weighted(
                self._agent_id,
                query=query,
                k=k,
            )
        except Exception:
            logger.debug("AD-608: Neighbor recall failed; skipping retroactive evolution", exc_info=True)
            return []

        return results

    def _classify_relation(
        self,
        source_episode: Any,
        target_episode: Any,
    ) -> str:
        """Classify the relationship between two episodes."""
        source_ts = getattr(source_episode, "timestamp", 0.0) or 0.0
        target_ts = getattr(target_episode, "timestamp", 0.0) or 0.0
        time_delta = abs(source_ts - target_ts)

        source_anchors = getattr(source_episode, "anchors", None)
        target_anchors = getattr(target_episode, "anchors", None)

        if time_delta <= 60.0 and source_anchors and target_anchors:
            source_trigger = (
                getattr(source_anchors, "trigger_type", None)
                or getattr(source_anchors, "trigger", None)
                or ""
            )
            target_trigger = (
                getattr(target_anchors, "trigger_type", None)
                or getattr(target_anchors, "trigger", None)
                or ""
            )
            if source_trigger and source_trigger == target_trigger:
                return "causal"

        if source_anchors and target_anchors:
            source_department = getattr(source_anchors, "department", None) or ""
            target_department = getattr(target_anchors, "department", None) or ""
            if source_department and source_department == target_department:
                return "contextual"

            source_channel = getattr(source_anchors, "channel", None) or ""
            target_channel = getattr(target_anchors, "channel", None) or ""
            if source_channel and source_channel == target_channel:
                return "contextual"

        return "associative"

    async def _propagate_metadata(
        self,
        source_episode: Any,
        target_id: str,
        relation: str,
    ) -> bool:
        """Add a relational tag from source to target episode."""
        if not self._episodic_memory:
            return False

        return await self._add_relation(
            episode_id=source_episode.id,
            related_id=target_id,
            relation=relation,
        )

    async def _propagate_metadata_reverse(
        self,
        episode_id: str,
        source_id: str,
        relation_type: str,
    ) -> bool:
        """Add a reverse relational back-reference from target back to source."""
        if not self._episodic_memory:
            return False

        reverse_map = {
            "causal": "caused_by",
            "caused_by": "causal",
            "follows": "followed_by",
            "followed_by": "follows",
            "answers": "answered_by",
            "answered_by": "answers",
            "contradicts": "contradicts",
            "contextual": "contextual",
            "associative": "associative",
            "relates_to": "relates_to",
        }
        reverse_relation = reverse_map.get(relation_type, "relates_to")

        return await self._add_relation(
            episode_id=episode_id,
            related_id=source_id,
            relation=reverse_relation,
        )

    async def _add_relation(
        self,
        episode_id: str,
        related_id: str,
        relation: str,
    ) -> bool:
        """Add a single relation to an episode's relations_json metadata."""
        memory = self._episodic_memory
        if not memory:
            return False

        try:
            metadata = await memory.get_episode_metadata(episode_id)
            if metadata is None:
                return False
            current_relations_json = metadata.get("relations_json", "[]")
        except Exception:
            return False

        try:
            relations = json.loads(current_relations_json)
        except (json.JSONDecodeError, TypeError):
            relations = []

        if len(relations) >= self._max_relations:
            return False

        for existing_relation in relations:
            if (
                existing_relation.get("related_episode_id") == related_id
                and existing_relation.get("relation_type") == relation
            ):
                return False

        relations.append(
            {
                "related_episode_id": related_id,
                "relation_type": relation,
                "timestamp": time.time(),
            }
        )

        try:
            await memory.update_episode_metadata(episode_id, {"relations_json": json.dumps(relations)})
        except Exception:
            logger.debug(
                "AD-608: Failed to update relations for %s; skipping this relation",
                episode_id,
                exc_info=True,
            )
            return False

        return True

    async def _update_anchor_fields(
        self,
        target_id: str,
        source_episode: Any,
    ) -> int:
        """Propagate missing anchor fields from source to target episode."""
        if not self._episodic_memory:
            return 0

        source_anchors = getattr(source_episode, "anchors", None)
        if source_anchors is None:
            return 0

        try:
            metadata = await self._episodic_memory.get_episode_metadata(target_id) or {}
        except Exception:
            return 0

        updates: dict[str, str] = {}
        propagated = 0

        if self._propagate_watch_section and source_anchors.watch_section:
            current = metadata.get("anchor_watch_section", "")
            if not current:
                updates["anchor_watch_section"] = source_anchors.watch_section
                propagated += 1

        if self._propagate_department and source_anchors.department:
            current = metadata.get("anchor_department", "")
            if not current:
                updates["anchor_department"] = source_anchors.department
                propagated += 1

        if updates and propagated > 0:
            try:
                await self._episodic_memory.update_episode_metadata(target_id, updates)
            except Exception:
                logger.debug(
                    "AD-608: Failed to propagate anchor fields to %s; leaving existing metadata unchanged",
                    target_id,
                    exc_info=True,
                )
                return 0

        return propagated

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot for monitoring."""
        return {
            "enabled": self._enabled,
            "neighbor_k": self._neighbor_k,
            "similarity_threshold": self._similarity_threshold,
            "max_relations": self._max_relations,
        }