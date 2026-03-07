"""Shared types for ProbOS."""

from __future__ import annotations

import uuid
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
