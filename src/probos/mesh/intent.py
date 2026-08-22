"""Intent bus — broadcast intents, agents self-select, collect results."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from collections import OrderedDict, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from probos.types import HandlerLatencyClass, IntentMessage, IntentResult, Priority, DispatchAdmission
from probos.mesh.nats_bus import DEFAULT_MAX_PAYLOAD_BYTES
from probos.mesh.signal import SignalManager
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied, authorize_intent

if TYPE_CHECKING:
    from probos.mesh.nats_bus import NATSBus

logger = logging.getLogger(__name__)

# Type for subscriber callbacks
IntentHandler = Callable[[IntentMessage], Awaitable[IntentResult | None]]


# BF-789: the class itself moved to `mesh.pre_intent_auth` so that consumers
# opting into the raising denial shape -- the AD-654c Dispatcher among them --
# can catch it without a module-level import of this module. Re-exported here
# because five production modules import it from `probos.mesh.intent`.
IntentAuthorizationDenied = IntentAuthorizationDenied

_DETERMINISTIC_HANDLER_LATENCY_MS = 100.0
_NETWORK_HANDLER_LATENCY_MS = 10_000.0
_COGNITIVE_HANDLER_LATENCY_MS = 30_000.0
_MAX_HANDLER_LATENCY_SAMPLES = 200
_MAX_HANDLER_METRIC_KEYS = 1_000

# BF-747: characters NATS forbids in a durable consumer name. A dot is the
# subject separator, so `agent-dispatch-perception.vision_aggregator` is not a
# name the server can hold -- and it does not say so. It TIMES OUT, which is why
# the boot log reported `nats: timeout` and named nothing useful. Verified live
# 2026-08-11 against the running server: the same call with an underscore
# succeeds and with a dot times out.
_DURABLE_UNSAFE = str.maketrans({c: "_" for c in ". *>\t\n/\\"})


def _durable_consumer_name(agent_id: str) -> str:
    """Return a NATS-safe durable name for this agent's dispatch consumer.

    Both the create and the delete path call this, or teardown would target a
    consumer that setup never made.

    A sanitised name carries a short hash of the original so two agents that
    differ only in an unsafe character (``a.b`` and ``a_b``) cannot collide onto
    one consumer. An id that needs no sanitising is returned unchanged, which
    matters: every durable that works today keeps the exact name it already has
    on the live server, so this fix cannot orphan a working consumer.
    """
    safe = agent_id.translate(_DURABLE_UNSAFE)
    if safe == agent_id:
        return f"agent-dispatch-{agent_id}"
    digest = hashlib.sha256(agent_id.encode("utf-8")).hexdigest()[:8]
    return f"agent-dispatch-{safe}-{digest}"


@dataclass
class _HandlerMetricStats:
    durations_ms: list[float] = field(default_factory=list)
    responded_count: int = 0
    declined_count: int = 0
    error_count: int = 0

    @property
    def count(self) -> int:
        return self.responded_count + self.declined_count + self.error_count

    def record(
        self,
        duration_ms: float,
        outcome: Literal["responded", "declined", "error"],
    ) -> None:
        self.durations_ms.append(duration_ms)
        if len(self.durations_ms) > _MAX_HANDLER_LATENCY_SAMPLES:
            del self.durations_ms[:-_MAX_HANDLER_LATENCY_SAMPLES]
        if outcome == "responded":
            self.responded_count += 1
        elif outcome == "declined":
            self.declined_count += 1
        else:
            self.error_count += 1

    def to_row(
        self,
        agent_id: str,
        intent_type: str,
        latency_class: HandlerLatencyClass,
    ) -> dict[str, Any]:
        sorted_samples = sorted(self.durations_ms)
        p95_index = math.ceil(0.95 * len(sorted_samples)) - 1
        return {
            "agent_id": agent_id,
            "intent": intent_type,
            "latency_class": latency_class.value,
            "count": self.count,
            "mean_ms": round(sum(sorted_samples) / len(sorted_samples), 2),
            "p95_ms": round(sorted_samples[p95_index], 2),
            "max_ms": round(sorted_samples[-1], 2),
            "responded_count": self.responded_count,
            "declined_count": self.declined_count,
            "error_count": self.error_count,
        }


@dataclass
class IntentMetrics:
    """Tracks intent broadcast statistics (AD-470)."""

    broadcast_count: int = 0
    send_count: int = 0
    total_results: int = 0
    type_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    type_durations_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _handler_stats: OrderedDict[
        tuple[str, str, HandlerLatencyClass], _HandlerMetricStats
    ] = field(default_factory=OrderedDict, init=False, repr=False)

    def record_broadcast(self, intent_type: str, result_count: int, duration_ms: float) -> None:
        """Record a broadcast completion."""
        self.broadcast_count += 1
        self.total_results += result_count
        self.type_counts[intent_type] += 1
        durations = self.type_durations_ms[intent_type]
        durations.append(duration_ms)
        if len(durations) > 200:
            self.type_durations_ms[intent_type] = durations[-200:]

    def record_send(self, intent_type: str, duration_ms: float) -> None:
        """Record a directed send completion."""
        self.send_count += 1
        self.type_counts[intent_type] += 1
        durations = self.type_durations_ms[intent_type]
        durations.append(duration_ms)
        if len(durations) > 200:
            self.type_durations_ms[intent_type] = durations[-200:]

    def record_handler(
        self,
        agent_id: str,
        intent_type: str,
        latency_class: HandlerLatencyClass,
        duration_ms: float,
        outcome: Literal["responded", "declined", "error"],
    ) -> None:
        """Record one completed broadcast-handler invocation."""
        if outcome not in ("responded", "declined", "error"):
            raise ValueError(f"invalid handler outcome: {outcome}")
        if not isinstance(latency_class, HandlerLatencyClass):
            raise TypeError("latency_class must be a HandlerLatencyClass")
        if not math.isfinite(duration_ms) or duration_ms < 0.0:
            raise ValueError("handler duration must be finite and non-negative")
        key = (agent_id, intent_type, latency_class)
        stats = self._handler_stats.get(key)
        if stats is None:
            stats = _HandlerMetricStats()
            self._handler_stats[key] = stats
            if len(self._handler_stats) > _MAX_HANDLER_METRIC_KEYS:
                self._handler_stats.popitem(last=False)
        else:
            self._handler_stats.move_to_end(key)
        stats.record(duration_ms, outcome)

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of intent metrics."""
        type_stats: dict[str, dict[str, Any]] = {}
        for intent_type, durations in self.type_durations_ms.items():
            if durations:
                type_stats[intent_type] = {
                    "count": self.type_counts[intent_type],
                    "mean_ms": round(sum(durations) / len(durations), 2),
                    "max_ms": round(max(durations), 2),
                }
        handler_rows = [
            stats.to_row(agent_id, intent_type, latency_class)
            for (agent_id, intent_type, latency_class), stats in sorted(
                self._handler_stats.items(),
                key=lambda item: (
                    item[0][0],
                    item[0][1],
                    item[0][2].value,
                ),
            )
        ]
        return {
            "broadcast_count": self.broadcast_count,
            "send_count": self.send_count,
            "total_results": self.total_results,
            "types": type_stats,
            "handlers": handler_rows,
        }


