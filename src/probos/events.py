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

    # Skill telemetry (AD-628a)
    SKILL_LOADED = "skill_loaded"
    SKILL_BLOCKED = "skill_blocked"
    SKILL_EXERCISED = "skill_exercised"
    SKILL_REGRESSION = "skill_regression"
    SKILL_DECAY = "skill_decay"
    SKILL_ACQUIRED = "skill_acquired"

    # Limited duty (AD-628g)
    LIMDU_RECOMMENDED = "limdu_recommended"

    # Dream / system mode
    SYSTEM_MODE = "system_mode"
    CAPABILITY_GAP_PREDICTED = "capability_gap_predicted"

    # Agent lifecycle
    AGENT_STATE = "agent_state"
    AGENT_WIRED = "agent_wired"  # AD-490
    AGENT_CAPACITY_APPROACHING = "agent_capacity_approaching"
    AGENT_REMOVED = "agent_removed"  # AD-880: reactive reclaim trigger
    CONDUCT_VIOLATION = "conduct_violation"  # AD-489

    # Assignments
    ASSIGNMENT_CREATED = "assignment_created"
    ASSIGNMENT_UPDATED = "assignment_updated"
    ASSIGNMENT_COMPLETED = "assignment_completed"

    # Work items / workforce
    WORK_ITEM_CREATED = "work_item_created"
    WORK_ITEM_UPDATED = "work_item_updated"
    WORK_ITEM_STATUS_CHANGED = "work_item_status_changed"
    WORK_ITEM_RECONCILED = "work_item_reconciled"  # AD-875
    WORK_ITEM_ASSIGNED = "work_item_assigned"
    WORK_ITEM_CLAIMED = "work_item_claimed"
    CREW_TASK_STARTED = "crew_task_started"  # AD-859
    SUBTASK_COMPLETED = "subtask_completed"  # AD-859
    CREW_TASK_COMPLETED = "crew_task_completed"  # AD-861
    CREW_ORCHESTRATION_STARTED = "crew_orchestration_started"  # AD-867
    BOOKING_STARTED = "booking_started"
    BOOKING_COMPLETED = "booking_completed"
    BOOKING_CANCELLED = "booking_cancelled"

    # Capability requests (AD-853)
    CAPABILITY_REQUEST_FILED = "capability_request_filed"
    CAPABILITY_REQUEST_DECIDED = "capability_request_decided"
    CAPABILITY_REQUEST_FULFILLED = "capability_request_fulfilled"
    # Skill requests (AD-906/907) — crew skill-acquisition approval queue +
    # holodeck-training completion wiring.
    SKILL_REQUEST_FILED = "skill_request_filed"
    SKILL_REQUEST_DECIDED = "skill_request_decided"
    SKILL_REQUEST_TRAINING_STARTED = "skill_request_training_started"
    SKILL_REQUEST_COMPLETED = "skill_request_completed"
    # Per-agent capability enablement (AD-983b) — Captain grant/revoke of a
    # tool or cognitive skill on a specific agent.
    CAPABILITY_ACCESS_RESOLVED = "capability_access_resolved"

    # Exogenous attention triggers (AD-1032) — raise the per-agent
    # AttentionFaculty's FACULTY-LOCAL arousal zone (GREEN→AMBER→RED), the
    # cognitive-layer mirror of HXI Design Principle #9 (LCARS Red-Alert
    # reconfiguration). DEFINITIONS ONLY: the live emission-site wiring (router
    # @mentions, bridge alerts, consensus/safety events, peer gossip) is a
    # deferred follow-up. The governed inlet is ``CognitiveAgent.on_exogenous_event``.
    EXOGENOUS_MENTION = "exogenous_mention"
    EXOGENOUS_ALERT = "exogenous_alert"
    EXOGENOUS_SCENE_CHANGE = "exogenous_scene_change"
    EXOGENOUS_CONSENSUS = "exogenous_consensus"
    EXOGENOUS_SAFETY = "exogenous_safety"
    EXOGENOUS_GOSSIP = "exogenous_gossip"

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

    # OS-activity sensor (AD-1054) -- raw desktop foreground-window metadata.
    # Pure sensor; emitted in-process. Nothing in OSS consumes it.
    OS_ACTIVITY = "os_activity"

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
    COUNSELOR_INTERVENTION = "counselor_intervention"  # AD-561
    SELF_MONITORING_CONCERN = "self_monitoring_concern"  # AD-506a: amber zone
    ZONE_RECOVERY = "zone_recovery"  # AD-506b: agent zone improved
    PEER_REPETITION_DETECTED = "peer_repetition_detected"  # AD-506b
    # AD-479: Federation hardening event types (Wave 91)
    FEDERATION_PEER_UNREACHABLE = "federation_peer_unreachable"  # AD-479g
    FEDERATION_PEER_RECOVERED = "federation_peer_recovered"  # AD-479g
    FEDERATION_PEER_DISCOVERED = "federation_peer_discovered"  # AD-479h
    # AD-607: Federation memory security event types (Wave 92)
    FEDERATION_EPISODE_REJECTED = "federation_episode_rejected"  # AD-607f
    FEDERATION_RECALL_DP_REDACTED = "federation_recall_dp_redacted"  # AD-607i
    FEDERATION_DESIGNED_AGENT_RECEIVED = "federation_designed_agent_received"  # AD-479e
    TASK_EXECUTION_COMPLETE = "task_execution_complete"  # AD-532e: reactive trigger
    PROCEDURE_FALLBACK_LEARNING = "procedure_fallback_learning"  # AD-534b: fallback evidence
    GAP_IDENTIFIED = "gap_identified"  # AD-539: gap → qualification pipeline
    GAP_REMEDIATION_RECORDED = "gap_remediation_recorded"  # AD-539c: observational remediation candidate
    FLEET_GAP_SNAPSHOT_TAKEN = "fleet_gap_snapshot_taken"  # AD-539d: local-ship gap aggregation
    TRUST_CASCADE_WARNING = "trust_cascade_warning"  # AD-558: trust cascade breaker tripped
    EMERGENCE_METRICS_UPDATED = "emergence_metrics_updated"  # AD-557: emergence snapshot computed
    GROUPTHINK_WARNING = "groupthink_warning"  # AD-557: redundancy dominates
    FRAGMENTATION_WARNING = "fragmentation_warning"  # AD-557: synergy near zero
    BEHAVIORAL_METRICS_UPDATED = "behavioral_metrics_updated"  # AD-569: behavioral snapshot computed
    TELEMETRY_REPORT = "telemetry_report"  # AD-461
    ANOMALY_WINDOW_OPENED = "anomaly_window_opened"  # AD-673: anomaly window opened
    ANOMALY_WINDOW_CLOSED = "anomaly_window_closed"  # AD-673: anomaly window closed
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
    LEADERSHIP_DIVERGENCE = "leadership_divergence"  # AD-439
    WARD_ROOM_ECHO_DETECTED = "ward_room_echo_detected"  # AD-583g
    OBSERVABLE_STATE_MISMATCH = "observable_state_mismatch"  # AD-583f
    SELF_MODEL_DRIFT = "self_model_drift"  # AD-589: introspective confabulation detected
    DM_CONVERGENCE_DETECTED = "dm_convergence_detected"  # AD-623: DM thread converged
    ORDER_ISSUED = "order_issued"  # AD-440
    ORDER_REJECTED = "order_rejected"  # AD-440
    ORDER_ACKNOWLEDGED = "order_acknowledged"  # AD-440
    ORDER_DECLINED = "order_declined"  # AD-581b
    ORDER_REFUSED = "order_refused"  # AD-581b
    SENSORIUM_BUDGET_EXCEEDED = "sensorium_budget_exceeded"  # AD-666: sensorium injection over char threshold
    TOOL_PERMISSION_DENIED = "tool_permission_denied"  # AD-423b: agent lacks tool permission
    TOOL_INVOKED = "tool_invoked"  # AD-448
    TOOL_INTERVENTION_REQUIRED = "tool_intervention_required"  # AD-706: tier-3 action awaits Captain ACK
    BROWSER_ACTION_EXECUTED = "browser_action_executed"        # AD-706: per-action telemetry
    BROWSER_SESSION_OPENED = "browser_session_opened"          # AD-706
    BROWSER_VERIFY_OBSERVED = "browser_verify_observed"        # AD-706c-1: vision-LLM verification result
    BROWSER_COMPUTE_USE_CLICK_PROPOSED = "browser_compute_use_click_proposed"  # AD-706c-2: coordinate predicted
    BROWSER_COMPUTE_USE_CLICK_VERIFIED = "browser_compute_use_click_verified"  # AD-706c-2: handshake succeeded
    BROWSER_COMPUTE_USE_CLICK_ABORTED = "browser_compute_use_click_aborted"    # AD-706c-2: verification disagreed
    BROWSER_COMPUTE_USE_CLICK_EXECUTED = "browser_compute_use_click_executed"  # AD-706c-2: click sent to page
    BROWSER_FILE_UPLOAD_REQUESTED = "browser_file_upload_requested"  # AD-706e: upload_file invoked
    BROWSER_DOWNLOAD_REQUESTED = "browser_download_requested"        # AD-706e: download invoked
    BROWSER_EVAL_JS_EXECUTED = "browser_eval_js_executed"            # AD-706e: eval_js executed
    CREDENTIAL_STORED = "credential_stored"                          # AD-706f: vault write
    CREDENTIAL_READ = "credential_read"                              # AD-706f: vault read (audit row)
    CREDENTIAL_READ_DENIED = "credential_read_denied"                # AD-706f: capability scope mismatch
    CREDENTIAL_DELETED = "credential_deleted"                        # AD-706f: vault delete
    CREDENTIAL_FILL_REQUESTED = "credential_fill_requested"          # AD-706f: page.fill invoked
    BROWSER_STREAM_OPENED = "browser_stream_opened"                  # AD-706a: Captain-watch viewer connected
    BROWSER_STREAM_CLOSED = "browser_stream_closed"                  # AD-706a: viewer disconnected
    BROWSER_STREAM_FRAME_DROPPED = "browser_stream_frame_dropped"    # AD-706a: viewer backpressure / frame skipped
    BROWSER_RECORDING_STARTED = "browser_recording_started"          # AD-706b: session opened with recording on
    BROWSER_RECORDING_STOPPED = "browser_recording_stopped"          # AD-706b: webm file finalized
    BROWSER_RECORDING_EXPIRED = "browser_recording_expired"          # AD-706b: reaper deleted past retention
    BROWSER_RECORDING_FAILED = "browser_recording_failed"            # AD-706b: Playwright recording errored at close
    BROWSER_BRIDGE_CONNECTED = "browser_bridge_connected"        # AD-1052b: connected to an external CDP browser
    BROWSER_BRIDGE_REFUSED = "browser_bridge_refused"            # AD-1052b: bridge connect refused (disabled/consent/allowlist/unreachable)
    BROWSER_BRIDGE_DISCONNECTED = "browser_bridge_disconnected"  # AD-1052b: bridge session torn down (disconnect, not close)
    BROWSER_INPUT_FORWARDED = "browser_input_forwarded"        # AD-1052c: Captain took the wheel (per drive-episode)
    BROWSER_INPUT_REFUSED = "browser_input_refused"            # AD-1052c: input forward refused (disabled/no-session/no-page/key)
    # AD-733-1: AttachmentStore retention telemetry.
    ATTACHMENT_REAPED = "attachment_reaped"                          # AD-733-1: per-sweep summary
    ATTACHMENT_STORE_DISK_FULL = "attachment_store_disk_full"        # AD-733-1: ENOSPC on write
    VISION_CAPABILITY_PROPOSED = "vision_capability_proposed"  # AD-720d-2.1: agent requests vision capability
    VISION_CAPABILITY_RESOLVED = "vision_capability_resolved"  # AD-720d-2.1: Captain approves or denies
    VISION_INTENT_DIVERGENCE_OBSERVED = "vision_intent_divergence_observed"  # AD-722a-1: vision-LLM intent-vs-render
    RENDER_DIVERGENCE_OBSERVED = "render_divergence_observed"  # AD-728: vision-LLM render coherence mirror
    PEER_OBSERVATION_RECORDED = "peer_observation_recorded"  # AD-729: peer avatar perception
    PEER_OBSERVATION_DECLINED = "peer_observation_declined"  # AD-729: capability gate / opt-out denial
    PEER_OBSERVATION_PERMISSION_REQUESTED = "peer_observation_permission_requested"  # AD-729: speak-freely protocol
    PEER_OBSERVATION_PERMISSION_GRANTED = "peer_observation_permission_granted"  # AD-729: speak-freely protocol
    PEER_OBSERVATION_PERMISSION_DENIED = "peer_observation_permission_denied"  # AD-729: speak-freely protocol
    CROSS_AGENT_DIVERGENCE_OBSERVED = "cross_agent_divergence_observed"  # AD-722a-6: peer perception of intent-vs-presentation
    PEER_OBSERVATION_CERTIFIED = "peer_observation_certified"  # AD-729b: training-module pass
    PEER_OBSERVATION_CERTIFICATION_REVOKED = "peer_observation_certification_revoked"  # AD-729b: training-module revocation
    PEER_OBSERVATION_PATTERN_FLAGGED = "peer_observation_pattern_flagged"  # AD-729c: pattern detector hit
    PEER_OBSERVATION_INTERVENTION_TIER_1 = "peer_observation_intervention_tier_1"  # AD-729c: private coaching
    PEER_OBSERVATION_INTERVENTION_TIER_2 = "peer_observation_intervention_tier_2"  # AD-729c: recertification triggered
    PEER_OBSERVATION_INTERVENTION_TIER_3 = "peer_observation_intervention_tier_3"  # AD-729c: bridge alert
    SELF_RENDER_COHERENCE_OBSERVED = "self_render_coherence_observed"  # AD-722e-2: vision-LLM digital-vs-render
    DIVERGENCE_OBSERVED_CHAIN = "divergence_observed_chain"  # AD-722a-2: chain-path divergence
    APPEARANCE_REVISION_MEDIATED = "appearance_revision_mediated"  # AD-721d-2: Counselor-mediated avatar revision
    BROWSER_SESSION_CLOSED = "browser_session_closed"          # AD-706
    AGENTIC_TOOL_CALL_STARTED = "agentic_tool_call_started"      # AD-545
    AGENTIC_TOOL_CALL_COMPLETED = "agentic_tool_call_completed"  # AD-545
    AGENTIC_LOOP_ITERATION = "agentic_loop_iteration"            # AD-545
    ACTION_RISK_DENIED = "action_risk_denied"  # AD-676
    DECISION_QUEUE_PAUSED = "decision_queue_paused"  # AD-445
    COMPENSATION_TRIGGERED = "compensation_triggered"  # AD-446
    TOOL_LOCKED = "tool_locked"  # AD-423b: LOTO lock acquired
    TOOL_UNLOCKED = "tool_unlocked"  # AD-423b: LOTO lock released
    TOOL_CONTEXT_CREATED = "tool_context_created"  # AD-423c: fired during onboarding
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"  # AD-585: tiered knowledge load
    CONTEXT_PROVENANCE_INJECTED = "context_provenance_injected"  # AD-677
    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679
    THREAT_DETECTED = "threat_detected"  # AD-455
    TRUST_INTEGRITY_VIOLATION = "trust_integrity_violation"  # AD-455
    SECURITY_INPUT_REJECTED = "security_input_rejected"  # AD-455
    RED_TEAM_CAMPAIGN_COMPLETE = "red_team_campaign_complete"  # AD-455
    CONFIG_CHANGED = "config_changed"  # AD-468
    SHIP_NAMED = "ship_named"  # AD-499
    AGENT_SELF_NAMED = "agent_self_named"  # AD-499
    VALIDATION_RECONCILIATION_REQUESTED = "validation_reconciliation_requested"  # AD-451
    VALIDATION_OUTCOME_VERIFIED = "validation_outcome_verified"  # AD-451
    DAMAGE_CONTROL_ACTIVATED = "damage_control_activated"  # AD-457
    MAINTENANCE_SCHEDULED = "maintenance_scheduled"  # AD-457
    PERFORMANCE_THRESHOLD_BREACHED = "performance_threshold_breached"  # AD-457
    SERVICE_TIER_DEGRADED = "service_tier_degraded"  # AD-459
    SERVICE_TIER_RESTORED = "service_tier_restored"  # AD-459
    SUBSYSTEM_PAUSED = "subsystem_paused"  # AD-459b
    SUBSYSTEM_RESUMED = "subsystem_resumed"  # AD-459b
    PREFLIGHT_FAILED = "preflight_failed"  # AD-458
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
    BACKUP_COMPLETE = "backup_complete"  # AD-466
    BACKUP_FAILED = "backup_failed"  # AD-466
    SECRET_ROTATED = "secret_rotated"  # AD-456
    EGRESS_BLOCKED = "egress_blocked"  # AD-456
    CLASSIFICATION_DISCLOSURE_BLOCKED = "classification_disclosure_blocked"  # AD-530
    BOUNDARY_VIOLATION_DETECTED = "boundary_violation_detected"  # AD-511
    DUTY_SCOPE_QUERIED = "duty_scope_queried"  # AD-508
    WORKSPACE_TERM_REGISTERED = "workspace_term_registered"  # AD-478
    AUDIT_RECORDED = "audit_recorded"  # AD-456
    SANDBOX_LIMIT_EXCEEDED = "sandbox_limit_exceeded"  # AD-456b
    SANDBOX_CAPABILITY_DENIED = "sandbox_capability_denied"  # AD-456b
    CREDENTIAL_TIER_DENIED = "credential_tier_denied"  # AD-456c
    AUDIT_PERSISTED = "audit_persisted"  # AD-456d
    # AD-802: DM pairing for channel-adapter inbound from unknown senders.
    PAIRING_REQUESTED = "pairing_requested"
    PAIRING_APPROVED = "pairing_approved"
    PAIRING_REVOKED = "pairing_revoked"
    VERIFICATION_PASSED = "verification_passed"  # AD-528
    VERIFICATION_FAILED = "verification_failed"  # AD-528
    VERIFICATION_REJECTED = "verification_rejected"  # AD-528b
    WORK_ITEM_QUARANTINED = "work_item_quarantined"  # AD-528b
    RESOURCE_ALLOCATED = "resource_allocated"  # AD-467
    TASK_SCHEDULED = "task_scheduled"  # AD-467
    WORKFLOW_STARTED = "workflow_started"  # AD-467
    MODEL_ROUTED = "model_routed"  # AD-463
    MODEL_FALLBACK = "model_fallback"  # AD-463
    READY_ROOM_SESSION_STARTED = "ready_room_session_started"  # AD-475
    IDEA_CAPTURED = "idea_captured"  # AD-475
    CHANNEL_MESSAGE_RECEIVED = "channel_message_received"  # AD-472
    CHANNEL_DELIVERY_FAILED = "channel_delivery_failed"  # AD-472
    DREAM_MANIFEST_UPDATED = "dream_manifest_updated"  # AD-538b
    CAPTAIN_DM_PRIORITY_QUEUED = "captain_dm_priority_queued"  # AD-572b
    RECREATION_GAME_REGISTERED = "recreation_game_registered"  # AD-526c
    RECREATION_SPECTATOR_JOINED = "recreation_spectator_joined"  # AD-526e
    RECREATION_SPECTATOR_COMMENTARY = "recreation_spectator_commentary"  # AD-526e
    ORACLE_LOOKUP_DISPATCHED = "oracle_lookup_dispatched"  # AD-696
    MEMORY_REFS_DISPATCHED = "memory_refs_dispatched"  # AD-462f
    # AD-607: Memory security framework event types (Wave 92)
    MEMORY_RECALL_ANOMALY = "memory_recall_anomaly"  # AD-607a
    MEMORY_PROVENANCE_GAP = "memory_provenance_gap"  # AD-607b
    MEMORY_ANCHOR_MISMATCH = "memory_anchor_mismatch"  # AD-607c
    MEMORY_LEAK_SUSPECTED = "memory_leak_suspected"  # AD-607d
    MEMORY_INJECTION_SUSPECTED = "memory_injection_suspected"  # AD-607h
    CONTRASTIVE_RECALL = "contrastive_recall"  # AD-655
    DEPT_PROFILE_APPLIED = "dept_profile_applied"  # AD-656
    EPS_BUDGET_EXCEEDED = "eps_budget_exceeded"  # AD-469
    EPS_REALLOCATION = "eps_reallocation"  # AD-469
    MCP_BRIDGE_INVOKE = "mcp_bridge_invoke"  # AD-449
    MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449
    # AD-597: MCP App Host events
    MCP_APP_TOOL_REGISTERED = "mcp_app_tool_registered"
    MCP_APP_RESOURCE_READ = "mcp_app_resource_read"
    MCP_APP_TOOL_INVOKED = "mcp_app_tool_invoked"
    MCP_APP_EXTERNAL_DISCOVERED = "mcp_app_external_discovered"
    OPTIMIZATION_PROPOSAL_APPLIED = "optimization_proposal_applied"  # AD-659c
    OPTIMIZATION_PROPOSAL_REVERTED = "optimization_proposal_reverted"  # AD-659c
    OPTIMIZATION_REGRESSION_DETECTED = "optimization_regression_detected"  # AD-659c
    OBSERVABILITY_SNAPSHOT_PUBLISHED = "observability_snapshot_published"  # AD-641a
    OBSERVABILITY_BRIDGE_FAILED = "observability_bridge_failed"  # AD-641a
    WARD_ROOM_HEBBIAN_UPDATED = "ward_room_hebbian_updated"  # AD-641b
    WARD_ROOM_HEBBIAN_DECAYED = "ward_room_hebbian_decayed"  # AD-641b
    ENGINEERING_SENSOR_REPORT = "engineering_sensor_report"  # AD-641f
    LEARNED_SHORTCUT_REGISTERED = "learned_shortcut_registered"  # AD-641e
    LEARNED_SHORTCUT_HIT = "learned_shortcut_hit"  # AD-641e
    THREAD_PRIORITY_SCORED = "thread_priority_scored"  # AD-641c
    DELIBERATION_INITIATED = "deliberation_initiated"  # AD-641d
    DELIBERATION_ARGUMENT_SUBMITTED = "deliberation_argument_submitted"  # AD-641d
    DELIBERATION_RESOLVED = "deliberation_resolved"  # AD-641d
    EPISODE_REJECTED = "episode_rejected"  # AD-610: storage gate rejected episode
    KNOWLEDGE_CONFIRMED = "knowledge_confirmed"  # AD-444: confidence score increased
    KNOWLEDGE_CONTRADICTED = "knowledge_contradicted"  # AD-444: confidence score decreased
    # Pinned knowledge (AD-579a)
    KNOWLEDGE_PINNED = "knowledge_pinned"  # AD-579a: pinned knowledge added
    KNOWLEDGE_UNPINNED = "knowledge_unpinned"  # AD-579a: pinned knowledge removed
    FORCED_CONSOLIDATION_TRIGGERED = "forced_consolidation_triggered"  # AD-564
    QUALITY_CONCERN = "quality_concern"  # AD-565: low notebook quality diagnostic

    # Boot camp (AD-638)
    BOOT_CAMP_ACTIVATED = "boot_camp_activated"
    SHIP_STATE_SNAPSHOT_CAPTURED = "ship_state_snapshot_captured"  # AD-683
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
    TASK_ROUTED = "task_routed"  # AD-438
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

    # Parallel execution dispatch (AD-594c)
    PARALLEL_DISPATCH_STARTED = "parallel_dispatch_started"
    PARALLEL_DISPATCH_PROGRESS = "parallel_dispatch_progress"
    PARALLEL_DISPATCH_BLOCKED = "parallel_dispatch_blocked"

    # Hybrid dispatch routing decisions (AD-581a)
    HYBRID_DISPATCH_DIRECT = "hybrid_dispatch_direct"
    HYBRID_DISPATCH_BROADCAST = "hybrid_dispatch_broadcast"

    # Predictive cognitive branching (AD-633)
    PREDICTION_HIT = "prediction_hit"  # AD-633b cache served pre-computed analysis
    PREDICTION_MISS = "prediction_miss"  # AD-633d cache miss; fell to LLM
    PREDICTION_FLUSHED = "prediction_flushed"  # AD-633b cache entry evicted (TTL or capacity)
    PREDICTION_ERROR_RECORDED = "prediction_error_recorded"  # AD-633h prediction diverged from outcome

    # Self-improvement pipeline (AD-482)
    CAPABILITY_PROPOSAL_CREATED = "capability_proposal_created"  # AD-482b ProposalStore.submit
    CAPABILITY_PROPOSAL_APPROVED = "capability_proposal_approved"  # AD-482c ApprovalGate.approve
    CAPABILITY_PROPOSAL_REJECTED = "capability_proposal_rejected"  # AD-482c ApprovalGate.reject
    PIVOT_REFINE_DECIDED = "pivot_refine_decided"  # AD-482e ProposalStore.transition
    EVOLUTION_LESSON_RECORDED = "evolution_lesson_recorded"  # AD-482d EvolutionStore.record_lesson
    AGENT_VERSION_PROMOTED = "agent_version_promoted"  # AD-482g AgentVersionStore.register_version + 482h promote

    # Billet management (AD-595a)
    BILLET_ASSIGNED = "billet_assigned"
    BILLET_VACATED = "billet_vacated"    # Reserved for AD-595b's vacate() — added now to keep enum changes atomic with BILLET_ASSIGNED

    # Naval Organization (AD-477)
    CAPTAINS_LOG_GENERATED = "captains_log_generated"  # AD-477
    PLAN_OF_DAY_GENERATED = "plan_of_day_generated"  # AD-477

    # Combo C (Wave 13) — additive read/write surface events
    GAME_PREFERENCE_RECORDED = "game_preference_recorded"  # AD-526d
    WORKING_MEMORY_NOTE_RECORDED = "working_memory_note_recorded"  # AD-573c
    COMMITMENT_RECORDED = "commitment_recorded"  # AD-573f

    # ── Self-Distillation (AD-487) ─────────────────────────────────
    ONTOLOGY_PROBE_RECORDED = "ontology_probe_recorded"  # AD-487
    ONTOLOGY_PROBE_RATE_LIMITED = "ontology_probe_rate_limited"  # AD-487

    # ── Creative Expression (AD-525) ───────────────────────────────
    CREATIVE_WORK_PUBLISHED = "creative_work_published"  # AD-525
    CREATIVE_SKILL_AFFINITY_QUERIED = "creative_skill_affinity_queried"  # AD-525

    # ── Crew Development (AD-507) ──────────────────────────────────
    CURRICULUM_MODULE_QUERIED = "curriculum_module_queried"  # AD-507

    # ── Boot Camp Phase Tracker (AD-509) ───────────────────────────
    BOOT_CAMP_PHASE_ADVANCED = "boot_camp_phase_advanced"  # AD-509

    # AD-486: Holodeck Birth Chamber phase events
    HOLODECK_AGENT_ADMITTED = "holodeck_agent_admitted"
    HOLODECK_PHASE_ENTERED = "holodeck_phase_entered"
    HOLODECK_PHASE_GATE_PASSED = "holodeck_phase_gate_passed"
    HOLODECK_PHASE_GATE_BLOCKED = "holodeck_phase_gate_blocked"
    HOLODECK_GRADUATION = "holodeck_graduation"
    HOLODECK_AFFECTIVE_BASELINE_OBSERVED = "holodeck_affective_baseline_observed"

    # AD-539b: Holodeck scenario generation from skill gaps
    HOLODECK_SCENARIO_GENERATED = "holodeck_scenario_generated"
    HOLODECK_SCENARIO_REGISTERED = "holodeck_scenario_registered"
    HOLODECK_SCENARIO_GAP_LINKED = "holodeck_scenario_gap_linked"
    HOLODECK_SCENARIO_OUTCOME_RECORDED = "holodeck_scenario_outcome_recorded"

    # AD-510: Holodeck team simulations — group discovery & collaboration
    TEAM_SCENARIO_REGISTERED = "team_scenario_registered"
    TEAM_SIMULATION_STARTED = "team_simulation_started"
    TEAM_SIMULATION_ROLE_ROTATED = "team_simulation_role_rotated"
    TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED = "team_simulation_communication_constraint_applied"
    TEAM_SIMULATION_DEBRIEF_RECORDED = "team_simulation_debrief_recorded"
    TEAM_SIMULATION_COMPLETED = "team_simulation_completed"

    # ── Discovery-Based Capability Building (AD-512) ───────────────
    DISCOVERY_SCENARIO_OFFERED = "discovery_scenario_offered"  # AD-512a registry
    DISCOVERY_OUTCOME_RECORDED = "discovery_outcome_recorded"  # AD-512b StrengthMap
    STRENGTH_MAP_UPDATED = "strength_map_updated"  # AD-512b StrengthMap
    CAPABILITY_CONFIDENCE_UPDATED = "capability_confidence_updated"  # AD-512e
    ZPD_SCENARIO_CALIBRATED = "zpd_scenario_calibrated"  # AD-512f

    # ── Statistical Process Control (AD-522) ───────────────────────
    SPC_RULE_VIOLATED = "spc_rule_violated"  # AD-522 v1

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


# ---------------------------------------------------------------------------
# OS-activity sensor (AD-1054)
# ---------------------------------------------------------------------------

@dataclass
class OSActivityEvent(BaseEvent):
    """AD-1054: a desktop OS foreground-window activity sample (pure sensor).

    Active-window METADATA ONLY -- app name + window title + optional app
    executable path / browser url. NO keystrokes, screen content, or clipboard.
    ``ts`` is the client (watcher) capture time; ``BaseEvent.timestamp`` is the
    server emit time. Emitted in-process; not persisted/exported by this AD.
    """

    event_type: EventType = field(default=EventType.OS_ACTIVITY, init=False)
    active_app: str = ""
    window_title: str = ""
    app_path: str = ""
    url: str = ""
    ts: float = 0.0
