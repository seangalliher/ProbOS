"""AD-1195 (#1132) M2: every EventType member is declared or grandfathered, checked at import.

``probos.event_persistence`` holds the declarations and the frozen snapshot of
the members that have none; ``probos.events`` calls ``assert_complete`` right
after the class. The import-failure cases run in a fresh interpreter, because
reloading ``probos.events`` in-process would leave a second EventType class for
the rest of the session.
"""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

import probos
from probos import event_persistence as ep
from probos.event_persistence import Persistence
from probos.events import EventType
from probos.substrate.durable_events import ROUTED_VALUES

_SRC = Path(probos.__file__).resolve().parents[1]
_IMPORTED = "probos.events imported from"
_UNDECLARED_VICTIM = "NODE_START"
_DECLARED_MEMBER = "THREAT_DETECTED"
_STALE = "NOT_AN_EVENT_TYPE_MEMBER"

# DECL-3: a deliberate literal restatement of the AD-1195 snapshot. It may only
# shrink, when a member is promoted into DECLARATIONS. Never add a name here.
_GOLDEN_GRANDFATHERED = frozenset({
    "ACTION_RISK_DENIED",
    "AGENTIC_LOOP_ITERATION",
    "AGENT_CAPACITY_APPROACHING",
    "AGENT_REMOVED",
    "AGENT_STATE",
    "AGENT_VERSION_PROMOTED",
    "ANOMALY_WINDOW_CLOSED",
    "ANOMALY_WINDOW_OPENED",
    "APPEARANCE_REVISION_MEDIATED",
    "ARTIFACT_VERSION_ADDED",
    "ASSIGNMENT_COMPLETED",
    "ASSIGNMENT_CREATED",
    "ASSIGNMENT_UPDATED",
    "ATTACHMENT_REAPED",
    "ATTACHMENT_STORE_DISK_FULL",
    "BEHAVIORAL_METRICS_UPDATED",
    "BILLET_ASSIGNED",
    "BILLET_VACATED",
    "BILL_ACTIVATED",
    "BILL_CANCELLED",
    "BILL_COMPLETED",
    "BILL_FAILED",
    "BILL_ROLE_ASSIGNED",
    "BILL_STEP_COMPLETED",
    "BILL_STEP_FAILED",
    "BILL_STEP_STARTED",
    "BOOKING_CANCELLED",
    "BOOKING_COMPLETED",
    "BOOKING_STARTED",
    "BOOT_CAMP_ACTIVATED",
    "BOOT_CAMP_GRADUATION",
    "BOOT_CAMP_PHASE_ADVANCE",
    "BOOT_CAMP_PHASE_ADVANCED",
    "BOOT_CAMP_TIMEOUT",
    "BRIDGE_ALERT",
    "BROWSER_ACTION_EXECUTED",
    "BROWSER_BRIDGE_CONNECTED",
    "BROWSER_BRIDGE_DISCONNECTED",
    "BROWSER_BRIDGE_REFUSED",
    "BROWSER_COMPUTE_USE_CLICK_ABORTED",
    "BROWSER_COMPUTE_USE_CLICK_EXECUTED",
    "BROWSER_COMPUTE_USE_CLICK_PROPOSED",
    "BROWSER_COMPUTE_USE_CLICK_VERIFIED",
    "BROWSER_DOWNLOAD_REQUESTED",
    "BROWSER_EVAL_JS_EXECUTED",
    "BROWSER_FILE_UPLOAD_REQUESTED",
    "BROWSER_INPUT_FORWARDED",
    "BROWSER_INPUT_REFUSED",
    "BROWSER_RECORDING_EXPIRED",
    "BROWSER_RECORDING_FAILED",
    "BROWSER_RECORDING_STARTED",
    "BROWSER_RECORDING_STOPPED",
    "BROWSER_SESSION_CLOSED",
    "BROWSER_SESSION_OPENED",
    "BROWSER_STREAM_CLOSED",
    "BROWSER_STREAM_FRAME_DROPPED",
    "BROWSER_STREAM_OPENED",
    "BROWSER_VERIFY_OBSERVED",
    "BUILD_FAILURE",
    "BUILD_GENERATED",
    "BUILD_PROGRESS",
    "BUILD_QUEUE_ITEM",
    "BUILD_QUEUE_UPDATE",
    "BUILD_RESOLVED",
    "BUILD_STARTED",
    "BUILD_SUCCESS",
    "CAPABILITY_ACCESS_RESOLVED",
    "CAPABILITY_CONFIDENCE_UPDATED",
    "CAPABILITY_GAP_PREDICTED",
    "CAPABILITY_PROPOSAL_APPROVED",
    "CAPABILITY_PROPOSAL_CREATED",
    "CAPABILITY_PROPOSAL_REJECTED",
    "CAPTAINS_LOG_GENERATED",
    "CAPTAIN_DM_PRIORITY_QUEUED",
    "CASCADE_CONFABULATION_DETECTED",
    "CHANNEL_DELIVERY_FAILED",
    "CHANNEL_MESSAGE_RECEIVED",
    "CHAT_THREAD_MESSAGE_APPENDED",
    "CIRCUIT_BREAKER_TRIP",
    "COMMITMENT_RECORDED",
    "COMPENSATION_TRIGGERED",
    "CONDUCT_VIOLATION",
    "CONFABULATION_SUPPRESSED",
    "CONSULTATION_COMPLETED",
    "CONSULTATION_FAILED",
    "CONSULTATION_REQUESTED",
    "CONSULTATION_TIMEOUT",
    "CONTENT_CONTAGION_FLAGGED",
    "CONTENT_QUARANTINE_RECOMMENDED",
    "CONTEXT_PROVENANCE_INJECTED",
    "CONTRASTIVE_RECALL",
    "CONVERGENCE_DETECTED",
    "CORROBORATION_PROVENANCE_VALIDATED",
    "CORROBORATION_VERIFIED",
    "COUNSELOR_ASSESSMENT",
    "COUNSELOR_INTERVENTION",
    "CREATIVE_SKILL_AFFINITY_QUERIED",
    "CREATIVE_WORK_PUBLISHED",
    "CREDENTIAL_DELETED",
    "CREDENTIAL_FILL_REQUESTED",
    "CREDENTIAL_STORED",
    "CREW_ORCHESTRATION_STARTED",
    "CROSS_AGENT_DIVERGENCE_OBSERVED",
    "CURRICULUM_MODULE_QUERIED",
    "DAMAGE_CONTROL_ACTIVATED",
    "DECISION_QUEUE_PAUSED",
    "DECOMPOSE_COMPLETE",
    "DECOMPOSE_START",
    "DELIBERATION_ARGUMENT_SUBMITTED",
    "DELIBERATION_INITIATED",
    "DELIBERATION_RESOLVED",
    "DEPT_PROFILE_APPLIED",
    "DESIGN_FAILURE",
    "DESIGN_PROGRESS",
    "DESIGN_STARTED",
    "DISCLOSURE_FILTERED",
    "DISCOVERY_OUTCOME_RECORDED",
    "DISCOVERY_SCENARIO_OFFERED",
    "DIVERGENCE_DETECTED",
    "DIVERGENCE_OBSERVED_CHAIN",
    "DM_CONVERGENCE_DETECTED",
    "DREAM_COMPLETE",
    "DREAM_MANIFEST_UPDATED",
    "DUTY_SCOPE_QUERIED",
    "EMERGENCE_METRICS_UPDATED",
    "ENGINEERING_SENSOR_REPORT",
    "EPISODE_REJECTED",
    "EPS_BUDGET_EXCEEDED",
    "EPS_REALLOCATION",
    "ESCALATION_EXHAUSTED",
    "ESCALATION_RESOLVED",
    "ESCALATION_START",
    "EVOLUTION_LESSON_RECORDED",
    "EXOGENOUS_ALERT",
    "EXOGENOUS_CONSENSUS",
    "EXOGENOUS_GOSSIP",
    "EXOGENOUS_MENTION",
    "EXOGENOUS_SAFETY",
    "EXOGENOUS_SCENE_CHANGE",
    "FAULT_REPORTED",
    "FAULT_RESOLVED",
    "FEDERATION_DESIGNED_AGENT_RECEIVED",
    "FEDERATION_EPISODE_REJECTED",
    "FEDERATION_PEER_DISCOVERED",
    "FEDERATION_PEER_RECOVERED",
    "FEDERATION_PEER_UNREACHABLE",
    "FEDERATION_RECALL_DP_REDACTED",
    "FLEET_GAP_SNAPSHOT_TAKEN",
    "FORCED_CONSOLIDATION_TRIGGERED",
    "FRAGMENTATION_WARNING",
    "GAME_COMPLETED",
    "GAME_PREFERENCE_RECORDED",
    "GAME_UPDATE",
    "GAP_IDENTIFIED",
    "GAP_REMEDIATION_RECORDED",
    "GROUPTHINK_WARNING",
    "HEBBIAN_UPDATE",
    "HOLODECK_AFFECTIVE_BASELINE_OBSERVED",
    "HOLODECK_AGENT_ADMITTED",
    "HOLODECK_GRADUATION",
    "HOLODECK_PHASE_ENTERED",
    "HOLODECK_PHASE_GATE_BLOCKED",
    "HOLODECK_PHASE_GATE_PASSED",
    "HOLODECK_SCENARIO_GAP_LINKED",
    "HOLODECK_SCENARIO_GENERATED",
    "HOLODECK_SCENARIO_OUTCOME_RECORDED",
    "HOLODECK_SCENARIO_REGISTERED",
    "HYBRID_DISPATCH_BROADCAST",
    "HYBRID_DISPATCH_DIRECT",
    "IDEA_CAPTURED",
    "INFODYNAMIC_REPORT",
    "INITIATIVE_PROPOSAL",
    "KNOWLEDGE_CONFIRMED",
    "KNOWLEDGE_CONTRADICTED",
    "KNOWLEDGE_PINNED",
    "KNOWLEDGE_TIER_LOADED",
    "KNOWLEDGE_UNPINNED",
    "LEADERSHIP_DIVERGENCE",
    "LEARNED_SHORTCUT_HIT",
    "LEARNED_SHORTCUT_REGISTERED",
    "LIMDU_RECOMMENDED",
    "LLM_HEALTH_CHANGED",
    "MAINTENANCE_SCHEDULED",
    "MCP_APP_EXTERNAL_DISCOVERED",
    "MCP_APP_RESOURCE_READ",
    "MCP_APP_TOOL_INVOKED",
    "MCP_APP_TOOL_REGISTERED",
    "MEMORY_ANCHOR_MISMATCH",
    "MEMORY_INJECTION_SUSPECTED",
    "MEMORY_LEAK_SUSPECTED",
    "MEMORY_PROVENANCE_GAP",
    "MEMORY_RECALL_ANOMALY",
    "MEMORY_REFS_DISPATCHED",
    "MODEL_FALLBACK",
    "MODEL_ROUTED",
    "NODE_COMPLETE",
    "NODE_FAILED",
    "NODE_START",
    "NOTEBOOK_QUALITY_UPDATED",
    "NOTEBOOK_SELF_REPETITION",
    "NOTIFICATION",
    "NOTIFICATION_ACK",
    "NOTIFICATION_SNAPSHOT",
    "OBSERVABILITY_BRIDGE_FAILED",
    "OBSERVABILITY_SNAPSHOT_PUBLISHED",
    "OBSERVABLE_STATE_MISMATCH",
    "ONTOLOGY_PROBE_RATE_LIMITED",
    "ONTOLOGY_PROBE_RECORDED",
    "OPTIMIZATION_PROPOSAL_APPLIED",
    "OPTIMIZATION_PROPOSAL_REVERTED",
    "OPTIMIZATION_REGRESSION_DETECTED",
    "ORACLE_LOOKUP_DISPATCHED",
    "ORDER_ACKNOWLEDGED",
    "ORDER_DECLINED",
    "ORDER_ISSUED",
    "ORDER_REFUSED",
    "ORDER_REJECTED",
    "OS_ACTIVITY",
    "PAIRING_APPROVED",
    "PAIRING_REQUESTED",
    "PAIRING_REVOKED",
    "PARALLEL_DISPATCH_BLOCKED",
    "PARALLEL_DISPATCH_PROGRESS",
    "PARALLEL_DISPATCH_STARTED",
    "PEER_OBSERVATION_CERTIFICATION_REVOKED",
    "PEER_OBSERVATION_CERTIFIED",
    "PEER_OBSERVATION_DECLINED",
    "PEER_OBSERVATION_INTERVENTION_TIER_1",
    "PEER_OBSERVATION_INTERVENTION_TIER_2",
    "PEER_OBSERVATION_INTERVENTION_TIER_3",
    "PEER_OBSERVATION_PATTERN_FLAGGED",
    "PEER_OBSERVATION_PERMISSION_DENIED",
    "PEER_OBSERVATION_PERMISSION_GRANTED",
    "PEER_OBSERVATION_PERMISSION_REQUESTED",
    "PEER_OBSERVATION_RECORDED",
    "PEER_REPETITION_DETECTED",
    "PERFORMANCE_THRESHOLD_BREACHED",
    "PIVOT_REFINE_DECIDED",
    "PLAN_OF_DAY_GENERATED",
    "PREDICTION_ERROR_RECORDED",
    "PREDICTION_FLUSHED",
    "PREDICTION_HIT",
    "PREDICTION_MISS",
    "PREFLIGHT_FAILED",
    "PROACTIVE_THOUGHT",
    "PROCEDURE_FALLBACK_LEARNING",
    "QUALIFICATION_BASELINE_SET",
    "QUALIFICATION_DRIFT_DETECTED",
    "QUALIFICATION_GATE_BLOCKED",
    "QUALIFICATION_TEST_COMPLETE",
    "QUALITY_CONCERN",
    "QUEUE_ITEM_DEQUEUED",
    "QUEUE_ITEM_ENQUEUED",
    "QUEUE_ITEM_SHED",
    "QUEUE_OVERFLOW",
    "READY_ROOM_SESSION_STARTED",
    "RECREATION_GAME_REGISTERED",
    "RECREATION_SPECTATOR_COMMENTARY",
    "RECREATION_SPECTATOR_JOINED",
    "RED_TEAM_CAMPAIGN_COMPLETE",
    "REGISTER_SHIFT_DENIED",
    "REGISTER_SHIFT_GRANTED",
    "REMINISCENCE_SESSION_COMPLETE",
    "RENDER_DIVERGENCE_OBSERVED",
    "RESOURCE_ALLOCATED",
    "RETRIEVAL_PRACTICE_CONCERN",
    "SANDBOX_CAPABILITY_DENIED",
    "SANDBOX_LIMIT_EXCEEDED",
    "SCHEDULED_TASK_CANCELLED",
    "SCHEDULED_TASK_CREATED",
    "SCHEDULED_TASK_DAG_RESUMED",
    "SCHEDULED_TASK_DAG_STALE",
    "SCHEDULED_TASK_FIRED",
    "SCHEDULED_TASK_UPDATED",
    "SELF_MODEL_DRIFT",
    "SELF_MOD_PROGRESS",
    "SELF_MOD_RETRY_COMPLETE",
    "SELF_MONITORING_CONCERN",
    "SELF_RENDER_COHERENCE_OBSERVED",
    "SENSORIUM_BUDGET_EXCEEDED",
    "SERVICE_TIER_DEGRADED",
    "SERVICE_TIER_RESTORED",
    "SHIP_STATE_SNAPSHOT_CAPTURED",
    "SKILL_ACQUIRED",
    "SKILL_BLOCKED",
    "SKILL_DECAY",
    "SKILL_EXERCISED",
    "SKILL_LOADED",
    "SKILL_REGRESSION",
    "SKILL_REQUEST_COMPLETED",
    "SKILL_REQUEST_DECIDED",
    "SKILL_REQUEST_FILED",
    "SKILL_REQUEST_TRAINING_STARTED",
    "SPC_RULE_VIOLATED",
    "STRENGTH_MAP_UPDATED",
    "SUBSYSTEM_PAUSED",
    "SUBSYSTEM_RESUMED",
    "SUBTASK_COMPLETED",
    "SUB_TASK_CHAIN_COMPLETED",
    "SUB_TASK_COMPLETED",
    "SYSTEM_MODE",
    "TASK_CREATED",
    "TASK_EVENT_DISPATCHED",
    "TASK_EVENT_UNROUTABLE",
    "TASK_EXECUTION_COMPLETE",
    "TASK_ROUTED",
    "TASK_SCHEDULED",
    "TASK_UPDATED",
    "TEAM_SCENARIO_REGISTERED",
    "TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED",
    "TEAM_SIMULATION_COMPLETED",
    "TEAM_SIMULATION_DEBRIEF_RECORDED",
    "TEAM_SIMULATION_ROLE_ROTATED",
    "TEAM_SIMULATION_STARTED",
    "TELEMETRY_REPORT",
    "THREAD_PRIORITY_SCORED",
    "TIERED_TRUST_INITIALIZED",
    "TOOL_CONTEXT_CREATED",
    "TOOL_FAILURE_PATTERN",
    "TOOL_LOCKED",
    "TOOL_UNLOCKED",
    "TRANSPORTER_ASSEMBLED",
    "TRANSPORTER_CHUNK_DONE",
    "TRANSPORTER_DECOMPOSED",
    "TRANSPORTER_EXECUTION_DONE",
    "TRANSPORTER_VALIDATED",
    "TRANSPORTER_WAVE_START",
    "TRUST_CASCADE_WARNING",
    "TRUST_UPDATE",
    "VALIDATION_OUTCOME_VERIFIED",
    "VALIDATION_RECONCILIATION_REQUESTED",
    "VERIFICATION_FAILED",
    "VERIFICATION_PASSED",
    "VERIFICATION_REJECTED",
    "VISION_CAPABILITY_PROPOSED",
    "VISION_CAPABILITY_RESOLVED",
    "VISION_INTENT_DIVERGENCE_OBSERVED",
    "WARD_ROOM_ECHO_DETECTED",
    "WARD_ROOM_ENDORSEMENT",
    "WARD_ROOM_HEBBIAN_DECAYED",
    "WARD_ROOM_HEBBIAN_UPDATED",
    "WARD_ROOM_POST_CREATED",
    "WARD_ROOM_PRUNED",
    "WARD_ROOM_THREAD_CREATED",
    "WARD_ROOM_THREAD_UPDATED",
    "WORKFLOW_STARTED",
    "WORKING_MEMORY_NOTE_RECORDED",
    "WORKSPACE_TERM_REGISTERED",
    "WORK_ITEM_ASSIGNED",
    "WORK_ITEM_CLAIMED",
    "WORK_ITEM_CREATED",
    "WORK_ITEM_RECONCILED",
    "WORK_ITEM_UPDATED",
    "WRONG_CONVERGENCE_DETECTED",
    "ZONE_RECOVERY",
    "ZPD_SCENARIO_CALIBRATED",
})

