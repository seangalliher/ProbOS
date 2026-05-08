"""AD-641g: ChainNATSBridge — publish-side foundation for the async cognitive pipeline.

Bridges the synchronous ``SubTaskExecutor`` to NATS JetStream by emitting a
lifecycle message after every chain step (success or failure). Foundation cut:
publish-side only — no consumer logic, no executor flip.

The synchronous chain remains the live execution path. NATS publishes are a
replayable observability trail and the schema contract that downstream ADs
(AD-644 SA, AD-645 P5 brief streaming, AD-647 process chains) consume.

Engineering principle compliance:
    * Constructor injection (no globals, no late-bind); ``enabled`` is a public
      property — callers never touch private attrs.
    * Fire-and-forget publishes hold task references and remove on completion
      so exceptions are not silently lost.
    * Publish failures degrade silently (log-and-degrade tier) — must never
      break the synchronous chain.
    * Full type annotations on every public method.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from probos.cognitive.chain_subjects import (
    CHAIN_STREAM,
    chain_stream_subjects,
    chain_subject,
)
from probos.cognitive.sub_task import SubTaskResult, SubTaskType

if TYPE_CHECKING:
    from probos.mesh.nats_bus import MockNATSBus, NATSBus

    NATSBusLike = NATSBus | MockNATSBus

logger = logging.getLogger(__name__)


_DEFAULT_PAYLOAD_MAX_BYTES = 16384  # 16 KB — protects JetStream from runaway result dicts


class ChainNATSBridge:
    """Publishes cognitive chain step lifecycle to NATS JetStream (AD-641g).

    Foundation-only: publish-side. Stream provisioning is idempotent and
    deferred to ``ensure_stream()`` (called once during startup finalize).
    """

    def __init__(self, *, nats_bus: "NATSBusLike | None", config: Any) -> None:
        self._nats_bus = nats_bus
        self._config = config
        self._publish_tasks: set[asyncio.Task[None]] = set()
        self._stream_ensured = False

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """True iff publish-side is wired AND NATS is currently connected."""
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

    @property
    def payload_max_bytes(self) -> int:
        cfg = self._config
        if cfg is None:
            return _DEFAULT_PAYLOAD_MAX_BYTES
        val = getattr(cfg, "nats_payload_max_bytes", _DEFAULT_PAYLOAD_MAX_BYTES)
        if isinstance(val, int) and val > 0:
            return val
        return _DEFAULT_PAYLOAD_MAX_BYTES

    # ------------------------------------------------------------------
    # Stream lifecycle
    # ------------------------------------------------------------------

    async def ensure_stream(self) -> None:
        """Provision the COGNITIVE_CHAIN JetStream stream. Idempotent.

        No-op when the bridge is disabled or the NATS bus is unavailable.
        """
        if self._stream_ensured:
            return
        if not self.enabled:
            return
        bus = self._nats_bus
        if bus is None or not hasattr(bus, "ensure_stream"):
            return
        try:
            await bus.ensure_stream(
                CHAIN_STREAM,
                chain_stream_subjects(),
            )
            self._stream_ensured = True
            logger.info(
                "AD-641g: provisioned JetStream stream %s for subjects %s",
                CHAIN_STREAM,
                chain_stream_subjects(),
            )
        except Exception:
            logger.warning(
                "AD-641g: failed to provision %s stream; chain publishes will degrade",
                CHAIN_STREAM,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Publish API (called by SubTaskExecutor)
    # ------------------------------------------------------------------

    def publish_step_complete(
        self,
        *,
        agent_id: str,
        step: SubTaskType,
        result: SubTaskResult,
        intent_id: str = "",
    ) -> None:
        """Fire-and-forget publish of a successful step result.

        Caller is the synchronous chain executor — must not raise. Disabled
        bridges return immediately with zero overhead.
        """
        if not self.enabled:
            return
        phase = "complete" if result.success else "error"
        subject = chain_subject(agent_id, step, phase)
        payload = self._build_payload(agent_id, step, result, intent_id, phase)
        self._dispatch(subject, payload)

    def publish_step_error(
        self,
        *,
        agent_id: str,
        step: SubTaskType,
        error: str,
        intent_id: str = "",
    ) -> None:
        """Publish an error event when a required step raises before producing a result."""
        if not self.enabled:
            return
        subject = chain_subject(agent_id, step, "error")
        payload = {
            "agent_id": agent_id,
            "step": step.value,
            "name": "",
            "intent_id": intent_id,
            "ok": False,
            "duration_ms": 0.0,
            "error": (error or "")[:500],
            "result": {},
            "ts": time.time(),
        }
        self._dispatch(subject, payload)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        agent_id: str,
        step: SubTaskType,
        result: SubTaskResult,
        intent_id: str,
        phase: str,
    ) -> dict[str, Any]:
        result_dict = result.result if isinstance(result.result, dict) else {}
        payload: dict[str, Any] = {
            "agent_id": agent_id,
            "step": step.value,
            "name": result.name,
            "intent_id": intent_id,
            "ok": bool(result.success),
            "phase": phase,
            "duration_ms": float(result.duration_ms or 0.0),
            "tokens_used": int(result.tokens_used or 0),
            "tier_used": result.tier_used or "",
            "error": (result.error or "")[:500],
            "result": result_dict,
            "ts": time.time(),
        }
        # Truncate oversized payloads. We measure the JSON-encoded size of the
        # inner result dict because that is the unbounded handler-controlled
        # field; envelope keys are bounded.
        try:
            encoded = json.dumps(result_dict).encode("utf-8")
        except (TypeError, ValueError):
            payload["result"] = {
                "truncated": True,
                "reason": "non-serializable",
            }
            return payload
        cap = self.payload_max_bytes
        if len(encoded) > cap:
            logger.warning(
                "AD-641g: chain payload for agent=%s step=%s oversize (%d > %d); truncating",
                agent_id,
                step.value,
                len(encoded),
                cap,
            )
            payload["result"] = {
                "truncated": True,
                "size": len(encoded),
                "max_bytes": cap,
            }
        return payload

    def _dispatch(self, subject: str, payload: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — drop the message rather than raise. The sync
            # chain must remain decoupled from event-loop availability.
            return
        task = loop.create_task(self._safe_publish(subject, payload))
        self._publish_tasks.add(task)
        task.add_done_callback(self._publish_tasks.discard)

    async def _safe_publish(self, subject: str, payload: dict[str, Any]) -> None:
        bus = self._nats_bus
        if bus is None:
            return
        try:
            await bus.js_publish(subject, payload)
        except Exception:
            logger.warning(
                "AD-641g: chain publish to %s failed; dropping", subject, exc_info=True
            )
