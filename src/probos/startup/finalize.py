"""Phase 8: Finalization — proactive loop, service wiring, startup event (AD-517).

Creates the proactive cognitive loop, WardRoomRouter, SelfModManager,
DreamAdapter, re-wires dream callbacks, patches late-init onboarding
dependencies, and announces startup to the Ward Room.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from probos.startup.results import FinalizationResult
from probos.utils import format_duration
from probos.crew_utils import is_crew_agent

if TYPE_CHECKING:
    from probos.config import SystemConfig

logger = logging.getLogger(__name__)


async def finalize_startup(
    *,
    runtime: Any,  # ProbOSRuntime — passed as Any to avoid circular import
    config: "SystemConfig",
) -> FinalizationResult:
    """Wire late-init services, start proactive loop, announce startup.

    This phase has direct access to the runtime object because it must
    wire cross-cutting services that reference many runtime attributes.
    """
    logger.info("Startup [finalize]: starting")

    conn_manager = None
    night_orders_mgr = None
    watch_manager = None
    proactive_loop = None
    ward_room_router = None
    self_mod_manager = None

    # --- Proactive Cognitive Loop (Phase 28b) ---
    if config.proactive_cognitive.enabled and runtime.ward_room:
        from probos.conn import ConnManager
        from probos.watch_rotation import WatchManager, NightOrdersManager

        conn_manager = ConnManager()
        night_orders_mgr = NightOrdersManager()
        watch_manager = WatchManager(
            dispatch_fn=runtime._dispatch_watch_intent,
            check_interval=30.0,
        )
        # Populate roster from ontology
        if runtime.ontology:
            runtime._populate_watch_roster()
        await watch_manager.start()

        from probos.proactive import ProactiveCognitiveLoop

        proactive_loop = ProactiveCognitiveLoop(
            interval=config.proactive_cognitive.interval_seconds,
            cooldown=config.proactive_cognitive.cooldown_seconds,
            on_event=lambda evt: runtime._emit_event(evt.get("type", ""), evt.get("data", {})),
        )
        proactive_loop.set_runtime(runtime)
        proactive_loop.set_config(config.proactive_cognitive, cb_config=config.circuit_breaker)
        if config.proactive_cognitive.duty_schedule.enabled:
            proactive_loop.set_duty_schedule(config.proactive_cognitive.duty_schedule)
        # PATCH(AD-517): Wire knowledge store for cooldown persistence
        if runtime._knowledge_store:
            proactive_loop._knowledge_store = runtime._knowledge_store
            await proactive_loop.restore_cooldowns()
        # AD-567g: Wire orientation service into proactive loop
        if hasattr(runtime, '_orientation_service') and runtime._orientation_service:
            proactive_loop.set_orientation_service(runtime._orientation_service)
        await proactive_loop.start()
        logger.info("proactive-cognitive-loop started (interval=%ss)", config.proactive_cognitive.interval_seconds)

    # --- AD-558: Wire trust dampening dependencies ---
    if runtime.ontology:
        runtime.trust_network.set_department_lookup(
            lambda agent_id: runtime.ontology.get_agent_department(agent_id)
        )
    runtime.trust_network.set_event_callback(
        lambda event_type, data: runtime._emit_event(event_type, data)
    )

    # --- AD-557: Wire emergence metrics dependencies ---
    if runtime.dream_scheduler and runtime.dream_scheduler.engine:
        engine = runtime.dream_scheduler.engine
        if runtime.ward_room:
            engine._ward_room = runtime.ward_room
        if runtime.ontology:
            engine._get_department = lambda aid: runtime.ontology.get_agent_department(aid)
        # AD-551: Wire records_store for notebook consolidation
        if hasattr(runtime, '_records_store') and runtime._records_store:
            engine._records_store = runtime._records_store

    # --- BF-100: Wire EmergentDetector to DreamScheduler for dream suppression ---
    if runtime.dream_scheduler and getattr(runtime, '_emergent_detector', None):
        runtime.dream_scheduler.set_emergent_detector(runtime._emergent_detector)

    # --- AD-567f: Wire social verification into Ward Room ---
    if hasattr(runtime, '_social_verification') and runtime._social_verification:
        ward_room = runtime.ward_room
        if ward_room:
            ward_room.set_social_verification(runtime._social_verification)

    # --- AD-515: Create extracted service instances ---
    from probos.ward_room_router import WardRoomRouter
    from probos.self_mod_manager import SelfModManager
    from probos.dream_adapter import DreamAdapter

    # Ward Room Router
    if runtime.ward_room:
        ward_room_router = WardRoomRouter(
            ward_room=runtime.ward_room,
            registry=runtime.registry,
            intent_bus=runtime.intent_bus,
            trust_network=runtime.trust_network,
            ontology=runtime.ontology,
            callsign_registry=runtime.callsign_registry,
            episodic_memory=runtime.episodic_memory,
            event_emitter=runtime._emit_event,
            event_log=runtime.event_log,
            config=config,
            notify_fn=runtime.notify,
            proactive_loop=proactive_loop,
        )
        # Wire the router ref so Ward Room emit callback can route events
        if hasattr(runtime.ward_room, '_ward_room_router_ref'):
            runtime.ward_room._ward_room_router_ref[0] = ward_room_router

    # Agent Onboarding Service — patch in late-init dependencies
    # PATCH(AD-517): These are set via private attrs because onboarding
    # is created before these services exist.
    runtime.onboarding._ontology = runtime.ontology
    runtime.onboarding._ward_room = runtime.ward_room
    runtime.onboarding._acm = runtime.acm
    runtime.onboarding._start_time_wall = runtime._start_time_wall
    # AD-567g: Wire orientation service into onboarding
    if hasattr(runtime, '_orientation_service') and runtime._orientation_service:
        runtime.onboarding.set_orientation_service(runtime._orientation_service)

    # AD-526a: Wire RecreationService with late-init dependencies
    from probos.recreation.service import RecreationService
    runtime.recreation_service = RecreationService(
        ward_room=runtime.ward_room,
        records_store=runtime._records_store,
        emit_event_fn=runtime._emit_event,
    )

    # Self-Modification Manager
    if runtime.self_mod_pipeline:
        self_mod_manager = SelfModManager(
            self_mod_pipeline=runtime.self_mod_pipeline,
            knowledge_store=runtime._knowledge_store,
            trust_network=runtime.trust_network,
            intent_bus=runtime.intent_bus,
            capability_registry=runtime.capability_registry,
            registry=runtime.registry,
            pools=runtime.pools,
            spawner=runtime.spawner,
            decomposer=runtime.decomposer,
            feedback_engine=runtime.feedback_engine,
            llm_client=runtime.llm_client,
            event_emitter=runtime._emit_event,
            config=config,
            semantic_layer=runtime._semantic_layer,
            collect_intent_descriptors_fn=runtime._collect_intent_descriptors,
            process_natural_language_fn=runtime.process_natural_language,
            add_skill_to_agents_fn=runtime._add_skill_to_agents,
            register_agent_type_fn=runtime.register_agent_type,
            unregister_agent_type_fn=runtime.unregister_agent_type,
            create_pool_fn=runtime.create_pool,
            runtime=runtime,
        )

    # Dream Adapter
    dream_adapter = DreamAdapter(
        dream_scheduler=runtime.dream_scheduler,
        emergent_detector=runtime._emergent_detector,
        episodic_memory=runtime.episodic_memory,
        knowledge_store=runtime._knowledge_store,
        hebbian_router=runtime.hebbian_router,
        trust_network=runtime.trust_network,
        event_emitter=runtime._emit_event,
        self_mod_pipeline=runtime.self_mod_pipeline,
        bridge_alerts=runtime.bridge_alerts,
        ward_room=runtime.ward_room,
        registry=runtime.registry,
        event_log=runtime.event_log,
        config=config,
        pools=runtime.pools,
        behavioral_monitor=runtime.behavioral_monitor,
        deliver_bridge_alert_fn=(
            ward_room_router.deliver_bridge_alert
            if ward_room_router else None
        ),
        llm_client=getattr(runtime, 'llm_client', None),  # BF-069
        identity_registry=runtime.identity_registry,  # BF-103
    )
    dream_adapter._cold_start = runtime._cold_start

    # Re-wire dream scheduler callbacks to use the adapter
    if runtime.dream_scheduler:
        # PATCH(AD-517): Dream scheduler callback re-wiring
        runtime.dream_scheduler._post_dream_fn = dream_adapter.on_post_dream
        runtime.dream_scheduler._pre_dream_fn = dream_adapter.on_pre_dream
        runtime.dream_scheduler._post_micro_dream_fn = dream_adapter.on_post_micro_dream

    # Re-wire periodic flush to use the adapter
    if hasattr(runtime, '_flush_task'):
        runtime._flush_task.cancel()
    runtime._flush_task = asyncio.create_task(dream_adapter.periodic_flush_loop())

    # --- AD-503: Counselor activation — initialize + wire initiative engine ---
    counselor_agent = None
    if "counselor" in runtime.pools:
        agents = runtime.registry.get_by_pool("counselor")
        if agents:
            counselor_agent = agents[0]
            await counselor_agent.initialize(
                trust_network=runtime.trust_network,
                hebbian_router=runtime.hebbian_router,
                registry=runtime.registry,
                crew_profiles=getattr(runtime, 'acm', None),
                episodic_memory=runtime.episodic_memory,
                emit_event_fn=runtime._emit_event,
                add_event_listener_fn=runtime.add_event_listener,
                ward_room_router=ward_room_router if runtime.ward_room else None,  # AD-505: fixed wiring
                ward_room=runtime.ward_room,  # AD-505: for DM channel creation
                directive_store=getattr(runtime, 'directive_store', None),  # AD-505
                dream_scheduler=getattr(runtime, 'dream_scheduler', None),  # AD-505
                proactive_loop=proactive_loop,  # AD-505: for cooldown adjustment
            )
            logger.info("AD-503: Counselor agent initialized")

            # AD-541d: Wire Guided Reminiscence Engine into Counselor
            if config.dreaming.reminiscence_enabled:
                try:
                    from probos.cognitive.guided_reminiscence import GuidedReminiscenceEngine

                    reminiscence_engine = GuidedReminiscenceEngine(
                        episodic_memory=runtime.episodic_memory,
                        llm_client=getattr(runtime, 'llm_client', None),
                        config=config.dreaming,
                        max_episodes_per_session=config.dreaming.reminiscence_episodes_per_session,
                        confabulation_alert_threshold=config.dreaming.reminiscence_confabulation_alert,
                    )
                    counselor_agent.set_reminiscence_engine(reminiscence_engine)
                    counselor_agent.configure_reminiscence(
                        cooldown_hours=config.dreaming.reminiscence_cooldown_hours,
                        concern_threshold=config.dreaming.reminiscence_concern_threshold,
                        confabulation_alert=config.dreaming.reminiscence_confabulation_alert,
                    )
                    logger.info("AD-541d: Guided Reminiscence wired into Counselor")
                except Exception:
                    logger.debug("AD-541d: Failed to wire Guided Reminiscence", exc_info=True)

    # AD-503: Wire InitiativeEngine counselor_fn
    if runtime.initiative and counselor_agent:
        def _counselor_alert_fn() -> list:
            return counselor_agent.agents_at_alert("yellow")
        runtime.initiative.set_counselor_fn(_counselor_alert_fn)

    runtime._started = True

    await runtime.event_log.log(category="system", event="started")
    logger.info(
        "ProbOS started: %d agents across %d pools + %d red team",
        runtime.registry.count,
        len(runtime.pools),
        len(runtime._red_team_agents),
    )

    # AD-435 + AD-502: Announce startup to Ward Room (lifecycle-aware)
    if runtime.ward_room:
        try:
            all_hands = await runtime.ward_room.get_channel_by_name("All Hands")
            if all_hands:
                    if runtime._lifecycle_state == "stasis_recovery":
                        dur = format_duration(runtime._stasis_duration)
                        prev = runtime._previous_session
                        shutdown_str = datetime.fromtimestamp(
                            prev["shutdown_time_utc"], tz=timezone.utc
                        ).strftime("%Y-%m-%d %H:%M:%S UTC") if prev else "unknown"
                        title = "Stasis Recovery — All Hands"
                        body = (
                            f"All hands: The ship has returned from stasis. "
                            f"Stasis duration: {dur}. "
                            f"Previous session ended: {shutdown_str}. "
                            f"All crew identities and memories are intact. "
                            f"Resume normal operations."
                        )
                    elif runtime._lifecycle_state == "first_boot":
                        title = "System Online — First Activation"
                        body = "This is the maiden voyage. All systems operational."
                    elif runtime._lifecycle_state == "restart":
                        title = "System Restart — All Stations Resume"
                        body = "System restart complete. All stations resume normal operations."
                    else:
                        title = "System Online"
                        body = "ProbOS startup complete. All systems operational."
                    await runtime.ward_room.create_thread(
                        channel_id=all_hands.id,
                        author_id="system",
                        title=title,
                        body=body,
                        author_callsign="Ship's Computer",
                        thread_mode="announce",
                        max_responders=0,
                    )
        except Exception:
            logger.debug("Startup announcement failed", exc_info=True)

    # AD-567g: Warm boot orientation for stasis recovery
    if (hasattr(runtime, '_orientation_service') and runtime._orientation_service
            and runtime._lifecycle_state == "stasis_recovery"
            and config.orientation.warm_boot_orientation):
        try:
            for agent in runtime.registry.all():
                if is_crew_agent(agent, runtime.ontology):
                    _ep_count = 0
                    if runtime.episodic_memory:
                        try:
                            _sid = getattr(agent, 'sovereign_id', None) or agent.id
                            _eps = await runtime.episodic_memory.recall("", agent_id=_sid, k=1)
                            _ep_count = len(_eps) if _eps else 0
                        except Exception:
                            pass
                    _trust = 0.5
                    if runtime.trust_network:
                        try:
                            _trust = runtime.trust_network.get_trust(agent.id)
                        except Exception:
                            pass
                    _ctx = runtime._orientation_service.build_orientation(
                        agent,
                        lifecycle_state="stasis_recovery",
                        stasis_duration=runtime._stasis_duration,
                        episodic_memory_count=_ep_count,
                        trust_score=_trust,
                    )
                    agent.set_orientation(
                        runtime._orientation_service.render_warm_boot_orientation(_ctx),
                        _ctx,
                    )
            logger.info("AD-567g: Warm boot orientation set for crew agents")
        except Exception:
            logger.debug("AD-567g: Warm boot orientation failed", exc_info=True)

    # BF-101/102 Enhancement: Batched auto-welcome for newly commissioned crew
    # Skip on cold start (reset) — the "Fresh Start" announcement handles it.
    if runtime.ward_room and not runtime._cold_start:
        try:
            new_crew = [
                a for a in runtime.registry.all()
                if getattr(a, '_newly_commissioned', False)
            ]
            if new_crew:
                all_hands_ch = await runtime.ward_room.get_channel_by_name("All Hands")
                if all_hands_ch:
                    names = ", ".join(
                        f"{a.callsign} ({a.agent_type.replace('_', ' ').title()})"
                        for a in new_crew
                    )
                    await runtime.ward_room.create_thread(
                        channel_id=all_hands_ch.id,
                        author_id="system",
                        title="New Crew Aboard",
                        body=(
                            f"The following crew members have been commissioned "
                            f"and joined the ship: {names}. Welcome aboard."
                        ),
                        author_callsign="Ship's Computer",
                        thread_mode="discuss",
                    )
                    logger.info("BF-102 Enhancement: Posted auto-welcome for %d new crew", len(new_crew))
                    # Clear flags to avoid duplicate announcements
                    for a in new_crew:
                        a._newly_commissioned = False
        except Exception:
            logger.debug("Auto-welcome announcement failed", exc_info=True)

    logger.info("Startup [finalize]: complete")
    return FinalizationResult(
        conn_manager=conn_manager,
        night_orders_mgr=night_orders_mgr,
        watch_manager=watch_manager,
        proactive_loop=proactive_loop,
        ward_room_router=ward_room_router,
        self_mod_manager=self_mod_manager,
        dream_adapter=dream_adapter,
    )
