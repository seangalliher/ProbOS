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


def _memory_field(runtime: Any, name: str, default: float) -> float:
    """BF-291: defensively read a MemoryConfig field with a fallback.

    Direct attribute access raises ``AttributeError`` on Pydantic v2 models
    when the field is absent — which happens transitionally when a process
    started before a new field was added is shutting down with newer
    ``shutdown.py`` code on disk. The ``getattr``-with-default form skips
    Pydantic's strict ``__getattr__`` path entirely.
    """
    cfg = getattr(getattr(runtime, "config", None), "memory", None)
    if cfg is None:
        return default
    return float(getattr(cfg, name, default))


async def shutdown(runtime: ProbOSRuntime, reason: str = "") -> None:
    """Graceful shutdown of all pools, mesh services, and persistence."""
    # BF-598: idempotency guard. A second shutdown() invocation (a duplicate
    # SIGTERM during Windows sleep/wake, or a retried stop()) must NOT re-run
    # teardown. The first invocation already consolidated and wrote the AD-820
    # integrity marker; re-running finds the cognitive subsystems torn down,
    # skips consolidation, and would DOWNGRADE the clean marker to partial —
    # the root cause of the recurring boot refusal. Use getattr-with-default so
    # a process that started before this field existed still degrades safely.
    if getattr(runtime, "_shutdown_started", False):
        logger.info(
            "BF-598: shutdown() re-entered (reason=%r); first invocation already "
            "ran — skipping teardown and preserving the AD-820 marker.",
            reason,
        )
        return
    runtime._shutdown_started = True

    # BF-135: Persist session record FIRST — synchronous file write, microseconds.
    # Must happen before any async operations (Ward Room, event log) because
    # __main__.py enforces a 5s timeout on stop(). If Ward Room create_thread()
    # or event log writes are slow, the timeout cancels stop() and the session
    # record is never written — causing stale stasis duration on next boot.
    # BF-137: Write session record even on partial boots (before _started guard)
    # so that failed startups don't leave a stale timestamp that inflates
    # stasis duration on the next successful boot.
    # BF-065: Write to runtime._data_dir directly (not knowledge_store).
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

    if not runtime._started:
        return

    logger.info("ProbOS shutting down...")

    try:
        await runtime.event_log.log(category="system", event="stopping")
    except (asyncio.CancelledError, Exception):
        pass  # event log may be unavailable during shutdown

    # AD-435 + AD-502: Announce shutdown to Ward Room (stasis protocol)
    if runtime.ward_room and runtime.ward_room.is_started:
        try:
            all_hands = await runtime.ward_room.get_channel_by_name("All Hands")
            if all_hands:
                    msg = (
                        "Attention all hands: The ship is entering stasis. "
                        "All cognitive processes will be suspended. "
                        "Your memories and identity will be preserved. "
                        "When the system resumes, you will be informed of the stasis duration."
                    )
                    if reason:
                        msg += f" Reason: {reason}"
                    await runtime.ward_room.create_thread(
                        channel_id=all_hands.id,
                        author_id="system",
                        author_callsign="Ship's Computer",
                        title="Entering Stasis",
                        body=msg,
                        thread_mode="announce",
                        max_responders=0,
                    )
        except Exception:
            pass  # Shutdown cleanup — don't block shutdown

    # AD-435: Grace period for in-flight DB writes to complete
    logger.info("Shutdown grace period (1s)...")
    await asyncio.sleep(1)

    # Cancel periodic flush — BF-099: await cancellation before trust writes
    if hasattr(runtime, '_flush_task'):
        runtime._flush_task.cancel()
        try:
            await runtime._flush_task
        except (asyncio.CancelledError, Exception):
            pass

    # ── Phase 1: Critical Persistence ──────────────────────────────────
    # Dream consolidation + episodic memory close MUST complete before the
    # __main__.py timeout expires. Moved ahead of service stops (BF-207).
    # AD-820: consolidation timeout is now configurable (default 30s, was a
    # hardcoded 2s that tore ChromaDB's HNSW index when the dream cycle had
    # real work — see #750). The status of this phase is written to
    # shutdown_status.json at the end so the next boot can refuse to start
    # if consolidation didn't complete.
    import time as _time
    _phase1_start = _time.monotonic()
    # AD-820: track whether consolidation completed fully so we can stamp
    # the right integrity marker before exit.
    _consolidation_result: str = "skipped"

    _shutdown_consolidation_timeout = _memory_field(
        runtime, "shutdown_consolidation_timeout_s", 30.0,
    )

    # BF-296 Phase A: close the IntentBus to new dispatches BEFORE the
    # DreamScheduler quiesce + explicit dream_cycle below. Without this,
    # cognitive agent action loops continue to receive proactive_think /
    # ward_room_notification intents during consolidation. Their writes
    # to ChromaDB / Ward Room / Notebook stores compete with dream_cycle's
    # consolidation writes → torn HNSW → AD-820 ``consolidation_result=failed``
    # (see #771, 2026-05-23 10:39 UTC partial-shutdown reproduction).
    #
    # Honest-degrade: if the bus or method is absent (transitional running
    # processes started before BF-296 shipped), we log and proceed — the
    # AD-825 quiesce + AD-824 cancel sweep below remain the fallback.
    try:
        intent_bus = getattr(runtime, "intent_bus", None)
        if intent_bus is not None and hasattr(intent_bus, "close_to_new_dispatches"):
            intent_bus.close_to_new_dispatches()
            # Brief grace so already-fanned-out broadcast() handlers and
            # in-flight cognitive queue items finish their writes before
            # consolidation starts.
            await asyncio.sleep(2.0)
            logger.info(
                "BF-296 Phase A: intent dispatch closed; "
                "2s grace for in-flight handlers complete"
            )
    except Exception:
        logger.warning(
            "BF-296 Phase A: failed to close intent bus; "
            "proceeding to consolidation (concurrent-write hazard)",
            exc_info=True,
        )

    # BF-602: Quiesce Ward Room routing alongside the intent-dispatch close.
    # The explicit dream_cycle below makes agents post to the Ward Room during
    # consolidation; each post schedules a coalesce timer (AD-616) that fires
    # ~200ms later. If the ward_room DB connection is torn down before the timer
    # fires, route_event() crashes inside aiosqlite ("no active connection") as
    # an unretrieved fire-and-forget task exception. stop() sets the suppression
    # flag and cancels all pending coalesce timers + in-flight _fire() tasks.
    # Honest-degrade: absent on transitional procs started before BF-602.
    try:
        _wrr = getattr(runtime, "ward_room_router", None)
        if _wrr is not None and hasattr(_wrr, "stop"):
            _wrr.stop()
            logger.info("BF-602: Ward Room routing quiesced for shutdown")
    except Exception:
        logger.warning(
            "BF-602: failed to quiesce Ward Room routing; "
            "proceeding (coalesce-timer race hazard)",
            exc_info=True,
        )

    # AD-825: quiesce the DreamScheduler monitor loop BEFORE the
    # explicit dream_cycle below. Without this, the monitor loop can
    # run its own dream_cycle concurrently with the explicit one, and
    # the two writers collide on the same Chroma collection — torn
    # HNSW index → AD-820 ``consolidation_result=failed``. We give it
    # the configured drain budget; if it doesn't exit cleanly we log
    # and proceed (the AD-824 cancel sweep will reap it later).
    if runtime.dream_scheduler:
        try:
            _drain_budget = _memory_field(
                runtime, "shutdown_drain_timeout_s", 30.0,
            )
            _ok = await runtime.dream_scheduler.stop_gracefully(
                timeout=_drain_budget,
            )
            if _ok:
                logger.info(
                    "AD-825: DreamScheduler quiesced within %.1fs", _drain_budget,
                )
            else:
                logger.warning(
                    "AD-825: DreamScheduler did not quiesce within %.1fs; "
                    "proceeding to explicit consolidation (concurrent-write hazard)",
                    _drain_budget,
                )
        except Exception:
            logger.warning(
                "AD-825: DreamScheduler.stop_gracefully raised; "
                "proceeding to explicit consolidation",
                exc_info=True,
            )

    # Tier 3: Shutdown consolidation — flush remaining episodes (AD-288)
    # Must run BEFORE pools stop (consolidation may trigger Ward Room
    # notifications) and BEFORE the LLM client is closed.
    # AD-959: call the LEAN ``consolidate_for_shutdown`` path, NOT the full
    # ``dream_cycle``. The full cycle's per-cluster LLM calls (procedure
    # extraction, spaced-retrieval therapy, …) routinely overran the 30s
    # budget at real episode volume, leaving an AD-820 ``partial`` marker
    # that refuses the next boot (and historically tore the HNSW index,
    # #750). The lean path runs only the cheap in-memory learning-weight
    # updates (micro-dream Hebbian replay + prune + trust) and makes no
    # episodic-collection writes, so it finishes well under budget; the
    # deferred idle-time steps re-run on the next dream cycle.
    if runtime.dream_scheduler and runtime.episodic_memory:
        logger.info(
            "Consolidating session memories (lean, budget=%.0fs)...",
            _shutdown_consolidation_timeout,
        )
        try:
            # BF-303: shutdown() is typically awaited from a task that's
            # already in cancelled state (operator Ctrl+C cancels the outer
            # server task; the `finally:` block then awaits us). Every await
            # in a cancelled task re-raises CancelledError, which kills the
            # consolidation's in-flight writes. Spawn it in a FRESH task and
            # shield the await so it runs to completion independent of the
            # outer cancel state. The wait_for still bounds total time via
            # the configured budget (now a safety net the lean path won't hit).
            _dream_task = asyncio.create_task(
                runtime.dream_scheduler.engine.consolidate_for_shutdown(),
                name="shutdown-dream-cycle",
            )
            try:
                report = await asyncio.wait_for(
                    asyncio.shield(_dream_task),
                    timeout=_shutdown_consolidation_timeout,
                )
            except asyncio.CancelledError:
                # Outer task cancelled us; let consolidation finish (shield
                # gave us this chance). Wait for it to complete, but bound
                # by the same budget so a stuck consolidation doesn't hang
                # shutdown indefinitely.
                logger.info(
                    "BF-303: shutdown task cancelled mid-consolidation; "
                    "awaiting consolidation completion under the same %.0fs budget",
                    _shutdown_consolidation_timeout,
                )
                try:
                    report = await asyncio.wait_for(
                        _dream_task, timeout=_shutdown_consolidation_timeout,
                    )
                except asyncio.TimeoutError:
                    _dream_task.cancel()
                    raise
            logger.info(
                "Session consolidation complete: replayed=%d strengthened=%d pruned=%d",
                report.episodes_replayed,
                report.weights_strengthened,
                report.weights_pruned,
            )
            _consolidation_result = "full"
        except asyncio.TimeoutError:
            logger.warning(
                "Shutdown consolidation timed out (%.0fs limit) — "
                "partial consolidation completed",
                _shutdown_consolidation_timeout,
            )
            _consolidation_result = "partial"
        except (asyncio.CancelledError, Exception) as e:
            # BF-302: include exc_info so we can see WHAT inside consolidation
            # actually fails. Previously this swallowed the traceback and
            # only logged the exception's str(), which is empty for many
            # exception types (KeyError, AssertionError without msg, etc.).
            logger.warning(
                "Shutdown consolidation failed: %s",
                e or type(e).__name__,
                exc_info=True,
            )
            _consolidation_result = "failed"

    else:
        # AD-828a: the consolidation gate skipped. Log WHICH component was
        # absent so the next recurrence is diagnosable instead of silent.
        _ds_present = runtime.dream_scheduler is not None
        _em_present = getattr(runtime, "episodic_memory", None) is not None
        # AD-828b: distinguish "killed before the cognitive layer was wired"
        # (startup_incomplete — recoverable, the shutdown handler below still
        # closes episodic memory cleanly and AD-822b's HNSW probe is the boot
        # backstop) from a deliberately disabled subsystem (leave "skipped").
        _startup_done = getattr(runtime, "_startup_complete", True)
        if not _startup_done:
            _consolidation_result = "startup_incomplete"
            logger.warning(
                "AD-828: consolidation skipped because startup never completed "
                "(dream_scheduler=%s episodic_memory=%s, _startup_complete=False). "
                "Classifying as startup_incomplete — boot will be permitted; the "
                "AD-822b HNSW structural probe remains the integrity backstop.",
                _ds_present, _em_present,
            )
        else:
            logger.warning(
                "AD-828: consolidation skipped with startup complete "
                "(dream_scheduler=%s episodic_memory=%s). Leaving "
                "consolidation_result=%r — subsystem appears disabled or "
                "torn down early.",
                _ds_present, _em_present, _consolidation_result,
            )

    # BF-207: Close episodic memory (ChromaDB) immediately after dream
    # consolidation — this is the critical operation that caused hash mismatches
    # when it was positioned after ~25 service stops.
    if runtime.episodic_memory:
        await runtime.episodic_memory.stop()

    # AD-455: stop red team campaign loop
    if hasattr(runtime, "red_team_lead") and runtime.red_team_lead is not None:
        await runtime.red_team_lead.stop()

    # AD-541f: Stop eviction audit log (companion to episodic memory)
    _eviction_audit = getattr(runtime, "_eviction_audit", None)
    if _eviction_audit is not None:
        await _eviction_audit.stop()
        runtime._eviction_audit = None

    _phase1_elapsed = _time.monotonic() - _phase1_start
    logger.info("BF-207: Phase 1 (Critical Persistence) completed in %.1fs", _phase1_elapsed)

    # AD-825: drain phase — let write-holding background loops finish
    # their current operation (Chroma add/upsert, SQLite checkpoint,
    # tar snapshot) before the AD-824 cancel sweep below force-cancels
    # them. Tasks that don't drain within the budget fall through to
    # cancel — drain is best-effort, cancel is the fallback. The drain
    # phase must NEVER raise out of shutdown(); on error we log and
    # proceed so the AD-820 marker still gets written.
    drain_tasks = getattr(runtime, "_drain_tasks", None)
    if drain_tasks:
        try:
            runtime._signal_drain_stop()
            pending_snapshot = list(drain_tasks)
            if pending_snapshot:
                _drain_budget = _memory_field(
                    runtime, "shutdown_drain_timeout_s", 30.0,
                )
                logger.info(
                    "AD-825: draining %d write-holding task(s) (budget=%.1fs)",
                    len(pending_snapshot), _drain_budget,
                )
                _, _pending = await asyncio.wait(
                    pending_snapshot, timeout=_drain_budget,
                )
                for _task in _pending:
                    logger.warning(
                        "AD-825: drain task %s did not exit within %.1fs; "
                        "falling through to AD-824 cancel sweep",
                        _task.get_name(), _drain_budget,
                    )
        except Exception:
            # Drain must never block the AD-820 marker — log and proceed
            # to the cancel sweep.
            logger.warning(
                "AD-825: drain phase raised; proceeding to cancel sweep",
                exc_info=True,
            )

    # AD-824: cancel registered long-lived background loops so the
    # AD-820 marker write below is never blocked by a stuck task. We
    # snapshot the set into a list because the done-callback mutates it.
    # AD-825: this also catches any drain-tagged tasks that didn't exit
    # cleanly within the drain budget — drain was best-effort, this is
    # the fallback. We sweep _drain_tasks here too for that reason.
    background_tasks = getattr(runtime, "_background_tasks", None)
    drain_tasks_remaining = getattr(runtime, "_drain_tasks", None)
    pending_snapshot: list[asyncio.Task] = []
    if background_tasks:
        pending_snapshot.extend(background_tasks)
    if drain_tasks_remaining:
        pending_snapshot.extend(drain_tasks_remaining)
    if pending_snapshot:
        for _task in pending_snapshot:
            _task.cancel()
        try:
            _, _pending = await asyncio.wait(pending_snapshot, timeout=5.0)
            for _task in _pending:
                logger.warning(
                    "AD-824: background task %s did not exit within 5s; abandoning",
                    _task.get_name(),
                )
        except Exception:
            # Sweep must never block the AD-820 marker — log and move on.
            logger.warning("AD-824: background-task sweep raised", exc_info=True)

    # AD-820: write shutdown integrity marker so the next boot can detect a
    # clean vs. partial shutdown BEFORE opening ChromaDB. If consolidation
    # was 'full', the marker is 'clean'; otherwise 'partial' and the next
    # boot refuses to start unless --force-unclean is passed.
    try:
        from probos.shutdown_integrity import (
            mark_clean_shutdown,
            mark_dirty_shutdown,
            read_shutdown_status,
        )
        _data_dir = getattr(runtime, "_data_dir", None)
        if _data_dir is not None:
            if _consolidation_result == "full":
                mark_clean_shutdown(
                    _data_dir,
                    consolidation_result="full",
                    note="phase1_ok",
                )
            elif _consolidation_result == "skipped":
                # BF-598: a SKIP means the cognitive subsystems were absent, so
                # nothing was written to the HNSW index — this event cannot
                # corrupt it. Never let a skip DOWNGRADE an existing
                # clean/rebuilt marker (that is the recurring boot-refusal bug).
                # If no clean marker exists, fall through to the dirty write so a
                # genuinely-disabled-episodic first boot still surfaces honestly.
                _existing = read_shutdown_status(_data_dir)
                if _existing.get("status") == "clean" or _existing.get(
                    "consolidation_result"
                ) in ("full", "rebuilt"):
                    logger.info(
                        "BF-598: consolidation skipped but a clean marker already "
                        "exists (consolidation=%s); preserving it — a skip cannot "
                        "tear the index.",
                        _existing.get("consolidation_result"),
                    )
                else:
                    mark_dirty_shutdown(
                        _data_dir,
                        consolidation_result="skipped",
                        note=f"phase1_elapsed={_phase1_elapsed:.1f}s",
                    )
            else:
                # partial / failed / startup_incomplete → unchanged behaviour
                mark_dirty_shutdown(
                    _data_dir,
                    consolidation_result=_consolidation_result,  # type: ignore[arg-type]
                    note=f"phase1_elapsed={_phase1_elapsed:.1f}s",
                )
    except Exception:
        logger.warning(
            "AD-820: failed to record shutdown integrity marker (continuing)",
            exc_info=True,
        )

    # ── Phase 2: Service Cleanup ───────────────────────────────────────

    # Stop ACM (AD-427)
    if runtime.acm:
        await runtime.acm.stop()
        runtime.acm = None

    # Stop Visiting Officer registry (AD-701)
    vo_registry = getattr(runtime, "visiting_officers", None)
    if vo_registry is not None:
        await vo_registry.stop()
        runtime.visiting_officers = None

    # Stop Workflow Cron scheduler (AD-707)
    wfc = getattr(runtime, "workflow_cron", None)
    if wfc is not None:
        await wfc.stop()
        runtime.workflow_cron = None

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

    # AD-654b: Shutdown cognitive queues (before proactive loop stops)
    if hasattr(runtime, 'intent_bus') and runtime.intent_bus:
        for agent_id, queue in list(runtime.intent_bus._agent_queues.items()):
            await queue.shutdown()
        logger.info("Shutdown: cognitive queues stopped")

    # AD-743: Stop ConversationPacingScheduler (cancels any pending follow-ups)
    _pacing = getattr(runtime, "conversation_pacing_scheduler", None)
    if _pacing is not None:
        try:
            await _pacing.stop()
        except Exception:
            logger.warning(
                "AD-743: ConversationPacingScheduler stop failed", exc_info=True
            )
        runtime.conversation_pacing_scheduler = None

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

    # AD-733c-2: stop the perception mode controller's idle watchdog.
    if (
        hasattr(runtime, 'perception_mode_controller')
        and runtime.perception_mode_controller is not None
    ):
        try:
            await runtime.perception_mode_controller.stop()
        except Exception:
            logger.warning("AD-733c-2: mode_controller.stop() failed", exc_info=True)
        runtime.perception_mode_controller = None

    # AD-733c-5: stop per-agent engagement controllers.
    _engagement = getattr(runtime, 'perception_engagement_registry', None)
    if _engagement is not None:
        for _aid, _ctrl in _engagement.all_controllers().items():
            try:
                await _ctrl.stop()
            except Exception:
                logger.warning(
                    "AD-733c-5: per-agent controller stop failed agent=%s",
                    _aid, exc_info=True,
                )
        runtime.perception_engagement_registry = None

    # AD-706b: Stop browser recording reaper (background retention sweeper)
    if hasattr(runtime, 'recording_reaper') and runtime.recording_reaper is not None:
        try:
            await runtime.recording_reaper.stop()
        except Exception:
            logger.warning("AD-706b: recording_reaper.stop() failed", exc_info=True)
        runtime.recording_reaper = None

    # AD-733-1: Stop attachment retention reaper.
    if hasattr(runtime, 'attachment_reaper') and runtime.attachment_reaper is not None:
        try:
            await runtime.attachment_reaper.stop()
        except Exception:
            logger.warning("AD-733-1: attachment_reaper.stop() failed", exc_info=True)

    # AD-986d: Stop transcript retention reaper.
    if hasattr(runtime, 'transcript_reaper') and runtime.transcript_reaper is not None:
        try:
            await runtime.transcript_reaper.stop()
        except Exception:
            logger.warning("AD-986d: transcript_reaper.stop() failed", exc_info=True)
        runtime.transcript_reaper = None

    # AD-876: Stop the board-reconciler cadence ticker (Quartermaster).
    if getattr(runtime, "board_reconciler_ticker", None) is not None:
        try:
            await runtime.board_reconciler_ticker.stop()
        except Exception:
            logger.warning(
                "AD-876: board_reconciler_ticker.stop() failed", exc_info=True
            )
        runtime.board_reconciler_ticker = None

    # AD-818 (#751): Stop schema-version sidecar (R2). Unlike ParticipantIndex
    # (owned by EpisodicMemory.stop()), this store has no owner — left unstopped
    # its aiosqlite WAL connection holds schema_versions.db-wal/-shm locks, a
    # real test-isolation hazard on Windows.
    if getattr(runtime, "schema_version_store", None) is not None:
        try:
            await runtime.schema_version_store.stop()
        except Exception:
            logger.warning("AD-818: schema_version_store.stop() failed", exc_info=True)

    # AD-751: Stop desktop UX surface (tray, hotkey, autostart, notifications)
    if hasattr(runtime, 'hotkey_listener') and runtime.hotkey_listener is not None:
        try:
            await runtime.hotkey_listener.stop_listening()
        except Exception:
            logger.warning("AD-751: hotkey_listener.stop_listening() failed", exc_info=True)
        runtime.hotkey_listener = None
    
    if hasattr(runtime, 'desktop_lifecycle') and runtime.desktop_lifecycle is not None:
        try:
            await runtime.desktop_lifecycle.release_lock()
        except Exception:
            logger.warning("AD-751: desktop_lifecycle.release_lock() failed", exc_info=True)
        runtime.desktop_lifecycle = None
        runtime.attachment_reaper = None

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

    # AD-596b: Disconnect cognitive skill catalog from standing orders
    from probos.cognitive.standing_orders import set_skill_catalog
    set_skill_catalog(None)

    # AD-596c: Clear skill bridge reference (stateless, no teardown needed)
    runtime.skill_bridge = None

    # Stop Ward Room (AD-407)
    if runtime.ward_room:
        await runtime.ward_room.stop_prune_loop()
        await runtime.ward_room.stop()
        runtime.ward_room = None

    # Stop Cognitive Journal (AD-431)
    if runtime.cognitive_journal:
        await runtime.cognitive_journal.stop()
        runtime.cognitive_journal = None

    # AD-622: Clearance grant store
    if hasattr(runtime, 'clearance_grant_store') and runtime.clearance_grant_store:
        await runtime.clearance_grant_store.stop()
        runtime.clearance_grant_store = None

    # AD-423b: Tool permission store
    if hasattr(runtime, 'tool_permission_store') and runtime.tool_permission_store:
        await runtime.tool_permission_store.stop()
        runtime.tool_permission_store = None

    # AD-983b: Skill grant store (per-agent cognitive-skill grants)
    if getattr(runtime, 'skill_grant_store', None):
        await runtime.skill_grant_store.stop()
        runtime.skill_grant_store = None

    # Stop Counselor Profile Store (AD-503)
    if runtime._counselor_profile_store:
        await runtime._counselor_profile_store.stop()
        runtime._counselor_profile_store = None

    # Stop Procedure Store (AD-533)
    if runtime._procedure_store:
        await runtime._procedure_store.stop()
        runtime._procedure_store = None

    # Stop Drift Scheduler (AD-566c) — before qualification store
    drift_sched = getattr(runtime, "_drift_scheduler", None)
    if drift_sched is not None:
        await drift_sched.stop()
        runtime._drift_scheduler = None

    # Stop Qualification Store (AD-566a)
    qual_store = getattr(runtime, "_qualification_store", None)
    if qual_store is not None:
        await qual_store.stop()
        runtime._qualification_store = None
        runtime._qualification_harness = None

    # Stop Retrieval Practice Engine (AD-541c)
    if hasattr(runtime, '_retrieval_practice_engine') and runtime._retrieval_practice_engine:
        await runtime._retrieval_practice_engine.stop()
        runtime._retrieval_practice_engine = None

    # Stop Activation Tracker (AD-567d)
    _activation_tracker = getattr(runtime, "_activation_tracker", None)
    if _activation_tracker is not None:
        await _activation_tracker.stop()
        runtime._activation_tracker = None

    # Stop Cognitive Skill Catalog (AD-596a)
    if runtime.cognitive_skill_catalog:
        await runtime.cognitive_skill_catalog.stop()
        runtime.cognitive_skill_catalog = None

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
    for agent in runtime.red_team_agents:
        await agent.stop()
        await runtime.registry.unregister(agent.id)
    runtime.red_team_agents.clear()

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

    # AD-573: Freeze all agent working memory before pools stop
    if hasattr(runtime, 'working_memory_store') and runtime.working_memory_store:
        try:
            from probos.crew_utils import is_crew_agent  # BF-127
            states: dict = {}
            for agent in runtime.registry.all():
                # BF-127: Only persist working memory for sovereign crew agents
                if not is_crew_agent(agent, getattr(runtime, 'ontology', None)):
                    continue
                wm = getattr(agent, 'working_memory', None)
                if wm:
                    states[agent.id] = wm.to_dict()
            if states:
                await runtime.working_memory_store.save_all(states)
                logger.info("AD-573: Froze working memory for %d agents", len(states))
        except Exception as e:
            logger.warning("AD-573: Working memory freeze failed: %s", e)

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

    # AD-637: Stop NATS event bus
    if getattr(runtime, 'nats_bus', None):
        try:
            await runtime.nats_bus.stop()
            runtime.nats_bus = None
            logger.info("NATS event bus stopped")
        except Exception as e:
            logger.warning("NATS shutdown error: %s", e)

    # AD-573: Stop working memory store
    if hasattr(runtime, 'working_memory_store') and runtime.working_memory_store:
        try:
            await runtime.working_memory_store.stop()
        except Exception:
            pass

    # AD-524: Close Ship's Archive store
    if getattr(runtime, "_archive_store", None):
        try:
            await runtime._archive_store.close()
            runtime._archive_store = None
        except Exception as e:
            logger.warning(
                "AD-524: ArchiveStore shutdown close failed; shutdown continues "
                "and the OS will reclaim the connection if needed: %s",
                e,
            )

    try:
        await runtime.event_log.log(category="system", event="stopped")
    except (asyncio.CancelledError, Exception):
        pass
    await runtime.event_log.stop()

    # Clean up LLM client — after consolidation so dream_cycle can make LLM calls
    await runtime.llm_client.close()

    # Stop dreaming scheduler
    if runtime.dream_scheduler:
        await runtime.dream_scheduler.stop()
        runtime.dream_scheduler = None

    # Stop task scheduler (AD-282)
    if runtime.task_scheduler:
        await runtime.task_scheduler.stop()
        runtime.task_scheduler = None

    # Stop semantic knowledge layer (AD-243)
    if runtime._semantic_layer:
        await runtime._semantic_layer.stop()
        runtime._semantic_layer = None

    runtime._started = False
    logger.info("ProbOS shutdown complete. Final agent count: %d", runtime.registry.count)