# DECL-4: the 28 routed values of the contract's DURABLE table (section 3.8).
_CONTRACT_ROUTED_VALUES = frozenset({
    "capability_request_filed", "capability_request_decided", "capability_request_fulfilled",
    "tool_permission_denied", "tool_intervention_required",
    "self_mod_started", "self_mod_import_approved", "self_mod_success", "self_mod_failure",
    "design_generated", "ship_named",
    "threat_detected", "trust_integrity_violation", "security_input_rejected", "egress_blocked",
    "boundary_violation_detected", "classification_disclosure_blocked", "credential_read",
    "credential_read_denied", "secret_rotated", "credential_tier_denied",
    "mcp_bridge_invoke", "mcp_bridge_failed",
    "work_item_status_changed", "work_item_quarantined", "crew_task_started", "crew_task_completed",
    "config_changed",
})

_CONTRACT_OPERATIONAL = frozenset({
    "AGENTIC_TOOL_CALL_STARTED", "AGENTIC_TOOL_CALL_COMPLETED", "AUDIT_RECORDED", "AUDIT_PERSISTED",
})


def _import_events(*mutation: str) -> subprocess.CompletedProcess[str]:
    """Apply ``mutation`` to probos.event_persistence, then import probos.events, in a new interpreter."""
    code = "\n".join([
        "import probos",
        "import probos.event_persistence as ep",
        *mutation,
        "import probos.events",
        f"print({_IMPORTED!r}, probos.__file__)",
    ])
    env = {**os.environ, "PYTHONPATH": str(_SRC)}
    return subprocess.run(
        [sys.executable, "-P", "-c", code],
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )


