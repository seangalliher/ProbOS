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
        self._nats_subs: dict[str, Any] = {}  # agent_id -> NATS subscription

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

        # AD-637b: Create NATS subscription for targeted send()
        if self._nats_bus and self._nats_bus.connected:
            asyncio.ensure_future(self._nats_subscribe_agent(agent_id, handler))

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
        self._nats_subs[agent_id] = sub

    def unsubscribe(self, agent_id: str) -> None:
        """Remove an agent's subscription and intent index entries."""
        self._subscribers.pop(agent_id, None)
        for agent_set in self._intent_index.values():
            agent_set.discard(agent_id)
        # AD-637b: Clean up NATS subscription
        nats_sub = self._nats_subs.pop(agent_id, None)
        if nats_sub and hasattr(nats_sub, 'unsubscribe'):
            asyncio.ensure_future(self._nats_unsubscribe(nats_sub))

    async def _nats_unsubscribe(self, sub: Any) -> None:
        """Unsubscribe from NATS subject."""
        try:
            await sub.unsubscribe()
        except Exception as e:
            logger.debug("NATS unsubscribe error: %s", e)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def send(self, intent: IntentMessage) -> IntentResult | None:
        """Deliver an intent to a specific agent (targeted dispatch, AD-397).

        AD-637b: Uses NATS request/reply when connected, direct-call fallback otherwise.
        Only one path is used per call — never both.
        """
        if not intent.target_agent_id:
            raise ValueError("send() requires target_agent_id")

        # AD-637b: NATS path (when connected and agent has NATS subscription)
        if (self._nats_bus and self._nats_bus.connected
                and intent.target_agent_id in self._nats_subs):
            return await self._nats_send(intent)

        # Direct-call fallback (original behavior, also used when NATS unavailable)
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
                self._nats_bus.request(subject, self._serialize_intent(intent)),
                timeout=intent.ttl_seconds,
            )
        except asyncio.TimeoutError:
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
