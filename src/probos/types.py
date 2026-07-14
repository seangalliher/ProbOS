"""Shared types for ProbOS."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum, StrEnum
from typing import Any


AgentID = str


class AgentState(Enum):
    """Agent lifecycle states."""

    SPAWNING = "spawning"
    ACTIVE = "active"
    DEGRADED = "degraded"
    RECYCLING = "recycling"


class HandlerLatencyClass(StrEnum):
    """Expected execution cost for an intent handler."""

    DETERMINISTIC = "deterministic"
    NETWORK = "network"
    COGNITIVE = "cognitive"


@dataclass
class CapabilityDescriptor:
    """Semantic description of what an agent can do."""

    can: str
    detail: str = ""
    formats: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class AgentMeta:
    """Runtime statistics for an agent."""

    spawn_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success_count: int = 0
    failure_count: int = 0

    @property
    def total_operations(self) -> int:
        return self.success_count + self.failure_count


@dataclass
class IntentMessage:
    """A request broadcast into the mesh."""

    intent: str
    params: dict[str, Any] = field(default_factory=dict)
    urgency: float = 0.5
    context: str = ""
    ttl_seconds: float = 60.0  # raised from 30s for chain pipeline (5-step × LLM call)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    target_agent_id: str | None = None  # AD-397: if set, deliver only to this agent
    # AD-791a: chat-thread provenance for intents dispatched from chat
    # endpoints (1:1 DM, inline-callsign, vision). ``None`` for non-chat
    # dispatches (proactive scans, decomposer-spawned subtasks, federation
    # bridges, etc.). Distinct namespace from ``AnchorFrame.thread_id``
    # (Ward Room) — see the comment block at AnchorFrame.chat_thread_id.
    thread_id: str | None = None


@dataclass
class IntentResult:
    """An agent's response to an intent."""

    intent_id: str
    agent_id: AgentID
    success: bool
    result: Any = None
    error: str | None = None
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Priority(StrEnum):
    """Three-tier priority model (AD-637f).

    CRITICAL: Captain messages, @mentions, DMs — reserved LLM slots, bypass quality gates.
    NORMAL: Ward room participation, standard intents — default processing.
    LOW: Proactive think cycles — observability label only; uses same background
         semaphore as NORMAL. A functional deferral tier (third semaphore) would
         require its own AD.
    """
    CRITICAL = "critical"
    NORMAL = "normal"
    LOW = "low"

    @staticmethod
    def classify(
        *,
        intent: str = "",
        is_captain: bool = False,
        was_mentioned: bool = False,
    ) -> "Priority":
        """Classify priority from observation context (AD-637f).

        Single source of truth — used by both LLM scheduling (cognitive_agent.py)
        and NATS header emission (communication.py, runtime.py).

        Rules:
        - Captain-originated or @mentioned → CRITICAL
        - DMs (from anyone) → CRITICAL (conversational, latency-sensitive)
        - Proactive think → LOW (observability label; same semaphore as NORMAL)
        - Everything else → NORMAL
        """
        if is_captain or was_mentioned:
            return Priority.CRITICAL
        if intent == "direct_message":
            return Priority.CRITICAL
        if intent == "proactive_think":
            return Priority.LOW
        return Priority.NORMAL


@dataclass
class GossipEntry:
    """State snapshot shared via gossip protocol."""

    agent_id: AgentID
    agent_type: str
    state: AgentState
    capabilities: list[str] = field(default_factory=list)
    pool: str = ""
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sequence: int = 0


@dataclass
class ConnectionWeight:
    """Hebbian connection weight between two agents."""

    source_id: AgentID
    target_id: AgentID
    weight: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ------------------------------------------------------------------
# Phase 2: Consensus types
# ------------------------------------------------------------------


class ConsensusOutcome(Enum):
    """Result of a quorum vote."""

    APPROVED = "approved"
    REJECTED = "rejected"
    INSUFFICIENT = "insufficient"  # Not enough voters


@dataclass
class Vote:
    """A single agent's vote on a proposal."""

    agent_id: AgentID
    approved: bool
    confidence: float = 0.0
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class QuorumPolicy:
    """Configurable quorum requirements."""

    min_votes: int = 3
    approval_threshold: float = 0.6  # Fraction of weighted votes to approve
    use_confidence_weights: bool = True  # Weight votes by agent confidence

    def required_approvals(self) -> float:
        """Minimum weighted approval score needed."""
        return self.min_votes * self.approval_threshold


