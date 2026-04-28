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
import uuid
from collections import deque
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from probos.cognitive.salience_filter import BackgroundStream, SalienceFilter

if TYPE_CHECKING:
    from probos.cognitive.memory_metabolism import MemoryMetabolism
    from probos.config import PinnedKnowledgeConfig

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


@dataclass(frozen=True)
class PinnedFact:
    """A pinned knowledge fact always loaded into agent context."""

    fact: str
    source: str
    pinned_at: float
    ttl_seconds: float | None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    priority: int = 5


class PinnedKnowledgeBuffer:
    """Small persistent buffer of critical operational facts (AD-579a)."""

    def __init__(
        self,
        *,
        max_tokens: int = 150,
        max_pins: int = 10,
        default_ttl_seconds: float = 86400.0,
    ) -> None:
        self._max_tokens = max_tokens
        self._max_pins = max_pins
        self._default_ttl_seconds = default_ttl_seconds
        self._pins: list[PinnedFact] = []

    def pin(
        self,
        fact: str,
        source: str,
        *,
        ttl_seconds: float | None = None,
        priority: int = 5,
    ) -> PinnedFact:
        """Add a pinned fact or refresh an existing matching fact."""
        self._evict_expired()
        effective_ttl = self._default_ttl_seconds if ttl_seconds is None else ttl_seconds
        pinned_at = time.time()
        for index, existing in enumerate(self._pins):
            if existing.fact == fact:
                updated = replace(
                    existing,
                    source=source,
                    pinned_at=pinned_at,
                    ttl_seconds=effective_ttl,
                    priority=priority,
                )
                self._pins[index] = updated
                return updated

        if len(self._pins) >= self._max_pins:
            self._evict_lowest_priority()

        pinned = PinnedFact(
            fact=fact,
            source=source,
            pinned_at=pinned_at,
            ttl_seconds=effective_ttl,
            priority=priority,
        )
        self._pins.append(pinned)
        return pinned

    def unpin(self, fact_id: str) -> bool:
        """Remove a pinned fact by ID."""
        self._evict_expired()
        for index, pinned in enumerate(self._pins):
            if pinned.id == fact_id:
                del self._pins[index]
                return True
        return False

    def render_pins(self, budget: int | None = None) -> str:
        """Render all active pins within token budget."""
        self._evict_expired()
        effective_budget = self._max_tokens if budget is None else budget
        if effective_budget <= 0 or not self._pins:
            return ""

        lines = ["[Pinned Knowledge]:"]
        total_tokens = 0
        for pinned in sorted(self._pins, key=lambda item: (item.priority, item.pinned_at)):
            line = f"  - {pinned.fact} [{pinned.source}]"
            token_estimate = len(pinned.fact) // CHARS_PER_TOKEN
            if total_tokens + token_estimate > effective_budget:
                continue
            lines.append(line)
            total_tokens += token_estimate

        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    def _evict_expired(self) -> int:
        """Remove pins past their TTL."""
        now = time.time()
        before = len(self._pins)
        self._pins = [
            pinned
            for pinned in self._pins
            if pinned.ttl_seconds is None or now <= pinned.pinned_at + pinned.ttl_seconds
        ]
        return before - len(self._pins)

    def _evict_lowest_priority(self) -> None:
        if not self._pins:
            return
        evict_index, _pinned = max(
            enumerate(self._pins),
            key=lambda item: (item[1].priority, -item[1].pinned_at),
        )
        del self._pins[evict_index]

    @property
    def pins(self) -> list[PinnedFact]:
        """Read-only snapshot of current pins."""
        self._evict_expired()
        return list(self._pins)

    def __len__(self) -> int:
        """Number of active pins."""
        self._evict_expired()
        return len(self._pins)


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


class ConclusionType(StrEnum):
    """AD-669: Types of conclusions a cognitive thread can reach."""

    DECISION = "decision"
    OBSERVATION = "observation"
    ESCALATION = "escalation"
    COMPLETION = "completion"


@dataclass
class ConclusionEntry:
    """AD-669: A conclusion reached by a cognitive thread."""

    thread_id: str
    conclusion_type: ConclusionType
    summary: str
    timestamp: float = field(default_factory=time.time)
    relevance_tags: list[str] = field(default_factory=list)
    correlation_id: str | None = None


