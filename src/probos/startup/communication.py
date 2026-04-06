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

if TYPE_CHECKING:
    from probos.config import SystemConfig
    from probos.identity import AgentIdentityRegistry
    from probos.mesh.intent import IntentBus
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)


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

        # Ward room event emitter — routes to both WebSocket and WardRoomRouter.
        # WardRoomRouter is wired later in finalize phase, so we use getattr guard.
        _ward_room_router_ref: list[Any] = [None]  # mutable ref for closure

        def _ward_room_emit(event_type: str, data: dict) -> None:
            emit_event_fn(event_type, data)
            router = _ward_room_router_ref[0]
            if router:
                asyncio.create_task(router.route_event(event_type, data))

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

        for agent in registry.all():
            if not is_crew_agent(agent):
                continue
            dept = get_department(agent.agent_type)
            if dept and dept in dept_channel_map:
                await ward_room.subscribe(agent.id, dept_channel_map[dept])
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
        )
        logger.info("bridge-alerts started")

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
    )
