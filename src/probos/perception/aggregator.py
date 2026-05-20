"""AD-746 Layer 1 — VisionAggregator (Pipecat-style debounce fusion).

Inserts between the source admitters (``perception/camera/frame`` for
both camera + screen) and the existing ``VisionConsumer._handle``.

Behavior:

  - Subscribes to ``vision_observation`` on the intent bus when wired.
    When wired, the consumer's own ``subscribe()`` MUST NOT be called
    (the aggregator is the consumer's bus front-end).
  - Per-session, on each frame the aggregator opens an N-ms debounce
    window (``fusion_window_ms``, default 800). If a frame from the
    OTHER source arrives within the window, the two are forwarded to
    the consumer as a single fused message with:

       params["attachment_refs"]: list[str]   # in arrival order
       params["attachment_ref"]:  primary     # arrived first
       params["sources"]:         list[str]   # parallel to refs
       params["source"]:          primary src # legacy alias
       params["fused"]:           True

    The consumer treats the fused message as ONE vision-tier call
    (AD-733c-6 budget invariant).

  - If the window expires with only one frame, the buffered message is
    forwarded UNCHANGED — legacy single-source contract preserved.

  - When ``source_fusion_enabled=False`` the aggregator is bypassed at
    wiring time (``VisionConsumer.subscribe()`` is called directly).

AD-731 invariant: refs only. The aggregator NEVER touches frame bytes
— it composes intent messages with content-addressable SHA refs only.

AD-541b: the consumer's anchor record carries ``sources: list[str]``
for both passthrough (single-element list) and fused (multi-element)
frames.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from probos.types import IntentMessage, IntentResult

if TYPE_CHECKING:
    from probos.perception.consumer import VisionConsumer

logger = logging.getLogger(__name__)


class VisionAggregator:
    """Buffer + fuse vision_observation frames within a debounce window."""

    INTENT_NAME = "vision_observation"
    SUBSCRIBER_AGENT_ID = "perception.vision_aggregator"

    def __init__(
        self,
        runtime: Any,
        consumer: "VisionConsumer",
        *,
        fusion_window_ms: int = 800,
    ) -> None:
        if fusion_window_ms < 100 or fusion_window_ms > 5000:
            raise ValueError(
                f"fusion_window_ms must be in [100, 5000]; got {fusion_window_ms}"
            )
        self._runtime = runtime
        self._consumer = consumer
        self._window_s = fusion_window_ms / 1000.0
        # Per-session buffered frame + arming task. Each session can
        # hold at most one pending frame; when the second source
        # arrives within the window, we fuse and forward; on timeout,
        # we forward the single pending frame.
        self._pending: dict[str, IntentMessage] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    def subscribe(self) -> None:
        """Register the aggregator on the intent bus. The consumer's own
        subscribe() must NOT be called when the aggregator is wired —
        the aggregator owns forwarding."""
        self._runtime.intent_bus.subscribe(
            self.SUBSCRIBER_AGENT_ID,
            self._handle,
            intent_names=[self.INTENT_NAME],
        )
        logger.info(
            "AD-746 Layer 1: VisionAggregator subscribed to %s (window=%dms)",
            self.INTENT_NAME, int(self._window_s * 1000),
        )

    async def _handle(self, msg: IntentMessage) -> IntentResult | None:
        if msg.intent != self.INTENT_NAME:
            return None
        # ``fused`` is the aggregator's own re-emit guard — passthrough
        # the message verbatim. Should never appear on inbound bus
        # messages from camera/screen frame uploads but defense-in-depth.
        if msg.params.get("fused", False):
            await self._forward(msg)
            return None

        session_id = str(msg.params.get("session_id", ""))
        if not session_id:
            # No session_id ⇒ no debounce key; pass through.
            await self._forward(msg)
            return None

        async with self._lock:
            pending = self._pending.get(session_id)
            if pending is None:
                # No buffered frame — buffer this one and start a timer.
                self._pending[session_id] = msg
                self._timers[session_id] = asyncio.create_task(
                    self._expire_window(session_id, msg)
                )
                self._timers[session_id].add_done_callback(
                    lambda t, sid=session_id: self._timers.pop(sid, None)
                    if self._timers.get(sid) is t else None
                )
                return None
            # A frame is already buffered. If it's a different source,
            # fuse and forward. If it's the same source, the second
            # frame REPLACES the first (most-recent-wins per-source);
            # the timer continues against the original arrival time so
            # an opposing-source frame still has a chance to fuse.
            pending_source = str(pending.params.get("source", "camera"))
            new_source = str(msg.params.get("source", "camera"))
            if pending_source == new_source:
                # Replace; keep timer.
                self._pending[session_id] = msg
                return None
            # Different source — fuse and forward.
            fused = self._build_fused_message(pending, msg)
            # Cancel the timer and clear state BEFORE awaiting the
            # forward so a concurrent expire_window can't double-fire.
            timer = self._timers.pop(session_id, None)
            self._pending.pop(session_id, None)
            if timer is not None and not timer.done():
                timer.cancel()
        await self._forward(fused)
        return None

    async def _expire_window(self, session_id: str, msg: IntentMessage) -> None:
        """Timer: when the debounce window expires, forward the buffered
        frame UNCHANGED (single-source passthrough)."""
        try:
            await asyncio.sleep(self._window_s)
        except asyncio.CancelledError:
            return
        async with self._lock:
            pending = self._pending.get(session_id)
            # Only forward if THIS message is still the pending one
            # (replacement under the lock means a later frame won the
            # slot — the later frame's timer owns the forward).
            if pending is not msg:
                return
            self._pending.pop(session_id, None)
        await self._forward(msg)

    def _build_fused_message(
        self, first: IntentMessage, second: IntentMessage,
    ) -> IntentMessage:
        """Compose a fused intent message from two source frames.

        Preserves ``first`` as the primary (legacy single-ref / single-
        source fields). Adds parallel ``attachment_refs`` + ``sources``
        lists in arrival order. Sets ``fused=True``.
        """
        first_ref = str(first.params.get("attachment_ref", ""))
        second_ref = str(second.params.get("attachment_ref", ""))
        first_source = str(first.params.get("source", "camera"))
        second_source = str(second.params.get("source", "camera"))
        # Inherit first's params shape; override with fused fields.
        fused_params: dict[str, Any] = dict(first.params)
        fused_params["attachment_refs"] = [first_ref, second_ref]
        fused_params["attachment_ref"] = first_ref  # primary alias
        fused_params["sources"] = [first_source, second_source]
        fused_params["source"] = first_source  # legacy alias (AD-746-5)
        fused_params["fused"] = True
        fused_params["fused_at"] = time.time()
        return IntentMessage(intent=self.INTENT_NAME, params=fused_params)

    async def _forward(self, msg: IntentMessage) -> None:
        """Forward to the wired VisionConsumer's _handle. Passthrough
        messages reach the consumer's full pipeline unchanged; fused
        messages carry their list refs through to the LLM call site."""
        try:
            await self._consumer._handle(msg)
        except Exception:
            logger.warning(
                "AD-746: VisionAggregator forward failed (session=%s)",
                str(msg.params.get("session_id", ""))[:8],
                exc_info=True,
            )

    async def stop(self) -> None:
        """Cancel pending timers (test + shutdown hygiene)."""
        timers = list(self._timers.values())
        self._timers.clear()
        self._pending.clear()
        for t in timers:
            if not t.done():
                t.cancel()
        for t in timers:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


__all__ = ["VisionAggregator"]
