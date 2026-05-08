"""AD-641g-1: ChainNATSConsumer — consumer-side foundation for the async cognitive pipeline.

Foundation cut. Pairs with the AD-641g publish-side bridge to provide a
clean subscription surface for downstream ADs (AD-644 cross-agent
situation awareness, AD-645 Phase 5 composition brief streaming, AD-647
process-chain step bridging).

Foundation only:
    * Wires ``js_subscribe`` to the COGNITIVE_CHAIN stream behind a
      simple ``register_handler(agent_id, step, phase, fn)`` API.
    * No executor flip — the synchronous chain remains the live path.
    * No replay / replay-aware consumer logic.
    * Disabled-by-default flag piggybacks on the existing
      ``SubTaskConfig.nats_publish_enabled`` toggle: if publish-side is
      off, consumer is off.

Engineering principle compliance:
    * Constructor injection (no globals, no late-bind).
    * ``enabled`` is a public property.
    * Subscriptions are tracked so ``stop()`` can drain.
    * Fire-and-forget dispatch holds task references and removes on
      completion to keep async hygiene tight.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from probos.cognitive.chain_subjects import (
    CHAIN_STREAM,
    chain_subject,
    chain_wildcard,
)
from probos.cognitive.sub_task import SubTaskType

if TYPE_CHECKING:
    from probos.mesh.nats_bus import MockNATSBus, NATSBus, NATSMessage

    NATSBusLike = NATSBus | MockNATSBus

logger = logging.getLogger(__name__)


# Handler signature: receives the decoded payload dict and returns awaitable
# (sync handlers wrapped automatically).
ChainStepHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


class ChainNATSConsumer:
    """Consumer-side foundation for ``chain.{agent}.{step}.{phase}`` subjects.

    Callers register handlers per (agent_id, step, phase) tuple; the
    consumer subscribes to the corresponding NATS subject (or wildcard)
    and dispatches inbound messages.
    """

    def __init__(self, *, nats_bus: "NATSBusLike | None", config: Any) -> None:
        self._nats_bus = nats_bus
        self._config = config
        self._dispatch_tasks: set[asyncio.Task[None]] = set()
        # Track subscriptions so stop() can drain.
        self._subscribed_subjects: list[str] = []
        # (agent_id, step_value, phase) -> list[handler]
        self._handlers: dict[tuple[str, str, str], list[ChainStepHandler]] = {}
        self._started = False

    @property
    def enabled(self) -> bool:
        cfg = self._config
        if not cfg or not getattr(cfg, "nats_publish_enabled", False):
            return False
        bus = self._nats_bus
        if bus is None:
            return False
        try:
            return bool(bus.connected)
        except Exception:
            return False

    def register_handler(
        self,
        *,
        agent_id: str = "*",
        step: SubTaskType | str = "*",
        phase: str = "complete",
        handler: ChainStepHandler,
    ) -> None:
        """Register a handler for a specific subject pattern.

        Use ``"*"`` to subscribe across all agents or all steps. The
        consumer must still be ``start()``-ed to actually subscribe.
        """
        step_str = step.value if isinstance(step, SubTaskType) else str(step)
        key = (str(agent_id) or "*", step_str or "*", phase or "complete")
        self._handlers.setdefault(key, []).append(handler)

    async def start(self) -> None:
        """Subscribe to NATS for every registered handler. Idempotent.

        No-op when the consumer is disabled (flag off OR NATS down).
        """
        if self._started:
            return
        if not self.enabled:
            # Mark started anyway so a subsequent start() while still
            # disabled stays a no-op; explicit stop() resets state.
            return
        bus = self._nats_bus
        if bus is None:
            return
        # Build a deduped set of subjects to subscribe to. We collapse
        # identical (agent_id, step, phase) tuples so multiple handlers
        # share one subscription.
        for (agent_id, step, phase), handlers in self._handlers.items():
            subject = self._build_subject(agent_id, step, phase)
            try:
                await bus.js_subscribe(
                    subject,
                    self._make_callback(agent_id, step, phase),
                    stream=CHAIN_STREAM,
                )
                self._subscribed_subjects.append(subject)
                logger.info(
                    "AD-641g-1: subscribed to %s with %d handler(s)",
                    subject,
                    len(handlers),
                )
            except Exception:
                logger.warning(
                    "AD-641g-1: failed to subscribe to %s; handlers inert",
                    subject,
                    exc_info=True,
                )
        self._started = True

    async def stop(self) -> None:
        """Drain in-flight dispatch tasks. Subscriptions remain in the
        bus until the bus itself is torn down — there's no per-handler
        unsubscribe in the current ``NATSBus`` surface.
        """
        if self._dispatch_tasks:
            await asyncio.gather(*self._dispatch_tasks, return_exceptions=True)
        self._started = False

    # ------------------------------------------------------------------

    def _build_subject(self, agent_id: str, step: str, phase: str) -> str:
        if agent_id == "*" or step == "*":
            return chain_wildcard(agent_id, step)
        return chain_subject(agent_id, step, phase)

    def _make_callback(
        self, agent_id_filter: str, step_filter: str, phase_filter: str
    ) -> Callable[..., Awaitable[None]]:
        async def _cb(msg: "NATSMessage") -> None:
            payload = msg.data if isinstance(msg.data, dict) else {}
            # Filter on phase even when wildcard subscription returned
            # other phases — wildcard "chain.*.*.>" catches start/error/complete.
            if phase_filter != "*" and payload.get("phase") and payload["phase"] != phase_filter:
                # Best effort: also accept subject suffix match.
                if not msg.subject.endswith(f".{phase_filter}"):
                    return
            key = (
                payload.get("agent_id", agent_id_filter),
                payload.get("step", step_filter),
                phase_filter,
            )
            await self._dispatch(key, payload)

        return _cb

    async def _dispatch(
        self,
        key: tuple[str, str, str],
        payload: dict[str, Any],
    ) -> None:
        # Match handlers on exact key OR with wildcard agent_id/step.
        matched: list[ChainStepHandler] = []
        for (a, s, p), hs in self._handlers.items():
            if (a, s, p) == key:
                matched.extend(hs)
                continue
            if (a == "*" or a == key[0]) and (s == "*" or s == key[1]) and (p == key[2]):
                matched.extend(hs)
        for fn in matched:
            try:
                result = fn(payload)
                if asyncio.iscoroutine(result):
                    task = asyncio.create_task(result)
                    self._dispatch_tasks.add(task)
                    task.add_done_callback(self._dispatch_tasks.discard)
            except Exception:
                logger.warning(
                    "AD-641g-1: chain handler raised on %s", key, exc_info=True,
                )
