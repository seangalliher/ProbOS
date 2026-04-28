"""Typed event system (AD-527).

Provides a formal registry of all ProbOS event types and typed dataclasses
for high-traffic event domains.  Backward-compatible — existing dict consumers
still work via the ``str, Enum`` identity (``EventType.X == "x"`` is True).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Event type registry
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """Registry of all ProbOS event types.

    Grouped by domain.  The string value matches the existing event type
    strings for backward compatibility with HXI WebSocket consumers.
    """

    # Build pipeline
    BUILD_QUEUE_ITEM = "build_queue_item"
    BUILD_QUEUE_UPDATE = "build_queue_update"
    BUILD_STARTED = "build_started"
    BUILD_PROGRESS = "build_progress"
    BUILD_GENERATED = "build_generated"
    BUILD_RESOLVED = "build_resolved"
    BUILD_SUCCESS = "build_success"
    BUILD_FAILURE = "build_failure"

    # Self-modification
    SELF_MOD_STARTED = "self_mod_started"
    SELF_MOD_IMPORT_APPROVED = "self_mod_import_approved"
    SELF_MOD_PROGRESS = "self_mod_progress"
    SELF_MOD_SUCCESS = "self_mod_success"
    SELF_MOD_RETRY_COMPLETE = "self_mod_retry_complete"
    SELF_MOD_FAILURE = "self_mod_failure"

    # Design pipeline
    DESIGN_STARTED = "design_started"
    DESIGN_PROGRESS = "design_progress"
    DESIGN_GENERATED = "design_generated"
    DESIGN_FAILURE = "design_failure"

    # Trust & routing
    TRUST_UPDATE = "trust_update"
    HEBBIAN_UPDATE = "hebbian_update"
    CONSENSUS = "consensus"

    # Transporter / builder
    TRANSPORTER_ASSEMBLED = "transporter_assembled"
    TRANSPORTER_VALIDATED = "transporter_validated"
    TRANSPORTER_DECOMPOSED = "transporter_decomposed"
    TRANSPORTER_WAVE_START = "transporter_wave_start"
    TRANSPORTER_CHUNK_DONE = "transporter_chunk_done"
    TRANSPORTER_EXECUTION_DONE = "transporter_execution_done"

    # Ward Room
    WARD_ROOM_PRUNED = "ward_room_pruned"
    WARD_ROOM_THREAD_CREATED = "ward_room_thread_created"
    WARD_ROOM_THREAD_UPDATED = "ward_room_thread_updated"
    WARD_ROOM_POST_CREATED = "ward_room_post_created"
    WARD_ROOM_ENDORSEMENT = "ward_room_endorsement"

    # Dream / system mode
    SYSTEM_MODE = "system_mode"
    CAPABILITY_GAP_PREDICTED = "capability_gap_predicted"

    # Agent lifecycle
    AGENT_STATE = "agent_state"
    AGENT_CAPACITY_APPROACHING = "agent_capacity_approaching"

    # Assignments
    ASSIGNMENT_CREATED = "assignment_created"
    ASSIGNMENT_UPDATED = "assignment_updated"
    ASSIGNMENT_COMPLETED = "assignment_completed"

    # Work items / workforce
    WORK_ITEM_CREATED = "work_item_created"
    WORK_ITEM_UPDATED = "work_item_updated"
    WORK_ITEM_STATUS_CHANGED = "work_item_status_changed"
    WORK_ITEM_ASSIGNED = "work_item_assigned"
    WORK_ITEM_CLAIMED = "work_item_claimed"
    BOOKING_STARTED = "booking_started"
    BOOKING_COMPLETED = "booking_completed"
    BOOKING_CANCELLED = "booking_cancelled"

    # Scheduled tasks
    SCHEDULED_TASK_CREATED = "scheduled_task_created"
    SCHEDULED_TASK_CANCELLED = "scheduled_task_cancelled"
    SCHEDULED_TASK_DAG_RESUMED = "scheduled_task_dag_resumed"
    SCHEDULED_TASK_FIRED = "scheduled_task_fired"
    SCHEDULED_TASK_UPDATED = "scheduled_task_updated"
    SCHEDULED_TASK_DAG_STALE = "scheduled_task_dag_stale"

    # Notifications / tasks
    NOTIFICATION = "notification"
    NOTIFICATION_ACK = "notification_ack"
    NOTIFICATION_SNAPSHOT = "notification_snapshot"
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"

    # Initiative
    INITIATIVE_PROPOSAL = "initiative_proposal"

    # NL pipeline (decomposer on_event callback chain)
    DECOMPOSE_START = "decompose_start"
    DECOMPOSE_COMPLETE = "decompose_complete"

    # Bridge
    BRIDGE_ALERT = "bridge_alert"
    PROACTIVE_THOUGHT = "proactive_thought"

    # Counselor / Cognitive Health (AD-503)
    CIRCUIT_BREAKER_TRIP = "circuit_breaker_trip"
    DREAM_COMPLETE = "dream_complete"
    COUNSELOR_ASSESSMENT = "counselor_assessment"
    SELF_MONITORING_CONCERN = "self_monitoring_concern"  # AD-506a: amber zone
    ZONE_RECOVERY = "zone_recovery"  # AD-506b: agent zone improved
    PEER_REPETITION_DETECTED = "peer_repetition_detected"  # AD-506b
    TASK_EXECUTION_COMPLETE = "task_execution_complete"  # AD-532e: reactive trigger
    PROCEDURE_FALLBACK_LEARNING = "procedure_fallback_learning"  # AD-534b: fallback evidence
    GAP_IDENTIFIED = "gap_identified"  # AD-539: gap → qualification pipeline
    TRUST_CASCADE_WARNING = "trust_cascade_warning"  # AD-558: trust cascade breaker tripped
    EMERGENCE_METRICS_UPDATED = "emergence_metrics_updated"  # AD-557: emergence snapshot computed
    GROUPTHINK_WARNING = "groupthink_warning"  # AD-557: redundancy dominates
    FRAGMENTATION_WARNING = "fragmentation_warning"  # AD-557: synergy near zero
    BEHAVIORAL_METRICS_UPDATED = "behavioral_metrics_updated"  # AD-569: behavioral snapshot computed
    GAME_COMPLETED = "game_completed"  # AD-526a: Game finished
    GAME_UPDATE = "game_update"  # AD-526b: game state changed (move made)
    LLM_HEALTH_CHANGED = "llm_health_changed"  # BF-069: LLM proxy status transition
    CONVERGENCE_DETECTED = "convergence_detected"  # AD-551: cross-agent convergence
    DIVERGENCE_DETECTED = "divergence_detected"  # AD-554: cross-agent divergence
    NOTEBOOK_SELF_REPETITION = "notebook_self_repetition"  # AD-552: notebook self-repetition
    NOTEBOOK_QUALITY_UPDATED = "notebook_quality_updated"  # AD-555: quality snapshot computed
    RETRIEVAL_PRACTICE_CONCERN = "retrieval_practice_concern"  # AD-541c: recall failure streak
    REMINISCENCE_SESSION_COMPLETE = "reminiscence_session_complete"  # AD-541d: guided reminiscence
    QUALIFICATION_TEST_COMPLETE = "qualification_test_complete"  # AD-566a
    QUALIFICATION_BASELINE_SET = "qualification_baseline_set"  # AD-566a
    QUALIFICATION_DRIFT_DETECTED = "qualification_drift_detected"  # AD-566c
    QUALIFICATION_GATE_BLOCKED = "qualification_gate_blocked"  # AD-595e
    CASCADE_CONFABULATION_DETECTED = "cascade_confabulation_detected"  # AD-567f
    CONTENT_CONTAGION_FLAGGED = "content_contagion_flagged"  # AD-529
    CONTENT_QUARANTINE_RECOMMENDED = "content_quarantine_recommended"  # AD-529
    CONFABULATION_SUPPRESSED = "confabulation_suppressed"  # BF-206
    # Communication register
    REGISTER_SHIFT_GRANTED = "register_shift_granted"    # AD-653
    REGISTER_SHIFT_DENIED = "register_shift_denied"      # AD-653
    CORROBORATION_VERIFIED = "corroboration_verified"  # AD-567f
    CORROBORATION_PROVENANCE_VALIDATED = "corroboration_provenance_validated"  # AD-665
    WRONG_CONVERGENCE_DETECTED = "wrong_convergence_detected"  # AD-583
    WARD_ROOM_ECHO_DETECTED = "ward_room_echo_detected"  # AD-583g
    OBSERVABLE_STATE_MISMATCH = "observable_state_mismatch"  # AD-583f
    SELF_MODEL_DRIFT = "self_model_drift"  # AD-589: introspective confabulation detected
    DM_CONVERGENCE_DETECTED = "dm_convergence_detected"  # AD-623: DM thread converged
    SENSORIUM_BUDGET_EXCEEDED = "sensorium_budget_exceeded"  # AD-666: sensorium injection over char threshold
    TOOL_PERMISSION_DENIED = "tool_permission_denied"  # AD-423b: agent lacks tool permission
    TOOL_LOCKED = "tool_locked"  # AD-423b: LOTO lock acquired
    TOOL_UNLOCKED = "tool_unlocked"  # AD-423b: LOTO lock released
    TOOL_CONTEXT_CREATED = "tool_context_created"  # AD-423c: fired during onboarding
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"  # AD-585: tiered knowledge load
    KNOWLEDGE_CONFIRMED = "knowledge_confirmed"  # AD-444: confidence score increased
    KNOWLEDGE_CONTRADICTED = "knowledge_contradicted"  # AD-444: confidence score decreased

    # Boot camp (AD-638)
    BOOT_CAMP_ACTIVATED = "boot_camp_activated"
    BOOT_CAMP_PHASE_ADVANCE = "boot_camp_phase_advance"
    BOOT_CAMP_GRADUATION = "boot_camp_graduation"
    BOOT_CAMP_TIMEOUT = "boot_camp_timeout"

    # Bill System (AD-618b)
    BILL_ACTIVATED = "bill_activated"
    BILL_STEP_STARTED = "bill_step_started"
    BILL_STEP_COMPLETED = "bill_step_completed"
    BILL_STEP_FAILED = "bill_step_failed"
    BILL_COMPLETED = "bill_completed"
    BILL_FAILED = "bill_failed"
    BILL_CANCELLED = "bill_cancelled"
    BILL_ROLE_ASSIGNED = "bill_role_assigned"

    # Tiered trust (AD-640)
    TIERED_TRUST_INITIALIZED = "tiered_trust_initialized"

    # ── Agent Cognitive Queue (AD-654b) ─────────────────────────────
    QUEUE_ITEM_ENQUEUED = "queue_item_enqueued"
    QUEUE_ITEM_DEQUEUED = "queue_item_dequeued"
    QUEUE_ITEM_SHED = "queue_item_shed"
    QUEUE_OVERFLOW = "queue_overflow"

    # ── TaskEvent Dispatcher (AD-654c) ─────────────────────────────
    TASK_EVENT_DISPATCHED = "task_event_dispatched"
    TASK_EVENT_UNROUTABLE = "task_event_unroutable"

    # Sub-task protocol (AD-632a)
    SUB_TASK_COMPLETED = "sub_task_completed"
    SUB_TASK_CHAIN_COMPLETED = "sub_task_chain_completed"

    # Consultation protocol (AD-594)
    CONSULTATION_REQUESTED = "consultation_requested"
    CONSULTATION_COMPLETED = "consultation_completed"
    CONSULTATION_TIMEOUT = "consultation_timeout"
    CONSULTATION_FAILED = "consultation_failed"

    # Billet management (AD-595a)
    BILLET_ASSIGNED = "billet_assigned"
    BILLET_VACATED = "billet_vacated"    # Reserved for AD-595b's vacate() — added now to keep enum changes atomic with BILLET_ASSIGNED

    # DAG execution (on_event callback chain, not _emit_event)
    NODE_START = "node_start"
    NODE_COMPLETE = "node_complete"
    NODE_FAILED = "node_failed"
    ESCALATION_START = "escalation_start"
    ESCALATION_RESOLVED = "escalation_resolved"
    ESCALATION_EXHAUSTED = "escalation_exhausted"


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------

@dataclass
class BaseEvent:
    """Base class for all typed events.

    Subclasses define domain-specific fields.  Serializes to the same
    ``{"type": str, "data": dict, "timestamp": float}`` format the HXI
    WebSocket expects.
    """

    event_type: EventType
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire format HXI expects."""
        data = {k: v for k, v in asdict(self).items()
                if k not in ("event_type", "timestamp")}
        return {
            "type": self.event_type.value,
            "data": data,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Priority A: Build pipeline events
# ---------------------------------------------------------------------------

@dataclass
class BuildStartedEvent(BaseEvent):
    """Build pipeline started."""
    event_type: EventType = field(default=EventType.BUILD_STARTED, init=False)
    build_id: str = ""
    title: str = ""
    message: str = ""


@dataclass
class BuildProgressEvent(BaseEvent):
    """Build pipeline progress update."""
    event_type: EventType = field(default=EventType.BUILD_PROGRESS, init=False)
    build_id: str = ""
    step: str = ""
    step_label: str = ""
    current: int = 0
    total: int = 0
    message: str = ""


@dataclass
class BuildGeneratedEvent(BaseEvent):
    """Build code generation completed — ready for review."""
    event_type: EventType = field(default=EventType.BUILD_GENERATED, init=False)
    build_id: str = ""
    title: str = ""
    description: str = ""
    ad_number: str = ""
    file_changes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BuildResolvedEvent(BaseEvent):
    """Build resolved (abort, commit_override, etc.)."""
    event_type: EventType = field(default=EventType.BUILD_RESOLVED, init=False)
    build_id: str = ""
    resolution: str = ""
    message: str = ""
    commit: str = ""


@dataclass
class BuildSuccessEvent(BaseEvent):
    """Build completed successfully."""
    event_type: EventType = field(default=EventType.BUILD_SUCCESS, init=False)
    build_id: str = ""
    branch: str = ""
    commit: str = ""
    files_written: int = 0
    tests_passed: bool = False


@dataclass
class BuildFailureEvent(BaseEvent):
    """Build failed."""
    event_type: EventType = field(default=EventType.BUILD_FAILURE, init=False)
    build_id: str = ""
    message: str = ""
    error: str = ""
    report: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Priority A: Self-modification events
# ---------------------------------------------------------------------------

@dataclass
class SelfModStartedEvent(BaseEvent):
    """Self-modification pipeline started."""
    event_type: EventType = field(default=EventType.SELF_MOD_STARTED, init=False)
    intent: str = ""
    description: str = ""
    message: str = ""


@dataclass
class SelfModImportApprovedEvent(BaseEvent):
    """Self-mod imports approved."""
    event_type: EventType = field(default=EventType.SELF_MOD_IMPORT_APPROVED, init=False)
    intent: str = ""
    imports: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class SelfModProgressEvent(BaseEvent):
    """Self-modification progress update."""
    event_type: EventType = field(default=EventType.SELF_MOD_PROGRESS, init=False)
    intent: str = ""
    step: str = ""
    step_label: str = ""
    current: int = 0
    total: int = 0
    message: str = ""


@dataclass
class SelfModSuccessEvent(BaseEvent):
    """Self-modification succeeded."""
    event_type: EventType = field(default=EventType.SELF_MOD_SUCCESS, init=False)
    intent: str = ""
    agent_type: str = ""
    agent_id: str = ""
    message: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class SelfModRetryCompleteEvent(BaseEvent):
    """Self-mod retry completed (success or failure)."""
    event_type: EventType = field(default=EventType.SELF_MOD_RETRY_COMPLETE, init=False)
    intent: str = ""
    response: str = ""
    message: str = ""


@dataclass
class SelfModFailureEvent(BaseEvent):
    """Self-modification failed."""
    event_type: EventType = field(default=EventType.SELF_MOD_FAILURE, init=False)
    intent: str = ""
    message: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Priority A: Trust & routing events
# ---------------------------------------------------------------------------

@dataclass
class TrustUpdateEvent(BaseEvent):
    """Trust score change."""
    event_type: EventType = field(default=EventType.TRUST_UPDATE, init=False)
    agent_id: str = ""
    new_score: float = 0.0
    success: bool = False


@dataclass
class TrustCascadeEvent(BaseEvent):
    """Emitted when the trust cascade circuit breaker trips (AD-558)."""
    event_type: EventType = field(default=EventType.TRUST_CASCADE_WARNING, init=False)
    anomalous_agents: list[str] = field(default_factory=list)
    departments_affected: list[str] = field(default_factory=list)
    global_dampening_factor: float = 0.5
    cooldown_seconds: float = 600.0


@dataclass
class EmergenceMetricsEvent(BaseEvent):
    """Emitted after emergence metrics computation during dream Step 9 (AD-557)."""
    event_type: EventType = field(default=EventType.EMERGENCE_METRICS_UPDATED, init=False)
    emergence_capacity: float = 0.0
    coordination_balance: float = 0.0
    threads_analyzed: int = 0
    pairs_analyzed: int = 0
    significant_pairs: int = 0
    groupthink_risk: bool = False
    fragmentation_risk: bool = False


@dataclass
class HebbianUpdateEvent(BaseEvent):
    """Hebbian routing weight update."""
    event_type: EventType = field(default=EventType.HEBBIAN_UPDATE, init=False)
    source: str = ""
    target: str = ""
    weight: float = 0.0
    rel_type: str = ""


@dataclass
class ConsensusEvent(BaseEvent):
    """Consensus round completed."""
    event_type: EventType = field(default=EventType.CONSENSUS, init=False)
    intent: str = ""
    outcome: str = ""
    approval_ratio: float = 0.0
    votes: int = 0
    shapley: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Priority B: Design pipeline events
# ---------------------------------------------------------------------------

@dataclass
class DesignStartedEvent(BaseEvent):
    """Design pipeline started."""
    event_type: EventType = field(default=EventType.DESIGN_STARTED, init=False)
    design_id: str = ""
    feature: str = ""
    message: str = ""


@dataclass
class DesignProgressEvent(BaseEvent):
    """Design pipeline progress update."""
    event_type: EventType = field(default=EventType.DESIGN_PROGRESS, init=False)
    design_id: str = ""
    step: str = ""
    step_label: str = ""
    current: int = 0
    total: int = 0


@dataclass
class DesignGeneratedEvent(BaseEvent):
    """Design generation completed."""
    event_type: EventType = field(default=EventType.DESIGN_GENERATED, init=False)
    design_id: str = ""
    title: str = ""
    summary: str = ""
    rationale: str = ""
    roadmap_ref: str = ""


@dataclass
class DesignFailureEvent(BaseEvent):
    """Design pipeline failed."""
    event_type: EventType = field(default=EventType.DESIGN_FAILURE, init=False)
    design_id: str = ""
    message: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Priority B: Ward Room events
# ---------------------------------------------------------------------------

@dataclass
class WardRoomThreadCreatedEvent(BaseEvent):
    """Ward Room thread created."""
    event_type: EventType = field(default=EventType.WARD_ROOM_THREAD_CREATED, init=False)
    thread_id: str = ""
    channel_id: str = ""
    author_id: str = ""
    title: str = ""
    author_callsign: str = ""
    thread_mode: str = ""
    mentions: list[str] = field(default_factory=list)


@dataclass
class WardRoomThreadUpdatedEvent(BaseEvent):
    """Ward Room thread updated."""
    event_type: EventType = field(default=EventType.WARD_ROOM_THREAD_UPDATED, init=False)
    thread_id: str = ""
    updates: dict[str, Any] = field(default_factory=dict)


@dataclass
class WardRoomPostCreatedEvent(BaseEvent):
    """Ward Room post created."""
    event_type: EventType = field(default=EventType.WARD_ROOM_POST_CREATED, init=False)
    post_id: str = ""
    thread_id: str = ""
    author_id: str = ""
    parent_id: str = ""
    author_callsign: str = ""
    mentions: list[str] = field(default_factory=list)


@dataclass
class WardRoomEndorsementEvent(BaseEvent):
    """Ward Room endorsement vote."""
    event_type: EventType = field(default=EventType.WARD_ROOM_ENDORSEMENT, init=False)
    target_id: str = ""
    target_type: str = ""
    voter_id: str = ""
    direction: str = ""
    net_score: int = 0


# ---------------------------------------------------------------------------
# Priority B: Counselor / Cognitive Health events (AD-503)
# ---------------------------------------------------------------------------

@dataclass
class CircuitBreakerTripEvent(BaseEvent):
    """Emitted when a cognitive circuit breaker trips for an agent."""
    event_type: EventType = field(default=EventType.CIRCUIT_BREAKER_TRIP, init=False)
    agent_id: str = ""
    agent_callsign: str = ""
    trip_count: int = 0
    cooldown_seconds: float = 0.0


@dataclass
class DreamCompleteEvent(BaseEvent):
    """Emitted when a dream cycle (full or micro) completes."""
    event_type: EventType = field(default=EventType.DREAM_COMPLETE, init=False)
    dream_type: str = ""  # "full" or "micro"
    duration_ms: float = 0.0
    episodes_replayed: int = 0


@dataclass
class CounselorAssessmentEvent(BaseEvent):
    """Emitted when the Counselor completes an agent assessment."""
    event_type: EventType = field(default=EventType.COUNSELOR_ASSESSMENT, init=False)
    agent_id: str = ""
    wellness_score: float = 0.0
    alert_level: str = "green"
    fit_for_duty: bool = True
    concerns_count: int = 0


@dataclass
class SelfMonitoringConcernEvent(BaseEvent):
    """Emitted when an agent enters the amber zone (pre-trip warning)."""
    event_type: EventType = field(default=EventType.SELF_MONITORING_CONCERN, init=False)
    agent_id: str = ""
    agent_callsign: str = ""
    zone: str = "amber"  # Current zone
    similarity_ratio: float = 0.0
    velocity_ratio: float = 0.0


@dataclass
class ZoneRecoveryEvent(BaseEvent):
    """Emitted when an agent's cognitive zone improves (e.g., amber -> green)."""
    event_type: EventType = field(default=EventType.ZONE_RECOVERY, init=False)
    agent_id: str = ""
    agent_callsign: str = ""
    old_zone: str = ""
    new_zone: str = ""


@dataclass
class PeerRepetitionDetectedEvent(BaseEvent):
    """Emitted when a Ward Room post is similar to another agent's recent post."""
    event_type: EventType = field(default=EventType.PEER_REPETITION_DETECTED, init=False)
    channel_id: str = ""
    author_id: str = ""
    author_callsign: str = ""
    match_count: int = 0
    top_similarity: float = 0.0
    post_type: str = ""  # "thread" or "reply"


@dataclass
class LlmHealthChangedEvent(BaseEvent):
    """AD-576: Emitted on LLM backend status transitions."""
    event_type: EventType = field(default=EventType.LLM_HEALTH_CHANGED, init=False)
    old_status: str = ""       # "operational", "degraded", "offline", "recovering"
    new_status: str = ""       # "operational", "degraded", "offline", "recovering"
    consecutive_failures: int = 0
    consecutive_successes: int = 0  # BF-240: Dwell count at transition time
    downtime_seconds: float = 0.0  # Time since first failure (0 on recovery)


@dataclass
class KnowledgeTierLoadedEvent(BaseEvent):
    """AD-585: Emitted after a successful tiered knowledge load."""
    event_type: EventType = field(default=EventType.KNOWLEDGE_TIER_LOADED, init=False)
    tier: str = ""           # "ambient", "contextual", "on_demand"
    snippet_count: int = 0
    intent_type: str = ""    # Contextual tier only
    query: str = ""          # On-demand tier only


@dataclass
class SensoriumBudgetExceededEvent(BaseEvent):
    """AD-666: Sensorium injection exceeded char threshold."""
    event_type: EventType = field(default=EventType.SENSORIUM_BUDGET_EXCEEDED, init=False)
    agent_id: str = ""
    callsign: str = ""
    total_chars: int = 0
    threshold: int = 0
    cognitive_state_chars: int = 0
    situation_chars: int = 0


@dataclass
class AgentCapacityApproachingEvent(BaseEvent):
    """AD-672: Agent nearing concurrency ceiling."""
    event_type: EventType = field(default=EventType.AGENT_CAPACITY_APPROACHING, init=False)
    agent_id: str = ""
    active_count: int = 0
    max_concurrent: int = 0
    queue_depth: int = 0


@dataclass
class NotebookSelfRepetitionEvent(BaseEvent):
    """AD-552: Emitted when an agent writes about the same topic repeatedly."""
    event_type: EventType = field(default=EventType.NOTEBOOK_SELF_REPETITION, init=False)
    agent_id: str = ""
    agent_callsign: str = ""
    topic_slug: str = ""
    revision: int = 0
    hours_active: float = 0.0
    novelty: float = 0.0
    suppressed: bool = False  # True if write was suppressed


@dataclass
class ConvergenceDetectedEvent(BaseEvent):
    """AD-554: Emitted when cross-agent convergence is detected."""
    event_type: EventType = field(default=EventType.CONVERGENCE_DETECTED, init=False)
    agents: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    topic: str = ""
    coherence: float = 0.0
    source: str = ""  # "realtime" or "dream_consolidation"
    report_path: str = ""


@dataclass
class WrongConvergenceDetectedEvent(BaseEvent):
    """AD-583: Convergence with insufficient independent evidence."""
    event_type: EventType = field(default=EventType.WRONG_CONVERGENCE_DETECTED, init=False)
    agents: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    topic: str = ""
    coherence: float = 0.0
    independence_score: float = 0.0
    source: str = ""  # "realtime" or "dream_consolidation"


@dataclass
class WardRoomEchoDetectedEvent:
    """AD-583g: Echo amplification chain detected in Ward Room thread."""
    thread_id: str = ""
    channel_id: str = ""
    source_callsign: str = ""
    chain_length: int = 0
    independence_score: float = 1.0
    affected_callsigns: list[str] = field(default_factory=list)
    source: str = "ward_room_echo"

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "channel_id": self.channel_id,
            "source_callsign": self.source_callsign,
            "chain_length": self.chain_length,
            "independence_score": self.independence_score,
            "affected_callsigns": self.affected_callsigns,
            "source": self.source,
        }


