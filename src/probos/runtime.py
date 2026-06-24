"""ProbOS runtime — top-level orchestrator for substrate + mesh + consensus layers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid as _uuid
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probos.events import BaseEvent, EventType
from probos.agents.directory_list import DirectoryListAgent
from probos.agents.code_search import CodeSearchAgent
from probos.agents.code_runner import CodeRunnerAgent
from probos.agents.file_reader import FileReaderAgent
from probos.agents.file_search import FileSearchAgent
from probos.agents.file_writer import FileWriterAgent
from probos.agents.heartbeat_monitor import SystemHeartbeatAgent
from probos.agents.http_fetch import HttpFetchAgent
from probos.service_profile import ServiceProfileStore
from probos.directive_store import DirectiveStore
from probos.cognitive.standing_orders import set_directive_store
from probos.agents.introspect import IntrospectionAgent
from probos.agents.quartermaster import QuartermasterAgent  # AD-876
from probos.agents.utility.nl_graph_query_agent import NLGraphQueryAgent  # AD-691
from probos.agents.utility.avatar_agents import AvatarRendererAgent  # AD-721i
from probos.agents.red_team import RedTeamAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.agents.utility import (
    WebSearchAgent,
    PageReaderAgent,
    WeatherAgent,
    NewsAgent,
    TranslateAgent,
    SummarizerAgent,
    CalculatorAgent,
    TodoAgent,
    NoteTakerAgent,
    SchedulerAgent,
)
from probos.agents.system_qa import SystemQAAgent
from probos.agents.medical import (
    VitalsMonitorAgent,
    DiagnosticianAgent,
    SurgeonAgent,
    PharmacistAgent,
    PathologistAgent,
)
from probos.agents.science import (
    DataAnalystAgent,
    SystemsAnalystAgent,
    ResearchSpecialistAgent,
)
from probos.cognitive.builder import BuilderAgent
from probos.cognitive.builder_specialists import (
    BackendSWEAgent,
    DataSWEAgent,
    FrontendSWEAgent,
    InfrastructureSWEAgent,
    TestSWEAgent,
)
from probos.cognitive.architect import ArchitectAgent
from probos.cognitive.scout import ScoutAgent
from probos.cognitive.counselor import CounselorAgent
from probos.cognitive.self_similarity_history import SelfSimilarityHistory
from probos.cognitive.yeoman import YeomanAgent
from probos.boot_camp import BootCampCoordinator
from probos.cognitive.security_officer import SecurityAgent
from probos.cognitive.operations_officer import OperationsAgent
from probos.cognitive.engineering_officer import EngineeringAgent
from probos.integrations.m365_token_manager import M365TokenManager  # AD-749
from probos.integrations.m365_connector import (  # AD-749
    OutlookAgent, TeamsAgent, CalendarAgent, SharePointAgent, OneDriveAgent
)
from probos.integrations.template_registry import TemplateRegistry  # AD-755
from probos.skill_framework import DocxAgent, PptxAgent, XlsxAgent  # AD-755
from probos.integrations.semantic_mapper import SemanticMapper  # AD-750
from probos.knowledge.semantic_store import SemanticStore  # AD-750
from probos.cognitive.session_manager import SessionManager  # AD-750
from probos.credential_store import CredentialStore
from probos.crew_profile import CallsignRegistry
from probos.cognitive.self_model import PoolSnapshot, SystemSelfModel
from probos.sif import StructuralIntegrityField
from probos.initiative import InitiativeEngine
from probos.build_queue import BuildQueue
from probos.worktree_manager import WorktreeManager
from probos.build_dispatcher import BuildDispatcher
from probos.notifications import NotificationQueue
from probos.substrate.skill_agent import SkillBasedAgent
from probos.cognitive.attention import AttentionManager
from probos.cognitive.decomposer import DAGExecutor, IntentDecomposer
from probos.cognitive.dreaming import DreamingEngine, DreamScheduler
from probos.cognitive.emergent_detector import EmergentDetector
from probos.cognitive.task_scheduler import TaskScheduler
from probos.knowledge.semantic import SemanticKnowledgeLayer
from probos.cognitive.llm_client import BaseLLMClient, MockLLMClient, OpenAICompatibleClient
from probos.cognitive.working_memory import WorkingMemoryManager
from probos.cognitive.workflow_cache import WorkflowCache
from probos.config import KnowledgeConfig, SystemConfig, load_config, TRUST_DEFAULT, TRUST_FLOOR_CONN, format_trust
from probos.utils import format_duration
from probos.consensus.escalation import EscalationManager
from probos.consensus.quorum import QuorumEngine
from probos.consensus.trust import TrustNetwork
from probos.mesh.capability import CapabilityRegistry
from probos.mesh.gossip import GossipProtocol
from probos.mesh.intent import IntentBus
from probos.mesh.routing import HebbianRouter
from probos.mesh.signal import SignalManager
from probos.substrate.event_log import EventLog
from probos.substrate.heartbeat import HeartbeatAgent
from probos.substrate.pool import ResourcePool
from probos.substrate.pool_group import PoolGroup, PoolGroupRegistry
from probos.substrate.registry import AgentRegistry
from probos.substrate.scaler import PoolScaler
from probos.substrate.spawner import AgentSpawner
from probos.substrate.identity import generate_agent_id, generate_pool_ids
from probos.types import (
    AnchorFrame,
    ConsensusOutcome,
    Episode,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
    NodeSelfModel,
    Priority,
    QuorumPolicy,
    TaskDAG,
    TaskNode,
)

from probos.agent_onboarding import AgentOnboardingService
from probos.crew_utils import is_crew_agent
from probos.dream_adapter import DreamAdapter
from probos.self_mod_manager import SelfModManager
from probos.ward_room_router import WardRoomRouter
from probos.build_pipeline import BuildPipeline
from probos.warm_boot import WarmBootService

if TYPE_CHECKING:
    from probos.acm import AgentCapitalService
    from probos.assignment import AssignmentService
    from probos.bridge_alerts import BridgeAlertService
    from probos.capability_request import CapabilityRequestStore
    from probos.clearance_grants import ClearanceGrantStore
    from probos.cognitive.agent_patcher import AgentPatcher
    from probos.cognitive.capability_gap_driver import CapabilityGapDriver
    from probos.cognitive.behavioral_monitor import BehavioralMonitor
    from probos.cognitive.clinical_notes_store import ClinicalNotesStore  # AD-904
    from probos.avatars.divergence_detector import DivergenceResult  # AD-722a
    from probos.avatars.divergence_detector import DivergenceHistoryEntry  # AD-722a-5
    from probos.cognitive.codebase_index import CodebaseIndex
    from probos.cognitive.correction_detector import CorrectionDetector
    from probos.cognitive.dependency_resolver import DependencyResult  # AD-838c
    from probos.cognitive.episodic import EpisodicMemory
    from probos.cognitive.feedback import FeedbackEngine
    from probos.cognitive.journal import CognitiveJournal
    from probos.cognitive.self_mod import SelfModificationPipeline
    from probos.cognitive.strategy_advisor import StrategyAdvisor
    from probos.conn import ConnManager
    from probos.sop.runtime import BillRuntime  # AD-618d
    from probos.federation.bridge import FederationBridge
    from probos.federation.transport import FederationTransport
    from probos.federation.peer import FederationPeerRegistry
    from probos.federation.mcp_server import FederationMCPServer
    from probos.federation.a2a.server import FederationA2AServer
    from probos.identity import AgentIdentityRegistry
    from probos.knowledge.records_store import RecordsStore
    from probos.knowledge.store import KnowledgeStore
    from probos.ontology import VesselOntologyService
    from probos.persistent_tasks import PersistentTaskStore
    from probos.proactive import ProactiveCognitiveLoop
    from probos.duty_schedule import DutySchedule
    from probos.cognitive.skill_catalog import CognitiveSkillCatalog
    from probos.cognitive.skill_grants import SkillGrantStore
    from probos.cognitive.intent_grants import IntentGrantStore
    from probos.skill_framework import AgentSkillService, SkillRegistry
    from probos.skill_request import SkillRequestStore  # AD-906
    from probos.mesh.nats_bus import NATSBus
    from probos.mcp_apps.registry import MCPAppRegistry
    from probos.tools.permissions import ToolPermissionStore
    from probos.tools.registry import ToolRegistry
    from probos.ward_room import WardRoomService
    from probos.watch_rotation import NightOrdersManager, WatchManager
    from probos.workforce import WorkItemStore

logger = logging.getLogger(__name__)

# Default paths (relative to project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG = _PROJECT_ROOT / "config" / "system.yaml"


def _platform_data_dir() -> Path:
    """BF-265: Platform-appropriate data directory, matching __main__._default_data_dir().

    Prevents split-brain where runtime.py defaults to repo-relative ``data/``
    while ``__main__.py`` uses AppData/XDG. Environment variable
    ``PROBOS_DATA_DIR`` overrides for testing.
    """
    override = os.environ.get("PROBOS_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local" / "ProbOS"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "ProbOS"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) / "ProbOS" if xdg else Path.home() / ".local" / "share" / "ProbOS"
    return base / "data"


_DEFAULT_DATA_DIR = _platform_data_dir()


class ProbOSRuntime:
    """Top-level orchestrator. Wires substrate + mesh + consensus components, manages lifecycle."""

    # --- Class-level type annotations (BF-085) ---
    # Declared here for type safety and MagicMock(spec=ProbOSRuntime) support.
    # All values are assigned in __init__(); these define the type contract only.

    # Constructor params
    config: SystemConfig

    # Substrate layer
    registry: AgentRegistry
    spawner: AgentSpawner
    pools: dict[str, ResourcePool]
    pool_groups: PoolGroupRegistry

    # Mesh layer
    signal_manager: SignalManager
    intent_bus: IntentBus
    capability_registry: CapabilityRegistry
    hebbian_router: HebbianRouter
    gossip: GossipProtocol

    # Event / Credential / Callsign
    event_log: EventLog
    credential_store: CredentialStore
    callsign_registry: CallsignRegistry

    # Consensus
    quorum_engine: QuorumEngine
    trust_network: TrustNetwork

    # Cognitive
    llm_client: BaseLLMClient
    working_memory: WorkingMemoryManager
    workflow_cache: WorkflowCache
    decomposer: IntentDecomposer
    attention: AttentionManager
    escalation_manager: EscalationManager
    dag_executor: DAGExecutor

    # Deferred-init services (assigned in start())
    episodic_memory: EpisodicMemory | None
    ward_room: WardRoomService | None
    ward_room_router: WardRoomRouter | None
    assignment_service: AssignmentService | None
    bridge_alerts: BridgeAlertService | None
    clearance_grant_store: ClearanceGrantStore | None
    clinical_notes_store: ClinicalNotesStore | None
    capability_request_store: CapabilityRequestStore | None
    skill_request_store: SkillRequestStore | None
    tool_registry: ToolRegistry | None
    dream_scheduler: DreamScheduler | None
    task_scheduler: TaskScheduler | None
    persistent_task_store: PersistentTaskStore | None
    work_item_store: WorkItemStore | None
    cognitive_journal: CognitiveJournal | None
    skill_registry: SkillRegistry | None
    skill_service: AgentSkillService | None
    cognitive_skill_catalog: CognitiveSkillCatalog | None
    skill_grant_store: SkillGrantStore | None
    intent_grant_store: "IntentGrantStore | None"
    acm: AgentCapitalService | None
    ontology: VesselOntologyService | None
    identity_registry: AgentIdentityRegistry | None
    pool_scaler: PoolScaler | None
    federation_bridge: FederationBridge | None
    federation_peer_registry: "FederationPeerRegistry"
    federation_mcp_server: "FederationMCPServer | None"
    federation_a2a_server: "FederationA2AServer | None"
    self_mod_pipeline: SelfModificationPipeline | None
    mcp_app_registry: "MCPAppRegistry | None"  # AD-597
    proposal_store: Any | None  # AD-482b ProposalStore
    approval_gate: Any | None  # AD-482c ApprovalGate
    proposal_grounding_verifier: Any | None  # AD-833
    evolution_store: Any | None  # AD-482d EvolutionStore
    qa_agent_pool: Any | None  # AD-482f QAAgentPool
    agent_version_store: Any | None  # AD-482g AgentVersionStore
    agent_persistence: Any | None  # AD-482h LocalDiskPersistence
    shadow_deployment_policy: Any | None  # AD-482i NoOpShadowDeploymentPolicy
    behavioral_monitor: BehavioralMonitor | None
    onboarding: AgentOnboardingService | None
    warm_boot: WarmBootService | None
    self_mod_manager: SelfModManager | None
    dream_adapter: DreamAdapter | None
    feedback_engine: FeedbackEngine | None
    proactive_loop: ProactiveCognitiveLoop | None
    duty_schedule: "DutySchedule | None"
    sif: StructuralIntegrityField | None
    initiative: InitiativeEngine | None
    build_queue: BuildQueue | None
    build_dispatcher: BuildDispatcher | None
    service_profiles: ServiceProfileStore | None
    directive_store: DirectiveStore | None
    notification_queue: NotificationQueue
    conn_manager: ConnManager | None
    watch_manager: WatchManager | None
    codebase_index: CodebaseIndex | None
    nats_bus: "NATSBus | None"

    # Private attributes
    _data_dir: Path
    _checkpoint_dir: Path
    red_team_agents: list[RedTeamAgent]
    _cold_start: bool
    _start_time: float
    _recent_errors: list[str]
    _last_capability_gap: str
    _federation_transport: FederationTransport | None
    _system_qa: SystemQAAgent | None
    _qa_reports: dict[str, Any]
    _knowledge_store: KnowledgeStore | None
    _records_store: RecordsStore | None
    _semantic_store: Any | None  # AD-750: SemanticStore
    _session_manager: Any | None  # AD-750: SessionManager
    _archive_store: Any | None
    _bill_runtime: "BillRuntime | None"  # AD-618d
    _last_execution: dict[str, Any] | None
    _previous_execution: dict[str, Any] | None
    _pending_proposal: TaskDAG | None
    _pending_proposal_text: str
    _last_feedback_applied: bool
    _last_execution_text: str | None
    _last_shapley_values: dict[str, float] | None
    _correction_detector: CorrectionDetector | None
    _agent_patcher: AgentPatcher | None
    _emergent_detector: EmergentDetector | None
    _strategy_advisor: StrategyAdvisor | None
    _semantic_layer: SemanticKnowledgeLayer | None
    _event_listeners: list[tuple[Callable[..., Any], frozenset[str] | None]]
    _started: bool
    _fresh_boot: bool
    _start_time_wall: float
    _session_id: str
    _lifecycle_state: str
    _stasis_duration: float
    _previous_session: dict | None
    _night_orders_mgr: NightOrdersManager | None
    _last_request_time: float

    def __init__(
        self,
        config: SystemConfig | None = None,
        data_dir: str | Path | None = None,
        llm_client: BaseLLMClient | None = None,
        episodic_memory: EpisodicMemory | None = None,
    ) -> None:
        self.config = config or load_config(_DEFAULT_CONFIG)
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._checkpoint_dir = self._data_dir / "checkpoints"

        # AD-823: daily episodic backup task handle. Created in start();
        # held here so async hygiene rules (no fire-and-forget) are met.
        self._episodic_backup_task: asyncio.Task[None] | None = None

        # --- Substrate ---
        self.registry = AgentRegistry()
        self.spawner = AgentSpawner(self.registry)
        self.pools: dict[str, ResourcePool] = {}
        self.pool_groups = PoolGroupRegistry()

        # --- Mesh ---
        self.signal_manager = SignalManager(reap_interval=1.0)
        self.intent_bus = IntentBus(self.signal_manager)
        self.capability_registry = CapabilityRegistry(
            semantic_matching=self.config.mesh.semantic_matching,
        )
        self.hebbian_router = HebbianRouter(
            decay_rate=self.config.mesh.hebbian_decay_rate,
            reward=self.config.mesh.hebbian_reward,
            db_path=self._data_dir / "hebbian_weights.db",
            social_decay_rate=self.config.mesh.hebbian_social_decay_rate,  # AD-571c
        )
        # AD-571b: operational status for non-crew agents (in-memory tracker).
        from probos.substrate.operational_status import OperationalStatusTracker
        self.operational_status_tracker = OperationalStatusTracker(
            config=self.config.operational_status,  # AD-571b: SystemConfig.operational_status (singular)
        )
        self.gossip = GossipProtocol(
            interval_seconds=self.config.mesh.gossip_interval_ms / 1000.0,
        )

        # --- Event log ---
        self.event_log = EventLog(db_path=self._data_dir / "events.db")

        # --- Credential Store (AD-395) ---
        self.credential_store = CredentialStore(
            config=self.config, event_log=self.event_log,
        )

        # --- M365 Token Manager (AD-749) ---
        self._m365_token_manager: M365TokenManager | None = None
        if self.config.m365.enabled and self.config.m365.client_id:
            self._m365_token_manager = M365TokenManager(
                cache_dir=self.config.m365.cache_dir,
                config=self.config.m365,
            )
            logger.info("M365 integration enabled; token manager initialized")

        # --- Callsign Registry (AD-397) ---
        self.callsign_registry = CallsignRegistry()
        self.callsign_registry.load_from_profiles()
        self.callsign_registry.bind_registry(self.registry)

        # --- Consensus ---
        consensus_cfg = self.config.consensus
        self.quorum_engine = QuorumEngine(
            policy=QuorumPolicy(
                min_votes=consensus_cfg.min_votes,
                approval_threshold=consensus_cfg.approval_threshold,
                use_confidence_weights=consensus_cfg.use_confidence_weights,
            )
        )
        self.trust_network = TrustNetwork(
            prior_alpha=consensus_cfg.trust_prior_alpha,
            prior_beta=consensus_cfg.trust_prior_beta,
            decay_rate=consensus_cfg.trust_decay_rate,
            db_path=str(self._data_dir / "trust.db"),
            dampening_config=self.config.trust_dampening,
        )
        # AD-718/AD-721d/AD-722 BF (2026-05-10): crew-wide ProfileStore.
        # Voice-set + appearance-set endpoints in routers/agents.py persist
        # via runtime.profile_store; before this it was never wired (only
        # the counselor-specific store on _counselor_profile_store existed),
        # so all approvals were silently dropped with the warning
        # "AD-718: profile_store not present on runtime; ... not persisted".
        from probos.crew_profile import ProfileStore
        # Ensure the data_dir exists; ProfileStore connects synchronously in
        # __init__ (unlike TrustNetwork/EventLog which are async-lazy and
        # mkdir on first start()). Tests that run RuntimeBuilder against a
        # tmp path expect this.
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self.profile_store = ProfileStore(
            db_path=str(self._data_dir / "crew_profiles.db"),
        )

        # AD-791 (Wave 193): chat-threads substrate. Eager init so REST
        # routes + IntentMessage emitters can reference it from any phase.
        from probos.threads import ChatThreadStore, ProjectStore
        self.chat_thread_store = ChatThreadStore(
            db_path=self._data_dir / "chat_threads.db",
        )
        # AD-793 (Wave 196): projects substrate. Shares the chat_threads
        # database file so cascade/unparent operations on contained
        # threads can run inside the same SQLite transaction context.
        self.project_store = ProjectStore(
            db_path=self._data_dir / "chat_threads.db",
        )

        # AD-1021c: in-memory pending agent suggestions for the Monaco co-edit
        # surface (HXI #11). Attached EXPLICITLY (not getattr lazy-create) so the
        # write/dismiss endpoints can rely on its presence at any startup phase
        # and a real (not auto-faked) store backs the per-(owner, path) bound.
        # Volatile by design: a restart clears pending proposals (agents
        # re-propose); the human Accepts (governed AD-1021b write) or Dismisses.
        from probos.execution.workspace_suggestions import WorkspaceSuggestionStore
        self.workspace_suggestions = WorkspaceSuggestionStore()

        # AD-918: agent-initiated group-chat creation. Bare-callable handler
        # subscribed under a synthetic id (yeoman.py:242 pattern) — no pool,
        # no registry entry. ontology read lazily (set later at startup).
        from probos.threads.agent_group_chat import (
            AgentGroupChatService,
            CREATE_GROUP_CHAT,
            GROUP_CHAT_COORDINATOR_ID,
        )
        self.agent_group_chat = AgentGroupChatService(
            store=self.chat_thread_store,
            registry=self.registry,
            callsign_registry=self.callsign_registry,
            config=self.config.group_chat,
            ontology_provider=lambda: self.ontology,
        )
        self.intent_bus.subscribe(
            GROUP_CHAT_COORDINATOR_ID,
            self.agent_group_chat.handle_intent,
            intent_names=[CREATE_GROUP_CHAT],
        )

        # AD-797 (Wave 195): artifact metadata store. Bytes live in the
        # existing AttachmentStore; this is the named/versioned layer.
        from probos.artifacts import ArtifactStore
        self.artifact_store = ArtifactStore(
            db_path=self._data_dir / "artifacts.db",
        )

        # AD-815a (Wave 200): TaskSession substrate — anchors cowork-style
        # work to a thread (AD-791) + work item (AD-477) with inputs/
        # outputs/scratch folders under the per-thread workspace.
        from probos.task_sessions import TaskSessionStore
        self.task_session_store = TaskSessionStore(
            db_path=self._data_dir / "task_sessions.db",
            workspace_root=self._data_dir / "workspaces",
        )

        # AD-722f: per-agent avatar-telemetry sampling state machine.
        # Initialized in __init__ (not finalize) so consumers in cognitive
        # services / routers can rely on its presence at any startup phase.
        # State is volatile by design — restart resets to LOW for every agent.
        from probos.avatars.sampling_state import AvatarSamplingStateMachine
        self.avatar_sampling_state = AvatarSamplingStateMachine(
            rates=self.config.avatar_telemetry.sampling_rates,
        )

        # AD-722b: avatar-telemetry WS push channel — event bus + connection
        # manager. Co-located with sampling_state for the same lifecycle
        # discipline (eager __init__, volatile across restarts).
        from probos.avatars.events import AvatarEventBus
        from probos.avatars.ws_connection_manager import (
            AvatarTelemetryConnectionManager,
        )
        self.avatar_event_bus = AvatarEventBus()
        self.avatar_telemetry_connection_manager = AvatarTelemetryConnectionManager(
            max_per_agent=self.config.avatar_telemetry.max_connections_per_agent,
        )

        from probos.avatars.telemetry_history import TelemetryHistoryWriter
        # AD-722c: append-only JSONL writer; None when feature is disabled
        # so the WS publish loop's hasattr check degrades cleanly.
        self.avatar_telemetry_history: TelemetryHistoryWriter | None = None
        if (
            getattr(self.config, "avatar_telemetry", None) is not None
            and self.config.avatar_telemetry.enabled
            and self.config.avatar_telemetry.history_enabled
        ):
            self.avatar_telemetry_history = TelemetryHistoryWriter(
                self.config.avatar_telemetry.history_dir,
            )

        # AD-722d: significance-event Records writer. Gated independently
        # so the Captain can have history (AD-722c) without the Records
        # ledger write surface. records_store is wired in Phase 4 (see
        # runtime.py around line 1528); the actual writer is instantiated
        # there. Declared here as None so the WS publish loop's getattr
        # guard degrades cleanly before finalize runs.
        self.avatar_telemetry_records_writer: Any = None

        # AD-722a: most-recent intent-vs-presentation divergence per agent.
        # Volatile (cleared on restart). Populated by the divergence detector
        # call site in routers/agents.py:agent_chat; consumed by
        # cognitive_agent._build_avatar_self_observation for next-cycle
        # injection. Type: dict[agent_id, DivergenceResult].
        self.divergence_results: dict[str, "DivergenceResult"] = {}

        # AD-722a-4: post-correction results. Populated by
        # apply_divergence_check when auto_correct_enabled and the
        # original result's magnitude exceeded auto_correct_threshold.
        # Cleared at the START of the NEXT DM reply by
        # DmReplyPipeline.step_1_sanity_gate_retry (NOT at step_7;
        # TTS reads the slot AFTER the reply returns).
        self.divergence_corrections: dict[str, "DivergenceResult"] = {}

        # AD-722a-5: per-agent ring buffer of historical divergence entries.
        # Volatile (cleared on restart). Populated by the same single call
        # site as divergence_results (apply_divergence_check), gated by
        # avatar_telemetry.divergence_history_size > 0. Consumed by the
        # GET /avatar-telemetry/divergence-history endpoint.
        # Type: dict[agent_id, collections.deque[DivergenceHistoryEntry]].
        from collections import deque as _deque
        self.divergence_history: dict[str, "_deque"] = {}

        # AD-730-2-1: load the per-Captain 24h image budget from disk if a
        # sidecar exists; otherwise start empty. Tier-2 - load failure
        # degrades to empty (logged in image_budget_store.load).
        from probos.attachments.image_budget_store import load as _ibs_load
        _ibs_cfg = getattr(self.config, "attachments", None)
        _ibs_path_str = getattr(_ibs_cfg, "image_budget_path", None) if _ibs_cfg else None
        if _ibs_path_str:
            self._image_budget_path = Path(_ibs_path_str)
        else:
            self._image_budget_path = self._data_dir / "image_budget.json"
        self.image_budget_tracker: dict[str, "_deque"] = _ibs_load(self._image_budget_path)

        # AD-721d-4: bind proposal_history to its on-disk sidecar so DSL
        # iterations survive restart. Path is configurable via
        # AvatarsConfig.proposal_history_path; defaults to
        # ``<data_dir>/proposal_history.json``. Tier-2 - configure failure
        # logs and degrades to in-memory mode.
        try:
            from probos.avatars import proposal_history as _ph
            _ph_cfg = getattr(self.config, "avatars", None)
            _ph_path_str = (
                getattr(_ph_cfg, "proposal_history_path", None) if _ph_cfg else None
            )
            if _ph_path_str:
                _ph_path = Path(_ph_path_str)
            else:
                _ph_path = self._data_dir / "proposal_history.json"
            _ph.configure(_ph_path)
        except Exception:
            logger.warning(
                "AD-721d-4: proposal_history.configure failed; in-memory mode only",
                exc_info=True,
            )

        # AD-720d-2.1: bind vision-capability proposal-history sidecar.
        # Mirrors the AD-721d-4 pattern; Tier-2 log-and-degrade on failure.
        try:
            from probos.avatars import vision_proposal_history as _vph
            _vph_cfg = getattr(self.config, "avatars", None)
            _vph_path_str = (
                getattr(_vph_cfg, "vision_proposal_history_path", None)
                if _vph_cfg
                else None
            )
            if _vph_path_str:
                _vph_path = Path(_vph_path_str)
            else:
                _vph_path = self._data_dir / "vision_proposal_history.json"
            _vph.configure(_vph_path)
        except Exception:
            logger.warning(
                "AD-720d-2.1: vision_proposal_history.configure failed; "
                "in-memory mode only",
                exc_info=True,
            )

        # AD-982a: persistent Captain-set vision-capability overrides. Bind the
        # data-dir sidecar and re-apply any persisted grants/revokes onto the
        # callsign registry (loaded from YAML at line ~412) so a Captain grant
        # survives restart without mutating the tracked crew-profile YAML.
        try:
            from probos.perception import vision_overrides as _vov
            _vov.configure(self._data_dir / "vision_overrides.json")
            _vov.apply(self.callsign_registry)
        except Exception:
            logger.warning(
                "AD-982a: vision_overrides configure/apply failed; YAML "
                "defaults stand",
                exc_info=True,
            )

        # Red team agents are stored separately — not on the intent bus
        self.red_team_agents: list[RedTeamAgent] = []

        # --- Cognitive ---
        cog_cfg = self.config.cognitive
        self.llm_client: BaseLLMClient = llm_client or MockLLMClient()
        self.working_memory = WorkingMemoryManager(
            token_budget=cog_cfg.working_memory_token_budget,
        )

        # AD-722a-1: vision-LLM intent-vs-render divergence detector.
        # Default-OFF gating lives on AvatarsConfig; the detector itself is
        # always constructed so callers can opt in per request.
        try:
            from probos.avatars.vision_intent_divergence import (
                VisionIntentDivergenceDetector,
            )
            _av_cfg = getattr(self.config, "avatars", None)
            _vid_max = int(
                getattr(_av_cfg, "vision_intent_divergence_max_per_hour_per_agent", 3)
                if _av_cfg else 3
            )
            self.vision_intent_divergence_detector = VisionIntentDivergenceDetector(
                llm_client=self.llm_client,
                max_per_hour=_vid_max,
            )
        except Exception:
            logger.warning(
                "AD-722a-1: vision_intent_divergence detector construction "
                "failed; feature disabled at runtime",
                exc_info=True,
            )
            self.vision_intent_divergence_detector = None

        # AD-722e-2: vision-LLM self-render coherence verifier.
        # Default-OFF gating on AvatarsConfig; verifier always constructed
        # so the AD-722e self-perception path can opt in per cycle.
        try:
            from probos.cognitive.self_render_verify import SelfRenderVerifier
            _srv_max = int(
                getattr(_av_cfg, "self_render_verify_max_per_hour_per_agent", 3)
                if _av_cfg else 3
            )
            self.self_render_verifier = SelfRenderVerifier(
                llm_client=self.llm_client,
                max_per_hour=_srv_max,
            )
        except Exception:
            logger.warning(
                "AD-722e-2: self_render_verifier construction failed; "
                "feature disabled at runtime",
                exc_info=True,
            )
            self.self_render_verifier = None

        # AD-573f: late-bind COMMITMENT_RECORDED emission
        self.working_memory.set_event_callback(self.emit_event)
        self.workflow_cache = WorkflowCache()
        self.decomposer = IntentDecomposer(
            llm_client=self.llm_client,
            working_memory=self.working_memory,
            timeout=cog_cfg.decomposition_timeout_seconds,
            workflow_cache=self.workflow_cache,
            deferred_capability_threshold=cog_cfg.deferred_capability_threshold,  # AD-983d
        )
        self.decomposer._callsign_map = self.callsign_registry.live_callsign_map  # BF-013: live ref updates after onboarding
        self.attention = AttentionManager(
            max_concurrent=cog_cfg.max_concurrent_tasks,
            decay_rate=cog_cfg.attention_decay_rate,
            focus_history_size=cog_cfg.focus_history_size,
            background_demotion_factor=cog_cfg.background_demotion_factor,
        )
        self.escalation_manager = EscalationManager(
            runtime=self,
            llm_client=self.llm_client,
            max_retries=2,
        )
        self.dag_executor = DAGExecutor(
            runtime=self,
            timeout=cog_cfg.dag_execution_timeout_seconds,
            attention=self.attention,
            escalation_manager=self.escalation_manager,
            checkpoint_dir=self._checkpoint_dir,  # AD-405
        )

        # --- Episodic memory ---
        self.episodic_memory = episodic_memory  # None = disabled

        # --- AD-573: Working memory persistence ---
        from probos.cognitive.working_memory_store import WorkingMemoryStore
        from probos.storage.sqlite_factory import default_factory as _wm_factory
        self.working_memory_store = WorkingMemoryStore(
            connection_factory=_wm_factory,
            db_path=str(self._data_dir / "working_memory.db"),
        )

        # --- Ward Room (AD-407) ---
        self.ward_room: WardRoomService | None = None  # Initialized in start()

        # AD-515: Ward Room routing state is now managed by WardRoomRouter
        self.ward_room_router: WardRoomRouter | None = None

        # --- Assignment Service (AD-408) ---
        self.assignment_service: AssignmentService | None = None  # Initialized in start()

        # --- Bridge Alerts (AD-410) ---
        self.bridge_alerts: BridgeAlertService | None = None

        # --- Clearance Grants (AD-622) ---
        self.clearance_grant_store: ClearanceGrantStore | None = None

        # --- Clinical Notes (AD-904) ---
        self.clinical_notes_store: ClinicalNotesStore | None = None

        # --- Clinical Access (AD-903) ---
        # Self-similarity history ring (always-on, pure in-memory) feeds the
        # Counselor clinical trend surface. Recorded from proactive
        # self-monitoring; read by the gated /clinical trend endpoint.
        self.self_similarity_history = SelfSimilarityHistory()
        # Bounded audit ring for clinical-access decisions (every allow AND
        # deny). Mirrors the ClinicalTelemetryService._record_audit in-memory
        # ring shape; fail-safe — a CONFIDENTIAL gate must never take a DB
        # dependency to record an access.
        self.clinical_access_audit: deque[dict[str, Any]] = deque(maxlen=1000)

        # --- Capability Requests (AD-853) ---
        self.capability_request_store: CapabilityRequestStore | None = None

        # --- Skill Requests (AD-906) ---
        self.skill_request_store: SkillRequestStore | None = None

        # --- Capability Gap Driver (AD-855) ---
        self.capability_gap_driver: "CapabilityGapDriver | None" = None

        # --- Tool Registry (AD-423a) ---
        self.tool_registry: ToolRegistry | None = None

        # --- Tool Permission Store (AD-423b) ---
        self.tool_permission_store: ToolPermissionStore | None = None

        # --- Dreaming ---
        self.dream_scheduler: DreamScheduler | None = None
        self._last_request_time: float = time.monotonic()

        # --- Task Scheduler ---
        self.task_scheduler: TaskScheduler | None = None

        # --- Persistent Task Store (Phase 25a) ---
        self.persistent_task_store: PersistentTaskStore | None = None

        # --- Workforce Scheduling Engine (AD-496) ---
        self.work_item_store: WorkItemStore | None = None

        # --- Cognitive Journal (AD-431) ---
        self.cognitive_journal: CognitiveJournal | None = None

        # --- Knowledge Edge Store (AD-687) ---
        self.knowledge_edges: Any = None  # SQLiteKnowledgeEdgeStore | None — Any to avoid circular import
        self.spatial_layout: Any = None  # AD-520: SpatialLayout | None — set by _wire_spatial_explorer
        self.rejection_cache: Any = None  # AD-690: SQLiteRejectionCache | None — Any to avoid circular import

        # --- Edge Backfill Service (AD-689) ---
        self.edge_backfill: Any = None  # EdgeBackfillService | None — wired in finalize phase

        # --- Counselor Profile Store (AD-503) ---
        self._counselor_profile_store: Any = None

        # --- Procedure Store (AD-533) ---
        self._procedure_store: Any = None

        # --- Qualification Harness (AD-566a) ---
        self._qualification_store: Any = None
        self._qualification_harness: Any = None
        self._drift_scheduler: Any = None  # AD-566c

        # --- Skill Framework (AD-428) ---
        self.skill_registry: SkillRegistry | None = None
        self.skill_service: AgentSkillService | None = None

        # --- Cognitive Skill Catalog (AD-596a) ---
        self.cognitive_skill_catalog: CognitiveSkillCatalog | None = None
        # --- Skill Grant Store (AD-983b) — per-agent cognitive-skill grants ---
        self.skill_grant_store: SkillGrantStore | None = None
        # --- Intent Grant Store (AD-1005/AD-1007) — per-agent mesh-capability grants ---
        self.intent_grant_store: "IntentGrantStore | None" = None

        # --- Recreation Service (AD-526a) ---
        self.recreation_service: Any = None

        # --- DM Sanity Gate (AD-724) ---
        from probos.cognitive.dm_sanity_gate import DmSanityGate
        self.dm_sanity_gate: DmSanityGate = DmSanityGate(
            self.config.dm_sanity_gate
        )

        # --- Recreation Preference Tracker (AD-526d) ---
        from probos.recreation.preferences import GamePreferenceTracker
        self.recreation_preference_tracker: GamePreferenceTracker = (
            GamePreferenceTracker()
        )
        self.recreation_preference_tracker.set_event_callback(self.emit_event)

        # --- Recreation Spectator Registry (AD-526e) ---
        from probos.recreation.spectators import SpectatorRegistry
        self.recreation_spectator_registry: SpectatorRegistry = SpectatorRegistry()
        self.recreation_spectator_registry.set_event_callback(self.emit_event)

        # --- TaskEvent Dispatcher (AD-654c) ---
        self.dispatcher: Any | None = None

        # --- Agent Capital Management (AD-427) ---
        self.acm: AgentCapitalService | None = None

        # --- Vessel Ontology (AD-429a) ---
        self.ontology: VesselOntologyService | None = None

        # --- Sovereign Agent Identity (AD-441) ---
        self.identity_registry: AgentIdentityRegistry | None = None

        # BF-034: Cold-start flag — True when booting with empty state (post-reset)
        self._cold_start: bool = False

        # AD-638: Boot camp coordinator
        self.boot_camp: BootCampCoordinator | None = None

        # --- Pool scaling ---
        self.pool_scaler: PoolScaler | None = None

        # --- Federation ---
        self.federation_bridge: FederationBridge | None = None
        self._federation_transport: FederationTransport | None = None
        # AD-480f: cross-protocol peer registry — initialized eagerly so
        # ZeroMQ peers can be auto-registered via the existing gossip path.
        from probos.federation.peer import FederationPeerRegistry
        self.federation_peer_registry: FederationPeerRegistry = FederationPeerRegistry(
            trust_network=self.trust_network,
            probationary_alpha=self.config.federation.peer_trust.probationary_alpha,
            probationary_beta=self.config.federation.peer_trust.probationary_beta,
        )
        # AD-843c-1: device tier (brain->limb). Registry constructed eagerly with the
        # CONCRETE TrustNetwork (mirrors FederationPeerRegistry) -- inert until a device
        # pairs. The device.notify actuation handler subscribes ONLY when
        # config.device.enabled (default False) -> byte-identical when off.
        from probos.substrate.device_node import DeviceNodeRegistry, NoOpDeviceNodeAdapter
        from probos.substrate.device_service import DeviceNodeService, DEVICE_NODE_SERVICE_ID
        self.device_node_registry: DeviceNodeRegistry = DeviceNodeRegistry(
            trust_network=self.trust_network,
            probationary_alpha=self.config.device.probationary_alpha,
            probationary_beta=self.config.device.probationary_beta,
        )
        self.device_node_service: DeviceNodeService = DeviceNodeService(
            registry=self.device_node_registry,
            adapter=NoOpDeviceNodeAdapter(),
            trust_network=self.trust_network,
            episodic_provider=lambda: self.episodic_memory,
        )
        if self.config.device.enabled:
            self.intent_bus.subscribe(
                DEVICE_NODE_SERVICE_ID,
                self.device_node_service.handle_intent,
                intent_names=["device.notify"],
            )
        # AD-480a / AD-480d: inbound servers — None until startup wires them.
        self.federation_mcp_server: "FederationMCPServer | None" = None
        self.federation_a2a_server: "FederationA2AServer | None" = None
        # AD-597: MCP App Host registry — installed by _wire_mcp_app_host.
        self.mcp_app_registry: "MCPAppRegistry | None" = None
        self._mcp_app_external_discovery_task: asyncio.Task | None = None
        # AD-479c / AD-479g: federation routing observability handles —
        # None when federation is disabled or features unwired.
        self.federation_hebbian_map: Any | None = None
        self.federation_cluster_monitor: Any | None = None
        self._start_time: float = time.monotonic()
        self._recent_errors: list[str] = []    # last 5 error summaries (AD-318)
        self._last_capability_gap: str = ""    # last unhandled intent (AD-318)
        # AD-741: path to the system.yaml that was loaded into this runtime.
        # Set externally by ``_load_config_with_fallback`` after construction.
        # None when the runtime is constructed in-memory (tests).
        self.config_path: str | None = None

        # --- Self-modification ---
        self.self_mod_pipeline: SelfModificationPipeline | None = None
        self.proposal_store: Any | None = None  # AD-482b
        self.approval_gate: Any | None = None  # AD-482c
        self.proposal_grounding_verifier: Any | None = None  # AD-833
        self.evolution_store: Any | None = None  # AD-482d
        self.qa_agent_pool: Any | None = None  # AD-482f
        self.agent_version_store: Any | None = None  # AD-482g
        self.agent_persistence: Any | None = None  # AD-482h
        self.shadow_deployment_policy: Any | None = None  # AD-482i
        self.behavioral_monitor: BehavioralMonitor | None = None

        # AD-515: Extracted service instances (created in start())
        self.onboarding: AgentOnboardingService | None = None
        self.warm_boot: WarmBootService | None = None
        # AD-521: BuildPipeline Ship's Computer service. Owns no agent
        # identity; SoftwareEngineerAgent (Scotty) delegates to this
        # service for build execution. Constructor-injected with the
        # runtime handle so it can read pre_flight_runner / emit_event
        # / llm_client via defensive `getattr` lookups at invocation
        # time (the runtime attributes are populated by
        # startup/finalize.py and other startup modules).
        self.build_pipeline: BuildPipeline | None = None
        self.self_mod_manager: SelfModManager | None = None
        self.dream_adapter: DreamAdapter | None = None

        # --- SystemQA (AD-153) ---
        self._system_qa: SystemQAAgent | None = None
        self._qa_reports: dict[str, Any] = {}  # AD-157: in-memory report store

        # --- Knowledge store (AD-159) ---
        self._knowledge_store: KnowledgeStore | None = None

        # --- Records store (AD-434) ---
        self._records_store: RecordsStore | None = None

        # --- Semantic work layer (AD-750) ---
        self._semantic_store: Any | None = None
        self._session_manager: Any | None = None
        self._template_registry: TemplateRegistry | None = None

        # --- Ship's Archive (AD-524) ---
        self._archive_store: Any | None = None

        # --- Bill System (AD-618d) ---
        self._bill_runtime: BillRuntime | None = None

        # --- Execution history (for introspection) ---
        self._last_execution: dict[str, Any] | None = None
        self._previous_execution: dict[str, Any] | None = None

        # --- DAG Proposal mode (AD-204) ---
        self._pending_proposal: TaskDAG | None = None
        self._pending_proposal_text: str = ""

        # --- Feedback-to-learning (AD-219) ---
        self._last_feedback_applied: bool = False
        self._last_execution_text: str | None = None
        self.feedback_engine: FeedbackEngine | None = None
        # --- Shapley attribution (AD-224) ---
        self._last_shapley_values: dict[str, float] | None = None
        # --- Correction feedback (AD-229-232) ---
        self._correction_detector: CorrectionDetector | None = None
        self._agent_patcher: AgentPatcher | None = None

        # --- Emergent detection (AD-236) ---
        self._emergent_detector: EmergentDetector | None = None

        # --- Emergence metrics (AD-557) ---
        self._emergence_metrics_engine: Any = None
        # AD-633: Predictive cognitive branching (set by _wire_predictive_branching)
        self.prediction_engine: Any = None
        self.speculation_cache: Any = None
        self.speculation_executor: Any = None
        self.speculation_budget: Any = None
        self.accuracy_tracker: Any = None
        self._behavioral_metrics_engine: Any = None  # AD-569

        # --- Structural Integrity Field (AD-370) ---
        self.sif: StructuralIntegrityField | None = None

        # --- InitiativeEngine (AD-381) ---
        self.initiative: InitiativeEngine | None = None

        # --- Proactive Cognitive Loop (Phase 28b) ---
        self.proactive_loop: ProactiveCognitiveLoop | None = None
        self.duty_schedule: "DutySchedule | None" = None
        self.proactive_last_scan_count: dict[str, int] = {
            "inbox": 0,
            "calendar": 0,
            "teams": 0,
        }

        # --- Strategy Advisor (AD-384) ---
        self._strategy_advisor: StrategyAdvisor | None = None

        # --- Automated Builder Dispatch (AD-375) ---
        self.build_queue: BuildQueue | None = None
        self.build_dispatcher: BuildDispatcher | None = None

        # --- Service Profiles (AD-382) ---
        self.service_profiles: ServiceProfileStore | None = None

        # --- Directive Store (AD-386) ---
        self.directive_store: DirectiveStore | None = None

        # --- Notification Queue (AD-323) ---
        self.notification_queue = NotificationQueue(on_event=self._emit_event)

        # --- Semantic knowledge layer (AD-243) ---
        self._semantic_layer: SemanticKnowledgeLayer | None = None

        # --- HXI event listeners (AD-254) ---
        self._event_listeners: list[tuple[Callable[..., Any], frozenset[str] | None]] = []
        self._nats_publish_tasks: set[asyncio.Task] = set()  # AD-637d: prevents GC of publish tasks

        # AD-824: registry for long-lived runtime-owned background loops.
        # The shutdown sequence in startup/shutdown.py cancels everything in
        # this set before AD-820's mark_clean_shutdown so a stuck loop can
        # never block the integrity marker. Per-event one-shot tasks
        # (ward room alerts, QA fan-out, NATS publish) are NOT registered
        # here — those use _nats_publish_tasks or are intentionally fire-
        # and-forget with their own bounded lifetimes.
        self._background_tasks: set[asyncio.Task] = set()
        # AD-825: separate registry for write-holding background loops
        # (episodic backup, dream-cycle adjacent work). The shutdown
        # sequence drains these BEFORE the AD-824 cancel sweep so any
        # atomic write (Chroma add/upsert, SQLite checkpoint, tar copy)
        # can finish cleanly. Tasks that don't drain in time are
        # force-cancelled by the AD-824 sweep that runs immediately
        # after the drain phase.
        self._drain_tasks: set[asyncio.Task] = set()
        # AD-825: shutdown signal. Drain-tagged loops replace bare
        # ``asyncio.sleep(N)`` with ``asyncio.wait_for(self._shutdown_event.wait(),
        # timeout=N)`` so they exit cleanly the moment shutdown is
        # initiated, instead of waiting up to N seconds for the next
        # iteration tick.
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._nats_events_wired: bool = False  # AD-637z: gate for inline NATS event subscription

        self._started = False
        self._fresh_boot = False

        # AD-502: Temporal context — session tracking and lifecycle awareness
        self._start_time_wall: float = time.time()
        self._session_id: str = str(_uuid.uuid4())
        self._lifecycle_state: str = "first_boot"
        # AD-828b: set True only at the very end of start() (Phase 8 finalize
        # complete). shutdown() reads this to distinguish "killed before the
        # cognitive layer was wired" (startup_incomplete — recoverable) from
        # a real consolidation failure (failed — blocks boot). Default False so
        # any kill before start() returns is correctly classified.
        self._startup_complete: bool = False
        # BF-598: idempotency guard for shutdown(). Set True at the top of the
        # first shutdown() invocation so a duplicate SIGTERM (Windows sleep/wake)
        # or a retried stop() returns early instead of re-running teardown and
        # downgrading the clean AD-820 marker. Separate from _started (BF-137).
        self._shutdown_started: bool = False
        self._stasis_duration: float = 0.0
        self._previous_session: dict | None = None

        # AD-471: Autonomous operations — conn and night orders
        self.conn_manager: ConnManager | None = None
        self._night_orders_mgr: NightOrdersManager | None = None
        self.watch_manager: WatchManager | None = None

        # Register built-in agent templates
        self.spawner.register_template("system_heartbeat", SystemHeartbeatAgent)
        self.spawner.register_template("file_reader", FileReaderAgent)
        self.spawner.register_template("file_writer", FileWriterAgent)
        self.spawner.register_template("directory_list", DirectoryListAgent)
        self.spawner.register_template("file_search", FileSearchAgent)
        self.spawner.register_template("code_search", CodeSearchAgent)  # AD-989
        # AD-994: code execution is the highest-risk capability — only register
        # the template (which makes run_python/install_package visible to the
        # decomposer) when the operator has opted in. Otherwise the planner
        # would advertise a capability with no pool to serve it (AD-592: never
        # offer what the ship cannot back).
        if getattr(self.config, "execution", None) and self.config.execution.enabled:
            self.spawner.register_template("code_runner", CodeRunnerAgent)  # AD-994
        self.spawner.register_template("shell_command", ShellCommandAgent)
        self.spawner.register_template("http_fetch", HttpFetchAgent)
        self.spawner.register_template("red_team", RedTeamAgent)
        self.spawner.register_template("introspect", IntrospectionAgent)
        self.spawner.register_template("quartermaster", QuartermasterAgent)  # AD-876
        self.spawner.register_template("nl_graph_query", NLGraphQueryAgent)  # AD-691
        self.spawner.register_template("avatar_renderer", AvatarRendererAgent)  # AD-721i
        self.spawner.register_template("skill_agent", SkillBasedAgent)
        self.spawner.register_template("system_qa", SystemQAAgent)
        # Bundled CognitiveAgent types (Phase 22, AD-252)
        self.spawner.register_template("web_search", WebSearchAgent)
        self.spawner.register_template("page_reader", PageReaderAgent)
        self.spawner.register_template("weather", WeatherAgent)
        self.spawner.register_template("news", NewsAgent)
        self.spawner.register_template("translator", TranslateAgent)
        self.spawner.register_template("summarizer", SummarizerAgent)
        self.spawner.register_template("calculator", CalculatorAgent)
        self.spawner.register_template("todo_manager", TodoAgent)
        self.spawner.register_template("note_taker", NoteTakerAgent)
        self.spawner.register_template("scheduler", SchedulerAgent)
        # Medical team (AD-290)
        self.spawner.register_template("vitals_monitor", VitalsMonitorAgent)
        self.spawner.register_template("diagnostician", DiagnosticianAgent)
        self.spawner.register_template("surgeon", SurgeonAgent)
        self.spawner.register_template("pharmacist", PharmacistAgent)
        self.spawner.register_template("pathologist", PathologistAgent)
        # Engineering team (AD-302)
        self.spawner.register_template("builder", BuilderAgent)
        # AD-476 — five SWE specialist templates (pools created in
        # startup/agent_fleet.py only when config.swe_specialists.enabled).
        self.spawner.register_template("backend_swe", BackendSWEAgent)
        self.spawner.register_template("frontend_swe", FrontendSWEAgent)
        self.spawner.register_template("test_swe", TestSWEAgent)
        self.spawner.register_template("infrastructure_swe", InfrastructureSWEAgent)
        self.spawner.register_template("data_swe", DataSWEAgent)
        # Science team (AD-306)
        self.spawner.register_template("architect", ArchitectAgent)
        self.spawner.register_template("scout", ScoutAgent)
        # Science analytical pyramid (AD-560)
        self.spawner.register_template("data_analyst", DataAnalystAgent)
        self.spawner.register_template("systems_analyst", SystemsAnalystAgent)
        self.spawner.register_template("research_specialist", ResearchSpecialistAgent)
        # Bridge crew (AD-398)
        self.spawner.register_template("counselor", CounselorAgent)
        # Bridge crew (AD-766) — Captain's personal assistant
        self.spawner.register_template("yeoman", YeomanAgent)
        # Security team (AD-398)
        self.spawner.register_template("security_officer", SecurityAgent)
        # Operations team (AD-398)
        self.spawner.register_template("operations_officer", OperationsAgent)
        # Training (AD-628) — Tucker
        from probos.cognitive.training_officer import TrainingAgent
        self.spawner.register_template("training_officer", TrainingAgent)
        # Engineering team (AD-398)
        self.spawner.register_template("engineering_officer", EngineeringAgent)

        # AD-457: Engineering crew templates
        from probos.agents.engineering import (
            DamageControlAgent,
            MaintenanceAgent,
            PerformanceMonitorAgent,
        )
        self.spawner.register_template("performance_monitor", PerformanceMonitorAgent)
        self.spawner.register_template("maintenance", MaintenanceAgent)
        self.spawner.register_template("damage_control", DamageControlAgent)

        # AD-467: Operations crew templates (operations_-prefixed to avoid
        # collision with the bundled cognitive SchedulerAgent at line 599)
        from probos.agents.operations import (
            CoordinatorAgent as OpsCoordinatorAgent,
            ResourceAllocatorAgent as OpsResourceAllocatorAgent,
            SchedulerAgent as OpsSchedulerAgent,
        )
        self.spawner.register_template(
            "operations_resource_allocator", OpsResourceAllocatorAgent,
        )
        self.spawner.register_template(
            "operations_scheduler", OpsSchedulerAgent,
        )
        self.spawner.register_template(
            "operations_coordinator", OpsCoordinatorAgent,
        )

        # AD-749: M365 connector agents (when enabled)
        if self.config.m365.enabled and self._m365_token_manager:
            self.spawner.register_template("outlook", OutlookAgent)
            self.spawner.register_template("teams", TeamsAgent)
            self.spawner.register_template("calendar", CalendarAgent)
            self.spawner.register_template("sharepoint", SharePointAgent)
            self.spawner.register_template("onedrive", OneDriveAgent)
            logger.info("M365 connector agent templates registered")

        # AD-755: Office document skills (OSS desktop scope)
        office_cfg = getattr(self.config, "office_skills", None)
        if office_cfg and office_cfg.enabled:
            self.spawner.register_template("office_docx", DocxAgent)
            self.spawner.register_template("office_pptx", PptxAgent)
            self.spawner.register_template("office_xlsx", XlsxAgent)
            self._template_registry = TemplateRegistry(office_cfg.template_dir)
            logger.info("Office document skill templates registered")

        # --- CodebaseIndex (AD-290) ---
        self.codebase_index: CodebaseIndex | None = None
        self.nats_bus: NATSBus | None = None

    def register_agent_type(self, type_name: str, agent_class: type) -> None:
        """Register an agent class and refresh the decomposer's intent descriptors."""
        self.spawner.register_template(type_name, agent_class)
        if self.decomposer:
            self.decomposer.refresh_descriptors(self._collect_intent_descriptors())

    def unregister_agent_type(self, type_name: str) -> None:
        """Unregister an agent class and refresh the decomposer's intent descriptors."""
        self.spawner.unregister_template(type_name)
        if self.decomposer:
            self.decomposer.refresh_descriptors(self._collect_intent_descriptors())

    # --- HXI event emission (AD-254) ---

    def add_event_listener(
        self,
        fn: Callable[..., Any],
        event_types: Iterable[str] | None = None,
    ) -> None:
        """Register a listener for system events.

        AD-637d: When NATS connected, creates NATS subscriptions for the
        specified event types. Falls back to in-memory listener list when
        NATS disconnected.
        """
        type_filter = frozenset(str(t) for t in event_types) if event_types else None
        # Always append to local list (used as fallback when NATS disconnected)
        self._event_listeners.append((fn, type_filter))

        # AD-637d/637z: Create NATS subscription only AFTER bulk wiring is done.
        # Before _nats_events_wired, _setup_nats_event_subscriptions() handles all.
        # After the flag is set, new listeners get their own NATS sub immediately.
        if self._nats_events_wired and getattr(self, 'nats_bus', None) and self.nats_bus.connected:
            self._create_nats_event_subscription(fn, type_filter)

    def remove_event_listener(self, fn: Callable[..., Any]) -> None:
        """Remove a previously registered event listener."""
        self._event_listeners = [
            (f, tf) for f, tf in self._event_listeners if f is not fn
        ]

    def _create_nats_event_subscription(
        self,
        fn: Callable[..., Any],
        type_filter: frozenset[str] | None,
    ) -> None:
        """Create NATS subscription(s) for an event listener (AD-637d)."""
        async def _nats_callback(msg: Any) -> None:
            event = msg.data
            try:
                if asyncio.iscoroutinefunction(fn):
                    await fn(event)
                else:
                    fn(event)
            except Exception:
                logger.debug("NATS event listener failed for %s",
                             event.get("type", ""), exc_info=True)

        async def _do_subscribe() -> None:
            if type_filter:
                for event_type in type_filter:
                    subject = f"system.events.{event_type}"
                    await self.nats_bus.js_subscribe(
                        subject,
                        _nats_callback,
                        stream="SYSTEM_EVENTS",
                    )
            else:
                await self.nats_bus.js_subscribe(
                    "system.events.>",
                    _nats_callback,
                    stream="SYSTEM_EVENTS",
                )

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_do_subscribe())
            self._nats_publish_tasks.add(task)
            task.add_done_callback(self._nats_publish_tasks.discard)
        except RuntimeError:
            pass  # No event loop — local-only listener

    def _setup_nats_event_subscriptions(self) -> None:
        """Wire existing event listeners to NATS subscriptions (AD-637d).

        Called from finalize phase after SYSTEM_EVENTS stream is ensured.
        Listeners registered during early startup phases (before NATS was
        available) get retroactively wired to NATS subscriptions.
        """
        if not (getattr(self, 'nats_bus', None) and self.nats_bus.connected):
            return
        for fn, type_filter in self._event_listeners:
            self._create_nats_event_subscription(fn, type_filter)
        self._nats_events_wired = True

    def _emit_event(self, event_type: str | EventType, data: dict[str, Any] | None = None) -> None:
        """Fire-and-forget event to all registered listeners (AD-254).

        AD-637d: When NATS connected, publishes to JetStream. Subscribers
        receive via their NATS subscriptions. Falls back to in-memory dispatch
        when NATS disconnected.
        """
        # Step 1: Serialize event (unchanged)
        if isinstance(event_type, BaseEvent):
            event = event_type.to_dict()
        elif isinstance(event_type, EventType):
            event = {"type": event_type.value, "data": data or {}, "timestamp": time.time()}
        else:
            event = {"type": event_type, "data": data or {}, "timestamp": time.time()}
        type_str = event.get("type", "")

        # Step 2: Night Orders escalation (always local, synchronous)
        # AD-471: Intentionally runs BEFORE dispatch — ensures escalation fires
        # even if NATS publish or local dispatch fails.
        self._check_night_order_escalation(type_str, event.get("data", {}))

        # Step 3: Route — NATS or fallback (mutually exclusive, no-dual-delivery)
        if getattr(self, 'nats_bus', None) and self.nats_bus.connected:
            # AD-637d: JetStream publish
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("AD-637d: _emit_event called outside event loop, using fallback")
                self._emit_event_local(event, type_str)
                return
            subject = f"system.events.{type_str}"
            headers = {"X-Priority": Priority.NORMAL.value}
            task = loop.create_task(self.nats_bus.js_publish(subject, event, headers=headers))
            self._nats_publish_tasks.add(task)
            task.add_done_callback(self._nats_publish_tasks.discard)
        else:
            # Fallback: in-memory dispatch (original behavior)
            self._emit_event_local(event, type_str)

    def _emit_event_local(self, event: dict[str, Any], type_str: str) -> None:
        """In-memory event dispatch to registered listeners (fallback path, AD-637d)."""
        for fn, type_filter in self._event_listeners:
            if type_filter is not None and type_str not in type_filter:
                continue
            try:
                if asyncio.iscoroutinefunction(fn):
                    asyncio.create_task(fn(event))
                else:
                    fn(event)
            except Exception:
                logger.debug("Event listener failed for %s", type_str, exc_info=True)

    def emit_event(self, event: BaseEvent | str | EventType, data: dict[str, Any] | None = None) -> None:
        """Public typed event emission (AD-527).  Delegates to _emit_event."""
        if isinstance(event, BaseEvent):
            self._emit_event(event)
        else:
            self._emit_event(event, data or {})

    # --- AD-471: Autonomous operations helpers ---

    async def _dispatch_watch_intent(self, intent_type: str, params: dict) -> Any:
        """Bridge between WatchManager and intent bus."""
        from probos.intent import IntentMessage
        intent = IntentMessage(intent=intent_type, **params)
        return await self.intent_bus.publish(intent)

    def _populate_watch_roster(self) -> None:
        """Populate watch roster from ontology assignments.

        Each assignment in organization.yaml specifies which watches
        the agent stands (e.g., watches: [alpha, beta, gamma]).
        Defaults to [alpha] if omitted.
        """
        if not self.ontology or not self.watch_manager:
            return
        from probos.watch_rotation import WatchType
        _WATCH_MAP = {"alpha": WatchType.ALPHA, "beta": WatchType.BETA, "gamma": WatchType.GAMMA}
        crew_types = self.ontology.get_crew_agent_types()
        for agent_type in crew_types:
            assignment = self.ontology.get_assignment_for_agent(agent_type)
            if assignment:
                for agent in self.registry.all():
                    if agent.agent_type == agent_type:
                        for watch_name in assignment.watches:
                            watch = _WATCH_MAP.get(watch_name)
                            if watch:
                                self.watch_manager.assign_to_watch(
                                    agent.id, watch,
                                )

    def is_conn_qualified(self, agent_id: str) -> bool:
        """Check if an agent is qualified to hold the conn.

        Requirements:
        - COMMANDER+ rank (trust >= 0.7)
        - Bridge officer or department chief
        """
        agent = self.registry.get(agent_id)
        if not agent:
            return False

        # Check rank — Rank is in crew_profile, not earned_agency
        trust = TRUST_DEFAULT
        if self.trust_network:
            trust = self.trust_network.get_trust_score(agent.id)
        from probos.crew_profile import Rank
        rank = Rank.from_trust(trust)
        _RANK_ORDER = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
        if _RANK_ORDER.index(rank) < _RANK_ORDER.index(Rank.COMMANDER):
            return False

        # Check role — bridge officers and department chiefs
        if not self.ontology:
            return False
        post = self.ontology.get_post_for_agent(agent.agent_type)
        if not post:
            return False
        # Bridge officers (report directly to captain) or department chiefs
        CONN_ELIGIBLE_POSTS = {
            "first_officer", "counselor",
            "chief_engineer", "chief_science", "chief_medical",
            "chief_security", "chief_operations",
        }
        return post.id in CONN_ELIGIBLE_POSTS

    def _check_night_order_escalation(self, event_type: str, details: dict[str, Any] | None = None) -> None:
        """Check if a runtime event should trigger Night Orders escalation.

        Called from event emission points (trust changes, alert changes,
        build results). If the event matches a Night Orders escalation trigger,
        fires a bridge alert to wake the Captain.
        """
        if not hasattr(self, '_night_orders_mgr') or not self._night_orders_mgr:
            return
        if not self._night_orders_mgr.active:
            return

        # Map runtime events to Night Orders trigger names
        trigger_map = {
            "trust_change": "trust_drop",
            "alert_condition_change": "red_alert",
            "build_failure": "build_failure",
            "security_alert": "security_alert",
        }
        trigger = trigger_map.get(event_type)
        if not trigger:
            return

        # Additional condition checks
        if trigger == "trust_drop" and details:
            # Only escalate if trust dropped below floor
            new_trust = details.get("new_trust", 1.0)
            if new_trust >= TRUST_FLOOR_CONN:  # Not below floor
                return
        if trigger == "red_alert" and details:
            new_level = details.get("new_level", "")
            if new_level.lower() != "red":
                return

        # Check against Night Orders escalation triggers
        if self._night_orders_mgr.check_escalation(trigger):
            # Also notify conn manager
            if self.conn_manager:
                self.conn_manager.check_escalation(trigger, details)
            # Fire bridge alert
            if hasattr(self, 'bridge_alerts') and self.bridge_alerts:
                self.bridge_alerts.add_alert(
                    severity="critical",
                    title=f"Night Orders escalation: {trigger}",
                    source="night_orders",
                    details=details or {},
                )
            logger.warning("Night Orders escalation triggered: %s", trigger)

    async def _on_build_complete(self, build: Any) -> None:
        """Callback fired when a dispatched build finishes (AD-375)."""
        from probos.build_queue import QueuedBuild
        if not isinstance(build, QueuedBuild):
            return
        self._emit_event(EventType.BUILD_QUEUE_ITEM, {
            "item": {
                "id": build.id,
                "title": build.spec.title,
                "ad_number": build.spec.ad_number,
                "status": build.status,
                "priority": build.priority,
                "worktree_path": build.worktree_path,
                "builder_id": build.builder_id,
                "error": build.error,
                "file_footprint": build.file_footprint,
                "commit_hash": build.result.commit_hash if build.result else "",
            }
        })

    @property
    def records_store(self):
        """Ship's Records service (AD-434)."""
        return self._records_store

    @property
    def data_dir(self) -> Path:
        """AD-468: public read-only accessor for the runtime data directory."""
        return self._data_dir

    @property
    def procedure_store(self):
        """AD-534: Procedure store for replay-first dispatch."""
        return self._procedure_store

    @property
    def is_cold_start(self) -> bool:
        """True during first cycle after a clean reset (no prior state)."""
        return self._cold_start

    @property
    def llm_is_mock(self) -> bool:
        """BF-108: True when LLM is MockLLMClient (no real LLM available)."""
        return type(self.llm_client).__name__ == "MockLLMClient"

    @property
    def commercial_overlay_loaded(self) -> bool:
        """AD-697: True iff a commercial overlay registered any extension hooks."""
        from probos.extensions.overlay import is_commercial_loaded
        return is_commercial_loaded()

    @property
    def loaded_extension_providers(self) -> tuple[str, ...]:
        """AD-697: provider names that registered extension hooks (sorted)."""
        from probos.extensions.overlay import loaded_providers
        return loaded_providers()

    @property
    def billet_registry(self) -> Any:
        """AD-595a: Billet resolution facade (delegates to ontology)."""
        if self.ontology is None:
            return None
        return self.ontology.billet_registry

    @property
    def bill_runtime(self) -> Any:
        """AD-647c: Public read-only accessor for BillRuntime.

        Closes the Wave 5 conv #1 hole that AD-635 documented retrospectively
        for ``_emergent_detector``. ProcessChainExecutor uses this to record
        chain-step lifecycle against BillInstance steps when chains are
        bill-bound.
        """
        return self._bill_runtime

    @property
    def emergence_metrics_engine(self) -> Any:
        """Public accessor for emergence metrics engine (AD-680). Read-only."""
        return self._emergence_metrics_engine

    @property
    def attachment_store(self) -> Any:
        """AD-731: public accessor for the runtime's content-addressable
        attachment store. Delegates to the cached helper in routers/chat.py
        so the per-runtime cache stays in one place. Returns an instance
        satisfying the ``probos.attachments.store.AttachmentStore`` Protocol.
        """
        from probos.routers.chat import _get_attachment_store
        return _get_attachment_store(self)

    def build_state_snapshot(self) -> dict[str, Any]:
        """Build a full state snapshot for HXI clients (AD-254)."""
        from probos.earned_agency import agency_from_rank
        from probos.crew_profile import Rank

        agents = []
        for agent in self.registry.all():
            trust_score = self.trust_network.get_score(agent.id)
            # Look up display_name from crew profile registry
            profile = self.callsign_registry._type_to_profile.get(agent.agent_type, {})
            agents.append({
                "id": agent.id,
                "agent_type": agent.agent_type,
                "callsign": agent.callsign,  # BF-013
                "display_name": profile.get("display_name", ""),
                "pool": agent.pool,
                "state": agent.state.value if hasattr(agent.state, "value") else str(agent.state),
                "confidence": agent.confidence,
                "trust": format_trust(trust_score),
                "tier": getattr(agent, "tier", "core"),
                "isCrew": is_crew_agent(agent, self.ontology),
                "agency": agency_from_rank(Rank.from_trust(trust_score)).value,
            })

        connections = []
        for (source, target, rel_type), weight in self.hebbian_router.all_weights_typed().items():
            connections.append({
                "source": source,
                "target": target,
                "rel_type": rel_type,
                "weight": format_trust(weight),
            })

        pools = []
        for name, pool in self.pools.items():
            info = pool.info()
            pools.append({
                "name": name,
                "agent_type": info.get("agent_type", ""),
                "size": info.get("current_size", 0),
                "target_size": info.get("target_size", 0),
            })

        system_mode = "active"
        if self.dream_scheduler and self.dream_scheduler.is_dreaming:
            system_mode = "dreaming"
        elif (time.monotonic() - self._last_request_time) > 30:
            system_mode = "idle"

        tc_n = 0.0
        routing_entropy = 0.0
        if self._emergent_detector:
            try:
                snap = self._emergent_detector.summary()
                tc_n = snap.get("tc_n", 0.0)
                routing_entropy = snap.get("routing_entropy", 0.0)
            except Exception:
                logger.debug("Emergent detector summary failed", exc_info=True)

        return {
            "agents": agents,
            "connections": connections,
            "pools": pools,
            "system_mode": system_mode,
            "tc_n": format_trust(tc_n),
            "routing_entropy": format_trust(routing_entropy),
            "fresh_boot": self._fresh_boot or self._lifecycle_state == "reset",
            "temporal": {
                "current_time_utc": datetime.now(timezone.utc).isoformat(),
                "uptime_seconds": round(time.monotonic() - self._start_time, 1),
                "lifecycle_state": self._lifecycle_state,
                "stasis_duration": self._stasis_duration if self._lifecycle_state == "stasis_recovery" else None,
                "session_id": self._session_id,
            },
            "pool_groups": self.pool_groups.status(self.pools),
            "pool_to_group": dict(self.pool_groups._pool_to_group),
            "directives": self._directive_summary(),
            "notifications": self.notification_queue.snapshot(),
            "unread_count": self.notification_queue.unread_count(),
            "scheduled_tasks": self.persistent_task_store.snapshot() if self.persistent_task_store else [],
            "workforce": self.work_item_store.snapshot() if self.work_item_store else {"work_items": [], "bookings": []},
            "ward_room_stats": getattr(self.ward_room, '_last_stats', None) if self.ward_room else None,
            "skill_framework": self.skill_registry is not None,  # AD-428
            "acm": self.acm is not None,  # AD-427
        }

    def _directive_summary(self) -> dict[str, int]:
        """Build directive count summary for state snapshot (AD-386)."""
        if not self.directive_store:
            return {"active": 0, "pending": 0}
        active = self.directive_store.all_directives(include_inactive=False)
        return {
            "active": len([d for d in active if d.status.value == "active"]),
            "pending": len([d for d in active if d.status.value == "pending_approval"]),
        }

    def notify(
        self,
        agent_id: str,
        title: str,
        detail: str = "",
        notification_type: str = "info",
        action_url: str = "",
    ) -> None:
        """Let any agent emit a notification to the Captain (AD-323)."""
        agent = self._find_agent(agent_id)
        agent_type = agent.agent_type if agent else "unknown"
        department = self._get_agent_department(agent_id) if agent else ""
        self.notification_queue.notify(
            agent_id=agent_id,
            agent_type=agent_type,
            department=department,
            title=title,
            detail=detail,
            notification_type=notification_type,
            action_url=action_url,
        )

    def _find_agent(self, agent_id: str) -> Any:
        """Find an agent by ID across all pools."""
        return self.registry.get(agent_id)

    def _get_agent_department(self, agent_id: str) -> str:
        """Get the department (pool group name) of an agent."""
        agent = self.registry.get(agent_id)
        if not agent:
            return ""
        pool_name = agent.pool
        return self.pool_groups._pool_to_group.get(pool_name, "")

    async def create_pool(
        self,
        name: str,
        agent_type: str,
        target_size: int | None = None,
        agent_ids: list[str] | None = None,
        **spawn_kwargs: Any,
    ) -> ResourcePool:
        """Create and start a resource pool."""
        # AD-411: Guard against duplicate pool names
        if name in self.pools:
            logger.warning("Pool '%s' already exists — skipping duplicate creation", name)
            return self.pools[name]

        pool = ResourcePool(
            name=name,
            agent_type=agent_type,
            spawner=self.spawner,
            registry=self.registry,
            config=self.config.pools,
            target_size=target_size,
            agent_ids=agent_ids,
            **spawn_kwargs,
        )
        self.pools[name] = pool
        await pool.start()

        # Wire newly spawned agents into the mesh
        for agent in self.registry.get_by_pool(name):
            if self.onboarding:
                await self.onboarding.wire_agent(agent)
            # AD-889: commission crew agents at birth — walk Role → Skills → Tools.
            if self.acm and is_crew_agent(agent, self.ontology):
                try:
                    await self.acm.commission(agent.id, agent.agent_type, self)
                except Exception:
                    logger.debug(
                        "AD-889: commission skipped for %s (type=%s)",
                        agent.id, getattr(agent, "agent_type", "?"), exc_info=True,
                    )

        await self.event_log.log(
            category="system",
            event="pool_created",
            pool=name,
            detail=f"type={agent_type} size={pool.current_size}",
        )
        return pool

    async def _spawn_red_team(self, count: int) -> None:
        """Spawn red team agents (separate from pools — not on intent bus)."""
        for i in range(count):
            agent_id = generate_agent_id("red_team_verifier", "red_team", i)
            agent = RedTeamAgent(pool="red_team", agent_id=agent_id)
            await self.registry.register(agent)
            await agent.start()
            self.red_team_agents.append(agent)

            # Register capabilities and gossip, but NOT intent bus
            if agent.capabilities:
                self.capability_registry.register(agent.id, agent.capabilities)
            self.gossip.update_local(
                agent_id=agent.id,
                agent_type=agent.agent_type,
                state=agent.state,
                pool=agent.pool,
                capabilities=[c.can for c in agent.capabilities],
                confidence=agent.confidence,
            )
            self.trust_network.get_or_create(agent.id)

            await self.event_log.log(
                category="lifecycle",
                event="agent_wired",
                agent_id=agent.id,
                agent_type=agent.agent_type,
                pool="red_team",
                data={"department": "security"},  # AD-490: enriched wiring log
            )

        logger.info("Spawned %d red team agents", count)

    async def start(self) -> None:
        """Boot ProbOS: start mesh services, consensus layer, create default pools."""
        if self._started:
            return


        logger.info("=" * 60)
        logger.info("ProbOS %s starting...", self.config.system.version)
        logger.info("=" * 60)

        # --- AD-757: Identity and Continuity wiring ---
        from probos.captain_card.card import load_card, save_card, CaptainCard
        from probos.identity import VoiceProfileManager, AvatarProfileManager, ContinuityValidator
        from probos.cognitive.session_manager import SessionManager
        from probos.cognitive.task_recovery import TaskRecoveryManager
        import hashlib
        # Captain Card path
        captain_card_path = self._data_dir / "captain_card.json"
        # Load or create Captain Card
        if captain_card_path.exists():
            self.captain_card = load_card(captain_card_path)
        else:
            self.captain_card = CaptainCard()
            # Compute continuity checksum
            card_dict = self.captain_card.model_dump()
            card_json = str(sorted(card_dict.items())).encode("utf-8")
            self.captain_card.continuity_checksum = hashlib.sha256(card_json).hexdigest()
            save_card(self.captain_card, captain_card_path)

        # Voice/Avatar managers (placeholders)
        self.identity_manager = VoiceProfileManager()
        self.avatar_manager = AvatarProfileManager()
        self.continuity_validator = ContinuityValidator()

        # Session continuity
        self.session_manager = SessionManager(sessions_dir=self._data_dir / "sessions", user_id=self.captain_card.id)
        self.task_recovery = TaskRecoveryManager()
        self.active_session = await self.session_manager.restore_active_session(self.captain_card.id)
        if self.active_session:
            logger.info(f"Resumed session {self.active_session.id}")
            pending = await self.task_recovery.list_pending_delegations(self.active_session.id)
            logger.info(f"Pending delegations: {len(pending)}")

        # Bootstrap LLM context with Captain Card
        self._system_context = self.captain_card.to_system_context()

        # Phase 1: Infrastructure (AD-517)
        from probos.startup.infrastructure import boot_infrastructure

        infra = await boot_infrastructure(
            event_log=self.event_log,
            hebbian_router=self.hebbian_router,
            signal_manager=self.signal_manager,
            gossip=self.gossip,
            trust_network=self.trust_network,
            data_dir=self._data_dir,
            config=self.config,
            event_log_prune_loop_fn=self._event_log_prune_loop,
            background_register=self._background_tasks.add,
        )
        self.identity_registry = infra.identity_registry

        # Phase 1b: NATS event bus (AD-637)
        from probos.startup.nats import init_nats

        self.nats_bus = await init_nats(self.config)

        # AD-637b: Wire NATS transport into IntentBus
        if self.nats_bus:
            self.intent_bus.set_nats_bus(self.nats_bus)

        # Phase 2: Agent Fleet (AD-517)
        from probos.startup.agent_fleet import create_agent_fleet

        # Create onboarding service first — needed by onboarding.wire_agent during pool creation
        from probos.agent_onboarding import AgentOnboardingService as _AOS
        self.onboarding = _AOS(
            callsign_registry=self.callsign_registry,
            capability_registry=self.capability_registry,
            gossip=self.gossip,
            intent_bus=self.intent_bus,
            trust_network=self.trust_network,
            event_log=self.event_log,
            identity_registry=self.identity_registry,
            ontology=None,
            event_emitter=self._emit_event,
            config=self.config,
            llm_client=self.llm_client,
            registry=self.registry,
            ward_room=None,
            acm=None,
        )

        fleet = await create_agent_fleet(
            config=self.config,
            pools=self.pools,
            llm_client=self.llm_client,
            decomposer=self.decomposer,
            strategy_advisor=self._strategy_advisor,
            runtime=self,
            create_pool_fn=self.create_pool,
            spawn_red_team_fn=self._spawn_red_team,
            collect_intent_descriptors_fn=self._collect_intent_descriptors,
        )
        self.codebase_index = fleet.codebase_index

        # Phase 3: Fleet Organization (AD-517)
        from probos.startup.fleet_organization import organize_fleet

        org = await organize_fleet(
            config=self.config,
            pools=self.pools,
            pool_groups=self.pool_groups,
            escalation_manager=self.escalation_manager,
            intent_bus=self.intent_bus,
            trust_network=self.trust_network,
            llm_client=self.llm_client,
            build_pool_intent_map_fn=self._build_pool_intent_map,
            find_consensus_pools_fn=self._find_consensus_pools,
            build_self_model_fn=self._build_self_model,
            validate_remote_result_fn=self._validate_remote_result,
            nats_bus=self.nats_bus,
        )
        self.pool_scaler = org.pool_scaler
        self.federation_bridge = org.federation_bridge
        self._federation_transport = org.federation_transport

        # Phase 4: Cognitive Services (AD-517)
        from probos.startup.cognitive_services import init_cognitive_services

        cog = await init_cognitive_services(
            config=self.config,
            data_dir=self._data_dir,
            registry=self.registry,
            pools=self.pools,
            llm_client=self.llm_client,
            trust_network=self.trust_network,
            hebbian_router=self.hebbian_router,
            episodic_memory=self.episodic_memory,
            intent_bus=self.intent_bus,
            working_memory=self.working_memory,
            event_log=self.event_log,
            workflow_cache=self.workflow_cache,
            qa_reports=self._qa_reports,
            identity_registry=self.identity_registry,  # BF-103
            submit_intent_with_consensus_fn=self.submit_intent_with_consensus,
            register_designed_agent_fn=self._register_designed_agent,
            unregister_designed_agent_fn=self._unregister_designed_agent,
            create_designed_pool_fn=self._create_designed_pool,
            set_probationary_trust_fn=self._set_probationary_trust,
            add_skill_to_agents_fn=self._add_skill_to_agents,
            register_tool_fn=self._register_designed_tool,  # AD-886
            create_pool_fn=self.create_pool,
            emit_event_fn=self._emit_event,
            ontology=self.ontology,  # BF-118
        )
        self.self_mod_pipeline = cog.self_mod_pipeline
        self.behavioral_monitor = cog.behavioral_monitor
        self._system_qa = cog.system_qa
        self.feedback_engine = cog.feedback_engine
        self._correction_detector = cog.correction_detector
        self._agent_patcher = cog.agent_patcher
        self._knowledge_store = cog.knowledge_store
        self.warm_boot = cog.warm_boot_service
        self._records_store = cog.records_store
        self._strategy_advisor = cog.strategy_advisor
        self._lifecycle_state = cog.lifecycle_state
        self._stasis_duration = cog.stasis_duration
        self._previous_session = cog.previous_session

        # AD-722d: instantiate the records-writer once records_store is
        # available. Two-phase wiring — the attribute was declared as None
        # next to the AvatarEventBus construction; here we replace it.
        if (
            getattr(self.config, "avatar_telemetry", None) is not None
            and self.config.avatar_telemetry.enabled
            and self.config.avatar_telemetry.records_auto_write_enabled
            and self._records_store is not None
        ):
            from probos.avatars.records_writer import TelemetryRecordsWriter
            self.avatar_telemetry_records_writer = TelemetryRecordsWriter(
                records_store=self._records_store,
                runtime=self,
                throttle_seconds=self.config.avatar_telemetry.records_throttle_seconds,
                significant_events=self.config.avatar_telemetry.records_significant_events,
                sustained_silence_seconds=self.config.avatar_telemetry.sustained_silence_seconds,
                divergence_threshold=self.config.avatar_telemetry.divergence_negative_threshold,
            )
        self._activation_tracker = cog.activation_tracker  # AD-567d
        self._social_verification = cog.social_verification  # AD-567f
        self._orientation_service = cog.orientation_service  # AD-567g
        self._oracle_service = cog.oracle_service  # AD-462e
        self.oracle = cog.oracle_service  # AD-686 (public alias; same instance)
        self._archive_store = cog.archive_store  # AD-524
        self._consultation_protocol = cog.consultation_protocol  # AD-594
        self._expertise_directory = cog.expertise_directory  # AD-600
        self._telemetry_service = cog.telemetry_service  # AD-461
        self.dependency_resolver = cog.dependency_resolver  # AD-838c
        self.schema_version_store = cog.schema_version_store  # AD-818

        # AD-588: Introspective Telemetry Service
        try:
            from probos.cognitive.introspective_telemetry import IntrospectiveTelemetryService
            self._introspective_telemetry = IntrospectiveTelemetryService(runtime=self)
            logger.info("AD-588: IntrospectiveTelemetryService initialized")
        except Exception as e:
            logger.warning("IntrospectiveTelemetryService failed to start: %s — continuing without", e)
            self._introspective_telemetry = None

        # AD-533: Procedure Store (after RecordsStore, before Dreaming)
        try:
            from probos.cognitive.procedure_store import ProcedureStore

            procedure_store = ProcedureStore(
                data_dir=self._data_dir / "procedures",
                records_store=self._records_store,
            )
            await procedure_store.start()
            self._procedure_store = procedure_store
        except Exception as e:
            logger.warning("ProcedureStore failed to start: %s — continuing without", e)
            self._procedure_store = None

        # AD-566a: Qualification Harness
        try:
            from probos.cognitive.qualification import QualificationHarness, QualificationStore

            qual_store = QualificationStore(data_dir=self._data_dir)
            await qual_store.start()
            self._qualification_store = qual_store

            self._qualification_harness = QualificationHarness(
                store=qual_store,
                emit_event_fn=self._emit_event,
                config=self.config.qualification,
            )

            # AD-566b: Register Tier 1 baseline tests
            from probos.cognitive.qualification_tests import (
                PersonalityProbe,
                EpisodicRecallProbe,
                ConfabulationProbe,
                TemperamentProbe,
            )
            for test_cls in (PersonalityProbe, EpisodicRecallProbe, ConfabulationProbe, TemperamentProbe):
                self._qualification_harness.register_test(test_cls())

            # AD-566d: Register Tier 2 domain tests
            from probos.cognitive.domain_tests import (
                TheoryOfMindProbe,
                CompartmentalizationProbe,
                DiagnosticReasoningProbe,
                AnalyticalSynthesisProbe,
                CodeQualityProbe,
            )
            for test_cls in (TheoryOfMindProbe, CompartmentalizationProbe, DiagnosticReasoningProbe, AnalyticalSynthesisProbe, CodeQualityProbe):
                self._qualification_harness.register_test(test_cls())

            # AD-566e: Register Tier 3 collective tests
            from probos.cognitive.collective_tests import (
                CoordinationBreakevenProbe,
                ScaffoldDecompositionProbe,
                CollectiveIntelligenceProbe,
                ConvergenceRateProbe,
                EmergenceCapacityProbe,
            )
            for test_cls in (CoordinationBreakevenProbe, ScaffoldDecompositionProbe, CollectiveIntelligenceProbe, ConvergenceRateProbe, EmergenceCapacityProbe):
                self._qualification_harness.register_test(test_cls())

            # AD-569: Register Tier 3 behavioral probes
            from probos.cognitive.behavioral_probes import (
                FrameDiversityProbe,
                SynthesisDetectionProbe,
                CrossDeptTriggerProbe,
                ConvergenceCorrectnessProbe,
                AnchorGroundedEmergenceProbe,
            )
            for test_cls in (FrameDiversityProbe, SynthesisDetectionProbe, CrossDeptTriggerProbe, ConvergenceCorrectnessProbe, AnchorGroundedEmergenceProbe):
                self._qualification_harness.register_test(test_cls())

            # AD-582: Register memory competency probes
            from probos.cognitive.memory_probes import (
                SeededRecallProbe,
                KnowledgeUpdateProbe,
                TemporalReasoningProbe,
                CrossAgentSynthesisProbe,
                MemoryAbstentionProbe,
                RetrievalAccuracyBenchmark,
            )
            for test_cls in (
                SeededRecallProbe,
                KnowledgeUpdateProbe,
                TemporalReasoningProbe,
                CrossAgentSynthesisProbe,
                MemoryAbstentionProbe,
                RetrievalAccuracyBenchmark,
            ):
                self._qualification_harness.register_test(test_cls())

            # AD-642: Register Tier 2 communication quality probes
            if self.config.qualification.communication_benchmarks.enabled:
                from probos.cognitive.communication_benchmarks import (
                    ALL_COMMUNICATION_PROBES,
                )
                for probe in ALL_COMMUNICATION_PROBES:
                    self._qualification_harness.register_test(probe)
        except Exception as e:
            logger.warning("QualificationStore failed to start: %s — continuing without", e)
            self._qualification_store = None
            self._qualification_harness = None

        # AD-566c: Drift Detection Pipeline
        if self._qualification_harness and self._qualification_store:
            try:
                from probos.cognitive.drift_detector import DriftDetector, DriftScheduler

                drift_detector = DriftDetector(
                    store=self._qualification_store,
                    config=self.config.qualification,
                )
                self._drift_scheduler = DriftScheduler(
                    harness=self._qualification_harness,
                    detector=drift_detector,
                    emit_event_fn=self._emit_event,
                    config=self.config.qualification,
                    runtime=self,
                )
                await self._drift_scheduler.start()
            except Exception as e:
                logger.warning("DriftScheduler failed to start: %s — continuing without", e)
                self._drift_scheduler = None

        # AD-573: Start working memory persistence store
        try:
            await self.working_memory_store.start()
        except Exception as e:
            logger.warning("AD-573: WorkingMemoryStore failed to start: %s — continuing without", e)

        # Phase 5: Dreaming & Detection (AD-517)
        from probos.startup.dreaming import init_dreaming

        dream_result, cold_start = await init_dreaming(
            config=self.config,
            trust_network=self.trust_network,
            hebbian_router=self.hebbian_router,
            episodic_memory=self.episodic_memory,
            pool_scaler=self.pool_scaler,
            knowledge_store=self._knowledge_store,
            ward_room=self.ward_room,
            registry=self.registry,
            on_gap_predictions_fn=lambda p: self.dream_adapter.on_gap_predictions(p) if self.dream_adapter else None,
            on_contradictions_fn=lambda c: self.dream_adapter.on_contradictions(c) if self.dream_adapter else None,
            on_post_dream_fn=lambda r: self.dream_adapter.on_post_dream(r) if self.dream_adapter else None,
            on_pre_dream_fn=lambda: self.dream_adapter.on_pre_dream() if self.dream_adapter else None,
            on_post_micro_dream_fn=lambda r: self.dream_adapter.on_post_micro_dream(r) if self.dream_adapter else None,
            process_natural_language_fn=self.process_natural_language,
            periodic_flush_loop_fn=self._periodic_flush_loop_bridge,
            refresh_emergent_detector_roster_fn=self._refresh_roster_bridge,
            emit_event_fn=self._emit_event,  # AD-503
            llm_client=self.llm_client,  # AD-532: procedure extraction
            procedure_store=self._procedure_store,  # AD-533: persistent procedure storage
            runtime=self,  # AD-532e: for reactive event subscription
            activation_tracker=self._activation_tracker,  # AD-567d
            records_store=self._records_store,  # BF-106: available from Phase 4
            expertise_directory=self._expertise_directory,  # AD-600
        )
        self.dream_scheduler = dream_result.dream_scheduler
        self._emergent_detector = dream_result.emergent_detector
        self._emergence_metrics_engine = dream_result.emergence_metrics_engine
        self._notebook_quality_engine = dream_result.notebook_quality_engine  # AD-555
        self._retrieval_practice_engine = dream_result.retrieval_practice_engine  # AD-541c
        self._behavioral_metrics_engine = dream_result.behavioral_metrics_engine  # AD-569
        self.task_scheduler = dream_result.task_scheduler
        self._flush_task = dream_result.flush_task
        self.dreaming_engine = dream_result.dreaming_engine  # AD-690: needed by finalize wiring

        # AD-810: operator-facing recent-activity summary (read-side aggregation)
        from probos.cognitive.insights import InsightService
        self.insight_service = InsightService(
            runtime=self,
            llm_client=self.llm_client,  # fast tier honest-degrades if not configured
        )

        self._cold_start = cold_start
        if self._cold_start:
            self._lifecycle_state = "reset"

        # Phase 6: Structural Services (AD-517)
        from probos.startup.structural_services import init_structural_services

        struct, semantic_layer = await init_structural_services(
            config=self.config,
            data_dir=self._data_dir,
            registry=self.registry,
            pools=self.pools,
            spawner=self.spawner,
            trust_network=self.trust_network,
            intent_bus=self.intent_bus,
            hebbian_router=self.hebbian_router,
            episodic_memory=self.episodic_memory,
            emergent_detector=self._emergent_detector,
            emit_event_fn=self._emit_event,
            persist_manifest_fn=self._persist_manifest,
            on_build_complete_fn=self._on_build_complete,
        )
        self._semantic_layer = semantic_layer
        # AD-686: Stitch Tier 5 onto Oracle now that the semantic layer exists.
        if self._oracle_service is not None and semantic_layer is not None:
            try:
                self._oracle_service.attach_semantic_layer(semantic_layer)
            except Exception:
                logger.warning(
                    "AD-686: failed to attach semantic layer to OracleService; "
                    "Tier 5 semantic queries will return [] until restart",
                    exc_info=True,
                )
        self.sif = struct.sif
        self.initiative = struct.initiative
        self.build_queue = struct.build_queue
        self.build_dispatcher = struct.build_dispatcher
        self.service_profiles = struct.service_profiles
        self.directive_store = struct.directive_store
        self._bill_runtime = struct.bill_runtime  # AD-618d

        # Phase 7: Communication & Services (AD-517)
        from probos.startup.communication import init_communication

        comm = await init_communication(
            config=self.config,
            data_dir=self._data_dir,
            checkpoint_dir=self._checkpoint_dir,
            registry=self.registry,
            identity_registry=self.identity_registry,
            episodic_memory=self.episodic_memory,
            hebbian_router=self.hebbian_router,
            emit_event_fn=self._emit_event,
            process_natural_language_fn=self.process_natural_language,
            register_workforce_resources_fn=self._register_workforce_resources,
            journal_prune_loop_fn=self._journal_prune_loop,
            background_register=self._background_tasks.add,
            nats_bus=self.nats_bus,  # AD-637c: NATS JetStream for Ward Room events
        )
        self.persistent_task_store = comm.persistent_task_store
        self.work_item_store = comm.work_item_store
        self.ward_room = comm.ward_room

        # AD-462d: Social Memory Service (late-bound, needs ward_room from communication phase)
        self._social_memory_service = None
        if self.ward_room and getattr(self, 'episodic_memory', None):
            try:
                from probos.cognitive.social_memory import SocialMemoryService
                self._social_memory_service = SocialMemoryService(
                    ward_room=self.ward_room,
                    episodic_memory=self.episodic_memory,
                )
                logger.info("AD-462d: SocialMemoryService initialized")
            except Exception as e:
                logger.warning("SocialMemoryService failed to start: %s", e)

        # AD-979d: Cross-agent associative recall service (construction-only,
        # default-OFF). Late-bound after episodic_memory + hebbian_router exist;
        # no hot-path call in slice 1. escalate_recall() returns [] while
        # cross_agent_recall_enabled is False -> byte-identical.
        self._cross_agent_recall_service = None
        if getattr(self, "episodic_memory", None) and self.hebbian_router:
            try:
                from probos.cognitive.cross_agent_recall import CrossAgentRecallService
                self._cross_agent_recall_service = CrossAgentRecallService(
                    episodic_memory=self.episodic_memory,
                    hebbian_router=self.hebbian_router,
                    trust_network=self.trust_network,
                    enabled=self.config.memory.cross_agent_recall_enabled,
                    access_policy=self.config.memory.access_policy,
                )
                logger.info(
                    "AD-979d: CrossAgentRecallService initialized (enabled=%s)",
                    self.config.memory.cross_agent_recall_enabled,
                )
            except Exception as e:
                logger.warning("AD-979d: CrossAgentRecallService failed to start: %s", e)

        # AD-567c: Late-bind WardRoom into SIF for anchor integrity cross-reference
        if self.sif and self.ward_room:
            self.sif.set_ward_room(self.ward_room)

        # AD-638: Boot camp coordinator (late-bound, needs ward_room + trust + episodic)
        if (
            self.config.boot_camp.enabled
            and self.ward_room
            and self.trust_network
            and getattr(self, 'episodic_memory', None)
        ):
            try:
                self.boot_camp = BootCampCoordinator(
                    config=self.config.boot_camp,
                    ward_room=self.ward_room,
                    trust_service=self.trust_network,
                    episodic_memory=self.episodic_memory,
                    emit_event_fn=self._emit_event,
                    ship_state_builder=getattr(self, "ship_state_snapshot", None),  # AD-683
                )
                logger.info("AD-638: BootCampCoordinator initialized")
            except Exception as e:
                logger.warning("AD-638: BootCampCoordinator failed to start: %s", e)

        self.assignment_service = comm.assignment_service
        self.bridge_alerts = comm.bridge_alerts
        self.clearance_grant_store = comm.clearance_grant_store
        self.clinical_notes_store = comm.clinical_notes_store
        self.capability_request_store = comm.capability_request_store
        self.skill_request_store = comm.skill_request_store
        self.tool_registry = comm.tool_registry
        self.tool_permission_store = comm.tool_permission_store
        self.cognitive_journal = comm.cognitive_journal
        self.knowledge_edges = comm.knowledge_edges  # AD-687
        # AD-688: Stitch Tier 6 onto Oracle now that the knowledge graph exists.
        if self._oracle_service is not None and self.knowledge_edges is not None:
            try:
                self._oracle_service.attach_knowledge_graph(self.knowledge_edges)
            except Exception:
                logger.warning(
                    "AD-688: failed to attach knowledge graph to OracleService; "
                    "Tier 6 graph queries will return [] until restart",
                    exc_info=True,
                )
        # BF-264: Stitch CallsignRegistry onto Oracle for callsign→agent_type expansion.
        if self._oracle_service is not None:
            try:
                self._oracle_service.attach_callsign_registry(self.callsign_registry)
            except Exception:
                logger.debug("BF-264: failed to attach callsign_registry to Oracle", exc_info=True)
        self.skill_registry = comm.skill_registry
        self.skill_service = comm.skill_service
        # AD-566f: Qualification → Skill Bridge
        self._qual_skill_bridge = None
        if self.skill_service and getattr(self, "_qualification_store", None):
            from probos.cognitive.qual_skill_bridge import QualificationSkillBridge

            self._qual_skill_bridge = QualificationSkillBridge(
                skill_service=self.skill_service,
                qualification_store=self._qualification_store,
            )
            self._qual_skill_bridge.register_mappings({
                "threat_analysis_t1": "threat_analysis",
                "ward_room_communication_t1": "ward_room_communication",
                "trust_assessment_t1": "trust_assessment",
            })
            logger.info(
                "AD-566f: QualificationSkillBridge initialized with %d mappings",
                len(self._qual_skill_bridge.get_mappings()),
            )
        self.cognitive_skill_catalog = comm.cognitive_skill_catalog
        self.skill_grant_store = comm.skill_grant_store
        self.intent_grant_store = comm.intent_grant_store
        self.hook_bus = comm.hook_bus  # AD-1004 substrate / AD-1012 wiring
        self.acm = comm.acm
        self.ontology = comm.ontology

        # AD-637: Update NATS subject prefix after ship commissioning assigns DID
        if self.nats_bus and self.identity_registry:
            cert = self.identity_registry.get_ship_certificate()
            if cert:
                await self.nats_bus.set_subject_prefix(f"probos.{cert.ship_did}")
                logger.info("AD-637: NATS subject prefix updated to probos.%s", cert.ship_did)

        # AD-596c (BF-596b fix): Wire cognitive skill catalog into standing orders
        # Must be AFTER Phase 7 assigns self.cognitive_skill_catalog from comm result
        if self.cognitive_skill_catalog:
            from probos.cognitive.standing_orders import set_skill_catalog
            set_skill_catalog(self.cognitive_skill_catalog)

        # AD-596c: Create SkillBridge to coordinate T2 catalog and T3 registry
        self.skill_bridge = None
        if self.cognitive_skill_catalog and self.skill_registry and self.skill_service:
            from probos.cognitive.skill_bridge import SkillBridge
            self.skill_bridge = SkillBridge(
                catalog=self.cognitive_skill_catalog,
                skill_registry=self.skill_registry,
                skill_service=self.skill_service,
            )
            try:
                sync_result = await self.skill_bridge.validate_and_sync()
                logger.info("AD-596c: Skill bridge synced — %s", sync_result)
            except Exception:
                logger.warning("AD-596c: Skill bridge sync failed", exc_info=True)

        # AD-628 v1: Crew skill readiness monitoring + Training Officer wiring
        self.skill_readiness_service = None
        self.drill_calendar = None
        self.readiness_reporter = None
        self.limdu_service = None
        if self.skill_service is not None:
            from probos.cognitive.skill_readiness import (
                AgentSkillReadinessService,
                SkillRegressionEvent,
            )
            advancement_log = (
                getattr(self._qual_skill_bridge, "_advancement_history", None)
                if self._qual_skill_bridge is not None else None
            )
            self.skill_readiness_service = AgentSkillReadinessService(
                self.skill_service,
                advancement_log=advancement_log,
                registry=self.skill_registry,
            )

            # AD-628a: feed SKILL_REGRESSION + SKILL_DECAY events into the
            # readiness service ring AND forward to the runtime emitter.
            _readiness = self.skill_readiness_service
            _runtime_emit = self._emit_event
            from probos.events import EventType as _ET

            def _skill_telemetry_emitter(event_type: Any, payload: dict[str, Any]) -> None:
                try:
                    if event_type in (_ET.SKILL_REGRESSION, _ET.SKILL_DECAY):
                        _readiness.record_regression(SkillRegressionEvent(
                            agent_id=payload.get("agent_id", ""),
                            skill_id=payload.get("skill_id", ""),
                            from_level=int(payload.get("from_level") or 0),
                            to_level=int(payload.get("to_level") or 0),
                            timestamp=float(payload.get("timestamp") or 0.0),
                            reason=payload.get("reason", ""),
                        ))
                except Exception:
                    logger.warning("AD-628a: regression-ring forward failed", exc_info=True)
                try:
                    _runtime_emit(event_type, payload)
                except Exception:
                    logger.debug("AD-628a: runtime event forward failed", exc_info=True)

            self.skill_service.set_event_emitter(_skill_telemetry_emitter)

            if self._qualification_harness is not None:
                from probos.cognitive.drill_calendar import DrillCalendar
                self.drill_calendar = DrillCalendar(
                    self._qualification_harness, runtime=self,
                )

            from probos.cognitive.readiness_reporter import ReadinessReporter
            self.readiness_reporter = ReadinessReporter(
                self.skill_readiness_service,
                self.ontology,
                self.registry,
                skill_registry=self.skill_registry,
            )

            if self.drill_calendar is not None:
                from probos.cognitive.limdu import LIMDUService

                _bridge = self._qual_skill_bridge

                def _test_for_skill(skill_id: str) -> str | None:
                    if _bridge is None:
                        return None
                    try:
                        for test_name, mapped_skill in (
                            _bridge._test_skill_map.items()
                        ):
                            if mapped_skill == skill_id:
                                return test_name
                    except Exception:
                        return None
                    return None

                self.limdu_service = LIMDUService(
                    self.skill_readiness_service,
                    self.drill_calendar,
                    circuit_breaker=getattr(self, "circuit_breaker", None),
                    test_for_skill=_test_for_skill,
                )
                self.limdu_service.set_event_emitter(self._emit_event)
            logger.info("AD-628: crew skill readiness services wired")

        # PATCH(AD-517): Wire ontology into WardRoom (constructed before ontology init)
        if self.ontology and self.ward_room:
            self.ward_room.set_ontology(self.ontology)

        # AD-750: Semantic work layer bootstrap (after AD-749 M365 wiring,
        # before finalize/start of higher-level crew loops).
        await self._initialize_semantic_work_layer()

        # Phase 8: Finalization (AD-517)
        from probos.startup.finalize import finalize_startup

        fin = await finalize_startup(runtime=self, config=self.config)
        self.conn_manager = fin.conn_manager
        self._night_orders_mgr = fin.night_orders_mgr
        self.watch_manager = fin.watch_manager
        self.proactive_loop = fin.proactive_loop
        self.ward_room_router = fin.ward_room_router
        self.self_mod_manager = fin.self_mod_manager
        self.dream_adapter = fin.dream_adapter
        # AD-521: BuildPipeline Ship's Computer service.
        self.build_pipeline = BuildPipeline(runtime=self)

        # AD-654a: Wire up WardRoomPostPipeline for agent self-posting
        # BF-238: Construct PostBudgetTelemetry first so the pipeline can
        # record invocation + exhaustion events.
        from probos.ward_room_pipeline import (
            PostBudgetTelemetry,
            WardRoomPostPipeline,
        )
        pbt_cfg = self.config.post_budget_telemetry
        self.post_budget_telemetry: PostBudgetTelemetry | None = None
        if pbt_cfg.enabled:
            self.post_budget_telemetry = PostBudgetTelemetry(
                exhaustion_alert_threshold=pbt_cfg.exhaustion_alert_threshold,
                min_samples_for_alert=pbt_cfg.min_samples_for_alert,
                recent_suppressions_max=pbt_cfg.recent_suppressions_max,
            )
        self.ward_room_post_pipeline: WardRoomPostPipeline | None = None
        if self.ward_room:
            self.ward_room_post_pipeline = WardRoomPostPipeline(
                ward_room=self.ward_room,
                ward_room_router=self.ward_room_router,
                proactive_loop=self.proactive_loop,
                trust_network=self.trust_network,
                callsign_registry=getattr(self, 'callsign_registry', None),
                config=self.config,
                runtime=self,
                novelty_gate=getattr(self, '_novelty_gate', None),
                post_budget_telemetry=self.post_budget_telemetry,
            )

        # AD-823 + AD-824 + AD-825: schedule the daily episodic backup
        # loop via the runtime's drain-on-shutdown registry. The loop
        # writes a tar snapshot of Chroma's on-disk footprint; if
        # cancelled mid-tar the snapshot file is corrupt. The drain
        # phase in startup/shutdown.py gives it the configured
        # ``memory.shutdown_drain_timeout_s`` window to finish the
        # current tar before the AD-824 cancel sweep would fire.
        self._episodic_backup_task = self._spawn_background(
            self._episodic_backup_loop(),
            name="episodic-backup-loop",
            drain_on_shutdown=True,
        )

        # AD-828b: startup fully complete — the cognitive layer (dream_scheduler,
        # episodic_memory) is wired. A shutdown after this point that still skips
        # consolidation is a real failure, not a killed-mid-boot event.
        self._startup_complete = True

    async def _initialize_semantic_work_layer(self) -> None:
        """AD-750: Initialize semantic storage, session continuity, and data mapping.

        Personal-desktop scope only:
        - local SQLite semantic store
        - local JSON session continuity files
        - bootstrap from episodic memory + available local M365 connectors
        """
        semantic_db_path = str(self._data_dir / "semantic_work.db")
        self._semantic_store = SemanticStore(
            db_path=semantic_db_path,
            owner_id="captain",
        )
        self._session_manager = SessionManager(
            sessions_dir=self._data_dir / "sessions",
            user_id="captain",
        )

        mapper = SemanticMapper(
            store=self._semantic_store,
            owner_id="captain",
            episodic_memory=self.episodic_memory,
        )

        try:
            migrated = await mapper.bootstrap_from_episodic(self._semantic_store)
            logger.info("AD-750: semantic episodic bootstrap migrated=%d", migrated)
        except Exception:
            logger.warning(
                "AD-750: semantic episodic bootstrap failed; continuing with empty store",
                exc_info=True,
            )

        connectors = self._collect_m365_connectors_for_semantic_sync()
        if connectors:
            try:
                synced = await mapper.sync_m365_to_semantic(connectors)
                logger.info(
                    "AD-750: semantic M365 sync inserted_or_updated=%d connectors=%d",
                    synced,
                    len(connectors),
                )
            except Exception:
                logger.warning(
                    "AD-750: semantic M365 sync failed; continuing without M365 hydration",
                    exc_info=True,
                )

    def _collect_m365_connectors_for_semantic_sync(self) -> list[Any]:
        """AD-750: collect runtime connector agents that expose list_changes()."""
        connectors: list[Any] = []
        for agent in self.registry.all():
            if not hasattr(agent, "list_changes"):
                continue
            if getattr(agent, "agent_type", "") not in {
                "OutlookAgent",
                "CalendarAgent",
                "TeamsAgent",
                "SharePointAgent",
                "OneDriveAgent",
            }:
                continue
            connectors.append(agent)
        return connectors

    # --- BF-071: Retention prune loops ---

    def _spawn_background(
        self,
        coro: "Coroutine[Any, Any, Any]",
        name: str,
        *,
        drain_on_shutdown: bool = False,
    ) -> asyncio.Task:
        """AD-824 + AD-825: spawn a long-lived runtime-owned background task.

        By default the task is stored in ``self._background_tasks`` and
        the shutdown sweep in ``startup/shutdown.py`` cancels it before
        the AD-820 clean-shutdown marker is written. Uses ``.discard``
        (not ``.remove``) in the done-callback so a duplicate removal
        never raises.

        Use ONLY for loops that live for the runtime's lifetime. For
        per-event fan-out tasks (ward room alerts, QA, NATS publish)
        continue to use ``asyncio.create_task`` directly with whatever
        per-feature registry already exists.

        AD-825 — ``drain_on_shutdown=True``:
            The task is stored in ``self._drain_tasks`` instead. The
            shutdown sequence runs a drain phase BEFORE the AD-824
            cancel sweep: ``self._shutdown_event`` is set and the
            shutdown awaits ``asyncio.wait(_drain_tasks,
            timeout=memory.shutdown_drain_timeout_s)``. Tasks that
            exit cleanly within the budget never see ``CancelledError``;
            tasks that don't exit in time fall through to the AD-824
            cancel sweep.

            Drain-tagged loops MUST follow this contract:
            1. Replace inner ``await asyncio.sleep(N)`` with::

                   try:
                       await asyncio.wait_for(
                           self._shutdown_event.wait(),
                           timeout=N,
                       )
                   except asyncio.TimeoutError:
                       pass  # normal idle tick

               (Exits the wait immediately on shutdown; otherwise
               continues looping each N seconds.)
            2. On ``self._shutdown_event.is_set()`` becoming True,
               finish the current atomic operation (any open write)
               inside a ``try/finally`` and ``return`` cleanly — do NOT
               ``raise CancelledError``.
            3. Keep the outer ``except asyncio.CancelledError:
               <cleanup>; raise`` arm from AD-824 as the fallback path
               for the cancel sweep.
        """
        task = asyncio.create_task(coro, name=name)
        if drain_on_shutdown:
            registry = self._drain_tasks
        else:
            registry = self._background_tasks
        registry.add(task)
        task.add_done_callback(registry.discard)
        return task

    def _signal_drain_stop(self) -> None:
        """AD-825: signal drain-tagged background loops to exit cleanly.

        Idempotent — calling more than once is a no-op. Drain-tagged
        loops check ``self._shutdown_event`` on every iteration and
        return cleanly the next time they wake up.
        """
        if not self._shutdown_event.is_set():
            self._shutdown_event.set()

    async def _event_log_prune_loop(self) -> None:
        """Periodic event log retention cleanup.

        AD-824: explicit ``CancelledError`` arm so the shutdown sweep
        terminates this loop deterministically.
        """
        cfg = self.config.event_log
        try:
            while True:
                await asyncio.sleep(cfg.prune_interval_seconds)
                try:
                    await self.event_log.prune(
                        retention_days=cfg.retention_days,
                        max_rows=cfg.max_rows,
                    )
                except Exception:
                    logger.debug("Event log prune failed", exc_info=True)
        except asyncio.CancelledError:
            logger.debug("AD-824: _event_log_prune_loop cancelled")
            raise

    async def _journal_prune_loop(self) -> None:
        """Periodic cognitive journal retention cleanup.

        AD-824: explicit ``CancelledError`` arm.
        """
        cfg = self.config.cognitive_journal
        try:
            while True:
                await asyncio.sleep(cfg.prune_interval_seconds)
                try:
                    await self.cognitive_journal.prune(
                        retention_days=cfg.retention_days,
                        max_rows=cfg.max_rows,
                    )
                except Exception:
                    logger.debug("Journal prune failed", exc_info=True)
        except asyncio.CancelledError:
            logger.debug("AD-824: _journal_prune_loop cancelled")
            raise

    async def _episodic_backup_loop(self) -> None:
        """AD-823: daily uncompressed-tar snapshot of chroma's on-disk footprint.

        First snapshot fires 60s after boot (warmup window so the runtime
        is past startup before any disk pressure from tar). Subsequent
        snapshots fire every 24h. Pairs with AD-822 (boot probe) and
        AD-819 (rebuild from ward room) as the third-line recovery
        primitive — not prevention, just the last line of defense if
        both chroma and the ward room go missing.

        Loop tolerates exceptions so a transient failure (disk full,
        permission flip) does not kill the task forever.
        """
        from probos.maintenance.episodic_backup import snapshot_episodic

        if not self.config.memory.backup_enabled:
            logger.info("AD-823: episodic backup disabled by config; loop exiting")
            return

        data_dir = Path(self._data_dir)
        backups_dir = data_dir / "backups" / "episodic"
        retain_days = self.config.memory.backup_retain_days

        # AD-825: warmup before first snapshot — exit immediately if
        # shutdown was signalled during the warmup window.
        try:
            await asyncio.wait_for(
                self._shutdown_event.wait(), timeout=60.0,
            )
            return
        except asyncio.TimeoutError:
            pass
        try:
            while True:
                # AD-825: early-exit check before starting a new tar.
                if self._shutdown_event.is_set():
                    return
                try:
                    try:
                        result = snapshot_episodic(
                            data_dir, backups_dir, retain_days=retain_days,
                        )
                        if result.ok:
                            logger.info(
                                "AD-823: snapshot tick ok path=%s bytes=%d skipped=%s",
                                result.path, result.bytes_written, result.skipped_reason,
                            )
                        else:
                            logger.warning(
                                "AD-823: snapshot tick failed reason=%s",
                                result.skipped_reason,
                            )
                    except Exception:
                        logger.warning("AD-823: snapshot tick raised", exc_info=True)
                finally:
                    # AD-825: after the atomic tar attempt, re-check
                    # shutdown so the loop returns cleanly without
                    # waiting another 24h tick when drain is pending.
                    if self._shutdown_event.is_set():
                        return
                # AD-825: drain-aware idle wait — wakes immediately on
                # shutdown instead of sleeping the full 24h.
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=86400.0,
                    )
                    return
                except asyncio.TimeoutError:
                    pass  # normal idle tick
        except asyncio.CancelledError:
            logger.debug("AD-824: _episodic_backup_loop cancelled")
            raise

    def _refresh_roster_bridge(self) -> None:
        """Bridge for Phase 5: refresh emergent detector roster before dream_adapter exists."""
        if self.dream_adapter:
            self.dream_adapter.refresh_emergent_detector_roster()
        elif self._emergent_detector:
            # During Phase 5 startup, dream_adapter doesn't exist yet.
            # Inline the roster refresh logic directly.
            live_ids: set[str] = set()
            for pool in self.pools.values():
                for agent_id in pool.healthy_agents:
                    aid = agent_id if isinstance(agent_id, str) else agent_id.id
                    live_ids.add(aid)
            self._emergent_detector.set_live_agents(live_ids)

    async def _periodic_flush_loop_bridge(self) -> None:
        """Bridge for Phase 5: periodic flush — no-op if dream_adapter not yet created.

        Finalize phase (Phase 8) cancels this task and creates a new one
        using dream_adapter.periodic_flush_loop() directly.
        """
        if self.dream_adapter:
            await self.dream_adapter.periodic_flush_loop()

    async def stop(self, reason: str = "") -> None:
        """Graceful shutdown of all pools, mesh services, and persistence."""
        from probos.startup.shutdown import shutdown
        await shutdown(self, reason)

    # --- Workforce Scheduling Engine helpers (AD-496) ---

    async def _register_workforce_resources(
        self, work_item_store: Any | None = None
    ) -> None:
        """Register all commissioned agents as BookableResources.

        BF-331: ``work_item_store`` may be passed explicitly by the
        communication startup phase, which calls this *before*
        ``self.work_item_store`` has been assigned from the returned
        ``init_communication`` result. Falling back to the instance
        attribute keeps the existing zero-argument call sites working.
        """
        store = work_item_store or self.work_item_store
        if not store:
            return
        from probos.workforce import BookableResource, AgentCalendar, CalendarEntry
        for agent in self.registry.all():
            resource = BookableResource(
                resource_id=getattr(agent, 'agent_uuid', '') or agent.id,
                resource_type="crew" if hasattr(agent, 'personality') else "infrastructure",
                agent_type=agent.agent_type,
                callsign=getattr(agent, 'callsign', agent.agent_type),
                capacity=self.config.workforce.default_capacity,
                department=getattr(agent, 'department', ''),
                characteristics=self._build_resource_characteristics(agent),
                display_on_board=hasattr(agent, 'personality'),
                active=True,
            )
            store.register_resource(resource)
            calendar = AgentCalendar(
                resource_id=resource.resource_id,
                entries=[CalendarEntry()],
            )
            store.register_calendar(calendar)

    def _build_resource_characteristics(self, agent: Any) -> list[dict[str, Any]]:
        """Build characteristics list from agent capabilities and trust."""
        characteristics: list[dict[str, Any]] = []
        characteristics.append({"skill": agent.agent_type, "proficiency": 1.0})
        dept = getattr(agent, 'department', '')
        if dept:
            characteristics.append({"skill": dept, "proficiency": 1.0})
        if self.trust_network:
            trust = self.trust_network.get_score(agent.id)
            characteristics.append({"skill": "trust", "proficiency": trust})
        return characteristics

    async def submit_intent(
        self,
        intent: str,
        params: dict[str, Any] | None = None,
        urgency: float = 0.5,
        context: str = "",
        timeout: float | None = None,
    ) -> list[IntentResult]:
        """Submit an intent to the mesh and collect results from self-selecting agents."""
        msg = IntentMessage(
            intent=intent,
            params=params or {},
            urgency=urgency,
            context=context,
            ttl_seconds=timeout or self.config.mesh.signal_ttl_seconds,
        )

        broadcast_row_id = await self.event_log.log(
            category="mesh",
            event="intent_broadcast",
            detail=f"intent={intent} id={msg.id[:8]}",
            correlation_id=msg.id,
            data={"intent": intent, "msg_id": msg.id, "ttl_seconds": msg.ttl_seconds},
        )

        results = await self.intent_bus.broadcast(msg, timeout=timeout)

        # Update hebbian weights based on results
        for result in results:
            self.hebbian_router.record_interaction(
                source=intent,  # intent name, not msg UUID — enables reinforcement
                target=result.agent_id,
                success=result.success,
            )

            # Emit hebbian_update for HXI (AD-254)
            self._emit_event(EventType.HEBBIAN_UPDATE, {
                "source": intent,
                "target": result.agent_id,
                "weight": format_trust(self.hebbian_router.get_weight(intent, result.agent_id)),
                "rel_type": "intent",
            })

        # BF-165: Signal cognitive activity to emergent detector
        if self._emergent_detector:
            self._emergent_detector.record_activity()

        await self.event_log.log(
            category="mesh",
            event="intent_resolved",
            detail=f"intent={intent} id={msg.id[:8]} results={len(results)}",
            correlation_id=msg.id,
            data={
                "intent": intent,
                "msg_id": msg.id,
                "result_count": len(results),
                "agent_ids": [r.agent_id for r in results] if results else [],
            },
            parent_event_id=broadcast_row_id,
        )

        return results

    async def ensure_dependency(
        self, import_name: str | list[str]
    ) -> "DependencyResult":
        """AD-838c: Ensure one or more third-party packages are importable.

        Copilot-style ask-before-install for the runtime task path. Disabled by
        default; requires ``config.dependency.dynamic_install_enabled``. Auto-approves
        imports already in ``config.self_mod.allowed_imports`` (the whitelist tier);
        unlisted imports require an approval callback (wired by the shell) under the
        ``prompt_unlisted`` policy. All install activity is logged to the event log.
        """
        from probos.cognitive.dependency_resolver import DependencyResult

        resolver = getattr(self, "dependency_resolver", None)
        if resolver is None:
            return DependencyResult(
                success=False,
                error="dynamic dependency installation disabled",
            )

        names = [import_name] if isinstance(import_name, str) else list(import_name)
        source = "\n".join(f"import {n}" for n in names)
        missing = resolver.detect_missing(source)

        if self.event_log:
            await self.event_log.log(
                category="dependency",
                event="dependency_check",
                detail=json.dumps(
                    {"requested": names, "missing_count": len(missing), "missing": missing}
                ),
            )

        if not missing:
            return DependencyResult(success=True, installed=[])

        # Defense in depth: if no approval callback is wired, the prompt tier
        # cannot be approved interactively. Hard-decline unlisted packages rather
        # than installing silently. Use the PUBLIC allowed_imports as the
        # auto-approve set (do not reach into resolver privates).
        if resolver._approval_fn is None:
            auto = set(self.config.self_mod.allowed_imports)
            prompt_tier = [
                m
                for m in missing
                if m not in auto
                and not any(a.split(".")[0] == m for a in auto)
            ]
            if prompt_tier:
                if self.event_log:
                    await self.event_log.log(
                        category="dependency",
                        event="dependency_install_declined",
                        detail=json.dumps(
                            {"packages": prompt_tier, "reason": "approval_callback_unavailable"}
                        ),
                    )
                return DependencyResult(
                    success=False,
                    declined=prompt_tier,
                    error="approval callback unavailable",
                )

        result = await resolver.resolve(source)

        if (result.installed or result.failed) and self.event_log:
            await self.event_log.log(
                category="dependency",
                event="dependency_install_approved",
                detail=json.dumps({"packages": result.installed + result.failed}),
            )
        if result.installed and self.event_log:
            for pkg in result.installed:
                await self.event_log.log(
                    category="dependency",
                    event="dependency_install_success",
                    detail=json.dumps({"package": pkg, "import_name": pkg}),
                )
        if result.declined and self.event_log:
            await self.event_log.log(
                category="dependency",
                event="dependency_install_declined",
                detail=json.dumps({"packages": result.declined}),
            )
        if result.failed and self.event_log:
            for pkg in result.failed:
                await self.event_log.log(
                    category="dependency",
                    event="dependency_install_failed",
                    detail=json.dumps({"package": pkg, "error": result.error or "unknown"}),
                )

        return result

    async def submit_intent_with_consensus(
        self,
        intent: str,
        params: dict[str, Any] | None = None,
        urgency: float = 0.5,
        context: str = "",
        timeout: float | None = None,
        policy: QuorumPolicy | None = None,
    ) -> dict[str, Any]:
        """Submit an intent with full consensus pipeline.

        1. Broadcast intent to agents
        2. Evaluate quorum from agent results
        3. Run red team verification on a sample
        4. Update trust network based on verification
        5. Update hebbian weights (agent-to-agent for verifications)

        Returns a dict with results, consensus, and verification details.
        """
        msg = IntentMessage(
            intent=intent,
            params=params or {},
            urgency=urgency,
            context=context,
            ttl_seconds=timeout or self.config.mesh.signal_ttl_seconds,
        )

        consensus_broadcast_row_id = await self.event_log.log(
            category="mesh",
            event="intent_broadcast",
            detail=f"intent={intent} id={msg.id[:8]} consensus=true",
            correlation_id=msg.id,
            data={"intent": intent, "msg_id": msg.id, "consensus": True},
        )

        # Step 1: Broadcast and collect results
        results = await self.intent_bus.broadcast(msg, timeout=timeout)

        # Update hebbian weights (intent → agent)
        for result in results:
            self.hebbian_router.record_interaction(
                source=intent,  # intent name, not msg UUID — enables reinforcement
                target=result.agent_id,
                success=result.success,
            )

            # Emit hebbian_update for HXI (AD-254)
            self._emit_event(EventType.HEBBIAN_UPDATE, {
                "source": intent,
                "target": result.agent_id,
                "weight": format_trust(self.hebbian_router.get_weight(intent, result.agent_id)),
                "rel_type": "intent",
            })

        # BF-165: Signal cognitive activity to emergent detector
        if self._emergent_detector:
            self._emergent_detector.record_activity()

        # Step 2: Evaluate quorum
        consensus = self.quorum_engine.evaluate(results, policy=policy)

        # Emit consensus event for HXI (AD-254)
        self._emit_event(EventType.CONSENSUS, {
            "intent": intent,
            "outcome": consensus.outcome.value,
            "approval_ratio": format_trust(consensus.approval_ratio),
            "votes": len(results),
            "shapley": consensus.shapley_values or {},
        })

        # Store latest Shapley values for introspection (AD-224)
        if consensus.shapley_values:
            self._last_shapley_values = consensus.shapley_values

        await self.event_log.log(
            category="consensus",
            event="quorum_evaluated",
            detail=(
                f"intent={intent} id={msg.id[:8]} outcome={consensus.outcome.value} "
                f"approval={consensus.approval_ratio:.3f}"
            ),
        )

        # Step 3: Red team verification (verify a sample of results)
        # Parallelized to avoid serial O(results × agents × timeout) blocking.
        verification_results = []
        if results and self.red_team_agents:
            verification_timeout = self.config.consensus.verification_timeout_seconds

            async def _verify_one(
                rt_agent: Any, result: Any,
            ) -> None:
                try:
                    vr = await asyncio.wait_for(
                        rt_agent.verify(result.agent_id, msg, result),
                        timeout=verification_timeout,
                    )
                    verification_results.append(vr)

                    # Step 4: Update trust network (AD-224: Shapley-weighted)
                    shapley_weight = 1.0
                    if consensus.shapley_values:
                        shapley_weight = max(
                            consensus.shapley_values.get(result.agent_id, 0.0),
                            0.1,
                        )
                    _old_trust = self.trust_network.get_score(result.agent_id)  # AD-410
                    self.trust_network.record_outcome(
                        result.agent_id,
                        success=vr.verified,
                        weight=shapley_weight,
                        intent_type=intent,
                        episode_id=msg.id,
                        verifier_id=rt_agent.id,
                    )

                    # AD-410: Bridge Alert on significant trust drop
                    if self.bridge_alerts:
                        _trust_alert = self.bridge_alerts.check_trust_change(
                            result.agent_id, _old_trust,
                            self.trust_network.get_score(result.agent_id),
                        )
                        if _trust_alert and self.ward_room_router:
                            asyncio.create_task(self.ward_room_router.deliver_bridge_alert(_trust_alert))

                    # Step 5: Update hebbian (agent-to-agent)
                    self.hebbian_router.record_verification(
                        verifier_id=rt_agent.id,
                        target_id=result.agent_id,
                        verified=vr.verified,
                    )

                    await self.event_log.log(
                        category="consensus",
                        event="verification_complete",
                        agent_id=result.agent_id,
                        detail=(
                            f"verifier={rt_agent.id[:8]} verified={vr.verified} "
                            f"intent={intent}"
                        ),
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Verification timeout: verifier=%s target=%s",
                        rt_agent.id[:8],
                        result.agent_id[:8],
                    )
                except Exception:
                    logger.warning(
                        "Verification error: verifier=%s target=%s",
                        rt_agent.id[:8],
                        result.agent_id[:8],
                        exc_info=True,
                    )

            verify_tasks = [
                _verify_one(rt_agent, result)
                for result in results if result.success
                for rt_agent in self.red_team_agents
            ]
            if verify_tasks:
                await asyncio.gather(*verify_tasks)

        await self.event_log.log(
            category="mesh",
            event="intent_resolved",
            detail=(
                f"intent={intent} id={msg.id[:8]} results={len(results)} "
                f"consensus={consensus.outcome.value} "
                f"verifications={len(verification_results)}"
            ),
            correlation_id=msg.id,
            data={
                "intent": intent,
                "msg_id": msg.id,
                "result_count": len(results),
                "consensus_outcome": consensus.outcome.value,
                "verification_count": len(verification_results),
                "agent_ids": [r.agent_id for r in results] if results else [],
            },
            parent_event_id=consensus_broadcast_row_id,
        )

        return {
            "intent": msg,
            "results": results,
            "consensus": consensus,
            "verifications": verification_results,
        }

    async def submit_write_with_consensus(
        self,
        path: str,
        content: str,
        timeout: float | None = None,
        policy: QuorumPolicy | None = None,
    ) -> dict[str, Any]:
        """Submit a write_file intent through the full consensus pipeline.

        The write only commits if quorum is reached and red team verification
        doesn't flag discrepancies.
        """
        result = await self.submit_intent_with_consensus(
            intent="write_file",
            params={"path": path, "content": content},
            timeout=timeout,
            policy=policy,
        )

        consensus = result["consensus"]
        committed = False

        if consensus.outcome == ConsensusOutcome.APPROVED:
            # Check if any verification flagged issues
            failed_verifications = [
                v for v in result["verifications"] if not v.verified
            ]
            if not failed_verifications:
                # Commit the write
                commit_result = await FileWriterAgent.commit_write(path, content)
                committed = commit_result.get("success", False)

                await self.event_log.log(
                    category="consensus",
                    event="write_committed" if committed else "write_failed",
                    detail=f"path={path} size={len(content)}",
                )
            else:
                await self.event_log.log(
                    category="consensus",
                    event="write_blocked",
                    detail=(
                        f"path={path} failed_verifications="
                        f"{len(failed_verifications)}"
                    ),
                )

        result["committed"] = committed
        return result

    async def submit_mcp_invoke_with_consensus(
        self,
        server_url: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        policy: QuorumPolicy | None = None,
    ) -> dict[str, Any]:
        """Invoke an MCP tool through the full consensus pipeline (AD-1019c).

        The CONSENSUS-tier "two keys" gate. Mirrors
        :meth:`submit_write_with_consensus` exactly: broadcast an ``mcp_invoke``
        intent (the :class:`~probos.agents.mcp_consensus_proposer.McpConsensusProposer`
        pool answers with a proposal only), evaluate quorum + red-team
        verification, and perform the ``MCPBridge.invoke`` **commit only on
        APPROVED with no failed verifications**.

        ⚠️ era-4 / AD-362 guard: an ``IntentResult(success=True)`` from the
        broadcast is only a *proposal* — the invoke is NEVER performed on the
        vote. A rejected / insufficient vote performs **zero** ``MCPBridge.invoke``
        calls. The returned dict carries ``committed`` (whether the invoke ran)
        and ``invoke_result`` (the tool output, or ``None``).
        """
        result = await self.submit_intent_with_consensus(
            intent="mcp_invoke",
            params={
                "server_url": server_url,
                "tool": tool,
                "arguments": dict(arguments or {}),
            },
            timeout=timeout,
            policy=policy,
        )

        consensus = result["consensus"]
        committed = False
        invoke_result: Any = None

        if consensus.outcome == ConsensusOutcome.APPROVED:
            # Check if any verification flagged issues.
            failed_verifications = [
                v for v in result["verifications"] if not v.verified
            ]
            if not failed_verifications:
                # Commit the invoke — the ONLY place MCPBridge.invoke is called
                # for the consensus tier, gated on APPROVED (the era-4 guard).
                if self.mcp_bridge is not None:
                    try:
                        invoke_result = await self.mcp_bridge.invoke(
                            server_url, tool, dict(arguments or {})
                        )
                        committed = True
                    except Exception:
                        logger.warning(
                            "AD-1019c: MCP invoke commit failed after approval "
                            "(server=%s tool=%s); reporting not-committed",
                            server_url,
                            tool,
                            exc_info=True,
                        )
                        committed = False
                else:
                    logger.warning(
                        "AD-1019c: consensus approved MCP invoke but no bridge "
                        "is wired (server=%s tool=%s); cannot commit",
                        server_url,
                        tool,
                    )

                await self.event_log.log(
                    category="consensus",
                    event="mcp_invoke_committed" if committed else "mcp_invoke_failed",
                    detail=f"server={server_url} tool={tool}",
                )
                # DD-5: episode on every invoke (the consensus tier records here;
                # OPEN/CONFIRM record in the adapter). No trust/Hebbian write for
                # the MCP tool itself.
                await self._store_mcp_invoke_episode(
                    server_url=server_url,
                    tool=tool,
                    tier="consensus",
                    success=committed,
                )
            else:
                await self.event_log.log(
                    category="consensus",
                    event="mcp_invoke_blocked",
                    detail=(
                        f"server={server_url} tool={tool} failed_verifications="
                        f"{len(failed_verifications)}"
                    ),
                )

        result["committed"] = committed
        result["invoke_result"] = invoke_result
        return result

    async def _store_mcp_invoke_episode(
        self,
        *,
        server_url: str,
        tool: str,
        tier: str,
        success: bool,
        agent_id: str = "",
    ) -> None:
        """Persist an episode for one MCP tool invocation (AD-1019c DD-5).

        Episodic completeness: every MCP invoke (all three tiers) is recorded.
        Deliberately records only — there is **no** trust/Hebbian write
        attributable to the MCP tool/server (recorded-not-scored). Tier-2
        honest-degrade: a store failure is logged at debug and swallowed (the
        invoke already happened; the episode is provenance, not correctness).
        """
        if self.episodic_memory is None:
            return
        try:
            import time as _time

            from probos.cognitive.episodic import resolve_sovereign_id_from_slot

            # Episode agent_ids MUST be sovereign ids, never raw slot ids. The
            # invoke context carries the slot id; resolve it (unchanged when no
            # mapping exists).
            sovereign_ids: list[str] = []
            if agent_id:
                sovereign_ids = [
                    resolve_sovereign_id_from_slot(agent_id, self.identity_registry)
                ]

            episode = Episode(
                user_input=f"[mcp_invoke] {tool} on {server_url}",
                timestamp=_time.time(),
                agent_ids=sovereign_ids,
                outcomes=[
                    {
                        "kind": "mcp_invoke",
                        "success": success,
                        "server": server_url,
                        "tool": tool,
                        "tier": tier,
                    }
                ],
                dag_summary={},
                anchors=AnchorFrame(channel="mcp", trigger_type="mcp_invoke"),
            )
            await self.episodic_memory.store(episode)
        except Exception:
            logger.debug(
                "AD-1019c: failed to store MCP invoke episode (server=%s tool=%s)",
                server_url,
                tool,
                exc_info=True,
            )

    def _build_system_self_model(self) -> SystemSelfModel:
        """Build structured self-knowledge snapshot (AD-318)."""
        import time as _time

        # Topology
        pools: list[PoolSnapshot] = []
        dept_lookup: dict[str, str] = {}

        # Build department lookup from pool groups
        try:
            for group in self.pool_groups.all_groups():
                for pool_name in group.pool_names:
                    dept_lookup[pool_name] = group.display_name
        except Exception:
            logger.debug("Failed to build department lookup", exc_info=True)

        for name, pool in self.pools.items():
            pools.append(PoolSnapshot(
                name=name,
                agent_type=pool.agent_type,
                agent_count=pool.current_size,
                department=dept_lookup.get(name, ""),
            ))

        # Departments
        departments: list[str] = []
        try:
            departments = [g.display_name for g in self.pool_groups.all_groups()]
        except Exception:
            logger.debug("System mode detection failed", exc_info=True)

        # System mode
        system_mode = "active"
        try:
            if self.dream_scheduler and self.dream_scheduler.is_dreaming:
                system_mode = "dreaming"
            elif (_time.monotonic() - self._last_request_time) > 30:
                system_mode = "idle"
        except Exception:
            logger.debug("System mode detection failed", exc_info=True)

        # Intent count
        intent_count = 0
        try:
            intent_count = len(self.decomposer._intent_descriptors)
        except Exception:
            logger.debug("Intent count tracking failed", exc_info=True)

        return SystemSelfModel(
            pool_count=len(self.pools),
            agent_count=sum(p.current_size for p in self.pools.values()),
            pools=pools,
            departments=departments,
            intent_count=intent_count,
            system_mode=system_mode,
            uptime_seconds=_time.monotonic() - self._start_time,
            recent_errors=list(self._recent_errors),
            last_capability_gap=self._last_capability_gap,
        )

    def _record_error(self, summary: str) -> None:
        """Record a recent error for SystemSelfModel (AD-318)."""
        self._recent_errors.append(summary)
        if len(self._recent_errors) > 5:
            self._recent_errors = self._recent_errors[-5:]

    def _verify_response(self, response_text: str, self_model: SystemSelfModel) -> str:
        """Verify response text against SystemSelfModel facts (AD-319).

        Returns the response text with a correction footnote appended
        if any confabulated facts are detected. Returns original text
        if no issues found.
        """
        if not response_text or not response_text.strip():
            return response_text

        import re as _re

        violations: list[str] = []
        response_lower = response_text.lower()

        # Known pool sizes for whitelist matching (BF-004)
        known_pool_sizes = {p.agent_count for p in self_model.pools}
        known_pool_names = {p.name.lower() for p in self_model.pools}
        known_depts_lower = {d.lower() for d in self_model.departments}
        # Context words that indicate a subset rather than system-wide claim
        _SUBSET_WORDS = {"pool", "department", "team", "group", "division", "each", "per"}

        def _is_subset_claim(match_start: int) -> bool:
            """Check if the match is scoped to a pool/department (not system-wide)."""
            ctx = response_lower[max(0, match_start - 80):match_start]
            # Check for known pool name in context
            for pn in known_pool_names:
                if pn in ctx:
                    return True
            # Check for known department name in context
            for dept in known_depts_lower:
                if dept in ctx:
                    return True
            # Check for subset indicator words
            for word in _SUBSET_WORDS:
                if word in ctx:
                    return True
            return False

        # Check 1: Pool count claims (BF-004: contextual awareness)
        for m in _re.finditer(r'(\d+)\s+pools?\b', response_lower):
            claimed = int(m.group(1))
            if claimed == self_model.pool_count or claimed == 0:
                continue
            if _is_subset_claim(m.start()):
                continue
            violations.append(
                f"pools: claimed {claimed}, actual {self_model.pool_count}"
            )

        # Check 2: Agent count claims (BF-004: contextual awareness)
        for m in _re.finditer(r'(\d+)\s+agents?\b', response_lower):
            claimed = int(m.group(1))
            if claimed == self_model.agent_count or claimed == 0:
                continue
            # Skip if claimed count matches a known pool's agent count
            if claimed in known_pool_sizes:
                continue
            if _is_subset_claim(m.start()):
                continue
            violations.append(
                f"agents: claimed {claimed}, actual {self_model.agent_count}"
            )

        # Check 3: Fabricated department names
        known_departments = {d.lower() for d in self_model.departments}
        DEPARTMENT_PATTERNS = [
            "navigation", "tactical", "helm", "ops", "logistics",
            "research", "diplomacy", "intelligence", "weapons",
        ]
        for dept in DEPARTMENT_PATTERNS:
            if dept in response_lower and dept not in known_departments:
                dept_context = _re.search(
                    rf'\b{_re.escape(dept)}\b\s+(?:department|team|division|pool)',
                    response_lower,
                )
                if dept_context:
                    violations.append(f"unknown department: '{dept}'")

        # Check 4: Fabricated pool names
        known_pools = {p.name.lower() for p in self_model.pools}
        pool_ref_matches = _re.findall(
            r'the\s+(\w+)\s+pool\b', response_lower
        )
        for pool_name in pool_ref_matches:
            if pool_name not in known_pools and pool_name not in {
                "agent", "worker", "thread", "connection",
            }:
                violations.append(f"unknown pool: '{pool_name}'")

        # Check 5: System mode contradictions
        if self_model.system_mode == "active" and "system is idle" in response_lower:
            violations.append("mode: claimed idle, actual active")
        elif self_model.system_mode == "idle" and "system is active" in response_lower:
            violations.append("mode: claimed active, actual idle")
        elif self_model.system_mode == "dreaming" and (
            "system is active" in response_lower or "system is idle" in response_lower
        ):
            violations.append(f"mode: actual dreaming")

        if not violations:
            return response_text

        logger.warning(
            "Response verification found %d violation(s): %s",
            len(violations),
            "; ".join(violations),
        )

        correction = (
            "\n\n[Note: Some details in this response may be imprecise. "
            f"Verified system state: {self_model.pool_count} pools, "
            f"{self_model.agent_count} agents, "
            f"mode {self_model.system_mode}.]"
        )
        return response_text + correction

    async def process_natural_language(
        self,
        text: str,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        auto_selfmod: bool = True,
        conversation_history: list[tuple[str, str]] | None = None,
        channel_id: str | None = None,           # AD-418: accept from _fire_task
        agent_hint: str | None = None,            # AD-418: routing bias
    ) -> dict[str, Any]:
        """Process a natural language request through the full cognitive pipeline.

        Pipeline: NL input → working memory assembly → LLM decomposition →
        DAG execution via mesh + consensus → aggregated results.

        If on_event is provided, it is called at key pipeline stages:
        decompose_start, decompose_complete, node_start, node_complete, node_failed.
        """
        t_start = time.monotonic()

        # AD-418: Store hint for this request (used by HebbianRouter)
        self._current_agent_hint = agent_hint

        # Reset feedback state for new execution (AD-219)
        self._last_feedback_applied = False
        self._last_execution_text = text

        # Snapshot previous execution for introspection (prevents self-overwrite)
        self._previous_execution = self._last_execution

        # Track activity for dream scheduler
        self._last_request_time = time.monotonic()
        if self.dream_scheduler:
            self.dream_scheduler.record_activity()

        # Update attention focus with current request
        self.attention.update_focus(intent=text, context=text)

        if on_event:
            await on_event(EventType.DECOMPOSE_START, {"text": text})

        # 1. Assemble working memory context
        context = self.working_memory.assemble(
            registry=self.registry,
            trust_network=self.trust_network,
            hebbian_router=self.hebbian_router,
            capability_list=[
                cap.can
                for caps in self.capability_registry._capabilities.values()
                for cap in caps
            ] if hasattr(self.capability_registry, '_capabilities') else [],
        )

        # 2. Decompose NL → TaskDAG (with similar past episodes if available)
        similar_episodes = None
        if self.episodic_memory:
            try:
                similar_episodes = await self.episodic_memory.recall(text, k=3)
            except Exception as e:
                logger.warning("Episode recall failed: %s", e)

        # Sync pre-warm intents from dreaming engine to decomposer
        if self.dream_scheduler and self.dream_scheduler.last_dream_report:
            self.decomposer.pre_warm_intents = (
                self.dream_scheduler.engine.pre_warm_intents
            )

        # AD-232: Check for correction BEFORE decomposition.
        # The decomposer may turn "use http not https" into a new intent,
        # so correction detection must run first.
        if self._correction_detector and self._last_execution is not None:
            try:
                correction = await self._correction_detector.detect(
                    user_text=text,
                    last_execution_text=self._last_execution_text,
                    last_execution_dag=self._last_execution,
                    last_execution_success=self.self_mod_manager.was_last_execution_successful() if self.self_mod_manager else False,
                )
                if correction:
                    record = self.self_mod_manager.find_designed_record(
                        correction.target_agent_type,
                    ) if self.self_mod_manager else None
                    if record and self._agent_patcher:
                        patch_result = await self._agent_patcher.patch(
                            record, correction,
                            self._last_execution_text or text,
                        )
                        if patch_result.success:
                            if self.self_mod_manager:
                                self.self_mod_manager._last_execution = self._last_execution
                                self.self_mod_manager._last_execution_text = self._last_execution_text
                                result = await self.self_mod_manager.apply_correction(
                                    correction, patch_result, record,
                                )
                                return {
                                    "results": {},
                                    "input": text,
                                    "correction": {
                                        "success": result.success,
                                        "agent_type": result.agent_type,
                                        "changes": result.changes_description,
                                        "retried": result.retried,
                                        "retry_result": result.retry_result,
                                    },
                                }
            except Exception:
                logger.debug("Correction detection failed", exc_info=True)

        # Enrich conversation context with last execution's structured intent data
        if conversation_history and self._last_execution:
            last_dag = self._last_execution.get("dag")
            if last_dag and hasattr(last_dag, "nodes") and last_dag.nodes:
                intent_summary = "; ".join(
                    f'{n.intent}: {", ".join(f"{k}={v}" for k, v in n.params.items())}'
                    for n in last_dag.nodes
                )
                if intent_summary:
                    conversation_history = list(conversation_history) + [
                        ("context",
                         f"Previous action: {intent_summary}. "
                         f"When the user references a place, person, or topic without full qualification, "
                         f"assume the same context (location, region, domain) as the previous query.")
                    ]

        self_model = self._build_system_self_model()
        runtime_summary = self_model.to_context()
        dag = await self.decomposer.decompose(
            text, context=context, similar_episodes=similar_episodes or None,
            conversation_history=conversation_history,
            runtime_summary=runtime_summary,
        )

        if on_event:
            await on_event(EventType.DECOMPOSE_COMPLETE, {"dag": dag})

        if not dag.nodes:

            # Self-modification: try when the decomposer returned no intents.
            # Skip only if the response is a genuine conversational reply
            # (greeting, help text).  Capability-gap responses ("I don't
            # have X") should still trigger self-mod.
            from probos.cognitive.decomposer import is_capability_gap
            self_mod_result = None
            is_gap = dag.capability_gap or (dag.response and is_capability_gap(dag.response))
            if is_gap:
                self._last_capability_gap = text[:100]
            if self.self_mod_pipeline and (
                not dag.response or is_gap
            ):
                if auto_selfmod:
                    intent_meta = await self._extract_unhandled_intent(text)
                    if intent_meta:
                        # AD-1049: discovery-before-design (default-OFF; governance —
                        # SURFACE an existing resource, NEVER auto-adopt). Byte-identical
                        # when off: the guard short-circuits before any work runs.
                        _ard_cfg = getattr(getattr(self.config, "federation", None), "ard", None)
                        if _ard_cfg is not None and getattr(_ard_cfg, "discovery_before_design", False):
                            try:
                                from probos.federation.ard.adoption import surface_discovery_candidates
                                await surface_discovery_candidates(self, intent_meta)
                            except Exception:
                                logger.warning("AD-1049: discovery-before-design surface failed for %s; proceeding to design", intent_meta.get("name", "?"), exc_info=True)
                        # Build execution context from prior execution (AD-235)
                        exec_context = ""
                        if self._last_execution and (self.self_mod_manager.was_last_execution_successful() if self.self_mod_manager else False):
                            exec_context = self.self_mod_manager.format_execution_context() if self.self_mod_manager else ""

                        record = await self.self_mod_pipeline.handle_unhandled_intent(
                            intent_name=intent_meta["name"],
                            intent_description=intent_meta["description"],
                            parameters=intent_meta.get("parameters", {}),
                            requires_consensus=intent_meta.get("requires_consensus", False),
                            execution_context=exec_context,
                        )
                        if record and record.status == "active":
                            self_mod_result = {
                                "status": "active",
                                "intent": intent_meta["name"],
                                "agent_type": record.agent_type,
                            }
                            # Retry the original request now that a new agent exists
                            dag = await self.decomposer.decompose(
                                text, context=context, similar_episodes=similar_episodes or None,
                            )
                            if dag.nodes:
                                # Successfully re-decomposed — continue with normal execution
                                pass
                            # AD-154: Schedule QA as background task (non-blocking)
                            if self._system_qa is not None:
                                asyncio.create_task(
                                    self._run_qa_for_designed_agent(record)
                                )
                            # Persist designed agent to knowledge store
                            if self._knowledge_store:
                                try:
                                    await self._knowledge_store.store_agent(record, record.source_code)
                                except Exception:
                                    logger.warning("Failed to persist designed agent — may be lost on restart", exc_info=True)
                            # AD-686b: route through Oracle write-path
                            await self.oracle.write_semantic(
                                "agent",
                                agent_type=record.agent_type,
                                intent_name=record.intent_name,
                                description=record.intent_name,
                                strategy=record.strategy,
                                source_snippet=record.source_code[:200] if record.source_code else "",
                            )
                        elif record:
                            self_mod_result = {
                                "status": record.status,
                                "intent": intent_meta["name"],
                                "error": record.error,
                            }
                        else:
                            self_mod_result = {
                                "status": "failed",
                                "intent": intent_meta["name"],
                                "error": "design returned no record",
                            }
                else:
                    # API mode: return the capability gap as a proposal
                    # without running inline self-mod.
                    # Only propose when there's an actual capability gap,
                    # not for conversational replies (AD-269).
                    if is_gap or not dag.response:
                        intent_meta = await self._extract_unhandled_intent(text)
                        if intent_meta:
                            self_mod_result = {
                                "status": "proposed",
                                "intent": intent_meta["name"],
                                "description": intent_meta.get("description", ""),
                                "parameters": intent_meta.get("parameters", {}),
                            }

            if not dag.nodes:
                logger.warning("No intents parsed from NL input: %s", text[:50])
                result = {
                    "input": text,
                    "dag": dag,
                    "results": {},
                    "complete": True,
                    "node_count": 0,
                    "completed_count": 0,
                    "failed_count": 0,
                    "response": dag.response,
                }
                if self_mod_result:
                    result["self_mod"] = self_mod_result
                # Verify response against self-model (AD-319)
                if result.get("response"):
                    result["response"] = self._verify_response(
                        result["response"], self_model
                    )
                return result

        # Record intents in working memory
        for node in dag.nodes:
            self.working_memory.record_intent(node.intent, node.params)

        # 3. Execute DAG through shared path
        execution_result = await self._execute_dag(
            dag, text, t_start, on_event=on_event, self_model=self_model,
        )

        return execution_result

    async def _execute_dag(
        self,
        dag: TaskDAG,
        text: str,
        t_start: float,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        self_model: SystemSelfModel | None = None,
    ) -> dict[str, Any]:
        """Execute a TaskDAG through the full pipeline.

        Shared by ``process_natural_language()`` and ``execute_proposal()``.
        Pipeline: DAG execution via mesh + consensus → reflect → episodic
        storage → workflow cache.
        """
        # Reset feedback state (AD-219)
        self._last_feedback_applied = False

        # Execute DAG through mesh + consensus
        execution_result = await self.dag_executor.execute(dag, on_event=on_event)

        # Record results in working memory
        for node in dag.nodes:
            node_result = execution_result["results"].get(node.id, {})
            success = node.status == "completed"
            self.working_memory.record_result(
                intent=node.intent,
                success=success,
                result_count=1,
                detail=str(node_result)[:200],
            )

        execution_result["input"] = text

        # Step 5: Reflect if requested — send results back to LLM for synthesis
        if dag.reflect and dag.nodes:
            reflect_timeout = self.config.cognitive.decomposition_timeout_seconds
            try:
                reflection = await asyncio.wait_for(
                    self.decomposer.reflect(text, execution_result),
                    timeout=reflect_timeout,
                )
                execution_result["reflection"] = reflection
                # Verify reflection against self-model (AD-319)
                if reflection and self_model:
                    execution_result["reflection"] = self._verify_response(
                        reflection, self_model
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "Reflect timed out after %.0fs — results preserved",
                    reflect_timeout,
                )
                execution_result["reflection"] = (
                    "(Reflection unavailable — results shown above)"
                )
            except Exception as e:
                logger.warning("Reflect failed: %s: %s", type(e).__name__, e)
                self._record_error(f"Reflect: {type(e).__name__}: {str(e)[:60]}")
                execution_result["reflection"] = (
                    "(Reflection unavailable — results shown above)"
                )

        # Step 6: Store episode in episodic memory (fire-and-forget)
        if self.episodic_memory and dag.nodes:
            try:
                t_end = time.monotonic()
                if self.dream_adapter:
                    self.dream_adapter._last_shapley_values = self._last_shapley_values
                    episode = self.dream_adapter.build_episode(text, execution_result, t_start, t_end)
                else:
                    episode = Episode(
                        timestamp=time.time(),
                        user_input=text,
                        dag_summary={},
                        outcomes=[],
                        agent_ids=[],
                        duration_ms=(t_end - t_start) * 1000,
                        source="direct",
                        anchors=AnchorFrame(channel="dag", trigger_type="dag_execution"),
                    )
                await self.episodic_memory.store(episode)

                # Persist to knowledge store (AD-159)
                if self._knowledge_store:
                    try:
                        await self._knowledge_store.store_episode(episode)
                    except Exception:
                        logger.warning("Failed to persist episode — episodic memory data loss", exc_info=True)
            except Exception as e:
                logger.warning("Episode storage failed: %s: %s", type(e).__name__, e)
                self._record_error(f"Episode: {type(e).__name__}: {str(e)[:60]}")

        # Step 7: Store successful workflows in cache
        if self.workflow_cache and dag.nodes:
            all_success = all(n.status == "completed" for n in dag.nodes)
            if all_success:
                self.workflow_cache.store(text, dag)

        # Store execution result for introspection (AD-219: include DAG for feedback)
        execution_result["dag"] = dag
        self._last_execution = execution_result

        # AD-418: Clear hint after processing
        self._current_agent_hint = None

        return execution_result

    # ------------------------------------------------------------------
    # DAG Proposal Mode (AD-204, AD-205)
    # ------------------------------------------------------------------

    async def propose(
        self,
        text: str,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> TaskDAG:
        """Decompose NL into a TaskDAG without executing it.

        Runs the same pre-decomposition steps as ``process_natural_language()``
        (attention focus, dream scheduler, pre-warm intents, episodic recall)
        but does NOT execute the DAG.  Stores the result as
        ``_pending_proposal`` for later ``execute_proposal()`` or
        ``reject_proposal()``.
        """
        # Track activity for dream scheduler
        self._last_request_time = time.monotonic()
        if self.dream_scheduler:
            self.dream_scheduler.record_activity()

        # Update attention focus with current request
        self.attention.update_focus(intent=text, context=text)

        # Assemble working memory context
        context = self.working_memory.assemble(
            registry=self.registry,
            trust_network=self.trust_network,
            hebbian_router=self.hebbian_router,
            capability_list=[
                cap.can
                for caps in self.capability_registry._capabilities.values()
                for cap in caps
            ] if hasattr(self.capability_registry, '_capabilities') else [],
        )

        # Recall similar past episodes
        similar_episodes = None
        if self.episodic_memory:
            try:
                similar_episodes = await self.episodic_memory.recall(text, k=3)
            except Exception as e:
                logger.warning("Episode recall failed: %s", e)

        # Sync pre-warm intents from dreaming engine to decomposer
        if self.dream_scheduler and self.dream_scheduler.last_dream_report:
            self.decomposer.pre_warm_intents = (
                self.dream_scheduler.engine.pre_warm_intents
            )

        dag = await self.decomposer.decompose(
            text, context=context, similar_episodes=similar_episodes or None,
        )

        # Store as pending proposal (replaces any existing proposal)
        if dag.nodes and not dag.response:
            self._pending_proposal = dag
            self._pending_proposal_text = text
        elif dag.response and not dag.nodes:
            # Conversational or capability-gap — no proposal to store
            self._pending_proposal = None
            self._pending_proposal_text = ""
        else:
            # Has both nodes and response, or capability gap with nodes
            self._pending_proposal = dag
            self._pending_proposal_text = text

        # Log proposal_created event (AD-209)
        if self._pending_proposal is not None and dag.nodes:
            await self.event_log.log(
                category="cognitive",
                event="proposal_created",
                detail=f"text={text[:80]}, node_count={len(dag.nodes)}",
            )

        return dag

    async def execute_proposal(
        self,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any] | None:
        """Execute the pending proposal through the normal DAG pipeline.

        Returns the executed DAG result, or None if no pending proposal.
        Clears ``_pending_proposal`` after execution.
        """
        if self._pending_proposal is None:
            return None

        dag = self._pending_proposal
        text = self._pending_proposal_text
        t_start = time.monotonic()

        # Track execution text for feedback (AD-219)
        self._last_execution_text = text

        # Clear pending proposal before execution
        self._pending_proposal = None
        self._pending_proposal_text = ""

        if not dag.nodes:
            return None

        # Log proposal_approved event (AD-209)
        await self.event_log.log(
            category="cognitive",
            event="proposal_approved",
            detail=f"node_count={len(dag.nodes)}",
        )

        # Snapshot previous execution for introspection
        self._previous_execution = self._last_execution

        # Record intents in working memory
        for node in dag.nodes:
            self.working_memory.record_intent(node.intent, node.params)

        # Execute through the shared pipeline
        execution_result = await self._execute_dag(
            dag, text, t_start, on_event=on_event,
        )

        return execution_result

    async def reject_proposal(self) -> bool:
        """Discard the pending proposal.

        Returns True if there was a proposal to reject, False otherwise.
        Also records rejection feedback if FeedbackEngine is available (AD-219).
        """
        if self._pending_proposal is None:
            return False
        node_count = len(self._pending_proposal.nodes)
        proposal_text = self._pending_proposal_text
        proposal_dag = self._pending_proposal

        self._pending_proposal = None
        self._pending_proposal_text = ""
        # Log proposal_rejected event (AD-209)
        await self.event_log.log(
            category="cognitive",
            event="proposal_rejected",
            detail=f"node_count={node_count}",
        )

        # Record rejection feedback (AD-219)
        if self.feedback_engine and proposal_dag.nodes:
            try:
                await self.feedback_engine.apply_rejection_feedback(
                    proposal_text, proposal_dag,
                )
            except Exception:
                logger.debug("Rejection feedback failed", exc_info=True)  # Never block on feedback failure

        return True

    async def record_feedback(self, positive: bool) -> Any:
        """Record user feedback on the most recent execution.

        Returns FeedbackResult if successful, None if no execution or
        already rated.
        """
        if self._last_execution is None:
            return None
        if self._last_feedback_applied:
            return None
        if not self.feedback_engine:
            return None

        # Extract the DAG from the last execution
        dag = self._last_execution.get("dag")
        if dag is None:
            return None

        original_text = self._last_execution_text or ""

        result = await self.feedback_engine.apply_execution_feedback(
            dag, positive, original_text,
        )
        self._last_feedback_applied = True
        return result

    async def remove_proposal_node(self, node_index: int) -> TaskNode | None:
        """Remove a node from the pending proposal by 0-based index.

        Returns the removed node, or None if the index is out of range
        or there is no pending proposal.  After removal, cleans up
        dependency references in remaining nodes (removes the deleted
        node's ID from their ``depends_on`` lists).
        """
        if self._pending_proposal is None:
            return None
        nodes = self._pending_proposal.nodes
        if node_index < 0 or node_index >= len(nodes):
            return None

        removed = nodes.pop(node_index)

        # Clean up dependency references
        for node in nodes:
            if removed.id in node.depends_on:
                node.depends_on.remove(removed.id)

        # Log proposal_node_removed event (AD-209)
        await self.event_log.log(
            category="cognitive",
            event="proposal_node_removed",
            detail=f"removed_intent={removed.intent}, remaining_count={len(nodes)}",
        )

        return removed

    def status(self) -> dict[str, Any]:
        """Return a snapshot of the full system state."""
        result = {
            "system": self.config.system.model_dump(),
            "started": self._started,
            "crew_agents": self.registry.crew_count(),
            "total_agents": self.registry.count,
            "pools": {name: pool.info() for name, pool in self.pools.items()},
            "pool_groups": self.pool_groups.status(self.pools),
            "registry_summary": self.registry.summary(),
            "mesh": {
                "intent_subscribers": self.intent_bus.subscriber_count,
                "capability_agents": self.capability_registry.agent_count,
                "gossip_view_size": self.gossip.view_size,
                "hebbian_weights": self.hebbian_router.weight_count,
                "active_signals": self.signal_manager.active_count,
            },
            "consensus": {
                "trust_network_agents": self.trust_network.agent_count,
                "red_team_agents": len(self.red_team_agents),
                "quorum_policy": {
                    "min_votes": self.quorum_engine.policy.min_votes,
                    "approval_threshold": self.quorum_engine.policy.approval_threshold,
                    "confidence_weighted": self.quorum_engine.policy.use_confidence_weights,
                },
            },
            "cognitive": {
                "llm_client": type(self.llm_client).__name__,
                "working_memory_budget": self.working_memory.token_budget,
                "decomposition_timeout": self.decomposer.timeout,
                "dag_execution_timeout": self.dag_executor.timeout,
                "attention_budget": self.attention.max_concurrent,
                "attention_queue": self.attention.queue_size,
            },
        }
        if self.episodic_memory:
            result["episodic_memory"] = "enabled"
        result["escalation"] = {
            "enabled": self.escalation_manager is not None,
        }
        result["scaling"] = (
            self.pool_scaler.scaling_status()
            if self.pool_scaler
            else {"enabled": False}
        )
        result["federation"] = (
            self.federation_bridge.federation_status()
            if self.federation_bridge
            else {"enabled": False}
        )
        result["workflow_cache"] = {
            "size": self.workflow_cache.size,
            "entries": len(self.workflow_cache.entries),
        }
        result["self_mod"] = (
            self.self_mod_pipeline.designed_agent_status()
            if self.self_mod_pipeline
            else {"enabled": False}
        )
        result["qa"] = {
            "enabled": self.config.qa.enabled and self.config.self_mod.enabled,
            "report_count": len(self._qa_reports),
        }
        result["knowledge"] = {
            "enabled": self._knowledge_store is not None,
            "repo_path": str(self._knowledge_store.repo_path) if self._knowledge_store else None,
        }
        result["records"] = {
            "enabled": self._records_store is not None,
            "repo_path": str(self._records_store.repo_path) if self._records_store else None,
        }
        result["emergent"] = (
            self._emergent_detector.summary()
            if self._emergent_detector
            else {"enabled": False}
        )
        result["semantic_knowledge"] = (
            # AD-686c: route through Oracle's public surface; fall back to
            # the legacy direct read for stub runtimes that bypass init.
            self.oracle.semantic_stats()
            if getattr(self, "oracle", None) is not None
            else (
                self._semantic_layer.stats()
                if self._semantic_layer
                else {"enabled": False}
            )
        )
        if self.dream_scheduler:
            dream_status: dict[str, Any] = {
                "state": "dreaming" if self.dream_scheduler.is_dreaming else "idle",
                "enabled": True,
            }
            report = self.dream_scheduler.last_dream_report
            if report:
                dream_status["last_report"] = {
                    "episodes_replayed": report.episodes_replayed,
                    "weights_strengthened": report.weights_strengthened,
                    "weights_pruned": report.weights_pruned,
                    "trust_adjustments": report.trust_adjustments,
                    "pre_warm_intents": report.pre_warm_intents,
                    "duration_ms": round(report.duration_ms, 1),
                }
            result["dreaming"] = dream_status
        else:
            result["dreaming"] = {"state": "disabled", "enabled": False}
        result["task_scheduler"] = (
            self.task_scheduler.get_stats()
            if self.task_scheduler
            else {"enabled": False}
        )
        if self.ward_room:
            result["ward_room_available"] = True
            result["ward_room_channels"] = self.ward_room.get_channel_snapshot()
        if self.assignment_service:
            result["assignments"] = self.assignment_service.get_assignment_snapshot()
        if self.bridge_alerts:
            result["bridge_alerts"] = {
                "recent": [
                    {"id": a.id, "severity": a.severity.value, "title": a.title, "timestamp": a.timestamp}
                    for a in self.bridge_alerts.get_recent_alerts(10)
                ],
            }
        return result

    # ------------------------------------------------------------------
    # Federation
    # ------------------------------------------------------------------

    def _build_self_model(self) -> NodeSelfModel:
        """Build this node's self-model (Psi) for gossip broadcast."""
        capabilities = []
        for template_cls in self.spawner._templates.values():
            for desc in getattr(template_cls, 'intent_descriptors', []):
                capabilities.append(desc.name)
        pool_sizes = {name: pool.current_size for name, pool in self.pools.items()}
        agent_count = sum(pool.current_size for pool in self.pools.values())
        health = self._compute_health()
        uptime = time.monotonic() - self._start_time
        return NodeSelfModel(
            node_id=self.config.federation.node_id,
            capabilities=sorted(set(capabilities)),
            pool_sizes=pool_sizes,
            agent_count=agent_count,
            health=health,
            uptime_seconds=uptime,
            timestamp=time.monotonic(),
        )

    def _compute_health(self) -> float:
        """Average confidence of all ACTIVE agents."""
        from probos.types import AgentState
        agents = self.registry.all()
        active = [a for a in agents if a.state == AgentState.ACTIVE]
        if not active:
            return 0.0
        return sum(a.confidence for a in active) / len(active)

    async def _validate_remote_result(self, result: IntentResult) -> bool:
        """Validate a remote result through local red team verification.

        Only applied to results from consensus-requiring intents.
        Read results are trusted without validation.
        """
        consensus_intents = {"write_file", "run_command"}
        if result.intent_id not in consensus_intents:
            return True
        return True  # Placeholder — full validation in a future phase

    # ------------------------------------------------------------------
    # Internal wiring
    # ------------------------------------------------------------------

    def _collect_intent_descriptors(self) -> list[IntentDescriptor]:
        """Collect unique intent descriptors from all registered agent templates
        and cognitive skill catalog (AD-596b)."""
        seen: set[str] = set()
        descriptors: list[IntentDescriptor] = []
        for type_name, agent_class in self.spawner._templates.items():
            for desc in getattr(agent_class, "intent_descriptors", []):
                if desc.name not in seen:
                    seen.add(desc.name)
                    descriptors.append(desc)

        # AD-596b: collect from cognitive skill catalog
        if self.cognitive_skill_catalog:
            for entry in self.cognitive_skill_catalog.list_entries():
                for intent_name in entry.intents:
                    if intent_name not in seen:
                        seen.add(intent_name)
                        descriptors.append(IntentDescriptor(
                            name=intent_name,
                            description=f"[Cognitive Skill: {entry.name}] {entry.description}",
                            tier="domain",
                        ))

        return descriptors

    def _build_pool_intent_map(self) -> dict[str, list[str]]:
        """Build mapping of pool_name -> list of intent names for demand tracking.

        Uses intent_descriptors from registered agent templates.
        """
        pool_intents: dict[str, list[str]] = {}
        for type_name, template_cls in self.spawner._templates.items():
            descriptors = getattr(template_cls, 'intent_descriptors', [])
            if not descriptors:
                continue
            for pool_name, pool in self.pools.items():
                if pool.agent_type == type_name:
                    pool_intents[pool_name] = [d.name for d in descriptors]
                    break
        return pool_intents

    def _find_consensus_pools(self) -> set[str]:
        """Return pool names whose agents declare requires_consensus=True."""
        result: set[str] = set()
        for type_name, template_cls in self.spawner._templates.items():
            descriptors = getattr(template_cls, 'intent_descriptors', [])
            if any(d.requires_consensus for d in descriptors):
                for pool_name, pool in self.pools.items():
                    if pool.agent_type == type_name:
                        result.add(pool_name)
                        break
        return result

    # ------------------------------------------------------------------
    # Self-modification helpers
    # ------------------------------------------------------------------

    async def _register_designed_agent(self, agent_class: type) -> None:
        """Register a self-designed agent class. Wraps register_agent_type()."""
        if getattr(self, 'self_mod_manager', None):
            await self.self_mod_manager.register_designed_agent(agent_class)

    async def _unregister_designed_agent(self, agent_type: str) -> None:
        """Rollback registration of a self-designed agent type (AD-368)."""
        if getattr(self, 'self_mod_manager', None):
            await self.self_mod_manager.unregister_designed_agent(agent_type)

    async def _create_designed_pool(self, agent_type: str, pool_name: str, size: int = 1) -> None:
        """Create a pool for a self-designed agent type."""
        if getattr(self, 'self_mod_manager', None):
            await self.self_mod_manager.create_designed_pool(agent_type, pool_name, size)

    async def _set_probationary_trust(self, pool_name: str) -> None:
        """Set probationary trust for all agents in a designed pool."""
        if getattr(self, 'self_mod_manager', None):
            await self.self_mod_manager.set_probationary_trust(pool_name)

    # ------------------------------------------------------------------
    # Agent manifest (Phase 14c)
    # ------------------------------------------------------------------

    def _build_manifest(self) -> list[dict]:
        """Build the agent roster from current pools + red team."""
        manifest: list[dict] = []
        for pool_name, pool in self.pools.items():
            # Get tier from the template class
            template = self.spawner._templates.get(pool.agent_type)
            tier = getattr(template, "tier", "domain") if template else "domain"
            for idx, aid in enumerate(pool._agent_ids):
                entry: dict[str, Any] = {
                    "agent_id": aid,
                    "agent_type": pool.agent_type,
                    "pool_name": pool_name,
                    "instance_index": idx,
                    "tier": tier,
                }
                manifest.append(entry)
        for idx, agent in enumerate(self.red_team_agents):
            manifest.append({
                "agent_id": agent.id,
                "agent_type": agent.agent_type,
                "pool_name": "red_team",
                "instance_index": idx,
                "tier": agent.tier,
            })
        return manifest

    async def _persist_manifest(self) -> None:
        """Save the agent manifest to the knowledge store."""
        if self._knowledge_store:
            try:
                await self._knowledge_store.store_manifest(self._build_manifest())
            except Exception as e:
                logger.warning("Manifest persistence failed: %s", e)

    async def prune_agent(self, agent_id: str) -> bool:
        """Permanently remove an agent.

        Removes from pool, trust network, Hebbian router, and manifest.
        The agent's ID is never recycled.
        Returns True if the agent was found and removed.
        """
        # Find the agent's pool
        target_pool: ResourcePool | None = None
        for pool in self.pools.values():
            if agent_id in pool._agent_ids:
                target_pool = pool
                break

        if target_pool is None:
            return False

        # Remove from pool
        target_pool._agent_ids.remove(agent_id)
        agent = self.registry.get(agent_id)
        if agent:
            await agent.stop()
            await self.registry.unregister(agent_id)

        # Remove trust records
        if agent_id in self.trust_network._records:
            del self.trust_network._records[agent_id]

        # Remove Hebbian weights referencing this agent
        to_remove = [
            k for k in self.hebbian_router._weights
            if agent_id in (k[0], k[1])
        ]
        for k in to_remove:
            del self.hebbian_router._weights[k]
        to_remove_compat = [
            k for k in self.hebbian_router._compat_weights
            if agent_id in (k[0], k[1])
        ]
        for k in to_remove_compat:
            del self.hebbian_router._compat_weights[k]

        # Persist updated manifest
        await self._persist_manifest()

        logger.info("Pruned agent %s from pool %s", agent_id, target_pool.name)
        return True

    def _get_llm_equipped_types(self) -> set[str]:
        """Return agent types that have LLM client access.

        The runtime knows because it injected llm_client into these agents.
        Includes SkillBasedAgent, IntrospectionAgent, and any CognitiveAgent subclasses.
        """
        from probos.cognitive.cognitive_agent import CognitiveAgent

        types: set[str] = set()
        if self.pools.get("skills"):
            types.add("skill_agent")
        if self.pools.get("introspect"):
            types.add("introspection")
        # Include all CognitiveAgent subclasses across all pools
        for pool in self.pools.values():
            for agent_id in pool.healthy_agents:
                agent = self.registry.get(agent_id)
                if agent and isinstance(agent, CognitiveAgent):
                    types.add(agent.agent_type)
        return types

    def _get_agent_classes(self) -> dict[str, type]:
        """Return a mapping of agent_type -> agent class for registered agents.

        Used by StrategyRecommender to read instructions from cognitive agents.
        """
        classes: dict[str, type] = {}
        for pool in self.pools.values():
            for agent_id in pool.healthy_agents:
                agent = self.registry.get(agent_id)
                if agent and agent.agent_type not in classes:
                    classes[agent.agent_type] = type(agent)
        return classes

    def _register_designed_tool(self, skill: Any) -> None:
        """AD-886: register a designed deterministic Skill into the ToolRegistry.

        The self-mod pipeline calls this (via ``register_tool_fn``) right after a
        Skill is attached to its SkillBasedAgent. The legacy ``Skill`` is a
        deterministic async handler — a *tool* by AD-441c's identity split — so it
        belongs in the ToolRegistry alongside built-in tools, gaining
        persistence-of-record, permission resolution, and LOTO governance.

        ``self.tool_registry`` is wired in Phase 7 (``init_communication``), after
        the Phase 4 self-mod pipeline is constructed; reading it here (at skill-design
        time, post-startup) rather than at construction time means the registry is
        always available when a skill is actually forged. Honest-degrade (Tier-2):
        if the registry is absent the skill stays attached and dispatchable via
        SkillBasedAgent — ToolRegistry visibility is a bonus, not a precondition.

        Uses ``InfraServiceAdapter`` (not ``DeterministicFunctionAdapter``): the
        skill's handler is async and is already bus-dispatched by SkillBasedAgent,
        so re-broadcasting the same intent through the bus is the correct invocation
        path. Marked ``provider="designed"`` to distinguish from built-in tools.
        """
        registry = self.tool_registry
        if registry is None:
            logger.debug(
                "AD-886: tool_registry unavailable; designed skill %s not registered "
                "as a tool (still dispatchable via SkillBasedAgent)",
                getattr(skill, "name", "?"),
            )
            return
        from probos.tools.adapters import InfraServiceAdapter

        descriptor = getattr(skill, "descriptor", None)
        description = descriptor.description if descriptor is not None else skill.name
        adapter = InfraServiceAdapter(
            tool_id=skill.name,
            name=skill.name,
            description=description,
            intent_name=skill.name,
            intent_bus=self.intent_bus,
        )
        registry.register(adapter, provider="designed")
        logger.info(
            "AD-886: registered designed skill %s into ToolRegistry as a tool "
            "(provider=designed)",
            skill.name,
        )

    async def _add_skill_to_agents(self, skill: Any, target_agent_type: str = "skill_agent") -> None:
        """Add a skill to agents of the target type across all pools.

        If no agents of the target type are found, falls back to
        SkillBasedAgent instances in the skills pool (backward compat).
        After adding, refresh decomposer descriptors.
        """
        from probos.cognitive.cognitive_agent import CognitiveAgent

        attached = False

        # Search all pools for agents matching the target type
        if target_agent_type != "skill_agent":
            for pool in self.pools.values():
                for agent_id in pool.healthy_agents:
                    agent = self.registry.get(agent_id)
                    if agent and agent.agent_type == target_agent_type:
                        if hasattr(agent, "add_skill"):
                            agent.add_skill(skill)
                            attached = True

        # Fall back to SkillBasedAgent in skills pool if no target found
        if not attached:
            pool = self.pools.get("skills")
            if pool:
                for agent_id in pool.healthy_agents:
                    agent = self.registry.get(agent_id)
                    if agent and isinstance(agent, SkillBasedAgent):
                        agent.add_skill(skill)
                        attached = True

        # Refresh descriptors
        self.decomposer.refresh_descriptors(self._collect_intent_descriptors())

        # Persist skill to knowledge store
        if self._knowledge_store and hasattr(skill, "source_code") and hasattr(skill, "descriptor"):
            try:
                descriptor_dict = {
                    "name": skill.descriptor.name,
                    "params": skill.descriptor.params,
                    "description": skill.descriptor.description,
                    "requires_reflect": getattr(skill.descriptor, "requires_reflect", True),
                    "created_at": getattr(skill, "created_at", 0.0),
                }
                await self._knowledge_store.store_skill(skill.name, skill.source_code, descriptor_dict)
            except Exception:
                logger.warning("Failed to persist skill — may be lost on restart", exc_info=True)
        # AD-686b: route through Oracle write-path
        await self.oracle.write_semantic(
            "skill",
            intent_name=skill.name,
            description=skill.descriptor.description if skill.descriptor else skill.name,
            target_agent=getattr(skill, "target_agent", ""),
        )

    # ------------------------------------------------------------------
    # SystemQA helper (AD-154)
    # ------------------------------------------------------------------

    async def _run_qa_for_designed_agent(self, record: Any) -> Any:
        """Run smoke tests for a newly designed agent. Non-blocking.

        AD-154: All errors contained — this runs as a fire-and-forget task.
        """
        try:
            if not self.config.qa.enabled or self._system_qa is None:
                return None

            pool = self.pools.get(record.pool_name)
            if not pool or not pool.healthy_agents:
                return None

            report = await self._system_qa.run_smoke_tests(
                record, pool, self.config.qa,
            )

            # AD-157: Store report in-memory for /qa command
            self._qa_reports[record.agent_type] = report

            # Persist QA report to knowledge store
            if self._knowledge_store:
                try:
                    report_dict = {
                        "agent_type": record.agent_type,
                        "verdict": report.verdict,
                        "passed": report.passed,
                        "total_tests": report.total_tests,
                        "duration_ms": report.duration_ms,
                        "test_details": report.test_details,
                    }
                    await self._knowledge_store.store_qa_report(record.agent_type, report_dict)
                except Exception:
                    logger.debug("Failed to persist QA report", exc_info=True)
            # AD-686b: route through Oracle write-path
            await self.oracle.write_semantic(
                "qa_report",
                agent_type=record.agent_type,
                verdict=report.verdict,
                pass_rate=report.passed / report.total_tests if report.total_tests > 0 else 0.0,
            )

            # Trust updates (AD-155)
            for agent_id_or_agent in pool.healthy_agents:
                aid = agent_id_or_agent if isinstance(agent_id_or_agent, str) else agent_id_or_agent.id
                for test in report.test_details:
                    weight = (
                        self.config.qa.trust_reward_weight
                        if test["passed"]
                        else self.config.qa.trust_penalty_weight
                    )
                    _old_trust_qa = self.trust_network.get_score(aid)  # AD-410
                    self.trust_network.record_outcome(
                        aid, success=test["passed"], weight=weight,
                    )

                    # AD-410: Bridge Alert on significant trust drop
                    if self.bridge_alerts:
                        _trust_alert_qa = self.bridge_alerts.check_trust_change(
                            aid, _old_trust_qa,
                            self.trust_network.get_score(aid),
                        )
                        if _trust_alert_qa and self.ward_room_router:
                            asyncio.create_task(self.ward_room_router.deliver_bridge_alert(_trust_alert_qa))

            # Episodic memory
            if self.episodic_memory:
                import uuid as _uuid
                from probos.cognitive.episodic import EpisodicMemory, resolve_sovereign_id
                episode = Episode(
                    id=_uuid.uuid4().hex,
                    timestamp=time.time(),
                    user_input=f"[SystemQA] Smoke test: {record.intent_name}",
                    dag_summary={
                        "node_count": report.total_tests,
                        "intent_types": [record.intent_name],
                        "has_dependencies": False,
                    },
                    outcomes=[
                        {
                            "intent": "smoke_test",
                            "success": t["passed"],
                            "status": "completed" if t["passed"] else "failed",
                        }
                        for t in report.test_details
                    ],
                    reflection=f"QA {report.verdict}: {report.passed}/{report.total_tests} passed for {record.agent_type}",
                    agent_ids=[
                        (a if isinstance(a, str) else resolve_sovereign_id(a))
                        for a in pool.healthy_agents
                    ],
                    duration_ms=report.duration_ms,
                    embedding=[],
                    source="direct",
                    anchors=AnchorFrame(channel="smoke_test", trigger_type="smoke_test"),
                )
                if EpisodicMemory.should_store(episode):
                    await self.episodic_memory.store(episode)

            # Flagging
            if report.verdict == "failed" and self.config.qa.flag_on_fail:
                await self.event_log.log(
                    category="qa",
                    event="agent_flagged",
                    detail=f"{record.agent_type} failed smoke tests ({report.passed}/{report.total_tests})",
                )

            # Auto-remove on total failure
            if report.passed == 0 and self.config.qa.auto_remove_on_total_fail:
                for agent_or_id in list(pool.healthy_agents):
                    aid = agent_or_id if isinstance(agent_or_id, str) else agent_or_id.id
                    await pool.remove_agent()
                await self.event_log.log(
                    category="qa",
                    event="agent_removed",
                    detail=f"{record.agent_type}: all agents removed after 0/{report.total_tests} passed",
                )

            return report

        except Exception as e:
            # AD-154: QA failure must never crash the runtime
            try:
                await self.event_log.log(
                    category="qa",
                    event="qa_error",
                    detail=f"QA failed for {record.agent_type}: {repr(e)}",
                )
            except Exception:
                logger.debug("Failed to log QA error event", exc_info=True)
            return None

    async def _extract_unhandled_intent(self, text: str) -> dict[str, Any] | None:
        """Use LLM to extract intent metadata from an unhandled request."""
        import json as _json

        existing = [d.name for d in self._collect_intent_descriptors()]

        prompt = (
            '/no_think\n'
            'The user asked ProbOS to do something, but no existing agent can handle it.\n'
            f'User request: "{text}"\n\n'
            'Respond IMMEDIATELY with ONLY a JSON object — no explanation, no reasoning:\n'
            '{\n'
            '    "name": "intent_name_snake_case",\n'
            '    "description": "What this intent does in one sentence",\n'
            '    "parameters": {"param_name": "description"},\n'
            '    "actual_values": {"param_name": "value_from_user_request"},\n'
            '    "requires_consensus": false\n'
            '}\n\n'
            'Rules:\n'
            '- name must be snake_case, 2-4 words\n'
            f'- Do NOT create intents that duplicate existing capabilities: {existing}\n'
            '- requires_consensus should be true only for destructive or external operations\n'
            '- actual_values must contain the real values extracted from the user request\n'
            '- PREFER GENERAL-PURPOSE intents over narrow ones. For example:\n'
            '  GOOD: "translate_text" with params {"text": "...", "target_language": "..."}\n'
            '  BAD:  "translate_text_to_french" with params {"text": "..."}\n'
            '  The agent should handle the whole category, not just one specific case.\n'
        )

        from probos.types import LLMRequest
        import re as _re

        # Try fast tier first, fall back to standard if qwen's reasoning
        # mode consumes all tokens and produces no usable JSON.
        for tier in ("fast", "standard"):
            request = LLMRequest(prompt=prompt, tier=tier, max_tokens=2048)
            response = await self.llm_client.complete(request)

            if not response.content or response.error:
                logger.warning("_extract_unhandled_intent: empty/error response (error=%s, content_len=%s, tier=%s)",
                               response.error, len(response.content) if response.content else 0, tier)
                continue

            try:
                # Strip <think>...</think> blocks (common with qwen / reasoning models)
                raw = _re.sub(r'<think>.*?</think>', '', response.content, flags=_re.DOTALL).strip()
                logger.debug("_extract_unhandled_intent raw after strip: %s", raw[:300])
                # Strip markdown code fences if present (common with local models)
                fence = _re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, _re.DOTALL)
                if fence:
                    raw = fence.group(1).strip()
                elif not raw.startswith("{"):
                    brace = raw.find("{")
                    if brace >= 0:
                        raw = raw[brace:]

                data = _json.loads(raw)
                if "name" in data and "description" in data:
                    return data
                logger.warning("_extract_unhandled_intent: JSON missing name/description keys: %s", list(data.keys()))
            except (_json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning("_extract_unhandled_intent: parse failed (%s, tier=%s). raw=%s",
                               exc, tier, response.content[:200])
        return None