@dataclass
class ConsensusResult:
    """Outcome of a consensus round."""

    proposal_id: str
    outcome: ConsensusOutcome
    votes: list[Vote] = field(default_factory=list)
    weighted_approval: float = 0.0
    weighted_rejection: float = 0.0
    total_weight: float = 0.0
    policy: QuorumPolicy = field(default_factory=QuorumPolicy)
    shapley_values: dict[str, float] | None = None  # AD-224: per-agent Shapley attribution
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def approval_ratio(self) -> float:
        if self.total_weight == 0:
            return 0.0
        return self.weighted_approval / self.total_weight


@dataclass
class VerificationResult:
    """Result of a red team agent's independent verification."""

    verifier_id: AgentID
    target_agent_id: AgentID
    intent_id: str
    verified: bool
    expected: Any = None
    actual: Any = None
    discrepancy: str = ""
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ------------------------------------------------------------------
# Phase 3: Cognitive types
# ------------------------------------------------------------------


class LLMTier(Enum):
    """LLM routing tiers — trade cost/latency for capability."""

    FAST = "fast"  # Simple classification, single-intent parsing
    STANDARD = "standard"  # Multi-intent decomposition
    DEEP = "deep"  # Complex reasoning, ambiguous inputs


@dataclass
class LLMRequest:
    """A request to the LLM client."""

    prompt: str
    system_prompt: str = ""
    tier: str = "standard"  # LLMTier value
    temperature: float = 0.0
    top_p: float | None = None
    max_tokens: int = 2048
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # AD-543: Tool-aware completion (None preserves byte-for-byte text-only behaviour).
    tools: list[dict] | None = None
    tool_choice: str = "auto"
    # AD-720d (Wave 139): when set, takes precedence over ``prompt`` for multimodal turns.
    # The OpenAI-compatible client posts the array verbatim as the request's
    # ``messages`` field. None preserves the existing prompt-shape behaviour.
    messages: list[dict] | None = None


@dataclass
class LLMResponse:
    """Response from the LLM client."""

    content: str
    model: str = ""
    tier: str = "standard"
    tokens_used: int = 0
    prompt_tokens: int = 0       # AD-431: separate prompt token count
    completion_tokens: int = 0   # AD-431: separate completion token count
    cached: bool = False
    error: str | None = None
    request_id: str = ""
    # AD-543: Structured content blocks when tools are active (empty when text-only).
    content_blocks: list = field(default_factory=list)
    stop_reason: str = "stop"


class EscalationTier(Enum):
    """Escalation cascade levels."""

    RETRY = "retry"              # Tier 1: retry with a different agent
    ARBITRATION = "arbitration"  # Tier 2: ask the LLM to judge
    USER = "user"                # Tier 3: ask the user


