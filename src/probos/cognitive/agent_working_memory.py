"""AD-573: Unified Agent Working Memory — Cognitive Continuity Layer.

Per-agent working memory maintaining the agent's active situation model
across all cognitive pathways (proactive, DM, Ward Room). Every pathway
writes to it when something happens; every pathway reads from it when
building context.

Absorbs concepts from:
- AD-28 WorkingMemoryManager (token budget, priority eviction)
- AD-462 Unified Cognitive Bottleneck (one source of truth)
- AD-504 self-monitoring concepts (recent actions, patterns)
- Letta pattern (persistent agent-scoped state)
- Memory Architecture Layer 2 (implemented, not just documented)
"""

from __future__ import annotations

import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Rough estimate: 1 token ≈ 4 characters
CHARS_PER_TOKEN = 4


@dataclass
class WorkingMemoryEntry:
    """A single item in working memory with timestamp and source."""

    content: str  # Human-readable summary
    category: str  # "action", "observation", "conversation", "game", "alert", "event"
    source_pathway: str  # "proactive", "dm", "ward_room", "system"
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    knowledge_source: str = "unknown"  # AD-568d: "episodic", "parametric", "procedural", "oracle", "unknown"

    def age_seconds(self) -> float:
        return time.time() - self.timestamp

    def token_estimate(self) -> int:
        return len(self.content) // CHARS_PER_TOKEN


@dataclass
class ActiveEngagement:
    """An ongoing interactive state (game, task, conversation thread)."""

    engagement_type: str  # "game", "task", "collaboration"
    engagement_id: str  # unique identifier
    summary: str  # human-readable: "Playing tic-tac-toe against Captain"
    state: dict[str, Any]  # type-specific state (board, valid_moves, etc.)
    started_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def render(self) -> str:
        """Render for LLM context injection."""
        lines = [f"[Active: {self.summary}]"]
        if self.state.get("render"):
            lines.append(self.state["render"])
        return "\n".join(lines)


