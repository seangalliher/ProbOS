"""Phase 4: Cognitive services — self-mod, feedback, memory, knowledge (AD-517).

Initializes the self-modification pipeline, episodic memory, feedback
engine, knowledge store, warm boot, records store, and strategy advisor.
"""

from __future__ import annotations

import asyncio
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


async def _run_one_migration(
    label: str,
    coro_factory: Callable[[], Any],
    timeout_s: float,
    success_template: str,
    noop_template: str,
    *,
    schema_store: Any | None = None,   # AD-818
    migration_id: str | None = None,   # AD-818
    version_hash: str | None = None,   # AD-818
) -> None:
    """BF-295 (#748): wrap a single episodic-memory migration with start log,
    timeout, elapsed-time logging, and honest-degrade on failure.

    `coro_factory` is a zero-arg callable returning a fresh awaitable each call
    (so the helper does not consume an already-awaited coroutine).
    `success_template` is a printf-style format string consuming
    (migrated_count: int, elapsed_seconds: float).
    `noop_template` consumes (elapsed_seconds: float) and is logged when the
    migration completes successfully but reports zero migrated episodes.

    On `asyncio.TimeoutError`: WARNING + return (non-fatal).
    On any other exception: WARNING with `exc_info=True` + return (non-fatal).

    AD-818 (#751): when `schema_store`, `migration_id`, and `version_hash` are
    all set, skip the migration entirely (no scan) if the recorded schema
    version matches, and record the version on clean success (NOT on timeout or
    exception — a migration that does not complete must retry next boot).
    """
    # AD-818: short-circuit — recorded schema version matches → skip the scan.
    if schema_store is not None and migration_id is not None and version_hash is not None:
        if await schema_store.is_current(migration_id, version_hash):
            logger.info(
                "%s: schema current (version %s) — skipping scan",
                label,
                version_hash,
            )
            return

    logger.info("%s: starting (timeout=%.0fs)", label, timeout_s)
    t0 = time.perf_counter()
    try:
        migrated = await asyncio.wait_for(coro_factory(), timeout=timeout_s)
        elapsed = time.perf_counter() - t0
        if migrated and migrated > 0:
            logger.info(success_template, migrated, elapsed)
        else:
            logger.info(noop_template, elapsed)
        # AD-818 R1: record-on-clean-success ONLY. This MUST be the final
        # statement inside the try — placing it after the try/except would
        # reference `migrated` (unbound on timeout) → UnboundLocalError boot
        # crash, and would falsely mark a timed-out migration as current.
        if schema_store is not None and migration_id is not None and version_hash is not None:
            await schema_store.record(
                migration_id,
                episode_count=int(migrated or 0),
                version_hash=version_hash,
            )
    except asyncio.TimeoutError:
        logger.warning(
            "%s: timed out after %.0fs — proceeding with degraded state",
            label,
            timeout_s,
        )
    except Exception:
        logger.warning("%s: failed (non-fatal)", label, exc_info=True)


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
    register_tool_fn: Callable[..., Any] | None = None,  # AD-886: Skill -> ToolRegistry
    create_pool_fn: Callable[..., Any],
    emit_event_fn: Callable[..., Any] | None = None,
    ontology: Any = None,  # BF-118: for OrientationService
) -> CognitiveServicesResult:
    """Initialize self-mod pipeline, feedback, memory, knowledge, and strategy."""
    logger.info("Startup [cognitive_services]: starting")

    self_mod_pipeline = None
    behavioral_monitor = None
    system_qa = None

    # AD-838c: Construct a DependencyResolver for the task path (runtime dynamic
    # install) and/or the self-mod pipeline. A single shared instance is used
    # when both are enabled so approval wiring and policy stay consistent.
    dependency_resolver = None
    dep_cfg = config.dependency
    if config.self_mod.enabled or dep_cfg.dynamic_install_enabled:
        from probos.cognitive.dependency_resolver import DependencyResolver

        if dep_cfg.dynamic_install_enabled:
            dependency_resolver = DependencyResolver(
                allowed_imports=config.self_mod.allowed_imports,
                policy=dep_cfg.dynamic_install_policy,
                deny_imports=dep_cfg.dynamic_install_deny,
            )
        else:
            dependency_resolver = DependencyResolver(
                allowed_imports=config.self_mod.allowed_imports,
            )

    # Start self-modification pipeline if enabled
    if config.self_mod.enabled:
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.code_validator import CodeValidator
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
            register_tool_fn=register_tool_fn,
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

    # AD-608: Retroactive evolver for episodic memory
    if episodic_memory and config.retroactive.enabled:
        try:
            from probos.cognitive.retroactive_evolver import RetroactiveEvolver as _RetroactiveEvolver

            retroactive_evolver = _RetroactiveEvolver(
                config=config.retroactive,
                episodic_memory=episodic_memory,
            )
            episodic_memory.set_retroactive_evolver(retroactive_evolver)
            logger.info("AD-608: RetroactiveEvolver initialized and wired to EpisodicMemory")
        except Exception as exc:
            logger.warning(
                "AD-608: RetroactiveEvolver failed to start: %s; continuing without store-time evolution",
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

    # BF-295 (#748): each episodic-memory migration below logs start +
    # elapsed time AND runs under asyncio.wait_for. Timeout sourced from
    # config.memory.migration_timeout_s (default 300s) so the operator
    # can raise it for large stores (AD-605 enriched re-embed on a 10k+
    # store can legitimately need several minutes on CPU). Honest-degrade
    # to WARNING on timeout; boot continues.
    _migration_timeout_s = float(config.memory.migration_timeout_s)

    # Operator escape hatch (BF-2026-05-22): some migrations load the
    # entire ChromaDB collection into Python memory at once, which can
    # OOM on large stores. Setting PROBOS_SKIP_EPISODIC_MIGRATIONS=1
    # boots the runtime without running them; the operator can then
    # invoke them as a separate maintenance step when ready.
    import os as _os_for_skip
    _skip_migrations = _os_for_skip.environ.get(
        "PROBOS_SKIP_EPISODIC_MIGRATIONS", ""
    ).strip() in {"1", "true", "yes"}
    if _skip_migrations:
        logger.warning(
            "PROBOS_SKIP_EPISODIC_MIGRATIONS set; skipping episodic-memory "
            "migrations (BF-103, AD-570, AD-570b, AD-584, AD-605). Run "
            "them as maintenance when ready."
        )

    # AD-818 (#751): schema-version sidecar. When enabled, records which
    # migration ran at which version so subsequent boots can skip a migration's
    # full-collection scan when its recorded version matches. Guarded: a
    # build/start failure leaves schema_store=None so every migration runs
    # unversioned exactly as today.
    schema_store = None
    if episodic_memory and not _skip_migrations and config.memory.schema_version_tracking:
        try:
            from probos.cognitive.schema_versions import SchemaVersionStore
            schema_store = SchemaVersionStore(db_path=str(data_dir / "schema_versions.db"))
            await schema_store.start()
            logger.info("AD-818: schema-version store started")
        except Exception:
            logger.warning(
                "AD-818: schema-version store start failed (non-fatal); "
                "migrations will run unversioned",
                exc_info=True,
            )
            schema_store = None

    # BF-103: Migrate episode agent_ids from slot IDs to sovereign IDs
    if episodic_memory and identity_registry and not _skip_migrations:
        from probos.cognitive.episodic import migrate_episode_agent_ids
        from probos.cognitive.schema_versions import MIGRATION_VERSIONS
        await _run_one_migration(
            "BF-103",
            lambda: migrate_episode_agent_ids(episodic_memory, identity_registry),
            _migration_timeout_s,
            "BF-103: Migrated %d episodes to sovereign IDs in %.1fs",
            "BF-103: episode agent_id migration completed in %.1fs (no episodes needed migration)",
            schema_store=schema_store,
            migration_id="BF-103",
            version_hash=MIGRATION_VERSIONS["BF-103"],
        )

    # AD-570: Promote anchor fields to top-level ChromaDB metadata
    if episodic_memory and not _skip_migrations:
        from probos.cognitive.episodic import migrate_anchor_metadata
        from probos.cognitive.schema_versions import MIGRATION_VERSIONS
        await _run_one_migration(
            "AD-570",
            lambda: migrate_anchor_metadata(episodic_memory),
            _migration_timeout_s,
            "AD-570: Promoted anchor metadata for %d episodes in %.1fs",
            "AD-570: anchor metadata migration completed in %.1fs (no episodes needed migration)",
            schema_store=schema_store,
            migration_id="AD-570",
            version_hash=MIGRATION_VERSIONS["AD-570"],
        )

    # AD-570b: Create and wire participant index
    if episodic_memory and not _skip_migrations:
        try:
            from probos.cognitive.participant_index import ParticipantIndex

            participant_index = ParticipantIndex(
                db_path=str(data_dir / "participant_index.db"),
            )
            await participant_index.start()
            episodic_memory.set_participant_index(participant_index)
            logger.info("AD-570b: Participant index started")
        except Exception:
            logger.warning("AD-570b: Participant index start failed (non-fatal)", exc_info=True)
        else:
            # One-time migration: backfill from existing episodes
            from probos.cognitive.episodic import migrate_participant_index
            from probos.cognitive.schema_versions import MIGRATION_VERSIONS
            await _run_one_migration(
                "AD-570b",
                lambda: migrate_participant_index(episodic_memory),
                _migration_timeout_s,
                "AD-570b: Indexed participants for %d episodes in %.1fs",
                "AD-570b: participant index backfill completed in %.1fs (no episodes needed migration)",
                schema_store=schema_store,
                migration_id="AD-570b",
                version_hash=MIGRATION_VERSIONS["AD-570b"],
            )

    # AD-584: Embedding model migration (re-embed if model changed)
    if episodic_memory and not _skip_migrations:
        from probos.cognitive.episodic import migrate_embedding_model
        from probos.cognitive.schema_versions import MIGRATION_VERSIONS
        from probos.knowledge.embeddings import get_active_embedding_model_name
        _embedding_model_name = get_active_embedding_model_name()
        await _run_one_migration(
            "AD-584",
            lambda: migrate_embedding_model(episodic_memory, _embedding_model_name),
            _migration_timeout_s,
            "AD-584: Re-embedded %d episodes with new model in %.1fs",
            "AD-584: embedding model migration completed in %.1fs (no episodes needed migration)",
            schema_store=schema_store,
            migration_id="AD-584",
            version_hash=MIGRATION_VERSIONS["AD-584"],
        )

    # AD-605: Re-embed with enriched anchor metadata (AD-818a-2: async + paginated)
    if episodic_memory and not _skip_migrations:
        from probos.cognitive.episodic import migrate_enriched_embedding
        from probos.cognitive.schema_versions import MIGRATION_VERSIONS
        await _run_one_migration(
            "AD-605",
            lambda: migrate_enriched_embedding(episodic_memory),
            _migration_timeout_s,
            "AD-605: Re-embedded %d episodes with enriched anchor text in %.1fs",
            "AD-605: enriched embedding migration completed in %.1fs (no episodes needed migration)",
            schema_store=schema_store,
            migration_id="AD-605",
            version_hash=MIGRATION_VERSIONS["AD-605"],
        )

    # BF-207: Proactive hash integrity sweep — heal stale hashes from unclean shutdown.
    # Must run AFTER all other migrations (BF-103, AD-570, AD-584, AD-605) which
    # may legitimately change metadata that affects the content hash.
    # ⚠️ MUST be the last migration. New migrations go ABOVE this block.
    if episodic_memory and config.memory.verify_content_hash and not _skip_migrations:
        from probos.cognitive.episodic import sweep_hash_integrity
        await _run_one_migration(
            "BF-207",
            lambda: sweep_hash_integrity(episodic_memory),
            _migration_timeout_s,
            "BF-207: Healed %d hash mismatches in startup sweep in %.1fs",
            "BF-207: hash integrity sweep completed in %.1fs (0 mismatches)",
        )

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

    # AD-524: Ship's Archive — cross-reset knowledge persistence
    archive_store = None
    if config.archive.enabled:
        try:
            import os
            import sys

            from probos.knowledge.archive_store import ArchiveStore
            from probos.storage.sqlite_factory import default_factory

            archive_db_path = config.archive.db_path
            if not archive_db_path:
                if sys.platform == "win32":
                    archive_base = Path.home() / "AppData" / "Local" / "ProbOS" / "archive"
                elif sys.platform == "darwin":
                    archive_base = (
                        Path.home() / "Library" / "Application Support" / "ProbOS" / "archive"
                    )
                else:
                    xdg_data_home = os.environ.get("XDG_DATA_HOME")
                    archive_base = (
                        Path(xdg_data_home) / "ProbOS" / "archive"
                        if xdg_data_home
                        else Path.home() / ".local" / "share" / "ProbOS" / "archive"
                    )
                archive_base.mkdir(parents=True, exist_ok=True)
                archive_db_path = str(archive_base / "archive.db")

            archive_store = ArchiveStore(archive_db_path, connection_factory=default_factory)
            await archive_store.initialize()
            logger.info("AD-524: ArchiveStore initialized at %s", archive_db_path)
        except Exception as e:
            logger.warning(
                "AD-524: ArchiveStore failed to start at configured archive path; "
                "Oracle Tier 4 archive recall will be disabled and startup continues: %s",
                e,
            )
            archive_store = None

    # AD-462e: Oracle Service — cross-tier unified memory query
    oracle_service = None
    try:
        from probos.cognitive.oracle_service import OracleService
        oracle_service = OracleService(
            episodic_memory=episodic_memory,
            records_store=records_store,
            knowledge_store=knowledge_store,
            archive_store=archive_store,  # AD-524
            trust_network=trust_network,
            hebbian_router=hebbian_router,
            expertise_directory=expertise_directory,
            # AD-988: default-OFF retrieval-reason transparency gate.
            match_reason_enabled=getattr(
                config.memory, "oracle_match_reason_enabled", False,
            ),
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

    # AD-461: Ship's Telemetry
    telemetry_service = None
    if config.telemetry.enabled:
        try:
            from probos.substrate.telemetry import TelemetryService

            telemetry_service = TelemetryService(
                emit_fn=emit_event_fn,
                report_interval_seconds=config.telemetry.report_interval_seconds,
                max_samples_per_bucket=config.telemetry.max_samples_per_bucket,
            )
            logger.info("AD-461: TelemetryService initialized")
        except Exception as e:
            logger.warning(
                "TelemetryService failed to start: %s; operation timing disabled and startup continues",
                e,
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
        activation_tracker=activation_tracker,  # AD-567d
        social_verification=social_verification,  # AD-567f
        orientation_service=orientation_service,  # AD-567g
        oracle_service=oracle_service,  # AD-462e
        consultation_protocol=consultation_protocol,  # AD-594
        expertise_directory=expertise_directory,  # AD-600
        telemetry_service=telemetry_service,  # AD-461
        archive_store=archive_store,  # AD-524
        dependency_resolver=dependency_resolver,  # AD-838c
        schema_version_store=schema_store,  # AD-818
    )