@dataclass
class EscalationResult:
    """Outcome of an escalation attempt."""

    tier: EscalationTier
    resolved: bool                          # Did this tier resolve the issue?
    original_error: str = ""                # What triggered escalation
    resolution: Any = None                  # The successful result (if resolved)
    reason: str = ""                        # Human-readable explanation
    agent_id: str = ""                      # Which agent resolved it (Tier 1)
    attempts: int = 0                       # How many retry attempts were made
    user_approved: bool | None = None       # User's decision (Tier 3 only)
    tiers_attempted: list[EscalationTier] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict. Required because TaskNode gets serialized
        for workflow cache deep copy, episodic memory, working memory snapshots,
        and debug output."""
        return {
            "tier": self.tier.value,
            "resolved": self.resolved,
            "original_error": self.original_error,
            "resolution": str(self.resolution) if self.resolution is not None else None,
            "reason": self.reason,
            "agent_id": self.agent_id,
            "attempts": self.attempts,
            "user_approved": self.user_approved,
            "tiers_attempted": [t.value for t in self.tiers_attempted],
        }


@dataclass
class TaskNode:
    """A node in a task DAG — represents a single intent to execute."""

    id: str
    intent: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    use_consensus: bool = False
    background: bool = False
    result: Any = None
    status: str = "pending"  # pending, running, completed, failed
    escalation_result: dict | None = None  # Serialized EscalationResult via .to_dict()


@dataclass
class TaskDAG:
    """Directed acyclic graph of tasks parsed from natural language."""

    nodes: list[TaskNode] = field(default_factory=list)
    source_text: str = ""
    response: str = ""  # Conversational reply from LLM for non-actionable inputs
    reflect: bool = False  # Whether to send results back to LLM for synthesis
    capability_gap: bool = False  # LLM says no intent can handle this task
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def get_ready_nodes(self) -> list[TaskNode]:
        """Return nodes whose dependencies are all completed."""
        completed = {n.id for n in self.nodes if n.status == "completed"}
        return [
            n for n in self.nodes
            if n.status == "pending" and all(d in completed for d in n.depends_on)
        ]

    def is_complete(self) -> bool:
        return all(n.status in ("completed", "failed") for n in self.nodes)

    def get_node(self, node_id: str) -> TaskNode | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None


# ------------------------------------------------------------------
# Phase 3b: Episodic memory types
# ------------------------------------------------------------------


class EpisodeDuplicatePolicy(StrEnum):
    """Policy for classifying an authoritative same-ID episode."""

    UNEXPECTED = "unexpected"
    EXPECT_SAME_REFLECTION = "expect_same_reflection"


class EpisodeStoreOutcome(StrEnum):
    """Result of an episodic primary-store attempt."""

    STORED = "stored"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"


class MemorySource(str, Enum):
    """Classification of how an episode entered an agent's memory (AD-541)."""
    DIRECT = "direct"            # Agent personally experienced this
    SECONDHAND = "secondhand"    # Heard about it in Ward Room / DM from another agent
    SHIP_RECORDS = "ship_records"  # Read from Ship's Records (AD-434, future)
    BRIEFING = "briefing"        # Received during onboarding (AD-486, future)
    REFLECTION = "reflection"    # AD-599: Synthesized from dream consolidation insights


@dataclass(frozen=True)
class AnchorFrame:
    """Contextual anchors grounding an episode in ship reality (AD-567a).

    Inspired by Johnson's Source Monitoring Framework — the qualitative
    characteristics that distinguish genuine memory from confabulation.
    SEEM's Episodic Event Frame pattern — typed structure, not flat metadata.
    """

    # TEMPORAL — when did this happen?
    duty_cycle_id: str = ""          # Links to duty assignment if from duty cycle
    watch_section: str = ""          # e.g., "alpha", "beta" — temporal context
    sequence_index: int = 0          # AD-577: intra-cycle ordering (monotonic within a batch)
    source_timestamp: float = 0.0    # AD-577: original event time (e.g. WR post created_at)

    # SPATIAL — where in the ship did this happen?
    channel: str = ""                # "ward_room", "dm", "duty_report", "dag", "feedback", "smoke_test"
    channel_id: str = ""             # Specific Ward Room channel or thread ID
    department: str = ""             # Agent's department at time of episode

    # SOCIAL — who was involved?
    participants: list[str] = field(default_factory=list)  # Callsigns present/involved
    trigger_agent: str = ""          # Callsign of agent/entity that triggered this episode

    # CAUSAL — why did this happen?
    trigger_type: str = ""           # "duty_cycle", "proactive_think", "direct_message", etc.

    # EVIDENTIAL — what corroborates this?
    thread_id: str = ""              # Ward Room thread ID for cross-reference
    # AD-791a: chat-thread provenance for episodes originating from chat
    # turns (1:1 DM via routers/agents.py, inline-callsign + vision via
    # routers/chat.py, cognitive-layer DM reply pipeline). ``""`` for
    # non-chat episodes (proactive scans, dream consolidation, action
    # dispatches outside a chat turn, etc.).
    #
    # DELIBERATELY SEPARATE NAMESPACE from ``thread_id`` above. The
    # Ward Room field is for inter-channel cross-reference within the
    # Ward Room subsystem; ``chat_thread_id`` is for the chat-thread
    # substrate (probos.threads.ChatThreadStore — see AD-791). Merging
    # them would silently conflate two distinct ID spaces and break
    # cross-thread recall ranking in future AD-810 work. Future
    # contributors: add a NEW field; do NOT reuse either.
    chat_thread_id: str = ""
    event_log_window: float = 0.0    # Timestamp range for EventLog cross-verification

    # AD-987: visual<->conversational binding — the frame the agent SAW at capture.
    # Binds the otherwise-separate visual stream into the conversational episode so
    # recall is integrated ("what was said" + "what I saw" as one memory). The ref is
    # a content-addressable AttachmentStore SHA-256 (AD-731), so the frame survives
    # the VisionWorkingMemory ring's TTL reap. Both "" unless
    # ``memory.episode_visual_binding_enabled`` is on at store time.
    visual_attachment_ref: str = ""  # SHA-256 of the bound frame in AttachmentStore
    visual_description: str = ""     # vision-LLM description at capture time

    # SOURCE PROVENANCE — where did the observed data originate? (AD-662)
    source_origin_id: str = ""       # ID of the root data artifact that generated this observation
    artifact_version: str = ""       # Version/hash of the artifact observed (detects same-version dupes)
    anomaly_window_id: str = ""      # If observed during a known anomaly window, its ID
    # AD-579b: Temporal validity for anchor-scoped facts
    temporal_validity_start: float = 0.0  # epoch; 0.0 = anchor creation time
    temporal_validity_end: float = 0.0    # epoch; 0.0 = no expiry