@dataclass
class ObservableStateMismatchEvent:
    """AD-583f: Agent claims contradicted by observable system state."""
    thread_id: str = ""
    claims_checked: int = 0
    claims_failed: int = 0
    ground_truth_summary: str = ""
    agents_involved: list[str] = field(default_factory=list)
    source: str = "observable_state"

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "claims_checked": self.claims_checked,
            "claims_failed": self.claims_failed,
            "ground_truth_summary": self.ground_truth_summary,
            "agents_involved": self.agents_involved,
            "source": self.source,
        }


@dataclass
class DivergenceDetectedEvent(BaseEvent):
    """AD-554: Emitted when cross-agent divergence is detected."""
    event_type: EventType = field(default=EventType.DIVERGENCE_DETECTED, init=False)
    agents: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    topic: str = ""
    similarity: float = 0.0


@dataclass
class TaskExecutionCompleteEvent(BaseEvent):
    """Emitted after a cognitive agent completes a task via LLM path (AD-532e)."""
    event_type: EventType = field(default=EventType.TASK_EXECUTION_COMPLETE, init=False)
    agent_id: str = ""
    agent_type: str = ""
    intent_type: str = ""
    success: bool = False
    used_procedure: bool = False  # True if procedural replay was used (no reactive needed)


@dataclass
class ProcedureFallbackLearningEvent(BaseEvent):
    """Emitted when a procedure was relevant but skipped/failed, and the LLM succeeded (AD-534b)."""
    event_type: EventType = field(default=EventType.PROCEDURE_FALLBACK_LEARNING, init=False)
    agent_id: str = ""
    intent_type: str = ""
    fallback_type: str = ""        # "execution_failure" | "quality_gate" | "score_threshold" | "negative_veto" | "format_exception"
    procedure_id: str = ""
    procedure_name: str = ""
    near_miss_score: float = 0.0   # Cosine similarity score (0 for execution failures)
    rejection_reason: str = ""     # Human-readable reason for rejection/failure
    llm_response: str = ""         # What the LLM did (truncated to MAX_FALLBACK_RESPONSE_CHARS)
    timestamp: float = 0.0


