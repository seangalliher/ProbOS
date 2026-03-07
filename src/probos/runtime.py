"""ProbOS runtime — top-level orchestrator for substrate + mesh + consensus layers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from probos.agents.file_reader import FileReaderAgent
from probos.agents.file_writer import FileWriterAgent
from probos.agents.heartbeat_monitor import SystemHeartbeatAgent
from probos.agents.red_team import RedTeamAgent
from probos.cognitive.decomposer import DAGExecutor, IntentDecomposer
from probos.cognitive.llm_client import BaseLLMClient, MockLLMClient, OpenAICompatibleClient
from probos.cognitive.working_memory import WorkingMemoryManager
from probos.config import SystemConfig, load_config
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
from probos.substrate.spawner import AgentSpawner
from probos.types import (
    ConsensusOutcome,
    IntentMessage,
    IntentResult,
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
        self.decomposer = IntentDecomposer(
            llm_client=self.llm_client,
            working_memory=self.working_memory,
            timeout=cog_cfg.decomposition_timeout_seconds,
        )
        self.dag_executor = DAGExecutor(
            runtime=self,
            timeout=cog_cfg.dag_execution_timeout_seconds,
        )

        self._started = False

        # Register built-in agent templates
        self.spawner.register_template("system_heartbeat", SystemHeartbeatAgent)
        self.spawner.register_template("file_reader", FileReaderAgent)
        self.spawner.register_template("file_writer", FileWriterAgent)
        self.spawner.register_template("red_team", RedTeamAgent)

    def register_agent_type(self, type_name: str, agent_class: type) -> None:
        """Register an agent class so it can be spawned into pools."""
        self.spawner.register_template(type_name, agent_class)

    async def create_pool(
        self,
        name: str,
        agent_type: str,
        target_size: int | None = None,
    ) -> ResourcePool:
        """Create and start a resource pool."""
        pool = ResourcePool(
            name=name,
            agent_type=agent_type,
            spawner=self.spawner,
            registry=self.registry,
            config=self.config.pools,
            target_size=target_size,
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

        # Spawn red team agents
        await self._spawn_red_team(self.config.consensus.red_team_pool_size)

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

        # 2. Decompose NL → TaskDAG
        dag = await self.decomposer.decompose(text, context=context)

        if on_event:
            await on_event("decompose_complete", {"dag": dag})

        if not dag.nodes:
            logger.warning("No intents parsed from NL input: %s", text[:50])
            return {
                "input": text,
                "dag": dag,
                "results": {},
                "complete": True,
                "node_count": 0,
                "completed_count": 0,
                "failed_count": 0,
                "response": dag.response,
            }

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
        return execution_result

    def status(self) -> dict[str, Any]:
        """Return a snapshot of the full system state."""
        return {
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
            },
        }

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