@dataclass(frozen=True)
class RecallScore:
    """Salience-weighted recall result combining multiple ranking signals (AD-567b/c).

    Returned by EpisodicMemory.recall_weighted() — wraps an Episode with
    composite scoring from semantic similarity, keyword hits, trust, Hebbian
    weight, recency, and anchor confidence (Johnson-weighted).
    """
    episode: Episode
    semantic_similarity: float = 0.0   # 0.0–1.0, from ChromaDB cosine distance
    keyword_hits: int = 0              # FTS5 match count (0 if no keyword match)
    trust_weight: float = 0.5          # agent trust score (0.0–1.0)
    hebbian_weight: float = 0.5        # intent-agent Hebbian weight (0.0–1.0)
    recency_weight: float = 0.0        # exponential decay by age
    anchor_confidence: float = 0.0     # 0.0–1.0, Johnson-weighted anchor confidence (AD-567c)
    tcm_similarity: float = 0.0        # AD-601: TCM temporal context similarity
    composite_score: float = 0.0       # weighted combination of all signals


def dominant_match_reason(rs: RecallScore) -> str:
    """AD-988: Name the dominant retrieval signal behind a ``RecallScore``.

    Pure, deterministic, no I/O. Returns a short human-readable phrase
    answering *why* a fragment was recalled — the Counselor's 2026-06-13
    "I can tell it's reaching but not why" gap. The Oracle collapses the
    full breakdown to one scalar (``composite_score``); this projects the
    dominant axis back out for transparency.

    Heuristic (in priority order):
      1. ``keyword_hits > 0`` ⇒ ``"keyword match (<n> hit[s])"``. Lexical /
         FTS5 is the strongest *explicit* signal, so it wins outright even
         when a graded signal is numerically larger.
      2. Otherwise pick the MAX among the normalized [0,1] match signals and
         name it with its value, e.g. ``"semantic similarity (0.83)"``:
         ``semantic_similarity`` → ``"semantic similarity"``,
         ``hebbian_weight`` → ``"Hebbian co-activation"``,
         ``anchor_confidence`` → ``"anchored context"``,
         ``recency_weight`` → ``"recency"``,
         ``tcm_similarity`` → ``"temporal context"``.
         ``trust_weight`` is EXCLUDED — it is a weighting, not a match reason.
         Ties resolve to the first signal in the order above (stable).
      3. Every graded match signal ``<= 0.0`` ⇒ ``"weak/ambiguous match"``
         (the degenerate "it's reaching" case).
    """
    if rs.keyword_hits > 0:
        plural = "s" if rs.keyword_hits != 1 else ""
        return f"keyword match ({rs.keyword_hits} hit{plural})"
    candidates: tuple[tuple[str, float], ...] = (
        ("semantic similarity", rs.semantic_similarity),
        ("Hebbian co-activation", rs.hebbian_weight),
        ("anchored context", rs.anchor_confidence),
        ("recency", rs.recency_weight),
        ("temporal context", rs.tcm_similarity),
    )
    best_label = ""
    best_value = 0.0
    for label, value in candidates:
        if value > best_value:
            best_value = value
            best_label = label
    if not best_label:
        return "weak/ambiguous match"
    return f"{best_label} ({best_value:.2f})"


