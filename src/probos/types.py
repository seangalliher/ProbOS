"""Shared types for ProbOS."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
    event_log_window: float = 0.0    # Timestamp range for EventLog cross-verification

    # SOURCE PROVENANCE — where did the observed data originate? (AD-662)
    source_origin_id: str = ""       # ID of the root data artifact that generated this observation
    artifact_version: str = ""       # Version/hash of the artifact observed (detects same-version dupes)
    anomaly_window_id: str = ""      # If observed during a known anomaly window, its ID


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


@dataclass
class FederationMessage:
    """Wire protocol message between nodes."""

    type: str  # "intent_request", "intent_response", "gossip_self_model", "ping", "pong"
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