@dataclass
class NamedBuffer:
    """A named semantic group of working memory entries with its own token budget."""

    name: str
    token_budget: int
    _entries: deque[WorkingMemoryEntry] = field(default_factory=lambda: deque(maxlen=20))

    def append(self, entry: WorkingMemoryEntry) -> None:
        """Add an entry to this buffer."""
        self._entries.append(entry)

    def render(self, *, budget: int | None = None) -> str:
        """Render this buffer's newest entries within its token budget."""
        if not self._entries:
            return ""

        effective_budget = self.token_budget if budget is None else budget
        selected: list[WorkingMemoryEntry] = []
        total_tokens = 0
        for entry in reversed(self._entries):
            entry_tokens = entry.token_estimate()
            if total_tokens + entry_tokens > effective_budget:
                break
            selected.append(entry)
            total_tokens += entry_tokens

        if not selected:
            return ""

        lines = [f"[{self.name.title()}]:"]
        for entry in selected:
            age = AgentWorkingMemory._format_age(entry.age_seconds())
            lines.append(f"  - ({age} ago) {entry.content}")
        return "\n".join(lines)

    @property
    def entries(self) -> list[WorkingMemoryEntry]:
        """Read-only snapshot of current entries."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


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
        max_recent_reasoning: int = 5,
        duty_budget: int = 600,
        social_budget: int = 800,
        ship_budget: int = 800,
        engagement_budget: int = 800,
        salience_filter: SalienceFilter | None = None,
        agent_context: dict[str, Any] | None = None,
        max_conclusions: int = 20,
        pinned_config: PinnedKnowledgeConfig | None = None,
    ) -> None:
        self._token_budget = token_budget
        self._salience_filter = salience_filter
        self._agent_context = dict(agent_context) if agent_context else {}
        self._background_stream = BackgroundStream() if salience_filter is not None else None

        # Ring buffers for recent activity
        self._recent_actions: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_actions)
        self._recent_observations: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_observations)
        self._recent_conversations: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_conversations)
        self._recent_events: deque[WorkingMemoryEntry] = deque(maxlen=max_events)
        self._recent_reasoning: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_reasoning)

        self._named_buffers: dict[str, NamedBuffer] = {
            "duty": NamedBuffer(name="duty", token_budget=duty_budget),
            "social": NamedBuffer(name="social", token_budget=social_budget),
            "ship": NamedBuffer(name="ship", token_budget=ship_budget),
            "engagement": NamedBuffer(name="engagement", token_budget=engagement_budget),
        }

        # Active engagements (games, tasks, collaborations)
        self._active_engagements: dict[str, ActiveEngagement] = {}

        # Cognitive state (cognitive zone, cooldown, alert condition)
        self._cognitive_state: dict[str, Any] = {}

        # AD-589: Last telemetry snapshot for introspective faithfulness verification
        self._last_telemetry_snapshot: dict[str, Any] | None = None

        # AD-492: Current cognitive cycle correlation ID
        self._correlation_id: str | None = None

        # AD-670: Optional metabolism engine for active lifecycle management
        self._metabolism: MemoryMetabolism | None = None

        # AD-669: Cross-thread conclusion log
        self._conclusions: deque[ConclusionEntry] = deque(maxlen=max_conclusions)

        # AD-579a: Optional pinned knowledge buffer
        if pinned_config is not None and pinned_config.enabled:
            self._pinned_knowledge: PinnedKnowledgeBuffer | None = PinnedKnowledgeBuffer(
                max_tokens=pinned_config.max_tokens,
                max_pins=pinned_config.max_pins,
                default_ttl_seconds=pinned_config.default_ttl_seconds,
            )
        else:
            self._pinned_knowledge = None

    def get_buffer(self, name: str) -> NamedBuffer | None:
        """AD-667: Get a named buffer by name."""
        return self._named_buffers.get(name)

    @property
    def buffer_names(self) -> list[str]:
        """AD-667: List available buffer names."""
        return list(self._named_buffers.keys())

    def set_agent_context(self, context: dict[str, Any]) -> None:
        """AD-668: Update the agent context used for salience scoring."""
        self._agent_context = dict(context)

    def get_background_stream(self) -> BackgroundStream | None:
        """AD-668: Return the background stream when salience filtering is configured."""
        return self._background_stream

    def _passes_salience_gate(self, entry: WorkingMemoryEntry) -> bool:
        """AD-668: Return True when an entry should enter main working memory."""
        if self._salience_filter is None:
            return True
        scored = self._salience_filter.score(entry, self._agent_context)
        if not scored.promoted:
            if self._background_stream is not None:
                self._background_stream.add(scored)
            logger.debug(
                "AD-668: Entry demoted to background stream "
                "(score=%.3f, threshold=%.3f, category=%s)",
                scored.total,
                self._salience_filter._threshold,
                entry.category,
            )
            return False
        return True

    # ── Write API (called by all cognitive pathways) ──────────────

    def record_action(
        self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """Record an action the agent just took (any pathway)."""
        _meta = dict(metadata) if metadata else {}
        # AD-492: Attach correlation ID if active
        if self._correlation_id and "correlation_id" not in _meta:
            _meta["correlation_id"] = self._correlation_id
        entry = WorkingMemoryEntry(
            content=summary,
            category="action",
            source_pathway=source,
            metadata=_meta,
            knowledge_source=knowledge_source,
        )
        if not self._passes_salience_gate(entry):
            return
        if self._metabolism and not self._metabolism.triage(entry, self._recent_actions):
            logger.debug("AD-670 TRIAGE rejected action entry: %.60s...", summary)
            return
        self._recent_actions.append(entry)
        self._named_buffers["duty"].append(entry)

    def record_observation(
        self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """Record an observation from a proactive think or duty cycle."""
        entry = WorkingMemoryEntry(
            content=summary,
            category="observation",
            source_pathway=source,
            metadata=metadata or {},
            knowledge_source=knowledge_source,
        )
        if not self._passes_salience_gate(entry):
            return
        if self._metabolism and not self._metabolism.triage(entry, self._recent_observations):
            logger.debug("AD-670 TRIAGE rejected observation entry: %.60s...", summary)
            return
        self._recent_observations.append(entry)
        self._named_buffers["ship"].append(entry)

    def record_conversation(
        self, summary: str, *, partner: str, source: str,
        metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """Record a DM or Ward Room conversation exchange."""
        entry = WorkingMemoryEntry(
            content=summary,
            category="conversation",
            source_pathway=source,
            metadata={"partner": partner, **(metadata or {})},
            knowledge_source=knowledge_source,
        )
        if not self._passes_salience_gate(entry):
            return
        if self._metabolism and not self._metabolism.triage(entry, self._recent_conversations):
            logger.debug("AD-670 TRIAGE rejected conversation entry: %.60s...", summary)
            return
        self._recent_conversations.append(entry)
        self._named_buffers["social"].append(entry)

    def record_event(
        self, summary: str, *, source: str = "system",
        metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """Record a system event the agent should be aware of."""
        entry = WorkingMemoryEntry(
            content=summary,
            category="event",
            source_pathway=source,
            metadata=metadata or {},
            knowledge_source=knowledge_source,
        )
        if not self._passes_salience_gate(entry):
            return
        if self._metabolism and not self._metabolism.triage(entry, self._recent_events):
            logger.debug("AD-670 TRIAGE rejected event entry: %.60s...", summary)
            return
        self._recent_events.append(entry)
        self._named_buffers["ship"].append(entry)

    def record_reasoning(
        self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """AD-645: Record a composition brief or reasoning artifact from the cognitive chain."""
        entry = WorkingMemoryEntry(
            content=summary,
            category="reasoning",
            source_pathway=source,
            metadata=metadata or {},
            knowledge_source=knowledge_source,
        )
        if not self._passes_salience_gate(entry):
            return
        if self._metabolism and not self._metabolism.triage(entry, self._recent_reasoning):
            logger.debug("AD-670 TRIAGE rejected reasoning entry: %.60s...", summary)
            return
        self._recent_reasoning.append(entry)
        self._named_buffers["duty"].append(entry)

    def add_engagement(self, engagement: ActiveEngagement) -> None:
        """Register an active engagement (game, task, etc.)."""
        self._active_engagements[engagement.engagement_id] = engagement
        self._named_buffers["engagement"].append(WorkingMemoryEntry(
            content=engagement.summary,
            category="engagement",
            source_pathway="system",
            metadata={
                "engagement_id": engagement.engagement_id,
                "engagement_type": engagement.engagement_type,
            },
        ))

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
        if kwargs:
            summary_parts = [f"{key}={value}" for key, value in kwargs.items()]
            self._named_buffers["ship"].append(WorkingMemoryEntry(
                content=f"Cognitive state: {', '.join(summary_parts)}",
                category="cognitive_state",
                source_pathway="system",
            ))

    def get_cognitive_zone(self) -> str | None:
        """AD-588: Return cognitive zone if set via AD-573 sync."""
        return self._cognitive_state.get("zone")

    def set_telemetry_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        """AD-589: Cache telemetry snapshot for faithfulness cross-check."""
        self._last_telemetry_snapshot = snapshot

    def set_correlation_id(self, correlation_id: str) -> None:
        """AD-492: Set the current cognitive cycle's correlation ID."""
        self._correlation_id = correlation_id

    def get_correlation_id(self) -> str | None:
        """AD-492: Get the current cognitive cycle's correlation ID."""
        return self._correlation_id

    def clear_correlation_id(self) -> None:
        """AD-492: Clear correlation ID after cognitive cycle completes."""
        self._correlation_id = None

    def set_metabolism(self, metabolism: MemoryMetabolism) -> None:
        """AD-670: Attach a metabolism engine for active lifecycle management."""
        self._metabolism = metabolism

    def get_buffers(self) -> dict[str, deque[WorkingMemoryEntry]]:
        """AD-670: Expose internal buffers for metabolism operations."""
        return {
            "actions": self._recent_actions,
            "observations": self._recent_observations,
            "conversations": self._recent_conversations,
            "events": self._recent_events,
            "reasoning": self._recent_reasoning,
        }

    def run_metabolism_cycle(self) -> None:
        """AD-670: Run one metabolism cycle if metabolism is attached."""
        if self._metabolism is None:
            return
        self._metabolism.run_cycle(self.get_buffers())

    def record_conclusion(
        self,
        thread_id: str,
        conclusion_type: ConclusionType,
        summary: str,
        *,
        relevance_tags: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """AD-669: Record a conclusion reached by a cognitive thread."""
        if not summary or not summary.strip():
            return
        self._conclusions.append(ConclusionEntry(
            thread_id=thread_id,
            conclusion_type=conclusion_type,
            summary=summary.strip()[:200],
            relevance_tags=relevance_tags or [],
            correlation_id=correlation_id or self._correlation_id,
        ))

    def get_active_conclusions(
        self,
        *,
        exclude_thread: str | None = None,
        max_age_seconds: float = 1800.0,
    ) -> list[ConclusionEntry]:
        """AD-669: Get conclusions from sibling threads, excluding the caller's own."""
        now = time.time()
        return [
            conclusion for conclusion in self._conclusions
            if (now - conclusion.timestamp) < max_age_seconds
            and (exclude_thread is None or conclusion.thread_id != exclude_thread)
        ]

    def render_conclusions(
        self,
        *,
        exclude_thread: str | None = None,
        max_age_seconds: float = 1800.0,
        budget: int = 500,
    ) -> str:
        """AD-669: Render sibling conclusions for LLM context injection."""
        conclusions = self.get_active_conclusions(
            exclude_thread=exclude_thread,
            max_age_seconds=max_age_seconds,
        )
        if not conclusions:
            return ""

        lines = ["--- Sibling Thread Conclusions ---"]
        total_chars = len(lines[0])
        budget_chars = budget * CHARS_PER_TOKEN

        for conclusion in conclusions:
            age = self._format_age(time.time() - conclusion.timestamp)
            tags = f" [{', '.join(conclusion.relevance_tags)}]" if conclusion.relevance_tags else ""
            line = (
                f"  - [{conclusion.conclusion_type.value}] ({age} ago) "
                f"{conclusion.summary}{tags}"
            )
            if total_chars + len(line) > budget_chars:
                break
            lines.append(line)
            total_chars += len(line)

        if len(lines) == 1:
            return ""

        lines.append("--- End Sibling Conclusions ---")
        return "\n".join(lines)

    def pin_knowledge(
        self,
        fact: str,
        source: str,
        *,
        ttl_seconds: float | None = None,
        priority: int = 5,
    ) -> PinnedFact | None:
        """AD-579a: Pin a knowledge fact."""
        if self._pinned_knowledge is None:
            return None
        return self._pinned_knowledge.pin(
            fact,
            source,
            ttl_seconds=ttl_seconds,
            priority=priority,
        )

    def unpin_knowledge(self, fact_id: str) -> bool:
        """AD-579a: Unpin a knowledge fact by ID."""
        if self._pinned_knowledge is None:
            return False
        return self._pinned_knowledge.unpin(fact_id)

    @property
    def pinned_knowledge(self) -> list[PinnedFact]:
        """AD-579a: Read-only snapshot of pinned facts."""
        if self._pinned_knowledge is None:
            return []
        return self._pinned_knowledge.pins

    # ── Read API (called during context construction) ─────────────

    def render_context(self, *, budget: int | None = None) -> str:
        """Render the full working memory context for LLM injection.

        Budget-aware: evicts lowest-priority items if the rendered
        context exceeds the token budget. Returns empty string if
        nothing noteworthy in working memory.
        """
        effective_budget = budget or self._token_budget
        sections: list[tuple[int, str]] = []  # (priority, text)

        # Priority 0 (highest): Pinned knowledge — always include first
        if self._pinned_knowledge is not None:
            pin_text = self._pinned_knowledge.render_pins()
            if pin_text:
                sections.append((0, pin_text))

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

        # Priority 3: Recent reasoning — what I was thinking (AD-645)
        if self._recent_reasoning:
            reason_lines = ["Recent reasoning:"]
            for entry in self._recent_reasoning:
                age = self._format_age(entry.age_seconds())
                reason_lines.append(f"  - ({age} ago) {entry.content}")
            sections.append((3, "\n".join(reason_lines)))

        # Priority 4: Recent conversations — who I just talked to
        if self._recent_conversations:
            conv_lines = ["Recent conversations:"]
            for entry in self._recent_conversations:
                age = self._format_age(entry.age_seconds())
                partner = entry.metadata.get("partner", "unknown")
                conv_lines.append(f"  - ({age} ago) with {partner}: {entry.content}")
            sections.append((4, "\n".join(conv_lines)))

        # Priority 5: Recent observations — what I noticed
        if self._recent_observations:
            obs_lines = ["Recent observations:"]
            for entry in self._recent_observations:
                age = self._format_age(entry.age_seconds())
                _src_tag = f" [{entry.knowledge_source}]" if entry.knowledge_source != "unknown" else ""
                obs_lines.append(f"  - ({age} ago) {entry.content}{_src_tag}")
            sections.append((5, "\n".join(obs_lines)))

        # Priority 6: Sibling thread conclusions (AD-669)
        conclusion_text = self.render_conclusions()
        if conclusion_text:
            sections.append((6, conclusion_text))

        # Priority 7: Cognitive state — zone, cooldown
        if self._cognitive_state:
            state_parts = []
            if "zone" in self._cognitive_state:
                state_parts.append(f"Cognitive zone: {self._cognitive_state['zone']}")
            if "cooldown_reason" in self._cognitive_state:
                state_parts.append(f"Cooldown: {self._cognitive_state['cooldown_reason']}")
            if state_parts:
                sections.append((7, "Cognitive state: " + " | ".join(state_parts)))

        # Priority 8 (lowest): Recent events
        if self._recent_events:
            event_lines = ["Recent events:"]
            for entry in list(self._recent_events)[-5:]:
                event_lines.append(f"  - {entry.content}")
            sections.append((8, "\n".join(event_lines)))

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

    def render_buffers(
        self,
        names: list[str],
        *,
        budget: int | None = None,
    ) -> str:
        """AD-667: Render specific named buffers within a total token budget."""
        requested: list[NamedBuffer] = []
        for name in names:
            buffer = self._named_buffers.get(name)
            if buffer is None:
                logger.warning("AD-667: Unknown working memory buffer '%s'; skipping", name)
                continue
            requested.append(buffer)

        if not requested:
            return ""

        total_configured_budget = sum(buffer.token_budget for buffer in requested)
        if total_configured_budget <= 0:
            return ""
        effective_budget = budget if budget is not None else total_configured_budget

        rendered: list[str] = []
        for buffer in requested:
            allocated = int(effective_budget * (buffer.token_budget / total_configured_budget))
            buffer_text = buffer.render(budget=max(1, allocated))
            if buffer_text:
                rendered.append(buffer_text)

        if not rendered:
            return ""

        return "--- Working Memory ---\n" + "\n\n".join(rendered) + "\n--- End Working Memory ---"

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

    def has_thread_engagement(self, thread_id: str) -> bool:
        """BF-239: Check if agent has an active ward_room_reply engagement for a thread."""
        _key = f"ward_room:{thread_id}"
        return _key in self._active_engagements and \
            self._active_engagements[_key].engagement_type == "ward_room_reply"

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
            "recent_reasoning": [
                {"content": e.content, "category": e.category,
                 "source_pathway": e.source_pathway, "timestamp": e.timestamp,
                 "metadata": e.metadata, "knowledge_source": e.knowledge_source}
                for e in self._recent_reasoning
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
            "conclusions": [
                {
                    "thread_id": conclusion.thread_id,
                    "conclusion_type": conclusion.conclusion_type.value,
                    "summary": conclusion.summary,
                    "timestamp": conclusion.timestamp,
                    "relevance_tags": conclusion.relevance_tags,
                    "correlation_id": conclusion.correlation_id,
                }
                for conclusion in self._conclusions
            ],
            "background_stream_count": len(self._background_stream) if self._background_stream else 0,
            "named_buffers": {
                name: {
                    "name": buffer.name,
                    "token_budget": buffer.token_budget,
                    "entries": [
                        {"content": entry.content, "category": entry.category,
                         "source_pathway": entry.source_pathway, "timestamp": entry.timestamp,
                         "metadata": entry.metadata, "knowledge_source": entry.knowledge_source}
                        for entry in buffer.entries
                    ],
                }
                for name, buffer in self._named_buffers.items()
            },
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
        _restore_entries(data.get("recent_reasoning", []), wm._recent_reasoning)

        for raw_conclusion in data.get("conclusions", []):
            age = now - raw_conclusion.get("timestamp", 0)
            if age < stale_threshold_seconds:
                try:
                    wm._conclusions.append(ConclusionEntry(
                        thread_id=raw_conclusion.get("thread_id", ""),
                        conclusion_type=ConclusionType(
                            raw_conclusion.get("conclusion_type", "completion"),
                        ),
                        summary=raw_conclusion.get("summary", ""),
                        timestamp=raw_conclusion.get("timestamp", now),
                        relevance_tags=raw_conclusion.get("relevance_tags", []),
                        correlation_id=raw_conclusion.get("correlation_id"),
                    ))
                except (ValueError, KeyError):
                    pass

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

        for buffer_name, buffer_data in data.get("named_buffers", {}).items():
            buffer = wm._named_buffers.get(buffer_name)
            if buffer is None:
                continue
            buffer.token_budget = buffer_data.get("token_budget", buffer.token_budget)
            for raw in buffer_data.get("entries", []):
                age = now - raw.get("timestamp", 0)
                if age < stale_threshold_seconds:
                    buffer.append(WorkingMemoryEntry(
                        content=raw["content"],
                        category=raw.get("category", "unknown"),
                        source_pathway=raw.get("source_pathway", "restored"),
                        timestamp=raw.get("timestamp", now),
                        metadata=raw.get("metadata", {}),
                        knowledge_source=raw.get("knowledge_source", "unknown"),
                    ))

        # Add stasis awareness marker
        wm._recent_events.append(WorkingMemoryEntry(
            content="Restored from stasis — working memory reloaded",
            category="event",
            source_pathway="system",
        ))

        return wm