@dataclass(frozen=True)
class MemoryRef:
    """AD-462f: Lightweight projection of an OracleResult — retrieval-as-pointers.

    A ``MemoryRef`` is the surface representation of a memory-tier hit:
    enough information to render a one-line preview in a prompt and to
    resolve the full ``OracleResult`` later via
    ``OracleService.resolve_ref(ref_id)``. Refs are token-efficient (≤200
    char snippet vs. full content), stable within an OracleService
    instance's LRU cache lifetime, and hashable so consumers can dedupe.

    See ``decisions-era-4-evolution.md`` AD-462f for design rationale and
    the deferral chain (462f-b/c/d).
    """

    ref_id: str               # f"{tier}:{stable_key}" — see AD-462f DLog #3
    tier: str                 # "episodic" | "records" | "operational" | "archive" | "semantic" | "graph" | "health"
    score: float              # 0.0–1.0 (mirrors OracleResult.score)
    snippet: str              # ≤200 chars (truncated content preview)
    provenance: str           # human-readable tag (e.g. "[episodic memory]")
    timestamp: float = 0.0    # original event timestamp (0.0 if tier-irrelevant)
    # AD-462f DLog #12: metadata is excluded from hash/eq so the dataclass
    # remains hashable despite carrying a dict. Identity is driven by
    # (ref_id, tier, score, snippet, provenance, timestamp) — same-ref_id
    # refs from the same query compare equal regardless of metadata churn.
    metadata: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


# AD-873: Ebbinghaus memory decay — default stability (decay time-constant, in
# seconds) for a freshly-encoded episode. Sized so a brand-new memory barely
# decays over a day: S(t)=e^(-t/stability), so over 86_400s (one day) a fresh
# memory retains e^(-86400/1_728_000)=e^(-0.05) ~= 0.95 of its strength. Grows
# on reinforced recall/replay (spaced repetition) so revisited memories decay
# slower. 1_728_000s = 20 days.
EBBINGHAUS_DEFAULT_STABILITY_SECONDS: float = 1_728_000.0