def _assert_unmutated_import_succeeds() -> None:
    """The premise of DECL-2: the same subprocess, unmutated, imports this checkout's probos."""
    clean = _import_events()
    assert clean.returncode == 0, clean.stderr
    marker, _, path = clean.stdout.strip().partition(" from ")
    assert f"{marker} from" == _IMPORTED, clean.stdout
    assert Path(path).resolve().is_relative_to(_SRC), path


def _problem_lines(text: str, kind: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith(f"- {kind}")]


# ── DECL-1 ───────────────────────────────────────────────────────────────────


def test_every_member_is_declared_or_grandfathered_never_both() -> None:
    """DECL-1: 396 members = 40 declared + 356 grandfathered, disjoint."""
    names = set(EventType.__members__)
    declared = set(ep.DECLARATIONS)
    assert not declared & ep.GRANDFATHERED
    assert declared | ep.GRANDFATHERED == names
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (396, 40, 356)
    assert isinstance(ep.GRANDFATHERED, frozenset)
    assert ep.assert_complete(EventType.__members__) is None


# ── DECL-2 ───────────────────────────────────────────────────────────────────


def test_import_fails_for_undeclared_member_outside_snapshot() -> None:
    """DECL-2: a member neither declared nor grandfathered fails the import, and is named."""
    _assert_unmutated_import_succeeds()
    assert _UNDECLARED_VICTIM in EventType.__members__
    assert _UNDECLARED_VICTIM not in ep.DECLARATIONS
    failed = _import_events(
        f"ep.GRANDFATHERED = getattr(ep, 'GRANDFATHERED', frozenset()) - {{{_UNDECLARED_VICTIM!r}}}",
    )
    assert failed.returncode != 0, failed.stdout
    assert _IMPORTED not in failed.stdout
    assert "EventPersistenceContractError" in failed.stderr, failed.stderr
    lines = _problem_lines(failed.stderr, "undeclared")
    assert len(lines) == 1, failed.stderr
    assert lines[0].rstrip().endswith(f": {_UNDECLARED_VICTIM}"), lines