class IntentBus:
    """Async pub/sub for intent broadcasting.

    Agents subscribe with a handler. When an intent is broadcast,
    all subscribers are notified concurrently. Each subscriber decides
    whether to respond (self-selection). Results are collected with
    a configurable timeout.
    """

    def __init__(
        self,
        signal_manager: SignalManager,
        *,
        handler_latency_thresholds_ms: Mapping[
            HandlerLatencyClass, float
        ] | None = None,
    ) -> None:
        self._signal_manager = signal_manager
        if handler_latency_thresholds_ms is None:
            normalized_thresholds = {
                HandlerLatencyClass.DETERMINISTIC: _DETERMINISTIC_HANDLER_LATENCY_MS,
                HandlerLatencyClass.NETWORK: _NETWORK_HANDLER_LATENCY_MS,
                HandlerLatencyClass.COGNITIVE: _COGNITIVE_HANDLER_LATENCY_MS,
            }
        else:
            normalized_thresholds: dict[HandlerLatencyClass, float] = {}
            for latency_class in HandlerLatencyClass:
                try:
                    raw_threshold = handler_latency_thresholds_ms[latency_class]
                except (KeyError, TypeError) as exc:
                    raise ValueError(
                        f"missing handler latency threshold for {latency_class.value}"
                    ) from exc
                if isinstance(raw_threshold, bool):
                    raise ValueError(
                        "handler latency thresholds must be finite positive numbers"
                    )
                try:
                    threshold = float(raw_threshold)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "handler latency thresholds must be finite positive numbers"
                    ) from exc
                if not math.isfinite(threshold) or threshold <= 0.0:
                    raise ValueError(
                        "handler latency thresholds must be finite positive numbers"
                    )
                normalized_thresholds[latency_class] = threshold
        self._handler_latency_thresholds_ms = normalized_thresholds
        self._subscribers: dict[str, IntentHandler] = {}  # agent_id -> handler
        self._subscriber_latency_classes: dict[str, HandlerLatencyClass] = {}
        self._intent_index: dict[str, set[str]] = {}  # intent_name -> set of agent_ids
        self._pending_results: dict[str, list[IntentResult]] = {}  # intent_id -> results
        self._result_events: dict[str, asyncio.Event] = {}
        self._broadcast_timestamps: list[tuple[float, str]] = []  # (monotonic_time, intent_name)
        self._window_seconds: float = 60.0
        self._federation_fn: Callable[[IntentMessage], Awaitable[list[IntentResult]]] | None = None
        self._nats_bus: Any = None  # AD-637b: wired via set_nats_bus()
        self._pending_sub_tasks: set[asyncio.Task] = set()  # AD-637z: tracked NATS sub tasks
        self._agent_subscription_tasks: dict[str, set[asyncio.Task]] = {}
        self._pending_task_registration_closed: bool = False
        # BF-223: Defer JetStream dispatch consumer creation until after ship
        # commissioning sets the correct NATS subject prefix (DID-based).
        # During startup, subscribe() skips dispatch consumers; finalize.py
        # calls create_dispatch_consumers() after prefix is stable.
        self._defer_dispatch_consumers: bool = True
        # AD-654b: Per-agent cognitive queues
        self._agent_queues: dict[str, Any] = {}  # agent_id -> AgentCognitiveQueue
        # AD-654b: Injected callback for response recording (replaces handler.__self__ reach-through)
        self._record_response: Callable[[str, str], None] | None = None  # (agent_id, thread_id)

        # BF-234: Consumer-side dedup — tracks recently-seen intent IDs to
        # suppress transport-layer duplicates (JetStream redelivery, js_publish
        # timeout-then-succeed). Keyed by intent_id, value is monotonic timestamp.
        self._seen_intents: dict[str, float] = {}
        self._last_seen_eviction: float = time.monotonic()
        self._duplicate_suppressed_count: int = 0

        # BF-234: Injected event emitter for duplicate-suppressed telemetry.
        # Wired from finalize.py via set_emit_event().
        self._emit_event_fn: Callable[[str, dict[str, Any]], None] | None = None
        # AD-470: Intent metrics
        self._metrics = IntentMetrics()

        # BF-296: shutdown gate. When True, new dispatches are rejected
        # at all four entry points (broadcast, send, dispatch_async, and
        # the JetStream _on_dispatch NATS callback). In-flight handlers
        # complete normally. Idempotent. See startup/shutdown.py Phase A.
        self._closed: bool = False

    def close_to_new_dispatches(self) -> None:
        """BF-296: stop accepting new intent dispatches.

        Sets the closed flag. Subsequent broadcast(), send(),
        dispatch_async(), and JetStream _on_dispatch callbacks
        reject the work with an honest-degrade log. In-flight handlers
        complete normally — this method does NOT interrupt them.

        Idempotent — safe to call multiple times.

        Called from startup/shutdown.py Phase A before
        DreamScheduler.stop_gracefully() so consolidation writes do not
        compete with concurrent agent writes (see #771).
        """
        if self._closed:
            return
        self._closed = True
        logger.info(
            "BF-296: IntentBus closed to new dispatches "
            "(subscribers=%d, agent_queues=%d)",
            len(self._subscribers),
            len(self._agent_queues),
        )

    async def drain_pending_tasks(self, timeout_seconds: float = 5.0) -> None:
        """Close task registration and drain owned work before NATS shutdown."""
        self._pending_task_registration_closed = True
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, timeout_seconds)
        try:
            while True:
                tasks = tuple(
                    task for task in self._pending_sub_tasks if not task.done()
                )
                if not tasks:
                    await asyncio.sleep(0)
                    tasks = tuple(
                        task for task in self._pending_sub_tasks if not task.done()
                    )
                    if not tasks:
                        return

                remaining = deadline - loop.time()
                if remaining <= 0.0:
                    await self._cancel_pending_tasks(tasks, timeout_seconds)
                    return
                done, pending = await asyncio.wait(tasks, timeout=remaining)
                if done:
                    await asyncio.gather(*done, return_exceptions=True)
                if pending:
                    await self._cancel_pending_tasks(tuple(pending), timeout_seconds)
                    return
        except asyncio.CancelledError:
            pending = tuple(
                task for task in self._pending_sub_tasks if not task.done()
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise

    async def _cancel_pending_tasks(
        self,
        tasks: tuple[asyncio.Task, ...],
        timeout_seconds: float,
    ) -> None:
        for task in tasks:
            task.cancel()
        cancellation_grace = min(1.0, max(0.0, timeout_seconds))
        done, pending = await asyncio.wait(
            tasks,
            timeout=cancellation_grace,
        )
        if done:
            await asyncio.gather(*done, return_exceptions=True)
        logger.warning(
            "IntentBus pending-task drain timed out after %.1fs; cancelled "
            "%d task(s), %d still settling, so NATS shutdown can proceed",
            timeout_seconds,
            len(tasks),
            len(pending),
        )

    def _track_pending_task(
        self,
        task: asyncio.Task,
        *,
        report_nats_error: bool = False,
    ) -> bool:
        """Own one task unless shutdown already closed registration."""
        if self._pending_task_registration_closed:
            self._pending_sub_tasks.add(task)
            task.add_done_callback(self._pending_sub_tasks.discard)
            if report_nats_error:
                task.add_done_callback(self._on_nats_task_done)
            task.cancel()
            return False
        self._pending_sub_tasks.add(task)
        task.add_done_callback(self._pending_sub_tasks.discard)
        if report_nats_error:
            task.add_done_callback(self._on_nats_task_done)
        return True

    def _track_agent_subscription_task(
        self,
        agent_id: str,
        task: asyncio.Task,
    ) -> None:
        """Own one transport-subscription task for exact lifecycle teardown."""
        if not self._track_pending_task(task, report_nats_error=True):
            return
        tasks = self._agent_subscription_tasks.setdefault(agent_id, set())
        tasks.add(task)

        def _discard(completed: asyncio.Task) -> None:
            agent_tasks = self._agent_subscription_tasks.get(agent_id)
            if agent_tasks is None:
                return
            agent_tasks.discard(completed)
            if not agent_tasks:
                self._agent_subscription_tasks.pop(agent_id, None)

        task.add_done_callback(_discard)

    async def _cancel_agent_subscription_tasks(self, agent_id: str) -> None:
        """Cancel and await every pending subscription owned by one agent."""
        tasks = tuple(
            task
            for task in self._agent_subscription_tasks.pop(agent_id, set())
            if not task.done()
        )
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _remove_intent_index_memberships(self, agent_id: str) -> None:
        for agent_ids in self._intent_index.values():
            agent_ids.discard(agent_id)

    def subscribe(
        self,
        agent_id: str,
        handler: IntentHandler,
        intent_names: list[str] | None = None,
        *,
        latency_class: HandlerLatencyClass = HandlerLatencyClass.DETERMINISTIC,
    ) -> None:
        """Register an agent's intent handler.

        If intent_names is provided, the agent is indexed for those intents
        and will only be invoked when a matching intent is broadcast.
        Agents subscribed without intent_names receive all broadcasts (fallback).
        """
        if not isinstance(latency_class, HandlerLatencyClass):
            raise TypeError("latency_class must be a HandlerLatencyClass")
        self._subscribers[agent_id] = handler
        self._subscriber_latency_classes[agent_id] = latency_class
        self._remove_intent_index_memberships(agent_id)
        if intent_names:
            for name in intent_names:
                if name not in self._intent_index:
                    self._intent_index[name] = set()
                self._intent_index[name].add(agent_id)

        # AD-637b/z: Create NATS subscription for targeted send()
        if (
            self._nats_bus
            and self._nats_bus.connected
            and not self._pending_task_registration_closed
        ):
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    self._nats_subscribe_agent(agent_id, handler),
                    name=f"nats-sub-{agent_id[:12]}",
                )
                self._track_agent_subscription_task(agent_id, task)
                # AD-654a: Also subscribe to JetStream dispatch subject
                # BF-223: Skip during startup — deferred until prefix is stable
                if not self._defer_dispatch_consumers:
                    dispatch_task = loop.create_task(
                        self._js_subscribe_agent_dispatch(agent_id, handler),
                        name=f"js-dispatch-sub-{agent_id[:12]}",
                    )
                    self._track_agent_subscription_task(agent_id, dispatch_task)
            except RuntimeError:
                pass

    async def create_dispatch_consumers(self) -> None:
        """Create JetStream dispatch consumers for all subscribed agents.

        BF-223: Called from finalize.py after ship commissioning sets the
        correct DID-based NATS prefix. This ensures durable consumers are
        created with the stable prefix, eliminating the prefix race.

        Also clears _defer_dispatch_consumers so that agents created after
        startup (e.g., via self-modification) get immediate dispatch consumers.
        """
        self._defer_dispatch_consumers = False
        if not self._nats_bus or not self._nats_bus.connected:
            logger.debug("BF-223: NATS not connected, skipping dispatch consumer creation")
            return

        count = 0
        # BF-696: snapshot before iterating. ``_js_subscribe_agent_dispatch`` is
        # awaited inside this loop, so every iteration yields to the event loop
        # and a concurrent ``subscribe()`` mutates ``_subscribers`` mid-iteration
        # -> ``RuntimeError: dictionary changed size during iteration``, which
        # aborts ``finalize_startup`` and takes the whole boot down. The
        # perception.vision_aggregator JetStream retry loop is one live producer
        # of exactly that concurrent subscribe, which is why it presented
        # intermittently rather than every boot.
        #
        # A snapshot is COMPLETE here, not merely safe: ``_defer_dispatch_consumers``
        # is cleared above with no intervening await, so an agent subscribing
        # after that point creates its own dispatch consumer through the normal
        # ``subscribe()`` path. Nobody is missed, and nobody is created twice.
        for agent_id, handler in tuple(self._subscribers.items()):
            try:
                await self._js_subscribe_agent_dispatch(agent_id, handler)
                count += 1
            except Exception as e:
                logger.warning(
                    "BF-223: Dispatch consumer creation failed for %s: %s",
                    agent_id[:12], e,
                )
        logger.info("BF-223: Created %d JetStream dispatch consumers (prefix-stable)", count)

    async def _nats_subscribe_agent(self, agent_id: str, handler: IntentHandler) -> None:
        """Subscribe an agent to their NATS intent subject for send() delivery."""
        subject = f"intent.{agent_id}"

        async def _on_nats_intent(msg: Any) -> None:
            """NATS message adapter: deserialize → handler → serialize reply."""
            try:
                intent = self._deserialize_intent(msg.data)
                result = await handler(intent)
                if msg.reply:
                    if result is not None:
                        await msg.respond_encoded(
                            self._reply_bytes(result, self._reply_budget(msg))
                        )
                    else:
                        # Agent declined — send empty success response.
                        #
                        # BF-827: budgeted like the other two reply sites. The
                        # body is 18 bytes, so it cannot overflow on its own —
                        # but ``Msg.respond`` echoes the REQUEST's headers and
                        # the server counts body + headers, so a peer that
                        # sends a tiny body under a very large header block
                        # leaves no room even for this. nats-py's own guard
                        # checks the body alone, so the send would succeed
                        # locally and the server would reset the connection
                        # asynchronously: the caller times out holding nothing,
                        # with no local error. Every ProbOS caller sends a full
                        # serialized intent, so reaching it needs a
                        # non-standard peer — which is exactly the case a
                        # budget is for.
                        #
                        # Read the budget ONCE. Deciding from one call and
                        # logging another lets the warning name a size the
                        # decision was never made on — a log that confabulates
                        # its own reason.
                        budget = self._reply_budget(msg)
                        declined = self._decline_bytes(budget)
                        if declined is not None:
                            await msg.respond_encoded(declined)
                        else:
                            logger.warning(
                                "BF-827: cannot send the decline for intent on "
                                "agent %s — the request's echoed headers leave "
                                "%d bytes, less than the smallest decline this "
                                "can encode; the caller will time out",
                                agent_id[:12], budget,
                            )
            except Exception as e:
                logger.warning("NATS intent handler error for %s: %s", agent_id[:8], e)
                if msg.reply:
                    intent_id = (
                        msg.data.get("id", "") if isinstance(msg.data, dict) else ""
                    )
                    error_result = IntentResult(
                        intent_id=intent_id,
                        agent_id=agent_id,
                        success=False,
                        error=str(e),
                        confidence=0.0,
                    )
                    budget = self._reply_budget(msg)
                    try:
                        payload = self._reply_bytes(error_result, budget)
                    except Exception:
                        # BF-805: this branch is the last thing standing between
                        # the caller and silence, so it must not fail the same
                        # way the reply it is reporting on did. Measured live:
                        # a legal request whose echoed headers left a 111-byte
                        # budget could carry neither the 170-byte answer nor the
                        # 290-byte error about it, so BOTH raised, the second
                        # escaped the callback, and the requester timed out
                        # holding nothing -- exactly the outcome this BF exists
                        # to prevent, reached by its own error path.
                        payload = IntentBus._smallest_error_bytes(
                            intent_id, str(e), budget
                        )
                        if payload is None:
                            logger.error(
                                "BF-805: no reply of any size fits the %d-byte "
                                "budget for intent %s on agent %s (the request's "
                                "echoed headers consume the payload limit); the "
                                "caller will time out with nothing",
                                budget, intent_id[:16], agent_id[:12],
                            )
                            return
                    try:
                        await msg.respond_encoded(payload)
                    except Exception:
                        logger.error(
                            "BF-805: the error reply to intent %s on agent %s "
                            "could not be sent; the caller will time out",
                            intent_id[:16], agent_id[:12], exc_info=True,
                        )

        sub = await self._nats_bus.subscribe(subject, _on_nats_intent)

    async def _js_subscribe_agent_dispatch(self, agent_id: str, handler: IntentHandler) -> None:
        """Subscribe agent to their JetStream dispatch subject (AD-654a).

        Creates a durable consumer on intent.dispatch.{agent_id} within
        the INTENT_DISPATCH stream. Messages queue while agent is busy
        and are processed sequentially (max_ack_pending=1).

        Uses manual_ack=True because cognitive chains need msg.term() on
        error (not msg.nak()) — LLM calls that already ran must not retry.
        """
        subject = f"intent.dispatch.{agent_id}"

        async def _on_dispatch(msg: Any) -> None:
            """JetStream dispatch callback — deserialize and enqueue.

            AD-654b: Enqueues to cognitive queue instead of inline processing.
            The queue manages ack/term, priority ordering, and handler dispatch.

            BF-296: if the bus has been closed (shutdown Phase A), term the
            message instead of enqueueing it. Using term() (not nak()) so
            JetStream does NOT redeliver this intent on the next boot — that
            would replay pre-shutdown work after consolidation completed.
            """
            # BF-296: shutdown gate — drop on the floor, do not redeliver
            if self._closed:
                logger.debug(
                    "BF-296: _on_dispatch terminating msg on closed bus agent=%s",
                    agent_id[:12],
                )
                try:
                    await msg.term()
                except Exception:
                    pass  # transport may already be tearing down
                return

            try:
                intent_msg = self._deserialize_intent(msg.data)

                # BF-234: Consumer-side dedup gate — suppress transport-layer
                # duplicates (JetStream redelivery, js_publish timeout-then-succeed).
                # Only ward_room_notification intents need this; other intent types
                # are idempotent or use request/reply (not fire-and-forget).
                # NOTE: This is structural dedup (same intent.id delivered twice).
                # BF-198 record_agent_response/has_agent_responded is semantic
                # round-tracking (agent spoke in this thread) — different invariant.
                if intent_msg.intent == "ward_room_notification":
                    if self._is_duplicate_intent(intent_msg.id):
                        _first_seen_ts = self._seen_intents[intent_msg.id]
                        _age_ms = (time.monotonic() - _first_seen_ts) * 1000
                        self._duplicate_suppressed_count += 1
                        logger.warning(
                            "BF-234: Suppressed duplicate ward_room_notification "
                            "for %s (intent=%s, age=%.0fms, total_suppressed=%d)",
                            agent_id[:12], intent_msg.id[:8], _age_ms,
                            self._duplicate_suppressed_count,
                        )
                        if self._emit_event_fn:
                            self._emit_event_fn(
                                "wardroom.dispatch.duplicate_suppressed",
                                {
                                    "agent_id": agent_id,
                                    "thread_id": intent_msg.params.get("thread_id", ""),
                                    "intent_id": intent_msg.id,
                                    "age_ms": round(_age_ms, 1),
                                },
                            )
                        await msg.ack()
                        return
                    self._record_seen_intent(intent_msg.id)
                    self._maybe_evict_seen_intents()  # periodic sweep — after gate, not before

                # AD-654a/BF-198: Record response BEFORE handler runs to close
                # the proactive-loop race window.
                # Uses injected callback instead of handler.__self__ reach-through.
                if self._record_response:
                    _thread_id = intent_msg.params.get("thread_id", "")
                    if _thread_id:
                        self._record_response(intent_msg.target_agent_id, _thread_id)

                # AD-654b: Enqueue with priority classification
                queue = self._get_agent_queue(agent_id)
                if queue:
                    priority = Priority.classify(
                        intent=intent_msg.intent,
                        is_captain=intent_msg.params.get("is_captain", False),
                        was_mentioned=intent_msg.params.get("was_mentioned", False),
                    )
                    accepted = queue.enqueue(intent_msg, priority, js_msg=msg)
                    if not accepted:
                        # Queue rejected it (full + lower priority). term() it.
                        await msg.term()
                else:
                    # No queue — fall back to direct handler.
                    # This is normal for substrate agents (IntrospectAgent, VitalsMonitor, etc.)
                    # which don't have cognitive queues. Log at debug, not warning.
                    logger.debug("AD-654b: No queue for %s, direct dispatch", agent_id[:12])
                    await handler(intent_msg)
                    await msg.ack()
            except Exception as e:
                logger.warning(
                    "AD-654b: Dispatch callback error for %s: %s",
                    agent_id[:8], e,
                )
                await msg.term()

        # BF-747: sanitised, because the comment that used to sit here said the
        # name "must be NATS-safe (alphanumeric + dash)" and then interpolated
        # the agent id raw.
        durable_name = _durable_consumer_name(agent_id)

        # AD-654b: max_deliver=10 bounds nak() redelivery loops.
        # With circuit breaker nak(delay=60) + max_deliver=10, a stuck breaker
        # causes at most 10 redeliveries (~10 min) before JetStream auto-discards.
        # Without this, nak loops are unbounded.
        for attempt in range(3):
            sub = await self._nats_bus.js_subscribe(
                subject,
                _on_dispatch,
                durable=durable_name,
                stream="INTENT_DISPATCH",
                max_ack_pending=1,
                ack_wait=300,
                manual_ack=True,
                max_deliver=10,
            )
            if sub:
                logger.debug(
                    "AD-654b: JetStream dispatch consumer for %s",
                    agent_id[:12],
                )
                return
            if attempt < 2:
                delay = 0.5 * (2 ** attempt)
                logger.warning(
                    "JetStream dispatch consumer for %s was not created "
                    "(attempt %d/3); retrying in %.1fs",
                    agent_id[:12],
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
        raise RuntimeError(
            "JetStream dispatch consumer creation failed after 3 attempts "
            f"for agent {agent_id}"
        )

    def _unsubscribe_local(self, agent_id: str) -> None:
        """Synchronously remove one agent from all in-process indexes."""
        self._subscribers.pop(agent_id, None)
        self._subscriber_latency_classes.pop(agent_id, None)
        self.unregister_queue(agent_id)  # AD-654b: clean up cognitive queue
        self._remove_intent_index_memberships(agent_id)

    async def _unsubscribe_remote(self, agent_id: str) -> None:
        """Remove tracked NATS recipes before deleting the durable consumer."""
        await self._cancel_agent_subscription_tasks(agent_id)
        if not self._nats_bus:
            return
        removal_error: BaseException | None = None
        try:
            await self._nats_bus.remove_tracked_subscriptions(
                (
                    f"intent.{agent_id}",
                    f"intent.dispatch.{agent_id}",
                )
            )
        except BaseException as exc:
            removal_error = exc
        try:
            await self._nats_bus.delete_consumer(
                "INTENT_DISPATCH",
                _durable_consumer_name(agent_id),
            )
        except BaseException:
            if removal_error is None:
                raise
            logger.warning(
                "Agent %s transport teardown failed for both tracked "
                "subscriptions and durable consumer; preserving the first error",
                agent_id,
                exc_info=True,
            )
        if removal_error is not None:
            raise removal_error

    async def unsubscribe_and_wait(self, agent_id: str) -> None:
        """Remove one agent locally and await complete transport teardown."""
        await self._unsubscribe_remote(agent_id)
        self._unsubscribe_local(agent_id)

    def unsubscribe(self, agent_id: str) -> None:
        """Remove an agent locally and schedule transport cleanup."""
        self._unsubscribe_local(agent_id)
        if self._nats_bus and not self._pending_task_registration_closed:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    self._unsubscribe_remote(agent_id),
                    name=f"nats-unsub-{agent_id[:12]}",
                )
                self._track_pending_task(task, report_nats_error=True)
            except RuntimeError:
                pass

    def _on_nats_task_done(self, task: asyncio.Task) -> None:
        """Log errors from NATS subscribe/unsubscribe tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.warning("NATS sub/unsub task failed: %s", exc)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def has_subscriber(self, agent_id: str) -> bool:
        """Return whether an exact local subscriber is registered for agent_id."""
        return agent_id in self._subscribers

    def _authorize(
        self,
        intent: IntentMessage,
        *,
        entry_point: str,
        raise_on_denial: bool,
    ) -> bool:
        """Evaluate AD-698 pre-intent authorization. True to proceed (BF-771).

        Called from every entry point that can reach a handler -- ``broadcast``,
        ``send`` and ``dispatch_async``. It used to sit only in ``broadcast``,
        and below the targeted-dispatch branch, so setting ``target_agent_id``
        or calling ``send``/``dispatch_async`` directly bypassed it entirely.
        ``send`` alone has 14 direct callers, so RBAC or rate limiting could be
        skipped by choosing the entry point.

        Evaluated ONCE per intent: ``broadcast`` checks only on the fan-out
        path, because its targeted path delegates to ``send``, which checks.

        DENIAL SHAPE. A denial is reported in each entry point's PRE-EXISTING
        refusal shape -- ``send`` returns ``None``, ``broadcast`` returns
        ``[]``, ``dispatch_async`` no-ops -- so none of the 35 call seams sees
        a type it did not already handle. Those seams are 14 ``send``, 19
        ``broadcast``, one ``dispatch_async`` and one ``publish`` (the alias
        that forwards ``**kwargs`` to ``broadcast``; do not omit it, its
        WatchManager consumer is a real one). Raising unconditionally was tried
        and rejected: ``IntentAuthorizationDenied`` subclasses
        ``PermissionError``, so 14 of those seams sit inside a broad
        ``except Exception`` that swallows it, which relocates the defect
        instead of fixing it (one renders a policy refusal as "the lookup
        didn't finish in time"). A caller that must tell a denial apart from a
        silent no-op opts in with ``raise_on_denial=True`` and handles the
        exception itself.

        A type-compatible default is NOT automatically a safe one: a consumer
        that records success after a refused dispatch needs the opt-in. Known
        outstanding cases are tracked as BF-790 (#1254).

        SCOPE, stated plainly because an earlier version of this comment
        overclaimed: this covers the PRODUCER side only -- a caller on this
        node reaching the bus. It does NOT cover intents arriving over the
        wire: the NATS request/reply callback, the JetStream callback, the
        AD-654b cognitive queue and the AD-654c ``Dispatcher`` all reach a
        handler without passing here. That is BF-789 (#1253), and it is a
        different problem -- checking at both transport ends would
        double-charge a stateful hook such as a rate limiter.
        """
        # BF-789: the evaluation itself lives in `mesh.pre_intent_auth`, because
        # the AD-654c Dispatcher reaches handlers without touching this class and
        # needs to ask the identical question. Fail-closed handling for a broken
        # import and for a raising evaluator lives there; this method only maps
        # the verdict onto the bus's denial shape.
        #
        # DIAGNOSTIC CHANGE, stated because it is a real difference: the
        # import-failure and evaluator-failure paths used to raise `from exc`,
        # so `__cause__` carried the underlying error. The shared helper reports
        # a verdict rather than an exception, so `__cause__` is now None on
        # those two paths. Reason strings (`import:*`, `evaluator:*`) and
        # `entry_point` are unchanged, and the full traceback is still logged
        # with `exc_info=True` -- under `probos.mesh.pre_intent_auth` now, not
        # `probos.mesh.intent`. No consumer inspects the cause.
        allowed, reason = authorize_intent(intent, entry_point=entry_point)
        if allowed:
            return True
        if raise_on_denial:
            raise IntentAuthorizationDenied(intent.intent, reason, entry_point)
        return False

    async def send(
        self,
        intent: IntentMessage,
        *,
        raise_on_denial: bool = False,
    ) -> IntentResult | None:
        """Deliver an intent to a specific agent (targeted dispatch, AD-397).

        AD-637b: Uses NATS request/reply when connected, direct-call fallback otherwise.
        Only one path is used per call — never both.

        AD-637z: BF-221 lifted. Prefix re-subscription (set_subject_prefix)
        ensures NATS subscriptions survive the Phase 7 DID assignment.

        BF-296: returns ``None`` if the bus has been closed via
        ``close_to_new_dispatches()`` (shutdown Phase A).

        BF-771: also returns ``None`` when a pre-intent authorization hook
        denies the intent -- the same shape as the BF-296 gate, which every
        caller already handles. Pass ``raise_on_denial=True`` to receive
        ``IntentAuthorizationDenied`` instead.
        """
        if not intent.target_agent_id:
            raise ValueError("send() requires target_agent_id")

        # BF-296: shutdown gate
        if self._closed:
            logger.debug(
                "BF-296: send rejected on closed bus intent=%s target=%s",
                intent.intent, intent.target_agent_id[:12],
            )
            return None

        if not self._authorize(
            intent, entry_point="send", raise_on_denial=raise_on_denial
        ):
            return None

        _send_start = time.monotonic()  # AD-470: timing
        try:
            # NATS path when connected
            if self._nats_bus and self._nats_bus.connected:
                return await self._nats_send(intent)

            # Direct-call fallback when NATS disconnected
            handler = self._subscribers.get(intent.target_agent_id)
            if handler is None:
                return None
            try:
                result = await asyncio.wait_for(handler(intent), timeout=intent.ttl_seconds)
                return result
            except asyncio.TimeoutError:
                return IntentResult(
                    intent_id=intent.id,
                    agent_id=intent.target_agent_id,
                    success=False,
                    error="Agent did not respond in time.",
                    confidence=0.0,
                )
        finally:
            _elapsed_ms = (time.monotonic() - _send_start) * 1000
            self._metrics.record_send(intent.intent, _elapsed_ms)

    async def _nats_send(self, intent: IntentMessage) -> IntentResult | None:
        """Send intent via NATS request/reply to target agent."""
        subject = f"intent.{intent.target_agent_id}"
        try:
            reply = await asyncio.wait_for(
                self._nats_bus.request(
                    subject,
                    self._serialize_intent(intent),
                    timeout=intent.ttl_seconds,
                ),
                timeout=intent.ttl_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("NATS send timeout: %s → %s", intent.intent, intent.target_agent_id[:12])
            return IntentResult(
                intent_id=intent.id,
                agent_id=intent.target_agent_id or "",
                success=False,
                error="Agent did not respond in time.",
                confidence=0.0,
            )
        if reply is None:
            return None
        data = reply.data if hasattr(reply, 'data') else reply
        if isinstance(data, dict) and data.get("declined"):
            return None
        return self._deserialize_result(data)

    async def broadcast(
        self,
        intent: IntentMessage,
        timeout: float | None = None,
        *,
        federated: bool = True,
        raise_on_denial: bool = False,
    ) -> list[IntentResult]:
        """Broadcast an intent to all subscribers, collect results.

        Each subscriber is called concurrently. Subscribers that return
        None are treated as having declined the intent (self-deselected).
        Waits up to `timeout` seconds (defaults to intent TTL) for results.

        If intent.target_agent_id is set, delegates to send() for targeted dispatch.

        BF-296: returns ``[]`` if the bus has been closed via
        ``close_to_new_dispatches()`` (shutdown Phase A).

        BF-771: also returns ``[]`` when a pre-intent authorization hook denies
        the intent -- the shape AD-698 has always used for a denial. Pass
        ``raise_on_denial=True`` to receive ``IntentAuthorizationDenied``
        instead; it propagates through the targeted path as well.
        """
        # BF-296: shutdown gate. Honest-degrade — return empty result list
        # so callers see "no agent responded" rather than an exception, which
        # matches the existing behavior when no subscribers match.
        if self._closed:
            logger.debug(
                "BF-296: broadcast rejected on closed bus intent=%s id=%s",
                intent.intent, intent.id[:8],
            )
            return []

        # AD-397: targeted dispatch. `send` performs the AD-698 authorization,
        # so this path must NOT check first -- that would evaluate every hook
        # twice for one intent.
        if intent.target_agent_id:
            result = await self.send(intent, raise_on_denial=raise_on_denial)
            return [result] if result else []

        # AD-698 / BF-771: fan-out path authorization.
        if not self._authorize(
            intent, entry_point="broadcast", raise_on_denial=raise_on_denial
        ):
            return []

        timeout = timeout if timeout is not None else intent.ttl_seconds
        _broadcast_start = time.monotonic()  # AD-470: timing

        self.record_broadcast(intent.intent)

        # BF-829: the straggler-cancel and both state cleanups used to sit
        # BELOW the await, on the normal path only. A caller cancelled
        # mid-flight -- a request timeout, shutdown, or an OUTER broadcast
        # cancelling this one as its own straggler -- raised CancelledError out
        # of `asyncio.wait` and skipped all three. Measured against the real
        # bus: the child was neither cancelled nor completed, still sleeping
        # with nothing left holding a reference that would ever cancel it,
        # while `_pending_results` and the SignalManager entry both leaked.
        # The nested case compounds: stranding the inner broadcast's children
        # strands theirs in turn.
        #
        # The `try` opens BEFORE `track()` and the `_pending_results` entry, not
        # at the fan-out. Review measured why: nothing between them awaits, so
        # cancellation cannot land there -- but a synchronous raise can, and a
        # logging handler whose `emit()` raised left BOTH registries dirty. A
        # `try` that starts after the registration it is meant to unwind only
        # moves the leak somewhere quieter. `untrack` is idempotent and both
        # cleanups tolerate partial setup.
        tasks: list[asyncio.Task] = []
        # THE round's result list. Held as a local, not looked up again: every
        # ID-keyed read is a chance to pick up a different round's work, which
        # is the whole of BF-833. `_pending_results` stays a registry so the
        # leak assertions BF-829 added remain meaningful, but it is no longer
        # how this round finds its own results.
        sink: list[IntentResult] = []
        try:
            self._signal_manager.track(intent)
            self._pending_results[intent.id] = sink

            logger.info(
                "Intent broadcast: %s id=%s urgency=%.1f subscribers=%d",
                intent.intent,
                intent.id[:8],
                intent.urgency,
                len(self._subscribers),
            )

            # Determine which agents to fan out to
            indexed_agents = self._intent_index.get(intent.intent)
            if indexed_agents is not None:
                # Pre-filtered: only invoke agents indexed for this intent
                # Plus any agents not in the index at all (fallback subscribers)
                all_indexed = set()
                for agent_set in self._intent_index.values():
                    all_indexed.update(agent_set)
                candidates = {
                    aid: (
                        handler,
                        self._subscriber_latency_classes.get(
                            aid, HandlerLatencyClass.DETERMINISTIC
                        ),
                    )
                    for aid, handler in self._subscribers.items()
                    if aid in indexed_agents or aid not in all_indexed
                }
            else:
                # No index entry: fall back to all subscribers
                candidates = {
                    aid: (
                        handler,
                        self._subscriber_latency_classes.get(
                            aid, HandlerLatencyClass.DETERMINISTIC
                        ),
                    )
                    for aid, handler in self._subscribers.items()
                }

            # Fan out to selected subscribers concurrently
            #
            # BF-833 (#1298): hand each handler THIS round's list object, not the
            # intent id. `_invoke_handler` used to look the id up in
            # `_pending_results` before appending -- a presence test, which
            # cannot tell one round from the next, because `broadcast` recreates
            # the key on every call. A straggler that suppressed its
            # `CancelledError` and finished during a later broadcast of the same
            # id appended into that later round: measured
            # `second=[('stale-first','STALE'), ('fresh','FRESH')]`. Well-formed,
            # so nothing logged and nothing failed -- and every result is fed to
            # Hebbian routing and quorum before the caller sees it, so it
            # reinforced the wrong edge and voted in a round it was not part of.
            #
            # The capture is HERE, synchronously, and deliberately not inside
            # `_invoke_handler`: `create_task` only schedules. Review opened
            # that window -- two broadcasts of one ID released together, where
            # round 2 replaces the dict entry before round 1's handler runs its
            # first line, 10 runs out of 10. My own attempt with SEQUENTIAL
            # rounds could not open it in 33 orderings, which is why the
            # concurrent case is now a test.
            for agent_id, (handler, latency_class) in list(candidates.items()):
                tasks.append(
                    asyncio.create_task(
                        self._invoke_handler(
                            intent, agent_id, handler, latency_class, sink,
                        ),
                        name=f"intent-{intent.id[:8]}-{agent_id[:8]}",
                    )
                )

            if tasks:
                # Wait for all handlers, bounded by timeout
                await asyncio.wait(tasks, timeout=timeout)

            # Read THIS round's list. Reading `_pending_results[intent.id]`
            # here would hand a concurrent round's results to this caller and
            # lose its own -- measured, and identical before BF-833.
            results = list(sink)
        finally:
            # Cancel stragglers. Not awaited: that is deliberate. The timeout
            # path has always returned without waiting for stragglers to
            # unwind, and awaiting here would let one handler with slow
            # cancellation cleanup block every broadcast that times out --
            # measured at 2.2s against 0.2s.
            #
            # A straggler cannot touch `_pending_results` at all: BF-833 gives
            # it this round's list object directly, so once the pop below runs
            # nothing but the straggler holds that list and its append is
            # inert. Before BF-833 the appends were guarded by an id presence
            # test, which stopped a re-leak of the popped key but NOT an append
            # into a later round that had recreated it. That distinction is
            # gone; the object now identifies the round.
            for task in tasks:
                if not task.done():
                    task.cancel()

            # Drop the registry entry ONLY if it is still this round's list. A
            # later broadcast of the same ID has already replaced it, and
            # popping then would delete a live round's entry.
            if self._pending_results.get(intent.id) is sink:
                self._pending_results.pop(intent.id, None)
            self._signal_manager.untrack(intent.id)

        # AD-470: Record metrics
        elapsed_ms = (time.monotonic() - _broadcast_start) * 1000
        self._metrics.record_broadcast(intent.intent, len(results), elapsed_ms)

        # Federation: forward to peers if enabled and not an inbound federated intent
        if federated and self._federation_fn:
            try:
                remote_results = await self._federation_fn(intent)
                results.extend(remote_results)
            except Exception as e:
                logger.debug("Federation forwarding failed: %s", e)

        logger.info(
            "Intent resolved: %s id=%s results=%d",
            intent.intent,
            intent.id[:8],
            len(results),
        )
        return results

    async def publish(self, intent: IntentMessage, **kwargs: Any) -> list[IntentResult]:
        """Alias for broadcast() — used by WatchManager dispatch (runtime.py:689)."""
        return await self.broadcast(intent, **kwargs)

    async def dispatch_async(
        self,
        intent: IntentMessage,
        *,
        raise_on_denial: bool = False,
    ) -> DispatchAdmission:
        """Fire-and-forget dispatch to a specific agent via JetStream (AD-654a).

        Publishes the intent to the agent's durable JetStream consumer.
        No reply expected — the agent processes asynchronously and posts
        its own response. Falls back to direct async handler invocation
        when NATS/JetStream is unavailable.

        Requires intent.target_agent_id to be set.

        BF-296: silently no-ops if the bus has been closed via
        ``close_to_new_dispatches()`` (shutdown Phase A). Note this also
        prevents new JetStream publishes during shutdown, so peer nodes
        will not see fresh dispatch messages from this node post-Phase-A.

        BF-815: returns a ``DispatchAdmission`` rather than ``None``. Four paths
        here reject the intent -- closed bus, policy denial, no handler, and the
        pending-task cap -- and all four were previously indistinguishable from
        success, because the method returned ``None`` whether it handed the work
        off or binned it. Consumers counted every call as delivered. Adding a
        return value is backward-compatible: callers that ignore it behave
        exactly as before.

        ``admitted`` means the delivery SUBSTRATE accepted responsibility, not
        that an agent processed the work or ever will. See ``DispatchAdmission``.
        """
        if not intent.target_agent_id:
            raise ValueError("dispatch_async() requires target_agent_id")

        # BF-296: shutdown gate
        if self._closed:
            logger.debug(
                "BF-296: dispatch_async rejected on closed bus intent=%s target=%s",
                intent.intent, intent.target_agent_id[:12],
            )
            return DispatchAdmission(False, reason="bus_closed")

        if not self._authorize(
            intent, entry_point="dispatch_async", raise_on_denial=raise_on_denial
        ):
            return DispatchAdmission(False, reason="denied")

        # JetStream path when connected
        if self._nats_bus and self._nats_bus.connected:
            subject = f"intent.dispatch.{intent.target_agent_id}"
            try:
                outcome = await self._nats_bus.js_publish(
                    subject, self._serialize_intent(intent)
                )
                # BF-815: js_publish returns normally even when BOTH JetStream
                # and core NATS failed and it logged "event dropped", so this
                # used to report a lost message as dispatched. A drop now falls
                # through to the local paths below rather than claiming success.
                if outcome != "dropped":
                    logger.debug(
                        "AD-654a: Dispatched %s → %s via %s",
                        intent.intent, intent.target_agent_id[:12], outcome,
                    )
                    return DispatchAdmission(True, route=outcome)
                logger.warning(
                    "BF-815: both transports dropped %s → %s; falling back to "
                    "local dispatch",
                    intent.intent, intent.target_agent_id[:12],
                )
            except Exception as e:
                logger.warning(
                    "AD-654a: JetStream dispatch failed for %s → %s: %s, falling back to direct",
                    intent.intent, intent.target_agent_id[:12], e,
                )
                # Fall through to direct dispatch

        # Direct-call fallback when NATS/JetStream unavailable

        # AD-654b: Try cognitive queue even when NATS is down.
        # This PRECEDES the existing create_task fallback — if the queue
        # accepts the item, return early. If no queue exists (substrate agents)
        # or enqueue is rejected (full + lower priority), fall through to
        # the create_task direct-dispatch path below.
        queue = self._get_agent_queue(intent.target_agent_id)
        if queue:
            priority = Priority.classify(
                intent=intent.intent,
                is_captain=intent.params.get("is_captain", False),
                was_mentioned=intent.params.get("was_mentioned", False),
            )
            # js_msg=None — no JetStream backing for fallback path
            if queue.enqueue(intent, priority):
                return DispatchAdmission(True, route="queue")
            # enqueue returned False — fall through to create_task

        # Existing AD-654a fallback: direct handler invocation for agents
        # without cognitive queues (substrate agents) or when queue is full.
        handler = self._subscribers.get(intent.target_agent_id)
        if handler is None:
            logger.debug("AD-654a: No handler for %s, dropping", intent.target_agent_id[:12])
            return DispatchAdmission(False, reason="no_handler")

        # Soft cap on pending fallback tasks to prevent unbounded growth
        _MAX_PENDING_TASKS = 200
        if len(self._pending_sub_tasks) >= _MAX_PENDING_TASKS:
            logger.warning(
                "AD-654a: Pending task cap (%d) reached, dropping dispatch for %s",
                _MAX_PENDING_TASKS, intent.target_agent_id[:12],
            )
            return DispatchAdmission(False, reason="pending_cap")

        async def _run_handler() -> None:
            try:
                await handler(intent)
            except Exception:
                logger.warning(
                    "AD-654a: Direct handler failed for %s",
                    intent.target_agent_id[:12],
                    exc_info=True,
                )

        task = asyncio.get_running_loop().create_task(
            _run_handler(),
            name=f"dispatch-async-{intent.target_agent_id[:12]}",
        )
        # BF-815: `_track_pending_task` CANCELS the task and returns False when
        # shutdown has closed registration. Ignoring that reported an admission
        # for a handler that was cancelled before it ran -- reachable whenever
        # the bus closes while an awaited transport call is in flight.
        if not self._track_pending_task(task):
            return DispatchAdmission(False, reason="registration_closed")
        return DispatchAdmission(True, route="task")

    # ── AD-654b: Cognitive queue management ─────────────────────────

    def set_record_response(self, callback: Callable[[str, str], None]) -> None:
        """AD-654b: Inject response recording callback.

        Replaces the handler.__self__._runtime.ward_room_router reach-through
        that violated Law of Demeter. Called from finalize.py with
        ward_room_router.record_agent_response.
        """
        self._record_response = callback

    def register_queue(self, agent_id: str, queue: Any) -> None:
        """Register an agent's cognitive queue (AD-654b)."""
        self._agent_queues[agent_id] = queue

    def unregister_queue(self, agent_id: str) -> None:
        """Remove an agent's cognitive queue (AD-654b)."""
        self._agent_queues.pop(agent_id, None)

    def _get_agent_queue(self, agent_id: str) -> Any | None:
        """Get the cognitive queue for an agent (AD-654b)."""
        return self._agent_queues.get(agent_id)

    def get_subscriber_map(self) -> dict[str, list[str]]:
        """Return intent_name → [agent_ids] mapping (AD-470).

        Shows which agents are indexed for which intent types.
        Agents not in any index (fallback subscribers) are listed
        under the key "__fallback__".
        """
        result: dict[str, list[str]] = {}
        all_indexed: set[str] = set()

        for intent_name, agent_ids in self._intent_index.items():
            result[intent_name] = sorted(agent_ids)
            all_indexed.update(agent_ids)

        fallback = [
            aid for aid in self._subscribers
            if aid not in all_indexed
        ]
        if fallback:
            result["__fallback__"] = sorted(fallback)

        return result

    def get_metrics(self) -> dict[str, Any]:
        """Return intent bus metrics summary (AD-470)."""
        return self._metrics.get_summary()

    def record_broadcast(self, intent_name: str) -> None:
        """Record a broadcast event with its intent name."""
        self._broadcast_timestamps.append((time.monotonic(), intent_name))

    def demand_metrics(self) -> dict:
        """Return current demand snapshot (system-wide)."""
        now = time.monotonic()
        cutoff = now - self._window_seconds
        self._broadcast_timestamps = [(t, n) for t, n in self._broadcast_timestamps if t > cutoff]
        return {
            "broadcasts_in_window": len(self._broadcast_timestamps),
            "subscriber_count": len(self._subscribers),
        }

    def per_pool_demand(self, pool_intents: dict[str, list[str]]) -> dict[str, int]:
        """Return broadcast counts per pool within the observation window.

        Args:
            pool_intents: mapping of pool_name -> list of intent names that pool handles.

        Returns:
            dict of pool_name -> number of broadcasts targeting that pool's intents.
        """
        now = time.monotonic()
        cutoff = now - self._window_seconds
        self._broadcast_timestamps = [(t, n) for t, n in self._broadcast_timestamps if t > cutoff]

        # Build reverse mapping: intent_name -> pool_name
        intent_to_pool: dict[str, str] = {}
        for pool_name, intents in pool_intents.items():
            for intent_name in intents:
                intent_to_pool[intent_name] = pool_name

        counts: dict[str, int] = {name: 0 for name in pool_intents}
        for _, intent_name in self._broadcast_timestamps:
            pool = intent_to_pool.get(intent_name)
            if pool:
                counts[pool] += 1
        return counts

    async def _invoke_handler(
        self,
        intent: IntentMessage,
        agent_id: str,
        handler: IntentHandler,
        latency_class: HandlerLatencyClass,
        sink: list[IntentResult],
    ) -> None:
        """Invoke a single subscriber's handler, catching errors.

        ``sink`` is the result list belonging to the broadcast that launched
        this task, captured before the task was scheduled (BF-833). Appending
        to it directly is what makes a late result land in its OWN round: once
        that round returns, its list is dropped from ``_pending_results`` and
        nothing else holds it, so a straggler's append is inert rather than
        misattributed. There is no presence test because there is nothing left
        to test -- the object identifies the round.
        """
        t0 = time.monotonic()
        try:
            result = await handler(intent)
            elapsed_ms = (time.monotonic() - t0) * 1000
            outcome: Literal["responded", "declined"] = (
                "responded" if result is not None else "declined"
            )
            self._metrics.record_handler(
                agent_id,
                intent.intent,
                latency_class,
                elapsed_ms,
                outcome,
            )
            threshold_ms = self._handler_latency_thresholds_ms[latency_class]
            if elapsed_ms > threshold_ms:
                logger.warning(
                    "Handler completed over latency budget: agent_id=%s "
                    "intent=%s latency_class=%s threshold_ms=%.0f "
                    "elapsed_ms=%.0f outcome=%s dispatch=completed",
                    agent_id,
                    intent.intent,
                    latency_class.value,
                    threshold_ms,
                    elapsed_ms,
                    outcome,
                )
            if result is not None:
                # Agent accepted and responded
                sink.append(result)
        except Exception as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._metrics.record_handler(
                agent_id,
                intent.intent,
                latency_class,
                elapsed_ms,
                "error",
            )
            logger.warning(
                "Handler error: agent_id=%s intent=%s intent_id=%s "
                "reason=%s dispatch=completed",
                agent_id,
                intent.intent,
                intent.id,
                e,
            )
            # Record the failure as a result
            sink.append(
                IntentResult(
                    intent_id=intent.id,
                    agent_id=agent_id,
                    success=False,
                    error=str(e),
                    confidence=0.0,
                )
            )

    # ------------------------------------------------------------------
    # AD-514: Public API
    # ------------------------------------------------------------------

    def set_federation_handler(self, fn: Callable) -> None:
        """Set the federation forwarding handler for cross-realm intents."""
        self._federation_fn = fn

    def set_nats_bus(self, nats_bus: Any) -> None:
        """Wire NATS transport (called after NATS connects in Phase 1b)."""
        self._nats_bus = nats_bus
        # AD-637z: Register for prefix change notification (logging only —
        # NATSBus handles re-subscription of all tracked subs automatically)
        nats_bus.register_on_prefix_change(self._on_prefix_change)

    async def _on_prefix_change(self, old_prefix: str, new_prefix: str) -> None:
        """Log prefix change — NATSBus has already re-subscribed all agents."""
        logger.info(
            "IntentBus: NATS prefix changed %s → %s, %d agent subs re-subscribed by NATSBus",
            old_prefix[:20], new_prefix[:20], len(self._subscribers),
        )

    # ------------------------------------------------------------------
    # BF-234: Consumer-side dispatch dedup
    # ------------------------------------------------------------------

    # Window must be ≥ JetStream ack_wait to catch duplicates queued behind
    # a slow handler. With max_ack_pending=1, msg #2 waits until msg #1 acks
    # (5–60s for a cognitive chain). 300s matches ack_wait=300 in
    # _js_subscribe_agent_dispatch. Memory: ~84KB worst case at 12 agents ×
    # 10 events/min × 600s eviction.
    _WARD_ROOM_DISPATCH_DEDUP_WINDOW: float = 300.0  # seconds — matches ack_wait

    def _is_duplicate_intent(self, intent_id: str) -> bool:
        """BF-234: Check if intent_id was already seen within the dedup window."""
        if not intent_id:
            return False
        last = self._seen_intents.get(intent_id)
        if last is not None and (time.monotonic() - last) < self._WARD_ROOM_DISPATCH_DEDUP_WINDOW:
            return True
        return False

    def _record_seen_intent(self, intent_id: str) -> None:
        """BF-234: Record that intent_id has been consumed."""
        if intent_id:
            self._seen_intents[intent_id] = time.monotonic()

    def _evict_stale_seen_intents(self, max_age: float = 600.0) -> None:
        """BF-234: Evict seen-intent records older than ``max_age`` seconds."""
        cutoff = time.monotonic() - max_age
        self._seen_intents = {
            k: v for k, v in self._seen_intents.items() if v > cutoff
        }
        self._last_seen_eviction = time.monotonic()

    def _maybe_evict_seen_intents(self, interval: float = 300.0) -> None:
        """BF-234: Periodic eviction — runs at most once per ``interval`` seconds."""
        if time.monotonic() - self._last_seen_eviction >= interval:
            self._evict_stale_seen_intents()

    def get_duplicate_suppressed_count(self) -> int:
        """BF-234: Return total number of transport-layer duplicates suppressed."""
        return self._duplicate_suppressed_count

    def set_emit_event(self, fn: Callable[[str, dict[str, Any]], None]) -> None:
        """BF-234: Inject event emitter for duplicate-suppressed telemetry."""
        self._emit_event_fn = fn

    # ------------------------------------------------------------------
    # AD-637b: Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_intent(intent: IntentMessage) -> dict[str, Any]:
        """Serialize IntentMessage for NATS transport.

        All fields must be JSON-serializable. params dict values that are
        not JSON-serializable will raise TypeError — fail fast.

        AD-731 (2026-05-11): BF-265's transport strip removed. Vision
        attachments are now carried as content-addressable refs (~70 bytes
        per image) instead of inline base64. The receiver dereferences from
        the local AttachmentStore inside the LLM client. The bus carries
        only refs; payload size is bounded; the uniform-NATS-transport
        invariant is restored. AD-637z2 closes as part of this AD.

        BF-742: every field of ``IntentMessage`` must appear here. A field the
        wire omits is not defaulted at the receiver in any visible way -- it
        arrives as the dataclass default, so a producer that set it and a
        consumer that reads it can both be correct while the value never
        survives the trip. A drift guard in the tests pins this set against
        ``dataclasses.fields``.
        """
        return {
            "intent": intent.intent,
            "params": intent.params,
            "urgency": intent.urgency,
            "context": intent.context,
            "ttl_seconds": intent.ttl_seconds,
            "id": intent.id,
            "created_at": intent.created_at.isoformat(),
            "target_agent_id": intent.target_agent_id,
            "thread_id": intent.thread_id,
        }

    @staticmethod
    def _deserialize_intent(data: dict[str, Any]) -> IntentMessage:
        """Deserialize IntentMessage from NATS transport."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        else:
            created_at = datetime.now(timezone.utc)
        return IntentMessage(
            intent=data["intent"],
            params=data.get("params", {}),
            urgency=data.get("urgency", 0.5),
            context=data.get("context", ""),
            ttl_seconds=data.get("ttl_seconds", 60.0),
            id=data.get("id", ""),
            created_at=created_at,
            target_agent_id=data.get("target_agent_id"),
            # Tolerant of a peer that predates BF-742: absent means None, which
            # is the pre-fix behaviour rather than a hard failure.
            thread_id=data.get("thread_id"),
        )

    @staticmethod
    def _decline_bytes(limit: int) -> bytes | None:
        """The smallest decline that still fits, or ``None`` if none does.

        BF-827: the ordinary encoding is 18 bytes and is what every peer has
        always received, so it is tried first and is byte-identical to the
        pre-fix reply. Below that there is still one honest option: JSON's
        whitespace is optional, and ``{"declined":true}`` is 17 bytes and
        decodes to exactly the same object.

        Review measured that 17-byte case against a live server — headers left
        exactly 17 bytes, the compact form crossed at the limit and decoded
        correctly, and the first version of this fix logged and gave up on a
        reply that was deliverable. A refusal where delivery is possible is a
        capability ceiling nobody chose (DP-13a), not a safety property.

        ``None`` means the budget will not take even seventeen bytes. Nothing
        can be sent then; returning it rather than raising lets the caller say
        so in the log.
        """
        for payload in (
            b'{"declined": true}',  # the historical encoding, byte-for-byte
            b'{"declined":true}',   # the same object, JSON whitespace dropped
        ):
            if len(payload) <= limit:
                return payload
        return None

    @staticmethod
    def _serialize_result(result: IntentResult) -> dict[str, Any]:
        """Serialize IntentResult for NATS reply.

        Shape only. Whether the shape can actually cross the wire is
        ``_reply_bytes``'s question — see there for why ``metadata`` is
        allowed to be dropped and ``result`` is not.

        BF-742: ``metadata`` is carried. AD-1203 put the per-turn tool-trace
        ref there and this omission dropped it on every NATS reply.
        """
        return {
            "intent_id": result.intent_id,
            "agent_id": result.agent_id,
            "success": result.success,
            "result": result.result,
            "error": result.error,
            "confidence": result.confidence,
            "timestamp": result.timestamp.isoformat(),
            "metadata": result.metadata,
        }

    @staticmethod
    def _encoded(payload: Any) -> bytes | None:
        """The bytes ``respond`` would send, or ``None`` if it cannot encode.

        Catches ``Exception``, not a chosen tuple. Encoding runs caller-supplied
        objects' own code: a deeply nested value raises ``RecursionError``
        (measured, and it took a valid answer down), and a ``dict`` subclass
        whose ``items()`` raises produces whatever it likes. The question here
        is only "will this encode", and every failure answers it the same way.
        """
        try:
            return json.dumps(payload).encode()
        except Exception:
            return None

    def _wire_limit(self) -> int:
        """Bytes the reply transport will accept, asked of the transport."""
        bus = getattr(self, "_nats_bus", None)
        limit = getattr(bus, "max_payload", None)
        if isinstance(limit, int) and limit > 0:
            return limit
        return DEFAULT_MAX_PAYLOAD_BYTES

    def _reply_budget(self, msg: Any) -> int:
        """Bytes left for THIS reply's body after its echoed headers.

        ``Msg.respond`` carries the request's headers onto the reply and the
        server counts them against the limit, so the body ceiling is
        per-message rather than global. A message that cannot say (a double
        without the accessor) falls back to the whole limit, which is the
        pre-BF-805 assumption.
        """
        limit = self._wire_limit()
        budget = getattr(msg, "reply_body_budget", None)
        if callable(budget):
            try:
                value = budget(limit)
            except Exception:
                return limit
            if isinstance(value, int) and value >= 0:
                return value
        return limit

    def _reply_bytes(
        self, result: IntentResult, limit: int | None = None
    ) -> bytes:
        """BF-805: a reply the wire will take, minus only what it will not.

        ``metadata`` is out-of-band provenance ABOUT the answer — AD-1203's
        ``tool_trace_ref``, AD-1248's ``dm_reply``. It must never be able to
        take the answer down with it. Measured through the real adapter: one
        ``object()`` under ``metadata["dm_reply"]`` turned a successful reply
        into ``success=False, result=None, error="Object of type object is not
        JSON serializable"``. The Captain lost the answer and was handed a
        serialization fault about their request instead. Measured against a
        live server: 1 MB of perfectly valid metadata did the same thing with
        ``nats: maximum payload exceeded``.

        Three properties, each of which cost a review round:

        **The answer is checked alone first.** If the envelope will not go even
        with no provenance attached, nothing here can rescue it, and pruning
        metadata would only produce a log claiming a delivery that never
        happened.

        **Keys are tested inside the real envelope, cumulatively.** A value can
        encode alone and still fail nested under ``metadata`` (recursion depth),
        and two values can each fit and together exceed the payload limit.
        Probing a key in a shallower or emptier envelope than the consumer
        receives answers a different question.

        **A metadata container that is not a mapping is dropped whole.** There
        are no keys to prune, and the answer is what matters.

        A ``result`` that cannot be encoded still raises, so the caller receives
        the error reply the handler-error branch builds. Fail fast is right for
        the answer and wrong for provenance.

        This is BF-799's judgement one layer down: the federation bridge already
        drops the disclosure and delivers the reply. A drop is recorded in the
        log and nowhere else — the receiver cannot distinguish "no provenance
        existed" from "provenance was dropped", which is the honest cost of not
        inventing a wire field nothing reads.

        Returns the BYTES, and the caller sends exactly these. Encoding again at
        the transport would let the check and the send see different artifacts
        — measured with a mapping whose ``items()`` succeeds once and then
        raises, which passed the check and destroyed the answer on the second
        encode, reproducing the very defect being fixed.
        """
        limit = self._wire_limit() if limit is None else limit
        payload = IntentBus._serialize_result(result)
        metadata = payload.get("metadata")
        mapping = isinstance(metadata, dict)
        if mapping:
            encoded = IntentBus._encoded(payload)
            if encoded is not None and len(encoded) <= limit:
                return encoded

        bare = dict(payload)
        bare["metadata"] = {}
        bare_bytes = IntentBus._encoded(bare)
        if bare_bytes is None:
            # The answer itself cannot be encoded. Encode it once more so the
            # caller sees the encoder's own error rather than a synthesised one,
            # and the handler-error branch builds the error reply.
            bare_bytes = json.dumps(bare).encode()
        if len(bare_bytes) > limit:
            # Returning it anyway would hand nats-py a body under its own guard
            # (which checks the body alone) and a FRAME the server refuses --
            # measured: it resets the responder connection asynchronously, so
            # the reply never fails locally and the caller simply times out
            # holding nothing. Raising here reaches the handler-error branch,
            # which sends a short reply the wire will actually take.
            raise ValueError(
                f"BF-805: the reply to intent {result.intent_id} is "
                f"{len(bare_bytes)} bytes with no provenance attached at all, "
                f"past the {limit}-byte body budget for this wire"
            )

        if not mapping:
            # A container that is not a mapping has no keys to prune, and
            # ``_deserialize_result`` would silently turn it into ``{}`` at the
            # far end anyway -- so a JSON-safe list crossed the wire and became
            # nothing, with no record that provenance had been lost.
            candidate_bytes: bytes = bare_bytes
            dropped = ["<metadata>"]
        else:
            try:
                kept, dropped = self._prune_metadata(
                    metadata, len(bare_bytes), limit
                )
            except Exception:
                # Naming or iterating the keys can itself raise -- a hostile
                # ``items()`` or a ``__str__`` that throws. The answer has
                # already proved sendable without provenance, so losing all of
                # it beats losing the answer to a pruning accident.
                logger.warning(
                    "BF-805: could not inspect the metadata on the reply to "
                    "intent %s; dropping it whole and delivering the answer",
                    result.intent_id, exc_info=True,
                )
                kept, dropped = {}, ["<metadata>"]
            candidate = dict(bare)
            candidate["metadata"] = kept
            assembled = IntentBus._encoded(candidate)
            if assembled is None or len(assembled) > limit:
                # Byte accounting cannot see a value that encodes at this depth
                # and fails one level deeper, so a key can survive the pass and
                # still sink the envelope. Fall back to no provenance at all
                # rather than announce a drop for something still unsendable.
                candidate_bytes = bare_bytes
                dropped = ["<metadata>"]
            else:
                candidate_bytes = assembled

        if not dropped:
            return candidate_bytes

        logger.warning(
            "BF-805: dropping metadata %s from the reply to intent %s by "
            "agent=%s — it does not fit the wire (unserializable, or past the "
            "%d-byte limit). The answer is kept and only this provenance is "
            "lost",
            dropped, result.intent_id, result.agent_id[:12], limit,
        )
        return candidate_bytes

    @staticmethod
    def _smallest_error_bytes(
        intent_id: str, error: str, limit: int
    ) -> bytes | None:
        """The shortest failure envelope that still fits, or ``None``.

        BF-805: when the echoed request headers eat the payload limit, even the
        synthesised error reply can be too big — and raising there hands the
        caller silence instead of a failure they can act on. Each candidate
        drops one more thing the far end can live without: ``_deserialize_result``
        reads every field with a defaulted ``.get()``, so ``{"success": false}``
        is a complete, correctly-shaped IntentResult carrying the one fact that
        matters.

        ``None`` means the budget will not take even eighteen bytes. Nothing can
        be sent, and the caller times out; the point of returning it rather than
        raising is that the caller of THIS method can say so in the log.
        """
        for candidate in (
            {"intent_id": intent_id, "success": False, "error": error[:200]},
            {"intent_id": intent_id, "success": False},
            {"success": False},
        ):
            encoded = IntentBus._encoded(candidate)
            if encoded is not None and len(encoded) <= limit:
                return encoded
        return None

    @staticmethod
    def _prune_metadata(
        metadata: dict[Any, Any], bare_bytes: int, limit: int
    ) -> tuple[dict[Any, Any], list[str]]:
        """Keep the metadata keys that still fit, in one linear pass.

        Each key is encoded ONCE as its own ``{"k": v}`` fragment and charged
        the bytes it would add inside the metadata object: the fragment less
        its braces, plus a separating comma after the first. Re-encoding the
        growing envelope per key instead was quadratic — measured at 0.85s for
        5,001 keys, synchronously inside the NATS callback, delaying every task
        on that event loop.

        Size accounting alone cannot see a value that encodes at this depth and
        fails one level deeper, so the caller still checks the assembled
        envelope once and falls back to dropping the container whole.

        Greedy in iteration order, so an early large key can starve later small
        ones. Tolerable while the known producers insert ``tool_trace_ref``
        before ``dm_reply`` and both are small; an explicit retention priority
        belongs here before a third field is added.
        """
        kept: dict[Any, Any] = {}
        dropped: list[str] = []
        room = limit - bare_bytes
        spent = 0
        for key, value in metadata.items():
            fragment = IntentBus._encoded({key: value})
            if fragment is None:
                dropped.append(str(key))
                continue
            # ``{"k": v}`` minus its own braces, plus the ``", "`` that joins
            # it to whatever is already kept. Two bytes, not one: measured, a
            # one-byte charge under-counted every key after the first, kept a
            # key that did not fit, and lost the whole container at the final
            # check -- including the earlier keys that would have fitted.
            cost = len(fragment) - 2 + (2 if kept else 0)
            if spent + cost <= room:
                kept[key] = value
                spent += cost
            else:
                dropped.append(str(key))
        return kept, dropped


    @staticmethod
    def _deserialize_result(data: dict[str, Any]) -> IntentResult:
        """Deserialize IntentResult from NATS reply."""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        else:
            ts = datetime.now(timezone.utc)
        metadata = data.get("metadata")
        return IntentResult(
            intent_id=data.get("intent_id", ""),
            agent_id=data.get("agent_id", ""),
            success=data.get("success", False),
            result=data.get("result"),
            error=data.get("error"),
            confidence=data.get("confidence", 0.0),
            timestamp=ts,
            metadata=metadata if isinstance(metadata, dict) else {},
        )
