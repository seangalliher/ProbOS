"""Phase 7: Communication & services — tasks, ward room, skills, ACM, ontology (AD-517).

Creates the persistent task store, workforce engine, Ward Room, assignment
service, bridge alerts, cognitive journal, skill framework, Agent Capital
Management, and vessel ontology.  Also wires ship commissioning (AD-441b)
and deferred crew birth certificates.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from probos.startup.results import CommunicationResult
from probos.types import Priority

if TYPE_CHECKING:
    from probos.config import SystemConfig
    from probos.identity import AgentIdentityRegistry
    from probos.mesh.intent import IntentBus
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)


async def _noop_handler(**kwargs: Any) -> None:
    """Placeholder handler for ontology-seeded tools.

    AD-423c will replace these with real service bindings during
    onboarding when ToolContext is established.
    """
    return None


async def init_communication(
    *,
    config: "SystemConfig",
    data_dir: Path,
    checkpoint_dir: Path,
    registry: "AgentRegistry",
    identity_registry: "AgentIdentityRegistry | None",
    episodic_memory: Any,
    hebbian_router: Any,
    emit_event_fn: Callable[..., Any],
    process_natural_language_fn: Callable[..., Any],
    register_workforce_resources_fn: Callable[..., Any],
    journal_prune_loop_fn: Callable[[], Any],
    nats_bus: Any = None,  # AD-637c: NATS event bus for JetStream ward room dispatch
) -> CommunicationResult:
    """Start communication services, scheduling, and identity commissioning.

    Returns a CommunicationResult with all created services.
    """
    logger.info("Startup [communication]: starting")

    # --- Persistent Task Store (Phase 25a) ---
    persistent_task_store = None
    if config.persistent_tasks.enabled:
        from probos.persistent_tasks import PersistentTaskStore

        persistent_task_store = PersistentTaskStore(
            db_path=str(data_dir / "scheduled_tasks.db"),
            emit_event=emit_event_fn,
            process_fn=process_natural_language_fn,
            tick_interval=config.persistent_tasks.tick_interval_seconds,
            checkpoint_dir=checkpoint_dir,
        )
        await persistent_task_store.start()
        logger.info("persistent-task-store started")
    else:
        # Fallback: still scan checkpoints for logging (original AD-405 behavior)
        from probos.cognitive.checkpoint import scan_checkpoints

        stale = scan_checkpoints(checkpoint_dir)
        if stale:
            logger.info(
                "Found %d incomplete DAG checkpoint(s) from previous session",
                len(stale),
            )
            for cp in stale:
                completed = sum(
                    1 for s in cp.node_states.values()
                    if s.get("status") == "completed"
                )
                logger.info(
                    "  - DAG %s: '%s' (%d/%d nodes completed)",
                    cp.dag_id[:8], cp.source_text[:60],
                    completed, len(cp.node_states),
                )

    # --- Workforce Scheduling Engine (AD-496) ---
    work_item_store = None
    if config.workforce.enabled:
        from probos.workforce import WorkItemStore

        work_item_store = WorkItemStore(
            db_path=str(data_dir / "workforce.db"),
            emit_event=emit_event_fn,
            tick_interval=config.workforce.tick_interval_seconds,
            config={
                "custom_work_types": config.workforce.custom_work_types,
                "custom_templates": config.workforce.custom_templates,
            },
        )
        await work_item_store.start()
        await register_workforce_resources_fn()
        logger.info("workforce-scheduling-engine started")

    # --- Ward Room (AD-407) ---
    ward_room = None
    if config.ward_room.enabled:
        from probos.ward_room import WardRoomService

        # Ward room event emitter — routes to WebSocket + JetStream (AD-637c).
        # When NATS is connected, events publish to JetStream for durable delivery.
        # When NATS is disconnected, falls back to create_task direct dispatch.
        _ward_room_router_ref: list[Any] = [None]  # mutable ref for fallback path only

        # AD-616: Semaphore bounds concurrent route_event() calls (fallback path only)
        _ward_room_semaphore = asyncio.Semaphore(
            getattr(config.ward_room, 'router_concurrency_limit', 10)
        )

        # AD-637c: Task set holds references to publish tasks (prevents GC + silent loss)
        _wardroom_publish_tasks: set[asyncio.Task] = set()

        def _ward_room_emit(event_type: str, data: dict) -> None:
            # Step 1: Always emit to WebSocket (synchronous)
            emit_event_fn(event_type, data)

            # Step 2: Route to WardRoomRouter via NATS or fallback
            if nats_bus and nats_bus.connected:
                # AD-637c: JetStream publish — durable, ordered, backpressure-aware
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    logger.warning("AD-637c: Ward room emit called outside event loop, skipping NATS publish")
                    return
                payload = {"event_type": event_type, **data}
                subject = f"wardroom.events.{event_type}"
                # AD-637f: Priority header for observability
                _author = data.get("author_id", "")
                _mentions = data.get("mentions", [])
                _is_captain = _author == "captain"
                _was_mentioned = "captain" in [
                    m.lower() for m in _mentions if isinstance(m, str)
                ]
                _priority = Priority.classify(
                    is_captain=_is_captain,
                    was_mentioned=_was_mentioned,
                )
                headers = {"X-Priority": _priority.value}
                task = loop.create_task(nats_bus.js_publish(subject, payload, headers=headers))
                _wardroom_publish_tasks.add(task)
                task.add_done_callback(_wardroom_publish_tasks.discard)
            else:
                # Fallback: direct dispatch via create_task (original behavior)
                router = _ward_room_router_ref[0]
                if router:
                    async def _bounded_route() -> None:
                        async with _ward_room_semaphore:
                            await router.route_event_coalesced(event_type, data)
                    asyncio.create_task(_bounded_route())

        ward_room = WardRoomService(
            db_path=str(data_dir / "ward_room.db"),
            emit_event=_ward_room_emit,
            episodic_memory=episodic_memory,
            hebbian_router=hebbian_router,
            identity_registry=identity_registry,  # BF-103
        )
        await ward_room.start()
        # Stash the mutable ref so finalize phase can wire the router
        ward_room._ward_room_router_ref = _ward_room_router_ref  # type: ignore[attr-defined]
        logger.info("ward-room started")

        # AD-425: Auto-subscribe crew agents to department + All Hands channels
        from probos.cognitive.standing_orders import get_department
        from probos.crew_utils import is_crew_agent

        wr_channels = await ward_room.list_channels()
        all_hands_id = None
        proposals_ch_id = None
        recreation_ch_id = None
        creative_ch_id = None
        dept_channel_map: dict[str, str] = {}
        for ch in wr_channels:
            if ch.name == "All Hands":
                all_hands_id = ch.id
            elif ch.name == "Improvement Proposals":
                proposals_ch_id = ch.id
            elif ch.name == "Recreation":
                recreation_ch_id = ch.id
            elif ch.name == "Creative":
                creative_ch_id = ch.id
            elif ch.channel_type == "department" and ch.department:
                dept_channel_map[ch.department] = ch.id

        # AD-621: Pre-compute agent_types that report to captain (bridge officers).
        # OntologyLoader is used because VesselOntologyService isn't created yet.
        _ad621_bridge_agents: set[str] = set()
        try:
            from probos.ontology.loader import OntologyLoader as _OntLoader

            _ont_dir = Path(__file__).resolve().parent.parent.parent.parent / "config" / "ontology"
            if _ont_dir.exists():
                _ont_loader = _OntLoader(_ont_dir)
                await _ont_loader.initialize()
                for _atype, _assignment in _ont_loader.assignments.items():
                    _post = _ont_loader.posts.get(_assignment.post_id)
                    if _post and _post.reports_to == "captain":
                        _ad621_bridge_agents.add(_atype)
        except Exception:
            pass  # Graceful degradation — no cross-dept subscriptions

        for agent in registry.all():
            if not is_crew_agent(agent):
                continue
            dept = get_department(agent.agent_type)
            if dept and dept in dept_channel_map:
                await ward_room.subscribe(agent.id, dept_channel_map[dept])
            # AD-621: Bridge officers (reports_to: captain) get all department channels.
            # Channel visibility is about observation (being in the room),
            # not capability access — separate concern from clearance.
            # Ontology service isn't created yet, so use OntologyLoader directly.
            if _ad621_bridge_agents and agent.agent_type in _ad621_bridge_agents:
                for dept_ch_id in dept_channel_map.values():
                    await ward_room.subscribe(agent.id, dept_ch_id)
            if all_hands_id:
                await ward_room.subscribe(agent.id, all_hands_id)
            if proposals_ch_id:
                await ward_room.subscribe(agent.id, proposals_ch_id)
            # AD-526a: Subscribe all crew to social channels
            if recreation_ch_id:
                await ward_room.subscribe(agent.id, recreation_ch_id)
            if creative_ch_id:
                await ward_room.subscribe(agent.id, creative_ch_id)

        # AD-416: Start Ward Room pruning loop
        archive_dir = data_dir / "ward_room_archive"
        await ward_room.start_prune_loop(config.ward_room, archive_dir)

        # AD-485: Archive old DM messages periodically
        async def _dm_archive_loop() -> None:
            while True:
                await asyncio.sleep(3600)
                try:
                    archived = await ward_room.archive_dm_messages(max_age_hours=24)
                    if archived:
                        logger.info("Archived %d old DM messages", archived)
                except Exception as e:
                    logger.debug("DM archival failed: %s", e)

        asyncio.get_event_loop().create_task(_dm_archive_loop())

    # --- Assignment Service (AD-408) ---
    assignment_service = None
    if config.assignments.enabled:
        from probos.assignment import AssignmentService

        assignment_service = AssignmentService(
            db_path=str(data_dir / "assignments.db"),
            emit_event=emit_event_fn,
            ward_room=ward_room,
        )
        await assignment_service.start()
        logger.info("assignment-service started")

    # --- Bridge Alerts (AD-410) ---
    bridge_alerts = None
    if config.bridge_alerts.enabled and ward_room:
        from probos.bridge_alerts import BridgeAlertService

        bridge_alerts = BridgeAlertService(
            cooldown_seconds=config.bridge_alerts.cooldown_seconds,
            trust_drop_threshold=config.bridge_alerts.trust_drop_threshold,
            trust_drop_alert_threshold=config.bridge_alerts.trust_drop_alert_threshold,
            resolve_clean_period=config.bridge_alerts.resolve_clean_period,
            default_dismiss_duration=config.bridge_alerts.default_dismiss_duration,
        )
        logger.info("bridge-alerts started")

    # --- Clearance Grant Store (AD-622) ---
    clearance_grant_store = None
    from probos.clearance_grants import ClearanceGrantStore

    clearance_grant_store = ClearanceGrantStore(
        db_path=str(data_dir / "clearance_grants.db"),
    )
    await clearance_grant_store.start()
    logger.info("clearance-grant-store started")

    # --- Tool Registry (AD-423a) ---
    from probos.tools.registry import ToolRegistry

    tool_registry = ToolRegistry()
    # Ontology seeding deferred until after VesselOntologyService init below

    # --- Cognitive Journal (AD-431) ---
    cognitive_journal = None
    if config.cognitive_journal.enabled:
        from probos.cognitive.journal import CognitiveJournal

        cognitive_journal = CognitiveJournal(
            db_path=str(data_dir / "cognitive_journal.db"),
        )
        await cognitive_journal.start()
        asyncio.create_task(journal_prune_loop_fn())
        logger.info("cognitive-journal started")

    # --- Skill Framework (AD-428) ---
    from probos.skill_framework import SkillRegistry, AgentSkillService

    skills_db = str(data_dir / "skills.db")
    skill_registry = SkillRegistry(db_path=skills_db)
    skill_service = AgentSkillService(db_path=skills_db, registry=skill_registry)
    await skill_registry.start()
    await skill_registry.register_builtins()
    await skill_service.start()
    logger.info("skill-framework started")

    # --- Cognitive Skill Catalog (AD-596a) ---
    from probos.cognitive.skill_catalog import CognitiveSkillCatalog

    skills_dir = Path(__file__).resolve().parent.parent.parent.parent / "config" / "skills"
    cognitive_catalog = CognitiveSkillCatalog(
        skills_dir=skills_dir,
        db_path=str(data_dir / "cognitive_skills.db"),
    )
    await cognitive_catalog.start()
    logger.info("cognitive-skill-catalog started")

    # --- Agent Capital Management (AD-427) ---
    from probos.acm import AgentCapitalService

    acm = AgentCapitalService(data_dir=data_dir)
    await acm.start()
    logger.info("acm started")

    # AD-441: Wire identity registry to ACM
    if acm and identity_registry:
        acm.set_identity_registry(identity_registry)

    # --- Vessel Ontology (AD-429a) ---
    ontology = None
    ontology_dir = Path(__file__).resolve().parent.parent.parent.parent / "config" / "ontology"
    if ontology_dir.exists():
        from probos.ontology import VesselOntologyService

        ontology = VesselOntologyService(ontology_dir, data_dir=data_dir)
        await ontology.initialize()
        # Wire all registered agents to their ontology posts
        for agent in registry.all():
            ontology.wire_agent(agent.agent_type, agent.id)
        logger.info("ontology initialized")

    # --- AD-423a: Seed tool registry from ontology tool capabilities ---
    if ontology:
        from probos.tools.adapters import DirectServiceAdapter
        from probos.tools.protocol import ToolType

        for tc in ontology.get_tool_capabilities():
            _type_map = {
                "ship_computer": ToolType.INFRA_SERVICE,
                "ward_room": ToolType.COMMUNICATION,
                "dreaming_engine": ToolType.INFRA_SERVICE,
            }
            adapter = DirectServiceAdapter(
                tool_id=tc.id,
                name=tc.name,
                description=tc.description,
                handler=_noop_handler,
                tool_type=_type_map.get(tc.provider, ToolType.INFRA_SERVICE),
            )
            tool_registry.register(
                adapter,
                provider=tc.provider,
                tags=[tc.id, tc.provider],
            )

    # --- Tool Permission Store (AD-423b) ---
    from probos.tools.permissions import ToolPermissionStore

    tool_permission_store = ToolPermissionStore(
        db_path=str(data_dir / "tool_permissions.db"),
    )
    await tool_permission_store.start()
    tool_registry.set_permission_store(tool_permission_store)
    tool_registry.set_event_callback(emit_event_fn)
    logger.info("tool-permission-store started")

    logger.info("tool-registry started (%d tools)", tool_registry.count())

    # --- Ship Commissioning (AD-441b) ---
    if ontology and identity_registry:
        vi = ontology.get_vessel_identity()
        await identity_registry.start(
            instance_id=vi.instance_id,
            vessel_name=vi.name,
            version=config.system.version,
        )

        # AD-441c: Issue deferred crew birth certificates
        from probos.crew_utils import is_crew_agent as _is_crew

        for agent in registry.all():
            if _is_crew(agent, ontology) and not getattr(agent, 'did', ''):
                try:
                    from probos.cognitive.standing_orders import get_department as _get_dept

                    dept = ontology.get_agent_department(agent.agent_type) or ""
                    post = ontology.get_post_for_agent(agent.agent_type)
                    post_id = post.id if post else ""
                    if not dept:
                        dept = _get_dept(agent.agent_type) or "unassigned"

                    _callsign = getattr(agent, 'callsign', '') or agent.agent_type
                    cert = await identity_registry.resolve_or_issue(
                        slot_id=agent.id,
                        agent_type=agent.agent_type,
                        callsign=_callsign,
                        instance_id=vi.instance_id,
                        vessel_name=vi.name,
                        department=dept,
                        post_id=post_id,
                        baseline_version=config.system.version,
                    )
                    agent.sovereign_id = cert.agent_uuid
                    agent.did = cert.did
                except Exception as e:
                    logger.debug("Deferred identity skipped for %s: %s", agent.id, e)

    # --- Wire ontology ↔ skill service (AD-429b) ---
    if ontology and skill_service:
        ontology.set_skill_service(skill_service)

    logger.info("Startup [communication]: complete")
    return CommunicationResult(
        persistent_task_store=persistent_task_store,
        work_item_store=work_item_store,
        ward_room=ward_room,
        assignment_service=assignment_service,
        bridge_alerts=bridge_alerts,
        cognitive_journal=cognitive_journal,
        skill_registry=skill_registry,
        skill_service=skill_service,
        acm=acm,
        ontology=ontology,
        clearance_grant_store=clearance_grant_store,
        tool_registry=tool_registry,
        tool_permission_store=tool_permission_store,
        cognitive_skill_catalog=cognitive_catalog,
    )