class AgentWorkingMemory:
    """Unified working memory for a single agent instance.

    Maintains the agent's active situation model across all cognitive
    pathways (proactive, DM, Ward Room). Every pathway writes to it
    when something happens; every pathway reads from it when building
    context.

    AD-573: Cognitive Continuity Layer.
    """

    def __init__(
        self,
        *,
        token_budget: int = 3000,
        max_recent_actions: int = 10,
        max_recent_observations: int = 5,
        max_recent_conversations: int = 5,
        max_events: int = 10,
    ) -> None:
        self._token_budget = token_budget

        # Ring buffers for recent activity
        self._recent_actions: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_actions)
        self._recent_observations: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_observations)
        self._recent_conversations: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_conversations)
        self._recent_events: deque[WorkingMemoryEntry] = deque(maxlen=max_events)

        # Active engagements (games, tasks, collaborations)
        self._active_engagements: dict[str, ActiveEngagement] = {}

        # Cognitive state (cognitive zone, cooldown, alert condition)
        self._cognitive_state: dict[str, Any] = {}

        # AD-589: Last telemetry snapshot for introspective faithfulness verification
        self._last_telemetry_snapshot: dict[str, Any] | None = None

    # ── Write API (called by all cognitive pathways) ──────────────

    def record_action(
        self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """Record an action the agent just took (any pathway)."""
        self._recent_actions.append(WorkingMemoryEntry(
            content=summary,
            category="action",
            source_pathway=source,
            metadata=metadata or {},
            knowledge_source=knowledge_source,
        ))

    def record_observation(
        self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """Record an observation from a proactive think or duty cycle."""
        self._recent_observations.append(WorkingMemoryEntry(
            content=summary,
            category="observation",
            source_pathway=source,
            metadata=metadata or {},
            knowledge_source=knowledge_source,
        ))

    def record_conversation(
        self, summary: str, *, partner: str, source: str,
        metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """Record a DM or Ward Room conversation exchange."""
        self._recent_conversations.append(WorkingMemoryEntry(
            content=summary,
            category="conversation",
            source_pathway=source,
            metadata={"partner": partner, **(metadata or {})},
            knowledge_source=knowledge_source,
        ))

    def record_event(
        self, summary: str, *, source: str = "system",
        metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """Record a system event the agent should be aware of."""
        self._recent_events.append(WorkingMemoryEntry(
            content=summary,
            category="event",
            source_pathway=source,
            metadata=metadata or {},
            knowledge_source=knowledge_source,
        ))

    def add_engagement(self, engagement: ActiveEngagement) -> None:
        """Register an active engagement (game, task, etc.)."""
        self._active_engagements[engagement.engagement_id] = engagement

    def remove_engagement(self, engagement_id: str) -> None:
        """Remove a completed/cancelled engagement."""
        self._active_engagements.pop(engagement_id, None)

    def update_engagement(
        self, engagement_id: str, *, state: dict[str, Any] | None = None,
        summary: str | None = None,
    ) -> None:
        """Update an active engagement's state."""
        eng = self._active_engagements.get(engagement_id)
        if eng:
            if state is not None:
                eng.state.update(state)
            if summary is not None:
                eng.summary = summary
            eng.last_updated = time.time()

    def update_cognitive_state(self, **kwargs: Any) -> None:
        """Update cognitive state fields (zone, cooldown, alert condition)."""
        self._cognitive_state.update(kwargs)

    def get_cognitive_zone(self) -> str | None:
        """AD-588: Return cognitive zone if set via AD-573 sync."""
        return self._cognitive_state.get("zone")

    def set_telemetry_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        """AD-589: Cache telemetry snapshot for faithfulness cross-check."""
        self._last_telemetry_snapshot = snapshot

    # ── Read API (called during context construction) ─────────────

    def render_context(self, *, budget: int | None = None) -> str:
        """Render the full working memory context for LLM injection.

        Budget-aware: evicts lowest-priority items if the rendered
        context exceeds the token budget. Returns empty string if
        nothing noteworthy in working memory.
        """
        effective_budget = budget or self._token_budget
        sections: list[tuple[int, str]] = []  # (priority, text)

        # Priority 1 (highest): Active engagements — always include
        for eng in self._active_engagements.values():
            sections.append((1, eng.render()))

        # Priority 2: Recent actions — what I just did
        if self._recent_actions:
            action_lines = ["Recent actions:"]
            for entry in self._recent_actions:
                age = self._format_age(entry.age_seconds())
                _src_tag = f" [{entry.knowledge_source}]" if entry.knowledge_source != "unknown" else ""
                action_lines.append(f"  - ({age} ago, {entry.source_pathway}) {entry.content}{_src_tag}")
            sections.append((2, "\n".join(action_lines)))

        # Priority 3: Recent conversations — who I just talked to
        if self._recent_conversations:
            conv_lines = ["Recent conversations:"]
            for entry in self._recent_conversations:
                age = self._format_age(entry.age_seconds())
                partner = entry.metadata.get("partner", "unknown")
                conv_lines.append(f"  - ({age} ago) with {partner}: {entry.content}")
            sections.append((3, "\n".join(conv_lines)))

        # Priority 4: Recent observations — what I noticed
        if self._recent_observations:
            obs_lines = ["Recent observations:"]
            for entry in self._recent_observations:
                age = self._format_age(entry.age_seconds())
                _src_tag = f" [{entry.knowledge_source}]" if entry.knowledge_source != "unknown" else ""
                obs_lines.append(f"  - ({age} ago) {entry.content}{_src_tag}")
            sections.append((4, "\n".join(obs_lines)))

        # Priority 5: Cognitive state — zone, cooldown
        if self._cognitive_state:
            state_parts = []
            if "zone" in self._cognitive_state:
                state_parts.append(f"Cognitive zone: {self._cognitive_state['zone']}")
            if "cooldown_reason" in self._cognitive_state:
                state_parts.append(f"Cooldown: {self._cognitive_state['cooldown_reason']}")
            if state_parts:
                sections.append((5, "Cognitive state: " + " | ".join(state_parts)))

        # Priority 6 (lowest): Recent events
        if self._recent_events:
            event_lines = ["Recent events:"]
            for entry in list(self._recent_events)[-5:]:
                event_lines.append(f"  - {entry.content}")
            sections.append((6, "\n".join(event_lines)))

        if not sections:
            return ""

        # Evict lowest-priority sections until within budget
        sections.sort(key=lambda x: x[0])  # ascending priority (1=highest)
        result_parts: list[str] = []
        total_tokens = 0

        for _priority, text in sections:
            tokens = len(text) // CHARS_PER_TOKEN
            if total_tokens + tokens <= effective_budget:
                result_parts.append(text)
                total_tokens += tokens
            # else: evicted (over budget)

        if not result_parts:
            return ""

        return "--- Working Memory ---\n" + "\n\n".join(result_parts) + "\n--- End Working Memory ---"

    def has_engagement(self, engagement_type: str | None = None) -> bool:
        """Check if agent has any (or specific type of) active engagement."""
        if engagement_type is None:
            return bool(self._active_engagements)
        return any(
            e.engagement_type == engagement_type
            for e in self._active_engagements.values()
        )

    def get_engagement(self, engagement_id: str) -> ActiveEngagement | None:
        """Get a specific engagement by ID."""
        return self._active_engagements.get(engagement_id)

    def get_engagements_by_type(self, engagement_type: str) -> list[ActiveEngagement]:
        """Get all engagements of a given type."""
        return [
            e for e in self._active_engagements.values()
            if e.engagement_type == engagement_type
        ]

    @staticmethod
    def _format_age(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds / 60)}m"
        return f"{seconds / 3600:.1f}h"

    # ── Serialization (freeze/restore across stasis) ──────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize working memory state for persistence."""
        return {
            "recent_actions": [
                {"content": e.content, "category": e.category,
                 "source_pathway": e.source_pathway, "timestamp": e.timestamp,
                 "metadata": e.metadata, "knowledge_source": e.knowledge_source}
                for e in self._recent_actions
            ],
            "recent_observations": [
                {"content": e.content, "category": e.category,
                 "source_pathway": e.source_pathway, "timestamp": e.timestamp,
                 "metadata": e.metadata, "knowledge_source": e.knowledge_source}
                for e in self._recent_observations
            ],
            "recent_conversations": [
                {"content": e.content, "category": e.category,
                 "source_pathway": e.source_pathway, "timestamp": e.timestamp,
                 "metadata": e.metadata, "knowledge_source": e.knowledge_source}
                for e in self._recent_conversations
            ],
            "recent_events": [
                {"content": e.content, "category": e.category,
                 "source_pathway": e.source_pathway, "timestamp": e.timestamp,
                 "metadata": e.metadata, "knowledge_source": e.knowledge_source}
                for e in self._recent_events
            ],
            "active_engagements": {
                eid: {
                    "engagement_type": eng.engagement_type,
                    "engagement_id": eng.engagement_id,
                    "summary": eng.summary,
                    "state": eng.state,
                    "started_at": eng.started_at,
                    "last_updated": eng.last_updated,
                }
                for eid, eng in self._active_engagements.items()
            },
            "cognitive_state": dict(self._cognitive_state),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        stale_threshold_seconds: float = 86400.0,  # 24 hours default
    ) -> AgentWorkingMemory:
        """Restore working memory from persisted state.

        Prunes entries older than stale_threshold_seconds.
        Active engagements are restored but may need revalidation
        against live services (e.g., games that expired during stasis).
        """
        now = time.time()
        wm = cls()

        def _restore_entries(entries: list[dict], target: deque) -> None:
            for raw in entries:
                age = now - raw.get("timestamp", 0)
                if age < stale_threshold_seconds:
                    target.append(WorkingMemoryEntry(
                        content=raw["content"],
                        category=raw.get("category", "unknown"),
                        source_pathway=raw.get("source_pathway", "restored"),
                        timestamp=raw.get("timestamp", now),
                        metadata=raw.get("metadata", {}),
                        knowledge_source=raw.get("knowledge_source", "unknown"),
                    ))

        _restore_entries(data.get("recent_actions", []), wm._recent_actions)
        _restore_entries(data.get("recent_observations", []), wm._recent_observations)
        _restore_entries(data.get("recent_conversations", []), wm._recent_conversations)
        _restore_entries(data.get("recent_events", []), wm._recent_events)

        for eid, eng_data in data.get("active_engagements", {}).items():
            wm._active_engagements[eid] = ActiveEngagement(
                engagement_type=eng_data.get("engagement_type", "unknown"),
                engagement_id=eng_data.get("engagement_id", eid),
                summary=eng_data.get("summary", ""),
                state=eng_data.get("state", {}),
                started_at=eng_data.get("started_at", now),
                last_updated=eng_data.get("last_updated", now),
            )

        wm._cognitive_state = data.get("cognitive_state", {})

        # Add stasis awareness marker
        wm.record_event(
            "Restored from stasis — working memory reloaded",
            source="system",
        )

        return wm
