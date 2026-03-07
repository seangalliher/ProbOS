"""Intent bus — broadcast intents, agents self-select, collect results."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from probos.types import IntentMessage, IntentResult
from probos.mesh.signal import SignalManager

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
        self._pending_results: dict[str, list[IntentResult]] = {}  # intent_id -> results
        self._result_events: dict[str, asyncio.Event] = {}

    def subscribe(self, agent_id: str, handler: IntentHandler) -> None:
        """Register an agent's intent handler."""
        self._subscribers[agent_id] = handler

    def unsubscribe(self, agent_id: str) -> None:
        """Remove an agent's subscription."""
        self._subscribers.pop(agent_id, None)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def broadcast(
        self,
        intent: IntentMessage,
        timeout: float | None = None,
    ) -> list[IntentResult]:
        """Broadcast an intent to all subscribers, collect results.

        Each subscriber is called concurrently. Subscribers that return
        None are treated as having declined the intent (self-deselected).
        Waits up to `timeout` seconds (defaults to intent TTL) for results.
        """
        timeout = timeout if timeout is not None else intent.ttl_seconds

        self._signal_manager.track(intent)
        self._pending_results[intent.id] = []

        logger.info(
            "Intent broadcast: %s id=%s urgency=%.1f subscribers=%d",
            intent.intent,
            intent.id[:8],
            intent.urgency,
            len(self._subscribers),
        )

        # Fan out to all subscribers concurrently
        tasks = []
        for agent_id, handler in list(self._subscribers.items()):
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

        logger.info(
            "Intent resolved: %s id=%s results=%d",
            intent.intent,
            intent.id[:8],
            len(results),
        )
        return results

    async def _invoke_handler(
        self,
        intent: IntentMessage,
        agent_id: str,
        handler: IntentHandler,
    ) -> None:
        """Invoke a single subscriber's handler, catching errors."""
        try:
            result = await handler(intent)
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
