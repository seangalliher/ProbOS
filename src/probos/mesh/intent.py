"""Intent bus — broadcast intents, agents self-select, collect results."""

from __future__ import annotations

import asyncio
import time
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Awaitable

from probos.types import IntentMessage, IntentResult
from probos.mesh.signal import SignalManager

if TYPE_CHECKING:
    from probos.mesh.nats_bus import NATSBus

logger = logging.getLogger(__name__)

# Type for subscriber callbacks
IntentHandler = Callable[[IntentMessage], Awaitable[IntentResult | None]]


class IntentBus:
    """Async pub/sub for intent broadcasting.

    Agents subscribe with a handler. When an intent is broadcast,
    all subscribers are notified concurrently. Each subscriber decides
    whether to respond (self-selection). Results are collected with
    a configurable timeout.
    """

    def __init__(self, signal_manager: SignalManager) -> None:
        self._signal_manager = signal_manager
        self._subscribers: dict[str, IntentHandler] = {}  # agent_id -> handler
        self._intent_index: dict[str, set[str]] = {}  # intent_name -> set of agent_ids
        self._pending_results: dict[str, list[IntentResult]] = {}  # intent_id -> results
        self._result_events: dict[str, asyncio.Event] = {}
        self._broadcast_timestamps: list[tuple[float, str]] = []  # (monotonic_time, intent_name)
        self._window_seconds: float = 60.0
        self._federation_fn: Callable[[IntentMessage], Awaitable[list[IntentResult]]] | None = None
        self._nats_bus: Any = None  # AD-637b: wired via set_nats_bus()
        self._pending_sub_tasks: set[asyncio.Task] = set()  # AD-637z: tracked NATS sub tasks

    def subscribe(self, agent_id: str, handler: IntentHandler, intent_names: list[str] | None = None) -> None:
        """Register an agent's intent handler.

        If intent_names is provided, the agent is indexed for those intents
        and will only be invoked when a matching intent is broadcast.
        Agents subscribed without intent_names receive all broadcasts (fallback).
        """
        self._subscribers[agent_id] = handler
        if intent_names:
            for name in intent_names:
                if name not in self._intent_index:
                    self._intent_index[name] = set()
                self._intent_index[name].add(agent_id)

        # AD-637b/z: Create NATS subscription for targeted send()
        if self._nats_bus and self._nats_bus.connected:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    self._nats_subscribe_agent(agent_id, handler),
                    name=f"nats-sub-{agent_id[:12]}",
                )
                self._pending_sub_tasks.add(task)
                task.add_done_callback(self._pending_sub_tasks.discard)
                task.add_done_callback(self._on_nats_task_done)
                # AD-654a: Also subscribe to JetStream dispatch subject
                dispatch_task = loop.create_task(
                    self._js_subscribe_agent_dispatch(agent_id, handler),
                    name=f"js-dispatch-sub-{agent_id[:12]}",
                )
                self._pending_sub_tasks.add(dispatch_task)
                dispatch_task.add_done_callback(self._pending_sub_tasks.discard)
                dispatch_task.add_done_callback(self._on_nats_task_done)
            except RuntimeError:
                pass

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
                        await msg.respond(self._serialize_result(result))
                    else:
                        # Agent declined — send empty success response
                        await msg.respond({"declined": True})
            except Exception as e:
                logger.warning("NATS intent handler error for %s: %s", agent_id[:8], e)
                if msg.reply:
                    error_result = IntentResult(
                        intent_id=msg.data.get("id", "") if isinstance(msg.data, dict) else "",
                        agent_id=agent_id,
                        success=False,
                        error=str(e),
                        confidence=0.0,
                    )
                    await msg.respond(self._serialize_result(error_result))

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
            """JetStream dispatch callback — deserialize and handle.

            Uses manual ack: ack() on success, term() on error.
            """
            try:
                intent = self._deserialize_intent(msg.data)
                # AD-654a/BF-198: Record response BEFORE handler runs to close
                # the proactive-loop race window.
                _rt_ref = getattr(handler, "__self__", None)
                if _rt_ref and hasattr(_rt_ref, "_runtime"):
                    _rt = _rt_ref._runtime
                    _router = getattr(_rt, "ward_room_router", None)
                    _thread_id = intent.params.get("thread_id", "")
                    if _router and _thread_id:
                        _router.record_agent_response(intent.target_agent_id, _thread_id)
                await handler(intent)
                await msg.ack()
            except Exception as e:
                logger.warning(
                    "AD-654a: Dispatch handler error for %s: %s",
                    agent_id[:8], e,
                )
                # term() = permanently reject. Do NOT nak() — cognitive chains
                # must not be retried (LLM already ran, would cause duplicates).
                await msg.term()

        # Durable name must be NATS-safe (alphanumeric + dash).
        durable_name = f"agent-dispatch-{agent_id}"

        sub = await self._nats_bus.js_subscribe(
            subject,
            _on_dispatch,
            durable=durable_name,
            stream="INTENT_DISPATCH",
            max_ack_pending=1,
            ack_wait=300,
            manual_ack=True,
        )
        if sub:
            logger.debug("AD-654a: JetStream dispatch consumer for %s", agent_id[:12])

    def unsubscribe(self, agent_id: str) -> None:
        """Remove an agent's subscription and intent index entries."""
        self._subscribers.pop(agent_id, None)
        for agent_set in self._intent_index.values():
            agent_set.discard(agent_id)
        # AD-637z: Clean up NATS subscription via NATSBus lifecycle management
        if self._nats_bus:
            subject = f"intent.{agent_id}"
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    self._nats_bus.remove_tracked_subscription(subject),
                    name=f"nats-unsub-{agent_id[:12]}",
                )
                self._pending_sub_tasks.add(task)
                task.add_done_callback(self._pending_sub_tasks.discard)
                task.add_done_callback(self._on_nats_task_done)
            except RuntimeError:
                pass
            # AD-654a: Clean up JetStream dispatch consumer
            durable_name = f"agent-dispatch-{agent_id}"
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._nats_bus.delete_consumer("INTENT_DISPATCH", durable_name),
                    name=f"cleanup-dispatch-{agent_id[:12]}",
                )
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

    async def send(self, intent: IntentMessage) -> IntentResult | None:
        """Deliver an intent to a specific agent (targeted dispatch, AD-397).

        AD-637b: Uses NATS request/reply when connected, direct-call fallback otherwise.
        Only one path is used per call — never both.

        AD-637z: BF-221 lifted. Prefix re-subscription (set_subject_prefix)
        ensures NATS subscriptions survive the Phase 7 DID assignment.
        """
        if not intent.target_agent_id:
            raise ValueError("send() requires target_agent_id")

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
    ) -> list[IntentResult]:
        """Broadcast an intent to all subscribers, collect results.

        Each subscriber is called concurrently. Subscribers that return
        None are treated as having declined the intent (self-deselected).
        Waits up to `timeout` seconds (defaults to intent TTL) for results.

        If intent.target_agent_id is set, delegates to send() for targeted dispatch.
        """
        # AD-397: targeted dispatch
        if intent.target_agent_id:
            result = await self.send(intent)
            return [result] if result else []

        timeout = timeout if timeout is not None else intent.ttl_seconds

        self.record_broadcast(intent.intent)
        self._signal_manager.track(intent)
        self._pending_results[intent.id] = []

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
                aid: handler
                for aid, handler in self._subscribers.items()
                if aid in indexed_agents or aid not in all_indexed
            }
        else:
            # No index entry: fall back to all subscribers
            candidates = dict(self._subscribers)

        # Fan out to selected subscribers concurrently
        tasks = []
        for agent_id, handler in list(candidates.items()):
            tasks.append(
                asyncio.create_task(
                    self._invoke_handler(intent, agent_id, handler),
                    name=f"intent-{intent.id[:8]}-{agent_id[:8]}",
                )
            )

        if tasks:
            # Wait for all handlers, bounded by timeout
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            # Cancel stragglers
            for task in pending:
                task.cancel()

        results = self._pending_results.pop(intent.id, [])
        self._signal_manager.untrack(intent.id)

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

    async def dispatch_async(self, intent: IntentMessage) -> None:
        """Fire-and-forget dispatch to a specific agent via JetStream (AD-654a).

        Publishes the intent to the agent's durable JetStream consumer.
        No reply expected — the agent processes asynchronously and posts
        its own response. Falls back to direct async handler invocation
        when NATS/JetStream is unavailable.

        Requires intent.target_agent_id to be set.
        """
        if not intent.target_agent_id:
            raise ValueError("dispatch_async() requires target_agent_id")

        # JetStream path when connected
        if self._nats_bus and self._nats_bus.connected:
            subject = f"intent.dispatch.{intent.target_agent_id}"
            try:
                await self._nats_bus.js_publish(subject, self._serialize_intent(intent))
                logger.debug(
                    "AD-654a: Dispatched %s → %s via JetStream",
                    intent.intent, intent.target_agent_id[:12],
                )
                return
            except Exception as e:
                logger.warning(
                    "AD-654a: JetStream dispatch failed for %s → %s: %s, falling back to direct",
                    intent.intent, intent.target_agent_id[:12], e,
                )
                # Fall through to direct dispatch

        # Direct-call fallback when NATS/JetStream unavailable
        handler = self._subscribers.get(intent.target_agent_id)
        if handler is None:
            logger.debug("AD-654a: No handler for %s, dropping", intent.target_agent_id[:12])
            return

        # Soft cap on pending fallback tasks to prevent unbounded growth
        _MAX_PENDING_TASKS = 200
        if len(self._pending_sub_tasks) >= _MAX_PENDING_TASKS:
            logger.warning(
                "AD-654a: Pending task cap (%d) reached, dropping dispatch for %s",
                _MAX_PENDING_TASKS, intent.target_agent_id[:12],
            )
            return

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
        self._pending_sub_tasks.add(task)
        task.add_done_callback(self._pending_sub_tasks.discard)

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
    ) -> None:
        """Invoke a single subscriber's handler, catching errors."""
        try:
            t0 = time.monotonic()
            result = await handler(intent)
            elapsed_ms = (time.monotonic() - t0) * 1000
            if elapsed_ms > 100:
                logger.warning(
                    "Slow handler: agent=%s intent=%s elapsed=%.0fms result=%s",
                    agent_id[:16], intent.intent, elapsed_ms,
                    "responded" if result else "declined",
                )
            if result is not None:
                # Agent accepted and responded
                if intent.id in self._pending_results:
                    self._pending_results[intent.id].append(result)
        except Exception as e:
            logger.warning(
                "Handler error for agent %s on intent %s: %s",
                agent_id[:8],
                intent.id[:8],
                e,
            )
            # Record the failure as a result
            if intent.id in self._pending_results:
                self._pending_results[intent.id].append(
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
    # AD-637b: Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_intent(intent: IntentMessage) -> dict[str, Any]:
        """Serialize IntentMessage for NATS transport.

        All fields must be JSON-serializable. params dict values that are
        not JSON-serializable will raise TypeError — fail fast.
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
        )

    @staticmethod
    def _serialize_result(result: IntentResult) -> dict[str, Any]:
        """Serialize IntentResult for NATS reply.

        result.result must be JSON-serializable. Non-serializable values
        will raise TypeError — this is intentional (fail fast). Handlers
        using the NATS path must return serializable results.
        """
        return {
            "intent_id": result.intent_id,
            "agent_id": result.agent_id,
            "success": result.success,
            "result": result.result,
            "error": result.error,
            "confidence": result.confidence,
            "timestamp": result.timestamp.isoformat(),
        }

    @staticmethod
    def _deserialize_result(data: dict[str, Any]) -> IntentResult:
        """Deserialize IntentResult from NATS reply."""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        else:
            ts = datetime.now(timezone.utc)
        return IntentResult(
            intent_id=data.get("intent_id", ""),
            agent_id=data.get("agent_id", ""),
            success=data.get("success", False),
            result=data.get("result"),
            error=data.get("error"),
            confidence=data.get("confidence", 0.0),
            timestamp=ts,
        )