@dataclass
class CascadeConfabulationEvent(BaseEvent):
    """AD-567f: Emitted when cascade confabulation risk is detected."""
    event_type: EventType = field(default=EventType.CASCADE_CONFABULATION_DETECTED, init=False)
    risk_level: str = ""                    # "low", "medium", "high"
    source_agent: str = ""                  # Earliest poster (callsign)
    affected_agents: list[str] = field(default_factory=list)
    affected_departments: list[str] = field(default_factory=list)
    propagation_count: int = 0
    anchor_independence_score: float = 0.0
    channel_id: str = ""
    detail: str = ""


@dataclass
class CorroborationVerifiedEvent(BaseEvent):
    """AD-567f: Emitted when a claim is independently corroborated."""
    event_type: EventType = field(default=EventType.CORROBORATION_VERIFIED, init=False)
    requesting_agent: str = ""              # Callsign of verifying agent
    claim_preview: str = ""                 # First 100 chars of the claim
    corroborating_agents: list[str] = field(default_factory=list)
    corroboration_score: float = 0.0
    anchor_independence_score: float = 0.0


@dataclass
class CorroborationProvenanceValidatedEvent(BaseEvent):
    """AD-665: Emitted when provenance validation detects shared ancestry."""
    event_type: EventType = field(default=EventType.CORROBORATION_PROVENANCE_VALIDATED, init=False)
    requesting_agent: str = ""
    shared_ancestry_pairs: int = 0
    discounted_pairs: int = 0
    total_pairs_checked: int = 0