def test_import_fails_for_a_member_declared_and_grandfathered() -> None:
    """DECL-2: a member in both tables fails the import, and is named."""
    _assert_unmutated_import_succeeds()
    assert _DECLARED_MEMBER in ep.DECLARATIONS
    failed = _import_events(
        f"ep.GRANDFATHERED = getattr(ep, 'GRANDFATHERED', frozenset()) | {{{_DECLARED_MEMBER!r}}}",
    )
    assert failed.returncode != 0, failed.stdout
    assert _IMPORTED not in failed.stdout
    assert "EventPersistenceContractError" in failed.stderr, failed.stderr
    lines = [line for line in _problem_lines(failed.stderr, "in both") if _DECLARED_MEMBER in line]
    assert len(lines) == 1, failed.stderr


# ── DECL-3 ───────────────────────────────────────────────────────────────────


def test_snapshot_only_shrinks() -> None:
    """DECL-3: GRANDFATHERED may lose names (promotion) but never gain one."""
    assert len(_GOLDEN_GRANDFATHERED) == 356
    assert ep.GRANDFATHERED <= _GOLDEN_GRANDFATHERED, sorted(ep.GRANDFATHERED - _GOLDEN_GRANDFATHERED)


# ── DECL-4 ───────────────────────────────────────────────────────────────────


