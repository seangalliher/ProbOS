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
from probos.cognitive.emergent_detector import EmergentDetector
from probos.cognitive.task_scheduler import TaskScheduler
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
) -> tuple[DreamingResult, bool]:
    """Start dreaming/detection subsystems and detect cold start.

    Returns a tuple of (DreamingResult, cold_start_flag).
    """
    logger.info("Startup [dreaming]: starting")

    # Start dreaming scheduler if episodic memory is available
    dream_scheduler = None
    dreaming_engine = None
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
        )
        dream_scheduler = DreamScheduler(
            engine=dreaming_engine,
            idle_threshold_seconds=dream_cfg.idle_threshold_seconds,
            dream_interval_seconds=dream_cfg.dream_interval_seconds,
            proactive_extends_idle=dream_cfg.proactive_extends_idle,
        )
        dream_scheduler._emit_event_fn = emit_event_fn  # AD-503
        dream_scheduler.start()

    # Create EmergentDetector (AD-237) — unconditional, pure observer
    emergent_detector = EmergentDetector(
        hebbian_router=hebbian_router,
        trust_network=trust_network,
        episodic_memory=episodic_memory,
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

    # Wire post-dream analysis callback (AD-237)
    # NOTE: These are re-wired to DreamAdapter below in the AD-515 service creation block.
    if dream_scheduler:
        # PATCH(AD-517): Dream scheduler callback wiring — re-wired in finalize phase
        dream_scheduler._post_dream_fn = on_post_dream_fn
        dream_scheduler._pre_dream_fn = on_pre_dream_fn
        dream_scheduler._post_micro_dream_fn = on_post_micro_dream_fn

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
        task_scheduler=task_scheduler,
        flush_task=flush_task,
    )
    return result, cold_start
