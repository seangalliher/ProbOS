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
from probos.cognitive.attention import AttentionManager
from probos.cognitive.decomposer import DAGExecutor, IntentDecomposer
from probos.cognitive.dreaming import DreamingEngine, DreamScheduler
from probos.cognitive.llm_client import BaseLLMClient, MockLLMClient, OpenAICompatibleClient
from probos.cognitive.working_memory import WorkingMemoryManager
from probos.cognitive.workflow_cache import WorkflowCache
from probos.config import SystemConfig, load_config
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
from probos.substrate.registry import AgentRegistry
from probos.substrate.scaler import PoolScaler
from probos.substrate.spawner import AgentSpawner
from probos.types import (
    ConsensusOutcome,
    Episode,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
    NodeSelfModel,
    QuorumPolicy,
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

        # --- Mesh ---
        self.signal_manager = SignalManager(reap_interval=1.0)
        self.intent_bus = IntentBus(self.signal_manager)
        self.capability_registry = CapabilityRegistry()
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

        # --- Pool scaling ---
        self.pool_scaler: PoolScaler | None = None

        # --- Federation ---
        self.federation_bridge: Any = None  # FederationBridge | None
        self._federation_transport: Any = None
        self._start_time: float = time.monotonic()

        # --- Self-modification ---
        self.self_mod_pipeline: Any = None  # SelfModificationPipeline | None
        self.behavioral_monitor: Any = None  # BehavioralMonitor | None

        # --- Execution history (for introspection) ---
        self._last_execution: dict[str, Any] | None = None
        self._previous_execution: dict[str, Any] | None = None

        self._started = False

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

    def register_agent_type(self, type_name: str, agent_class: type) -> None:
        """Register an agent class and refresh the decomposer's intent descriptors."""
        self.spawner.register_template(type_name, agent_class)
        if self.decomposer:
            self.decomposer.refresh_descriptors(self._collect_intent_descriptors())

    async def create_pool(
        self,
        name: str,
        agent_type: str,
        target_size: int | None = None,
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
        for _ in range(count):
            agent = RedTeamAgent(pool="red_team")
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

        # Start default pools
        await self.create_pool("system", "system_heartbeat", target_size=2)
        await self.create_pool("filesystem", "file_reader", target_size=3)
        await self.create_pool("filesystem_writers", "file_writer", target_size=3)
        await self.create_pool("directory", "directory_list", target_size=3)
        await self.create_pool("search", "file_search", target_size=3)
        await self.create_pool("shell", "shell_command", target_size=3)
        await self.create_pool("http", "http_fetch", target_size=3)
        await self.create_pool("introspect", "introspect", target_size=2, runtime=self)

        # Refresh decomposer with intent descriptors from all registered templates
        self.decomposer.refresh_descriptors(self._collect_intent_descriptors())

        # Spawn red team agents
        await self._spawn_red_team(self.config.consensus.red_team_pool_size)

        # Start pool scaler if scaling is enabled
        if self.config.scaling.enabled:
            pool_intent_map = self._build_pool_intent_map()
            self.pool_scaler = PoolScaler(
                pools=self.pools,
                intent_bus=self.intent_bus,
                pool_config=self.config.pools,
                scaling_config=self.config.scaling,
                pool_intent_map=pool_intent_map,
                excluded_pools={"system"},
                trust_network=self.trust_network,
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
            from probos.cognitive.sandbox import SandboxRunner
            from probos.cognitive.behavioral_monitor import BehavioralMonitor
            from probos.cognitive.self_mod import SelfModificationPipeline

            designer = AgentDesigner(self.llm_client, self.config.self_mod)
            validator = CodeValidator(self.config.self_mod)
            sandbox = SandboxRunner(self.config.self_mod)
            self.behavioral_monitor = BehavioralMonitor()

            self.self_mod_pipeline = SelfModificationPipeline(
                designer=designer,
                validator=validator,
                sandbox=sandbox,
                monitor=self.behavioral_monitor,
                config=self.config.self_mod,
                register_fn=self._register_designed_agent,
                create_pool_fn=self._create_designed_pool,
                set_trust_fn=self._set_probationary_trust,
                user_approval_fn=None,  # Shell sets this after creation
            )
            logger.info("Self-modification pipeline enabled")

        # Start episodic memory if provided
        if self.episodic_memory:
            await self.episodic_memory.start()

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
        await self.event_log.log(category="system", event="stopping")

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

        # Stop mesh and consensus services
        await self.gossip.stop()
        await self.signal_manager.stop()
        await self.hebbian_router.stop()
        await self.trust_network.stop()
        await self.event_log.log(category="system", event="stopped")
        await self.event_log.stop()

        # Clean up LLM client
        await self.llm_client.close()

        # Stop dreaming scheduler
        if self.dream_scheduler:
            await self.dream_scheduler.stop()
            self.dream_scheduler = None

        # Stop episodic memory
        if self.episodic_memory:
            await self.episodic_memory.stop()

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

        # Step 2: Evaluate quorum
        consensus = self.quorum_engine.evaluate(results, policy=policy)

        await self.event_log.log(
            category="consensus",
            event="quorum_evaluated",
            detail=(
                f"intent={intent} id={msg.id[:8]} outcome={consensus.outcome.value} "
                f"approval={consensus.approval_ratio:.3f}"
            ),
        )

        # Step 3: Red team verification (verify a sample of results)
        verification_results = []
        if results and self._red_team_agents:
            verification_timeout = self.config.consensus.verification_timeout_seconds
            for result in results:
                if not result.success:
                    continue  # Only verify successful results
                # Pick a red team agent to verify
                for rt_agent in self._red_team_agents:
                    try:
                        vr = await asyncio.wait_for(
                            rt_agent.verify(result.agent_id, msg, result),
                            timeout=verification_timeout,
                        )
                        verification_results.append(vr)

                        # Step 4: Update trust network
                        self.trust_network.record_outcome(
                            result.agent_id,
                            success=vr.verified,
                        )

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

    async def process_natural_language(
        self,
        text: str,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Process a natural language request through the full cognitive pipeline.

        Pipeline: NL input → working memory assembly → LLM decomposition →
        DAG execution via mesh + consensus → aggregated results.

        If on_event is provided, it is called at key pipeline stages:
        decompose_start, decompose_complete, node_start, node_complete, node_failed.
        """
        t_start = time.monotonic()

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

        dag = await self.decomposer.decompose(
            text, context=context, similar_episodes=similar_episodes or None,
        )

        if on_event:
            await on_event("decompose_complete", {"dag": dag})

        if not dag.nodes:
            # Self-modification: try to design an agent for this unhandled intent
            # Trigger even if dag.response is set — a conversational "I can't do that"
            # response with no actual intents still means no agent handled it.
            self_mod_result = None
            if self.self_mod_pipeline:
                intent_meta = await self._extract_unhandled_intent(text)
                if intent_meta:
                    record = await self.self_mod_pipeline.handle_unhandled_intent(
                        intent_name=intent_meta["name"],
                        intent_description=intent_meta["description"],
                        parameters=intent_meta.get("parameters", {}),
                        requires_consensus=intent_meta.get("requires_consensus", False),
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
                    elif record:
                        self_mod_result = {
                            "status": record.status,
                            "intent": intent_meta["name"],
                        }
                    else:
                        self_mod_result = {
                            "status": "failed",
                            "intent": intent_meta["name"],
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
                return result

        # Record intents in working memory
        for node in dag.nodes:
            self.working_memory.record_intent(node.intent, node.params)

        # 3. Execute DAG through mesh + consensus
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
                execution_result["reflection"] = (
                    "(Reflection unavailable — results shown above)"
                )

        # Step 6: Store episode in episodic memory (fire-and-forget)
        if self.episodic_memory and dag.nodes:
            try:
                t_end = time.monotonic()
                episode = self._build_episode(text, execution_result, t_start, t_end)
                await self.episodic_memory.store(episode)
            except Exception as e:
                logger.warning("Episode storage failed: %s: %s", type(e).__name__, e)

        # Step 7: Store successful workflows in cache
        if self.workflow_cache and dag.nodes:
            all_success = all(n.status == "completed" for n in dag.nodes)
            if all_success:
                self.workflow_cache.store(text, dag)

        # Store execution result for introspection
        self._last_execution = execution_result

        return execution_result

    def status(self) -> dict[str, Any]:
        """Return a snapshot of the full system state."""
        result = {
            "system": self.config.system.model_dump(),
            "started": self._started,
            "total_agents": self.registry.count,
            "pools": {name: pool.info() for name, pool in self.pools.items()},
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
        return result

    async def recall_similar(self, query: str, k: int = 5) -> list[Episode]:
        """Recall similar past episodes from episodic memory."""
        if not self.episodic_memory:
            return []
        return await self.episodic_memory.recall(query, k=k)

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
                            if hasattr(r, "agent_id"):
                                agent_ids.append(r.agent_id)
                outcomes.append(outcome)

        reflection = execution_result.get("reflection")

        return Episode(
            timestamp=time.time(),
            user_input=text,
            dag_summary=dag_summary,
            outcomes=outcomes,
            reflection=reflection if isinstance(reflection, str) else None,
            agent_ids=agent_ids,
            duration_ms=(t_end - t_start) * 1000,
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
        consensus_intents = {"write_file", "run_command", "http_fetch"}
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
            self.intent_bus.subscribe(agent.id, agent.handle_intent)

        # Initialize trust record
        self.trust_network.get_or_create(agent.id)

        await self.event_log.log(
            category="lifecycle",
            event="agent_wired",
            agent_id=agent.id,
            agent_type=agent.agent_type,
            pool=agent.pool,
        )

    def _collect_intent_descriptors(self) -> list[IntentDescriptor]:
        """Collect unique intent descriptors from all registered agent templates."""
        seen: set[str] = set()
        descriptors: list[IntentDescriptor] = []
        for agent_class in self.spawner._templates.values():
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

    # ------------------------------------------------------------------
    # Self-modification helpers
    # ------------------------------------------------------------------

    async def _register_designed_agent(self, agent_class: type) -> None:
        """Register a self-designed agent class. Wraps register_agent_type()."""
        agent_type = getattr(agent_class, "agent_type", "unknown")
        self.register_agent_type(agent_type, agent_class)

    async def _create_designed_pool(self, agent_type: str, pool_name: str, size: int = 2) -> None:
        """Create a pool for a self-designed agent type."""
        await self.create_pool(pool_name, agent_type, target_size=size)

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

    async def _extract_unhandled_intent(self, text: str) -> dict[str, Any] | None:
        """Use LLM to extract intent metadata from an unhandled request."""
        import json as _json

        existing = [d.name for d in self._collect_intent_descriptors()]

        prompt = (
            'The user asked ProbOS to do something, but no existing agent can handle it.\n'
            f'User request: "{text}"\n\n'
            'Extract what kind of agent would be needed. Respond with ONLY a JSON object:\n'
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
        request = LLMRequest(prompt=prompt, tier="fast")
        response = await self.llm_client.complete(request)

        if not response.content or response.error:
            return None

        try:
            data = _json.loads(response.content)
            if "name" in data and "description" in data:
                return data
        except (_json.JSONDecodeError, TypeError):
            pass
        return None