def test_declared_counts_and_routed_values_match_the_contract() -> None:
    """DECL-4: 36 DURABLE (8 owner, 28 routed), 4 OPERATIONAL, 0 DIAGNOSTIC."""
    counts = Counter(ep.DECLARATIONS.values())
    assert counts == {Persistence.DURABLE: 36, Persistence.OPERATIONAL: 4}
    assert counts[Persistence.DIAGNOSTIC] == 0
    assert len(ep.OWNER_RECORDS) == 8
    assert ROUTED_VALUES == _CONTRACT_ROUTED_VALUES
    assert len(ROUTED_VALUES) == 28
    operational = {name for name, cls in ep.DECLARATIONS.items() if cls is Persistence.OPERATIONAL}
    assert operational == _CONTRACT_OPERATIONAL
    assert not any(ep.is_routed(name) for name in operational)
    values = {member.value for member in EventType}
    assert ep.ROUTED_CATEGORY not in values
    assert ep.DROP_MARKER_EVENT not in values


# ── DECL-5 ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("table", ["DECLARATIONS", "GRANDFATHERED", "OWNER_RECORDS"])
def test_a_stale_name_in_any_table_raises(table: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """DECL-5: a declared, grandfathered or owner name that is not a member raises."""
    assert ep.assert_complete(EventType.__members__) is None
    assert _STALE not in EventType.__members__
    if table == "DECLARATIONS":
        monkeypatch.setattr(ep, table, {**ep.DECLARATIONS, _STALE: Persistence.OPERATIONAL})
    elif table == "GRANDFATHERED":
        monkeypatch.setattr(ep, table, ep.GRANDFATHERED | {_STALE})
    else:
        monkeypatch.setattr(ep, table, {**ep.OWNER_RECORDS, _STALE: ("owner", "stale_pair")})
    with pytest.raises(ep.EventPersistenceContractError) as raised:
        ep.assert_complete(EventType.__members__)
    lines = _problem_lines(str(raised.value), "stale")
    assert len(lines) == 1, str(raised.value)
    assert table in lines[0] and lines[0].rstrip().endswith(f": {_STALE}"), lines


def test_an_owner_member_not_declared_durable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """DECL-5: an OWNER_RECORDS name whose class is not DURABLE raises."""
    assert "CONSENSUS" in ep.OWNER_RECORDS
    monkeypatch.setattr(ep, "DECLARATIONS", {**ep.DECLARATIONS, "CONSENSUS": Persistence.OPERATIONAL})
    with pytest.raises(ep.EventPersistenceContractError) as raised:
        ep.assert_complete(EventType.__members__)
    lines = _problem_lines(str(raised.value), "in OWNER_RECORDS but not declared DURABLE")
    assert len(lines) == 1 and lines[0].rstrip().endswith(": CONSENSUS"), str(raised.value)


def test_the_error_lists_each_problem_sorted_with_a_remedy(monkeypatch: pytest.MonkeyPatch) -> None:
    """DECL-5: every problem kind is listed, names sorted, each with a remedy line."""
    monkeypatch.setattr(
        ep, "GRANDFATHERED", (ep.GRANDFATHERED - {"NODE_START", "NODE_FAILED"}) | {_DECLARED_MEMBER},
    )
    with pytest.raises(ep.EventPersistenceContractError) as raised:
        ep.assert_complete(list(EventType.__members__))
    message = str(raised.value)
    assert _problem_lines(message, "undeclared")[0].rstrip().endswith(": NODE_FAILED, NODE_START")
    assert _problem_lines(message, "in both")[0].rstrip().endswith(f": {_DECLARED_MEMBER}")
    assert message.count("remedy:") == 2
    assert "probos/event_persistence.py" in message


def test_no_member_names_leave_every_table_stale() -> None:
    """DECL-5 boundary: an empty member set makes every declared and grandfathered name stale."""
    with pytest.raises(ep.EventPersistenceContractError) as raised:
        ep.assert_complete(())
    message = str(raised.value)
    assert len(_problem_lines(message, "stale")) == 3
    assert not _problem_lines(message, "undeclared")


# ── DECL-6 ───────────────────────────────────────────────────────────────────


def test_every_member_keeps_str_equality_and_pickle_identity() -> None:
    """DECL-6: the import-time check leaves EventType itself untouched."""
    protocols = range(pickle.HIGHEST_PROTOCOL + 1)
    broken = [
        member.name for member in EventType
        if not (
            isinstance(member, str)
            and member == member.value
            and all(pickle.loads(pickle.dumps(member, protocol)) is member for protocol in protocols)
        )
    ]
    assert broken == []
    assert len(EventType) == 396