@dataclass(frozen=True)
class Episode:
    """A recorded episode from the cognitive pipeline."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = 0.0
    user_input: str = ""
    dag_summary: dict[str, Any] = field(default_factory=dict)
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    reflection: str | None = None
    agent_ids: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    embedding: list[float] = field(default_factory=list)
    shapley_values: dict[str, float] = field(default_factory=dict)
    trust_deltas: list[dict[str, Any]] = field(default_factory=list)
    # AD-541: Memory integrity fields
    source: str = "direct"       # MemorySource value — how this episode was acquired
    # AD-567a: Contextual anchors grounding this episode in ship reality
    anchors: AnchorFrame | None = None
    # AD-598: Importance scoring at encoding — selective retention signal
    importance: int = 5  # 1-10 scale, 5 = neutral
    # AD-492: Cognitive cycle correlation ID for cross-layer trace threading
    correlation_id: str = ""
    # AD-579b: Temporal validity windows — when is this episode's content valid?
    valid_from: float = 0.0    # epoch timestamp; 0.0 = episode.timestamp (creation time)
    valid_until: float = 0.0   # epoch timestamp; 0.0 = no expiry (valid forever)
    # AD-871: Provenance-aware memory envelope — graded belief, not flat truth.
    source_type: str = ""      # graded origin: user_statement|tool_result|observation|external|agent_inference|reflection ("" = back-fill from source at store time)
    confidence: float = 1.0    # store-time belief strength (0.0–1.0); derived from source_type when graded, else caller-authoritative
    verification_count: int = 0  # how many independent corroborations have been observed
    contradicted_by: list[str] = field(default_factory=list)  # episode ids that contradict this record
    # AD-873: Ebbinghaus memory decay — strength decays over time, stability slows decay.
    strength: float = 1.0  # current retention strength S(t) in [0,1]; 1.0 = freshly encoded
    stability: float = EBBINGHAUS_DEFAULT_STABILITY_SECONDS  # decay time-constant (s); grows on reinforced recall/replay
    # AD-979f: affective-salience retrieval slot [0,1]; 0.0 = neutral. Populated by a
    # deferred capture AD; consumed by the AD-873 reranker's affect term (off by
    # default → byte-identical). NOT measured affect yet — the storage slot.
    affect_salience: float = 0.0


# ------------------------------------------------------------------
# AD-871: Provenance-aware memory envelope — graded-belief constants/helpers
# ------------------------------------------------------------------

# Graded ``source_type`` -> store-time default confidence (belief strength).
SOURCE_TYPE_CONFIDENCE: dict[str, float] = {
    "user_statement": 1.0,
    "tool_result": 1.0,
    "observation": 0.8,
    "external": 0.8,
    "agent_inference": 0.5,
    "reflection": 0.5,
}

# Confidence used when a ``source_type`` is unknown/unmapped.
DEFAULT_PROVENANCE_CONFIDENCE: float = 1.0

# Back-fill map: legacy ``Episode.source`` (MemorySource value) -> graded source_type.
SOURCE_TO_SOURCE_TYPE: dict[str, str] = {
    "direct": "observation",       # agent personally observed it
    "secondhand": "agent_inference",  # heard about it from another agent
    "ship_records": "external",    # read from ship's records
    "briefing": "external",        # received during onboarding
    "reflection": "reflection",    # synthesized during dream consolidation
}

# ``source_type`` used when a legacy ``source`` tag is unrecognized.
DEFAULT_SOURCE_TYPE: str = "observation"


def resolve_provenance(source: str, source_type: str, confidence: float) -> tuple[str, float]:
    """AD-871: Resolve graded provenance ``(source_type, confidence)`` at store time.

    Back-fills an empty ``source_type`` from the legacy ``source`` origin tag.
    When the caller opted into a graded ``source_type`` but left ``confidence``
    at the neutral default (1.0), the confidence is derived from
    ``SOURCE_TYPE_CONFIDENCE``. Caller-provided non-default confidence and
    pre-AD-871 episodes (empty ``source_type``) are never silently downgraded —
    "store raw, never derived".
    """
    resolved_type = source_type or SOURCE_TO_SOURCE_TYPE.get(source or "direct", DEFAULT_SOURCE_TYPE)
    if source_type and confidence == 1.0:
        resolved_conf = SOURCE_TYPE_CONFIDENCE.get(resolved_type, DEFAULT_PROVENANCE_CONFIDENCE)
    else:
        resolved_conf = confidence
    return resolved_type, resolved_conf


def mark_contradicted(episode: Episode, contradicting_id: str) -> Episode:
    """AD-871: Return a copy of ``episode`` with ``contradicting_id`` appended to
    ``contradicted_by`` (frozen-safe via ``dataclasses.replace``).

    Duplicate or empty ids are a no-op (the same episode is returned).
    """
    if not contradicting_id or contradicting_id in episode.contradicted_by:
        return episode
    return replace(
        episode, contradicted_by=[*episode.contradicted_by, contradicting_id]
    )


# ------------------------------------------------------------------
# Phase 3b-2: Attention types
# ------------------------------------------------------------------


@dataclass
class AttentionEntry:
    """A task competing for attention resources."""

    task_id: str
    intent: str
    urgency: float = 0.5
    relevance: float = 1.0
    deadline_factor: float = 1.0
    dependency_depth: int = 0
    is_background: bool = False
    score: float = 0.0  # Computed by AttentionManager
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: float = 30.0


@dataclass
class FocusSnapshot:
    """A snapshot of attention focus at a point in time."""

    keywords: list[str] = field(default_factory=list)
    context: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ------------------------------------------------------------------
# Phase 3b-3: Dreaming types
# ------------------------------------------------------------------


@dataclass
class DreamReport:
    """Result of a single dream cycle."""

    episodes_replayed: int = 0
    weights_strengthened: int = 0
    weights_pruned: int = 0
    trust_adjustments: int = 0
    pre_warm_intents: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    clusters_found: int = 0  # AD-531 (replaces strategies_extracted)
    clusters: list[Any] = field(default_factory=list)  # AD-531: EpisodeCluster objects
    procedures_extracted: int = 0  # AD-532
    chain_procedures_extracted: int = 0  # AD-632g: chain-compiled procedures
    procedures: list[Any] = field(default_factory=list)  # AD-532: Procedure objects
    procedures_evolved: int = 0  # AD-532b
    negative_procedures_extracted: int = 0  # AD-532c
    failure_patterns_extracted: int = 0  # AD-609
    comparative_insights: int = 0  # AD-609
    proactive_evolutions: int = 0  # AD-532e: procedures evolved by proactive scan
    reactive_flags: int = 0        # AD-532e: extraction candidates flagged by reactive trigger
    fallback_evolutions: int = 0   # AD-534b: procedures evolved from fallback learning evidence
    fallback_events_processed: int = 0  # AD-534b: total fallback events processed in dream cycle
    gaps_predicted: int = 0
    contradictions_found: int = 0  # AD-403
    # AD-537: Observational learning
    procedures_observed: int = 0
    observation_threads_scanned: int = 0
    teaching_dms_processed: int = 0
    # AD-538: Procedure lifecycle
    procedures_decayed: int = 0
    procedures_archived: int = 0
    dedup_candidates_found: int = 0
    # AD-539: Gap → Qualification Pipeline
    gaps_classified: int = 0
    qualification_paths_triggered: int = 0
    gap_reports_generated: int = 0
    # AD-557: Emergence metrics
    emergence_capacity: float | None = None
    coordination_balance: float | None = None
    groupthink_risk: bool = False
    fragmentation_risk: bool = False
    tom_effectiveness: float | None = None
    # AD-551: Notebook consolidation
    notebook_consolidations: int = 0
    notebook_entries_archived: int = 0
    convergence_reports_generated: int = 0
    convergence_reports: list[Any] = field(default_factory=list)
    # AD-555: Notebook quality
    notebook_quality_score: float | None = None
    notebook_quality_agents: int = 0
    # AD-563: Knowledge linting
    lint_score: float | None = None
    lint_issues_found: int = 0
    # AD-564: Forced consolidation
    forced_consolidations: int = 0
    # AD-541c: Spaced Retrieval Therapy
    retrieval_practices: int = 0
    retrieval_accuracy: float | None = None
    retrieval_concerns: int = 0
    # AD-569: Behavioral metrics
    behavioral_quality_score: float | None = None
    frame_diversity_score: float | None = None
    synthesis_rate: float | None = None
    cross_dept_trigger_rate: float | None = None
    anchor_grounded_rate: float | None = None
    # AD-567d: Activation-based memory lifecycle
    activation_pruned: int = 0
    activation_reinforced: int = 0
    # AD-568d: Source attribution consolidation
    source_attribution: dict[str, Any] = field(default_factory=dict)
    # AD-568e: Faithfulness verification
    mean_faithfulness_score: float | None = None
    unfaithful_episodes: int = 0
    # AD-599: Reflection episodes promoted from dream insights
    reflections_created: int = 0
    # AD-671: Dream-Working Memory bridge
    wm_entries_flushed: int = 0
    bridged_procedures: int = 0  # AD-572: cross-cycle procedural bridge
    wm_priming_entries: int = 0
    # AD-690: Dream Step 7i — Relationship inference (titled "Dream Step 10" in spec/issue)
    inferred_relationships: int = 0
    relationship_pairs_rejected: int = 0
    relationship_pairs_capped: int = 0


# ------------------------------------------------------------------
# Phase 3b-5: Workflow cache types
# ------------------------------------------------------------------


@dataclass
class WorkflowCacheEntry:
    """A cached workflow pattern for fast replay."""

    pattern: str  # normalized user input (lowercase, stripped)
    dag_json: str  # serialized TaskDAG JSON
    hit_count: int = 0
    last_hit: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ------------------------------------------------------------------
# Phase 6b: Dynamic intent discovery types
# ------------------------------------------------------------------


@dataclass
class IntentDescriptor:
    """Structured metadata declaring an intent an agent can handle.

    Used by the PromptBuilder to dynamically assemble the decomposer's
    system prompt from whatever agents are registered.
    """

    name: str  # e.g. "read_file"
    params: dict[str, str] = field(default_factory=dict)  # param name → description
    description: str = ""  # e.g. "Read file contents"
    requires_consensus: bool = False
    requires_reflect: bool = False
    tier: str = "domain"  # "core", "utility", or "domain"
    # AD-983a: optional AGENT-FACING invocation manual. ``description`` serves
    # the decomposer (planning); ``usage_hint`` serves a crew agent at reply
    # time (how to reach this capability via the mesh) — exactly like a Copilot
    # tool's self-description. Declared once on the capability; the
    # ``CognitiveAgent`` base composes the hints of all live, reachable
    # capabilities into every crew agent's conversational prompt, so no agent's
    # behavior rules have to teach "how to use" what it holds. Empty = not
    # surfaced as a self-serve affordance. Only declare a ``[MESH ...]`` form
    # on an intent the AD-869 do-and-report seam actually backs.
    usage_hint: str = ""


@dataclass
class Skill:
    """A modular intent handler that can be attached to an agent.

    Unlike a full agent (which has its own pool, lifecycle, and identity),
    a skill is a piece of code that extends an existing agent's capabilities.
    The agent discovers its skills via its _skills list and dispatches
    matching intents to the skill's handler.
    """

    name: str  # Intent name this skill handles, e.g., "translate_text"
    descriptor: IntentDescriptor  # Intent metadata for decomposer
    source_code: str  # Python source of the handler function
    handler: Callable[..., Awaitable] | None = None  # Compiled async callable
    created_at: float = 0.0
    origin: str = "designed"  # "designed" or "built_in"


# ------------------------------------------------------------------
# Phase 9: Federation types
# ------------------------------------------------------------------


@dataclass
class NodeSelfModel:
    """A node's self-assessment of its capabilities and health (Nooplex Psi).

    Broadcast to peers via gossip so they can make routing decisions.
    """

    node_id: str
    capabilities: list[str] = field(default_factory=list)
    pool_sizes: dict[str, int] = field(default_factory=dict)
    agent_count: int = 0
    health: float = 0.0
    uptime_seconds: float = 0.0
    timestamp: float = 0.0


# ------------------------------------------------------------------
# AD-750: Semantic work layer entity models (personal data model)
# ------------------------------------------------------------------


@dataclass
class SemanticEntity:
    """Base for all work semantics (personal data model)."""

    id: str  # UUID
    entity_type: str  # "task" | "meeting" | "commitment" | "thread" | "document"
    owner_id: str  # Captain's local identifier
    created_at: datetime
    modified_at: datetime
    content: str  # plaintext/reference (not full doc body)


@dataclass
class Task(SemanticEntity):
    """A personal task tracked by Yeo and crew agents."""

    title: str = ""
    due_date: datetime | None = None
    completed: bool = False
    delegated_to_agent: str | None = None  # "OutlookAgent", "ArchitectAgent", etc.
    priority: int = 1  # 1–5 scale


@dataclass
class Meeting(SemanticEntity):
    """A calendar meeting entry."""

    title: str = ""
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attendees: list[str] = field(default_factory=list)
    location: str | None = None


@dataclass
class Commitment(SemanticEntity):
    """A crew commitment — what the assistant committed to deliver."""

    description: str = ""
    deadline: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    stake_agent: str = ""  # who holds the commitment
    status: str = "open"  # "open" | "in_progress" | "completed" | "blocked"


@dataclass
class WorkThread(SemanticEntity):
    """A conversation/work thread with related tasks and meetings."""

    topic: str = ""
    messages: list[dict] = field(default_factory=list)
    related_tasks: list[str] = field(default_factory=list)
    related_meetings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------


@dataclass
class FederationMessage:
    """Wire protocol message between nodes."""

    type: str  # "intent_request", "intent_response", "gossip_self_model", "ping", "pong",
    # AD-443e: "transfer_request", "transfer_response", "chain_request", "chain_response"
    source_node: str
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass
class QAReport:
    """Result of a smoke-test run for a designed agent (AD-399: moved from system_qa)."""

    agent_type: str
    intent_name: str
    pool_name: str
    total_tests: int
    passed: int
    failed: int
    pass_rate: float
    verdict: str  # "passed" | "failed" | "error"
    test_details: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: float = 0.0
