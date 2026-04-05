"""Typed result dataclasses for startup phase outputs (AD-517).

Each phase function returns one of these so ProbOSRuntime.start() can
assign created services to ``self``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.acm import AgentCapitalService
    from probos.agent_onboarding import AgentOnboardingService
    from probos.assignment import AssignmentService
    from probos.bridge_alerts import BridgeAlertService
    from probos.build_dispatcher import BuildDispatcher
    from probos.build_queue import BuildQueue
    from probos.cognitive.agent_patcher import AgentPatcher
    from probos.cognitive.behavioral_monitor import BehavioralMonitor
    from probos.cognitive.codebase_index import CodebaseIndex
    from probos.cognitive.correction_detector import CorrectionDetector
    from probos.cognitive.dreaming import DreamingEngine, DreamScheduler
    from probos.cognitive.emergent_detector import EmergentDetector
    from probos.cognitive.emergence_metrics import EmergenceMetricsEngine
    from probos.cognitive.feedback import FeedbackEngine
    from probos.cognitive.journal import CognitiveJournal
    from probos.cognitive.self_mod import SelfModificationPipeline
    from probos.cognitive.strategy_advisor import StrategyAdvisor
    from probos.cognitive.task_scheduler import TaskScheduler
    from probos.conn import ConnManager
    from probos.directive_store import DirectiveStore
    from probos.dream_adapter import DreamAdapter
    from probos.identity import AgentIdentityRegistry
    from probos.initiative import InitiativeEngine
    from probos.knowledge.records_store import RecordsStore
    from probos.knowledge.semantic import SemanticKnowledgeLayer
    from probos.knowledge.store import KnowledgeStore
    from probos.ontology import VesselOntologyService
    from probos.persistent_tasks import PersistentTaskStore
    from probos.proactive import ProactiveCognitiveLoop
    from probos.self_mod_manager import SelfModManager
    from probos.service_profile import ServiceProfileStore
    from probos.sif import StructuralIntegrityField
    from probos.skill_framework import AgentSkillService, SkillRegistry
    from probos.substrate.scaler import PoolScaler
    from probos.task_tracker import TaskTracker
    from probos.ward_room import WardRoomService
    from probos.ward_room_router import WardRoomRouter
    from probos.warm_boot import WarmBootService
    from probos.watch_rotation import NightOrdersManager, WatchManager
    from probos.workforce import WorkItemStore


@dataclass
class InfrastructureResult:
    """Services created by the infrastructure boot phase."""

    identity_registry: "AgentIdentityRegistry"
    event_prune_task: asyncio.Task[None]


@dataclass
class AgentFleetResult:
    """Services created by the agent fleet creation phase."""

    onboarding_service: "AgentOnboardingService"
    codebase_index: "CodebaseIndex"
    red_team_agents: list[Any]


@dataclass
class FleetOrganizationResult:
    """Services created by the fleet organization phase."""

    pool_scaler: "PoolScaler | None"
    federation_bridge: Any  # FederationBridge | None
    federation_transport: Any  # FederationTransport | None


@dataclass
class CognitiveServicesResult:
    """Services created by the cognitive services phase."""

    self_mod_pipeline: "SelfModificationPipeline | None"
    behavioral_monitor: "BehavioralMonitor | None"
    system_qa: Any  # SystemQAAgent | None
    feedback_engine: "FeedbackEngine"
    correction_detector: "CorrectionDetector"
    agent_patcher: "AgentPatcher | None"
    knowledge_store: "KnowledgeStore | None"
    warm_boot_service: "WarmBootService | None"
    records_store: "RecordsStore | None"
    strategy_advisor: "StrategyAdvisor | None"
    cold_start: bool
    fresh_boot: bool
    lifecycle_state: str
    stasis_duration: float
    previous_session: dict[str, Any] | None
    semantic_layer: "SemanticKnowledgeLayer | None"
    activation_tracker: Any = None  # AD-567d


@dataclass
class DreamingResult:
    """Services created by the dreaming & detection phase."""

    dream_scheduler: "DreamScheduler | None"
    dreaming_engine: "DreamingEngine | None"
    emergent_detector: "EmergentDetector"
    emergence_metrics_engine: "EmergenceMetricsEngine"
    task_scheduler: "TaskScheduler"
    flush_task: asyncio.Task[None]
    notebook_quality_engine: Any = None  # AD-555
    retrieval_practice_engine: Any = None  # AD-541c


@dataclass
class StructuralServicesResult:
    """Services created by the structural services phase."""

    sif: "StructuralIntegrityField"
    initiative: "InitiativeEngine"
    build_queue: "BuildQueue"
    build_dispatcher: "BuildDispatcher"
    task_tracker: "TaskTracker"
    service_profiles: "ServiceProfileStore"
    directive_store: "DirectiveStore | None"


@dataclass
class CommunicationResult:
    """Services created by the communication phase."""

    persistent_task_store: "PersistentTaskStore | None"
    work_item_store: "WorkItemStore | None"
    ward_room: "WardRoomService | None"
    assignment_service: "AssignmentService | None"
    bridge_alerts: "BridgeAlertService | None"
    cognitive_journal: "CognitiveJournal | None"
    skill_registry: "SkillRegistry"
    skill_service: "AgentSkillService"
    acm: "AgentCapitalService"
    ontology: "VesselOntologyService | None"


@dataclass
class FinalizationResult:
    """Services created by the finalization phase."""

    conn_manager: "ConnManager | None"
    night_orders_mgr: "NightOrdersManager | None"
    watch_manager: "WatchManager | None"
    proactive_loop: "ProactiveCognitiveLoop | None"
    ward_room_router: "WardRoomRouter | None"
    self_mod_manager: "SelfModManager | None"
    dream_adapter: "DreamAdapter"
