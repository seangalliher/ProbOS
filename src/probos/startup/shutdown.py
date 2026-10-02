"""Graceful shutdown sequence (AD-518).

Extracted from ProbOSRuntime.stop() — handles ordered teardown of all
services, persistence of knowledge artifacts, and session record writing.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import math
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from probos.crew_utils import is_crew_agent
from probos.execution.long_runs import LONG_RUN_SETTLE_SECONDS, LongRunService

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)

# AD-1270f (P1.2): the two fixed shutdown waits. They are also the maximums of
# MemoryConfig.shutdown_write_grace_s / shutdown_dispatch_grace_s, so an
# unreadable or out-of-range config always falls back to today's timing.
# AD-435 runs after crew scheduling, confab probes and long runs have closed,
# and before the periodic flush and the remaining write-holding services are
# quiesced.
SHUTDOWN_WRITE_GRACE_S: float = 1.0  # AD-435
SHUTDOWN_DISPATCH_GRACE_S: float = 2.0  # BF-296 Phase A: after the bus closes


async def _close_crew_session_delivery(runtime: Any) -> None:
    listener = getattr(runtime, "crew_session_delivery_listener", None)
    remove_listener = getattr(runtime, "remove_event_listener", None)
    if callable(listener) and callable(remove_listener):
        try:
            remove_listener(listener)
        except Exception:
            logger.warning(
                "AD-1131: CrewSession delivery listener removal failed; the "
                "service admission gate will still close before workforce "
                "storage shutdown",
                exc_info=True,
            )
    runtime.crew_session_delivery_listener = None

    service = getattr(runtime, "crew_session_delivery_service", None)
    close = getattr(service, "close", None) if service is not None else None
    try:
        if callable(close):
            await close()
    finally:
        runtime.crew_session_delivery_service = None


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


def _grace_seconds(runtime: Any, name: str, default: float) -> float:
    """AD-1270f: strictly read a shutdown grace, in seconds, from MemoryConfig.

    Deliberately not ``_memory_field``: its ``float()`` conversion turns a mock
    config's 2.0 s grace into 1.0 s (``float(MagicMock()) == 1.0``). Only a
    plain, finite ``int`` or ``float`` inside ``[0, default]`` is honoured. A
    missing or unreadable config, a ``bool``, ``nan``, ``inf``, a negative and a
    value above ``default`` all return ``default``, so today's wait is the only
    fallback and a config can shorten it but never extend it. Never raises.

    ``MemoryConfig`` already rejects a non-number when it is validated; this
    read-site check is the second layer, for a mock, a value assigned after
    validation and a process that started before the fields existed.
    """
    try:
        cfg = getattr(getattr(runtime, "config", None), "memory", None)
        value = getattr(cfg, name, default)
    except Exception:
        logger.debug(
            "AD-1270f: memory.%s could not be read; using the %gs default",
            name, default, exc_info=True,
        )
        return default
    if type(value) in (int, float) and 0.0 <= value <= default and math.isfinite(value):
        return float(value)
    logger.debug(
        "AD-1270f: memory.%s (%s) is not a finite number in [0, %g]; using the "
        "%gs default",
        name, type(value).__name__, default, default,
    )
    return default


def _security_field(runtime: Any, name: str, default: float) -> float:
    """AD-1278: the ``_memory_field`` shape for ``SecurityInfraConfig``.

    Same reason as BF-291: a process that started before a field existed is
    shutting down against newer ``shutdown.py`` code on disk, and direct
    attribute access on a Pydantic v2 model raises for the absent field.
    """
    cfg = getattr(getattr(runtime, "config", None), "security_infra", None)
    if cfg is None:
        return default
    return float(getattr(cfg, name, default))


async def _flush_audit_log(runtime: Any) -> None:
    """AD-1278 (BF-780) phase 1: get the bulk of the trail onto disk, EARLY.

    Registration deliberately stays open. ``AuditLog.drain`` closes it, and
    everything that runs after this point -- the pool scaler, the pools and
    intent bus, the knowledge store, the mesh services, the semantic layer --
    can still produce an audit-worthy event. Closing registration here would
    make the most failure-prone stretch of the run the one stretch with no
    durable record, which is where a durability control is least allowed to be
    absent.

    Budget: HALF of ``security_infra.audit_drain_timeout_s``, because phase 2
    gets the full value afterwards and ``__main__.py`` gives the whole teardown
    ten seconds. On expiry ``flush`` logs and returns; phase 2 tries again.
    """
    audit_log = getattr(runtime, "audit_log", None)
    if audit_log is None or not callable(getattr(audit_log, "flush", None)):
        return
    try:
        await audit_log.flush(
            timeout_seconds=_security_field(
                runtime, "audit_drain_timeout_s", 2.0,
            ) / 2.0,
        )
    except Exception:
        logger.warning(
            "AD-1278: the early audit flush failed; the shutdown drain still "
            "gets a full attempt at the same entries.",
            exc_info=True,
        )


async def _drain_audit_log(runtime: Any) -> None:
    """AD-1278 (BF-780) phase 2: flush the audit chain, then close its SQLite handle.

    BF-763 removed the quorum gate on ``run_python`` in exchange for a
    per-execution audit record. Until now nothing drained the writer, so the
    tail of that record died with the process -- the trail was best-effort in
    exactly the moment it was most likely to matter.

    Placed after ``_semantic_layer.stop()`` and before ``runtime._started =
    False``, which is the last point at which anything can append; this is the
    call that closes registration, so nothing that could still append may run
    after it.

    Bounded by ``security_infra.audit_drain_timeout_s`` and log-and-degrade
    throughout: ``__main__.py`` gives the whole teardown ten seconds, and a
    drain that hangs shutdown is a worse defect than the tail it saves.
    ``CancelledError`` is deliberately not caught -- it belongs to the shutdown.
    """
    audit_log = getattr(runtime, "audit_log", None)
    if audit_log is not None and callable(getattr(audit_log, "drain", None)):
        try:
            await audit_log.drain(
                timeout_seconds=_security_field(
                    runtime, "audit_drain_timeout_s", 2.0,
                ),
            )
        except Exception:
            logger.warning(
                "AD-1278: the audit drain failed; entries that had not reached "
                "SQLite are lost at exit. The persistence handle is still "
                "closed below.",
                exc_info=True,
            )
    persistence = getattr(runtime, "audit_log_persistence", None)
    if persistence is None:
        return
    try:
        await persistence.stop()
    except Exception:
        logger.warning(
            "AD-456d: AuditLogPersistence failed to close during shutdown; the "
            "SQLite handle is released at process exit",
            exc_info=True,
        )
    finally:
        runtime.audit_log_persistence = None


async def _cancel_confab_probe_tasks(runtime: Any) -> None:
    """BF-663: cancel and reap every one-shot probe before LLM shutdown.

    Probe tasks depend on ``runtime.llm_client`` and therefore must not be
    folded into the earlier bounded background-task sweep, which can abandon
    tasks after five seconds. Cancellation is unbounded here by design: the
    client remains open until every probe has run its ``finally`` cleanup.
    The production caller closes probe admission synchronously at shutdown
    entry; this helper retains missing-registry tolerance for partial runtimes.
    """
    registry = getattr(runtime, "confab_probe_tasks", None)
    if not registry:
        return

    tasks = tuple(registry)
    cancelled = 0
    for task in tasks:
        if not task.done() and task.cancelling() == 0:
            task.cancel()
            cancelled += 1
    logger.info(
        "BF-663: cancelling and awaiting %d confab probe task(s) before LLM "
        "client shutdown (unfinished=%d)",
        len(tasks), cancelled,
    )

    async def _drain_snapshot() -> list[Any]:
        return await asyncio.gather(*tasks, return_exceptions=True)

    drain_task = asyncio.create_task(
        _drain_snapshot(),
        name="bf663-confab-probe-shutdown-drain",
    )
    try:
        try:
            results = await asyncio.shield(drain_task)
        except asyncio.CancelledError:
            # Preserve the original snapshot drain across outer shutdown
            # cancellation. Re-await the SAME shielded drain without issuing a
            # second cancel to probes already running awaited finally cleanup,
            # then propagate the outer cancellation only after they finish.
            while True:
                try:
                    await asyncio.shield(drain_task)
                    break
                except asyncio.CancelledError:
                    continue
            raise
    finally:
        for task in tasks:
            registry.discard(task)

    failures = [
        result
        for result in results
        if isinstance(result, BaseException)
        and not isinstance(result, asyncio.CancelledError)
    ]
    if failures:
        logger.warning(
            "BF-663: %d confab probe task(s) failed during shutdown cleanup; "
            "all probes are reaped and LLM shutdown will continue",
            len(failures),
        )
    logger.debug(
        "BF-663: reaped %d confab probe task(s) before LLM shutdown "
        "(cancelled=%d failures=%d)",
        len(tasks), cancelled, len(failures),
    )


async def _close_llm_client_after_confab_probes(runtime: Any) -> None:
    """Close the LLM only after the stable confab-probe registry is drained."""
    await _cancel_confab_probe_tasks(runtime)
    await runtime.llm_client.close()


async def _stop_runtime_sqlite_sidecars(runtime: Any) -> None:
    """Close runtime-owned SQLite services without another lifecycle owner."""
    services = (
        ("capability_request_store", "capability request store"),
        ("fault_report_store", "fault report store"),  # AD-1169
        ("approval_authority_store", "approval authority store"),  # AD-1213
        ("decision_pre_clearance_store", "decision pre-clearance store"),  # AD-1214
        ("standing_interest_store", "standing interest store"),  # AD-1228
        ("knowledge_edges", "knowledge edge store"),
        ("personal_ontology_prober", "personal ontology prober"),
        ("rejection_cache", "relationship rejection cache"),
    )
    for attribute, label in services:
        service = getattr(runtime, attribute, None)
        if service is None:
            continue
        try:
            await service.stop()
        except Exception:
            logger.warning(
                "BF-662: failed to close %s during runtime shutdown; "
                "remaining sidecars will still be closed",
                label,
                exc_info=True,
            )
        finally:
            setattr(runtime, attribute, None)


def _close_sync_store(store: Any, label: str) -> None:
    """BF-881 (#1452): close a SQLite store opened synchronously; log-and-degrade.

    ``ProfileStore`` (``ProbOSRuntime.__init__``), ``ServiceProfileStore`` and
    ``SemanticStore`` each had a ``close()`` that nothing called, so their handles
    stayed open (a held file on Windows) until a garbage collection. A failing close
    must not stop the rest of the teardown.
    """
    if store is None:
        return
    try:
        store.close()
    except Exception:
        logger.warning(
            "BF-881: %s failed to close during shutdown; its SQLite handle stays open "
            "until the store is collected. Shutdown continues.",
            label,
            exc_info=True,
        )


async def _stop_held_start_service(
    runtime: Any,
    *,
    service_attr: str,
    start_task_attr: str | None,
    label: str,
) -> None:
    """BF-881 (#1452): stop a service nothing stopped, and the task that started it.

    The AD-641a bridge and the AD-477 Captain's Log and Plan of the Day each have a
    ``stop()`` that no shutdown step called, and the AD-733c-5 repoint dropped the only
    reference to the AD-733c-2 ship-level perception controller, so five loops outlived
    ``stop()``. A pending start task is cancelled first, so a service that has not begun
    never does. ``stop()`` is awaited only when it is a coroutine function, which skips a
    ``MagicMock`` runtime double (BF-254).

    AD-477's ``stop()`` cancels its loop and awaits it, so the loop's own
    ``CancelledError`` propagates out of ``stop()`` by contract. That one is swallowed. A
    cancellation that arrives while this runs is not: the running task's cancel count is
    compared with its count at entry, because ``stop()`` is typically awaited from a task
    that was already cancelled (BF-303: the operator's Ctrl+C), whose count is above zero
    for the whole teardown. Any other failure is logged and shutdown continues. Both
    attributes are cleared either way.
    """
    service = getattr(runtime, service_attr, None)
    start_task = getattr(runtime, start_task_attr, None) if start_task_attr else None
    stop = getattr(service, "stop", None)
    start_pending = isinstance(start_task, asyncio.Task) and not start_task.done()
    stop_awaitable = inspect.iscoroutinefunction(stop)
    if not (start_pending or stop_awaitable):
        return

    current = asyncio.current_task()
    cancelling_at_entry = current.cancelling() if current is not None else 0

    def _outer_cancel_arrived() -> bool:
        return current is not None and current.cancelling() > cancelling_at_entry

    try:
        if start_pending:
            start_task.cancel()
            try:
                await start_task
            except asyncio.CancelledError:
                if _outer_cancel_arrived():
                    raise
            except Exception:
                logger.warning(
                    "BF-881: the %s start task failed while it was cancelled for "
                    "shutdown; stop() is still attempted",
                    label,
                    exc_info=True,
                )
        if stop_awaitable:
            try:
                await stop()
            except asyncio.CancelledError:
                if _outer_cancel_arrived():
                    raise
            except Exception:
                logger.warning(
                    "BF-881: %s.stop() failed during shutdown; its background loop may "
                    "run until the event loop closes. Shutdown continues.",
                    label,
                    exc_info=True,
                )
    finally:
        if service is not None:
            setattr(runtime, service_attr, None)
        if start_task is not None and start_task_attr:
            setattr(runtime, start_task_attr, None)


class _RollbackSteps:
    """BF-882 (#1419): ``shutdown()``'s steps, best-effort in a rollback, transparent otherwise.

    ``with steps("name"):`` around one teardown step does nothing at all when ``rollback``
    is False, so a normal stop is the function it was: a failing step propagates, with the
    same traceback and the same log lines. In a rollback a step that raises is logged,
    naming the step and the exception, and the rollback goes on to the next one. A rollback
    tears down a boot that failed halfway, so any component may be half built; one that
    cannot stop must not leave every later store, pool and agent running, because their
    non-daemon aiosqlite workers keep the interpreter from exiting and a Yeoman that never
    stops keeps the AD-766 slot.

    Cancellation follows the BF-881 rule. The cancel count of the running task is taken
    when the teardown begins. A ``CancelledError`` while that count is unchanged is not a
    request to stop this task (a component re-raising its own loop's cancellation, as
    AD-477's ``stop()`` does by contract), so it is logged like any other failure. One that
    arrives after the count has risen is the caller's cancellation and propagates.
    """

    def __init__(self, rollback: bool) -> None:
        self._rollback = rollback
        # Only a rollback reads the running task: a normal stop must not depend on it.
        self._task = asyncio.current_task() if rollback else None
        self._cancelling_at_entry = (
            self._task.cancelling() if self._task is not None else 0
        )

    def __call__(self, step: str) -> contextlib.AbstractContextManager[None]:
        if not self._rollback:
            return contextlib.nullcontext()
        return self._best_effort(step)

    def _outer_cancel_arrived(self) -> bool:
        return (
            self._task is not None
            and self._task.cancelling() > self._cancelling_at_entry
        )

    @contextlib.contextmanager
    def _best_effort(self, step: str) -> Iterator[None]:
        try:
            yield
        except asyncio.CancelledError:
            if self._outer_cancel_arrived():
                raise
            logger.warning(
                "BF-882: startup rollback step %r ended in a CancelledError nobody asked "
                "this task for; it may not have released everything. The rollback "
                "continues with the next step.",
                step,
                exc_info=True,
            )
        except Exception as error:
            logger.warning(
                "BF-882: startup rollback step %r raised %s: %s; it may not have "
                "released everything. The rollback continues with the next step.",
                step,
                type(error).__name__,
                error,
                exc_info=True,
            )


async def _quiesce_surviving_agents(runtime: Any, steps: _RollbackSteps) -> None:
    """BF-882 (#1419): stop every agent a failed pool stop left running. Rollback only.

    ``ResourcePool`` unwires an agent from the mesh before it stops it and keeps
    ownership when the unwire fails, so such an agent (the singleton YeomanAgent among
    them) survives ``_stop_pools_and_drain_intent_bus`` still running and still holding
    whatever it holds. A rollback has no later retry, so each is stopped here, and only
    then can its own ``stop()`` release what only it can (the Yeoman slot is freed after
    the agent has stopped, never before). The ownership policy is unchanged: nothing is
    unregistered and the pool is retained. A failing stop is logged and the next agent
    is still stopped.
    """
    for agent in list(runtime.registry.all()):
        if not getattr(agent, "is_alive", False):
            continue
        with steps(
            f"force-stop agent {getattr(agent, 'id', '?')} "
            f"({getattr(agent, 'agent_type', '?')})"
        ):
            await agent.stop()


async def _stop_pools_and_drain_intent_bus(
    runtime: Any,
) -> asyncio.CancelledError | None:
    """Stop every pool and always drain IntentBus before transport shutdown."""
    deferred_cancellation: asyncio.CancelledError | None = None
    for name, pool in list(runtime.pools.items()):
        try:
            await pool.stop()
        except asyncio.CancelledError as exc:
            deferred_cancellation = exc
            logger.warning(
                "Pool %r completed its cancellation-safe stop but shutdown "
                "cancellation is deferred until transport teardown completes",
                name,
            )
        except Exception:
            logger.exception(
                "Pool %r failed to stop; retaining runtime ownership while "
                "remaining pools and transport teardown continue",
                name,
            )
        else:
            runtime.pools.pop(name, None)

    intent_bus = getattr(runtime, "intent_bus", None)
    if intent_bus is not None and hasattr(intent_bus, "drain_pending_tasks"):
        try:
            await intent_bus.drain_pending_tasks(timeout_seconds=5.0)
        except asyncio.CancelledError as exc:
            deferred_cancellation = deferred_cancellation or exc
            logger.warning(
                "IntentBus cleanup drain was cancelled; deferring cancellation "
                "until transport teardown completes"
            )
        except Exception:
            logger.warning(
                "IntentBus cleanup drain failed before NATS shutdown; "
                "continuing transport teardown",
                exc_info=True,
            )
    return deferred_cancellation


async def shutdown(
    runtime: ProbOSRuntime, reason: str = "", *, rollback: bool = False,
) -> None:
    """Graceful shutdown of all pools, mesh services, and persistence.

    ``rollback=True`` (BF-882, #1419) is the teardown of a ``start()`` that failed or was
    cancelled (``startup/rollback.py``). It releases everything the partial boot started,
    in this same order, and persists nothing: no session consolidation, no AD-820
    integrity marker, no knowledge-store or working-memory write, no "Entering Stasis"
    post, no proactive-cooldown write and no Night Orders expiry, because none of those is
    a release and a boot that never completed has no session to record. The one record it
    does touch is ``session_last.json``: refreshed when it exists (BF-137, a failed start
    must not leave the previous session's timestamp to inflate the next stasis) and never
    created, because the next boot reads ANY record as a stasis recovery. Everything else
    runs: both waits, the BF-296 and BF-602 quiesce, the AD-824/825 sweeps, the AD-1278
    flush and drain, the event-log rows and the LLM close. Every step is best-effort
    (``_RollbackSteps``): one that raises is logged by name and the rollback goes on,
    because a half-built component may not be able to stop and must not leave every later
    store, pool and agent running. The BF-598 and ``_started`` guards are bypassed,
    because the runtime a rollback tears down is by definition one ``stop()`` would skip.
    ``rollback=False`` (the default) is the unchanged shutdown.
    """
    # BF-598: idempotency guard. A second shutdown() invocation (a duplicate
    # SIGTERM during Windows sleep/wake, or a retried stop()) must NOT re-run
    # teardown. The first invocation already consolidated and wrote the AD-820
    # integrity marker; re-running finds the cognitive subsystems torn down,
    # skips consolidation, and would DOWNGRADE the clean marker to partial —
    # the root cause of the recurring boot refusal. Use getattr-with-default so
    # a process that started before this field existed still degrades safely.
    if getattr(runtime, "_shutdown_started", False) and not rollback:
        logger.info(
            "BF-598: shutdown() re-entered (reason=%r); first invocation already "
            "ran — skipping teardown and preserving the AD-820 marker.",
            reason,
        )
        return
    runtime._shutdown_started = True
    deferred_shutdown_cancellation: asyncio.CancelledError | None = None
    steps = _RollbackSteps(rollback)
    if rollback:
        # A rollback is the teardown of a start that failed. Set here as well as by
        # rollback_failed_start so that a direct call is flagged too: two steps below must
        # keep their AST shape (tests/test_ad654d_internal_emitters.py executes them with
        # only ``runtime`` and ``logger``), so they read this instead of ``steps``.
        runtime._start_failed = True

    crew_orchestrator = getattr(runtime, "crew_orchestrator", None)
    crew_close = (
        getattr(crew_orchestrator, "close_scheduling", None)
        if crew_orchestrator is not None
        else None
    )
    crew_stop = (
        getattr(crew_orchestrator, "stop", None)
        if crew_orchestrator is not None
        else None
    )
    if callable(crew_close):
        with steps("crew scheduling close"):
            crew_close()

    # BF-663: close the public probe-scheduling gate synchronously at shutdown
    # entry, before the first await. This makes the later registry snapshot a
    # stable shutdown barrier instead of a point-in-time view that fan-out can
    # append to while teardown is in progress. The method also requests
    # cancellation immediately, preventing a registered-but-not-started probe
    # from beginning after shutdown starts.
    with steps("confab probe scheduling close"):
        runtime.close_confab_probe_scheduling()

    # AD-1246 / #1417: fire the kill switch of every run_python child the service
    # tracks, long and inline, before anything awaits, and refuse any new one. A
    # sandbox child survives its parent's os._exit, and nothing later tries to
    # stop it. The kill reaches what SubprocessSandbox._kill reaches; on Windows
    # a process the child started itself survives it.
    long_runs = getattr(runtime, "execution_long_runs", None)
    if isinstance(long_runs, LongRunService):
        with steps("run_python long-run close"):
            long_runs.close("shutdown")

    # BF-135: Persist session record FIRST — synchronous file write, microseconds.
    # Must happen before any async operations (Ward Room, event log) because
    # __main__.py enforces a 10s timeout on stop() (`__main__.py:653`, `:938`;
    # the 5s at `:928` bounds `adapter.stop()`, a different call). If Ward Room
    # create_thread() or event log writes are slow, the timeout cancels stop()
    # and the session record is never written — causing stale stasis duration on
    # next boot.
    # BF-137: Write session record even on partial boots (before _started guard)
    # so that failed startups don't leave a stale timestamp that inflates
    # stasis duration on the next successful boot.
    # BF-065: Write to runtime._data_dir directly (not knowledge_store).
    try:
        session_path = runtime._data_dir / "session_last.json"
        if rollback and not session_path.exists():
            # BF-882: a rollback refreshes a session record that exists (BF-137: a failed
            # start must not leave the previous session's timestamp to inflate the next
            # boot's stasis) but never creates one. cognitive_services reads ANY record
            # as a stasis recovery, so one written by a boot that never completed would
            # turn a maiden voyage into one.
            logger.info(
                "BF-882: startup rollback found no session record and does not create "
                "one; the next boot is still a first boot."
            )
        else:
            session_record = {
                "session_id": runtime._session_id,
                "start_time_utc": runtime._start_time_wall,
                "shutdown_time_utc": time.time(),
                "uptime_seconds": time.monotonic() - runtime._start_time,
                "agent_count": len([a for a in runtime.registry.all() if is_crew_agent(a, runtime.ontology)]),
                "reason": reason,
            }
            session_path.write_text(json.dumps(session_record, indent=2))
    except Exception as e:
        logger.debug("AD-502: Session record persistence failed: %s", e)

    if crew_stop is not None and asyncio.iscoroutinefunction(crew_stop):
        with steps("crew orchestrator stop"):
            await crew_stop()

    # AD-1246: bounded, and returns without suspending when no tracked run is in flight.
    if isinstance(long_runs, LongRunService):
        with steps("run_python long-run settle"):
            await long_runs.wait_settled(LONG_RUN_SETTLE_SECONDS)

    if not runtime._started and not rollback:
        return

    if rollback:
        logger.info(
            "BF-882: rolling back a failed start (reason=%r); stopping everything the "
            "partial boot started. Nothing is persisted and no shutdown marker is written.",
            reason,
        )
    else:
        logger.info("ProbOS shutting down...")

    try:
        await runtime.event_log.log(category="system", event="stopping")
    except (asyncio.CancelledError, Exception):
        pass  # event log may be unavailable during shutdown

    # AD-435 + AD-502: Announce shutdown to Ward Room (stasis protocol). Not in a
    # rollback (BF-882): a boot that never completed has no session to put into stasis.
    if not rollback and runtime.ward_room and runtime.ward_room.is_started:
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

    # AD-435: Grace period for in-flight DB writes to complete.
    # AD-1270f: MemoryConfig.shutdown_write_grace_s; its default (1.0) is also its
    # maximum, so production timing is unchanged.
    _write_grace = _grace_seconds(
        runtime, "shutdown_write_grace_s", SHUTDOWN_WRITE_GRACE_S,
    )
    logger.info("Shutdown grace period (%gs)...", _write_grace)
    await asyncio.sleep(_write_grace)

    # Cancel periodic flush — BF-099: await cancellation before trust writes
    if hasattr(runtime, '_flush_task'):
        flush_cancelled = False
        with steps("periodic flush task cancel"):
            runtime._flush_task.cancel()
            flush_cancelled = True
        # Not awaited when the cancel itself failed in a rollback: the task would still be
        # running, and waiting for it would hang the very teardown that must end.
        if flush_cancelled:
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
            # consolidation starts. AD-1270f: MemoryConfig.shutdown_dispatch_grace_s;
            # its default (2.0) is also its maximum, so production timing is unchanged.
            _dispatch_grace = _grace_seconds(
                runtime, "shutdown_dispatch_grace_s", SHUTDOWN_DISPATCH_GRACE_S,
            )
            await asyncio.sleep(_dispatch_grace)
            logger.info(
                "BF-296 Phase A: intent dispatch closed; "
                "%gs grace for in-flight handlers complete",
                _dispatch_grace,
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
    if rollback:
        # BF-882: a boot that never completed has no session to consolidate, and the
        # AD-820 marker below describes that consolidation, so neither runs.
        logger.info(
            "BF-882: startup rollback skips session consolidation and the AD-820 "
            "integrity marker."
        )
    elif runtime.dream_scheduler and runtime.episodic_memory:
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

    # BF-662: EvolutionStore may own a second PersistentClient on the same data
    # root. Release it before episodic Chroma shutdown so Windows does not retain
    # a competing handle during critical persistence cleanup.
    if getattr(runtime, "evolution_store", None) is not None:
        try:
            runtime.evolution_store.stop()
        except Exception:
            logger.warning(
                "BF-662: EvolutionStore stop failed before episodic shutdown; "
                "critical persistence cleanup will continue",
                exc_info=True,
            )
        runtime.evolution_store = None

    # BF-207: Close episodic memory (ChromaDB) immediately after dream
    # consolidation — this is the critical operation that caused hash mismatches
    # when it was positioned after ~25 service stops.
    if runtime.episodic_memory:
        with steps("episodic memory stop"):
            await runtime.episodic_memory.stop()

    # AD-455: stop red team campaign loop
    if hasattr(runtime, "red_team_lead") and runtime.red_team_lead is not None:
        with steps("red team lead stop"):
            await runtime.red_team_lead.stop()

    # AD-541f: Stop eviction audit log (companion to episodic memory)
    _eviction_audit = getattr(runtime, "_eviction_audit", None)
    if _eviction_audit is not None:
        with steps("eviction audit log stop"):
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
        if _data_dir is not None and not rollback:
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

    # BF-662 lifecycle: these runtime-owned SQLite services were
    # opened during startup but had no shutdown owner. Their non-daemon
    # aiosqlite workers kept pytest alive after all assertions completed.
    with steps("runtime SQLite sidecars stop"):
        await _stop_runtime_sqlite_sidecars(runtime)

    # Stop ACM (AD-427)
    if runtime.acm:
        with steps("ACM stop"):
            await runtime.acm.stop()
        runtime.acm = None

    # Stop Visiting Officer registry (AD-701)
    vo_registry = getattr(runtime, "visiting_officers", None)
    if vo_registry is not None:
        with steps("visiting officer registry stop"):
            await vo_registry.stop()
        runtime.visiting_officers = None

    # Stop Workflow Cron scheduler (AD-707)
    wfc = getattr(runtime, "workflow_cron", None)
    if wfc is not None:
        with steps("workflow cron stop"):
            await wfc.stop()
        runtime.workflow_cron = None

    # Stop Identity Registry (AD-441)
    if runtime.identity_registry:
        with steps("identity registry stop"):
            await runtime.identity_registry.stop()
        runtime.identity_registry = None

    # Stop SIF (AD-370)
    if runtime.sif:
        with steps("SIF stop"):
            await runtime.sif.stop()
        runtime.sif = None

    # Stop InitiativeEngine (AD-381)
    if runtime.initiative:
        with steps("initiative engine stop"):
            await runtime.initiative.stop()
        runtime.initiative = None

    from probos.recreation.turns import RecreationTurns

    # BF-882: these two statements are best-effort in a rollback, like every other step,
    # but they are executed on their own by tests/test_ad654d_internal_emitters.py with
    # only ``runtime`` and ``logger`` in scope, so they read the runtime's own flag
    # (set by the rollback) instead of the ``steps`` guard. A CancelledError is never
    # swallowed here: turns.stop() does synchronous work and AgentCognitiveQueue.shutdown()
    # waits with asyncio.wait, so neither re-raises a cancellation of its own, and the only
    # one that can arrive is the caller's.
    recreation = getattr(runtime, "recreation_service", None)
    if recreation is not None:
        turns: RecreationTurns = recreation.turns
        try:
            await turns.stop()
        except Exception:
            if not getattr(runtime, "_start_failed", False):
                raise
            logger.warning(
                "BF-882: startup rollback step 'recreation turns stop' raised; it may "
                "not have released everything. The rollback continues with the next step.",
                exc_info=True,
            )

    # AD-654b: Shutdown cognitive queues (before proactive loop stops)
    if hasattr(runtime, 'intent_bus') and runtime.intent_bus:
        for agent_id, queue in list(runtime.intent_bus._agent_queues.items()):
            try:
                await queue.shutdown()
            except Exception:
                if not getattr(runtime, "_start_failed", False):
                    raise
                logger.warning(
                    "BF-882: startup rollback step 'cognitive queue shutdown' raised for "
                    "agent %s; it may not have released everything. The rollback continues "
                    "with the next step.",
                    agent_id,
                    exc_info=True,
                )
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

    # BF-881 (#1452): the AD-641a bridge and the AD-477 Captain's Log and Plan of the
    # Day each have a stop() that no step here called, so their loops (and a start task
    # that had not run yet) outlived the runtime.
    for _service_attr, _start_task_attr, _service_label in (
        ("observability_bridge", "observability_bridge_start_task",
         "AD-641a ObservabilityBridge"),
        ("captains_log_service", "captains_log_start_task",
         "AD-477 CaptainsLogService"),
        ("plan_of_day_service", "plan_of_day_start_task",
         "AD-477 PlanOfDayService"),
    ):
        await _stop_held_start_service(
            runtime,
            service_attr=_service_attr,
            start_task_attr=_start_task_attr,
            label=_service_label,
        )

    # Stop Proactive Cognitive Loop (Phase 28b)
    if runtime.proactive_loop:
        # AD-415: Persist proactive cooldown overrides before stopping (not in a rollback)
        if not rollback and runtime._knowledge_store and runtime.proactive_loop._agent_cooldowns:
            try:
                await runtime._knowledge_store.store_cooldowns(runtime.proactive_loop._agent_cooldowns.copy())
            except Exception:
                logger.warning("Failed to persist proactive cooldowns", exc_info=True)
        with steps("proactive loop stop"):
            await runtime.proactive_loop.stop()
        runtime.proactive_loop = None

    # AD-471: Stop watch manager and expire Night Orders
    if hasattr(runtime, 'watch_manager') and runtime.watch_manager:
        with steps("watch manager stop"):
            await runtime.watch_manager.stop()
        runtime.watch_manager = None
    if not rollback and hasattr(runtime, '_night_orders_mgr') and runtime._night_orders_mgr:
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

    # BF-881 (#1452): the AD-733c-5 repoint above replaces the singleton the block before
    # it stopped, so the ship-level AD-733c-2 controller (kept on this attribute by
    # finalize) had no other owner and its idle watchdog outlived the runtime.
    await _stop_held_start_service(
        runtime,
        service_attr="perception_default_controller",
        start_task_attr=None,
        label="AD-733c-2 ship-level perception controller",
    )

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

    # AD-1019c: Stop MCP workbench idle-TTL reaper (before the bridge/stores it
    # drives are torn down). Idempotent; honest-degrade on failure.
    if getattr(runtime, 'mcp_workbench_reaper', None) is not None:
        try:
            await runtime.mcp_workbench_reaper.stop()
        except Exception:
            logger.warning(
                "AD-1019c: mcp_workbench_reaper.stop() failed", exc_info=True
            )
        runtime.mcp_workbench_reaper = None
        runtime.mcp_workbench = None

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

    # AD-1230: stop holding degraded turns. ``stop()`` posts into every thread
    # that is still waiting — the Captain was promised an answer, so a restart
    # must say so rather than drop the promise silently.
    if getattr(runtime, "deferred_turn_queue", None) is not None:
        try:
            await runtime.deferred_turn_queue.stop()
        except Exception:
            logger.warning(
                "AD-1230: deferred_turn_queue.stop() failed; held turns may not "
                "have been reported into their threads", exc_info=True
            )
        runtime.deferred_turn_queue = None

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
        with steps("persistent task store stop"):
            await runtime.persistent_task_store.stop()
        runtime.persistent_task_store = None

    # Stop Workforce Scheduling Engine (AD-496)
    if runtime.work_item_store:
        with steps("crew session delivery close"):
            await _close_crew_session_delivery(runtime)
        with steps("workforce store stop"):
            await runtime.work_item_store.stop()
        runtime.work_item_store = None

    # Stop build dispatcher (AD-375)
    if runtime.build_dispatcher:
        with steps("build dispatcher stop"):
            await runtime.build_dispatcher.stop()
        runtime.build_dispatcher = None
        runtime.build_queue = None

    # Disconnect service profiles (AD-382)
    from probos.agents.http_fetch import HttpFetchAgent
    from probos.cognitive.standing_orders import set_directive_store

    HttpFetchAgent.set_profile_store(None)
    # BF-881 (#1452): HttpFetchAgent was disconnected above and reads the store only in
    # synchronous code, so nothing can reach the store once it is closed.
    _close_sync_store(getattr(runtime, "service_profiles", None), "AD-382 ServiceProfileStore")
    runtime.service_profiles = None

    # Disconnect directive store (AD-386)
    if runtime.directive_store:
        set_directive_store(None)
        with steps("directive store close"):
            runtime.directive_store.close()
        runtime.directive_store = None

    # AD-596b: Disconnect cognitive skill catalog from standing orders
    from probos.cognitive.standing_orders import set_skill_catalog
    set_skill_catalog(None)

    # AD-596c: Clear skill bridge reference (stateless, no teardown needed)
    runtime.skill_bridge = None

    # Stop Ward Room (AD-407)
    if runtime.ward_room:
        with steps("ward room prune loop stop"):
            await runtime.ward_room.stop_prune_loop()
        with steps("ward room stop"):
            await runtime.ward_room.stop()
        runtime.ward_room = None

    # Stop Cognitive Journal (AD-431)
    if runtime.cognitive_journal:
        with steps("cognitive journal stop"):
            await runtime.cognitive_journal.stop()
        runtime.cognitive_journal = None

    # AD-622: Clearance grant store
    if hasattr(runtime, 'clearance_grant_store') and runtime.clearance_grant_store:
        with steps("clearance grant store stop"):
            await runtime.clearance_grant_store.stop()
        runtime.clearance_grant_store = None

    # AD-904: Clinical notes store
    if hasattr(runtime, 'clinical_notes_store') and runtime.clinical_notes_store:
        with steps("clinical notes store stop"):
            await runtime.clinical_notes_store.stop()
        runtime.clinical_notes_store = None

    # AD-423b: Tool permission store
    if hasattr(runtime, 'tool_permission_store') and runtime.tool_permission_store:
        with steps("tool permission store stop"):
            await runtime.tool_permission_store.stop()
        runtime.tool_permission_store = None

    # AD-1278 phase 1: get the bulk of the audit trail onto disk while the
    # system is still fully alive. Registration stays OPEN -- pools, the intent
    # bus and the mesh services all tear down below and can still append.
    with steps("AD-1278 early audit flush"):
        await _flush_audit_log(runtime)

    # AD-983b: Skill grant store (per-agent cognitive-skill grants)
    if getattr(runtime, 'skill_grant_store', None):
        with steps("skill grant store stop"):
            await runtime.skill_grant_store.stop()
        runtime.skill_grant_store = None

    # AD-1005/AD-1007: Intent grant store (per-agent mesh-capability grants)
    if getattr(runtime, 'intent_grant_store', None):
        with steps("intent grant store stop"):
            await runtime.intent_grant_store.stop()
        runtime.intent_grant_store = None
        runtime.hook_bus = None  # AD-1012

    # AD-1154: Action approval store (standing, TTL-bounded action approvals)
    if getattr(runtime, 'action_approval_store', None):
        with steps("action approval store stop"):
            await runtime.action_approval_store.stop()
        runtime.action_approval_store = None

    # AD-1015: MCP server registration store (runtime-mutable MCP registrations)
    if getattr(runtime, 'mcp_server_store', None):
        with steps("MCP server store stop"):
            await runtime.mcp_server_store.stop()
        runtime.mcp_server_store = None

    # AD-1019b: department-tier grant + tool-risk stores
    if getattr(runtime, 'department_tool_grant_store', None):
        with steps("department tool grant store stop"):
            await runtime.department_tool_grant_store.stop()
        runtime.department_tool_grant_store = None
    if getattr(runtime, 'mcp_tool_risk_store', None):
        with steps("MCP tool risk store stop"):
            await runtime.mcp_tool_risk_store.stop()
        runtime.mcp_tool_risk_store = None

    # Stop Counselor Profile Store (AD-503)
    if runtime._counselor_profile_store:
        with steps("counselor profile store stop"):
            await runtime._counselor_profile_store.stop()
        runtime._counselor_profile_store = None

    # Stop Procedure Store (AD-533)
    if runtime._procedure_store:
        with steps("procedure store stop"):
            await runtime._procedure_store.stop()
        runtime._procedure_store = None

    # Stop Drift Scheduler (AD-566c) — before qualification store
    drift_sched = getattr(runtime, "_drift_scheduler", None)
    if drift_sched is not None:
        with steps("drift scheduler stop"):
            await drift_sched.stop()
        runtime._drift_scheduler = None

    # Stop Qualification Store (AD-566a)
    qual_store = getattr(runtime, "_qualification_store", None)
    if qual_store is not None:
        with steps("qualification store stop"):
            await qual_store.stop()
        runtime._qualification_store = None
        runtime._qualification_harness = None

    # Stop Retrieval Practice Engine (AD-541c)
    if hasattr(runtime, '_retrieval_practice_engine') and runtime._retrieval_practice_engine:
        with steps("retrieval practice engine stop"):
            await runtime._retrieval_practice_engine.stop()
        runtime._retrieval_practice_engine = None

    # Stop Activation Tracker (AD-567d)
    _activation_tracker = getattr(runtime, "_activation_tracker", None)
    if _activation_tracker is not None:
        with steps("activation tracker stop"):
            await _activation_tracker.stop()
        runtime._activation_tracker = None

    # Stop Cognitive Skill Catalog (AD-596a)
    if runtime.cognitive_skill_catalog:
        with steps("cognitive skill catalog stop"):
            await runtime.cognitive_skill_catalog.stop()
        runtime.cognitive_skill_catalog = None

    # Stop Skill Framework (AD-428)
    if runtime.skill_service:
        with steps("skill service stop"):
            await runtime.skill_service.stop()
        runtime.skill_service = None
    if runtime.skill_registry:
        with steps("skill registry stop"):
            await runtime.skill_registry.stop()
        runtime.skill_registry = None

    # Stop Assignment Service (AD-408)
    if runtime.assignment_service:
        with steps("assignment service stop"):
            await runtime.assignment_service.stop()
        runtime.assignment_service = None

    # Stop red team agents
    for agent in runtime.red_team_agents:
        with steps(f"red team agent {agent.id} stop"):
            await agent.stop()
        with steps(f"red team agent {agent.id} unregister"):
            await runtime.registry.unregister(agent.id)
    runtime.red_team_agents.clear()

    # Stop pool scaler before stopping pools
    if runtime.pool_scaler:
        with steps("pool scaler stop"):
            await runtime.pool_scaler.stop()
        runtime.pool_scaler = None

    # Stop federation
    federation_telemetry_relay = getattr(
        runtime,
        "federation_telemetry_relay",
        None,
    )
    if federation_telemetry_relay:
        with steps("federation telemetry relay stop"):
            await federation_telemetry_relay.stop()
        runtime.federation_telemetry_relay = None
    if runtime.federation_bridge:
        with steps("federation bridge stop"):
            await runtime.federation_bridge.stop()
        runtime.federation_bridge = None
    remote_avatar_telemetry_cache = getattr(
        runtime,
        "remote_avatar_telemetry_cache",
        None,
    )
    if remote_avatar_telemetry_cache:
        with steps("remote avatar telemetry cache clear"):
            remote_avatar_telemetry_cache.clear()
    if runtime._federation_transport:
        with steps("federation transport stop"):
            await runtime._federation_transport.stop()
        runtime._federation_transport = None

    # AD-573: Freeze all agent working memory before pools stop (not in a rollback: a boot
    # that never completed has no session state to freeze, BF-882)
    if not rollback and hasattr(runtime, 'working_memory_store') and runtime.working_memory_store:
        # BF-127 / BF-882: is_crew_agent is the module-level import. A function-local
        # re-import here made the name local to all of shutdown(), so the session record
        # above raised UnboundLocalError (logged at debug) whenever the registry had agents.
        try:
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

    # Stop all pools, then drain any previously scheduled or concurrent
    # IntentBus work while NATS is still available. Failures retain the pool
    # owner but cannot bypass the remaining transport teardown.
    with steps("pools stop and intent bus drain"):
        deferred_shutdown_cancellation = await _stop_pools_and_drain_intent_bus(
            runtime
        )

    # BF-882: a pool that could not unwire an agent keeps it, running. A rollback has no
    # later retry, so stop what is still alive before the transport below is torn down.
    if rollback:
        await _quiesce_surviving_agents(runtime, steps)

    # BF-881 (#1452): three standing-orders module globals (single-runtime state, like
    # the two cleared earlier) were never cleared. ``_billet_registry`` reaches the runtime
    # through ``BilletRegistry._emit_event_fn``, so the whole stopped runtime stayed alive
    # until the next one overwrote it. Cleared HERE, after the pools stop and the
    # IntentBus drain, and not with the two above: a dispatch admitted before the bus
    # closed is still running until the drain completes, and composes its prompt from
    # these (sub_tasks/compose.py, analyze.py), which silently degrades without them.
    with steps("standing-orders globals clear"):
        from probos.cognitive.standing_orders import (
            set_billet_registry,
            set_step_router,
            set_task_context,
        )
        set_billet_registry(None)
        set_step_router(None)
        set_task_context(None)

    # Persist knowledge store artifacts before stopping services
    # (not in a rollback: BF-882 persists nothing a completed session would)
    if runtime._knowledge_store and not rollback:
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
    with steps("gossip protocol stop"):
        await runtime.gossip.stop()
    with steps("signal manager stop"):
        await runtime.signal_manager.stop()
    with steps("Hebbian router stop"):
        await runtime.hebbian_router.stop()
    with steps("trust network stop"):
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

    # BF-881 (#1452): two more synchronous SQLite handles with a close() nothing called.
    # SemanticStore (AD-750) is dropped after the close; ProfileStore keeps its attribute,
    # because close() is idempotent and a closed store's _persist does nothing.
    _semantic_store = getattr(runtime, "_semantic_store", None)
    if _semantic_store is not None:
        _close_sync_store(_semantic_store, "AD-750 SemanticStore")
        runtime._semantic_store = None
    _close_sync_store(getattr(runtime, "profile_store", None), "crew ProfileStore")

    # AD-1195: flush queued durable rows while the EventLog is still open, so
    # they land before the stopped row. A runtime double whose attribute is
    # not a coroutine function (a MagicMock) is skipped silently (BF-254).
    drain = getattr(runtime, "drain_durable_events", None)
    if drain is not None and inspect.iscoroutinefunction(drain):
        try:
            await drain()
        except Exception:
            logger.warning(
                "AD-1195: durable event drain failed; queued durable rows may be lost and shutdown continues",
                exc_info=True,
            )

    try:
        await runtime.event_log.log(category="system", event="stopped")
    except (asyncio.CancelledError, Exception):
        pass
    with steps("event log stop"):
        await runtime.event_log.stop()

    # BF-663: one-shot confab probes use the LLM but are not part of the generic
    # background registry. The production close seam drains the now-stable
    # registry before closing its dependency, so no evidence or notification can
    # arrive after shutdown. Dream consolidation remains earlier in the order.
    with steps("LLM client close"):
        await _close_llm_client_after_confab_probes(runtime)

    # Stop dreaming scheduler
    if runtime.dream_scheduler:
        with steps("dream scheduler stop"):
            await runtime.dream_scheduler.stop()
        runtime.dream_scheduler = None

    # Stop task scheduler (AD-282)
    if runtime.task_scheduler:
        with steps("task scheduler stop"):
            await runtime.task_scheduler.stop()
        runtime.task_scheduler = None

    try:
        # Stop semantic knowledge layer (AD-243)
        if runtime._semantic_layer:
            with steps("semantic knowledge layer stop"):
                await runtime._semantic_layer.stop()
            runtime._semantic_layer = None
    finally:
        # AD-1278 phase 2: the authoritative drain. Here rather than with the
        # other stores because `drain()` closes registration, and this is the
        # last point at which anything can append -- only a log line and the
        # return follow. Above the deferred-cancellation re-raise below, so a
        # cancellation carried over from pool teardown cannot skip it.
        #
        # In a `finally` because review reproduced the skip: a raising
        # `_semantic_layer.stop()` gave `drain_called=False`, losing the tail on
        # exactly the failure path an investigator most wants the record for.
        with steps("AD-1278 audit drain"):
            await _drain_audit_log(runtime)

    runtime._started = False
    if rollback:
        logger.info(
            "BF-882: startup rollback complete. Final agent count: %d",
            runtime.registry.count,
        )
    else:
        logger.info("ProbOS shutdown complete. Final agent count: %d", runtime.registry.count)
    if deferred_shutdown_cancellation is not None:
        raise deferred_shutdown_cancellation
