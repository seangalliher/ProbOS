"""Graceful shutdown sequence (AD-518).

Extracted from ProbOSRuntime.stop() — handles ordered teardown of all
services, persistence of knowledge artifacts, and session record writing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from probos.crew_utils import is_crew_agent

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def shutdown(runtime: ProbOSRuntime, reason: str = "") -> None:
    """Graceful shutdown of all pools, mesh services, and persistence."""
    if not runtime._started:
        return

    logger.info("ProbOS shutting down...")
    try:
        await runtime.event_log.log(category="system", event="stopping")
    except (asyncio.CancelledError, Exception):
        pass  # event log may be unavailable during shutdown

    # AD-435 + AD-502: Announce shutdown to Ward Room (stasis protocol)
    if runtime.ward_room and runtime.ward_room._db:
        try:
            async with runtime.ward_room._db.execute(
                "SELECT id FROM channels WHERE name = 'All Hands' LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    msg = (
                        "Attention all hands: The ship is entering stasis. "
                        "All cognitive processes will be suspended. "
                        "Your memories and identity will be preserved. "
                        "When the system resumes, you will be informed of the stasis duration."
                    )
                    if reason:
                        msg += f" Reason: {reason}"
                    await runtime.ward_room.create_thread(
                        channel_id=row[0],
                        author_id="system",
                        author_callsign="Ship's Computer",
                        title="Entering Stasis",
                        body=msg,
                        thread_mode="announce",
                        max_responders=0,
                    )
        except Exception:
            pass  # best-effort, don't block shutdown

    # AD-502: Persist session record immediately after stasis announcement
    # BF-065: Write to runtime._data_dir directly (not knowledge_store) so it
    # persists even if knowledge store is torn down or never initialized.
    try:
        session_record = {
            "session_id": runtime._session_id,
            "start_time_utc": runtime._start_time_wall,
            "shutdown_time_utc": time.time(),
            "uptime_seconds": time.monotonic() - runtime._start_time,
            "agent_count": len([a for a in runtime.registry.all() if is_crew_agent(a, runtime.ontology)]),
            "reason": reason,
        }
        session_path = runtime._data_dir / "session_last.json"
        session_path.write_text(json.dumps(session_record, indent=2))
    except Exception as e:
        logger.debug("AD-502: Session record persistence failed: %s", e)

    # AD-435: Grace period for in-flight DB writes to complete
    logger.info("Shutdown grace period (1s)...")
    await asyncio.sleep(1)

    # Cancel periodic flush
    if hasattr(runtime, '_flush_task'):
        runtime._flush_task.cancel()

    # Stop ACM (AD-427)
    if runtime.acm:
        await runtime.acm.stop()
        runtime.acm = None

    # Stop Identity Registry (AD-441)
    if runtime.identity_registry:
        await runtime.identity_registry.stop()
        runtime.identity_registry = None

    # Stop SIF (AD-370)
    if runtime.sif:
        await runtime.sif.stop()
        runtime.sif = None

    # Stop InitiativeEngine (AD-381)
    if runtime.initiative:
        await runtime.initiative.stop()
        runtime.initiative = None

    # Stop Proactive Cognitive Loop (Phase 28b)
    if runtime.proactive_loop:
        # AD-415: Persist proactive cooldown overrides before stopping
        if runtime._knowledge_store and runtime.proactive_loop._agent_cooldowns:
            try:
                await runtime._knowledge_store.store_cooldowns(runtime.proactive_loop._agent_cooldowns.copy())
            except Exception:
                logger.warning("Failed to persist proactive cooldowns", exc_info=True)
        await runtime.proactive_loop.stop()
        runtime.proactive_loop = None

    # AD-471: Stop watch manager and expire Night Orders
    if hasattr(runtime, 'watch_manager') and runtime.watch_manager:
        await runtime.watch_manager.stop()
        runtime.watch_manager = None
    if hasattr(runtime, '_night_orders_mgr') and runtime._night_orders_mgr:
        if runtime._night_orders_mgr.active:
            runtime._night_orders_mgr.expire()

    # Stop Persistent Task Store (Phase 25a)
    if runtime.persistent_task_store:
        await runtime.persistent_task_store.stop()
        runtime.persistent_task_store = None

    # Stop Workforce Scheduling Engine (AD-496)
    if runtime.work_item_store:
        await runtime.work_item_store.stop()
        runtime.work_item_store = None

    # Stop build dispatcher (AD-375)
    if runtime.build_dispatcher:
        await runtime.build_dispatcher.stop()
        runtime.build_dispatcher = None
        runtime.build_queue = None

    # Stop task tracker (AD-316)
    if runtime.task_tracker:
        runtime.task_tracker = None

    # Disconnect service profiles (AD-382)
    from probos.agents.http_fetch import HttpFetchAgent
    from probos.cognitive.standing_orders import set_directive_store

    HttpFetchAgent.set_profile_store(None)
    runtime.service_profiles = None

    # Disconnect directive store (AD-386)
    if runtime.directive_store:
        set_directive_store(None)
        runtime.directive_store.close()
        runtime.directive_store = None

    # Stop Ward Room (AD-407)
    if runtime.ward_room:
        await runtime.ward_room.stop_prune_loop()
        await runtime.ward_room.stop()
        runtime.ward_room = None

    # Stop Cognitive Journal (AD-431)
    if runtime.cognitive_journal:
        await runtime.cognitive_journal.stop()
        runtime.cognitive_journal = None

    # Stop Skill Framework (AD-428)
    if runtime.skill_service:
        await runtime.skill_service.stop()
        runtime.skill_service = None
    if runtime.skill_registry:
        await runtime.skill_registry.stop()
        runtime.skill_registry = None

    # Stop Assignment Service (AD-408)
    if runtime.assignment_service:
        await runtime.assignment_service.stop()
        runtime.assignment_service = None

    # Stop red team agents
    for agent in runtime._red_team_agents:
        await agent.stop()
        await runtime.registry.unregister(agent.id)
    runtime._red_team_agents.clear()

    # Stop pool scaler before stopping pools
    if runtime.pool_scaler:
        await runtime.pool_scaler.stop()
        runtime.pool_scaler = None

    # Stop federation
    if runtime.federation_bridge:
        await runtime.federation_bridge.stop()
        runtime.federation_bridge = None
    if runtime._federation_transport:
        await runtime._federation_transport.stop()
        runtime._federation_transport = None

    # Stop pools (stops agents, unregisters from registry)
    for name, pool in runtime.pools.items():
        await pool.stop()
    runtime.pools.clear()

    # Persist knowledge store artifacts before stopping services
    if runtime._knowledge_store:
        try:
            # Persist agent manifest (Phase 14c)
            await runtime._knowledge_store.store_manifest(runtime._build_manifest())
            # Persist trust snapshot (raw alpha/beta — AD-168)
            await runtime._knowledge_store.store_trust_snapshot(
                runtime.trust_network.raw_scores()
            )
            # Persist routing weights
            weights = [
                {"source": s, "target": t, "rel_type": rt_type, "weight": w}
                for (s, t, rt_type), w in runtime.hebbian_router.all_weights_typed().items()
            ]
            await runtime._knowledge_store.store_routing_weights(weights)
            # Persist workflow cache
            await runtime._knowledge_store.store_workflows(
                runtime.workflow_cache.export_all()
            )
            # Flush all pending commits
            await runtime._knowledge_store.flush()
        except Exception as e:
            logger.warning("Knowledge store shutdown persistence failed: %s", e)

    # Stop mesh and consensus services
    await runtime.gossip.stop()
    await runtime.signal_manager.stop()
    await runtime.hebbian_router.stop()
    await runtime.trust_network.stop()
    try:
        await runtime.event_log.log(category="system", event="stopped")
    except (asyncio.CancelledError, Exception):
        pass
    await runtime.event_log.stop()

    # Clean up LLM client
    await runtime.llm_client.close()

    # Tier 3: Shutdown consolidation — flush remaining episodes (AD-288)
    if runtime.dream_scheduler and runtime.episodic_memory:
        logger.info("Consolidating session memories...")
        try:
            report = await asyncio.wait_for(
                runtime.dream_scheduler.engine.dream_cycle(),
                timeout=5.0,  # Don't let consolidation block shutdown
            )
            logger.info(
                "Session consolidation complete: replayed=%d strengthened=%d pruned=%d",
                report.episodes_replayed,
                report.weights_strengthened,
                report.weights_pruned,
            )
        except (asyncio.CancelledError, Exception) as e:
            logger.warning("Shutdown consolidation failed: %s", e)

    # Stop dreaming scheduler
    if runtime.dream_scheduler:
        await runtime.dream_scheduler.stop()
        runtime.dream_scheduler = None

    # Stop task scheduler (AD-282)
    if runtime.task_scheduler:
        await runtime.task_scheduler.stop()
        runtime.task_scheduler = None

    # Stop episodic memory
    if runtime.episodic_memory:
        await runtime.episodic_memory.stop()

    # Stop semantic knowledge layer (AD-243)
    if runtime._semantic_layer:
        await runtime._semantic_layer.stop()
        runtime._semantic_layer = None

    runtime._started = False
    logger.info("ProbOS shutdown complete. Final agent count: %d", runtime.registry.count)
