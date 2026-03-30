"""Phase 4: Cognitive services — self-mod, feedback, memory, knowledge (AD-517).

Initializes the self-modification pipeline, episodic memory, feedback
engine, knowledge store, warm boot, records store, and strategy advisor.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from probos.startup.results import CognitiveServicesResult
from probos.substrate.identity import generate_pool_ids
from probos.utils import format_duration

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.cognitive.workflow_cache import WorkflowCache
    from probos.cognitive.working_memory import WorkingMemoryManager
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.intent import IntentBus
    from probos.mesh.routing import HebbianRouter
    from probos.substrate.event_log import EventLog
    from probos.substrate.pool import ResourcePool
    from probos.substrate.registry import AgentRegistry
    from probos.substrate.spawner import AgentSpawner

logger = logging.getLogger(__name__)


async def init_cognitive_services(
    *,
    config: "SystemConfig",
    data_dir: Path,
    registry: "AgentRegistry",
    pools: dict[str, "ResourcePool"],
    llm_client: "BaseLLMClient",
    trust_network: "TrustNetwork",
    hebbian_router: "HebbianRouter",
    episodic_memory: Any,
    intent_bus: "IntentBus",
    working_memory: "WorkingMemoryManager",
    event_log: "EventLog",
    workflow_cache: "WorkflowCache",
    qa_reports: dict[str, Any],
    # Function references from runtime
    submit_intent_with_consensus_fn: Callable[..., Any],
    register_designed_agent_fn: Callable[..., Any],
    unregister_designed_agent_fn: Callable[..., Any],
    create_designed_pool_fn: Callable[..., Any],
    set_probationary_trust_fn: Callable[..., Any],
    add_skill_to_agents_fn: Callable[..., Any],
    create_pool_fn: Callable[..., Any],
) -> CognitiveServicesResult:
    """Initialize self-mod pipeline, feedback, memory, knowledge, and strategy."""
    logger.info("Startup [cognitive_services]: starting")

    self_mod_pipeline = None
    behavioral_monitor = None
    system_qa = None

    # Start self-modification pipeline if enabled
    if config.self_mod.enabled:
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.code_validator import CodeValidator
        from probos.cognitive.dependency_resolver import DependencyResolver
        from probos.cognitive.sandbox import SandboxRunner
        from probos.cognitive.behavioral_monitor import BehavioralMonitor
        from probos.cognitive.self_mod import SelfModificationPipeline
        from probos.cognitive.skill_designer import SkillDesigner
        from probos.cognitive.skill_validator import SkillValidator

        designer = AgentDesigner(llm_client, config.self_mod)
        validator = CodeValidator(config.self_mod)
        sandbox = SandboxRunner(config.self_mod, llm_client=llm_client)
        behavioral_monitor = BehavioralMonitor()
        skill_designer = SkillDesigner(llm_client, config.self_mod)
        skill_validator = SkillValidator(config.self_mod)
        dependency_resolver = DependencyResolver(
            allowed_imports=config.self_mod.allowed_imports,
        )

        # Optional research phase
        research = None
        if config.self_mod.research_enabled:
            from probos.cognitive.research import ResearchPhase

            research = ResearchPhase(
                llm_client=llm_client,
                submit_intent_fn=submit_intent_with_consensus_fn,
                config=config.self_mod,
            )

        self_mod_pipeline = SelfModificationPipeline(
            designer=designer,
            validator=validator,
            sandbox=sandbox,
            monitor=behavioral_monitor,
            config=config.self_mod,
            register_fn=register_designed_agent_fn,
            unregister_fn=unregister_designed_agent_fn,
            create_pool_fn=create_designed_pool_fn,
            set_trust_fn=set_probationary_trust_fn,
            user_approval_fn=None,  # Shell sets this after creation
            skill_designer=skill_designer,
            skill_validator=skill_validator,
            add_skill_fn=add_skill_to_agents_fn,
            research=research,
            dependency_resolver=dependency_resolver,
            event_log=event_log,
        )
        logger.info("Self-modification pipeline enabled")

        # Spawn skills pool for SkillBasedAgent
        ids = generate_pool_ids("skill_agent", "skills", 2)
        await create_pool_fn(
            "skills", "skill_agent", target_size=2,
            agent_ids=ids,
            llm_client=llm_client,
        )

        # Spawn SystemQA pool if QA enabled (AD-153: single agent)
        if config.qa.enabled:
            ids = generate_pool_ids("system_qa", "system_qa", 1)
            await create_pool_fn("system_qa", "system_qa", target_size=1, agent_ids=ids)
            qa_pool = pools.get("system_qa")
            if qa_pool and qa_pool.healthy_agents:
                agents = list(qa_pool.healthy_agents)
                if isinstance(agents[0], str):
                    system_qa = registry.get(agents[0])
                else:
                    system_qa = agents[0]

    # Start episodic memory if provided
    if episodic_memory:
        await episodic_memory.start()

    # Create FeedbackEngine (AD-219)
    from probos.cognitive.feedback import FeedbackEngine

    feedback_engine = FeedbackEngine(
        trust_network=trust_network,
        hebbian_router=hebbian_router,
        episodic_memory=episodic_memory,
        event_log=event_log,
    )

    # Create CorrectionDetector + AgentPatcher (AD-229, AD-230)
    from probos.cognitive.correction_detector import CorrectionDetector
    from probos.cognitive.agent_patcher import AgentPatcher

    correction_detector = CorrectionDetector(llm_client=llm_client)
    agent_patcher = None
    if self_mod_pipeline:
        agent_patcher = AgentPatcher(
            llm_client=llm_client,
            code_validator=self_mod_pipeline._validator,
            sandbox=self_mod_pipeline._sandbox,
        )

    # Initialize knowledge store (AD-159) and warm boot (AD-162)
    knowledge_store = None
    warm_boot_service = None
    if config.knowledge.enabled:
        try:
            from probos.knowledge.store import KnowledgeStore

            # If no explicit repo_path, use data_dir/knowledge (AD-159)
            kcfg = config.knowledge
            if not kcfg.repo_path:
                kcfg = kcfg.model_copy(update={"repo_path": str(data_dir / "knowledge")})

            knowledge_store = KnowledgeStore(kcfg)
            await knowledge_store.initialize()

            if config.knowledge.restore_on_boot:
                from probos.warm_boot import WarmBootService

                warm_boot_service = WarmBootService(
                    knowledge_store=knowledge_store,
                    trust_network=trust_network,
                    hebbian_router=hebbian_router,
                    episodic_memory=episodic_memory,
                    workflow_cache=workflow_cache,
                    config=config,
                    register_designed_agent_fn=register_designed_agent_fn,
                    create_designed_pool_fn=create_designed_pool_fn,
                    add_skill_to_agents_fn=add_skill_to_agents_fn,
                    qa_reports=qa_reports,
                    pools=pools,
                    semantic_layer=None,  # created later in structural_services phase
                )
                await warm_boot_service.restore()

            logger.info("Knowledge store initialized: %s", knowledge_store.repo_path)
        except Exception as e:
            logger.warning("Knowledge store initialization failed: %s — continuing without persistence", e)
            knowledge_store = None

    # AD-502: Detect lifecycle state — stasis vs first boot
    # BF-065: Use data_dir directly (not knowledge_store) so detection
    # works even if knowledge store is disabled or fails to initialize.
    # BF-070: Removed trust.db heuristic — runtime creates trust.db during
    # initialization before this check runs, so it was always true after a
    # reset, misclassifying first_boot as "restart".
    lifecycle_state = "first_boot"
    stasis_duration = 0.0
    previous_session = None
    try:
        session_path = data_dir / "session_last.json"
        if session_path.exists():
            previous_session = json.loads(session_path.read_text())
            stasis_duration = time.time() - previous_session["shutdown_time_utc"]
            lifecycle_state = "stasis_recovery"
            logger.info("AD-502: Stasis recovery detected — stasis duration: %s", format_duration(stasis_duration))
        else:
            logger.info("AD-502: No session record — first boot (maiden voyage)")
    except Exception:
        logger.warning("Failed to load session record for lifecycle detection", exc_info=True)

    # Initialize Ship's Records (AD-434)
    records_store = None
    if config.records.enabled:
        try:
            from probos.knowledge.records_store import RecordsStore

            rcfg = config.records
            if not rcfg.repo_path:
                rcfg = rcfg.model_copy(update={"repo_path": str(data_dir / "ship-records")})
            records_store = RecordsStore(rcfg, ontology=None)
            await records_store.initialize()
            logger.info("ship-records started")
        except Exception as e:
            logger.warning("Ship's Records failed to start: %s — continuing without records", e)
            records_store = None

    # Wire StrategyAdvisor (AD-384) if knowledge store is available
    strategy_advisor = None
    if knowledge_store:
        from probos.cognitive.strategy_advisor import StrategyAdvisor

        strategies_dir = knowledge_store.repo_path / "strategies"
        strategies_dir.mkdir(exist_ok=True)
        strategy_advisor = StrategyAdvisor(
            strategies_dir=strategies_dir,
            hebbian_router=hebbian_router,
        )

    logger.info("Startup [cognitive_services]: complete")
    return CognitiveServicesResult(
        self_mod_pipeline=self_mod_pipeline,
        behavioral_monitor=behavioral_monitor,
        system_qa=system_qa,
        feedback_engine=feedback_engine,
        correction_detector=correction_detector,
        agent_patcher=agent_patcher,
        knowledge_store=knowledge_store,
        warm_boot_service=warm_boot_service,
        records_store=records_store,
        strategy_advisor=strategy_advisor,
        cold_start=False,  # determined later in dreaming phase
        fresh_boot=False,
        lifecycle_state=lifecycle_state,
        stasis_duration=stasis_duration,
        previous_session=previous_session,
        semantic_layer=None,  # created in structural_services phase
    )
