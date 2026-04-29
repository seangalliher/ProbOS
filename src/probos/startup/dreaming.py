"""Phase 5: Dreaming, detection, scheduling (AD-517).

Creates the dreaming engine + scheduler, emergent detector, detects
cold-start, starts the task scheduler, and creates the periodic flush
task.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable

from probos.cognitive.dreaming import DreamingEngine, DreamScheduler
from probos.cognitive.dream_wm_bridge import DreamWorkingMemoryBridge
from probos.cognitive.emergent_detector import EmergentDetector
from probos.cognitive.emergence_metrics import EmergenceMetricsEngine
from probos.cognitive.episodic_procedural_bridge import EpisodicProceduralBridge
from probos.cognitive.retrieval_practice import RetrievalPracticeEngine
from probos.cognitive.task_scheduler import TaskScheduler
from probos.events import EventType
from probos.knowledge.notebook_quality import NotebookQualityEngine
from probos.startup.results import DreamingResult

if TYPE_CHECKING:
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.routing import HebbianRouter
    from probos.substrate.scaler import PoolScaler

logger = logging.getLogger(__name__)


async def init_dreaming(
    *,
    config: "SystemConfig",
    trust_network: "TrustNetwork",
    hebbian_router: "HebbianRouter",
    episodic_memory: Any,
    pool_scaler: "PoolScaler | None",
    knowledge_store: Any,
    ward_room: Any,
    registry: Any,
    # Callback functions from runtime
    on_gap_predictions_fn: Callable[..., Any],
    on_contradictions_fn: Callable[..., Any],
    on_post_dream_fn: Callable[..., Any],
    on_pre_dream_fn: Callable[..., Any],
    on_post_micro_dream_fn: Callable[..., Any],
    process_natural_language_fn: Callable[..., Any],
    periodic_flush_loop_fn: Callable[[], Any],
    refresh_emergent_detector_roster_fn: Callable[[], None],
    emit_event_fn: Callable[..., Any] | None = None,  # AD-503
    llm_client: Any = None,  # AD-532: procedure extraction
    procedure_store: Any = None,  # AD-533: persistent procedure storage
    runtime: Any = None,  # AD-532e: for reactive event subscription
    activation_tracker: Any = None,  # AD-567d: activation-based lifecycle
    records_store: Any = None,  # BF-106: Ship's Records for notebook consolidation
) -> tuple[DreamingResult, bool]:
    """Start dreaming/detection subsystems and detect cold start.

    Returns a tuple of (DreamingResult, cold_start_flag).
    """
    logger.info("Startup [dreaming]: starting")

    # Start dreaming scheduler if episodic memory is available
    dream_scheduler = None
    dreaming_engine = None
    emergence_engine = EmergenceMetricsEngine(config.emergence_metrics)
    # AD-555: Notebook Quality Engine
    staleness_hours = 72.0
    if hasattr(config, 'records'):
        staleness_hours = getattr(config.records, 'notebook_staleness_hours', 72.0)
    notebook_quality_engine = NotebookQualityEngine(staleness_hours=staleness_hours)
    # AD-564: Quality-triggered consolidation
    from probos.knowledge.quality_trigger import QualityConsolidationTrigger
    quality_trigger = None
    if config.quality_trigger.enabled:
        quality_trigger = QualityConsolidationTrigger(
            config=config.quality_trigger,
            emit_event_fn=emit_event_fn,
        )
    # AD-565: Quality-informed routing
    from probos.knowledge.quality_router import QualityRouter
    quality_router = None
    if config.quality_router.enabled:
        quality_router = QualityRouter(
            config=config.quality_router,
            emit_event_fn=emit_event_fn,
        )
    # AD-444: Confidence Tracker
    from probos.knowledge.confidence_tracker import ConfidenceTracker
    confidence_tracker = None
    if config.confidence.enabled:
        confidence_tracker = ConfidenceTracker(config=config.confidence)
    # AD-563: Knowledge Linter
    from probos.knowledge.knowledge_linter import KnowledgeLinter
    knowledge_linter = None
    if config.lint.enabled and records_store:
        knowledge_linter = KnowledgeLinter(
            records_store=records_store,
            config=config.lint,
        )
    # AD-569: Behavioral Metrics Engine
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    behavioral_metrics_engine = BehavioralMetricsEngine(config.behavioral_metrics)
    # AD-671: Dream-Working Memory bridge
    dream_wm_bridge = None
    if config.dream_wm.enabled:
        dream_wm_bridge = DreamWorkingMemoryBridge(config=config.dream_wm)
    # AD-572: Episodic-procedural bridge
    procedural_bridge = None
    if config.procedural_bridge.enabled:
        procedural_bridge = EpisodicProceduralBridge(
            config=config.procedural_bridge,
            procedure_store=procedure_store,
            episodic_memory=episodic_memory,
        )
    # AD-541c: Spaced Retrieval Therapy
    retrieval_practice_engine = None
    retrieval_llm_client = None
    if config.dreaming.active_retrieval_enabled:
        data_dir = getattr(config, 'data_dir', '')
        retrieval_practice_engine = RetrievalPracticeEngine(
            success_threshold=config.dreaming.retrieval_success_threshold,
            partial_threshold=config.dreaming.retrieval_partial_threshold,
            initial_interval_hours=config.dreaming.retrieval_initial_interval_hours,
            max_interval_hours=config.dreaming.retrieval_max_interval_hours,
            episodes_per_cycle=config.dreaming.retrieval_episodes_per_cycle,
            counselor_failure_streak=config.dreaming.retrieval_counselor_failure_streak,
            data_dir=data_dir,
        )
        try:
            await retrieval_practice_engine.start()
        except Exception:
            logger.debug("AD-541c: Retrieval practice DB init failed", exc_info=True)
        retrieval_llm_client = llm_client  # Reuse the same LLM client (fast tier routed by LLMRequest)
    if episodic_memory:
        dream_cfg = config.dreaming
        dreaming_engine = DreamingEngine(
            router=hebbian_router,
            trust_network=trust_network,
            episodic_memory=episodic_memory,
            config=dream_cfg,
            idle_scale_down_fn=(
                pool_scaler.scale_down_idle
                if pool_scaler
                else None
            ),
            gap_prediction_fn=on_gap_predictions_fn,
            contradiction_resolve_fn=on_contradictions_fn,
            llm_client=llm_client,
            procedure_store=procedure_store,
            emergence_metrics_engine=emergence_engine,
            notebook_quality_engine=notebook_quality_engine,
            retrieval_practice_engine=retrieval_practice_engine,
            retrieval_llm_client=retrieval_llm_client,
            activation_tracker=activation_tracker,
            behavioral_metrics_engine=behavioral_metrics_engine,
            records_store=records_store,  # BF-106: constructor injection
            dream_wm_bridge=dream_wm_bridge,
            episodic_procedural_bridge=procedural_bridge,
        )
        dream_scheduler = DreamScheduler(
            engine=dreaming_engine,
            idle_threshold_seconds=dream_cfg.idle_threshold_seconds,
            dream_interval_seconds=dream_cfg.dream_interval_seconds,
        )
        dream_scheduler._emit_event_fn = emit_event_fn  # AD-503
        dream_scheduler.start()
        if confidence_tracker:
            dreaming_engine.set_confidence_tracker(confidence_tracker)
        if knowledge_linter:
            dreaming_engine.set_knowledge_linter(knowledge_linter)
        if quality_trigger:
            dreaming_engine.set_quality_trigger(quality_trigger)
        if quality_router:
            dreaming_engine.set_quality_router(quality_router)

    if confidence_tracker and records_store:
        records_store.set_confidence_tracker(confidence_tracker)

    # Create EmergentDetector (AD-237) — unconditional, pure observer
    _edc = config.emergent_detector  # BF-124
    emergent_detector = EmergentDetector(
        hebbian_router=hebbian_router,
        trust_network=trust_network,
        episodic_memory=episodic_memory,
        cluster_edge_threshold=_edc.cluster_edge_threshold,
        cluster_min_size=_edc.cluster_min_size,
        cluster_min_avg_weight=_edc.cluster_min_avg_weight,
        cluster_cooldown_seconds=_edc.cluster_cooldown_seconds,
        cluster_activity_window=_edc.cluster_activity_window,
        dream_min_history=_edc.dream_min_history,
        dream_anomaly_min_strengthened=_edc.dream_anomaly_min_strengthened,
        dream_anomaly_min_pruned=_edc.dream_anomaly_min_pruned,
        dream_anomaly_min_trust_adj=_edc.dream_anomaly_min_trust_adj,
        # AD-556: Per-agent adaptive trust anomaly detection
        adaptive_window_size=_edc.adaptive_window_size,
        adaptive_z_threshold=_edc.adaptive_z_threshold,
        adaptive_debounce_count=_edc.adaptive_debounce_count,
        adaptive_min_history=_edc.adaptive_min_history,
    )
    # Provide live agent roster so detector filters out defunct agents
    refresh_emergent_detector_roster_fn()

    # BF-034: Detect cold start (post-reset boot with empty state)
    # BF-069: Don't gate on _knowledge_store — cold start detection must work
    # even if knowledge store is disabled or fails to initialize.
    cold_start = False
    if emergent_detector:
        trust_records = trust_network.raw_scores()
        all_at_prior = all(
            abs(r["alpha"] - config.consensus.trust_prior_alpha) < 0.01
            and abs(r["beta"] - config.consensus.trust_prior_beta) < 0.01
            for r in trust_records.values()
        ) if trust_records else True
        episodes_empty = not episodic_memory
        if all_at_prior and episodes_empty:
            cold_start = True
            emergent_detector.set_cold_start_suppression(300)  # 5 minutes
            logger.info("BF-034: Cold start detected — suppressing trust anomalies for 5 minutes")
        elif runtime and getattr(runtime, '_lifecycle_state', None) == 'stasis_recovery':
            # BF-178: Stasis recovery is not a cold start (trust/memory preserved),
            # but dream history is stale. Clear it so dream_min_history gate re-applies
            # and apply a short suppression window for the first dream cycle.
            emergent_detector.clear_dream_history()
            emergent_detector.set_cold_start_suppression(60)  # 1 minute
            logger.info("BF-178: Stasis recovery — cleared stale dream history, suppressing anomalies for 60s")

    # BF-034: Announce fresh start to crew
    if cold_start and ward_room:
        async def _announce_cold_start():
            try:
                channels = await ward_room.list_channels()
                all_hands = next((c for c in channels if c.channel_type == "ship"), None)
                if all_hands:
                    await ward_room.create_thread(
                        channel_id=all_hands.id,
                        author_id="system",
                        title="Fresh Start — System Reset",
                        body=(
                            "This instance has been reset. All crew are being created fresh "
                            "through the Construct. All trust scores are at baseline (0.5) — "
                            "this is normal initialization, not a demotion. Trust will be rebuilt "
                            "through demonstrated competence. Episodic memory has been cleared. "
                            "Previous experiences are not available."
                        ),
                        author_callsign="Ship's Computer",
                        thread_mode="announce",
                        max_responders=0,
                    )
            except Exception:
                logger.debug("Cold-start announcement failed", exc_info=True)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_announce_cold_start())
        except RuntimeError:
            pass

    # AD-638: Activate boot camp for cold-start crew
    if cold_start and runtime and hasattr(runtime, 'boot_camp') and runtime.boot_camp:
        from probos.cognitive.standing_orders import get_department
        crew_agents = []
        for a in runtime.registry.all():
            if getattr(a, 'tier', '') in ("crew", "domain"):
                crew_agents.append({
                    "agent_id": a.id,
                    "callsign": getattr(a, 'callsign', '') or a.agent_type,
                    "department": getattr(a, 'department', '') or get_department(a.agent_type) or "unassigned",
                })
        if crew_agents:
            async def _activate_boot_camp():
                try:
                    await runtime.boot_camp.activate(crew_agents)
                    logger.info("AD-638: Boot camp activated for %d crew agents", len(crew_agents))
                except Exception:
                    logger.debug("AD-638: Boot camp activation failed", exc_info=True)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_activate_boot_camp())
            except RuntimeError:
                pass

    # Wire post-dream analysis callback (AD-237)
    # NOTE: These are re-wired to DreamAdapter below in the AD-515 service creation block.
    if dream_scheduler:
        # PATCH(AD-517): Dream scheduler callback wiring — re-wired in finalize phase
        dream_scheduler._post_dream_fn = on_post_dream_fn
        dream_scheduler._pre_dream_fn = on_pre_dream_fn
        dream_scheduler._post_micro_dream_fn = on_post_micro_dream_fn

    # AD-532e: Reactive trigger subscription
    if dreaming_engine and runtime and hasattr(runtime, 'add_event_listener'):
        async def _on_task_complete(event: dict) -> None:
            try:
                await dreaming_engine.on_task_execution_complete(event.get("data", event))
            except Exception:
                logger.debug("Reactive trigger handler failed", exc_info=True)

        runtime.add_event_listener(
            _on_task_complete,
            event_types=[EventType.TASK_EXECUTION_COMPLETE],
        )

        # AD-534b: Fallback learning event subscription
        async def _on_fallback_learning(event: dict) -> None:
            try:
                await dreaming_engine.on_procedure_fallback_learning(event.get("data", event))
            except Exception:
                logger.debug("Fallback learning handler failed", exc_info=True)

        runtime.add_event_listener(
            _on_fallback_learning,
            event_types=[EventType.PROCEDURE_FALLBACK_LEARNING],
        )

    # Start task scheduler (AD-282)
    task_scheduler = TaskScheduler(
        process_fn=process_natural_language_fn,
    )
    task_scheduler.start()

    # Schedule daily scout scan (AD-394)
    if config.channels.discord.scout_channel_id:
        task_scheduler.schedule(
            text="/scout",
            delay_seconds=60,
            interval_seconds=86400,
            channel_id=str(config.channels.discord.scout_channel_id),
        )

    # Start periodic flush of trust + routing weights
    flush_task = asyncio.create_task(periodic_flush_loop_fn())

    logger.info("Startup [dreaming]: complete")
    result = DreamingResult(
        dream_scheduler=dream_scheduler,
        dreaming_engine=dreaming_engine,
        emergent_detector=emergent_detector,
        emergence_metrics_engine=emergence_engine,
        task_scheduler=task_scheduler,
        flush_task=flush_task,
        notebook_quality_engine=notebook_quality_engine,
        retrieval_practice_engine=retrieval_practice_engine,
        behavioral_metrics_engine=behavioral_metrics_engine,
        quality_router=quality_router,
    )
    return result, cold_start
