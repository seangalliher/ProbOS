"""Shared types for ProbOS."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
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
    ttl_seconds: float = 30.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


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
    max_tokens: int = 2048
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class LLMResponse:
    """Response from the LLM client."""

    content: str
    model: str = ""
    tier: str = "standard"
    tokens_used: int = 0
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


@dataclass
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
