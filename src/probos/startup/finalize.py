"""Phase 8: Finalization — proactive loop, service wiring, startup event (AD-517).

Creates the proactive cognitive loop, WardRoomRouter, SelfModManager,
DreamAdapter, re-wires dream callbacks, patches late-init onboarding
dependencies, and announces startup to the Ward Room.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from probos.startup.results import FinalizationResult
from probos.utils import format_duration
from probos.crew_utils import is_crew_agent

if TYPE_CHECKING:
    from probos.config import SystemConfig

logger = logging.getLogger(__name__)


def _wire_tiered_knowledge_loader(*, runtime: Any, config: "SystemConfig") -> int:
    """AD-585: Wire one shared TieredKnowledgeLoader onto CognitiveAgents."""
    knowledge_store = getattr(runtime, "_knowledge_store", None)
    if not knowledge_store or not config.knowledge_loading.enabled:
        return 0

    from probos.cognitive.cognitive_agent import CognitiveAgent as _CA
    from probos.cognitive.tiered_knowledge import TieredKnowledgeLoader

    knowledge_loader = TieredKnowledgeLoader(
        knowledge_source=knowledge_store,
        config=config.knowledge_loading,
        emit_event_fn=lambda event_type, data: runtime._emit_event(event_type, data),
    )
    wired_count = 0
    registry = getattr(runtime, "registry", None)
    for pool in runtime.pools.values():
        for agent_ref in pool.healthy_agents:
            agent = agent_ref
            if not isinstance(agent_ref, _CA) and registry is not None:
                agent = registry.get(agent_ref)
            if isinstance(agent, _CA) and hasattr(agent, "set_knowledge_loader"):
                agent.set_knowledge_loader(knowledge_loader)
                wired_count += 1
    return wired_count


def _wire_task_context(*, runtime: Any, config: "SystemConfig") -> int:
    """AD-586: Wire TaskContext for contextual standing orders."""
    if not config.task_context.enabled:
        return 0

    from probos.cognitive.cognitive_agent import CognitiveAgent as _CA
    from probos.cognitive.standing_orders import set_task_context
    from probos.cognitive.task_context import TaskContext

    ctx = TaskContext(config=config.task_context)
    set_task_context(ctx)

    wired_count = 0
    registry = getattr(runtime, "registry", None)
    for pool in runtime.pools.values():
        for agent_ref in pool.healthy_agents:
            agent = agent_ref
            if not isinstance(agent_ref, _CA) and registry is not None:
                agent = registry.get(agent_ref)
            if isinstance(agent, _CA) and hasattr(agent, "set_task_context"):
                agent.set_task_context(ctx)
                wired_count += 1
    return wired_count


def _populate_agent_tiers(*, runtime: Any, config: "SystemConfig") -> int:
    """AD-571: Classify registered agents and wire tier-aware services."""
    from probos.substrate.agent_tier import AgentTier, AgentTierRegistry

    agent_registry = getattr(runtime, "registry", None)
    if not agent_registry:
        return 0

    registry = AgentTierRegistry()
    crew_types = set(config.agent_tiers.crew_types)
    core_types = set(config.agent_tiers.core_types)

    for agent in agent_registry.all():
        agent_id = getattr(agent, "id", "")
        agent_type = getattr(agent, "agent_type", "")
        if not agent_id:
            continue
        if agent_type in core_types:
            registry.register(agent_id, AgentTier.CORE_INFRASTRUCTURE)
        elif agent_type in crew_types:
            registry.register(agent_id, AgentTier.CREW)
        else:
            registry.register(agent_id, AgentTier.UTILITY)

    trust = getattr(runtime, "trust_network", None)
    if trust and hasattr(trust, "set_tier_registry"):
        trust.set_tier_registry(registry)

    emergence = getattr(runtime, "_emergence_metrics_engine", None)
    if emergence and hasattr(emergence, "set_tier_registry"):
        emergence.set_tier_registry(registry)

    router = getattr(runtime, "hebbian_router", None)
    if router and hasattr(router, "set_tier_registry"):
        router.set_tier_registry(registry)

    runtime._tier_registry = registry
    return len(registry.all_registered())


def _sync_ontology_callsigns(runtime: Any) -> None:
    """BF-244: Reconcile naming ceremony callsigns into ontology assignments."""
    ontology = getattr(runtime, "ontology", None)
    callsign_registry = getattr(runtime, "callsign_registry", None)
    if not ontology or not callsign_registry:
        return

    for agent_type, callsign in callsign_registry.all_callsigns().items():
        current = ontology.get_assignment_for_agent(agent_type)
        if current and current.callsign != callsign:
            ontology.update_assignment_callsign(agent_type, callsign)
            logger.info(
                "BF-244: Synced ontology callsign for %s: '%s' -> '%s'",
                agent_type,
                current.callsign,
                callsign,
            )


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

    # BF-235: Defensive cache clear on any startup (cold or warm).
    # Ensures no stale standing orders or personality blocks from a
    # previous finalization pass within the same process. Also makes
    # the test surface uniform — stasis tests and cold-start tests
    # both start from a clean cache.
    from probos.cognitive.standing_orders import clear_cache as clear_standing_orders_cache
    clear_standing_orders_cache()

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
        proactive_loop.set_config(config.proactive_cognitive, cb_config=config.circuit_breaker, trait_config=config.trait_adaptive)
        if config.proactive_cognitive.duty_schedule.enabled:
            proactive_loop.set_duty_schedule(config.proactive_cognitive.duty_schedule)
        # PATCH(AD-517): Wire knowledge store for cooldown persistence
        if runtime._knowledge_store:
            proactive_loop._knowledge_store = runtime._knowledge_store
            await proactive_loop.restore_cooldowns()
        # AD-567g: Wire orientation service into proactive loop
        if hasattr(runtime, '_orientation_service') and runtime._orientation_service:
            proactive_loop.set_orientation_service(runtime._orientation_service)
        # --- AD-493: Novelty Gate ---
        runtime._novelty_gate = None
        if config.novelty_gate.enabled:
            from probos.cognitive.novelty_gate import NoveltyGate
            _novelty_gate = NoveltyGate.from_config(config.novelty_gate)
            proactive_loop.set_novelty_gate(_novelty_gate)
            runtime._novelty_gate = _novelty_gate
            logger.info("AD-493: NoveltyGate enabled (threshold=%.2f, decay=%.1fh)",
                         config.novelty_gate.similarity_threshold,
                         config.novelty_gate.decay_hours)
        await proactive_loop.start()
        logger.info("proactive-cognitive-loop started (interval=%ss)", config.proactive_cognitive.interval_seconds)

        # AD-595e: Wire qualification enforcement into proactive loop
        proactive_loop.set_qualification_config(config.qualification)
        if runtime.ontology and runtime.ontology.billet_registry:
            proactive_loop.set_billet_registry(runtime.ontology.billet_registry)

    # --- AD-558: Wire trust dampening dependencies ---
    if runtime.ontology:
        runtime.trust_network.set_department_lookup(
            lambda agent_id: runtime.ontology.get_agent_department(agent_id)
        )
    runtime.trust_network.set_event_callback(
        lambda event_type, data: runtime._emit_event(event_type, data)
    )

    # AD-585: Wire TieredKnowledgeLoader onto all CognitiveAgents.
    wired_count = _wire_tiered_knowledge_loader(runtime=runtime, config=config)
    if wired_count:
        logger.info("AD-585: TieredKnowledgeLoader wired to %d CognitiveAgents", wired_count)

    wired_task_context = _wire_task_context(runtime=runtime, config=config)
    if wired_task_context:
        logger.info("AD-586: TaskContext wired to %d CognitiveAgents", wired_task_context)

    tier_count = _populate_agent_tiers(runtime=runtime, config=config)
    if tier_count:
        logger.info("AD-571: Agent tiers populated for %d agents", tier_count)

    # AD-594: Late-bind expert selection registries into ConsultationProtocol.
    consultation_protocol = getattr(runtime, "_consultation_protocol", None)
    if consultation_protocol:
        consultation_protocol.set_capability_registry(runtime.capability_registry)
        if runtime.ontology and runtime.ontology.billet_registry:
            consultation_protocol.set_billet_registry(runtime.ontology.billet_registry)
        consultation_protocol.set_trust_network(runtime.trust_network)

    # --- AD-595a: Wire BilletRegistry event callback ---
    if runtime.ontology and runtime.ontology.billet_registry:
        runtime.ontology.billet_registry.set_event_callback(
            lambda event_type, data: runtime._emit_event(event_type, data)
        )
        logger.info("AD-595a: BilletRegistry wired")

    # AD-595c: Wire BilletRegistry into standing orders for template resolution
    if runtime.ontology and runtime.ontology.billet_registry:
        from probos.cognitive.standing_orders import set_billet_registry
        set_billet_registry(runtime.ontology.billet_registry)
        logger.info("AD-595c: Standing orders billet templating wired")

    # AD-651: Wire StepInstructionRouter into standing orders
    from probos.cognitive.standing_orders import set_step_router
    from probos.cognitive.step_instruction_router import StepInstructionRouter
    _step_router = StepInstructionRouter(config.step_instruction)
    set_step_router(_step_router)
    logger.info("AD-651: StepInstructionRouter wired into standing orders")

    # AD-595d: Wire QualificationStore into BilletRegistry
    billet_reg = runtime.ontology.billet_registry if runtime.ontology else None
    qual_store = getattr(runtime, '_qualification_store', None)
    if billet_reg and qual_store:
        billet_reg.set_qualification_store(qual_store)
        logger.info("AD-595d: Qualification store wired into BilletRegistry")

    # --- AD-618d: Wire BillRuntime event callback + billet registry ---
    if getattr(runtime, '_bill_runtime', None):
        runtime._bill_runtime.set_event_callback(
            lambda event_type, data: runtime._emit_event(event_type, data)
        )
        if runtime.ontology and runtime.ontology.billet_registry:
            runtime._bill_runtime.set_billet_registry(
                runtime.ontology.billet_registry
            )
        logger.info("AD-618d: BillRuntime wired (events + billet registry)")

        # AD-595e: Wire qualification enforcement config into BillRuntime
        runtime._bill_runtime.set_qualification_config(config.qualification)

    # --- AD-618e: Wire BillJITBridge (Bill step → skill proficiency) ---
    if (
        getattr(runtime, '_bill_runtime', None)
        and getattr(runtime, 'skill_bridge', None)
        and getattr(runtime, 'cognitive_skill_catalog', None)
        and getattr(runtime, 'skill_service', None)
    ):
        from probos.sop.jit_bridge import BillJITBridge
        _jit_bridge = BillJITBridge(
            skill_bridge=runtime.skill_bridge,
            catalog=runtime.cognitive_skill_catalog,
            skill_service=runtime.skill_service,
        )
        runtime.add_event_listener(
            _jit_bridge.on_step_completed,
            event_types={"bill_step_completed"},
        )
        logger.info("AD-618e: BillJITBridge wired (bill_step_completed → skill exercises)")

    # --- AD-557: Wire emergence metrics dependencies ---
    if runtime.dream_scheduler and runtime.dream_scheduler.engine:
        engine = runtime.dream_scheduler.engine
        # BF-106: Late-bind Phase 7 dependencies via public setters
        if runtime.ward_room:
            engine.set_ward_room(runtime.ward_room)
        if runtime.ontology:
            engine.set_get_department(
                lambda aid: runtime.ontology.get_agent_department(aid)
            )
        # BF-106: records_store is now constructor-injected (AD-551 wiring path,
        # moved from finalize.py to init_dreaming). Setter is no-op if already
        # set via constructor — only fires if Phase 4 had it as None.
        if hasattr(runtime, '_records_store') and runtime._records_store:
            engine.set_records_store(runtime._records_store)

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

        # AD-637c: JetStream consumer subscription (stream ensured in startup/nats.py)
        if getattr(runtime, 'nats_bus', None) and runtime.nats_bus.connected:
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
                ack_wait=300,  # BF-220: Must exceed LLM timeout (300s) to prevent redelivery
            )
            logger.info("AD-637c: WARDROOM JetStream stream + consumer wired")

        # ── AD-654b: Agent Cognitive Queues ──────────────────────────────
        from probos.cognitive.queue import AgentCognitiveQueue
        from probos.cognitive.circuit_breaker import BreakerState

        _intent_bus = runtime.intent_bus

        if _intent_bus is None:
            logger.debug("Startup [finalize]: intent_bus not available, skipping AD-654b/c/d wiring")
        else:
            # AD-654b: Inject response recording callback (replaces handler.__self__ reach-through)
            _wr_router = ward_room_router
            _intent_bus.set_record_response(_wr_router.record_agent_response)
            _intent_bus.set_emit_event(runtime.emit_event)  # BF-234: dedup telemetry

        # Create per-agent cognitive queues for crew agents.
        def _make_should_process(agent_ref: Any) -> Callable:
            """Create dequeue-time guard for an agent.

            Returns (allow, transient) tuple:
            - (True, _) → process the item
            - (False, True) → transient rejection, nak(delay=60) for redelivery
            - (False, False) → permanent rejection, term()

            Uses lazy lookup: runtime.proactive_loop resolved at dequeue time,
            not at queue construction time. Safe against wiring-order changes.
            """
            def _guard(item: Any, js_msg: Any) -> tuple[bool, bool]:
                # Lazy lookup — resolved at dequeue time, not construction time
                _pl = getattr(runtime, 'proactive_loop', None)
                if _pl:
                    breaker = _pl.circuit_breaker
                    status = breaker.get_status(agent_ref.id)
                    if status.get("state") == BreakerState.OPEN.value:
                        return (False, True)  # Transient — nak for redelivery
                return (True, False)
            return _guard

        if _intent_bus is not None:
            _queue_count = 0
            for agent in runtime.registry.all():
                if not is_crew_agent(agent, runtime.ontology):
                    continue

                queue = AgentCognitiveQueue(
                    agent_id=agent.id,
                    handler=agent.handle_intent,
                    should_process=_make_should_process(agent),
                    emit_event=runtime._emit_event,
                )
                _intent_bus.register_queue(agent.id, queue)
                await queue.start()
                _queue_count += 1

            logger.info("Startup [finalize]: AD-654b cognitive queues created for %d agents", _queue_count)

            # AD-654c: Create Dispatcher
            from probos.activation.dispatcher import Dispatcher

            dispatcher = Dispatcher(
                registry=runtime.registry,
                ontology=runtime.ontology,
                get_queue=_intent_bus._get_agent_queue,
                dispatch_async_fn=_intent_bus.dispatch_async,
                emit_event=runtime._emit_event,
            )
            runtime.dispatcher = dispatcher
            logger.info("Startup [finalize]: AD-654c Dispatcher created")

            # AD-654d: Wire dispatcher into internal emitters
            if runtime.work_item_store:
                runtime.work_item_store.attach_dispatcher(runtime.dispatcher)
            if runtime.ward_room:
                runtime.ward_room.attach_dispatcher(runtime.dispatcher, runtime.callsign_registry)

            # BF-223: Create per-agent JetStream dispatch consumers AFTER ship
            # commissioning has set the stable DID-based NATS prefix. During
            # startup, IntentBus.subscribe() defers dispatch consumers to avoid
            # the prefix race (consumers created with stale "probos.local" prefix
            # would never match messages published with the DID prefix).
            await runtime.intent_bus.create_dispatch_consumers()

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

    _sync_ontology_callsigns(runtime)

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

    # AD-595b: Wire BilletRegistry into onboarding
    if runtime.ontology and runtime.ontology.billet_registry:
        runtime.onboarding.set_billet_registry(runtime.ontology.billet_registry)

    # AD-526a: Wire RecreationService with late-init dependencies
    from probos.recreation.service import RecreationService
    runtime.recreation_service = RecreationService(
        ward_room=runtime.ward_room,
        records_store=runtime._records_store,
        emit_event_fn=runtime._emit_event,
        dispatcher=runtime.dispatcher,                # AD-654d
        callsign_registry=runtime.callsign_registry,  # AD-654d
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

    # --- AD-594: Crew consultation handler wiring ---
    if consultation_protocol:
        wired_consultation = 0
        for _agent in runtime.registry.all():
            if not is_crew_agent(_agent, runtime.ontology):
                continue
            if hasattr(_agent, "set_consultation_protocol"):
                _agent.set_consultation_protocol(consultation_protocol)
                wired_consultation += 1
        logger.info(
            "AD-594: ConsultationProtocol wired to %d crew agents",
            wired_consultation,
        )

    # --- AD-672: Per-agent concurrency management ---
    try:
        from probos.cognitive.concurrency_manager import ConcurrencyManager

        concurrency_config = getattr(config, "concurrency", None)
        if concurrency_config and concurrency_config.enabled:
            wired_concurrency = 0
            for agent in runtime.registry.all():
                if not is_crew_agent(agent, runtime.ontology):
                    continue
                if not hasattr(agent, "set_concurrency_manager"):
                    continue
                role = getattr(agent, "pool_group", "") or ""
                max_concurrent = concurrency_config.role_overrides.get(
                    role.lower(),
                    concurrency_config.default_max_concurrent,
                )
                manager = ConcurrencyManager(
                    agent_id=agent.id,
                    max_concurrent=max_concurrent,
                    queue_max_size=concurrency_config.queue_max_size,
                    capacity_warning_ratio=concurrency_config.capacity_warning_ratio,
                    emit_event_fn=runtime._emit_event,
                )
                agent.set_concurrency_manager(manager)
                wired_concurrency += 1
            logger.info(
                "AD-672: ConcurrencyManager wired to %d crew agents",
                wired_concurrency,
            )
    except Exception:
        logger.warning(
            "AD-672: ConcurrencyManager wiring failed; agents continue unmanaged",
            exc_info=True,
        )

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

    # BF-235: Always clear identity caches on stasis resume, regardless of
    # whether warm-boot orientation rendering is enabled. The caches are stale
    # because of the stasis boundary, not because of orientation policy.
    if runtime._lifecycle_state == "stasis_recovery":
        from probos.cognitive.standing_orders import clear_cache as clear_standing_orders_cache
        clear_standing_orders_cache()
        logger.info("BF-235: Cleared standing orders cache for stasis recovery")

        # BF-235: Evict decision caches so next decide() uses fresh instructions.
        from probos.cognitive.cognitive_agent import CognitiveAgent
        _evicted_total = 0
        for agent in runtime.registry.all():
            if is_crew_agent(agent, runtime.ontology):
                _evicted = CognitiveAgent.evict_cache_for_type(agent.agent_type)
                _evicted_total += _evicted
        if _evicted_total:
            logger.info("BF-235: Evicted %d decision cache entries for stasis recovery", _evicted_total)

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
                    _rendered = runtime._orientation_service.render_warm_boot_orientation(_ctx)
                    agent.set_orientation(_rendered, _ctx)
                    logger.debug(
                        "BF-235: %s orientation set — callsign=%s",
                        agent.agent_type,
                        getattr(agent, 'callsign', '?'),
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

    # AD-637d: System Events subscription wiring (stream ensured in startup/nats.py)
    # Placed after ALL add_event_listener() calls (game completion, Counselor, etc.)
    # so _setup_nats_event_subscriptions() catches every registered listener.
    if getattr(runtime, 'nats_bus', None) and runtime.nats_bus.connected:
        runtime._setup_nats_event_subscriptions()
        logger.info("AD-637d: SYSTEM_EVENTS %d listeners wired to NATS",
                    len(runtime._event_listeners))

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
