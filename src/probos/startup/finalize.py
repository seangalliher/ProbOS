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
        # Wire watch_manager early so _populate_watch_roster() can find it
        runtime.watch_manager = watch_manager
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

    # --- AD-529: Wire content contagion firewall into Ward Room ---
    if runtime.ward_room and runtime.trust_network and config.firewall.enabled:
        from probos.ward_room.content_firewall import ContentFirewall

        _content_firewall = ContentFirewall(
            trust_network=runtime.trust_network,
            emit_event_fn=runtime._emit_event,
            config=config.firewall,
        )
        if runtime.ward_room._messages:
            runtime.ward_room._messages.set_content_firewall(_content_firewall)
        if runtime.ward_room._threads:
            runtime.ward_room._threads.set_content_firewall(_content_firewall)
        logger.info("AD-529: Content contagion firewall wired")

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
        # AD-637c: Only wire router ref for fallback path (NATS disconnected).
        # When NATS is connected, events flow through JetStream → consumer callback.
        # Not wiring the ref when NATS is active makes no-dual-delivery structural.
        if not (getattr(runtime, 'nats_bus', None) and runtime.nats_bus.connected):
            if hasattr(runtime.ward_room, '_ward_room_router_ref'):
                runtime.ward_room._ward_room_router_ref[0] = ward_room_router
        # AD-621: Populate membership cache after startup subscriptions
        await ward_room_router.populate_membership_cache()

        # AD-637c: JetStream setup — stream ensure + consumer subscription
        # Both are in finalize.py to avoid split-phase race conditions.
        if getattr(runtime, 'nats_bus', None) and runtime.nats_bus.connected:
            # Ensure WARDROOM stream exists
            await runtime.nats_bus.ensure_stream(
                "WARDROOM",
                ["wardroom.events.>"],
                max_msgs=10000,
                max_age=3600,  # 1 hour retention
            )

            # Subscribe router as durable JetStream consumer
            async def _on_wardroom_event(msg: Any) -> None:
                """JetStream consumer callback — extract event_type and route."""
                event_type = msg.data.get("event_type", "")
                if not event_type:
                    logger.debug("AD-637c: Ward room event missing event_type, skipping")
                    return
                # Remove event_type from data before routing (router expects raw event data)
                data = {k: v for k, v in msg.data.items() if k != "event_type"}
                await ward_room_router.route_event_coalesced(event_type, data)

            await runtime.nats_bus.js_subscribe(
                "wardroom.events.>",
                _on_wardroom_event,
                durable="wardroom-router",
                stream="WARDROOM",
                max_ack_pending=10,  # Matches AD-616 concurrency limit
                ack_wait=120,  # Seconds — must exceed slow cognitive chain time
            )
            logger.info("AD-637c: WARDROOM JetStream stream + consumer wired")

        # AD-625: Pre-cache communication proficiency profiles for gate modulation
        if hasattr(runtime, 'skill_service') and runtime.skill_service:
            runtime._comm_profiles = {}
            for agent in runtime.registry.all():
                if is_crew_agent(agent, runtime.ontology):
                    try:
                        profile = await runtime.skill_service.get_profile(agent.id)
                        if profile:
                            runtime._comm_profiles[agent.id] = profile
                    except Exception:
                        logger.debug("Comm profile cache failed for %s", agent.id, exc_info=True)

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

    # AD-423c: Wire tool registry into onboarding service
    if runtime.tool_registry:
        runtime.onboarding.set_tool_registry(runtime.tool_registry)

    # AD-596b: Wire cognitive skill catalog into onboarding service
    if runtime.cognitive_skill_catalog:
        runtime.onboarding.set_cognitive_skill_catalog(runtime.cognitive_skill_catalog)
        # BF: Backfill catalog onto agents created before the catalog existed (Phase 2 < Phase 7)
        for _agent in runtime.registry.all():
            if not getattr(_agent, '_cognitive_skill_catalog', None):
                _agent._cognitive_skill_catalog = runtime.cognitive_skill_catalog

    # AD-596c: Wire skill bridge into onboarding service
    if hasattr(runtime, 'skill_bridge') and runtime.skill_bridge:
        runtime.onboarding.set_skill_bridge(runtime.skill_bridge)

    # AD-526a: Wire RecreationService with late-init dependencies
    from probos.recreation.service import RecreationService
    runtime.recreation_service = RecreationService(
        ward_room=runtime.ward_room,
        records_store=runtime._records_store,
        emit_event_fn=runtime._emit_event,
    )

    # AD-632b: Wire SubTaskExecutor + QueryHandler for Level 3 cognitive escalation
    try:
        from probos.cognitive.sub_task import SubTaskExecutor, SubTaskType
        from probos.cognitive.sub_tasks import (
            AnalyzeHandler, ComposeHandler, EvaluateHandler, QueryHandler, ReflectHandler,
        )

        sub_task_config = config.sub_task
        executor = SubTaskExecutor(
            config=sub_task_config,
            emit_event_fn=runtime._emit_event,
        )
        query_handler = QueryHandler(runtime)
        executor.register_handler(SubTaskType.QUERY, query_handler)

        analyze_handler = AnalyzeHandler(
            llm_client=runtime.llm_client,
            runtime=runtime,
        )
        executor.register_handler(SubTaskType.ANALYZE, analyze_handler)

        compose_handler = ComposeHandler(
            llm_client=runtime.llm_client,
            runtime=runtime,
        )
        executor.register_handler(SubTaskType.COMPOSE, compose_handler)

        evaluate_handler = EvaluateHandler(
            llm_client=runtime.llm_client,
            runtime=runtime,
        )
        executor.register_handler(SubTaskType.EVALUATE, evaluate_handler)

        reflect_handler = ReflectHandler(
            llm_client=runtime.llm_client,
            runtime=runtime,
        )
        executor.register_handler(SubTaskType.REFLECT, reflect_handler)

        runtime._sub_task_executor = executor

        # Wire executor onto all crew agents
        for _agent in runtime.registry.all():
            if is_crew_agent(_agent, runtime.ontology):
                _agent.set_sub_task_executor(executor)

        logger.info(
            "AD-632e: SubTaskExecutor wired with Query + Analyze + Compose + Evaluate + Reflect handlers (enabled=%s)",
            sub_task_config.enabled,
        )
    except Exception:
        logger.warning(
            "AD-632c: SubTaskExecutor wiring failed — continuing without",
            exc_info=True,
        )
        runtime._sub_task_executor = None

    # --- AD-583f/583g: Observable State Verification + Source Tracing ---
    try:
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        from probos.cognitive.observable_state import (
            ObservableStateVerifier,
            RecreationStateProvider,
            TrustStateProvider,
            SystemHealthProvider,
        )

        src_cfg = config.source_tracing
        obs_cfg = config.observable_state

        # Build state providers from available services
        providers = []
        if runtime.recreation_service:
            providers.append(RecreationStateProvider(runtime.recreation_service))
        if runtime.trust_network:
            providers.append(TrustStateProvider(runtime.trust_network))

        observable_verifier = (
            ObservableStateVerifier(providers, max_claims=obs_cfg.max_claims_per_thread)
            if providers and obs_cfg.verification_enabled else None
        )

        # Thread echo analyzer
        thread_echo = None
        if src_cfg.echo_analysis_enabled and runtime.ward_room:
            thread_echo = ThreadEchoAnalyzer(
                thread_manager=runtime.ward_room._threads,
                min_chain_length=src_cfg.echo_min_chain_length,
                similarity_threshold=src_cfg.echo_similarity_threshold,
            )

        # Late-bind to Ward Room via public set_echo_services (Law of Demeter)
        if runtime.ward_room and (thread_echo or observable_verifier):
            runtime.ward_room.set_echo_services(
                thread_echo_analyzer=thread_echo,
                observable_state_verifier=observable_verifier,
                bridge_alerts=getattr(runtime, 'bridge_alerts', None),
                ward_room_router=ward_room_router,
            )

        # Store verifier on runtime for behavioral metrics access
        runtime._observable_state_verifier = observable_verifier

        # Wire verifier into behavioral metrics engine
        bme = getattr(runtime, 'behavioral_metrics_engine', None)
        if bme and observable_verifier:
            bme.set_observable_verifier(observable_verifier)

        logger.info("AD-583f/583g: Echo detection + observable state verification wired")
    except Exception as e:
        logger.warning("AD-583f/583g: Setup failed: %s — continuing without", e)
        runtime._observable_state_verifier = None

    # BF-125: Subscribe to GAME_COMPLETED to clean both players' working memory
    from probos.events import EventType


    async def _on_game_completed(event: dict) -> None:
        """BF-125: Clean both players' working memory on game completion."""
        event_data = event.get("data", event)
        game_id = event_data.get("game_id", "")
        if not game_id:
            return
        for agent in runtime.registry.all():
            # BF-127: Only crew agents have meaningful working memory
            if not is_crew_agent(agent, getattr(runtime, 'ontology', None)):
                continue
            wm = getattr(agent, 'working_memory', None)
            if wm and wm.get_engagement(game_id):
                wm.remove_engagement(game_id)
                logger.debug("BF-125: Removed game %s from %s working memory",
                             game_id, getattr(agent, 'callsign', agent.id))

    runtime.add_event_listener(
        _on_game_completed,
        event_types=[EventType.GAME_COMPLETED],
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

    # AD-573: Restore working memory from stasis
    if (runtime._lifecycle_state == "stasis_recovery"
            and hasattr(runtime, 'working_memory_store')
            and runtime.working_memory_store):
        try:
            from probos.cognitive.agent_working_memory import AgentWorkingMemory
        
            frozen_states = await runtime.working_memory_store.load_all()
            stale_hours = config.working_memory.stale_threshold_hours
            restored = 0
            for agent in runtime.registry.all():
                # BF-127: Only restore working memory for sovereign crew agents
                if not is_crew_agent(agent, getattr(runtime, 'ontology', None)):
                    continue
                wm = getattr(agent, 'working_memory', None)
                if wm is None:
                    continue
                state = frozen_states.get(agent.id)
                if state:
                    restored_wm = AgentWorkingMemory.from_dict(
                        state,
                        stale_threshold_seconds=stale_hours * 3600,
                    )
                    # Revalidate game engagements against live RecreationService
                    if hasattr(runtime, 'recreation_service') and runtime.recreation_service:
                        active_game_ids = {
                            g["game_id"]
                            for g in runtime.recreation_service.get_active_games()
                        }
                        for eng in list(restored_wm.get_engagements_by_type("game")):
                            if eng.engagement_id not in active_game_ids:
                                restored_wm.remove_engagement(eng.engagement_id)
                    agent._working_memory = restored_wm
                    restored += 1
            if restored:
                logger.info("AD-573: Restored working memory for %d agents", restored)
        except Exception:
            logger.debug("AD-573: Working memory restore failed", exc_info=True)

    # AD-567g: Warm boot orientation for stasis recovery
    if (hasattr(runtime, '_orientation_service') and runtime._orientation_service
            and runtime._lifecycle_state == "stasis_recovery"
            and config.orientation.warm_boot_orientation):
        try:
            # AD-513: Build crew names lookup for orientation
            _all_crew_names: dict[str, str] = {}
            if hasattr(runtime, 'callsign_registry') and runtime.callsign_registry:
                _all_crew_names = runtime.callsign_registry.all_callsigns()

            # BF-144: Compute authoritative stasis timestamps (once, before agent loop)
            _shutdown_str = ""
            _resume_str = ""
            if runtime._previous_session and "shutdown_time_utc" in runtime._previous_session:
                _shutdown_str = datetime.fromtimestamp(
                    runtime._previous_session["shutdown_time_utc"], tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC")
                _resume_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

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
                            _trust = runtime.trust_network.get_score(agent.id)
                        except Exception:
                            pass
                    # AD-513: Crew names excluding self
                    _crew_names = sorted(
                        cs for at, cs in _all_crew_names.items()
                        if cs and at != agent.agent_type
                    )
                    _ctx = runtime._orientation_service.build_orientation(
                        agent,
                        lifecycle_state="stasis_recovery",
                        stasis_duration=runtime._stasis_duration,
                        stasis_shutdown_utc=_shutdown_str,       # BF-144
                        stasis_resume_utc=_resume_str,           # BF-144
                        episodic_memory_count=_ep_count,
                        trust_score=_trust,
                        crew_names=_crew_names,
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
