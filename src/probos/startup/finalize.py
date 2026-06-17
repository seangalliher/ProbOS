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


def _wire_anomaly_window(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-673: Wire AnomalyWindowManager and subscribe to signal events."""
    if not config.anomaly_window.enabled:
        return False

    from probos.cognitive.anomaly_window import AnomalyWindowManager
    from probos.events import EventType

    emit_fn = getattr(runtime, "_emit_event", None)
    add_listener = getattr(runtime, "add_event_listener", None)
    manager = AnomalyWindowManager(
        config=config.anomaly_window,
        emit_event_fn=emit_fn,
        add_event_listener_fn=add_listener,
    )

    episodic_memory = getattr(runtime, "episodic_memory", None)
    if episodic_memory is not None and hasattr(episodic_memory, "set_anomaly_window_manager"):
        episodic_memory.set_anomaly_window_manager(manager)

    if add_listener is not None:
        async def on_signal_event(event: Any) -> None:
            if isinstance(event, dict):
                event_type = event.get("type", "")
                data = event.get("data", {})
            else:
                event_type = getattr(event, "event_type", getattr(event, "type", ""))
                data = getattr(event, "data", {})

            event_type_value = event_type.value if isinstance(event_type, EventType) else str(event_type)
            if event_type_value == EventType.TRUST_CASCADE_WARNING.value:
                manager.open_window("trust_cascade", str(data))
            elif event_type_value == EventType.LLM_HEALTH_CHANGED.value:
                status = ""
                if isinstance(data, dict):
                    status = data.get("new_status") or data.get("status", "")
                if status in ("degraded", "offline"):
                    manager.open_window("llm_degraded", f"LLM status: {status}")
                elif status in ("operational", "healthy") and manager.is_active():
                    active_window = manager.get_active_window()
                    if active_window:
                        manager.close_window(active_window)

        add_listener(
            on_signal_event,
            event_types=[
                EventType.TRUST_CASCADE_WARNING.value,
                EventType.LLM_HEALTH_CHANGED.value,
            ],
        )

    runtime._anomaly_window_manager = manager
    return True


async def _wire_desktop_ux(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-751: Wire Desktop UX Surface (tray, hotkey, autostart, notifications)."""
    cfg = getattr(config, "desktop", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.experience.desktop.tray import TrayManager
    from probos.experience.desktop.hotkey import HotkeyListener
    from probos.experience.desktop.lifecycle import DesktopLifecycle
    from probos.experience.desktop.notifications import NotificationCenter

    # Single-instance lock (must acquire before anything else)
    lifecycle = DesktopLifecycle(cfg)
    acquired = await lifecycle.acquire_lock()
    if not acquired:
        logger.warning("AD-751: Another instance of ProbOS is already running (lock file exists)")
        return False

    # Register autostart if configured
    if cfg.autostart_enabled:
        await lifecycle.register_autostart()
        logger.info("AD-751: Autostart registration completed")

    # Initialize tray manager
    tray_manager = TrayManager(cfg)
    tray_manager.set_status("idle")
    
    # Start hotkey listener
    hotkey_listener = HotkeyListener(cfg)
    await hotkey_listener.start_listening(cfg.hotkey)
    
    # Initialize notification center
    notification_center = NotificationCenter(cfg)
    
    # Store in runtime for later access
    runtime.desktop_lifecycle = lifecycle
    runtime.tray_manager = tray_manager
    runtime.hotkey_listener = hotkey_listener
    runtime.notification_center = notification_center
    
    logger.info(
        "AD-751: Desktop UX Surface initialized (tray=%s, hotkey=%s, autostart=%s)",
        cfg.tray_autostart,
        cfg.hotkey,
        cfg.autostart_enabled,
    )
    return True


def _wire_creative_expression(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-525 v1: Wire CreativeSkillsRegistry + CreativeOutputWriter."""
    cfg = getattr(config, "creative_expression", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.creative.skills_registry import CreativeSkillsRegistry
    from probos.creative.output_writer import CreativeOutputWriter

    emit_fn = getattr(runtime, "emit_event", None)
    registry = CreativeSkillsRegistry()
    registry._emit_event_fn = emit_fn
    writer = CreativeOutputWriter(runtime, cfg)
    writer._emit_event_fn = emit_fn

    runtime.creative_skills_registry = registry  # public attribute (Wave 5 convention #1)
    runtime.creative_output_writer = writer      # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-525: Creative Expression v1 initialized (default_classification=%s; %d skills)",
        cfg.default_classification,
        len(registry.list_skills()),
    )
    return True


def _wire_classification_gate(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-530 v1: Wire ClassificationGate observational disclosure gate."""
    cfg = getattr(config, "classification_gate", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.security.classification import ClassificationGate

    emit_fn = getattr(runtime, "emit_event", None)
    runtime.classification_gate = ClassificationGate(runtime, emit_event=emit_fn)  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-530: ClassificationGate initialized (%d patterns)",
        runtime.classification_gate.pattern_count,
    )
    return True


def _wire_browser_tool(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-706: Register BrowserTool in the ToolRegistry (default-disabled).

    Synchronous portion of the wiring; the async portion (RecordingReaper
    start, AD-706b) is invoked separately via ``_start_recording_reaper``
    from the async ``finalize_startup`` caller.
    """
    cfg = getattr(config, "browser_tool", None)
    if not cfg or not cfg.enabled:
        return False
    if getattr(runtime, "tool_registry", None) is None:
        logger.warning("AD-706: tool_registry not available; skipping BrowserTool wiring")
        return False

    # Lazy Playwright import — missing optional dep at import time must not crash startup.
    try:
        from playwright.async_api import async_playwright  # noqa: F401  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "AD-706: playwright not installed; install probos[browser] and run 'playwright install chromium'"
        )
        return False

    from probos.tools.browser.tool import BrowserTool

    emit_fn = getattr(runtime, "emit_event", None)
    audit_log = getattr(runtime, "audit_log", None)
    browser_tool = BrowserTool(
        config=cfg,
        audit_log=audit_log,
        emit_event=emit_fn,
        runtime=runtime,
    )
    runtime.tool_registry.register(
        browser_tool,
        domain="*",
        tags=["browser", "computer_use"],
        provider="ship_computer",
        enabled=True,
        default_permissions={
            "ensign": "none",
            "lieutenant": "read",
            "commander": "write",
            "senior_officer": "full",
        },
        concurrency="concurrent",
    )
    runtime.browser_tool = browser_tool  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-706: BrowserTool registered (headless=%s, allowlist=%s)",
        cfg.headless, cfg.domain_allowlist,
    )

    # AD-706f / AD-1016: credential vault — opt-in via cfg.credential_vault.enabled.
    # Backend selector (cfg.credential_vault.backend):
    #   "file" (default): EncryptedFileCredentialVault — requires a non-empty
    #     auth.crew_scope_token (Fernet KEK derivation). Honest-degrade to None.
    #   "keychain" (AD-1016): KeyringCredentialBackend over the OS keychain, which
    #     is already encrypted at rest — so it requires enabled=True but NOT a
    #     crew_scope_token (the metadata sidecar holds no secret values).
    runtime.credential_vault = None
    vault_cfg = getattr(cfg, "credential_vault", None)
    auth_cfg = getattr(config, "auth", None)
    crew_token = getattr(auth_cfg, "crew_scope_token", "") if auth_cfg else ""
    backend = getattr(vault_cfg, "backend", "file") if vault_cfg is not None else "file"
    if vault_cfg is not None and vault_cfg.enabled and backend == "keychain":
        try:
            from pathlib import Path
            from probos.security.keyring_backend import KeyringCredentialBackend
            vault = KeyringCredentialBackend(
                service_name=vault_cfg.keyring_service_name,
                index_path=Path(vault_cfg.keyring_index_path),
            )
            runtime.credential_vault = vault
            n_refs = len(getattr(vault, "_refs", {}))
            logger.info(
                "AD-1016 keychain credential backend enabled (%d credentials indexed)",
                n_refs,
            )
        except Exception:
            logger.warning(
                "AD-1016: keychain credential backend construction failed; "
                "runtime.credential_vault stays None (vault disabled this run)",
                exc_info=True,
            )
    elif vault_cfg is not None and vault_cfg.enabled and crew_token:
        try:
            from pathlib import Path
            from probos.tools.browser.credentials import (
                EncryptedFileCredentialVault,
                _derive_kek,
            )
            kek = _derive_kek(crew_token)
            vault = EncryptedFileCredentialVault(
                path=Path(vault_cfg.file_path),
                kek=kek,
                crew_scope_token=crew_token,
            )
            runtime.credential_vault = vault
            # Sync count via the in-memory loaded state (avoid async dispatch
            # at startup time — vault constructor already loaded the sidecar).
            n_refs = len(getattr(vault, "_refs", {}))
            logger.info("AD-706f credential vault enabled (%d credentials loaded)", n_refs)
        except Exception:
            logger.warning(
                "AD-706f: credential vault construction failed; "
                "runtime.credential_vault stays None (vault disabled this run)",
                exc_info=True,
            )
    elif vault_cfg is not None and vault_cfg.enabled and backend == "file" and not crew_token:
        logger.warning(
            "AD-706f: credential_vault.enabled=True but auth.crew_scope_token "
            "is empty; vault disabled. Set auth.crew_scope_token in "
            "config/system.yaml to enable."
        )

    # AD-706b: RecordingReaper attribute is declared here; the actual async
    # start happens via ``_start_recording_reaper`` from the async caller.
    runtime.recording_reaper = None
    # AD-733-1: AttachmentReaper attribute -- async-started below.
    runtime.attachment_reaper = None
    # AD-986d: TranscriptReaper attribute -- async-started below (default-off).
    runtime.transcript_reaper = None
    return True


def _wire_mesh_intent_tools(*, runtime: Any) -> list[str]:
    """AD-909: Seed the universal mesh read-intents into the PERSISTENT catalog.

    ``web_search`` / ``read_page`` / ``http_fetch`` are wrapped as first-class
    Tools by ``register_mesh_intent_tools`` (AD-856) — but before AD-909 that ran
    only lazily inside the per-dispatch executor, so the three reads were absent
    from ``GET /api/tools`` (and the AD-885 capability lens / AD-899 certification
    console) until an agent first used one. That left the Captain unable to *see*
    web-search/page-read/http-fetch in the catalog, or to turn one off for a
    specific agent — even though the AD-423/894 ``ToolAccessGrant`` model fully
    supports a per-agent off-switch.

    This registers them into ``runtime.tool_registry`` at startup, tagged
    ``provider="mesh"`` and READ-for-all (empty ``default_permissions`` → the
    registry's ship-wide default grants READ to every rank). Registration is
    idempotent — the dispatch path's later call finds them already present and
    skips. The off-switch is a reversible, audit-retained Captain
    ``is_restriction`` grant (permission ``none``), which ``resolve_permission``
    restricts the READ-for-all base down to NONE; no new consensus gate is
    introduced (Minimal Authority). Honest-degrade: returns ``[]`` and logs when
    the registry or intent bus is unavailable.
    """
    registry = getattr(runtime, "tool_registry", None)
    intent_bus = getattr(runtime, "intent_bus", None)
    if registry is None or intent_bus is None:
        logger.warning(
            "AD-909: tool_registry or intent_bus unavailable; universal mesh "
            "read-intents not seeded into the persistent catalog (they will "
            "still register lazily on first agentic dispatch)"
        )
        return []
    from probos.cognitive.agentic_dispatch import register_mesh_intent_tools

    ids = register_mesh_intent_tools(registry, intent_bus, provider="mesh")
    logger.info(
        "AD-909: seeded %d universal mesh read-intents into the tool catalog: %s",
        len(ids), ", ".join(ids),
    )
    return ids


async def _start_recording_reaper(*, runtime: Any, config: "SystemConfig") -> None:
    """AD-706b: start the recording retention reaper if recording is enabled."""
    cfg = getattr(config, "browser_tool", None)
    if not cfg or not getattr(cfg, "enabled", False):
        return
    if not getattr(cfg, "recording_enabled", False):
        return
    try:
        from probos.tools.browser.recording_reaper import RecordingReaper
        emit_fn = getattr(runtime, "emit_event", None)
        reaper = RecordingReaper(cfg=cfg, emit_event_fn=emit_fn)
        await reaper.start()
        runtime.recording_reaper = reaper
        logger.info(
            "AD-706b: RecordingReaper started (interval=%ds, retention=%dd, dir=%s)",
            cfg.recording_reaper_interval_seconds,
            cfg.recording_retention_days,
            cfg.recording_dir,
        )
    except Exception:
        logger.warning(
            "AD-706b: RecordingReaper start failed; recordings will not be reaped this run",
            exc_info=True,
        )


async def _start_attachment_reaper(*, runtime: Any, config: "SystemConfig") -> None:
    """AD-733-1: start the AttachmentStore retention reaper.

    Active when ``perception.enabled`` (ephemeral frames present) or when
    ``attachments.max_store_bytes > 0`` (LRU safety net active for any
    producer). Tier-2 honest-degrade on construction failure -- the
    runtime keeps booting; attachments simply will not be reaped.
    """
    perception_cfg = getattr(config, "perception", None)
    attachments_cfg = getattr(config, "attachments", None)
    if attachments_cfg is None:
        return
    perception_enabled = bool(getattr(perception_cfg, "enabled", False))
    lru_enabled = int(getattr(attachments_cfg, "max_store_bytes", 0)) > 0
    if not (perception_enabled or lru_enabled):
        return
    try:
        from probos.attachments.reaper import AttachmentReaper
        from probos.routers.chat import _get_attachment_store

        store = _get_attachment_store(runtime)
        emit_fn = getattr(runtime, "emit_event", None)
        reaper = AttachmentReaper(
            store,
            perception_cfg=perception_cfg,
            attachments_cfg=attachments_cfg,
            event_emitter=emit_fn,
        )
        await reaper.start()
        runtime.attachment_reaper = reaper
        logger.info(
            "AD-733-1: AttachmentReaper started "
            "(interval=%ds, frame_retention=%ds, max_store_bytes=%d)",
            int(getattr(perception_cfg, "reaper_interval_seconds", 60)),
            int(getattr(perception_cfg, "frame_retention_seconds", 300)),
            int(getattr(attachments_cfg, "max_store_bytes", 0)),
        )
    except Exception:
        logger.warning(
            "AD-733-1: AttachmentReaper start failed; "
            "attachments will not be reaped this run",
            exc_info=True,
        )


async def _start_transcript_reaper(*, runtime: Any, config: "SystemConfig") -> None:
    """AD-986d: start the transcript retention reaper when retention is enabled.

    Default-off: ``memory.transcript_retention_days <= 0`` keeps the recording
    forever (opt-in), so the reaper is not started and the transcript store is
    byte-identical. Tier-2 honest-degrade on construction failure -- the runtime
    keeps booting; transcripts simply are not reaped this run.
    """
    mem_cfg = getattr(config, "memory", None)
    if mem_cfg is None:
        return
    retention_days = int(getattr(mem_cfg, "transcript_retention_days", 0))
    if retention_days <= 0:
        return
    store = getattr(runtime, "chat_thread_store", None)
    if store is None:
        return
    try:
        from probos.threads.transcript_reaper import TranscriptReaper

        interval = int(getattr(mem_cfg, "transcript_reaper_interval_seconds", 3600))
        reaper = TranscriptReaper(
            store, retention_days=retention_days, interval_seconds=interval
        )
        await reaper.start()
        runtime.transcript_reaper = reaper
        logger.info(
            "AD-986d: TranscriptReaper started (interval=%ds, retention=%dd)",
            interval,
            retention_days,
        )
    except Exception:
        logger.warning(
            "AD-986d: TranscriptReaper start failed; "
            "transcripts will not be reaped this run",
            exc_info=True,
        )


def _wire_curriculum_registry(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-507 v1: Wire CoreKnowledgeCurriculumRegistry (read-only catalog)."""
    cfg = getattr(config, "crew_development", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.crew_development.curriculum import CoreKnowledgeCurriculumRegistry

    emit_fn = getattr(runtime, "emit_event", None)
    registry = CoreKnowledgeCurriculumRegistry()
    registry.emit_event = emit_fn
    runtime.curriculum_registry = registry  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-507: Crew Development Framework v1 initialized (curriculum registry; %d modules)",
        len(registry.list_modules()),
    )
    return True


def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-509 v1: Wire BootCampPhaseTracker (in-memory observational)."""
    cfg = getattr(config, "boot_camp_phase", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.crew_development.boot_camp import BootCampPhaseTracker

    emit_fn = getattr(runtime, "emit_event", None)
    tracker = BootCampPhaseTracker()
    tracker.emit_event = emit_fn
    runtime.boot_camp_tracker = tracker  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-509: Boot Camp Phase Tracker v1 initialized (5 phases + COMPLETED; observational)"
    )
    return True


def _wire_emergence_collector(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-454: Wire EvidenceCollector if enabled. Default off.

    Pure observer — subscribes to WARD_ROOM_POST_CREATED, classifies posts
    against the AD-454 taxonomy via fast-tier LLM, writes OBS-NNNN.yaml
    files. No trust, Hebbian, or consensus participation.
    """
    cfg = getattr(config, "emergence_collector", None)
    if not cfg or not cfg.enabled:
        return False

    if getattr(runtime, "llm_client", None) is None:
        logger.warning(
            "AD-454: EvidenceCollector wants llm_client but runtime.llm_client "
            "is None; collector NOT wired. Configure an LLM client to enable."
        )
        return False
    if getattr(runtime, "ward_room", None) is None:
        logger.warning(
            "AD-454: EvidenceCollector wants ward_room but runtime.ward_room "
            "is None; collector NOT wired."
        )
        return False

    from probos.cognitive.evidence_collector import EvidenceCollector
    from probos.events import EventType

    collector = EvidenceCollector(
        runtime=runtime,
        confidence_threshold=cfg.confidence_threshold,
        dedup_window_seconds=cfg.dedup_window_seconds,
        output_dir=cfg.output_dir,
        llm_tier=cfg.llm_tier,
        trial_id=cfg.trial_id,
        thread_context_limit=cfg.thread_context_limit,
        max_reasoning_chars=cfg.max_reasoning_chars,
    )
    runtime.evidence_collector = collector  # public attribute (Wave 5 convention #1)
    runtime.add_event_listener(
        collector.on_ward_room_post,
        event_types=[EventType.WARD_ROOM_POST_CREATED.value],
    )
    logger.info(
        "AD-454: EvidenceCollector wired (trial=%s, threshold=%.2f, "
        "dedup_window=%.0fs, output=%s)",
        cfg.trial_id, cfg.confidence_threshold,
        cfg.dedup_window_seconds, cfg.output_dir,
    )
    return True


def _wire_birth_chamber(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-486 v1: Wire Holodeck Birth Chamber + Department scheduler.

    Default-False per AD-695 transitional-flag precedent. When disabled,
    no chamber is constructed; production graduation gates short-circuit
    to ``True`` via the ``runtime.birth_chamber is None`` check.
    """
    cfg = getattr(config, "holodeck_birth_chamber", None)
    if not cfg or not cfg.enabled:
        return False

    import asyncio as _asyncio

    from probos.holodeck import BirthChamber, DepartmentActivationScheduler

    emit_fn = getattr(runtime, "emit_event", None)
    chamber = BirthChamber(config=cfg, emit_event_fn=emit_fn)
    chamber.set_personal_ontology_prober(
        getattr(runtime, "personal_ontology_prober", None)
    )
    chamber.set_curriculum_registry(
        getattr(runtime, "curriculum_registry", None)
    )
    # AD-488 circuit_breaker is a leading-underscore attr on
    # ProactiveCognitiveLoop (predates Wave 5 convention #1). Demeter
    # exception documented; promote to public in a later wave.
    proactive = getattr(runtime, "proactive_loop", None)
    if proactive is not None:
        chamber.set_circuit_breaker(getattr(proactive, "_circuit_breaker", None))
    chamber.set_callsign_registry(getattr(runtime, "callsign_registry", None))
    chamber.set_episodic_memory(getattr(runtime, "episodic_memory", None))

    runtime.birth_chamber = chamber  # public attribute (Wave 5 convention #1)

    scheduler = DepartmentActivationScheduler(
        department_order=list(cfg.department_order),
        get_phase_fn=chamber.get_current_phase,
    )
    runtime.department_activation_scheduler = scheduler  # public attribute

    # Late-bind onto onboarding service so wire_agent can admit agents
    if getattr(runtime, "onboarding", None) is not None:
        try:
            runtime.onboarding.set_birth_chamber(chamber)
        except AttributeError:
            logger.warning(
                "AD-486: onboarding.set_birth_chamber not available; chamber will not auto-admit"
            )

    # AD-486: Late-bind onto AssignmentService for Ward Room subscription gating
    _assn = getattr(runtime, "assignment_service", None)
    if _assn is not None:
        try:
            _assn.set_birth_chamber(chamber)
        except AttributeError:
            logger.warning(
                "AD-486: assignment_service.set_birth_chamber not available; "
                "Ward Room subscription will not be deferred"
            )

    if cfg.auto_advance_enabled:
        try:
            runtime.birth_chamber_advance_task = _asyncio.create_task(
                chamber.run_advance_loop()
            )
        except RuntimeError:
            # No running loop yet (cold-start before serve()) — finalize
            # is invoked from an async context in normal boot, so this
            # branch is defensive only.
            logger.warning(
                "AD-486: no running event loop; advance task not started"
            )
            runtime.birth_chamber_advance_task = None
    else:
        runtime.birth_chamber_advance_task = None

    logger.info(
        "AD-486: Birth Chamber initialized (auto_advance=%s, departments=%s)",
        cfg.auto_advance_enabled, list(cfg.department_order),
    )
    return True


def _wire_holodeck_team_simulations(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-510 v1: Wire TeamSimulationOrchestrator + TeamScenarioRegistry.

    Default-False per AD-695 transitional-flag precedent. When disabled,
    no orchestrator is constructed; ``runtime.team_simulation_orchestrator``
    and ``runtime.team_scenario_registry`` are NOT set.
    """
    cfg = getattr(config, "team_simulations", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.holodeck.team_simulations import (
        TeamScenarioRegistry,
        TeamSimulationOrchestrator,
        TeamSimulationStore,
    )

    emit_fn = getattr(runtime, "emit_event", None)

    data_dir: Any = None
    if cfg.persist_to_sqlite:
        ship_data_dir = getattr(runtime, "data_dir", None)
        if ship_data_dir is not None:
            from pathlib import Path as _Path
            data_dir = _Path(ship_data_dir) / cfg.data_subdir
            data_dir.mkdir(parents=True, exist_ok=True)

    registry = TeamScenarioRegistry()
    registry.emit_event = emit_fn
    runtime.team_scenario_registry = registry  # public (Wave 5 conv #1)

    store = TeamSimulationStore(data_dir=data_dir)

    orchestrator = TeamSimulationOrchestrator(
        config=cfg,
        store=store,
        emit_event_fn=emit_fn,
        qualification_harness=getattr(runtime, "qualification_harness", None),
        team_scenario_registry=registry,
    )
    runtime.team_simulation_orchestrator = orchestrator  # public (Wave 5 conv #1)

    logger.info(
        "AD-510: Holodeck team simulations v1 initialized "
        "(harness=%s, registry=%s, persist=%s)",
        orchestrator.qualification_harness is not None,
        orchestrator.team_scenario_registry is not None,
        cfg.persist_to_sqlite,
    )
    return True


def _wire_holodeck_scenarios(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-539b v1: Wire HolodeckGapBridge — gap-driven scenario generation.

    Default-False per AD-695 transitional-flag precedent. When disabled,
    no bridge is constructed; ``runtime.holodeck_gap_bridge`` is not set
    and AD-539 ``trigger_qualification_if_needed`` continues to run with
    its default ``holodeck_bridge=None`` behavior (byte-for-byte
    identical to pre-AD-539b semantics).
    """
    cfg = getattr(config, "holodeck_scenarios", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.holodeck.scenarios import (
        GapScenarioGenerator,
        HolodeckGapBridge,
        HolodeckScenarioStore,
    )

    emit_fn = getattr(runtime, "emit_event", None)

    data_dir: Any = None
    if cfg.persist_to_sqlite:
        ship_data_dir = getattr(runtime, "data_dir", None)
        if ship_data_dir is not None:
            from pathlib import Path as _Path
            data_dir = _Path(ship_data_dir) / cfg.data_subdir
            data_dir.mkdir(parents=True, exist_ok=True)

    generator = GapScenarioGenerator(category_fallback=cfg.category_fallback)
    store = HolodeckScenarioStore(data_dir=data_dir)

    bridge = HolodeckGapBridge(
        config=cfg,
        generator=generator,
        store=store,
        emit_event_fn=emit_fn,
        qualification_harness=getattr(runtime, "qualification_harness", None),
        scenario_registry=getattr(runtime, "discovery_scenario_registry", None),
    )
    runtime.holodeck_gap_bridge = bridge  # public attr (Wave 5 conv #1)

    logger.info(
        "AD-539b: Holodeck scenario generation v1 initialized "
        "(harness=%s, registry=%s, persist=%s)",
        bridge.qualification_harness is not None,
        bridge.scenario_registry is not None,
        cfg.persist_to_sqlite,
    )
    return True


def _wire_discovery_learning(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-512 v1: Wire DiscoveryScenarioRegistry, StrengthMap,
    CapabilityConfidenceScorer, and ZPDCalibrator (observational substrate).
    """
    cfg = getattr(config, "discovery_learning", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.crew_development.discovery import (
        CapabilityConfidenceScorer,
        DiscoveryScenarioRegistry,
        StrengthMap,
        ZPDCalibrator,
    )

    emit_fn = getattr(runtime, "emit_event", None)

    scenario_registry = DiscoveryScenarioRegistry()
    scenario_registry.emit_event = emit_fn
    runtime.discovery_scenario_registry = scenario_registry  # public (Wave 5 conv #1)

    strength_map = StrengthMap()
    strength_map.emit_event = emit_fn
    runtime.strength_map = strength_map  # public (Wave 5 conv #1)

    confidence_scorer = CapabilityConfidenceScorer(
        prior_alpha=cfg.confidence_prior_alpha,
        prior_beta=cfg.confidence_prior_beta,
    )
    confidence_scorer.emit_event = emit_fn
    runtime.capability_confidence_scorer = confidence_scorer  # public (Wave 5 conv #1)

    zpd_calibrator = ZPDCalibrator(
        lower_offset=cfg.zpd_lower_bound,
        upper_offset=cfg.zpd_upper_bound,
    )
    zpd_calibrator.emit_event = emit_fn
    runtime.zpd_calibrator = zpd_calibrator  # public (Wave 5 conv #1)

    logger.info(
        "AD-512: Discovery Learning v1 initialized "
        "(%d scenarios; Beta(α=%.2f, β=%.2f) priors; ZPD band [%.2f, %.2f])",
        len(scenario_registry.list_scenarios()),
        cfg.confidence_prior_alpha,
        cfg.confidence_prior_beta,
        cfg.zpd_lower_bound,
        cfg.zpd_upper_bound,
    )
    return True


def _wire_ship_state_snapshot(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-683 v1: Wire ShipStateSnapshotBuilder (cold-start onboarding)."""
    cfg = getattr(config, "ship_state_snapshot", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.onboarding import ShipStateSnapshotBuilder

    emit_fn = getattr(runtime, "emit_event", None)
    builder = ShipStateSnapshotBuilder(runtime, emit_event=emit_fn)
    runtime.ship_state_snapshot = builder  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-683: ShipStateSnapshotBuilder v1 initialized (cold-start orientation)"
    )
    return True


def _wire_autonomy_boundaries(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-511 v1: Wire InviolableBoundaryRegistry + BoundaryViolationDetector."""
    cfg = getattr(config, "autonomy_boundaries", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.security.autonomy_boundaries import (
        BoundaryViolationDetector,
        InviolableBoundaryRegistry,
    )

    emit_fn = getattr(runtime, "emit_event", None)
    registry = InviolableBoundaryRegistry()
    detector = BoundaryViolationDetector(registry, emit_event=emit_fn)
    runtime.boundary_registry = registry  # public attribute (Wave 5 convention #1)
    runtime.boundary_detector = detector  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-511: Autonomy Boundaries v1 initialized (%d boundaries; %d patterns; observational)",
        len(registry.list_boundaries()),
        detector.pattern_count,
    )
    return True


def _wire_duty_scope_provider(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-508 v1: Wire DutyScopeProvider observational helper."""
    cfg = getattr(config, "scoped_cognition", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.scoped_cognition import DutyScopeProvider

    emit_fn = getattr(runtime, "emit_event", None)
    runtime.duty_scope_provider = DutyScopeProvider(runtime, emit_event=emit_fn)  # public attribute (Wave 5 convention #1)
    logger.info("AD-508: DutyScopeProvider v1 initialized (observational)")
    return True


def _wire_chain_optimizer(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-659 v1 + AD-659b: Wire ChainOptimizer with apply path + persistence."""
    cfg = getattr(config, "chain_optimizer", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.chain_optimizer import ChainOptimizer

    emit_fn = getattr(runtime, "emit_event", None)
    interval = getattr(cfg, "analysis_interval_seconds", 0)
    try:
        interval_int = int(interval)
    except (TypeError, ValueError):
        interval_int = 0
    apply_enabled = bool(getattr(cfg, "apply_enabled", False))
    optimizer = ChainOptimizer(
        runtime,
        analysis_window=cfg.analysis_window,
        latency_p95_ms_floor=cfg.latency_p95_ms_floor,
        success_rate_floor=cfg.success_rate_floor,
        error_rate_ceiling=cfg.error_rate_ceiling,
        min_samples_per_group=cfg.min_samples_per_group,
        apply_enabled=apply_enabled,
        analysis_interval_seconds=interval_int,
        emit_event=emit_fn,
    )
    runtime.chain_optimizer = optimizer
    if interval_int > 0:
        optimizer.start_scheduled_loop()
        # Mirror task onto runtime for shutdown observability (matches
        # `runtime._flush_task` precedent).
        runtime.chain_optimizer_analyze_task = optimizer._loop_task
    logger.info(
        "AD-659b: ChainOptimizer initialized (apply_enabled=%s, "
        "analysis_interval_seconds=%s)",
        apply_enabled,
        interval_int,
    )
    return True


async def _wire_optimization_counselor(
    *, runtime: Any, config: "SystemConfig",
) -> bool:
    """AD-659c v1: Wire OptimizationCounselor watchdog for AD-659b apply path."""
    cfg = getattr(config, "chain_optimizer_counselor", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.optimization_counselor import OptimizationCounselor

    counselor = OptimizationCounselor(
        runtime,
        baseline_window_seconds=cfg.baseline_window_seconds,
        observation_window_seconds=cfg.observation_window_seconds,
        success_rate_drop_floor=cfg.success_rate_drop_floor,
        min_samples_per_window=cfg.min_samples_per_window,
        auto_revert_enabled=cfg.auto_revert_enabled,
    )
    runtime.optimization_counselor = counselor  # public attribute (Wave 5 conv #1)
    try:
        await counselor.start()
    except Exception:
        logger.warning(
            "AD-659c: OptimizationCounselor.start() failed", exc_info=True,
        )
    logger.info(
        "AD-659c: OptimizationCounselor initialized "
        "(auto_revert_enabled=%s, observation_window=%.1fs, drop_floor=%.2f)",
        cfg.auto_revert_enabled,
        cfg.observation_window_seconds,
        cfg.success_rate_drop_floor,
    )
    return True


async def _wire_edge_backfill(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-689: Wire EdgeBackfillService and run a one-shot backfill on warm boot
    if the knowledge_edges table is empty (or force=True)."""
    cfg = getattr(config, "edge_backfill", None)
    if not cfg or not cfg.enabled:
        return False

    knowledge_edges = getattr(runtime, "knowledge_edges", None)
    if knowledge_edges is None:
        logger.debug("AD-689: knowledge_edges unavailable; skipping backfill")
        return False

    from pathlib import Path
    from probos.knowledge.backfill import EdgeBackfillService

    service = EdgeBackfillService(
        knowledge_edges=knowledge_edges,
        ontology=getattr(runtime, "ontology", None),
        hebbian_router=getattr(runtime, "hebbian_router", None),
        episodic_memory=getattr(runtime, "episodic_memory", None),
        decisions_paths=[Path(p) for p in cfg.decisions_paths],
        hebbian_threshold=cfg.hebbian_threshold,
    )
    runtime.edge_backfill = service  # public attribute (Wave 5 conv #1)

    if not cfg.run_on_warm_boot:
        logger.info("AD-689: EdgeBackfillService wired; warm-boot run disabled by config")
        return True

    if not cfg.force:
        try:
            existing = await knowledge_edges.find_edges(limit=1)
        except Exception:
            existing = []
            logger.debug("AD-689: find_edges probe failed; will run backfill", exc_info=True)
        if existing:
            logger.info(
                "AD-689: knowledge_edges already populated; skipping warm-boot backfill "
                "(use edge_backfill.force=true to override)"
            )
            return True

    try:
        result = await service.backfill_all()
        logger.info(
            "AD-689: backfill complete (ontology=%d hebbian=%d episodes=%d "
            "decisions=%d total=%d duration=%.0fms)",
            result.ontology, result.hebbian, result.episodes, result.decisions,
            result.total, result.duration_ms,
        )
    except Exception:
        logger.warning("AD-689: warm-boot backfill failed", exc_info=True)
    return True


async def _wire_relationship_inference(
    *, runtime: Any, config: "SystemConfig"
) -> bool:
    """AD-690: Wire SQLiteRejectionCache and attach knowledge_edges +
    rejection_cache to DreamingEngine for Step 7i relationship inference.

    Skips silently if dreaming is disabled, knowledge_edges is unavailable,
    or relationship_inference_enabled is False.
    """
    dream_cfg = getattr(config, "dreaming", None)
    if not dream_cfg or not getattr(dream_cfg, "relationship_inference_enabled", False):
        return False

    knowledge_edges = getattr(runtime, "knowledge_edges", None)
    if knowledge_edges is None:
        logger.debug(
            "AD-690: relationship inference enabled but knowledge_edges not "
            "wired; skipping (depends on AD-687)."
        )
        return False

    dreaming_engine = getattr(runtime, "dreaming_engine", None)
    if dreaming_engine is None:
        logger.debug(
            "AD-690: relationship inference enabled but dreaming_engine not "
            "wired; skipping."
        )
        return False

    from pathlib import Path

    from probos.knowledge.rejection_cache import SQLiteRejectionCache

    data_dir = getattr(config, "data_dir", "data")
    db_path = str(Path(data_dir) / "rejection_cache.sqlite")
    cache = SQLiteRejectionCache(db_path)
    try:
        await cache.start()
    except Exception as exc:
        logger.warning(
            "AD-690: rejection cache failed to start at %s: %s; "
            "Step 7i will be skipped",
            db_path,
            exc,
        )
        return False

    runtime.rejection_cache = cache

    if hasattr(dreaming_engine, "set_knowledge_edges"):
        dreaming_engine.set_knowledge_edges(knowledge_edges)
    if hasattr(dreaming_engine, "set_rejection_cache"):
        dreaming_engine.set_rejection_cache(cache)
    return True


def _wire_causal_reasoner(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-660 v1 + AD-660b: Wire CausalReasoner template-fill service."""
    cfg = getattr(config, "causal_reasoning", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.causal_reasoning import CausalReasoner

    runtime.causal_reasoner = CausalReasoner(
        runtime,
        max_tokens=cfg.max_tokens,
        tier=cfg.tier,
        max_invocations_per_hour=cfg.max_invocations_per_hour,
    )
    logger.info(
        "AD-660b: CausalReasoner initialized "
        "(template + journal + concern hook + emergence hooks; "
        "rate=%d/hr/bucket)",
        cfg.max_invocations_per_hour,
    )
    return True


def _wire_diagnostic_context(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-661 v1: Wire DiagnosticContextService pull-based assembly service."""
    cfg = getattr(config, "diagnostic_context", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.diagnostic_context import DiagnosticContextService

    runtime.diagnostic_context_service = DiagnosticContextService(
        runtime,
        default_budget_tokens=cfg.default_budget_tokens,
        chain_trace_ratio=cfg.chain_trace_ratio,
        procedure_ratio=cfg.procedure_ratio,
        episode_ratio=cfg.episode_ratio,
        records_ratio=cfg.records_ratio,
        chars_per_token=cfg.chars_per_token,
        redistribute_remainder=cfg.redistribute_remainder,
    )
    logger.info(
        "AD-661: DiagnosticContextService v1 initialized "
        "(pull-based, keyword-only, budget=%d)",
        cfg.default_budget_tokens,
    )
    return True


def _wire_nl_graph_query(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-691 v1: Wire NLGraphQueryService LLM-driven NL→graph router."""
    cfg = getattr(config, "nl_graph_query", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.nl_graph_query import NLGraphQueryService

    runtime.nl_graph_query = NLGraphQueryService(
        runtime,
        default_max_hops=cfg.default_max_hops,
        default_limit=cfg.default_limit,
        llm_tier=cfg.llm_tier,
        extraction_max_tokens=cfg.extraction_max_tokens,
        synthesis_max_tokens=cfg.synthesis_max_tokens,
    )
    logger.info(
        "AD-691: NLGraphQueryService v1 initialized "
        "(default_max_hops=%d, default_limit=%d, llm_tier=%s)",
        cfg.default_max_hops, cfg.default_limit, cfg.llm_tier,
    )
    return True


def _wire_edge_classification(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-692 v1: Wrap ``runtime.knowledge_edges`` with the classification
    gate. Re-stitches Oracle Tier 6 so the wrapper (not the bare store) is
    consulted on graph queries.

    Resolver maps ``requester_agent_id`` -> RecallTier name via the AD-635
    helpers (``effective_recall_tier`` + ``resolve_billet_clearance`` +
    ``resolve_active_grants``).
    """
    cfg = getattr(config, "knowledge_edge_classification", None)
    if not cfg or not cfg.enabled:
        return False
    if getattr(runtime, "knowledge_edges", None) is None:
        # Underlying store disabled (knowledge_edges.enabled=False); no-op.
        return False

    from probos.knowledge.edge_classification import (
        ClassificationGatedKnowledgeEdgeStore,
        KnowledgeEdgeClassificationGate,
    )
    from probos.earned_agency import (
        effective_recall_tier,
        resolve_active_grants,
        resolve_billet_clearance,
    )

    gate = KnowledgeEdgeClassificationGate(
        default_classification=cfg.default_classification,
    )

    def _resolve_tier(agent_id: str) -> str:
        try:
            # BF-265: System services get ORACLE tier (full graph access).
            from probos.cognitive.oracle_service import ORACLE_SYSTEM_AGENT_ID
            if agent_id == ORACLE_SYSTEM_AGENT_ID:
                return "oracle"

            registry = getattr(runtime, "registry", None)
            agent = registry.get(agent_id) if registry else None
            agent_type = getattr(agent, "agent_type", agent_id) if agent else agent_id
            rank_holder = getattr(agent, "rank", None) if agent else None
            billet = resolve_billet_clearance(
                agent_type, getattr(runtime, "ontology", None),
            )
            grants = resolve_active_grants(
                agent_id, getattr(runtime, "clearance_grant_store", None),
            )
            tier = effective_recall_tier(rank_holder, billet, grants)
            return tier.value  # RecallTier is a str Enum
        except Exception:
            logger.debug(
                "AD-692: resolver failed for agent=%s; defaulting to basic",
                agent_id, exc_info=True,
            )
            return "basic"

    gate.set_clearance_resolver(_resolve_tier)
    wrapper = ClassificationGatedKnowledgeEdgeStore(runtime.knowledge_edges, gate)
    runtime.knowledge_edges = wrapper
    runtime.edge_classification_gate = gate

    # Re-stitch Oracle Tier 6 so it sees the wrapper, not the bare store.
    oracle = getattr(runtime, "_oracle_service", None)
    if oracle is not None:
        try:
            oracle.attach_knowledge_graph(wrapper)
        except Exception:
            logger.warning(
                "AD-692: failed to re-attach wrapped knowledge graph to Oracle; "
                "Tier 6 graph queries continue against the bare store",
                exc_info=True,
            )

    logger.info(
        "AD-692: KnowledgeEdgeClassificationGate v1 initialized "
        "(default_classification=%s; Oracle Tier 6 re-stitched)",
        cfg.default_classification,
    )
    return True


def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-635 / AD-635b / AD-635c: Wire ClinicalTelemetryService +
    optional audit persistence + optional circuit-breaker history persistence."""
    cfg = getattr(config, "clinical_telemetry", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.clinical_telemetry import ClinicalTelemetryService

    audit_store = None
    if cfg.audit_persistence_enabled:
        # AD-635b: double-gated — service must be enabled AND persistence
        # opted in. Default cfg.audit_persistence_enabled=False keeps the
        # AD-635 v1 in-memory-only contract.
        from probos.cognitive.clinical_audit_store import ClinicalAuditStore
        from pathlib import Path as _Path
        _data_dir = getattr(runtime, "data_dir", None)
        _audit_db = (
            str(_Path(_data_dir) / _Path(cfg.audit_db_path).name)
            if _data_dir is not None else cfg.audit_db_path
        )
        audit_store = ClinicalAuditStore(db_path=_audit_db)
        logger.info(
            "AD-635b: ClinicalAuditStore wired (db_path=%s)",
            _audit_db,
        )

    breaker_history_store = None
    if cfg.circuit_breaker_history_persistence_enabled:
        # AD-635c: double-gated — service must be enabled AND breaker-
        # history persistence opted in. Default disabled flag keeps the
        # AD-488 / AD-506a in-memory-only contract.
        from probos.cognitive.circuit_breaker_history_store import (
            CircuitBreakerHistoryStore,
        )
        from pathlib import Path as _Path2
        _data_dir2 = getattr(runtime, "data_dir", None)
        _breaker_db = (
            str(_Path2(_data_dir2) / _Path2(cfg.circuit_breaker_history_db_path).name)
            if _data_dir2 is not None else cfg.circuit_breaker_history_db_path
        )
        breaker_history_store = CircuitBreakerHistoryStore(
            db_path=_breaker_db,
        )
        logger.info(
            "AD-635c: CircuitBreakerHistoryStore wired (db_path=%s)",
            _breaker_db,
        )

    service = ClinicalTelemetryService(
        runtime,
        audit_max_entries=cfg.audit_max_entries,
        audit_store=audit_store,
        circuit_breaker_history_store=breaker_history_store,
    )
    # AD-635c: stash the breaker store for the late-bind block at the
    # tail of finalize_startup. The proactive-loop wirer runs AFTER us;
    # the late-bind reads this attribute and calls
    # ``runtime.proactive_loop.circuit_breaker.set_history_store(...)``.
    service._pending_breaker_store = breaker_history_store
    runtime.clinical_telemetry = service
    logger.info(
        "AD-635: ClinicalTelemetryService initialized "
        "(3 domains: dream_history + chain_traces + circuit_breaker_history; "
        "clearance gate FULL+; audit_persistence=%s; breaker_history_persistence=%s)",
        bool(audit_store), bool(breaker_history_store),
    )
    return True


def _wire_knowledge_browser(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-562: Construct runtime.knowledge_browser if records_store available.

    Default-False per AD-695 transitional precedent. Pure sync wirer —
    no asyncio task creation. Returns False if records store unavailable
    (tier-2 WARNING).
    """
    cfg = getattr(config, "knowledge_browser", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        return False
    store = getattr(runtime, "_records_store", None)
    if store is None:
        logger.warning("AD-562: knowledge_browser enabled but _records_store unavailable")
        return False
    from probos.knowledge.backlinks import KnowledgeBrowserService
    quality_engine = getattr(runtime, "_notebook_quality_engine", None)
    runtime.knowledge_browser = KnowledgeBrowserService(
        records_store=store,
        notebook_quality_engine=quality_engine,
        max_graph_nodes=cfg.max_graph_nodes,
        max_graph_edges=cfg.max_graph_edges,
        jaccard_threshold=cfg.jaccard_threshold,
        max_suggestions_per_entry=cfg.max_suggestions_per_entry,
        index_refresh_seconds=cfg.index_refresh_seconds,
    )
    return True


def _wire_spatial_explorer(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-520: Construct runtime.spatial_layout from YAML or default.

    Default-False per AD-695 transitional precedent. Pure sync wirer —
    no asyncio task creation, no other side-effects. The explorer is a
    read-only HXI surface backed by REST consumption of existing data.
    """
    cfg = getattr(config, "spatial_explorer", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        return False
    from probos.ontology.spatial import load_spatial_layout

    path = cfg.spatial_layout_path or "config/ontology/spatial.yaml"
    layout = load_spatial_layout(path)
    runtime.spatial_layout = layout
    logger.info(
        "AD-520: spatial explorer wired with %d decks (path=%s)", len(layout.decks), path
    )
    return True


def _wire_mcp_app_host(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-597: install MCPAppRegistry, register internal games, schedule external discovery."""
    cfg = config.mcp_app_host
    if not cfg.enabled:
        return False
    from pathlib import Path
    from probos.mcp_apps.registry import MCPAppRegistry
    from probos.mcp_apps.game_app import (
        register_game_resources,
        register_game_tools,
    )
    registry = MCPAppRegistry(
        internal_default_csp=cfg.internal_default_csp,
        external_default_csp=cfg.external_default_csp,
    )
    if hasattr(runtime, "emit_event"):
        registry.set_event_callback(runtime.emit_event)
    runtime.mcp_app_registry = registry

    if cfg.serve_internal_games and getattr(runtime, "recreation_service", None):
        try:
            register_game_tools(registry, runtime.recreation_service)
        except Exception:
            logger.warning("AD-597b: register_game_tools failed", exc_info=True)
        bundles_dir = (
            Path(cfg.bundles_dir)
            if cfg.bundles_dir
            else Path(__file__).resolve().parent.parent / "mcp_apps" / "bundles"
        )
        try:
            register_game_resources(registry, bundles_dir)
        except Exception:
            logger.warning("AD-597b: register_game_resources failed", exc_info=True)

    if cfg.discover_external_apps and getattr(runtime, "mcp_bridge", None):
        from probos.mcp_apps.external_discovery import discover_external_apps

        async def _bg() -> None:
            try:
                await discover_external_apps(registry, runtime.mcp_bridge)
            except Exception:
                logger.warning("AD-597f: external discovery failed", exc_info=True)

        task = asyncio.create_task(_bg(), name="mcp-app-external-discovery")
        runtime._mcp_app_external_discovery_task = task
    return True


def _wire_native_swe_harness(
    *,
    runtime: Any,
    config: "SystemConfig",
    tool_executor: Any,
) -> bool:
    """AD-543/544/548/549: Register native SWE tools, attach blocked-paths hook,
    construct ``NativeBuilderHarness``, expose on runtime.

    Tool registration is unconditional (cheap, observable). Harness construction
    happens regardless; route selection in ``SoftwareEngineerAgent.perceive()``
    gates by ``config.native_swe_harness.enabled``.
    """
    try:
        from probos.cognitive.swe_harness.tools import register_native_swe_tools
        from probos.cognitive.swe_harness.policies import make_blocked_paths_hook
        from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
        from probos.cognitive.swe_harness.session_compactor import SessionCompactor

        registry = getattr(runtime, "tool_registry", None)
        if registry is None or tool_executor is None:
            logger.info(
                "AD-549: tool_registry / tool_executor missing on runtime; "
                "skipping native SWE harness wire-up"
            )
            return False

        cfg = getattr(config, "native_swe_harness", None)
        if cfg is None:
            return False

        count = register_native_swe_tools(registry, runtime)
        if cfg.blocked_paths:
            tool_executor.add_pre_hook(make_blocked_paths_hook(cfg.blocked_paths))

        llm_client = getattr(runtime, "llm_client", None)
        if llm_client is None:
            logger.info(
                "AD-549: llm_client missing; skipping NativeBuilderHarness construction"
            )
            return False

        harness = NativeBuilderHarness(
            runtime=runtime,
            llm_client=llm_client,
            tool_executor=tool_executor,
            tool_registry=registry,
            max_iterations=cfg.max_iterations,
            max_fix_iterations=cfg.max_fix_iterations,
            token_budget=cfg.token_budget,
            compactor=SessionCompactor(),
            compaction_threshold=int(cfg.compaction_threshold_pct * 100_000),
        )
        runtime.native_builder_harness = harness
        logger.info(
            "AD-549: Native SWE harness wired (tools=%d, enabled=%s, blocked_paths=%d)",
            count,
            cfg.enabled,
            len(cfg.blocked_paths),
        )
        return True
    except Exception:
        logger.warning(
            "AD-549: Native SWE harness wire-up failed; route selection will degrade to visiting/legacy",
            exc_info=True,
        )
        return False


def _wire_process_chain_registry(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-647b v1: Initialize ProcessChainRegistry and register built-in chains.

    Currently registered:
      - SCOUT_REPORT_CHAIN (chain_id="scout_report")
    """
    cfg = getattr(config, "process_chain_registry", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.process_chains import ProcessChainRegistry
    from probos.cognitive.scout import SCOUT_REPORT_CHAIN

    registry = ProcessChainRegistry()
    registry.register_chain(SCOUT_REPORT_CHAIN)
    runtime.process_chain_registry = registry
    logger.info(
        "AD-647b: ProcessChainRegistry initialized (chains=%s)",
        registry.list_chains(),
    )
    return True


def _wire_consultation_workspaces(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-594a v1: Wire WorkspaceRegistry session-scoped consultation workspaces.

    Registry is purely on-demand: nothing is materialized until an agent calls
    ``runtime.consultation_workspaces.create(...)``. Requires ``runtime.records_store``
    (AD-434) to be adopted; if missing, no-op.
    """
    cfg = getattr(config, "consultation_workspaces", None)
    if not cfg or not cfg.enabled:
        return False
    records_store = getattr(runtime, "records_store", None)
    if records_store is None:
        logger.info(
            "AD-594a: records_store unavailable; consultation_workspaces skipped"
        )
        return False

    from probos.consultation import WorkspaceRegistry, build_input_processor

    runtime.consultation_workspaces = WorkspaceRegistry(
        records_store,
        root_path=cfg.root_path,
        input_processor=build_input_processor(cfg.input_processor),
    )
    logger.info(
        "AD-594a: WorkspaceRegistry v1 initialized "
        "(root=%s, input_processor=%s)",
        cfg.root_path, cfg.input_processor,
    )
    return True


def _wire_consultation_delivery(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-594d v1: Wire DeliveryPipeline + built-in adapters.

    Requires ``runtime.consultation_workspaces`` (the registry from AD-594a).
    Tier-2 log-and-degrade: missing registry -> no-op + INFO log. Adapter
    construction failures (e.g. LocalFileAdapter with bogus allowed_roots)
    are caught per-adapter so a single bad adapter does not disable the
    pipeline.
    """
    cfg = getattr(config, "consultation_delivery", None)
    if not cfg or not cfg.enabled:
        return False
    registry = getattr(runtime, "consultation_workspaces", None)
    if registry is None:
        logger.info(
            "AD-594d: consultation_workspaces unavailable; consultation_delivery skipped"
        )
        return False

    from pathlib import Path
    from probos.consultation.delivery import (
        DeliveryPipeline, GitHubAdapter, LocalFileAdapter,
    )

    pipeline = DeliveryPipeline(registry)

    if cfg.local_file_enabled:
        try:
            roots = [Path(r).expanduser().resolve() for r in cfg.local_file_allowed_roots]
            pipeline.register_adapter(LocalFileAdapter(allowed_roots=roots))
        except Exception:
            logger.warning(
                "AD-594d: LocalFileAdapter ctor failed; adapter not registered",
                exc_info=True,
            )
    if cfg.github_enabled:
        try:
            pipeline.register_adapter(GitHubAdapter(token_env=cfg.github_token_env))
        except Exception:
            logger.warning(
                "AD-594d: GitHubAdapter ctor failed; adapter not registered",
                exc_info=True,
            )

    runtime.consultation_delivery = pipeline  # public attribute (Wave 5 conv #1)
    logger.info(
        "AD-594d: DeliveryPipeline v1 initialized (adapters=%s, default_requires_approval=%s)",
        pipeline.list_adapters(), cfg.default_requires_approval,
    )
    return True


def _wire_consultation_dispatch(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-594c v1: Wire ParallelDispatcher.

    Requires ``runtime.consultation_workspaces`` (AD-594a),
    ``runtime.work_item_store`` (AD-496), AND ``runtime.records_store`` (for
    plan-file reads). Tier-2 log-and-degrade: missing any dependency -> no-op
    + INFO log.
    """
    cfg = getattr(config, "consultation_dispatch", None)
    if not cfg or not cfg.enabled:
        return False
    registry = getattr(runtime, "consultation_workspaces", None)
    if registry is None:
        logger.info(
            "AD-594c: consultation_workspaces unavailable; consultation_dispatch skipped"
        )
        return False
    work_item_store = getattr(runtime, "work_item_store", None)
    if work_item_store is None:
        logger.info(
            "AD-594c: work_item_store unavailable; consultation_dispatch skipped"
        )
        return False
    records_store = getattr(runtime, "records_store", None)
    if records_store is None:
        logger.info(
            "AD-594c: records_store unavailable; consultation_dispatch skipped"
        )
        return False

    from probos.consultation.dispatch import ParallelDispatcher

    emit_fn = getattr(runtime, "emit_event", None)
    runtime.consultation_dispatcher = ParallelDispatcher(  # public attr (Wave 5 conv #1)
        workspace_registry=registry,
        work_item_store=work_item_store,
        records_store=records_store,
        config=cfg,
        emit_event=emit_fn,
    )
    logger.info(
        "AD-594c: ParallelDispatcher v1 initialized (default_work_type=%s, blocker_threshold=%.1fs)",
        cfg.default_work_type, cfg.blocker_threshold_seconds,
    )
    return True


def _wire_crew_orchestrator(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-867: wire :class:`CrewOrchestrator` behind ``runtime.crew_orchestrator``.

    Threads the dormant crew collaborators (AD-859 executor, AD-860 verifier,
    AD-861 synthesizer, AD-864 assignment resolver, AD-865 delegator) into one
    end-to-end pipeline. Gated on ``config.agentic_dispatch.orchestrator_enabled``
    (default OFF). Tier-2 log-and-degrade: any missing shared dependency -> no-op
    + INFO log.
    """
    cfg = getattr(config, "agentic_dispatch", None)
    if not cfg or not getattr(cfg, "orchestrator_enabled", False):
        return False

    work_item_store = getattr(runtime, "work_item_store", None)
    registry = getattr(runtime, "registry", None)
    capability_registry = getattr(runtime, "capability_registry", None)
    ontology = getattr(runtime, "ontology", None)
    trust_network = getattr(runtime, "trust_network", None)
    llm_client = getattr(runtime, "llm_client", None)
    missing = [
        name
        for name, dep in (
            ("work_item_store", work_item_store),
            ("registry", registry),
            ("capability_registry", capability_registry),
            ("ontology", ontology),
            ("trust_network", trust_network),
            ("llm_client", llm_client),
        )
        if dep is None
    ]
    if missing:
        logger.info(
            "AD-867: crew_orchestrator skipped; missing dependencies: %s",
            ", ".join(missing),
        )
        return False

    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.crew_assignment import CrewAssignmentResolver
    from probos.cognitive.crew_delegation import CrewDelegator
    from probos.cognitive.crew_executor import CrewTaskExecutor
    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_synth import CrewSynthesizer
    from probos.cognitive.crew_verifier import SubtaskVerifier

    emit_fn = getattr(runtime, "emit_event", None)
    order_manager = getattr(runtime, "order_manager", None)
    episodic_memory = getattr(runtime, "episodic_memory", None)
    try:
        from probos.routers.chat import _get_attachment_store

        attachment_store = _get_attachment_store(runtime)
    except Exception:
        # Honest-degrade: synthesis stores no attachment provenance without a
        # store, but the pipeline still completes.
        attachment_store = None

    agentic_executor = WorkItemAgenticExecutor(llm_client=llm_client)
    max_parallel = getattr(cfg, "max_parallel_subtasks", 3)
    max_rounds = getattr(cfg, "max_convergence_rounds", 2)

    assignment_resolver = CrewAssignmentResolver(
        capability_registry=capability_registry,
        ontology=ontology,
        trust_network=trust_network,
        agent_registry=registry,
    )
    delegator = CrewDelegator(
        ontology=ontology,
        order_manager=order_manager,
        agent_registry=registry,
    )
    crew_executor = CrewTaskExecutor(
        work_item_store=work_item_store,
        agent_registry=registry,
        agentic_executor=agentic_executor,
        runtime=runtime,
        max_parallel_subtasks=max_parallel,
        emit_fn=emit_fn,
    )
    verifier = SubtaskVerifier(
        llm_client=llm_client,
        work_item_store=work_item_store,
        agent_registry=registry,
        trust_network=trust_network,
        agentic_executor=agentic_executor,
        runtime=runtime,
        max_convergence_rounds=max_rounds,
        ontology=ontology,
    )
    synthesizer = CrewSynthesizer(
        llm_client=llm_client,
        work_item_store=work_item_store,
        trust_network=trust_network,
        episodic_memory=episodic_memory,
        attachment_store=attachment_store,
        runtime=runtime,
        emit_fn=emit_fn,
    )
    runtime.crew_orchestrator = CrewOrchestrator(  # public attr (Wave 5 conv #1)
        assignment_resolver=assignment_resolver,
        delegator=delegator,
        crew_executor=crew_executor,
        verifier=verifier,
        synthesizer=synthesizer,
        work_item_store=work_item_store,
        runtime=runtime,
        emit_fn=emit_fn,
        config=config,
    )
    logger.info(
        "AD-867: CrewOrchestrator initialized (max_parallel=%d, max_rounds=%d)",
        max_parallel, max_rounds,
    )
    return True


def _wire_self_improvement(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-482 v1: wire the self-improvement pipeline.

    Constructs and attaches:
    * ``runtime.proposal_store`` -- ProposalStore with evolution-store callback.
    * ``runtime.approval_gate`` -- ApprovalGate over ProposalStore.
    * ``runtime.evolution_store`` -- EvolutionStore (chroma if available).
    * ``runtime.qa_agent_pool`` -- QAAgentPool over up to N SystemQAAgent
      instances pulled from the spawner.
    * ``runtime.agent_version_store`` -- AgentVersionStore.
    * ``runtime.agent_persistence`` -- LocalDiskPersistence default impl.
    * ``runtime.shadow_deployment_policy`` -- NoOpShadowDeploymentPolicy default.

    Tier-2 log-and-degrade: missing chroma_client downgrades EvolutionStore to
    in-memory fallback; missing spawner downgrades QAAgentPool to a single
    in-process SystemQAAgent (Shapley still produces equal contributions).
    """
    cfg = config.self_improvement
    if not cfg.enabled:
        logger.info("AD-482: self_improvement disabled -- skipping wiring")
        return False

    try:
        from probos.cognitive.self_improvement import (
            ApprovalGate,
            EvolutionStore,
            LocalDiskPersistence,
            NoOpShadowDeploymentPolicy,
            ProposalStore,
            QAAgentPool,
            AgentVersionStore,
        )
        from probos.cognitive.self_improvement.grounding import (
            ProposalGroundingVerifier,
            SymbolExistenceProvider,
        )
    except Exception:
        logger.warning(
            "AD-482: self_improvement package import failed -- skipping wiring",
            exc_info=True,
        )
        return False

    emit = getattr(runtime, "emit_event", None)
    chroma_client = getattr(runtime, "_chroma_client", None)

    evolution_store = EvolutionStore(
        chroma_client=chroma_client,
        collection_name=cfg.evolution_collection_name,
        half_life_seconds=cfg.evolution_half_life_seconds,
        event_emit_fn=emit,
    )
    try:
        evolution_store.start()
    except Exception:
        logger.warning(
            "AD-482d: EvolutionStore.start raised; continuing in fallback mode",
            exc_info=True,
        )

    proposal_store = ProposalStore(
        evolution_store_callback=evolution_store.record_lesson,
        event_emit_fn=emit,
        iteration_cap=cfg.iteration_cap,
    )

    # AD-833: build the advisory grounding verifier over the codebase index.
    # If the index is absent (config-disabled / degraded boot), use an empty
    # provider list and log-and-degrade -- never crash finalize.
    codebase_index = getattr(runtime, "codebase_index", None)
    if codebase_index is not None:
        proposal_grounding_verifier = ProposalGroundingVerifier(
            providers=[SymbolExistenceProvider(codebase_index)]
        )
    else:
        logger.warning(
            "AD-833: codebase_index absent at finalize; grounding verifier has no providers"
        )
        proposal_grounding_verifier = ProposalGroundingVerifier(providers=[])

    approval_gate = ApprovalGate(
        proposal_store=proposal_store,
        event_emit_fn=emit,
        grounding_verifier=proposal_grounding_verifier,
    )

    # Pull QA agents from the spawner. Degrade to single in-process agent on absence.
    qa_agents: list[Any] = []
    spawner = getattr(runtime, "spawner", None)
    if spawner is not None:
        for _ in range(cfg.qa_pool_size):
            try:
                agent = spawner.spawn("system_qa")
                qa_agents.append(agent)
            except Exception:
                logger.warning(
                    "AD-482f: spawner.spawn('system_qa') failed; pool size %d short",
                    cfg.qa_pool_size,
                    exc_info=True,
                )
                break
    if not qa_agents:
        try:
            from probos.agents.system_qa import SystemQAAgent

            qa_agents = [SystemQAAgent(agent_id="qa_default_0")]
        except Exception:
            logger.warning(
                "AD-482f: fallback SystemQAAgent construction failed; QAAgentPool disabled",
                exc_info=True,
            )
            qa_agents = []

    qa_agent_pool: Any = None
    if qa_agents:
        try:
            qa_agent_pool = QAAgentPool(qa_agents=qa_agents)
        except Exception:
            logger.warning(
                "AD-482f: QAAgentPool construction failed",
                exc_info=True,
            )
            qa_agent_pool = None

    agent_version_store = AgentVersionStore(event_emit_fn=emit)
    agent_persistence = LocalDiskPersistence(root_dir=cfg.persistence_root_dir)
    shadow_deployment_policy = NoOpShadowDeploymentPolicy()

    runtime.proposal_store = proposal_store
    runtime.approval_gate = approval_gate
    runtime.proposal_grounding_verifier = proposal_grounding_verifier
    runtime.evolution_store = evolution_store
    runtime.qa_agent_pool = qa_agent_pool
    runtime.agent_version_store = agent_version_store
    runtime.agent_persistence = agent_persistence
    runtime.shadow_deployment_policy = shadow_deployment_policy

    logger.info(
        "AD-482: self_improvement wired -- qa_pool_size=%d, iteration_cap=%d, "
        "evolution_collection=%r",
        len(qa_agents) if qa_agents else 0,
        cfg.iteration_cap,
        cfg.evolution_collection_name,
    )
    return True


def _wire_predictive_branching(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-633 v1: Wire PredictionEngine + SpeculationCache + SpeculationExecutor
    + SpeculationBudget + AccuracyTracker.

    Requires ``runtime.hebbian_router`` AND ``runtime.ontology``. Optional:
    ``runtime._sub_task_executor`` (AD-632) — speculation cannot dispatch
    chains without it but the engine + cache still operate. Tier-2
    log-and-degrade: missing required deps -> no-op + INFO log.
    """
    cfg = getattr(config, "predictive_branching", None)
    if not cfg or not cfg.enabled:
        return False
    hebbian = getattr(runtime, "hebbian_router", None)
    if hebbian is None:
        logger.info("AD-633: hebbian_router unavailable; predictive_branching skipped")
        return False
    ontology = getattr(runtime, "ontology", None)
    if ontology is None:
        logger.info("AD-633: ontology unavailable; predictive_branching skipped")
        return False

    from probos.cognitive.predictive_branching import (
        AccuracyTracker,
        PredictionEngine,
        SpeculationBudget,
        SpeculationCache,
        SpeculationExecutor,
    )

    emit_fn = getattr(runtime, "emit_event", None)
    # AD-633a v1 deliberately does NOT integrate the AD-488 circuit breaker.
    # ProactiveCognitiveLoop's `_circuit_breaker` is a private attribute;
    # accessing it from this wirer would be a cross-module Demeter violation
    # per `.github/copilot-instructions.md`. Forcing function: AD-633a-1 ships
    # a public `ProactiveCognitiveLoop.circuit_breaker` property and re-wires
    # circuit-breaker gating into PredictionEngine.

    runtime.prediction_engine = PredictionEngine(
        hebbian_router=hebbian,
        ontology=ontology,
        config=cfg,
        circuit_breaker=None,
    )
    runtime.speculation_cache = SpeculationCache(
        max_entries=cfg.cache_max_entries,
        ttl_seconds=cfg.cache_ttl_seconds,
        emit_event=emit_fn,
    )
    runtime.speculation_budget = SpeculationBudget(
        tokens_per_window=cfg.speculation_tokens_per_window,
        window_seconds=cfg.speculation_window_seconds,
        flush_rate_threshold=cfg.flush_rate_feedback_threshold,
        flush_rate_window_seconds=cfg.flush_rate_window_seconds,
    )
    runtime.accuracy_tracker = AccuracyTracker(ring_size=cfg.accuracy_ring_size)
    runtime.speculation_executor = SpeculationExecutor(
        sub_task_executor=getattr(runtime, "_sub_task_executor", None),
        cache=runtime.speculation_cache,
        budget=runtime.speculation_budget,
        accuracy_tracker=runtime.accuracy_tracker,
        emit_event=emit_fn,
    )
    logger.info(
        "AD-633: PredictiveBranching v1 initialized "
        "(cache_max=%d, ttl=%.0fs, tokens_per_window=%d, ring=%d)",
        cfg.cache_max_entries,
        cfg.cache_ttl_seconds,
        cfg.speculation_tokens_per_window,
        cfg.accuracy_ring_size,
    )
    return True


def _wire_hybrid_dispatch(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-581 v1: Wire DepartmentDispatcher + WorkItemRouter.

    Requires ``runtime.hebbian_router``, ``runtime.ontology``,
    ``runtime.work_item_store``, AND ``runtime.dispatcher`` (AD-654c).
    Tier-2 log-and-degrade: missing any dependency -> no-op + INFO log.
    """
    cfg = getattr(config, "hybrid_dispatch", None)
    if not cfg or not cfg.enabled:
        return False
    hebbian = getattr(runtime, "hebbian_router", None)
    if hebbian is None:
        logger.info(
            "AD-581: hebbian_router unavailable; hybrid_dispatch skipped"
        )
        return False
    ontology = getattr(runtime, "ontology", None)
    if ontology is None:
        logger.info(
            "AD-581: ontology unavailable; hybrid_dispatch skipped"
        )
        return False
    dispatcher = getattr(runtime, "dispatcher", None)
    if dispatcher is None:
        logger.info(
            "AD-581: dispatcher (AD-654c) unavailable; hybrid_dispatch skipped"
        )
        return False
    registry = getattr(runtime, "registry", None)
    if registry is None:
        logger.info(
            "AD-581: registry unavailable; hybrid_dispatch skipped"
        )
        return False

    from probos.mesh.department_dispatcher import DepartmentDispatcher
    from probos.mesh.work_item_router import WorkItemRouter

    runtime.department_dispatcher = DepartmentDispatcher(  # public attr (Wave 5 conv #1)
        hebbian_router=hebbian,
        ontology=ontology,
        config=cfg,
    )
    emit_fn = getattr(runtime, "emit_event", None)
    runtime.work_item_router = WorkItemRouter(  # public attr (Wave 5 conv #1)
        dispatcher=dispatcher,
        department_dispatcher=runtime.department_dispatcher,
        registry=registry,
        config=cfg,
        emit_event=emit_fn,
    )

    # AD-581a: register WorkItemRouter as listener for WORK_ITEM_CREATED.
    # runtime.add_event_listener handles async callables via asyncio.create_task.
    add_listener = getattr(runtime, "add_event_listener", None)
    if add_listener is not None:
        try:
            add_listener(
                runtime.work_item_router.on_work_item_created,
                event_types=["work_item_created"],
            )
        except Exception:
            logger.warning(
                "AD-581a: add_event_listener failed; WorkItemRouter inactive",
                exc_info=True,
            )

    logger.info(
        "AD-581 v1: HybridDispatch wired "
        "(threshold=%.2f, margin=%.2f, floor=%.2f)",
        cfg.confidence_threshold, cfg.confidence_margin, cfg.min_hebbian_weight,
    )
    return True


def _wire_board_reconciler(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-876: Wire the Quartermaster cadence ticker (warm-boot + periodic).

    Requires ``runtime.work_item_router`` (only present when hybrid_dispatch is
    enabled), ``runtime.work_item_store``, and ``runtime.registry``. Tier-2
    log-and-degrade: missing any dependency or disabled config -> no-op + INFO.
    """
    cfg = getattr(config, "work_board_reconciler", None)
    if not cfg or not cfg.enabled:
        return False

    router = getattr(runtime, "work_item_router", None)
    if router is None:
        logger.info(
            "AD-876: work_item_router unavailable (requires hybrid_dispatch); "
            "board reconciler skipped"
        )
        return False
    store = getattr(runtime, "work_item_store", None)
    if store is None:
        logger.info(
            "AD-876: work_item_store unavailable; board reconciler skipped"
        )
        return False
    registry = getattr(runtime, "registry", None)
    if registry is None:
        logger.info(
            "AD-876: registry unavailable; board reconciler skipped"
        )
        return False

    from probos.cognitive.work_reconciler import WorkItemReconciler
    from probos.mesh.board_reconciler_ticker import BoardReconcilerTicker

    reconciler = WorkItemReconciler(
        registry=registry,
        identity_registry=getattr(runtime, "identity_registry", None),
    )

    # Resolve the live quartermaster agent and inject collaborators by the
    # exact private attrs the constructor uses (NOT the public kwarg names).
    agents = registry.get_by_pool("quartermaster")
    if not agents:
        logger.info(
            "AD-876: no quartermaster agent in pool; board reconciler skipped"
        )
        return False
    agent = agents[0]
    agent._reconciler = reconciler
    agent._store = store
    agent._router = router
    agent._emit = getattr(runtime, "emit_event", None)
    agent._episodic = getattr(runtime, "episodic_memory", None)
    agent._scan_limit = cfg.scan_limit
    # AD-877: thrash guard config (bounded re-route attempts + per-item backoff).
    agent._max_reconcile_attempts = cfg.max_reconcile_attempts
    agent._reconcile_backoff_seconds = cfg.reconcile_backoff_seconds
    # AD-878: boot-race grace period (skip items younger than this age).
    agent._min_item_age_seconds = cfg.min_item_age_seconds
    # AD-881: live-but-stalled reroute threshold (0 = disabled, default off).
    agent._stall_timeout_seconds = cfg.stall_timeout_seconds
    # AD-882: federation node-scope guard — local node id + federation-enabled flag.
    agent._local_node_id = config.federation.node_id
    agent._federation_enabled = config.federation.enabled

    ticker = BoardReconcilerTicker(
        agent=agent,
        interval_seconds=cfg.interval_seconds,
        warm_boot=cfg.warm_boot,
    )
    runtime.board_reconciler_ticker = ticker  # public attr (Wave 5 conv #1)
    ticker.start()

    # AD-880: reactive reclaim — subscribe the quartermaster to AGENT_REMOVED so a
    # dead agent's items are reclaimed immediately (additive to the periodic sweep).
    if getattr(cfg, "reactive_reclaim", False):
        from probos.events import EventType

        async def _on_agent_removed(event: Any) -> None:
            try:
                agent_id = (event.get("data") or {}).get("agent_id")
                if agent_id:
                    await agent.reconcile_for_agent(agent_id)
            except Exception:
                logger.warning(
                    "AD-880: reactive reclaim handler failed; periodic sweep "
                    "remains the safety net",
                    exc_info=True,
                )

        add_listener = getattr(runtime, "add_event_listener", None)
        if add_listener is not None:
            try:
                add_listener(_on_agent_removed, event_types=[EventType.AGENT_REMOVED.value])
                runtime.board_reactive_reclaim_handler = _on_agent_removed  # hold ref
                logger.info("AD-880: reactive reclaim subscribed to AGENT_REMOVED")
            except Exception:
                logger.warning(
                    "AD-880: add_event_listener failed; reactive reclaim inactive",
                    exc_info=True,
                )
        else:
            logger.info(
                "AD-880: add_event_listener unavailable; reactive reclaim skipped "
                "(periodic sweep unchanged)"
            )

    logger.info(
        "AD-876: BoardReconciler wired "
        "(interval=%ds, warm_boot=%s, scan_limit=%d)",
        cfg.interval_seconds, cfg.warm_boot, cfg.scan_limit,
    )
    return True


def _wire_capability_gap_driver(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-855: Wire the CapabilityGapDriver.

    Closes the BLOCKED -> request -> approve -> resume loop on the work-item
    board. Requires ``runtime.work_item_store`` and
    ``runtime.capability_request_store``; registers the driver as a listener
    for CAPABILITY_REQUEST_FULFILLED / CAPABILITY_REQUEST_DECIDED via
    ``runtime.add_event_listener``. Tier-2 log-and-degrade: missing any
    dependency -> no-op + INFO log.
    """
    work_item_store = getattr(runtime, "work_item_store", None)
    request_store = getattr(runtime, "capability_request_store", None)
    if work_item_store is None or request_store is None:
        logger.info(
            "AD-855: work_item_store or capability_request_store unavailable; "
            "capability gap driver skipped"
        )
        return False

    from probos.cognitive.capability_gap_driver import CapabilityGapDriver

    runtime.capability_gap_driver = CapabilityGapDriver(  # public attr
        runtime=runtime,
        work_item_store=work_item_store,
        capability_request_store=request_store,
    )

    add_listener = getattr(runtime, "add_event_listener", None)
    if add_listener is not None:
        try:
            add_listener(
                runtime.capability_gap_driver.on_capability_event,
                event_types=[
                    "capability_request_fulfilled",
                    "capability_request_decided",
                ],
            )
        except Exception:
            logger.warning(
                "AD-855: add_event_listener failed; CapabilityGapDriver "
                "resume loop inactive",
                exc_info=True,
            )

    logger.info("AD-855: CapabilityGapDriver wired")
    return True


def _wire_capability_request_notifier(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-857: Wire the capability-request Captain-DM notifier.

    Chat half of the dual-surface decision surface: registers a listener for
    CAPABILITY_REQUEST_FILED that posts a Captain-DM notice via the AD-485
    primitive. Tier-2 log-and-degrade: no ``add_event_listener`` -> no-op +
    INFO log. The HXI card remains the decision path regardless.
    """
    from probos.capability_request_notifier import (
        notify_captain_of_capability_request,
    )

    async def _on_filed(event: Any) -> None:
        await notify_captain_of_capability_request(runtime, event)

    add_listener = getattr(runtime, "add_event_listener", None)
    if add_listener is None:
        logger.info(
            "AD-857: add_event_listener unavailable; capability-request "
            "Captain-DM notifier skipped"
        )
        return False
    try:
        add_listener(_on_filed, event_types=["capability_request_filed"])
    except Exception:
        logger.warning(
            "AD-857: add_event_listener failed; capability-request "
            "Captain-DM notifier inactive",
            exc_info=True,
        )
        return False

    logger.info("AD-857: capability-request Captain-DM notifier wired")
    return True


def _wire_task_completion_notifier(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-846: Wire the Yeo task-completion Captain-DM notifier.

    Async half of Yeo's Tier-3 delegation loop: registers a listener for
    WORK_ITEM_STATUS_CHANGED that DMs the Captain (via the AD-485 primitive)
    when a Yeo-delegated dispatchable task reaches a terminal status. Tier-2
    log-and-degrade: no ``add_event_listener`` -> no-op + INFO log. The kanban
    board remains the result surface regardless.
    """
    from probos.task_completion_notifier import (
        notify_captain_of_task_completion,
    )

    async def _on_status_changed(event: Any) -> None:
        await notify_captain_of_task_completion(runtime, event)

    add_listener = getattr(runtime, "add_event_listener", None)
    if add_listener is None:
        logger.info(
            "AD-846: add_event_listener unavailable; task-completion "
            "Captain-DM notifier skipped"
        )
        return False
    try:
        add_listener(_on_status_changed, event_types=["work_item_status_changed"])
    except Exception:
        logger.warning(
            "AD-846: add_event_listener failed; task-completion "
            "Captain-DM notifier inactive",
            exc_info=True,
        )
        return False

    logger.info("AD-846: task-completion Captain-DM notifier wired")
    return True


def _wire_workspace_ontology(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-478 v1: Wire WorkspaceOntologyRegistry term frequency helper."""
    cfg = getattr(config, "workspace_ontology", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.workspace_ontology import WorkspaceOntologyRegistry

    emit_fn = getattr(runtime, "emit_event", None)
    runtime.workspace_ontology = WorkspaceOntologyRegistry(  # public attribute (Wave 5 convention #1)
        max_terms=cfg.max_terms,
        emit_event=emit_fn,
    )
    logger.info(
        "AD-478: WorkspaceOntologyRegistry v1 initialized (max_terms=%d)",
        cfg.max_terms,
    )
    return True


def _wire_gap_remediation_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-539c v1: Wire GapRemediationTracker (observational only)."""
    from probos.config import GapPipelineExtensionsConfig

    cfg = getattr(config, "gap_pipeline_extensions", None)
    # Defensive boundary check (BF-254 pattern): legacy tests pass MagicMock for
    # config, which would make cfg.remediation_max_history a MagicMock that
    # deque(maxlen=...) cannot accept as an int.
    if not isinstance(cfg, GapPipelineExtensionsConfig) or not cfg.remediation_tracker_enabled:
        return False

    from probos.cognitive.gap_remediation import GapRemediationTracker

    tracker = GapRemediationTracker(runtime, max_history=cfg.remediation_max_history)
    tracker.emit_event = getattr(runtime, "emit_event", None)
    runtime.gap_remediation_tracker = tracker  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-539c: GapRemediationTracker initialized (observational v1; max_history=%d)",
        cfg.remediation_max_history,
    )
    return True


def _wire_gap_aggregator(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-539d v1: Wire FleetGapAggregator (local-ship only; no federation)."""
    from probos.config import GapPipelineExtensionsConfig

    cfg = getattr(config, "gap_pipeline_extensions", None)
    if not isinstance(cfg, GapPipelineExtensionsConfig) or not cfg.fleet_aggregator_enabled:
        return False

    from probos.cognitive.gap_aggregation import FleetGapAggregator

    aggregator = FleetGapAggregator(runtime)
    aggregator.emit_event = getattr(runtime, "emit_event", None)
    runtime.gap_aggregator = aggregator  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-539d: FleetGapAggregator initialized (local-ship v1; federation deferred to AD-539d-i)"
    )
    return True


def _wire_spc_calibration(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-522 v1: Wire SPCCalibrationStore (calibration profile + WE rules)."""
    from probos.config import SPCConfig

    cfg = getattr(config, "spc", None)
    if not isinstance(cfg, SPCConfig) or not cfg.enabled:
        return False

    from probos.cognitive.spc import SPCCalibrationStore

    store = SPCCalibrationStore(runtime, sample_window=cfg.sample_window)
    store.emit_event = getattr(runtime, "emit_event", None)
    runtime.spc_calibration_store = store  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-522: SPCCalibrationStore initialized (sample_window=%d; 4 of 8 WE rules)",
        cfg.sample_window,
    )
    return True


async def _wire_self_distillation(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-487: Wire PersonalOntologyProber (Map step only) and open its SQLite handle."""
    # Defensive boundary check: some legacy tests pass MagicMock for config,
    # which would make `config.self_distillation.enabled` truthy and `db_path`
    # a MagicMock that aiosqlite cannot open. Skip wiring unless we have a
    # real Pydantic SelfDistillationConfig.
    from probos.config import SelfDistillationConfig
    sd_cfg = getattr(config, "self_distillation", None)
    if not isinstance(sd_cfg, SelfDistillationConfig):
        return False
    if not sd_cfg.enabled:
        return False

    from probos.cognitive.self_distillation.prober import PersonalOntologyProber

    # BF: rebase the configured db_path filename under runtime.data_dir so
    # tmp_path-based tests (and CI runners with a non-writable CWD) can open
    # the SQLite file. The default `data/agent_probes.db` is a project-root
    # relative path that fails on Linux CI when CWD differs.
    from pathlib import Path
    data_dir = getattr(runtime, "data_dir", None)
    if data_dir is not None:
        rebased_db_path = Path(data_dir) / Path(sd_cfg.db_path).name
        sd_cfg = sd_cfg.model_copy(update={"db_path": rebased_db_path})

    prober = PersonalOntologyProber(
        runtime=runtime,
        config=sd_cfg,
    )
    # Late-bind emit fn (Wave 5 convention #5).
    prober._emit_event_fn = getattr(runtime, "emit_event", None)
    await prober.start()
    runtime.personal_ontology_prober = prober  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-487: PersonalOntologyProber initialized (db=%s; rate_limit_hours=%d)",
        sd_cfg.db_path,
        sd_cfg.rate_limit_hours,
    )
    return True


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
        emit_event_fn=runtime.emit_event,
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

    emergence = getattr(runtime, "emergence_metrics_engine", None)
    if emergence and hasattr(emergence, "set_tier_registry"):
        emergence.set_tier_registry(registry)

    router = getattr(runtime, "hebbian_router", None)
    if router and hasattr(router, "set_tier_registry"):
        router.set_tier_registry(registry)

    op_tracker = getattr(runtime, "operational_status_tracker", None)
    if op_tracker and hasattr(op_tracker, "set_tier_registry"):
        op_tracker.set_tier_registry(registry)

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

    if _wire_anomaly_window(runtime=runtime, config=config):
        logger.info("AD-673: AnomalyWindowManager wired during finalization")

    if await _wire_desktop_ux(runtime=runtime, config=config):
        logger.info("AD-751: Desktop UX Surface wired during finalization")

    if await _wire_self_distillation(runtime=runtime, config=config):
        logger.info("AD-487: Self-distillation v1 wired during finalization")

    if _wire_creative_expression(runtime=runtime, config=config):
        logger.info("AD-525: Creative Expression v1 wired during finalization")

    if _wire_classification_gate(runtime=runtime, config=config):
        logger.info("AD-530: ClassificationGate v1 wired during finalization")

    if _wire_autonomy_boundaries(runtime=runtime, config=config):
        logger.info("AD-511: Autonomy Boundaries v1 wired during finalization")

    if _wire_curriculum_registry(runtime=runtime, config=config):
        logger.info("AD-507: Crew Development Framework v1 wired during finalization")

    if _wire_boot_camp_tracker(runtime=runtime, config=config):
        logger.info("AD-509: Boot Camp Phase Tracker v1 wired during finalization")

    if _wire_birth_chamber(runtime=runtime, config=config):
        logger.info("AD-486: Holodeck Birth Chamber v1 wired during finalization")

    if _wire_emergence_collector(runtime=runtime, config=config):
        logger.info("AD-454: EvidenceCollector wired during finalization")

    if _wire_holodeck_scenarios(runtime=runtime, config=config):
        logger.info("AD-539b: Holodeck Scenario Generation v1 wired during finalization")

    if _wire_holodeck_team_simulations(runtime=runtime, config=config):
        logger.info("AD-510: Holodeck Team Simulations v1 wired during finalization")

    if _wire_discovery_learning(runtime=runtime, config=config):
        logger.info("AD-512: Discovery Learning v1 wired during finalization")

    if _wire_ship_state_snapshot(runtime=runtime, config=config):
        logger.info("AD-683: Ship State Snapshot v1 wired during finalization")
        # BF-261: Late-bind into BootCampCoordinator (created at Phase 7, before finalize)
        _bc = getattr(runtime, "boot_camp", None)
        if _bc is not None and getattr(_bc, "_ship_state_builder", None) is None:
            _bc._ship_state_builder = runtime.ship_state_snapshot

    if _wire_duty_scope_provider(runtime=runtime, config=config):
        logger.info("AD-508: DutyScopeProvider v1 wired during finalization")

    if _wire_chain_optimizer(runtime=runtime, config=config):
        logger.info("AD-659: ChainOptimizer v1 wired during finalization")

    if await _wire_optimization_counselor(runtime=runtime, config=config):
        logger.info("AD-659c: OptimizationCounselor v1 wired during finalization")

    if await _wire_edge_backfill(runtime=runtime, config=config):
        logger.info("AD-689: EdgeBackfillService v1 wired during finalization")

    if await _wire_relationship_inference(runtime=runtime, config=config):
        logger.info("AD-690: Dream Step 7i relationship inference v1 wired during finalization")

    if _wire_causal_reasoner(runtime=runtime, config=config):
        logger.info("AD-660: CausalReasoner v1 wired during finalization")

    if _wire_diagnostic_context(runtime=runtime, config=config):
        logger.info("AD-661: DiagnosticContextService v1 wired during finalization")

    if _wire_nl_graph_query(runtime=runtime, config=config):
        logger.info("AD-691: NLGraphQueryService v1 wired during finalization")

    if _wire_edge_classification(runtime=runtime, config=config):
        logger.info("AD-692: KnowledgeEdgeClassificationGate v1 wired during finalization")

    if _wire_clinical_telemetry(runtime=runtime, config=config):
        logger.info("AD-635: ClinicalTelemetryService v1 wired during finalization")

    if _wire_process_chain_registry(runtime=runtime, config=config):
        logger.info("AD-647b: ProcessChainRegistry v1 wired during finalization")

    if _wire_consultation_workspaces(runtime=runtime, config=config):
        logger.info("AD-594a: WorkspaceRegistry v1 wired during finalization")

    if _wire_consultation_delivery(runtime=runtime, config=config):
        logger.info("AD-594d: DeliveryPipeline v1 wired during finalization")

    if _wire_consultation_dispatch(runtime=runtime, config=config):
        logger.info("AD-594c: ParallelDispatcher v1 wired during finalization")

    if _wire_crew_orchestrator(runtime=runtime, config=config):
        logger.info("AD-867: CrewOrchestrator wired during finalization")

    if _wire_workspace_ontology(runtime=runtime, config=config):
        logger.info("AD-478: WorkspaceOntologyRegistry v1 wired during finalization")

    if _wire_gap_remediation_tracker(runtime=runtime, config=config):
        logger.info("AD-539c: GapRemediationTracker v1 wired during finalization")

    if _wire_gap_aggregator(runtime=runtime, config=config):
        logger.info("AD-539d: FleetGapAggregator v1 wired during finalization")

    if _wire_spc_calibration(runtime=runtime, config=config):
        logger.info("AD-522: SPCCalibrationStore v1 wired during finalization")

    # BF-246: Start periodic LLM health probe for recovery from extended outages
    # BF-254: hasattr() alone matches MagicMock auto-attributes; require the
    # attribute to be an actual coroutine function before awaiting it.
    llm_client = getattr(runtime, "llm_client", None)
    probe_fn = getattr(llm_client, "start_health_probe", None) if llm_client else None
    if probe_fn is not None and asyncio.iscoroutinefunction(probe_fn):
        probe_interval = getattr(config, "health_probe_interval_seconds", 30.0)
        emit_fn = getattr(runtime, "emit_event", None)
        await probe_fn(
            interval_seconds=probe_interval,
            emit_fn=emit_fn,
        )
        logger.info("BF-246: LLM health probe started (interval=%.0fs)", probe_interval)

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

        from probos.duty_schedule import DutySchedule
        from probos.proactive import ProactiveCognitiveLoop

        runtime.duty_schedule = DutySchedule(config.duty_schedule)

        proactive_loop = ProactiveCognitiveLoop(
            interval=config.proactive_cognitive.interval_seconds,
            cooldown=config.proactive_cognitive.cooldown_seconds,
            on_event=lambda evt: runtime.emit_event(evt.get("type", ""), evt.get("data", {})),
        )
        proactive_loop.set_runtime(runtime)
        proactive_loop.set_config(config.proactive_cognitive, cb_config=config.circuit_breaker, trait_config=config.trait_adaptive)
        # AD-635c: late-bind seam — attach the CircuitBreakerHistoryStore
        # (constructed by _wire_clinical_telemetry above) to the breaker
        # owned by the proactive loop. Either side missing — clinical
        # disabled, persistence disabled, or no pending store — is
        # silently fine; the breaker simply stays unattached and
        # query_circuit_breaker_history returns [] from an empty store.
        _clinical = getattr(runtime, "clinical_telemetry", None)
        if _clinical is not None:
            _pending_store = getattr(_clinical, "_pending_breaker_store", None)
            if _pending_store is not None:
                try:
                    proactive_loop.circuit_breaker.set_history_store(_pending_store)
                    logger.info(
                        "AD-635c: CircuitBreakerHistoryStore attached to "
                        "CognitiveCircuitBreaker via late-bind"
                    )
                except Exception:
                    logger.warning(
                        "AD-635c: failed to attach CircuitBreakerHistoryStore "
                        "to breaker via late-bind",
                        exc_info=True,
                    )
        if config.proactive_cognitive.duty_schedule.enabled:
            proactive_loop.set_duty_schedule(config.proactive_cognitive.duty_schedule)
        # AD-891: park the single public duty-schedule accessor on the runtime so
        # the ACM personnel lens reads the configured schedule without reaching
        # into proactive_loop._duty_tracker (Law of Demeter). None when disabled.
        runtime.duty_schedule_tracker = proactive_loop.duty_tracker
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
    runtime.trust_network.set_event_callback(runtime.emit_event)

    # AD-676: Action Risk Tiers
    if config.risk_tiers.enabled:
        from probos.governance.risk_tiers import (
            ActionRiskRegistry,
            RiskPolicy,
            RiskTier,
            TIER_POLICIES,
        )

        policies = dict(TIER_POLICIES)
        if config.risk_tiers.elevated_min_trust != 0.0:
            policies[RiskTier.ELEVATED] = RiskPolicy(
                tier=RiskTier.ELEVATED,
                min_rank_ordinal=1,
                min_trust=config.risk_tiers.elevated_min_trust,
                description=TIER_POLICIES[RiskTier.ELEVATED].description,
            )
        if config.risk_tiers.critical_min_trust != 0.70:
            policies[RiskTier.CRITICAL] = RiskPolicy(
                tier=RiskTier.CRITICAL,
                min_rank_ordinal=2,
                min_trust=config.risk_tiers.critical_min_trust,
                description=TIER_POLICIES[RiskTier.CRITICAL].description,
            )
        risk_registry = ActionRiskRegistry(policies=policies)
        runtime._risk_registry = risk_registry
        logger.info(
            "AD-676: ActionRiskRegistry initialized with %d actions",
            len(risk_registry.list_actions()),
        )

    # AD-679: Selective Disclosure Routing
    from probos.mesh.disclosure import DisclosureRouter
    disclosure_router = DisclosureRouter()
    runtime._disclosure_router = disclosure_router
    logger.info("AD-679: DisclosureRouter initialized")

    # AD-439: Emergent Leadership Detector
    if config.emergent_leadership.enabled and runtime.ontology is not None:
        from probos.cognitive.emergent_leadership import EmergentLeadershipDetector
        detector = EmergentLeadershipDetector(
            ontology=runtime.ontology,
            hebbian=runtime.hebbian_router,
            registry=runtime.registry,
            emit_event=runtime.emit_event,
            min_weight=config.emergent_leadership.min_weight,
            min_ratio=config.emergent_leadership.min_ratio,
        )
        runtime.emergent_leadership_detector = detector
        logger.info("AD-439: EmergentLeadershipDetector wired")

    # AD-440: Chain of Command order manager
    if config.orders.enabled and runtime.ontology is not None:
        from probos.cognitive.orders import OrderManager
        order_manager = OrderManager(
            ontology=runtime.ontology,
            registry=runtime.registry,
            emit_event=runtime.emit_event,
            max_active_per_post=config.orders.max_active_per_post,
            default_ttl=config.orders.default_ttl_seconds,
        )
        runtime.order_manager = order_manager
        logger.info("AD-440: OrderManager wired (max_active=%d)", config.orders.max_active_per_post)

    # AD-451: Validation Framework
    if config.validation_framework.enabled:
        from probos.cognitive.validation_framework import ReconciliationEscalator
        runtime.reconciliation_escalator = ReconciliationEscalator(
            runtime=runtime,
            emit_event=runtime.emit_event,
            min_confidence_delta=config.validation_framework.min_confidence_delta,
            metadata_threshold=config.validation_framework.metadata_threshold,
        )
        logger.info("AD-451: ValidationFramework wired (ReconciliationEscalator)")

    # AD-458 / AD-458b: Pre-flight validation runner (4 checks at default config)
    if config.pre_flight.enabled:
        from pathlib import Path
        from probos.cognitive.pre_flight import (
            LLMTierReachableCheck,
            PreFlightRunner,
            TargetFilesExistCheck,
            TargetFilesWritableCheck,
            TokenBudgetCheck,
        )
        # finalize.py is at src/probos/startup/finalize.py — four levels deep
        # from the repo root, so parents[3] resolves to the repo root:
        #   parents[0] = src/probos/startup/
        #   parents[1] = src/probos/
        #   parents[2] = src/
        #   parents[3] = repo root  <- target
        repo_root = Path(__file__).resolve().parents[3]
        runtime.pre_flight_runner = PreFlightRunner(
            checks=[
                TargetFilesExistCheck(repo_root=repo_root),
                TargetFilesWritableCheck(repo_root=repo_root),
            ],
        )
        # AD-458b: append LLM-tier and token-budget checks AFTER the cheap
        # filesystem checks. PreFlightRunner short-circuits on the first
        # blocking failure, so the cheapest checks run first.
        if config.pre_flight.llm_tier_check_enabled:
            runtime.pre_flight_runner.checks.append(
                LLMTierReachableCheck(
                    runtime=runtime,
                    required_tier=config.pre_flight.required_llm_tier,
                ),
            )
        if config.pre_flight.token_budget_check_enabled:
            runtime.pre_flight_runner.checks.append(
                TokenBudgetCheck(
                    runtime=runtime,
                    blocking=config.pre_flight.token_budget_blocking,
                ),
            )
        logger.info(
            "AD-458b: PreFlightRunner wired (%d checks)",
            len(runtime.pre_flight_runner.checks),
        )

    # AD-491: Infodynamic Telemetry probe
    if config.infodynamic.enabled:
        from probos.cognitive.infodynamic import InfodynamicProbe
        runtime.infodynamic_probe = InfodynamicProbe(
            runtime=runtime,
            emit_event=runtime.emit_event,
            event_window_seconds=config.infodynamic.event_window_seconds,
            trust_buckets=config.infodynamic.trust_buckets,
        )
        logger.info("AD-491: InfodynamicProbe wired")

    # AD-466: Engineering Infrastructure (BackupService + StorageBackend)
    if config.infrastructure.enabled:
        from probos.infrastructure import (
            BackupService,
            SQLiteStorageBackend,
        )
        runtime.storage_backend = SQLiteStorageBackend()
        if config.infrastructure.backup_enabled:
            backup_root = runtime.data_dir / config.infrastructure.backup_subdir
            try:
                backup_root.mkdir(parents=True, exist_ok=True)
                runtime.backup_service = BackupService(
                    data_dir=runtime.data_dir,
                    backup_root=backup_root,
                    emit_event=runtime.emit_event,
                )
                logger.info(
                    "AD-466: BackupService wired (backup_root=%s)",
                    backup_root,
                )
            except OSError:
                logger.warning(
                    "AD-466: BackupService mkdir failed (backup_root=%s); "
                    "service disabled for this session",
                    backup_root, exc_info=True,
                )
                runtime.backup_service = None
        else:
            runtime.backup_service = None
        logger.info("AD-466: StorageBackend wired (sqlite)")

    # AD-459: Saucer separation -- graceful degradation
    # v1 always wires the manager (no enabled flag) so consumers can call
    # `runtime.degradation_manager.is_shed(name)` without a None check.
    # Default state is StressLevel.NORMAL (no shedding).
    from probos.degradation.manager import DegradationManager
    from probos.degradation.policy import SheddingPolicy
    from probos.degradation.registry import ServiceTierRegistry
    runtime.degradation_manager = DegradationManager(
        registry=ServiceTierRegistry(),
        policy=SheddingPolicy(),
        emit_event=runtime.emit_event,
    )
    logger.info("AD-459: DegradationManager wired (stress=normal)")

    # AD-459b: register active-shedding adopters when operator opts in.
    # Default `auto_pause_enabled=False` keeps the AD-459 v1 read-only
    # contract; flipping to True wires DreamScheduler + ProactiveCognitiveLoop
    # adopters whose `start`/`stop` methods are invoked on tier transitions.
    #
    # Source-attribute notes:
    #   * `runtime.dream_scheduler` is set during the dreaming phase (see
    #     runtime.py:1516) BEFORE `finalize_startup` is invoked, so the
    #     attribute is available here.
    #   * `proactive_loop` is the LOCAL variable bound at line ~863 / ~985
    #     of this same function. `runtime.proactive_loop` is NOT yet
    #     assigned at this point — that happens after finalize_startup
    #     returns (runtime.py:1704). Use the local binding.
    if config.degradation.auto_pause_enabled:
        from probos.degradation.subsystem import LifecycleAdapter
        adopters_registered: list[str] = []
        if runtime.dream_scheduler is not None:
            runtime.degradation_manager.register_subsystem(
                "dream_scheduler",
                LifecycleAdapter(
                    "dream_scheduler",
                    on_pause=runtime.dream_scheduler.stop,
                    on_resume=runtime.dream_scheduler.start,
                ),
            )
            adopters_registered.append("dream_scheduler")
        if proactive_loop is not None:
            runtime.degradation_manager.register_subsystem(
                "proactive_loop",
                LifecycleAdapter(
                    "proactive_loop",
                    on_pause=proactive_loop.stop,
                    on_resume=proactive_loop.start,
                ),
            )
            adopters_registered.append("proactive_loop")
        logger.info(
            "AD-459b: active shedding enabled; adopters=%s",
            adopters_registered,
        )

    # AD-468: Runtime Configuration Service
    if config.runtime_overrides.enabled:
        from probos.runtime_config_service import RuntimeConfigService
        store_path = runtime.data_dir / config.runtime_overrides.store_filename
        rcs = RuntimeConfigService(
            store_path=store_path,
            emit_event=runtime.emit_event,
        )
        runtime.runtime_config_service = rcs
        if runtime.proactive_loop is not None:
            if (val := rcs.get("proactive.interval")) is not None:
                try:
                    runtime.proactive_loop.set_cycle_interval(float(val))
                except Exception:
                    logger.warning(
                        "AD-468: failed to apply proactive.interval override",
                        exc_info=True,
                    )
            if (val := rcs.get("proactive.cooldown")) is not None:
                try:
                    runtime.proactive_loop.set_cooldown(float(val))
                except Exception:
                    logger.warning(
                        "AD-468: failed to apply proactive.cooldown override",
                        exc_info=True,
                    )
        logger.info(
            "AD-468: RuntimeConfigService wired (%d overrides loaded)",
            len(rcs.all()),
        )

    # AD-455: Security Team
    if config.security.enabled:
        from probos.security.threat_detector import ThreatDetector
        from probos.security.trust_integrity import TrustIntegrityMonitor
        from probos.security.input_validator import InputValidator
        from probos.security.red_team_lead import RedTeamLead

        threat_detector = ThreatDetector(emit_event=runtime.emit_event)
        trust_integrity = TrustIntegrityMonitor(
            trust_network=runtime.trust_network,
            event_log=runtime.event_log,
            emit_event=runtime.emit_event,
            burst_window_seconds=config.security.burst_window_seconds,
            burst_threshold=config.security.burst_threshold,
        )
        input_validator = InputValidator(
            threat_detector=threat_detector,
            emit_event=runtime.emit_event,
            max_payload_bytes=config.security.max_payload_bytes,
            rate_window_seconds=config.security.rate_window_seconds,
            rate_max_requests=config.security.rate_max_requests,
            max_threat_severity=config.security.max_threat_severity,
        )
        red_team_lead = RedTeamLead(
            runtime=runtime,
            emit_event=runtime.emit_event,
            campaign_interval_seconds=config.security.campaign_interval_seconds,
        )
        runtime.threat_detector = threat_detector
        runtime.trust_integrity_monitor = trust_integrity
        runtime.input_validator = input_validator
        runtime.red_team_lead = red_team_lead
        await red_team_lead.start()
        logger.info("AD-455: Security Team wired (4 services)")

    # AD-456: Security Infrastructure
    # Reconfigure existing CredentialStore (AD-395) with AD-456 rotation extension
    credential_store = getattr(runtime, "credential_store", None)
    if credential_store is not None and config.security_infra.secrets_persistence_enabled:
        try:
            credential_store._store_path = (
                runtime.data_dir / config.security_infra.secrets_store_filename
            )
            credential_store._emit_event = runtime.emit_event
            logger.info(
                "AD-456: CredentialStore extended with secrets store (path=%s)",
                credential_store._store_path,
            )
        except Exception:
            logger.warning(
                "AD-456: CredentialStore secrets-store extension failed",
                exc_info=True,
            )

    # AD-456c: Per-tier credential lookup gate. Default False preserves
    # AD-456 ungated-lookup behavior; Captain flips at upgrade time after
    # reviewing per-spec min_tier coverage AND caller-side tier= argument
    # propagation (AD-456c-2).
    if (
        credential_store is not None
        and config.security_infra.credential_tier_enforcement
    ):
        credential_store.set_tier_enforcement(True)
        logger.info("AD-456c: CredentialStore per-tier gate enabled")

    if config.security_infra.egress_enabled:
        from probos.security.egress import EgressPolicy
        runtime.egress_policy = EgressPolicy(
            emit_event=runtime.emit_event,
            deny_by_default=config.security_infra.egress_deny_by_default,
        )
        logger.info(
            "AD-456: EgressPolicy wired (deny_by_default=%s)",
            config.security_infra.egress_deny_by_default,
        )
    else:
        runtime.egress_policy = None

    if config.security_infra.audit_enabled:
        from probos.security.audit import AuditLog
        runtime.audit_log = AuditLog(emit_event=runtime.emit_event)
        logger.info("AD-456: AuditLog wired (in-memory hash chain)")
    else:
        runtime.audit_log = None

    # AD-456d: AuditLog SQLite persistence. Whole block is try/except —
    # boot continues with runtime.audit_log_persistence=None on any
    # failure (mirrors AD-456 CredentialStore extension shape).
    runtime.audit_log_persistence = None
    if (
        runtime.audit_log is not None
        and config.security_infra.audit_persistence_enabled
    ):
        try:
            from probos.security.audit import AuditLogPersistence
            from probos.storage.sqlite_factory import SQLiteConnectionFactory
            persistence = AuditLogPersistence(
                db_path=str(
                    runtime.data_dir / config.security_infra.audit_persistence_filename
                ),
                connection_factory=SQLiteConnectionFactory(),
                emit_event=runtime.emit_event,
            )
            await persistence.start()
            loaded = await persistence.load_entries()
            if loaded:
                runtime.audit_log.entries.extend(loaded)
                if not runtime.audit_log.verify_chain():
                    logger.warning(
                        "AD-456d: AuditLog chain verification FAILED on "
                        "rehydrate (tamper or corruption suspected; "
                        "AD-456d-3 will add Captain alert path)"
                    )
            runtime.audit_log.attach_persistence(persistence)
            runtime.audit_log_persistence = persistence
            logger.info(
                "AD-456d: AuditLog persistence wired (db=%s, rehydrated=%d)",
                persistence._db_path, len(loaded),
            )
        except Exception:
            logger.warning(
                "AD-456d: AuditLog persistence wiring failed (boot continues "
                "with in-memory-only audit chain)",
                exc_info=True,
            )
            runtime.audit_log_persistence = None

    # AD-456b: Runtime Sandboxing
    if config.security_infra.sandbox_enabled:
        from probos.security.runtime_sandbox import RuntimeSandbox, SandboxLimits
        runtime.runtime_sandbox = RuntimeSandbox(
            default_limits=SandboxLimits(
                wall_timeout_seconds=config.security_infra.sandbox_default_wall_timeout_seconds,
                memory_peak_mb=config.security_infra.sandbox_default_memory_peak_mb,
            ),
            emit_event=runtime.emit_event,
        )
        logger.info(
            "AD-456b: RuntimeSandbox wired (wall=%.1fs, mem_peak=%.0fMB)",
            config.security_infra.sandbox_default_wall_timeout_seconds,
            config.security_infra.sandbox_default_memory_peak_mb,
        )
    else:
        runtime.runtime_sandbox = None

    # AD-456b: HttpFetchAgent egress active enforcement (gated on
    # egress_active_enforcement; v1 default False preserves AD-456
    # consultation-only behavior). When False, _egress_policy stays None
    # and HttpFetchAgent._validate_url skips the consultation block.
    if (
        config.security_infra.egress_active_enforcement
        and runtime.egress_policy is not None
    ):
        from probos.agents.http_fetch import HttpFetchAgent
        HttpFetchAgent.set_egress_policy(runtime.egress_policy)
        logger.info("AD-456b: HttpFetchAgent egress active enforcement enabled")

    # AD-528: Ground-Truth Task Verification (v1: read-only scoring + emit).
    # AD-528b: optional active-rejection gate (default disabled).
    # AD-528c: optional trust-network feedback listener (default disabled).
    if config.ground_truth.enabled:
        from probos.cognitive.ground_truth import (
            GroundTruthVerifier,
            VerificationEpisodeWriter,
        )
        runtime.ground_truth_verifier = GroundTruthVerifier(
            runtime=runtime,
            emit_event=runtime.emit_event,
            threshold=config.ground_truth.threshold,
            event_window_seconds=config.ground_truth.event_window_seconds,
        )
        if config.ground_truth.write_episode:
            runtime.verification_episode_writer = VerificationEpisodeWriter(
                runtime=runtime,
            )
        else:
            runtime.verification_episode_writer = None
        # AD-528b: rejection gate wraps the verifier when the transitional
        # flag is set. Caller integration (consult gate before allowing
        # `→ done` transitions) is deferred to AD-528b-2; v1 ships the
        # layer + finalize wiring + tests with no production callers.
        if (
            config.ground_truth.active_rejection_enabled
            and runtime.ground_truth_verifier is not None
        ):
            from probos.cognitive.ground_truth import GroundTruthRejectionGate
            runtime.ground_truth_rejection_gate = GroundTruthRejectionGate(
                verifier=runtime.ground_truth_verifier,
                runtime=runtime,
                emit_event=runtime.emit_event,
                metadata_key=config.ground_truth.quarantine_metadata_key,
            )
            logger.info(
                "AD-528b: GroundTruthRejectionGate wired (metadata_key=%s)",
                config.ground_truth.quarantine_metadata_key,
            )
        else:
            runtime.ground_truth_rejection_gate = None
        # AD-528c: trust-network feedback listener subscribes to
        # VERIFICATION_PASSED + VERIFICATION_FAILED and calls
        # runtime.trust_network.record_outcome(...). Default disabled per
        # Convention #14 + #3; AD-528c-1 flips default True after fleet
        # rehearsal. v1 has zero coupling to the rejection gate -- the
        # listener consumes existing AD-528 events directly.
        if (
            config.ground_truth.trust_feedback_enabled
            and runtime.trust_network is not None
        ):
            from probos.cognitive.ground_truth import GroundTruthTrustFeedback
            from probos.events import EventType
            feedback = GroundTruthTrustFeedback(
                runtime=runtime,
                success_weight=config.ground_truth.trust_feedback_success_weight,
                failure_weight=config.ground_truth.trust_feedback_failure_weight,
            )
            runtime.add_event_listener(
                feedback.on_event,
                event_types=[
                    EventType.VERIFICATION_PASSED.value,
                    EventType.VERIFICATION_FAILED.value,
                ],
            )
            runtime.ground_truth_trust_feedback = feedback
            logger.info(
                "AD-528c: GroundTruthTrustFeedback wired (success_weight=%.2f, failure_weight=%.2f)",
                config.ground_truth.trust_feedback_success_weight,
                config.ground_truth.trust_feedback_failure_weight,
            )
        else:
            runtime.ground_truth_trust_feedback = None
        logger.info(
            "AD-528: GroundTruthVerifier wired (threshold=%.2f, window=%.0fs)",
            config.ground_truth.threshold,
            config.ground_truth.event_window_seconds,
        )
    else:
        runtime.ground_truth_verifier = None
        runtime.verification_episode_writer = None
        runtime.ground_truth_rejection_gate = None
        runtime.ground_truth_trust_feedback = None

    # AD-463: Model Diversity & Neural Routing (v1 foundation)
    if config.model_routing.enabled:
        from probos.cognitive.model_registry import ModelRegistry
        from probos.cognitive.model_router import ModelRouter
        runtime.model_registry = ModelRegistry()
        runtime.model_router = ModelRouter(
            registry=runtime.model_registry,
            emit_event=runtime.emit_event,
        )
        # Wire ModelRouter into the existing LLM client (real consumer, not theater).
        # The client's `model_router` public attribute is consulted at every
        # _complete_inner() iteration via _resolve_model_for_tier(). Existing
        # tier->model defaults remain when ModelRouter is absent.
        llm_client = getattr(runtime, "llm_client", None)
        if llm_client is not None:
            try:
                llm_client.model_router = runtime.model_router
            except Exception:
                logger.warning(
                    "AD-463: failed to wire ModelRouter into runtime.llm_client",
                    exc_info=True,
                )
        logger.info(
            "AD-463: ModelRegistry + ModelRouter wired (%d models)",
            len(runtime.model_registry.all()),
        )
    else:
        runtime.model_registry = None
        runtime.model_router = None

    # AD-475: Captain's Ready Room (Idea Capture + Session Manager)
    if config.ready_room.enabled:
        from probos.cognitive.ready_room import (
            IdeaCaptureStore,
            ReadyRoomSessionManager,
        )
        idea_path = runtime.data_dir / config.ready_room.idea_store_filename
        # AD-475 rev: parent dirs auto-created by IdeaCaptureStore._save() at
        # first write (mkdir(parents=True, exist_ok=True)). No explicit
        # mkdir at startup -- keeps the wiring side-effect free.
        runtime.idea_capture_store = IdeaCaptureStore(
            store_path=idea_path,
            emit_event=runtime.emit_event,
        )
        runtime.ready_room_session_manager = ReadyRoomSessionManager(
            runtime=runtime,
            emit_event=runtime.emit_event,
            wardroom_channel_id=config.ready_room.wardroom_channel_id,
        )
        logger.info(
            "AD-475: Ready Room wired (idea store=%s, channel=%s)",
            idea_path, config.ready_room.wardroom_channel_id,
        )
    else:
        runtime.idea_capture_store = None
        runtime.ready_room_session_manager = None

    # AD-538b: Dream manifest (skip-already-processed marker; survives restart)
    try:
        from probos.cognitive.dream_manifest import DreamManifest
        runtime.dream_manifest = DreamManifest(
            store_path=runtime.data_dir / "dream_manifest.json",
        )
        # Late-bind the manifest into the dreaming engine if it's already wired
        _de = getattr(runtime, "dreaming_engine", None)
        if _de is not None:
            try:
                _de._manifest = runtime.dream_manifest
            except Exception:
                logger.warning(
                    "AD-538b: failed to bind manifest to dreaming engine",
                    exc_info=True,
                )
    except Exception:
        logger.warning("AD-538b: DreamManifest wiring failed", exc_info=True)
        runtime.dream_manifest = None

    # AD-572b: Captain engagement provider (proactive context signals)
    try:
        from probos.cognitive.captain_engagement import CaptainEngagementProvider
        runtime.captain_engagement_provider = CaptainEngagementProvider(
            runtime=runtime,
            emit_event=runtime.emit_event,
        )
    except Exception:
        logger.warning(
            "AD-572b: CaptainEngagementProvider wiring failed", exc_info=True,
        )
        runtime.captain_engagement_provider = None

    # AD-469: EPS - Compute/Token Distribution (v1 foundation)
    if config.eps.enabled:
        from probos.cognitive.eps import (
            CapacityTracker,
            DepartmentBudget,
            DepartmentBudgetTable,
            EPSCoordinator,
        )
        capacity = CapacityTracker(
            runtime=runtime,
            window_seconds=config.eps.window_seconds,
        )
        budgets = DepartmentBudgetTable(
            departments=[
                DepartmentBudget(
                    name=d.name, percent=d.percent, priority=d.priority,
                )
                for d in config.eps.departments
            ],
        )
        runtime.eps_coordinator = EPSCoordinator(
            capacity_tracker=capacity,
            budget_table=budgets,
            emit_event=runtime.emit_event,
            over_budget_threshold=config.eps.over_budget_threshold,
        )
        logger.info(
            "AD-469: EPSCoordinator wired (%d departments, window=%.0fs)",
            len(config.eps.departments),
            config.eps.window_seconds,
        )
    else:
        runtime.eps_coordinator = None

    # AD-449: MCP Bridge (v1 OSS infrastructure)
    # AD-1014: stdio/subprocess transport (default-OFF; gated by command
    # allowlist + consent). The consent adapter is defined here so the bridge
    # stays decoupled from HookBus — HookEvent is imported in finalize, not the
    # bridge.
    if config.mcp.enabled:
        from probos.integrations.mcp_bridge import MCPBridge
        from probos.hooks.bus import HookEvent

        async def _mcp_consent(ctx: dict[str, Any]) -> bool:
            hb = getattr(runtime, "hook_bus", None)
            if hb is None:
                return True  # no bus -> allowlist is the guard (stdio already opt-in)
            decision = await hb.fire(HookEvent.PRE_TOOL_USE, ctx)
            return decision.allowed  # fail-safe: refuse on ASK or DENY (no approval loop yet)

        runtime.mcp_bridge = MCPBridge(
            egress_policy=getattr(runtime, "egress_policy", None),
            emit_event=runtime.emit_event,
            request_timeout=config.mcp.request_timeout_seconds,
            stdio_enabled=config.mcp.stdio_enabled,
            command_allowlist=config.mcp.command_allowlist,
            consent_fn=_mcp_consent,
        )
        for srv in config.mcp.servers:
            runtime.mcp_bridge.register_server(srv.url, headers=dict(srv.headers))
        # AD-1014: inert by default (stdio_enabled=False) and inert with the
        # default empty servers list -> byte-identical boot.
        if config.mcp.stdio_enabled:
            for srv in config.mcp.servers:
                if srv.type == "stdio":
                    await runtime.mcp_bridge.register_stdio_server(
                        name=srv.command,
                        command=srv.command,
                        args=srv.args,
                        env=srv.env,
                        cwd=srv.cwd,
                        timeout=srv.timeout_seconds,
                    )
        # AD-1015: runtime-mutable MCP server management store (default-OFF gate
        # config.mcp.management_enabled). Config servers register FIRST (above);
        # stored rows register SECOND so config wins — the bridge returns False on
        # a duplicate key, so the seed loop never double-registers. A fresh DB has
        # an empty cache -> the seed loop is a no-op -> byte-identical boot.
        if config.mcp.management_enabled:
            from probos.integrations.mcp_bridge.store import McpServerStore

            mcp_server_store = McpServerStore(
                db_path=str(runtime.data_dir / "mcp_servers.db")
            )
            await mcp_server_store.start()
            runtime.mcp_server_store = mcp_server_store
            for rec in mcp_server_store.list_sync():
                if not rec.enabled:
                    continue
                if rec.type == "http":
                    runtime.mcp_bridge.register_server(
                        rec.url, headers=dict(rec.headers)
                    )
                else:
                    await runtime.mcp_bridge.register_stdio_server(
                        name=rec.name,
                        command=rec.command,
                        args=rec.args,
                        env=rec.env,
                        cwd=rec.cwd,
                        timeout=rec.timeout_seconds,
                    )
            # AD-1019b: department-tier grant store (the "department locker" of
            # the three-tier authorization model) + per-tool risk override store.
            from probos.integrations.mcp_bridge.department_grants import (
                DepartmentToolGrantStore,
            )
            from probos.integrations.mcp_bridge.risk import McpToolRiskStore

            dept_grant_store = DepartmentToolGrantStore(
                db_path=str(runtime.data_dir / "department_tool_grants.db")
            )
            await dept_grant_store.start()
            runtime.department_tool_grant_store = dept_grant_store

            risk_store = McpToolRiskStore(
                db_path=str(runtime.data_dir / "mcp_tool_risk.db")
            )
            await risk_store.start()
            runtime.mcp_tool_risk_store = risk_store
        else:
            runtime.mcp_server_store = None
            runtime.department_tool_grant_store = None
            runtime.mcp_tool_risk_store = None
        logger.info(
            "AD-449: MCPBridge wired (%d server(s) preregistered)",
            len(config.mcp.servers),
        )
    else:
        runtime.mcp_bridge = None
        runtime.mcp_server_store = None
        runtime.department_tool_grant_store = None
        runtime.mcp_tool_risk_store = None

    # AD-701: Visiting Officer registry (formal external-participant registration).
    # Sourced from VesselIdentity (ontology) since runtime does not expose
    # instance_id / vessel_name / version directly. Default-False per
    # convention #14; opt-in via config.visiting_officers.enabled.
    from probos.config import VisitingOfficersConfig as _VOConfig
    vo_cfg = getattr(config, "visiting_officers", None)
    if (
        isinstance(vo_cfg, _VOConfig)
        and vo_cfg.enabled
        and getattr(runtime, "identity_registry", None) is not None
    ):
        from probos.visiting_officers import VisitingOfficerRegistry
        ontology = getattr(runtime, "ontology", None)
        if ontology is not None:
            try:
                vi = ontology.get_vessel_identity()
                instance_id = vi.instance_id
                vessel_name = vi.name
                baseline_version = vi.version or config.system.version
            except Exception:
                logger.warning(
                    "AD-701: vessel-identity lookup failed; falling back to config.system.version",
                    exc_info=True,
                )
                instance_id = ""
                vessel_name = "ProbOS"
                baseline_version = config.system.version
        else:
            instance_id = ""
            vessel_name = "ProbOS"
            baseline_version = config.system.version
        emit_fn = getattr(runtime, "emit_event", None)
        runtime.visiting_officers = VisitingOfficerRegistry(
            identity_registry=runtime.identity_registry,
            instance_id=instance_id,
            vessel_name=vessel_name,
            baseline_version=baseline_version,
            emit_event=emit_fn,
            session_ttl_seconds=vo_cfg.session_ttl_seconds,
            sweep_interval_seconds=vo_cfg.sweep_interval_seconds,
        )
        await runtime.visiting_officers.start()
        logger.info(
            "AD-701: VisitingOfficerRegistry wired (ttl=%.0fs, sweep=%.0fs)",
            vo_cfg.session_ttl_seconds,
            vo_cfg.sweep_interval_seconds,
        )
    else:
        runtime.visiting_officers = None

    # AD-707: Workflow Cron Trigger scheduler
    from probos.config import WorkflowCronTriggerConfig as _WFCConfig
    wfc_cfg = getattr(config, "workflow_cron", None)
    if isinstance(wfc_cfg, _WFCConfig) and wfc_cfg.enabled:
        from probos.cognitive.workflow_cron import WorkflowCronScheduler

        runtime.workflow_cron = WorkflowCronScheduler(
            process_nl_fn=runtime.process_natural_language,
            db_path=wfc_cfg.db_path or None,
            tick_interval_seconds=wfc_cfg.tick_interval_seconds,
        )
        await runtime.workflow_cron.start()
        for entry in wfc_cfg.initial_triggers:
            try:
                await runtime.workflow_cron.register(
                    entry["user_input"], entry["cron_expr"],
                )
            except Exception:
                logger.warning(
                    "AD-707: initial trigger failed to register: %s",
                    entry,
                    exc_info=True,
                )
        logger.info(
            "AD-707: WorkflowCronScheduler wired (%d initial trigger(s); db=%s)",
            len(wfc_cfg.initial_triggers),
            wfc_cfg.db_path or "<in-memory>",
        )
    else:
        runtime.workflow_cron = None

    # Memvid pattern 1: QueryPlanner for relational query routing.
    from probos.config import QueryPlannerConfig as _QPConfig
    qp_cfg = getattr(config, "query_planner", None)
    if isinstance(qp_cfg, _QPConfig) and qp_cfg.enabled:
        from probos.cognitive.query_planner import QueryPlanner

        runtime.query_planner = QueryPlanner()
        logger.info("Memvid pattern 1: QueryPlanner wired (relational query routing)")
    else:
        runtime.query_planner = None

    # AD-480: inbound MCP / A2A servers (default-False — opt-in).
    if config.federation.mcp_server.enabled:
        try:
            from probos.federation.mcp_server import FederationMCPServer
            runtime.federation_mcp_server = FederationMCPServer(
                runtime=runtime, config=config.federation.mcp_server,
            )
            await runtime.federation_mcp_server.start()
            logger.info(
                "AD-480a: MCP server started on %s:%d",
                config.federation.mcp_server.bind_host,
                config.federation.mcp_server.bind_port,
            )
        except Exception as exc:
            logger.warning("AD-480a: MCP server start failed: %s", exc)
            runtime.federation_mcp_server = None
    if config.federation.a2a.enabled:
        try:
            from probos.federation.a2a.server import FederationA2AServer
            runtime.federation_a2a_server = FederationA2AServer(
                runtime=runtime, config=config.federation.a2a,
            )
            await runtime.federation_a2a_server.start()
            logger.info(
                "AD-480d: A2A server started on %s:%d",
                config.federation.a2a.bind_host,
                config.federation.a2a.bind_port,
            )
        except Exception as exc:
            logger.warning("AD-480d: A2A server start failed: %s", exc)
            runtime.federation_a2a_server = None

    # AD-641a: Observability Bridge
    ob_cfg = getattr(getattr(runtime, "config", None), "observability_bridge", None)
    if ob_cfg is not None and ob_cfg.enabled:
        from probos.cognitive.observability import ObservabilityBridge
        runtime.observability_bridge = ObservabilityBridge(
            runtime=runtime,
            ward_room=getattr(runtime, "ward_room", None),
            emit_event=runtime.emit_event,
            publish_interval_seconds=ob_cfg.publish_interval_seconds,
            system_channel=ob_cfg.system_channel,
        )
        # Hold the start task on runtime so it isn't garbage-collected.
        # Public attribute (Wave 5 convention #1) -- consumer-facing for tests
        # that need to await startup completion.
        runtime.observability_bridge_start_task = asyncio.create_task(
            runtime.observability_bridge.start(),
            name="observability_bridge_start",
        )
        logger.info("AD-641a: ObservabilityBridge wired (channel=%s, interval=%.0fs)",
                    ob_cfg.system_channel, ob_cfg.publish_interval_seconds)
    else:
        runtime.observability_bridge = None

    # AD-695: Threshold Alert Service — replaces AD-641a continuous posting
    ta_cfg = getattr(getattr(runtime, "config", None), "threshold_alerts", None)
    if ta_cfg is not None and ta_cfg.enabled:
        from probos.cognitive.threshold_alerts import ThresholdAlertService
        runtime.threshold_alerts = ThresholdAlertService(
            runtime,
            pool_saturation_floor=ta_cfg.pool_saturation_floor,
            degradation_min_severity=ta_cfg.degradation_min_severity,
            attention_queue_depth=ta_cfg.attention_queue_depth,
            dedup_window_seconds=ta_cfg.dedup_window_seconds,
        )
        logger.info(
            "AD-695: ThresholdAlertService wired "
            "(pool>=%.0f%%, degradation>=%s, attention>=%d, dedup=%.0fs)",
            ta_cfg.pool_saturation_floor * 100,
            ta_cfg.degradation_min_severity,
            ta_cfg.attention_queue_depth,
            ta_cfg.dedup_window_seconds,
        )
    else:
        runtime.threshold_alerts = None

    # AD-695: Stitch Tier 7 health provider onto Oracle. ``runtime`` itself
    # satisfies the duck-typed contract (spawner / attention / degradation_manager
    # / observability_bridge). Done here in finalize because OracleService is
    # built in the cognitive phase BEFORE attention / spawner / degradation_manager
    # are fully populated, so late-bind is required.
    oracle_for_health = getattr(runtime, "_oracle_service", None) or getattr(runtime, "oracle", None)
    if oracle_for_health is not None:
        try:
            oracle_for_health.attach_health_provider(runtime)
        except Exception:
            logger.warning(
                "AD-695: failed to attach health provider to OracleService; "
                "Tier 7 health queries will return [] until restart",
                exc_info=True,
            )

    # AD-641b: Ward Room Hebbian Router (router only; listener deferred to AD-641b-iv)
    wr_heb_cfg = getattr(getattr(runtime, "config", None), "ward_room_hebbian", None)
    if wr_heb_cfg is not None and wr_heb_cfg.enabled:
        from probos.cognitive.ward_room_hebbian import WardRoomHebbianRouter
        runtime.ward_room_hebbian_router = WardRoomHebbianRouter(
            emit_event=runtime.emit_event,
            learning_rate=wr_heb_cfg.learning_rate,
            decay_factor=wr_heb_cfg.decay_factor,
        )
        logger.info("AD-641b: WardRoomHebbianRouter wired (lr=%.2f, decay=%.2f)",
                    wr_heb_cfg.learning_rate, wr_heb_cfg.decay_factor)
    else:
        runtime.ward_room_hebbian_router = None

    # AD-641f: Engineering Sensor Service
    es_cfg = getattr(getattr(runtime, "config", None), "engineering_sensors", None)
    if es_cfg is not None and es_cfg.enabled:
        from probos.cognitive.engineering_sensors import EngineeringSensorService
        runtime.engineering_sensor_service = EngineeringSensorService(
            runtime=runtime,
            emit_event=runtime.emit_event,
            report_interval_seconds=es_cfg.report_interval_seconds,
        )
        if es_cfg.auto_start_periodic_report:
            # Hold the start task on runtime so it isn't garbage-collected.
            # Public attribute (Wave 5 convention #1) -- consumer-facing for tests
            # that need to await startup completion.
            runtime.engineering_sensor_start_task = asyncio.create_task(
                runtime.engineering_sensor_service.start(),
                name="engineering_sensor_start",
            )
        logger.info("AD-641f: EngineeringSensorService wired (interval=%.0fs, auto_start=%s)",
                    es_cfg.report_interval_seconds, es_cfg.auto_start_periodic_report)
    else:
        runtime.engineering_sensor_service = None

    # AD-641e: LearnedShortcut Registry
    ls_cfg = getattr(getattr(runtime, "config", None), "learned_shortcuts", None)
    if ls_cfg is not None and ls_cfg.enabled:
        from probos.cognitive.learned_shortcuts import (
            LearnedShortcutRegistry,
            WorkflowCacheBackend,
        )
        runtime.learned_shortcut_registry = LearnedShortcutRegistry(
            emit_event=runtime.emit_event,
        )
        if ls_cfg.register_workflow_cache:
            wf = getattr(runtime, "workflow_cache", None)
            if wf is not None:
                runtime.learned_shortcut_registry.register(
                    WorkflowCacheBackend(workflow_cache=wf),
                )
        logger.info("AD-641e: LearnedShortcutRegistry wired (kinds=%s)",
                    runtime.learned_shortcut_registry.kinds)
    else:
        runtime.learned_shortcut_registry = None

    # AD-641c: Thread Priority Service
    tp_cfg = getattr(getattr(runtime, "config", None), "thread_priority", None)
    if tp_cfg is not None and tp_cfg.enabled:
        from probos.cognitive.thread_priority import (
            ThreadPriorityScorer,
            ThreadPriorityService,
        )
        runtime.thread_priority_service = ThreadPriorityService(
            runtime=runtime,
            scorer=ThreadPriorityScorer(
                weight_captain=tp_cfg.weight_captain,
                weight_unresolved=tp_cfg.weight_unresolved,
                weight_cross_department=tp_cfg.weight_cross_department,
                weight_recency=tp_cfg.weight_recency,
                weight_endorsement=tp_cfg.weight_endorsement,
            ),
            emit_event=runtime.emit_event,
            captain_callsign=tp_cfg.captain_callsign,
        )
        logger.info("AD-641c: ThreadPriorityService wired (captain=%s)",
                    tp_cfg.captain_callsign)
    else:
        runtime.thread_priority_service = None

    # AD-641d: Crew Deliberation Protocol
    delib_cfg = getattr(getattr(runtime, "config", None), "deliberation", None)
    if delib_cfg is not None and delib_cfg.enabled:
        from probos.cognitive.deliberation import DeliberationProtocol
        runtime.deliberation_protocol = DeliberationProtocol(
            ward_room=getattr(runtime, "ward_room", None),
            emit_event=runtime.emit_event,
            captain_callsign=delib_cfg.captain_callsign,
        )
        logger.info("AD-641d: DeliberationProtocol wired (captain=%s)",
                    delib_cfg.captain_callsign)
    else:
        runtime.deliberation_protocol = None

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
        runtime.ontology.billet_registry.set_event_callback(runtime.emit_event)
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
        runtime._bill_runtime.set_event_callback(runtime.emit_event)
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
            emit_event_fn=runtime.emit_event,
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
            event_emitter=runtime.emit_event,
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
                    emit_event=runtime.emit_event,
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
                emit_event=runtime.emit_event,
            )
            runtime.dispatcher = dispatcher
            logger.info("Startup [finalize]: AD-654c Dispatcher created")

            # AD-438: Ontology-Based Task Routing
            from probos.activation.task_router import TaskRouter
            task_router = TaskRouter(ontology=runtime.ontology)
            runtime._task_router = task_router
            logger.info(
                "AD-438: TaskRouter initialized with %d mappings",
                len(task_router.list_mappings()),
            )

            # AD-654d: Wire dispatcher into internal emitters
            if runtime.work_item_store:
                runtime.work_item_store.attach_dispatcher(runtime.dispatcher)
            if runtime.ward_room:
                runtime.ward_room.attach_dispatcher(runtime.dispatcher, runtime.callsign_registry)

            # AD-581 v1: HybridDispatch -- must follow AD-654c so runtime.dispatcher
            # is available. _wire_hybrid_dispatch is tier-2 log-and-degrade.
            if _wire_hybrid_dispatch(runtime=runtime, config=config):
                logger.info("AD-581 v1: HybridDispatch wired during finalization")

            # AD-876: Quartermaster board reconciler cadence -- must follow
            # _wire_hybrid_dispatch (depends on runtime.work_item_router).
            # Tier-2 log-and-degrade.
            if _wire_board_reconciler(runtime=runtime, config=config):
                logger.info("AD-876: BoardReconciler wired during finalization")

            # AD-855: CapabilityGapDriver -- BLOCKED -> request -> approve ->
            # resume loop. Independent of hybrid dispatch; only needs the
            # work-item + capability-request stores. Tier-2 log-and-degrade.
            if _wire_capability_gap_driver(runtime=runtime, config=config):
                logger.info("AD-855: CapabilityGapDriver wired during finalization")

            # AD-857: capability-request Captain-DM notifier -- chat half of the
            # dual-surface decision surface. Tier-2 log-and-degrade.
            if _wire_capability_request_notifier(runtime=runtime, config=config):
                logger.info(
                    "AD-857: capability-request Captain-DM notifier wired "
                    "during finalization"
                )

            # AD-846: Yeo task-completion Captain-DM notifier -- async half of
            # Yeo's Tier-3 delegation loop. Tier-2 log-and-degrade.
            if _wire_task_completion_notifier(runtime=runtime, config=config):
                logger.info(
                    "AD-846: task-completion Captain-DM notifier wired "
                    "during finalization"
                )

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

        # AD-448: Wrapped Tool Executor
        from probos.tools.executor import ToolExecutor, make_audit_hook
        tool_executor = ToolExecutor(registry=runtime.tool_registry)
        audit_hook = make_audit_hook(
            emit_fn=runtime.emit_event,
        )
        tool_executor.add_post_hook(audit_hook)
        runtime._tool_executor = tool_executor
        logger.info("AD-448: ToolExecutor initialized with %d hooks", tool_executor.hook_count)

        # AD-543/544/548/549: Wire native SWE harness (tools + blocked-paths hook + harness)
        _wire_native_swe_harness(runtime=runtime, config=config, tool_executor=tool_executor)

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
        emit_event_fn=runtime.emit_event,
        dispatcher=runtime.dispatcher,                # AD-654d
        callsign_registry=runtime.callsign_registry,  # AD-654d
    )

    # AD-597: Wire MCP App Host registry (default-False; serves internal games when enabled)
    try:
        _wire_mcp_app_host(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-597: _wire_mcp_app_host failed", exc_info=True)

    # AD-706: Wire BrowserTool (default-False; Computer Use via Playwright when enabled)
    try:
        _wire_browser_tool(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-706: _wire_browser_tool failed", exc_info=True)

    # AD-909: Seed the universal mesh read-intents (web_search, read_page,
    # http_fetch) into the persistent tool catalog so they are visible in
    # GET /api/tools + the AD-885 lens and restrictable per-agent from boot —
    # not only after the first agentic dispatch lazily registers them.
    try:
        _wire_mesh_intent_tools(runtime=runtime)
    except Exception:
        logger.warning("AD-909: _wire_mesh_intent_tools failed", exc_info=True)

    # AD-706b: async portion of browser-tool wiring - start the recording reaper.
    try:
        await _start_recording_reaper(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-706b: _start_recording_reaper failed", exc_info=True)

    # AD-733-1: AttachmentStore retention reaper. Active when perception is
    # enabled (ephemeral frames need TTL) or when max_store_bytes > 0
    # (LRU safety net). Failure honest-degrades -- never blocks boot.
    try:
        await _start_attachment_reaper(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-733-1: _start_attachment_reaper failed", exc_info=True)

    # AD-986d: transcript retention reaper. Default-off (opt-in via
    # memory.transcript_retention_days > 0); purges stale room recordings and
    # leaves tombstones for the purge-indication path. Honest-degrades on failure.
    try:
        await _start_transcript_reaper(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-986d: _start_transcript_reaper failed", exc_info=True)

    # AD-520: Wire Spatial Knowledge Explorer (default-False; constructs runtime.spatial_layout)
    try:
        _wire_spatial_explorer(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-520: _wire_spatial_explorer failed", exc_info=True)

    # AD-562: Wire Knowledge Browser service (default-False; constructs runtime.knowledge_browser)
    try:
        _wire_knowledge_browser(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-562: _wire_knowledge_browser failed", exc_info=True)

    # AD-632b: Wire SubTaskExecutor + QueryHandler for Level 3 cognitive escalation
    try:
        from probos.cognitive.sub_task import SubTaskExecutor, SubTaskType
        from probos.cognitive.sub_tasks import (
            AnalyzeHandler, ComposeHandler, EvaluateHandler, QueryHandler, ReflectHandler,
        )
        from probos.cognitive.chain_nats_bridge import ChainNATSBridge

        sub_task_config = config.sub_task
        # AD-641g: publish-side bridge — no-op when nats_publish_enabled=False.
        # Stream provisioning happens in startup/nats.py (canonical location).
        chain_nats_bridge = ChainNATSBridge(
            nats_bus=getattr(runtime, "nats_bus", None),
            config=sub_task_config,
        )
        runtime.chain_nats_bridge = chain_nats_bridge
        # AD-641g-1: consumer-side foundation — siblings of the bridge.
        # Only constructed; downstream ADs register handlers + call start().
        from probos.cognitive.chain_nats_consumer import ChainNATSConsumer
        chain_nats_consumer = ChainNATSConsumer(
            nats_bus=getattr(runtime, "nats_bus", None),
            config=sub_task_config,
        )
        runtime.chain_nats_consumer = chain_nats_consumer
        executor = SubTaskExecutor(
            config=sub_task_config,
            emit_event_fn=runtime.emit_event,
            nats_bridge=chain_nats_bridge,
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

    # AD-633: Wire PredictiveBranching after SubTaskExecutor so speculation
    # can dispatch chains. Tier-2 log-and-degrade.
    try:
        _wire_predictive_branching(runtime=runtime, config=config)
    except Exception:
        logger.warning(
            "AD-633: _wire_predictive_branching raised; predictive_branching disabled",
            exc_info=True,
        )

    # AD-482: Wire SelfImprovementPipeline after PredictiveBranching. Default-False;
    # operator opt-in. Tier-2 log-and-degrade.
    try:
        _wire_self_improvement(runtime=runtime, config=config)
    except Exception:
        logger.warning(
            "AD-482: _wire_self_improvement raised; self_improvement disabled",
            exc_info=True,
        )

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
                    emit_event_fn=runtime.emit_event,
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
            event_emitter=runtime.emit_event,
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
        event_emitter=runtime.emit_event,
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
        working_memory=getattr(runtime, "working_memory", None),  # AD-573d
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
                emit_event_fn=runtime.emit_event,
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

    # AD-445: Decision Queue
    from probos.governance.decision_queue import DecisionQueue
    decision_queue = DecisionQueue(
        emit_fn=runtime.emit_event,
    )
    runtime._decision_queue = decision_queue
    logger.info("AD-445: DecisionQueue initialized")

    # AD-446: Compensation & Recovery
    from probos.governance.compensation import CompensationHandler
    compensation_handler = CompensationHandler(
        emit_fn=runtime.emit_event,
    )
    runtime._compensation_handler = compensation_handler
    logger.info("AD-446: CompensationHandler initialized")

    # AD-477: Naval Organization Protocols (v1: Captain's Log + Plan of the Day)
    naval_cfg = getattr(config, "naval_organization", None)
    runtime.captains_log_service = None
    runtime.captains_log_start_task = None
    runtime.plan_of_day_service = None
    runtime.plan_of_day_start_task = None
    if naval_cfg is not None:
        from probos.naval import CaptainsLogService, PlanOfDayService

        if naval_cfg.captains_log.enabled:
            runtime.captains_log_service = CaptainsLogService(runtime, naval_cfg.captains_log)
            runtime.captains_log_start_task = asyncio.create_task(
                runtime.captains_log_service.start()
            )
            logger.info(
                "AD-477: CaptainsLogService started (output_dir=%s)",
                naval_cfg.captains_log.output_dir,
            )
        if naval_cfg.plan_of_day.enabled:
            runtime.plan_of_day_service = PlanOfDayService(runtime, naval_cfg.plan_of_day)
            runtime.plan_of_day_start_task = asyncio.create_task(
                runtime.plan_of_day_service.start()
            )
            logger.info(
                "AD-477: PlanOfDayService started (output_dir=%s)",
                naval_cfg.plan_of_day.output_dir,
            )

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
        len(runtime.red_team_agents),
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

    # AD-733a (Wave 171): VisionConsumer — bridge vision_observation -> WM.
    # Tier-2 honest-degrade: any wiring failure logs WARNING and leaves
    # vision_observation intents unconsumed (matches AD-733 v1 behaviour).
    try:
        _perception_cfg = getattr(getattr(runtime, "config", None), "perception", None)
        if (
            _perception_cfg is not None
            and _perception_cfg.enabled
            and getattr(_perception_cfg, "vision_consumer_enabled", False)
        ):
            from probos.perception.consumer import VisionConsumer

            # AD-742f: wire the shared SQLite WM store before observers register.
            if getattr(_perception_cfg, "wm_persistence_enabled", True):
                try:
                    from pathlib import Path
                    from probos.perception.consumer import set_working_memory_store
                    from probos.perception.wm_store import WorkingMemoryStore
                    _data_dir = Path(getattr(runtime, "data_dir", None) or "data")
                    _wm_store = WorkingMemoryStore(_data_dir / "perception_wm.db")
                    if _wm_store.available:
                        set_working_memory_store(_wm_store)
                        runtime.vision_wm_store = _wm_store
                        logger.info("AD-742f: vision WM persistence active")
                    else:
                        runtime.vision_wm_store = None
                except Exception:
                    logger.warning(
                        "AD-742f: WM store wiring failed; in-memory-only ring",
                        exc_info=True,
                    )
                    runtime.vision_wm_store = None
            else:
                runtime.vision_wm_store = None

            consumer = VisionConsumer(
                runtime,
                min_interval_seconds=_perception_cfg.vision_min_interval_seconds,
                novelty_threshold=_perception_cfg.vision_novelty_threshold,
                baseline_max_age_seconds=_perception_cfg.vision_baseline_max_age_seconds,
                working_memory_capacity=_perception_cfg.working_memory_capacity,
                vision_tier=_perception_cfg.vision_tier,
                vision_fast_tier=_perception_cfg.vision_fast_tier,
                supervisor_strategy_name=getattr(
                    _perception_cfg, "vision_supervisor_strategy", "ahash"
                ),
            )
            # BF-287: never reach into registry.agents — use public all().
            for agent in runtime.registry.all():
                _prof = runtime.callsign_registry.get_profile(
                    getattr(agent, "agent_type", "")
                )
                if (_prof or {}).get("vision_capable", False):
                    consumer.register_observer(agent.id)
            # AD-746 Layer 1: when fusion is enabled, the VisionAggregator
            # subscribes to vision_observation and forwards (passthrough
            # OR fused) into the consumer. The consumer's own subscribe
            # is skipped — the aggregator IS the consumer's bus front.
            _fusion_enabled = bool(getattr(
                _perception_cfg, "source_fusion_enabled", False,
            ))
            if _fusion_enabled:
                try:
                    from probos.perception.aggregator import VisionAggregator
                    _window_ms = int(getattr(
                        _perception_cfg, "fusion_window_ms", 800,
                    ))
                    _aggregator = VisionAggregator(
                        runtime, consumer, fusion_window_ms=_window_ms,
                    )
                    _aggregator.subscribe()
                    runtime.vision_aggregator = _aggregator
                    logger.info(
                        "AD-746 Layer 1: VisionAggregator wired (window=%dms); "
                        "VisionConsumer.subscribe() skipped",
                        _window_ms,
                    )
                except Exception:
                    logger.warning(
                        "AD-746: aggregator wiring failed; falling back to "
                        "direct VisionConsumer.subscribe()",
                        exc_info=True,
                    )
                    runtime.vision_aggregator = None
                    consumer.subscribe()
            else:
                runtime.vision_aggregator = None
                consumer.subscribe()
            runtime.vision_consumer = consumer
            logger.info(
                "AD-733a: VisionConsumer wired with %d observers",
                len(consumer.observer_agent_ids),
            )

            # AD-742b: face-embedding identity resolver. Lazy-construct;
            # MTCNN + ResNet models load on first .resolve() call.
            if getattr(_perception_cfg, "identity_resolver_enabled", True):
                try:
                    from probos.perception.identity import IdentityResolver
                    from pathlib import Path
                    _data_dir = Path(getattr(runtime, "data_dir", None) or "data")
                    _resolver = IdentityResolver(
                        data_dir=_data_dir,
                        threshold=getattr(_perception_cfg, "identity_match_threshold", 0.6),
                    )
                    consumer.set_identity_resolver(_resolver)
                    runtime.identity_resolver = _resolver
                    logger.info(
                        "AD-742b: IdentityResolver wired (enrolled=%s, threshold=%.2f)",
                        _resolver.is_enrolled(),
                        getattr(_perception_cfg, "identity_match_threshold", 0.6),
                    )
                except Exception:
                    logger.warning(
                        "AD-742b: IdentityResolver wiring failed; falling back to "
                        "AD-733b LLM-prompt path. Likely facenet-pytorch import error.",
                        exc_info=True,
                    )

            # BF-312: one-shot backfill for pre-BF-311 orphaned perception
            # episodes that were stored with agent_ids=[] and are therefore
            # invisible to per-agent recall. Idempotent on subsequent boots.
            try:
                from probos.perception.backfill import (
                    backfill_perception_episode_agent_ids,
                )
                _bf_count = await backfill_perception_episode_agent_ids(
                    runtime.episodic_memory,
                    list(consumer.observer_agent_ids),
                )
                if _bf_count:
                    logger.info(
                        "BF-312: backfilled agent_ids on %d orphaned "
                        "perception episode(s)", _bf_count,
                    )
            except Exception:
                logger.warning(
                    "BF-312: perception backfill failed; orphaned episodes "
                    "remain unrecallable. Non-fatal.",
                    exc_info=True,
                )

            # AD-733c-2 (Wave 172): PerceptionModeController -- drives the
            # BF-308 setters based on engagement state. Default: AMBIENT
            # when perception enabled; the idle watchdog (AD-733c-4) will
            # eventually drop to DORMANT after extended idle.
            from probos.perception.mode_controller import (
                Mode as _PerceptionMode,
                PerceptionModeController,
            )
            _controller = PerceptionModeController(
                runtime,
                initial_mode=_PerceptionMode.AMBIENT,
                engaged_idle_seconds=_perception_cfg.engaged_idle_seconds,
                ambient_idle_seconds=_perception_cfg.ambient_idle_seconds,
                idle_tick_seconds=_perception_cfg.idle_watchdog_tick_seconds,
            )
            # Apply the AMBIENT preset to the live supervisor so the
            # default boot state matches the mode.
            _controller.transition_to(_PerceptionMode.AMBIENT, trigger="init")
            await _controller.start()
            runtime.perception_mode_controller = _controller
            logger.info("AD-733c-2: PerceptionModeController wired (initial=ambient)")

            # AD-733c-5: Per-agent engagement registry. The singleton
            # ``runtime.perception_mode_controller`` above stays alive as
            # the back-compat pointer (consumed by AD-733c-6 budget
            # enforcement + ProactiveVisionObserver). For each crew agent
            # whose CrewProfile.perception.engagement_enabled is True, we
            # spawn an additional per-agent controller and register it so
            # DM-targeted activity, engage endpoint hits, and HXI badges
            # can resolve per agent.
            try:
                from probos.perception.engagement_registry import (
                    PerceptionEngagementRegistry,
                    select_primary_controller,
                )
                _registry = PerceptionEngagementRegistry(runtime)
                _profile_store = getattr(runtime, "profile_store", None)
                for _agent in runtime.registry.all():
                    if not is_crew_agent(_agent, runtime.ontology):
                        continue
                    _profile = (
                        _profile_store.get(_agent.id)
                        if _profile_store is not None
                        else None
                    )
                    _enabled = True
                    _initial_mode_name = "ambient"
                    if _profile is not None and _profile.perception is not None:
                        _enabled = bool(_profile.perception.engagement_enabled)
                        _initial_mode_name = _profile.perception.initial_mode or "ambient"
                    if not _enabled:
                        logger.info(
                            "AD-733c-5: agent=%s engagement_enabled=False; "
                            "skipping per-agent controller",
                            _agent.id,
                        )
                        continue
                    try:
                        _initial = _PerceptionMode(_initial_mode_name)
                    except Exception:
                        _initial = _PerceptionMode.AMBIENT
                    _per_ctrl = PerceptionModeController(
                        runtime,
                        initial_mode=_initial,
                        engaged_idle_seconds=_perception_cfg.engaged_idle_seconds,
                        ambient_idle_seconds=_perception_cfg.ambient_idle_seconds,
                        idle_tick_seconds=_perception_cfg.idle_watchdog_tick_seconds,
                        agent_id=_agent.id,
                    )
                    _per_ctrl.transition_to(_initial, trigger="init")
                    await _per_ctrl.start()
                    _registry.register(_agent.id, _per_ctrl)
                    logger.info(
                        "AD-733c-5: per-agent controller wired agent=%s "
                        "initial=%s",
                        _agent.id, _initial.value,
                    )
                runtime.perception_engagement_registry = _registry
                # Back-compat: if there's at least one per-agent
                # controller, repoint the singleton to the primary so
                # legacy code keeps working with the same instance the
                # registry returns.
                _primary = select_primary_controller(_registry)
                if _primary is not None:
                    runtime.perception_mode_controller = _primary
                logger.info(
                    "AD-733c-5: engagement registry wired (%d per-agent controllers)",
                    len(_registry),
                )
            except Exception:
                logger.warning(
                    "AD-733c-5: engagement registry wiring failed; "
                    "falling back to legacy singleton",
                    exc_info=True,
                )
                runtime.perception_engagement_registry = None

            if getattr(_perception_cfg, "proactive_observer_enabled", False):
                from probos.perception.observer import (
                    ProactiveBudget,
                    ProactiveVisionObserver,
                )
                observer = ProactiveVisionObserver(
                    runtime,
                    budget=ProactiveBudget(
                        max_emissions_per_session=_perception_cfg.proactive_max_emissions,
                        min_dwell_seconds=_perception_cfg.proactive_dwell_seconds,
                        novelty_threshold=_perception_cfg.proactive_novelty_threshold,
                    ),
                )
                consumer.wire_proactive_observer(observer)
                runtime.vision_observer = observer
                logger.info("AD-733b: ProactiveVisionObserver wired")
            else:
                runtime.vision_observer = None
        else:
            runtime.vision_consumer = None
            runtime.vision_observer = None
            runtime.perception_mode_controller = None
            runtime.perception_engagement_registry = None
    except Exception:
        logger.warning(
            "AD-733a: VisionConsumer wiring failed; "
            "vision_observation intents will be silently dropped",
            exc_info=True,
        )

    # AD-743: ConversationPacingScheduler wiring (default-OFF transitional).
    try:
        _avatars_cfg = getattr(runtime.config, "avatars", None)
        if _avatars_cfg is not None and getattr(
            _avatars_cfg, "pacing_enabled", False
        ):
            from probos.cognitive.dm.pacing_scheduler import (
                ConversationPacingScheduler,
            )
            _scheduler = ConversationPacingScheduler(runtime)
            await _scheduler.start()
            runtime.conversation_pacing_scheduler = _scheduler
            logger.info(
                "AD-743: ConversationPacingScheduler wired (pacing_enabled=True)"
            )
        else:
            runtime.conversation_pacing_scheduler = None
    except Exception:
        logger.warning(
            "AD-743: ConversationPacingScheduler wiring failed; "
            "[FOLLOW_UP] markers will be silently stripped",
            exc_info=True,
        )
        runtime.conversation_pacing_scheduler = None

    # AD-637d: System Events subscription wiring (stream ensured in startup/nats.py)
    # Placed after ALL add_event_listener() calls (game completion, Counselor, etc.)
    # so _setup_nats_event_subscriptions() catches every registered listener.
    if getattr(runtime, 'nats_bus', None) and runtime.nats_bus.connected:
        runtime._setup_nats_event_subscriptions()
        logger.info("AD-637d: SYSTEM_EVENTS %d listeners wired to NATS",
                    len(runtime._event_listeners))

    # AD-697: discover and run any installed overlay extensions.
    # Pure OSS plumbing — no-op when no overlay is installed. Failures
    # degrade silently so a broken overlay can never block the OSS
    # runtime from finishing finalize.
    try:
        from probos.extensions.overlay import discover_extensions, run_finalize_hooks
        discover_extensions()
        await run_finalize_hooks(runtime, config)
    except Exception:
        logger.warning(
            "AD-697: extension finalize phase failed; continuing OSS-only",
            exc_info=True,
        )

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
