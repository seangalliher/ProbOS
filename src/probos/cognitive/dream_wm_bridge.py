"""AD-671: Dream-Working Memory Bridge.

Bidirectional pipeline between AgentWorkingMemory and the dream cycle.
Pre-dream: flush WM state to episodic memory as a session summary.
Post-dream: seed WM with priming entries from dream insights.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any

from probos.cognitive.agent_working_memory import AgentWorkingMemory
from probos.config import DreamWMConfig
from probos.types import AnchorFrame, DreamReport, Episode, MemorySource

logger = logging.getLogger(__name__)


class DreamWorkingMemoryBridge:
    """Bidirectional bridge between working memory and dream consolidation."""

    def __init__(self, config: DreamWMConfig) -> None:
        self._config = config

    def pre_dream_flush(
        self,
        wm: AgentWorkingMemory | None,
        agent_id: str,
    ) -> dict[str, Any]:
        """Snapshot working memory into a session summary episode."""
        if not self._config.enabled:
            return {"flushed": False, "entry_count": 0, "reason": "disabled"}
        if wm is None:
            return {"flushed": False, "entry_count": 0, "reason": "no_wm"}

        snapshot = wm.to_dict()
        buffer_names = [
            "recent_actions",
            "recent_observations",
            "recent_conversations",
            "recent_events",
            "recent_reasoning",
        ]
        buffer_counts = {
            buffer_name: len(snapshot.get(buffer_name, []))
            for buffer_name in buffer_names
        }
        entry_count = sum(buffer_counts.values())
        if entry_count < self._config.flush_min_entries:
            return {
                "flushed": False,
                "entry_count": entry_count,
                "reason": "below_threshold",
            }

        entries = [
            entry
            for buffer_name in buffer_names
            for entry in snapshot.get(buffer_name, [])
        ]
        source_counts = Counter(
            entry.get("source_pathway", "unknown") for entry in entries
        )
        category_counts = Counter(
            entry.get("category", "unknown") for entry in entries
        )
        active_engagements = [
            engagement.get("summary", "")
            for engagement in snapshot.get("active_engagements", {}).values()
            if engagement.get("summary")
        ]
        session_summary = {
            "entry_count": entry_count,
            "buffer_counts": buffer_counts,
            "active_engagements": active_engagements,
            "top_sources": source_counts.most_common(5),
            "top_categories": category_counts.most_common(5),
            "cognitive_state": snapshot.get("cognitive_state", {}),
        }
        episode = Episode(
            timestamp=time.time(),
            user_input="[WM Session Summary]",
            dag_summary=session_summary,
            agent_ids=[agent_id],  # sovereign-ok: agent_id from DreamingEngine is already resolved
            source=MemorySource.REFLECTION,
            anchors=AnchorFrame(
                trigger_type="dream_wm_flush",
                channel="working_memory",
            ),
            importance=3,
        )
        return {"flushed": True, "entry_count": entry_count, "episode": episode}

    def post_dream_seed(
        self,
        wm: AgentWorkingMemory,
        dream_report: DreamReport,
        dream_cycle_id: str,
    ) -> int:
        """Seed working memory with non-trivial dream insights."""
        if not self._config.enabled:
            return 0

        insights: list[str] = []
        if dream_report.procedures_extracted > 0:
            insights.append(
                f"Learned {dream_report.procedures_extracted} new procedures "
                "from experience patterns"
            )
        if dream_report.procedures_evolved > 0:
            insights.append(
                f"Evolved {dream_report.procedures_evolved} procedures "
                "based on performance feedback"
            )
        if dream_report.gaps_classified > 0:
            insights.append(
                f"Identified {dream_report.gaps_classified} capability gaps "
                "for development"
            )
        if dream_report.emergence_capacity is not None:
            insights.append(
                f"Crew emergence capacity: {dream_report.emergence_capacity:.2f}"
            )
        if dream_report.notebook_consolidations > 0:
            insights.append(
                f"Consolidated {dream_report.notebook_consolidations} notebook "
                "entries from recent analysis"
            )
        if dream_report.reflections_created > 0:
            insights.append(
                f"Created {dream_report.reflections_created} reflection episodes "
                "from dream insights"
            )
        if dream_report.activation_pruned > 0:
            insights.append(
                f"Pruned {dream_report.activation_pruned} low-activation memories"
            )
        if dream_report.contradictions_found > 0:
            insights.append(
                f"Detected {dream_report.contradictions_found} memory contradictions "
                "for review"
            )

        if not insights:
            return 0

        seeded_count = 0
        for insight in insights[:self._config.max_priming_entries]:
            wm.record_observation(
                summary=f"Dream insight: {insight}",
                source="dream_consolidation",
                metadata={
                    "source": "dream_consolidation",
                    "dream_cycle_id": dream_cycle_id,
                },
                knowledge_source="procedural",
            )
            seeded_count += 1

        logger.info("AD-671: Seeded %d priming entries into WM", seeded_count)
        return seeded_count
