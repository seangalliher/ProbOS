"""Phase 6: Structural services — SIF, initiative, build, tasks, profiles (AD-517).

Creates the semantic layer, persists manifest, reconciles trust,
starts SIF, initiative engine, build dispatcher, task tracker,
service profiles, and directive store.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from probos.startup.results import StructuralServicesResult

if TYPE_CHECKING:
    from probos.cognitive.emergent_detector import EmergentDetector
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.intent import IntentBus
    from probos.mesh.routing import HebbianRouter
    from probos.substrate.pool import ResourcePool
    from probos.substrate.registry import AgentRegistry
    from probos.substrate.spawner import AgentSpawner

logger = logging.getLogger(__name__)


async def init_structural_services(
    *,
    config: "SystemConfig",
    data_dir: Path,
    registry: "AgentRegistry",
    pools: dict[str, "ResourcePool"],
    spawner: "AgentSpawner",
    trust_network: "TrustNetwork",
    intent_bus: "IntentBus",
    hebbian_router: "HebbianRouter",
    episodic_memory: Any,
    emergent_detector: "EmergentDetector",
    emit_event_fn: Callable[..., Any],
    persist_manifest_fn: Callable[..., Any],
    on_build_complete_fn: Callable[..., Any],
) -> tuple["StructuralServicesResult", Any]:
    """Create structural services and return (result, semantic_layer).

    Returns a tuple because semantic_layer needs to be assigned to
    runtime separately from the rest of the structural services.
    """
    logger.info("Startup [structural_services]: starting")

    # Create SemanticKnowledgeLayer (AD-243) — only when episodic memory available
    semantic_layer = None
    if episodic_memory:
        try:
            from probos.knowledge.semantic import SemanticKnowledgeLayer

            db_dir = Path(episodic_memory.db_path).parent
            semantic_layer = SemanticKnowledgeLayer(
                db_path=db_dir / "semantic",
                episodic_memory=episodic_memory,
            )
            await semantic_layer.start()
            logger.info("Semantic knowledge layer started")
        except Exception as e:
            logger.warning("Semantic knowledge layer initialization failed: %s — continuing without", e)
            semantic_layer = None

    # Persist agent manifest (Phase 14c)
    await persist_manifest_fn()

    # Reconcile trust store — remove stale entries from previous sessions (AD-280)
    active_ids = {a.id for a in registry.all()}
    removed = trust_network.reconcile(active_ids)
    if removed:
        logger.info("trust-reconcile removed=%d stale entries", removed)

    # Start Structural Integrity Field (AD-370)
    from probos.sif import StructuralIntegrityField

    sif = StructuralIntegrityField(
        trust_network=trust_network,
        intent_bus=intent_bus,
        hebbian_router=hebbian_router,
        spawner=spawner,
        pool_manager=pools,
        episodic_memory=episodic_memory,
        eviction_audit=getattr(episodic_memory, "_eviction_audit", None) if episodic_memory else None,
    )
    await sif.start()

    # Start InitiativeEngine (AD-381)
    from probos.initiative import InitiativeEngine

    initiative = InitiativeEngine(
        on_event=lambda evt: emit_event_fn(evt.get("type", ""), evt.get("data", {})),
        on_proposal=lambda p: logger.info("Initiative: %s", p.action_detail),
    )
    if sif:
        initiative.set_sif(sif)
    if emergent_detector:
        initiative.set_detector(emergent_detector)
    await initiative.start()

    # Start Automated Builder Dispatch (AD-375)
    from probos.build_queue import BuildQueue
    from probos.worktree_manager import WorktreeManager
    from probos.build_dispatcher import BuildDispatcher

    _repo_root = str(Path(__file__).resolve().parent.parent.parent.parent)
    build_queue = BuildQueue()
    _worktree_mgr = WorktreeManager(repo_root=_repo_root)
    build_dispatcher = BuildDispatcher(
        queue=build_queue,
        worktree_mgr=_worktree_mgr,
        on_build_complete=on_build_complete_fn,
    )
    await build_dispatcher.start()
    logger.info("build-dispatcher started")

    # --- Task Tracker (AD-316) ---
    from probos.task_tracker import TaskTracker

    task_tracker = TaskTracker(on_event=emit_event_fn)
    logger.info("task-tracker started")

    # --- Service Profiles (AD-382) ---
    from probos.service_profile import ServiceProfileStore
    from probos.agents.http_fetch import HttpFetchAgent

    service_profiles = ServiceProfileStore(
        db_path=data_dir / "service_profiles.db"
    )
    HttpFetchAgent.set_profile_store(service_profiles)
    logger.info("service-profiles started")

    # --- Directive Store (AD-386) ---
    from probos.directive_store import DirectiveStore
    from probos.cognitive.standing_orders import set_directive_store

    directive_store = None
    try:
        directive_store = DirectiveStore(
            db_path=str(Path(data_dir) / "directives.db")
        )
        set_directive_store(directive_store)
        logger.info("DirectiveStore initialized")
    except Exception:
        logger.exception("DirectiveStore init failed (non-fatal)")

    # --- Bill System (AD-618d) ---
    from probos.sop.runtime import BillRuntime
    from probos.sop.loader import load_builtin_bills, load_custom_bills

    bill_runtime = BillRuntime(config=config.bill)
    logger.info("AD-618d: BillRuntime created")

    # Load and register built-in bills (AD-618c)
    builtin_bills = load_builtin_bills()
    for defn in builtin_bills.values():
        bill_runtime.register_definition(defn)

    # Load and register custom bills from Ship's Records
    _custom_bills_dir = data_dir / "ship-records" / "bills"
    custom_bills = load_custom_bills(_custom_bills_dir)
    for defn in custom_bills.values():
        bill_runtime.register_definition(defn)

    if builtin_bills or custom_bills:
        logger.info(
            "AD-618d: Registered %d bill definition(s) (%d built-in, %d custom)",
            len(builtin_bills) + len(custom_bills),
            len(builtin_bills),
            len(custom_bills),
        )

    logger.info("Startup [structural_services]: complete")
    result = StructuralServicesResult(
        sif=sif,
        initiative=initiative,
        build_queue=build_queue,
        build_dispatcher=build_dispatcher,
        task_tracker=task_tracker,
        service_profiles=service_profiles,
        directive_store=directive_store,
        bill_runtime=bill_runtime,
    )
    return result, semantic_layer
