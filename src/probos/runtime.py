"""ProbOS runtime — top-level orchestrator for substrate + mesh + consensus layers."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from probos.agents.directory_list import DirectoryListAgent
from probos.agents.file_reader import FileReaderAgent
from probos.agents.file_search import FileSearchAgent
from probos.agents.file_writer import FileWriterAgent
from probos.agents.heartbeat_monitor import SystemHeartbeatAgent
from probos.agents.http_fetch import HttpFetchAgent
from probos.agents.introspect import IntrospectionAgent
from probos.agents.red_team import RedTeamAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.agents.bundled import (
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
from probos.cognitive.builder import BuilderAgent
from probos.cognitive.architect import ArchitectAgent
from probos.cognitive.self_model import PoolSnapshot, SystemSelfModel
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
from probos.config import KnowledgeConfig, SystemConfig, load_config
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
    ConsensusOutcome,
    Episode,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
    NodeSelfModel,
    QuorumPolicy,
    TaskDAG,
    TaskNode,
)

logger = logging.getLogger(__name__)

# Default paths (relative to project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG = _PROJECT_ROOT / "config" / "system.yaml"
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"


class ProbOSRuntime:
    """Top-level orchestrator. Wires substrate + mesh + consensus components, manages lifecycle."""

    def __init__(
        self,
        config: SystemConfig | None = None,
        data_dir: str | Path | None = None,
        llm_client: BaseLLMClient | None = None,
        episodic_memory: Any | None = None,
    ) -> None:
        self.config = config or load_config(_DEFAULT_CONFIG)
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

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
        )
        self.gossip = GossipProtocol(
            interval_seconds=self.config.mesh.gossip_interval_ms / 1000.0,
        )

        # --- Event log ---
        self.event_log = EventLog(db_path=self._data_dir / "events.db")

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
        )
        # Red team agents are stored separately — not on the intent bus
        self._red_team_agents: list[RedTeamAgent] = []

        # --- Cognitive ---
        cog_cfg = self.config.cognitive
        self.llm_client: BaseLLMClient = llm_client or MockLLMClient()
        self.working_memory = WorkingMemoryManager(
            token_budget=cog_cfg.working_memory_token_budget,
        )
        self.workflow_cache = WorkflowCache()
        self.decomposer = IntentDecomposer(
            llm_client=self.llm_client,
            working_memory=self.working_memory,
            timeout=cog_cfg.decomposition_timeout_seconds,
            workflow_cache=self.workflow_cache,
        )
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
        )

        # --- Episodic memory ---
        self.episodic_memory = episodic_memory  # None = disabled

        # --- Dreaming ---
        self.dream_scheduler: DreamScheduler | None = None
        self._last_request_time: float = time.monotonic()

        # --- Task Scheduler ---
        self.task_scheduler: TaskScheduler | None = None

        # --- Pool scaling ---
        self.pool_scaler: PoolScaler | None = None

        # --- Federation ---
        self.federation_bridge: Any = None  # FederationBridge | None
        self._federation_transport: Any = None
        self._start_time: float = time.monotonic()
        self._recent_errors: list[str] = []    # last 5 error summaries (AD-318)
        self._last_capability_gap: str = ""    # last unhandled intent (AD-318)

        # --- Self-modification ---
        self.self_mod_pipeline: Any = None  # SelfModificationPipeline | None
        self.behavioral_monitor: Any = None  # BehavioralMonitor | None

        # --- SystemQA (AD-153) ---
        self._system_qa: Any = None  # SystemQAAgent | None
        self._qa_reports: dict[str, Any] = {}  # AD-157: in-memory report store

        # --- Knowledge store (AD-159) ---
        self._knowledge_store: Any = None  # KnowledgeStore | None

        # --- Execution history (for introspection) ---
        self._last_execution: dict[str, Any] | None = None
        self._previous_execution: dict[str, Any] | None = None

        # --- DAG Proposal mode (AD-204) ---
        self._pending_proposal: TaskDAG | None = None
        self._pending_proposal_text: str = ""

        # --- Feedback-to-learning (AD-219) ---
        self._last_feedback_applied: bool = False
        self._last_execution_text: str | None = None
        self.feedback_engine: Any = None
        # --- Shapley attribution (AD-224) ---
        self._last_shapley_values: dict[str, float] | None = None
        # --- Correction feedback (AD-229-232) ---
        self._correction_detector: Any = None
        self._agent_patcher: Any = None

        # --- Emergent detection (AD-236) ---
        self._emergent_detector: EmergentDetector | None = None

        # --- Semantic knowledge layer (AD-243) ---
        self._semantic_layer: SemanticKnowledgeLayer | None = None

        # --- HXI event listeners (AD-254) ---
        self._event_listeners: list[Callable] = []

        self._started = False
        self._fresh_boot = False

        # Register built-in agent templates
        self.spawner.register_template("system_heartbeat", SystemHeartbeatAgent)
        self.spawner.register_template("file_reader", FileReaderAgent)
        self.spawner.register_template("file_writer", FileWriterAgent)
        self.spawner.register_template("directory_list", DirectoryListAgent)
        self.spawner.register_template("file_search", FileSearchAgent)
        self.spawner.register_template("shell_command", ShellCommandAgent)
        self.spawner.register_template("http_fetch", HttpFetchAgent)
        self.spawner.register_template("red_team", RedTeamAgent)
        self.spawner.register_template("introspect", IntrospectionAgent)
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
        # Science team (AD-306)
        self.spawner.register_template("architect", ArchitectAgent)

        # --- CodebaseIndex (AD-290) ---
        self.codebase_index: Any = None

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

    def add_event_listener(self, fn: Callable) -> None:
        """Register a listener for HXI events."""
        self._event_listeners.append(fn)

    def remove_event_listener(self, fn: Callable) -> None:
        """Remove a previously registered event listener."""
        try:
            self._event_listeners.remove(fn)
        except ValueError:
            pass

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire-and-forget event to all registered listeners (AD-254)."""
        event = {"type": event_type, "data": data, "timestamp": time.time()}
        for fn in self._event_listeners:
            try:
                fn(event)
            except Exception:
                pass

    def build_state_snapshot(self) -> dict[str, Any]:
        """Build a full state snapshot for HXI clients (AD-254)."""
        agents = []
        for agent in self.registry.all():
            trust_score = self.trust_network.get_score(agent.id)
            agents.append({
                "id": agent.id,
                "agent_type": agent.agent_type,
                "pool": agent.pool,
                "state": agent.state.value if hasattr(agent.state, "value") else str(agent.state),
                "confidence": agent.confidence,
                "trust": round(trust_score, 4),
                "tier": getattr(agent, "tier", "core"),
            })

        connections = []
        for (source, target, rel_type), weight in self.hebbian_router.all_weights_typed().items():
            connections.append({
                "source": source,
                "target": target,
                "rel_type": rel_type,
                "weight": round(weight, 4),
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
                pass

        return {
            "agents": agents,
            "connections": connections,
            "pools": pools,
            "system_mode": system_mode,
            "tc_n": round(tc_n, 4),
            "routing_entropy": round(routing_entropy, 4),
            "fresh_boot": self._fresh_boot,
            "pool_groups": self.pool_groups.status(self.pools),
            "pool_to_group": dict(self.pool_groups._pool_to_group),
        }

    async def create_pool(
        self,
        name: str,
        agent_type: str,
        target_size: int | None = None,
        agent_ids: list[str] | None = None,
        **spawn_kwargs: Any,
    ) -> ResourcePool:
        """Create and start a resource pool."""
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
            await self._wire_agent(agent)

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
            self._red_team_agents.append(agent)

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
            )

        logger.info("Spawned %d red team agents", count)

    async def start(self) -> None:
        """Boot ProbOS: start mesh services, consensus layer, create default pools."""
        if self._started:
            return

        logger.info("=" * 60)
        logger.info("ProbOS %s starting...", self.config.system.version)
        logger.info("=" * 60)

        # Start infrastructure
        self._data_dir.mkdir(parents=True, exist_ok=True)
        await self.event_log.start()
        await self.hebbian_router.start()
        await self.signal_manager.start()
        await self.gossip.start()
        await self.trust_network.start()

        # Start default pools (Phase 14c: deterministic agent IDs)
        _builtin_pools = [
            ("system", "system_heartbeat", 2),
            ("filesystem", "file_reader", 3),
            ("filesystem_writers", "file_writer", 3),
            ("directory", "directory_list", 3),
            ("search", "file_search", 3),
            ("shell", "shell_command", 3),
            ("http", "http_fetch", 3),
        ]
        for pool_name, agent_type, size in _builtin_pools:
            ids = generate_pool_ids(agent_type, pool_name, size)
            await self.create_pool(pool_name, agent_type, target_size=size, agent_ids=ids)

        # Introspect pool (needs runtime kwarg)
        ids = generate_pool_ids("introspect", "introspect", 2)
        await self.create_pool("introspect", "introspect", target_size=2, agent_ids=ids, runtime=self)

        # Bundled CognitiveAgent pools (Phase 22, AD-252)
        if self.config.bundled_agents.enabled:
            _bundled_pools = [
                ("web_search", "web_search", 2),
                ("page_reader", "page_reader", 2),
                ("weather", "weather", 2),
                ("news", "news", 2),
                ("translator", "translator", 2),
                ("summarizer", "summarizer", 2),
                ("calculator", "calculator", 2),
                ("todo_manager", "todo_manager", 2),
                ("note_taker", "note_taker", 2),
                ("scheduler", "scheduler", 2),
            ]
            for pool_name, agent_type, size in _bundled_pools:
                ids = generate_pool_ids(agent_type, pool_name, size)
                await self.create_pool(
                    pool_name, agent_type, target_size=size,
                    agent_ids=ids, llm_client=self.llm_client, runtime=self,
                )

        # Engineering team — Builder Agent (AD-302)
        if self.config.bundled_agents.enabled:
            await self.create_pool(
                "builder", "builder", target_size=1,
                llm_client=self.llm_client, runtime=self,
            )

        # Science team — Architect Agent (AD-307)
        if self.config.bundled_agents.enabled:
            await self.create_pool(
                "architect", "architect", target_size=1,
                llm_client=self.llm_client, runtime=self,
            )

        # Build CodebaseIndex — ship's library, available to all agents (AD-297)
        from probos.cognitive.codebase_index import CodebaseIndex
        self.codebase_index = CodebaseIndex(source_root=Path(__file__).resolve().parent)
        self.codebase_index.build()

        # Medical team pool (AD-290)
        if self.config.medical.enabled:
            med_cfg = self.config.medical

            # Create vitals monitor pool entry (HeartbeatAgent — no LLM)
            ids = generate_pool_ids("vitals_monitor", "medical_vitals", 1)
            await self.create_pool(
                "medical_vitals", "vitals_monitor", target_size=1,
                agent_ids=ids, runtime=self,
                window_size=med_cfg.vitals_window_size,
                pool_health_min=med_cfg.pool_health_min,
                trust_floor=med_cfg.trust_floor,
                health_floor=med_cfg.health_floor,
                max_trust_outliers=med_cfg.max_trust_outliers,
            )

            # CognitiveAgent medical agents — all share "medical" pool
            _medical_cognitive = [
                ("diagnostician", "diagnostician"),
                ("surgeon", "surgeon"),
                ("pharmacist", "pharmacist"),
                ("pathologist", "pathologist"),
            ]
            for agent_type_name, pool_suffix in _medical_cognitive:
                ids = generate_pool_ids(agent_type_name, f"medical_{pool_suffix}", 1)
                await self.create_pool(
                    f"medical_{pool_suffix}", agent_type_name, target_size=1,
                    agent_ids=ids, llm_client=self.llm_client, runtime=self,
                )

            # Register codebase_knowledge skill on CognitiveAgent medical agents
            from probos.cognitive.codebase_skill import create_codebase_skill
            codebase_skill = create_codebase_skill(self.codebase_index)
            for pool_name in ["medical_pathologist"]:
                pool = self.pools.get(pool_name)
                if pool:
                    for agent in pool.healthy_agents:
                        if hasattr(agent, "add_skill"):
                            agent.add_skill(codebase_skill)

        # Attach codebase_knowledge skill to architect pool (AD-307)
        if self.config.bundled_agents.enabled:
            from probos.cognitive.codebase_skill import create_codebase_skill as _create_cb_skill
            _cb_skill = _create_cb_skill(self.codebase_index)
            pool = self.pools.get("architect")
            if pool:
                for agent in pool.healthy_agents:
                    if hasattr(agent, "add_skill"):
                        agent.add_skill(_cb_skill)

        # Refresh decomposer with intent descriptors from all registered templates
        self.decomposer.refresh_descriptors(self._collect_intent_descriptors())

        # Spawn red team agents
        await self._spawn_red_team(self.config.consensus.red_team_pool_size)

        # Register pool groups (crew teams) — AD-291
        self.pool_groups.register(PoolGroup(
            name="core",
            display_name="Core Systems",
            pool_names={"system", "filesystem", "filesystem_writers", "directory", "search", "shell", "http", "introspect"},
            exclude_from_scaler=True,
        ))

        if self.config.bundled_agents.enabled:
            self.pool_groups.register(PoolGroup(
                name="bundled",
                display_name="Bundled Agents",
                pool_names={"web_search", "page_reader", "weather", "news", "translator", "summarizer", "calculator", "todo_manager", "note_taker", "scheduler"},
            ))

        if self.config.medical.enabled:
            self.pool_groups.register(PoolGroup(
                name="medical",
                display_name="Medical",
                pool_names={"medical_vitals", "medical_diagnostician", "medical_surgeon", "medical_pharmacist", "medical_pathologist"},
                exclude_from_scaler=True,
            ))

        if self.config.self_mod.enabled:
            sm_pools = {"skills"}
            if self.config.qa.enabled:
                sm_pools.add("system_qa")
            self.pool_groups.register(PoolGroup(
                name="self_mod",
                display_name="Self-Modification",
                pool_names=sm_pools,
                exclude_from_scaler=True,
            ))

        # Security pool group — red team agents (AD-296)
        self.pool_groups.register(PoolGroup(
            name="security",
            display_name="Security",
            pool_names={"red_team"},
            exclude_from_scaler=False,
        ))

        # Engineering pool group (AD-302)
        self.pool_groups.register(PoolGroup(
            name="engineering",
            display_name="Engineering",
            pool_names={"builder"},
            exclude_from_scaler=True,
        ))

        # Science pool group (AD-307)
        self.pool_groups.register(PoolGroup(
            name="science",
            display_name="Science",
            pool_names={"architect"},
            exclude_from_scaler=True,
        ))

        # Start pool scaler if scaling is enabled
        if self.config.scaling.enabled:
            pool_intent_map = self._build_pool_intent_map()
            consensus_pools = self._find_consensus_pools()
            self.pool_scaler = PoolScaler(
                pools=self.pools,
                intent_bus=self.intent_bus,
                pool_config=self.config.pools,
                scaling_config=self.config.scaling,
                pool_intent_map=pool_intent_map,
                excluded_pools=self.pool_groups.excluded_pools(),
                trust_network=self.trust_network,
                consensus_pools=consensus_pools,
                consensus_min_agents=self.config.consensus.min_votes,
            )
            await self.pool_scaler.start()

            # Wire surge function into escalation manager
            self.escalation_manager._surge_fn = self.pool_scaler.request_surge

        # Start federation if enabled
        if self.config.federation.enabled:
            from probos.federation import FederationRouter, FederationBridge
            from probos.federation.mock_transport import MockFederationTransport, MockTransportBus

            # Use real transport if pyzmq available, else skip
            transport = None
            try:
                from probos.federation.transport import FederationTransport
                transport = FederationTransport(
                    node_id=self.config.federation.node_id,
                    bind_address=self.config.federation.bind_address,
                    peers=self.config.federation.peers,
                )
                await transport.start()
            except ImportError:
                logger.warning("pyzmq not available; federation transport disabled")
            except Exception as e:
                logger.warning("Federation transport failed to start: %s", e)

            if transport is not None:
                router = FederationRouter()
                validate_fn = (
                    self._validate_remote_result
                    if self.config.federation.validate_remote_results
                    else None
                )
                bridge = FederationBridge(
                    node_id=self.config.federation.node_id,
                    transport=transport,
                    router=router,
                    intent_bus=self.intent_bus,
                    config=self.config.federation,
                    self_model_fn=self._build_self_model,
                    validate_fn=validate_fn,
                )
                await bridge.start()
                self.intent_bus._federation_fn = bridge.forward_intent
                self.federation_bridge = bridge
                self._federation_transport = transport
                logger.info("Federation started: node=%s", self.config.federation.node_id)

        # Start self-modification pipeline if enabled
        if self.config.self_mod.enabled:
            from probos.cognitive.agent_designer import AgentDesigner
            from probos.cognitive.code_validator import CodeValidator
            from probos.cognitive.dependency_resolver import DependencyResolver
            from probos.cognitive.sandbox import SandboxRunner
            from probos.cognitive.behavioral_monitor import BehavioralMonitor
            from probos.cognitive.self_mod import SelfModificationPipeline
            from probos.cognitive.skill_designer import SkillDesigner
            from probos.cognitive.skill_validator import SkillValidator

            designer = AgentDesigner(self.llm_client, self.config.self_mod)
            validator = CodeValidator(self.config.self_mod)
            sandbox = SandboxRunner(self.config.self_mod, llm_client=self.llm_client)
            self.behavioral_monitor = BehavioralMonitor()
            skill_designer = SkillDesigner(self.llm_client, self.config.self_mod)
            skill_validator = SkillValidator(self.config.self_mod)
            dependency_resolver = DependencyResolver(
                allowed_imports=self.config.self_mod.allowed_imports,
            )

            # Optional research phase
            research = None
            if self.config.self_mod.research_enabled:
                from probos.cognitive.research import ResearchPhase
                research = ResearchPhase(
                    llm_client=self.llm_client,
                    submit_intent_fn=self.submit_intent_with_consensus,
                    config=self.config.self_mod,
                )

            self.self_mod_pipeline = SelfModificationPipeline(
                designer=designer,
                validator=validator,
                sandbox=sandbox,
                monitor=self.behavioral_monitor,
                config=self.config.self_mod,
                register_fn=self._register_designed_agent,
                unregister_fn=self._unregister_designed_agent,
                create_pool_fn=self._create_designed_pool,
                set_trust_fn=self._set_probationary_trust,
                user_approval_fn=None,  # Shell sets this after creation
                skill_designer=skill_designer,
                skill_validator=skill_validator,
                add_skill_fn=self._add_skill_to_agents,
                research=research,
                dependency_resolver=dependency_resolver,
                event_log=self.event_log,
            )
            logger.info("Self-modification pipeline enabled")

            # Spawn skills pool for SkillBasedAgent
            ids = generate_pool_ids("skill_agent", "skills", 2)
            await self.create_pool(
                "skills", "skill_agent", target_size=2,
                agent_ids=ids,
                llm_client=self.llm_client,
            )

            # Spawn SystemQA pool if QA enabled (AD-153: single agent)
            if self.config.qa.enabled:
                ids = generate_pool_ids("system_qa", "system_qa", 1)
                await self.create_pool("system_qa", "system_qa", target_size=1, agent_ids=ids)
                qa_pool = self.pools.get("system_qa")
                if qa_pool and qa_pool.healthy_agents:
                    agents = list(qa_pool.healthy_agents)
                    if isinstance(agents[0], str):
                        self._system_qa = self.registry.get(agents[0])
                    else:
                        self._system_qa = agents[0]

        # Start episodic memory if provided
        if self.episodic_memory:
            await self.episodic_memory.start()

        # Create FeedbackEngine (AD-219)
        from probos.cognitive.feedback import FeedbackEngine
        self.feedback_engine = FeedbackEngine(
            trust_network=self.trust_network,
            hebbian_router=self.hebbian_router,
            episodic_memory=self.episodic_memory,
            event_log=self.event_log,
        )

        # Create CorrectionDetector + AgentPatcher (AD-229, AD-230)
        from probos.cognitive.correction_detector import CorrectionDetector
        from probos.cognitive.agent_patcher import AgentPatcher
        self._correction_detector = CorrectionDetector(llm_client=self.llm_client)
        if hasattr(self, "self_mod_pipeline") and self.self_mod_pipeline:
            self._agent_patcher = AgentPatcher(
                llm_client=self.llm_client,
                code_validator=self.self_mod_pipeline._validator,
                sandbox=self.self_mod_pipeline._sandbox,
            )

        # Initialize knowledge store (AD-159) and warm boot (AD-162)
        if self.config.knowledge.enabled:
            try:
                from probos.knowledge.store import KnowledgeStore

                # If no explicit repo_path, use data_dir/knowledge (AD-159)
                kcfg = self.config.knowledge
                if not kcfg.repo_path:
                    kcfg = kcfg.model_copy(update={"repo_path": str(self._data_dir / "knowledge")})

                self._knowledge_store = KnowledgeStore(kcfg)
                await self._knowledge_store.initialize()

                if self.config.knowledge.restore_on_boot:
                    await self._restore_from_knowledge()

                logger.info("Knowledge store initialized: %s", self._knowledge_store.repo_path)
            except Exception as e:
                logger.warning("Knowledge store initialization failed: %s — continuing without persistence", e)
                self._knowledge_store = None

        # Start dreaming scheduler if episodic memory is available
        if self.episodic_memory:
            dream_cfg = self.config.dreaming
            engine = DreamingEngine(
                router=self.hebbian_router,
                trust_network=self.trust_network,
                episodic_memory=self.episodic_memory,
                config=dream_cfg,
                idle_scale_down_fn=(
                    self.pool_scaler.scale_down_idle
                    if self.pool_scaler
                    else None
                ),
            )
            self.dream_scheduler = DreamScheduler(
                engine=engine,
                idle_threshold_seconds=dream_cfg.idle_threshold_seconds,
                dream_interval_seconds=dream_cfg.dream_interval_seconds,
            )
            self.dream_scheduler.start()

        # Create EmergentDetector (AD-237) — unconditional, pure observer
        self._emergent_detector = EmergentDetector(
            hebbian_router=self.hebbian_router,
            trust_network=self.trust_network,
            episodic_memory=self.episodic_memory,
        )

        # Wire post-dream analysis callback (AD-237)
        if self.dream_scheduler:
            self.dream_scheduler._post_dream_fn = self._on_post_dream
            self.dream_scheduler._pre_dream_fn = self._on_pre_dream
            self.dream_scheduler._post_micro_dream_fn = self._on_post_micro_dream

        # Start task scheduler (AD-282)
        self.task_scheduler = TaskScheduler(
            process_fn=self.process_natural_language,
        )
        self.task_scheduler.start()

        # Start periodic flush of trust + routing weights
        self._flush_task = asyncio.create_task(self._periodic_flush_loop())

        # Create SemanticKnowledgeLayer (AD-243) — only when episodic memory available
        if self.episodic_memory:
            try:
                db_dir = Path(self.episodic_memory.db_path).parent
                self._semantic_layer = SemanticKnowledgeLayer(
                    db_path=db_dir / "semantic",
                    episodic_memory=self.episodic_memory,
                )
                await self._semantic_layer.start()
                logger.info("Semantic knowledge layer started")
            except Exception as e:
                logger.warning("Semantic knowledge layer initialization failed: %s — continuing without", e)
                self._semantic_layer = None

        # Persist agent manifest (Phase 14c)
        await self._persist_manifest()

        # Reconcile trust store — remove stale entries from previous sessions (AD-280)
        active_ids = {a.id for a in self.registry.all()}
        removed = self.trust_network.reconcile(active_ids)
        if removed:
            logger.info("trust-reconcile removed=%d stale entries", removed)

        self._started = True

        await self.event_log.log(category="system", event="started")
        logger.info(
            "ProbOS started: %d agents across %d pools + %d red team",
            self.registry.count,
            len(self.pools),
            len(self._red_team_agents),
        )

    async def stop(self) -> None:
        """Graceful shutdown of all pools, mesh services, and persistence."""
        if not self._started:
            return

        logger.info("ProbOS shutting down...")
        try:
            await self.event_log.log(category="system", event="stopping")
        except (asyncio.CancelledError, Exception):
            pass  # event log may be unavailable during shutdown

        # Cancel periodic flush
        if hasattr(self, '_flush_task'):
            self._flush_task.cancel()

        # Stop red team agents
        for agent in self._red_team_agents:
            await agent.stop()
            await self.registry.unregister(agent.id)
        self._red_team_agents.clear()

        # Stop pool scaler before stopping pools
        if self.pool_scaler:
            await self.pool_scaler.stop()
            self.pool_scaler = None

        # Stop federation
        if self.federation_bridge:
            await self.federation_bridge.stop()
            self.federation_bridge = None
        if self._federation_transport:
            await self._federation_transport.stop()
            self._federation_transport = None

        # Stop pools (stops agents, unregisters from registry)
        for name, pool in self.pools.items():
            await pool.stop()
        self.pools.clear()

        # Persist knowledge store artifacts before stopping services
        if self._knowledge_store:
            try:
                # Persist agent manifest (Phase 14c)
                await self._knowledge_store.store_manifest(self._build_manifest())
                # Persist trust snapshot (raw alpha/beta — AD-168)
                await self._knowledge_store.store_trust_snapshot(
                    self.trust_network.raw_scores()
                )
                # Persist routing weights
                weights = [
                    {"source": s, "target": t, "rel_type": rt, "weight": w}
                    for (s, t, rt), w in self.hebbian_router.all_weights_typed().items()
                ]
                await self._knowledge_store.store_routing_weights(weights)
                # Persist workflow cache
                await self._knowledge_store.store_workflows(
                    self.workflow_cache.export_all()
                )
                # Flush all pending commits
                await self._knowledge_store.flush()
            except Exception as e:
                logger.warning("Knowledge store shutdown persistence failed: %s", e)

        # Stop mesh and consensus services
        await self.gossip.stop()
        await self.signal_manager.stop()
        await self.hebbian_router.stop()
        await self.trust_network.stop()
        try:
            await self.event_log.log(category="system", event="stopped")
        except (asyncio.CancelledError, Exception):
            pass
        await self.event_log.stop()

        # Clean up LLM client
        await self.llm_client.close()

        # Tier 3: Shutdown consolidation — flush remaining episodes (AD-288)
        if self.dream_scheduler and self.episodic_memory:
            logger.info("Consolidating session memories...")
            try:
                report = await self.dream_scheduler.engine.dream_cycle()
                logger.info(
                    "Session consolidation complete: replayed=%d strengthened=%d pruned=%d",
                    report.episodes_replayed,
                    report.weights_strengthened,
                    report.weights_pruned,
                )
            except (asyncio.CancelledError, Exception) as e:
                logger.warning("Shutdown consolidation failed: %s", e)

        # Stop dreaming scheduler
        if self.dream_scheduler:
            await self.dream_scheduler.stop()
            self.dream_scheduler = None

        # Stop task scheduler (AD-282)
        if self.task_scheduler:
            await self.task_scheduler.stop()
            self.task_scheduler = None

        # Stop episodic memory
        if self.episodic_memory:
            await self.episodic_memory.stop()

        # Stop semantic knowledge layer (AD-243)
        if self._semantic_layer:
            await self._semantic_layer.stop()
            self._semantic_layer = None

        self._started = False
        logger.info("ProbOS shutdown complete. Final agent count: %d", self.registry.count)

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

        await self.event_log.log(
            category="mesh",
            event="intent_broadcast",
            detail=f"intent={intent} id={msg.id[:8]}",
        )

        results = await self.intent_bus.broadcast(msg, timeout=timeout)

        # Update hebbian weights based on results
        for result in results:
            self.hebbian_router.record_interaction(
                source=msg.id,  # intent as source
                target=result.agent_id,
                success=result.success,
            )

            # Emit hebbian_update for HXI (AD-254)
            self._emit_event("hebbian_update", {
                "source": msg.id,
                "target": result.agent_id,
                "weight": round(self.hebbian_router.get_weight(msg.id, result.agent_id), 4),
                "rel_type": "intent",
            })

        await self.event_log.log(
            category="mesh",
            event="intent_resolved",
            detail=f"intent={intent} id={msg.id[:8]} results={len(results)}",
        )

        return results

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

        await self.event_log.log(
            category="mesh",
            event="intent_broadcast",
            detail=f"intent={intent} id={msg.id[:8]} consensus=true",
        )

        # Step 1: Broadcast and collect results
        results = await self.intent_bus.broadcast(msg, timeout=timeout)

        # Update hebbian weights (intent → agent)
        for result in results:
            self.hebbian_router.record_interaction(
                source=msg.id,
                target=result.agent_id,
                success=result.success,
            )

            # Emit hebbian_update for HXI (AD-254)
            self._emit_event("hebbian_update", {
                "source": msg.id,
                "target": result.agent_id,
                "weight": round(self.hebbian_router.get_weight(msg.id, result.agent_id), 4),
                "rel_type": "intent",
            })

        # Step 2: Evaluate quorum
        consensus = self.quorum_engine.evaluate(results, policy=policy)

        # Emit consensus event for HXI (AD-254)
        self._emit_event("consensus", {
            "intent": intent,
            "outcome": consensus.outcome.value,
            "approval_ratio": round(consensus.approval_ratio, 4),
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
        if results and self._red_team_agents:
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
                    self.trust_network.record_outcome(
                        result.agent_id,
                        success=vr.verified,
                        weight=shapley_weight,
                        intent_type=intent,
                        episode_id=msg.id,
                        verifier_id=rt_agent.id,
                    )

                    self._emit_event("trust_update", {
                        "agent_id": result.agent_id,
                        "new_score": round(self.trust_network.get_score(result.agent_id), 4),
                        "success": vr.verified,
                    })

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
                for rt_agent in self._red_team_agents
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
            pass

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
            pass

        # System mode
        system_mode = "active"
        try:
            if self.dream_scheduler and self.dream_scheduler.is_dreaming:
                system_mode = "dreaming"
            elif (_time.monotonic() - self._last_request_time) > 30:
                system_mode = "idle"
        except Exception:
            pass

        # Intent count
        intent_count = 0
        try:
            intent_count = len(self.decomposer._intent_descriptors)
        except Exception:
            pass

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

        # Check 1: Pool count claims
        pool_count_matches = _re.findall(r'(\d+)\s+pools?\b', response_lower)
        for match in pool_count_matches:
            claimed = int(match)
            if claimed != self_model.pool_count and claimed != 0:
                violations.append(
                    f"pools: claimed {claimed}, actual {self_model.pool_count}"
                )

        # Check 2: Agent count claims
        agent_count_matches = _re.findall(r'(\d+)\s+agents?\b', response_lower)
        for match in agent_count_matches:
            claimed = int(match)
            if claimed != self_model.agent_count and claimed != 0:
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
    ) -> dict[str, Any]:
        """Process a natural language request through the full cognitive pipeline.

        Pipeline: NL input → working memory assembly → LLM decomposition →
        DAG execution via mesh + consensus → aggregated results.

        If on_event is provided, it is called at key pipeline stages:
        decompose_start, decompose_complete, node_start, node_complete, node_failed.
        """
        t_start = time.monotonic()

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
            await on_event("decompose_start", {"text": text})

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
                    last_execution_success=self._was_last_execution_successful(),
                )
                if correction:
                    record = self._find_designed_record(
                        correction.target_agent_type,
                    )
                    if record and self._agent_patcher:
                        patch_result = await self._agent_patcher.patch(
                            record, correction,
                            self._last_execution_text or text,
                        )
                        if patch_result.success:
                            result = await self.apply_correction(
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
            await on_event("decompose_complete", {"dag": dag})

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
                        # Build execution context from prior execution (AD-235)
                        exec_context = ""
                        if self._last_execution and self._was_last_execution_successful():
                            exec_context = self._format_execution_context()

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
                                    pass  # Never block on persistence failure
                            # Auto-index for semantic search (AD-243)
                            if self._semantic_layer:
                                try:
                                    await self._semantic_layer.index_agent(
                                        agent_type=record.agent_type,
                                        intent_name=record.intent_name,
                                        description=record.intent_name,
                                        strategy=record.strategy,
                                        source_snippet=record.source_code[:200] if record.source_code else "",
                                    )
                                except Exception:
                                    pass
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
                episode = self._build_episode(text, execution_result, t_start, t_end)
                await self.episodic_memory.store(episode)

                # Persist to knowledge store (AD-159)
                if self._knowledge_store:
                    try:
                        await self._knowledge_store.store_episode(episode)
                    except Exception:
                        pass  # Never block on persistence failure
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
                pass  # Never block on feedback failure

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

    # ------------------------------------------------------------------
    # Correction hot-reload (AD-231)
    # ------------------------------------------------------------------

    async def apply_correction(
        self,
        correction: Any,
        patch_result: Any,
        original_record: Any,
    ) -> Any:
        """Hot-reload a patched self-mod'd agent into the runtime."""
        from probos.cognitive.agent_patcher import CorrectionResult

        strategy = original_record.strategy
        agent_type = original_record.agent_type

        try:
            if strategy == "skill":
                await self._apply_skill_correction(
                    correction, patch_result, original_record,
                )
            else:
                await self._apply_agent_correction(
                    correction, patch_result, original_record,
                )
        except Exception as exc:
            logger.warning("apply_correction failed: %s", exc)
            return CorrectionResult(
                success=False,
                agent_type=agent_type,
                strategy=strategy,
                changes_description=f"Hot-reload failed: {exc}",
            )

        # Update the record
        original_record.source_code = patch_result.patched_source
        original_record.status = "patched"

        # Refresh decomposer descriptors
        if hasattr(self, "decomposer") and self.decomposer:
            try:
                descriptors = self._collect_intent_descriptors()
                self.decomposer.refresh_descriptors(descriptors)
            except Exception:
                pass

        # Persist to knowledge store
        if hasattr(self, "_knowledge_store") and self._knowledge_store:
            try:
                await self._knowledge_store.store_agent(
                    original_record, patch_result.patched_source,
                )
            except Exception:
                pass
        # Auto-index for semantic search (AD-243)
        if self._semantic_layer:
            try:
                await self._semantic_layer.index_agent(
                    agent_type=original_record.agent_type,
                    intent_name=original_record.intent_name,
                    description=original_record.intent_name,
                    strategy=original_record.strategy,
                    source_snippet=patch_result.patched_source[:200] if patch_result.patched_source else "",
                )
            except Exception:
                pass

        # Auto-retry the original request
        retry_result = None
        retried = False
        original_text = self._last_execution_text
        if original_text:
            try:
                retried = True
                import time as _time

                retry_result = await self.process_natural_language(
                    original_text, on_event=None,
                )
            except Exception as exc:
                retry_result = {"error": str(exc)}

        # Record correction feedback (AD-234)
        retry_success = bool(
            retried and retry_result and not retry_result.get("error")
        )
        if hasattr(self, "feedback_engine") and self.feedback_engine:
            try:
                await self.feedback_engine.apply_correction_feedback(
                    original_text=original_text or "",
                    correction=correction,
                    patch_result=patch_result,
                    retry_success=retry_success,
                )
            except Exception:
                pass

        return CorrectionResult(
            success=True,
            agent_type=agent_type,
            strategy=strategy,
            changes_description=patch_result.changes_description,
            retried=retried,
            retry_result=retry_result,
        )

    async def _apply_agent_correction(
        self,
        correction: Any,
        patch_result: Any,
        record: Any,
    ) -> None:
        """Hot-swap a patched agent class into the runtime."""
        agent_type = record.agent_type
        pool_name = f"designed_{agent_type}"
        new_class = patch_result.agent_class

        if new_class is None:
            raise ValueError("PatchResult has no agent_class")

        # Register the new class template
        if hasattr(self, "_spawner") and hasattr(self._spawner, "_templates"):
            self._spawner._templates[agent_type] = new_class

        # Re-create pool agents with the new class
        pool = self._pools.get(pool_name)
        if pool:
            for agent in list(pool.healthy_agents):
                aid = agent.id if hasattr(agent, "id") else str(agent)
                try:
                    new_agent = new_class(
                        pool=pool_name,
                        llm_client=getattr(self, "llm_client", None),
                    )
                    new_agent._id = aid  # preserve agent identity
                    self.registry.register(new_agent)
                    self.intent_bus.subscribe(
                        aid, new_agent.handle_intent,
                        intent_names=[d.name for d in getattr(new_agent, "intent_descriptors", [])] or None,
                    )
                    if hasattr(new_agent, "capabilities") and new_agent.capabilities:
                        self.capability_registry.register(aid, new_agent.capabilities)
                except Exception as exc:
                    logger.warning("Failed to replace agent %s: %s", aid, exc)

    async def _apply_skill_correction(
        self,
        correction: Any,
        patch_result: Any,
        record: Any,
    ) -> None:
        """Hot-swap a patched skill handler."""
        from probos.types import IntentDescriptor, Skill
        import time as _time

        intent_name = correction.target_intent or record.intent_name
        handler = patch_result.handler

        if handler is None:
            raise ValueError("PatchResult has no handler")

        # Build a replacement skill
        new_skill = Skill(
            name=intent_name,
            descriptor=IntentDescriptor(
                name=intent_name,
                description=correction.explanation or record.intent_name,
            ),
            source_code=patch_result.patched_source,
            handler=handler,
            created_at=_time.time(),
            origin="patched",
        )

        # Find agents with the old skill and replace it
        if hasattr(self, "_add_skill_to_agents"):
            self._add_skill_to_agents(new_skill)

    def _find_designed_record(self, agent_type: str) -> Any:
        """Find the most recent active DesignedAgentRecord for an agent type."""
        if not hasattr(self, "self_mod_pipeline") or not self.self_mod_pipeline:
            return None
        records = self.self_mod_pipeline._records
        # Search in reverse (most recent first)
        for record in reversed(records):
            if record.agent_type == agent_type and record.status in (
                "active", "patched",
            ):
                return record
        return None

    def _was_last_execution_successful(self) -> bool:
        """Check whether the last execution had any failed nodes."""
        if not self._last_execution:
            return False
        dag = self._last_execution.get("dag")
        if dag is None:
            return True  # No DAG info — assume success
        nodes = getattr(dag, "nodes", [])
        if not nodes:
            return True
        return all(
            getattr(n, "status", "completed") == "completed"
            for n in nodes
        )

    def _format_execution_context(self) -> str:
        """Format last execution results as context for AgentDesigner (AD-235)."""
        if not self._last_execution:
            return ""

        parts: list[str] = []
        original_text = self._last_execution_text or ""
        if original_text:
            parts.append(f"Prior user request: {original_text!r}")

        dag = self._last_execution.get("dag")
        if dag is not None:
            nodes = getattr(dag, "nodes", [])
            for node in nodes:
                intent = getattr(node, "intent", "?")
                status = getattr(node, "status", "?")
                params = getattr(node, "params", {})
                result = getattr(node, "result", None)
                result_summary = ""
                if isinstance(result, dict):
                    # Show key fields without flooding context
                    for k in ("output", "result", "agent_id"):
                        v = result.get(k)
                        if v is not None:
                            val = str(v)
                            if len(val) > 200:
                                val = val[:200] + "..."
                            result_summary += f", {k}={val!r}"
                parts.append(
                    f"  [intent: {intent}, params: {params}, status: {status}{result_summary}]"
                )

        return "\n".join(parts) if parts else ""

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
                "red_team_agents": len(self._red_team_agents),
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
        result["emergent"] = (
            self._emergent_detector.summary()
            if self._emergent_detector
            else {"enabled": False}
        )
        result["semantic_knowledge"] = (
            self._semantic_layer.stats()
            if self._semantic_layer
            else {"enabled": False}
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
        return result

    async def recall_similar(self, query: str, k: int = 5) -> list[Episode]:
        """Recall similar past episodes from episodic memory."""
        if not self.episodic_memory:
            return []
        return await self.episodic_memory.recall(query, k=k)

    def _on_pre_dream(self) -> None:
        """Pre-dream callback: emit system_mode event for HXI (AD-254)."""
        self._emit_event("system_mode", {"mode": "dreaming", "previous": "idle"})

    def _on_post_dream(self, dream_report: Any) -> None:
        """Post-dream callback: run emergent detection and log patterns (AD-237)."""
        # Emit system_mode event for HXI (AD-254) — dream cycle ended
        self._emit_event("system_mode", {"mode": "idle", "previous": "dreaming"})

        if not self._emergent_detector:
            return
        try:
            patterns = self._emergent_detector.analyze(dream_report=dream_report)
            for pattern in patterns:
                # Fire-and-forget event logging (sync context, schedule coroutine)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.event_log.log(
                        category="emergent",
                        event=pattern.pattern_type,
                        detail=pattern.description,
                    ))
                except RuntimeError:
                    pass  # No running loop — skip logging
        except Exception as e:
            logger.debug("Post-dream emergent analysis failed: %s", e)

    def _on_post_micro_dream(self, micro_report: dict) -> None:
        """Post-micro-dream callback: update emergent detector (AD-288)."""
        if not self._emergent_detector:
            return
        try:
            self._emergent_detector.analyze(dream_report=micro_report)
        except Exception as e:
            logger.debug("Post-micro-dream analysis failed: %s", e)

    async def _periodic_flush(self) -> None:
        """Save trust scores and routing weights to KnowledgeStore."""
        if self._knowledge_store is None:
            return
        try:
            await self._knowledge_store.store_trust_snapshot(
                self.trust_network.raw_scores()
            )
            weights = [
                {"source": s, "target": t, "rel_type": rt, "weight": w}
                for (s, t, rt), w in self.hebbian_router.all_weights_typed().items()
            ]
            await self._knowledge_store.store_routing_weights(weights)
            logger.debug("Periodic flush: trust + routing saved")
        except Exception:
            logger.debug("Periodic flush failed", exc_info=True)

    async def _periodic_flush_loop(self) -> None:
        """Background loop that flushes trust + routing every 60s."""
        try:
            while True:
                await asyncio.sleep(60)
                await self._periodic_flush()
        except asyncio.CancelledError:
            return

    def _build_episode(
        self,
        text: str,
        execution_result: dict[str, Any],
        t_start: float,
        t_end: float,
    ) -> Episode:
        """Build an Episode dataclass from execution results."""
        dag = execution_result.get("dag")
        results = execution_result.get("results", {})

        dag_summary: dict[str, Any] = {}
        outcomes: list[dict[str, Any]] = []
        agent_ids: list[str] = []

        if dag and hasattr(dag, "nodes"):
            intent_types = [n.intent for n in dag.nodes]
            dag_summary = {
                "node_count": len(dag.nodes),
                "intent_types": intent_types,
                "has_dependencies": any(n.depends_on for n in dag.nodes),
            }
            for node in dag.nodes:
                node_result = results.get(node.id, {})
                outcome: dict[str, Any] = {
                    "intent": node.intent,
                    "success": node.status == "completed",
                    "status": node.status,
                }
                # Extract agent IDs from the result
                if isinstance(node_result, dict):
                    node_results = node_result.get("results", [])
                    if isinstance(node_results, list):
                        for r in node_results:
                            aid = r.get("agent_id") if isinstance(r, dict) else getattr(r, "agent_id", None)
                            if aid:
                                agent_ids.append(aid)
                outcomes.append(outcome)

        reflection = execution_result.get("reflection")

        # Capture Shapley attribution from the most recent consensus (AD-295b)
        shapley_values = dict(self._last_shapley_values) if hasattr(self, '_last_shapley_values') and self._last_shapley_values else {}

        # Capture trust deltas generated during this episode (AD-295b)
        trust_deltas: list[dict[str, Any]] = []
        if hasattr(self, 'trust_network') and self.trust_network:
            recent_events = self.trust_network.get_events_since(t_start)
            trust_deltas = [
                {
                    "agent_id": e.agent_id,
                    "old": round(e.old_score, 4),
                    "new": round(e.new_score, 4),
                    "weight": round(e.weight, 4),
                }
                for e in recent_events
            ]

        return Episode(
            timestamp=time.time(),
            user_input=text,
            dag_summary=dag_summary,
            outcomes=outcomes,
            reflection=reflection if isinstance(reflection, str) else None,
            agent_ids=agent_ids,
            duration_ms=(t_end - t_start) * 1000,
            shapley_values=shapley_values,
            trust_deltas=trust_deltas,
        )

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

    async def _wire_agent(self, agent: Any) -> None:
        """Connect an agent to the mesh infrastructure."""
        # Register capabilities
        if hasattr(agent, "capabilities") and agent.capabilities:
            self.capability_registry.register(agent.id, agent.capabilities)

        # Inject into gossip view
        self.gossip.update_local(
            agent_id=agent.id,
            agent_type=agent.agent_type,
            state=agent.state,
            pool=agent.pool,
            capabilities=[c.can for c in agent.capabilities],
            confidence=agent.confidence,
        )

        # If it's a heartbeat agent, attach gossip carrier
        if isinstance(agent, HeartbeatAgent):
            agent.attach_gossip(self.gossip)

        # If agent has handle_intent, subscribe to intent bus
        if hasattr(agent, "handle_intent"):
            intent_names = [d.name for d in getattr(agent, "intent_descriptors", [])] or None
            self.intent_bus.subscribe(agent.id, agent.handle_intent, intent_names=intent_names)

        # Initialize trust record
        self.trust_network.get_or_create(agent.id)

        # Emit agent_state event for HXI (AD-254)
        self._emit_event("agent_state", {
            "agent_id": agent.id,
            "pool": agent.pool,
            "state": agent.state.value if hasattr(agent.state, "value") else str(agent.state),
            "confidence": agent.confidence,
            "trust": round(self.trust_network.get_score(agent.id), 4),
        })

        await self.event_log.log(
            category="lifecycle",
            event="agent_wired",
            agent_id=agent.id,
            agent_type=agent.agent_type,
            pool=agent.pool,
        )

    def _collect_intent_descriptors(self) -> list[IntentDescriptor]:
        """Collect unique intent descriptors from all registered agent templates.

        Includes all agents with non-empty intent_descriptors regardless of tier.
        Agents with empty descriptors (heartbeat, red_team, etc.) are naturally
        excluded because they have nothing to contribute.
        """
        seen: set[str] = set()
        descriptors: list[IntentDescriptor] = []
        for type_name, agent_class in self.spawner._templates.items():
            for desc in getattr(agent_class, "intent_descriptors", []):
                if desc.name not in seen:
                    seen.add(desc.name)
                    descriptors.append(desc)
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
        agent_type = getattr(agent_class, "agent_type", "unknown")
        self.register_agent_type(agent_type, agent_class)

    async def _unregister_designed_agent(self, agent_type: str) -> None:
        """Rollback registration of a self-designed agent type (AD-368)."""
        self.unregister_agent_type(agent_type)

    async def _create_designed_pool(self, agent_type: str, pool_name: str, size: int = 1) -> None:
        """Create a pool for a self-designed agent type."""
        ids = generate_pool_ids(agent_type, pool_name, size)
        await self.create_pool(
            pool_name, agent_type, target_size=size,
            agent_ids=ids, llm_client=self.llm_client, runtime=self,
        )

    async def _set_probationary_trust(self, pool_name: str) -> None:
        """Set probationary trust for all agents in a designed pool."""
        pool = self.pools.get(pool_name)
        if not pool:
            return
        for agent in pool.healthy_agents:
            self.trust_network.create_with_prior(
                agent.id,
                alpha=self.config.self_mod.probationary_alpha,
                beta=self.config.self_mod.probationary_beta,
            )

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
        for idx, agent in enumerate(self._red_team_agents):
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
                pass  # Never block on persistence failure
        # Auto-index skill for semantic search (AD-243)
        if self._semantic_layer:
            try:
                await self._semantic_layer.index_skill(
                    intent_name=skill.name,
                    description=skill.descriptor.description if skill.descriptor else skill.name,
                    target_agent=getattr(skill, "target_agent", ""),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Knowledge store — warm boot and persistence (AD-162)
    # ------------------------------------------------------------------

    async def _restore_from_knowledge(self) -> None:
        """Warm boot: restore state from the knowledge store (AD-162).

        Load order: trust → routing → agents → skills → episodes → workflows → QA.
        Each step is independent and wrapped in try/except so that partial
        failures don't block other restorations.
        """
        ks = self._knowledge_store
        if ks is None:
            return

        restored: list[str] = []
        _trust_snapshot: dict[str, dict] = {}

        # 1. Trust snapshot → restore raw Beta parameters (AD-168)
        try:
            snapshot = await ks.load_trust_snapshot()
            if snapshot:
                _trust_snapshot = snapshot
                for agent_id, params in snapshot.items():
                    alpha = params.get("alpha", 2.0)
                    beta = params.get("beta", 2.0)
                    # Force-set even if record already exists from pool creation
                    record = self.trust_network.get_or_create(agent_id)
                    record.alpha = alpha
                    record.beta = beta
                restored.append(f"trust({len(snapshot)} agents)")
        except Exception as e:
            logger.warning("Warm boot: trust restore failed: %s", e)

        # 2. Routing weights → restore Hebbian weights
        try:
            weights = await ks.load_routing_weights()
            if weights:
                for w in weights:
                    key = (w["source"], w["target"], w.get("rel_type", "intent"))
                    self.hebbian_router._weights[key] = w["weight"]
                    # Also update compat view
                    self.hebbian_router._compat_weights[(w["source"], w["target"])] = w["weight"]
                restored.append(f"routing({len(weights)} weights)")
        except Exception as e:
            logger.warning("Warm boot: routing restore failed: %s", e)

        # 3. Designed agents → validate + register + pool (AD-163)
        #    Phase 14c: use deterministic IDs so trust reconnects automatically.
        #    Only set probationary trust for agents NOT in the trust snapshot.
        try:
            agents = await ks.load_agents()
            if agents and self.config.self_mod.enabled:
                from probos.cognitive.code_validator import CodeValidator
                validator = CodeValidator(self.config.self_mod)

                for metadata, source_code in agents:
                    agent_type = metadata.get("agent_type", "")
                    try:
                        # AD-163: validate before loading
                        errors = validator.validate(source_code)
                        if errors:
                            logger.warning(
                                "Warm boot: skipping agent %s — validation errors: %s",
                                agent_type, errors,
                            )
                            continue

                        # Dynamic load via importlib
                        import importlib.util
                        import sys
                        import tempfile

                        class_name = metadata.get("class_name", "")
                        tmp = tempfile.NamedTemporaryFile(
                            mode="w", suffix=".py", delete=False, encoding="utf-8",
                        )
                        tmp.write(source_code)
                        tmp.flush()
                        tmp.close()
                        tmp_path = tmp.name
                        module_name = f"_probos_restored_{agent_type}"

                        try:
                            spec = importlib.util.spec_from_file_location(module_name, tmp_path)
                            if spec and spec.loader:
                                module = importlib.util.module_from_spec(spec)
                                sys.modules[module_name] = module
                                spec.loader.exec_module(module)
                                agent_class = getattr(module, class_name, None)
                                if agent_class:
                                    await self._register_designed_agent(agent_class)
                                    pool_name = metadata.get("pool_name", f"designed_{agent_type}")
                                    await self._create_designed_pool(agent_type, pool_name)
                                    # Phase 14c: only set probationary trust for
                                    # agents that do NOT have restored trust records.
                                    pool = self.pools.get(pool_name)
                                    if pool:
                                        for aid in pool.healthy_agents:
                                            if aid not in _trust_snapshot:
                                                self.trust_network.create_with_prior(
                                                    aid,
                                                    alpha=self.config.self_mod.probationary_alpha,
                                                    beta=self.config.self_mod.probationary_beta,
                                                )
                                    restored.append(f"agent({agent_type})")
                                else:
                                    logger.warning(
                                        "Warm boot: class %s not found in restored agent %s",
                                        class_name, agent_type,
                                    )
                        finally:
                            try:
                                Path(tmp_path).unlink(missing_ok=True)
                            except OSError:
                                pass
                    except Exception as e:
                        logger.warning("Warm boot: agent %s restore failed: %s", agent_type, e)
        except Exception as e:
            logger.warning("Warm boot: agent restore failed: %s", e)

        # 4. Skills → compile + attach to SkillBasedAgent
        try:
            skills = await ks.load_skills()
            if skills and self.config.self_mod.enabled:
                import importlib.util
                import sys
                import tempfile

                for intent_name, source_code, descriptor_dict in skills:
                    try:
                        # Compile handler
                        handler = None
                        func_name = f"handle_{intent_name}"
                        tmp = tempfile.NamedTemporaryFile(
                            mode="w", suffix=".py", delete=False, encoding="utf-8",
                        )
                        tmp.write(source_code)
                        tmp.flush()
                        tmp.close()
                        tmp_path = tmp.name
                        module_name = f"_probos_skill_restored_{intent_name}"

                        try:
                            spec = importlib.util.spec_from_file_location(module_name, tmp_path)
                            if spec and spec.loader:
                                module = importlib.util.module_from_spec(spec)
                                sys.modules[module_name] = module
                                spec.loader.exec_module(module)
                                handler = getattr(module, func_name, None)
                        finally:
                            try:
                                Path(tmp_path).unlink(missing_ok=True)
                            except OSError:
                                pass
                            sys.modules.pop(module_name, None)

                        if handler is None:
                            logger.warning("Warm boot: no handler function for skill %s", intent_name)
                            continue

                        from probos.types import IntentDescriptor as _ID, Skill as _Skill
                        skill_desc = _ID(
                            name=descriptor_dict.get("name", intent_name),
                            params=descriptor_dict.get("params", {}),
                            description=descriptor_dict.get("description", ""),
                            requires_reflect=descriptor_dict.get("requires_reflect", True),
                        )
                        skill_obj = _Skill(
                            name=intent_name,
                            descriptor=skill_desc,
                            source_code=source_code,
                            handler=handler,
                            created_at=descriptor_dict.get("created_at", time.monotonic()),
                            origin="designed",
                        )
                        await self._add_skill_to_agents(skill_obj)
                        restored.append(f"skill({intent_name})")
                    except Exception as e:
                        logger.warning("Warm boot: skill %s restore failed: %s", intent_name, e)
        except Exception as e:
            logger.warning("Warm boot: skill restore failed: %s", e)

        # 5. Episodes → seed into episodic memory
        try:
            if self.episodic_memory:
                episodes = await ks.load_episodes(limit=self.config.knowledge.max_episodes)
                if episodes:
                    seeded = await self.episodic_memory.seed(episodes)
                    restored.append(f"episodes({seeded})")
        except Exception as e:
            logger.warning("Warm boot: episode restore failed: %s", e)

        # 6. Workflows → populate cache
        try:
            workflows = await ks.load_workflows()
            if workflows and self.workflow_cache:
                from probos.types import WorkflowCacheEntry
                from datetime import datetime, timezone

                for entry_dict in workflows:
                    key = entry_dict.get("pattern", "")
                    if not key:
                        continue
                    entry = WorkflowCacheEntry(
                        pattern=key,
                        dag_json=entry_dict.get("dag_json", "{}"),
                        hit_count=entry_dict.get("hit_count", 0),
                        last_hit=datetime.fromisoformat(entry_dict["last_hit"]) if "last_hit" in entry_dict else datetime.now(timezone.utc),
                        created_at=datetime.fromisoformat(entry_dict["created_at"]) if "created_at" in entry_dict else datetime.now(timezone.utc),
                    )
                    self.workflow_cache._cache[key] = entry
                restored.append(f"workflows({len(workflows)})")
        except Exception as e:
            logger.warning("Warm boot: workflow restore failed: %s", e)

        # 7. QA reports → restore _qa_reports dict
        try:
            qa_reports = await ks.load_qa_reports()
            if qa_reports:
                self._qa_reports.update(qa_reports)
                restored.append(f"qa({len(qa_reports)})")
        except Exception as e:
            logger.warning("Warm boot: QA report restore failed: %s", e)

        if restored:
            logger.info("Warm boot restored: %s", ", ".join(restored))
        else:
            logger.info("Warm boot: no artifacts to restore (clean repo)")

        # Semantic knowledge re-indexing from restored artifacts (AD-243)
        if self._semantic_layer and ks:
            try:
                counts = await self._semantic_layer.reindex_from_store(ks)
                logger.info("Semantic knowledge reindexed: %s", counts)
            except Exception as e:
                logger.warning("Semantic knowledge reindex failed: %s", e)

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
                    pass  # Never block on persistence failure
            # Auto-index QA report for semantic search (AD-243)
            if self._semantic_layer:
                try:
                    await self._semantic_layer.index_qa_report(
                        agent_type=record.agent_type,
                        verdict=report.verdict,
                        pass_rate=report.passed / report.total_tests if report.total_tests > 0 else 0.0,
                    )
                except Exception:
                    pass

            # Trust updates (AD-155)
            for agent_id_or_agent in pool.healthy_agents:
                aid = agent_id_or_agent if isinstance(agent_id_or_agent, str) else agent_id_or_agent.id
                for test in report.test_details:
                    weight = (
                        self.config.qa.trust_reward_weight
                        if test["passed"]
                        else self.config.qa.trust_penalty_weight
                    )
                    self.trust_network.record_outcome(
                        aid, success=test["passed"], weight=weight,
                    )

                    # Emit trust_update for HXI (AD-254)
                    self._emit_event("trust_update", {
                        "agent_id": aid,
                        "new_score": round(self.trust_network.get_score(aid), 4),
                        "success": test["passed"],
                    })

            # Episodic memory
            if self.episodic_memory:
                import uuid as _uuid
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
                        (a if isinstance(a, str) else a.id)
                        for a in pool.healthy_agents
                    ],
                    duration_ms=report.duration_ms,
                    embedding=[],
                )
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
                pass
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
