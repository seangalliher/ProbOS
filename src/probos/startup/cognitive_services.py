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
    from probos.cognitive.consultation import ConsultationProtocol
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
    identity_registry: Any = None,  # BF-103: for episode ID migration
    # Function references from runtime
    submit_intent_with_consensus_fn: Callable[..., Any],
    register_designed_agent_fn: Callable[..., Any],
    unregister_designed_agent_fn: Callable[..., Any],
    create_designed_pool_fn: Callable[..., Any],
    set_probationary_trust_fn: Callable[..., Any],
    add_skill_to_agents_fn: Callable[..., Any],
    create_pool_fn: Callable[..., Any],
    emit_event_fn: Callable[..., Any] | None = None,
    ontology: Any = None,  # BF-118: for OrientationService
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

    # AD-567d: Create and wire activation tracker
    activation_tracker = None
    if episodic_memory and config.dreaming.activation_enabled:
        try:
            from probos.cognitive.activation_tracker import ActivationTracker

            activation_tracker = ActivationTracker(
                decay_d=config.dreaming.activation_decay_d,
                access_max_age_days=config.dreaming.activation_access_max_age_days,
                db_path=str(data_dir / "activation_tracker.db"),
            )
            await activation_tracker.start()
            episodic_memory.set_activation_tracker(activation_tracker)
            logger.info("AD-567d: Activation tracker started")
        except Exception:
            logger.warning("AD-567d: Activation tracker start failed (non-fatal)", exc_info=True)
            activation_tracker = None

    # AD-610: Storage gate for episodic memory
    if episodic_memory and config.storage_gate.enabled:
        try:
            from probos.cognitive.storage_gate import StorageGate as _StorageGate

            storage_gate = _StorageGate(
                config=config.storage_gate,
                emit_event_fn=emit_event_fn,
            )
            episodic_memory.set_storage_gate(storage_gate)
            logger.info("AD-610: StorageGate initialized and wired to EpisodicMemory")
        except Exception as exc:
            logger.warning(
                "AD-610: StorageGate failed to start: %s; continuing without write-time storage gating",
                exc,
            )

    # AD-601: Wire Temporal Context Model
    if episodic_memory and config.memory.tcm_enabled:
        try:
            from probos.cognitive.temporal_context import TemporalContextModel, TCMConfig

            _tcm_config = TCMConfig(
                dimension=config.memory.tcm_dimension,
                drift_rate=config.memory.tcm_drift_rate,
                weight=config.memory.tcm_weight,
                fallback_watch_weight=config.memory.tcm_fallback_watch_weight,
            )
            _tcm = TemporalContextModel(config=_tcm_config)
            episodic_memory.set_tcm(_tcm)
            logger.info("AD-601: TCM wired (d=%d, rho=%.3f, w=%.2f)",
                         config.memory.tcm_dimension, config.memory.tcm_drift_rate,
                         config.memory.tcm_weight)
        except Exception:
            logger.warning("AD-601: TCM wiring failed (non-fatal)", exc_info=True)

    # AD-541f: Start eviction audit log
    eviction_audit = getattr(episodic_memory, "_eviction_audit", None) if episodic_memory else None
    if eviction_audit:
        try:
            await eviction_audit.start(db_path=str(data_dir / "eviction_audit.db"))
        except Exception:
            logger.warning("AD-541f: Eviction audit log start failed (non-fatal)", exc_info=True)

    # BF-103: Migrate episode agent_ids from slot IDs to sovereign IDs
    if episodic_memory and identity_registry:
        try:
            from probos.cognitive.episodic import migrate_episode_agent_ids
            migrated = await migrate_episode_agent_ids(episodic_memory, identity_registry)
            if migrated > 0:
                logger.info("BF-103: Migrated %d episodes to sovereign IDs", migrated)
        except Exception:
            logger.warning("BF-103: Episode ID migration failed (non-fatal)", exc_info=True)

    # AD-570: Promote anchor fields to top-level ChromaDB metadata
    if episodic_memory:
        try:
            from probos.cognitive.episodic import migrate_anchor_metadata
            migrated = await migrate_anchor_metadata(episodic_memory)
            if migrated > 0:
                logger.info("AD-570: Promoted anchor metadata for %d episodes", migrated)
        except Exception:
            logger.warning("AD-570: Anchor metadata migration failed (non-fatal)", exc_info=True)

    # AD-570b: Create and wire participant index
    if episodic_memory:
        try:
            from probos.cognitive.participant_index import ParticipantIndex

            participant_index = ParticipantIndex(
                db_path=str(data_dir / "participant_index.db"),
            )
            await participant_index.start()
            episodic_memory.set_participant_index(participant_index)
            logger.info("AD-570b: Participant index started")

            # One-time migration: backfill from existing episodes
            from probos.cognitive.episodic import migrate_participant_index
            migrated = await migrate_participant_index(episodic_memory)
            if migrated > 0:
                logger.info("AD-570b: Indexed participants for %d episodes", migrated)
        except Exception:
            logger.warning("AD-570b: Participant index start failed (non-fatal)", exc_info=True)

    # AD-584: Embedding model migration (re-embed if model changed)
    if episodic_memory:
        try:
            from probos.cognitive.episodic import migrate_embedding_model
            from probos.knowledge.embeddings import get_embedding_model_name
            migrated = await migrate_embedding_model(episodic_memory, get_embedding_model_name())
            if migrated > 0:
                logger.info("AD-584: Re-embedded %d episodes with new model", migrated)
        except Exception:
            logger.warning("AD-584: Embedding model migration failed (non-fatal)", exc_info=True)

    # AD-605: Re-embed with enriched anchor metadata
    if episodic_memory:
        try:
            from probos.cognitive.episodic import migrate_enriched_embedding
            migrated = migrate_enriched_embedding(episodic_memory)
            if migrated > 0:
                logger.info("AD-605: Re-embedded %d episodes with enriched anchor text", migrated)
        except Exception:
            logger.warning("AD-605: Enriched embedding migration failed (non-fatal)", exc_info=True)

    # BF-207: Proactive hash integrity sweep — heal stale hashes from unclean shutdown.
    # Must run AFTER all other migrations (BF-103, AD-570, AD-584, AD-605) which
    # may legitimately change metadata that affects the content hash.
    # ⚠️ MUST be the last migration. New migrations go ABOVE this block.
    if episodic_memory and config.memory.verify_content_hash:
        try:
            from probos.cognitive.episodic import sweep_hash_integrity
            healed = await sweep_hash_integrity(episodic_memory)
            if healed > 0:
                logger.info("BF-207: Healed %d hash mismatches from previous shutdown", healed)
        except Exception:
            logger.warning("BF-207: Hash integrity sweep failed (non-fatal)", exc_info=True)

    # Create FeedbackEngine (AD-219)
    from probos.cognitive.feedback import FeedbackEngine

    feedback_engine = FeedbackEngine(
        trust_network=trust_network,
        hebbian_router=hebbian_router,
        episodic_memory=episodic_memory,
        event_log=event_log,
        identity_registry=identity_registry,
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
            # BF-084: Seed manuals from config/manuals/ into ship-records
            manuals_dir = Path(__file__).resolve().parent.parent.parent.parent / "config" / "manuals"
            seeded = await records_store.seed_manuals(manuals_dir)
            if seeded:
                logger.info("Seeded %d manual(s) into Ship's Records", seeded)
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

    # AD-567g: Cognitive Re-Localization
    orientation_service = None
    if config.orientation.enabled:
        try:
            from probos.cognitive.orientation import OrientationService
            orientation_service = OrientationService(config=config, ontology=ontology)
            logger.info("AD-567g: OrientationService initialized")
        except Exception as e:
            logger.warning("OrientationService failed to start: %s — continuing without", e)

    # AD-567f: Social Verification Protocol
    social_verification = None
    if config.social_verification.enabled:
        try:
            from probos.cognitive.social_verification import SocialVerificationService
            social_verification = SocialVerificationService(
                episodic_memory=episodic_memory,
                config=config.social_verification,
                emit_event_fn=emit_event_fn,
            )
            logger.info("AD-567f: SocialVerificationService initialized")
        except Exception as e:
            logger.warning("SocialVerificationService failed to start: %s — continuing without", e)

    # AD-600: Transactive Memory expertise directory
    expertise_directory = None
    if config.expertise.enabled:
        try:
            from probos.cognitive.expertise_directory import ExpertiseDirectory as _ExpertiseDirectory

            expertise_directory = _ExpertiseDirectory(config=config.expertise)
            logger.info("AD-600: ExpertiseDirectory initialized")
        except Exception as e:
            logger.warning("AD-600: ExpertiseDirectory failed to start: %s; continuing without", e)
            expertise_directory = None

    # AD-462e: Oracle Service — cross-tier unified memory query
    oracle_service = None
    try:
        from probos.cognitive.oracle_service import OracleService
        oracle_service = OracleService(
            episodic_memory=episodic_memory,
            records_store=records_store,
            knowledge_store=knowledge_store,
            trust_network=trust_network,
            hebbian_router=hebbian_router,
            expertise_directory=expertise_directory,
        )
        logger.info("AD-462e: OracleService initialized")
    except Exception as e:
        logger.warning("OracleService failed to start: %s — continuing without", e)

    # AD-594: Crew Consultation Protocol
    consultation_protocol: "ConsultationProtocol | None" = None
    if config.consultation.enabled:
        try:
            from probos.cognitive.consultation import ConsultationProtocol as _ConsultationProtocol

            consultation_protocol = _ConsultationProtocol(
                emit_event_fn=emit_event_fn,
                config=config.consultation,
            )
            logger.info("AD-594: ConsultationProtocol initialized")
        except Exception as e:
            logger.warning(
                "AD-594: ConsultationProtocol failed to start: %s; continuing without",
                e,
            )
            consultation_protocol = None

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
        activation_tracker=activation_tracker,  # AD-567d
        social_verification=social_verification,  # AD-567f
        orientation_service=orientation_service,  # AD-567g
        oracle_service=oracle_service,  # AD-462e
        consultation_protocol=consultation_protocol,  # AD-594
        expertise_directory=expertise_directory,  # AD-600
    )