@dataclass
class SubTaskChainCompletedEvent(BaseEvent):
    """AD-632a: Emitted when a sub-task chain finishes execution."""
    event_type: EventType = field(
        default=EventType.SUB_TASK_CHAIN_COMPLETED, init=False
    )
    agent_id: str = ""
    agent_type: str = ""
    intent: str = ""
    chain_steps: int = 0
    total_tokens: int = 0
    total_duration_ms: float = 0.0
    success: bool = True
    fallback_used: bool = False
    source: str = ""          # What triggered the chain


@dataclass
class ConsultationRequestedEvent(BaseEvent):
    """AD-594: Consultation request submitted."""

    event_type: EventType = field(
        default=EventType.CONSULTATION_REQUESTED, init=False
    )
    request_id: str = ""
    requester_id: str = ""
    requester_callsign: str = ""
    target_agent_id: str = ""
    topic: str = ""
    urgency: str = ""


@dataclass
class ConsultationCompletedEvent(BaseEvent):
    """AD-594: Consultation completed successfully."""

    event_type: EventType = field(
        default=EventType.CONSULTATION_COMPLETED, init=False
    )
    request_id: str = ""
    requester_id: str = ""
    responder_id: str = ""
    responder_callsign: str = ""
    topic: str = ""
    confidence: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class ConsultationTimeoutEvent(BaseEvent):
    """AD-594: Consultation timed out."""

    event_type: EventType = field(
        default=EventType.CONSULTATION_TIMEOUT, init=False
    )
    request_id: str = ""
    requester_id: str = ""
    target_agent_id: str = ""
    topic: str = ""
    timeout_seconds: float = 0.0


@dataclass
class ConsultationFailedEvent(BaseEvent):
    """AD-594: Consultation handler failed."""

    event_type: EventType = field(
        default=EventType.CONSULTATION_FAILED, init=False
    )
    request_id: str = ""
    requester_id: str = ""
    target_agent_id: str = ""
    topic: str = ""
    error: str = ""
