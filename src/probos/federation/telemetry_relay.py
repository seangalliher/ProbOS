"""AD-722b-5 (Wave 162): federation cross-mesh telemetry push relay.

**Local-mesh portion only.** The federation hop is forward-marked
(AD-722b-5a) — `FederationBridge` currently exposes only `forward_intent`
(single-shot RPC); no streaming/relay primitive exists. This module ships
the **subscription + rate-limit + dispatch table** that the future
streaming primitive will plug into. When AD-480e/g matures the bridge
with a streaming surface, the only change required here is to replace the
``_emit_to_peer`` stub with the real ``bridge.forward_telemetry`` call.

Design doc placeholder: ``docs/development/federation-streaming.md`` (not
authored in this AD — its scope is the bridge protocol, not the relay).
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PeerTelemetrySubscription:
    peer_id: str
    agent_ids: frozenset[str]


class FederationTelemetryRelay:
    """Subscribes peer meshes to local telemetry frames by agent_id.

    Wave 162 ships the LOCAL plumbing: subscription registration, per-peer
    outbound rate-limit, agent_id filtering, and frame dispatch through a
    pluggable ``_emit_to_peer`` callback. The default callback is a no-op
    that records to an in-memory dispatch log (test-observable).

    When AD-480e/g lands the streaming primitive, ``set_emit_callback`` is
    wired to the bridge — this module needs zero changes.
    """

    def __init__(
        self,
        *,
        max_per_sec_per_peer: int = 10,
    ) -> None:
        self._subs: dict[str, PeerTelemetrySubscription] = {}
        self._rate: dict[str, deque[float]] = {}
        self._max_per_sec = int(max_per_sec_per_peer)
        self._dispatch_log: list[tuple[str, str, dict]] = []
        self._emit_callback = self._default_emit

    def register_peer(self, peer_id: str, agent_ids: list[str]) -> None:
        """Register a peer mesh's subscription to local agent telemetry.

        Empty ``agent_ids`` registers a peer with zero subscriptions
        (no frames emitted). Re-registration replaces the prior set.
        """
        self._subs[peer_id] = PeerTelemetrySubscription(
            peer_id=peer_id, agent_ids=frozenset(agent_ids),
        )
        logger.info(
            "AD-722b-5: peer %s registered with %d agent subscriptions",
            peer_id, len(agent_ids),
        )

    def unregister_peer(self, peer_id: str) -> None:
        self._subs.pop(peer_id, None)
        self._rate.pop(peer_id, None)

    def set_emit_callback(self, callback) -> None:
        """Wire the actual transport. AD-722b-5a hookup point — replace
        the default in-memory logger with ``bridge.forward_telemetry``
        once the federation streaming primitive ships.
        """
        self._emit_callback = callback

    async def on_local_telemetry_frame(
        self,
        *,
        agent_id: str,
        frame_type: str,
        payload: dict,
    ) -> int:
        """Dispatch a local telemetry frame to subscribed peers.

        Returns the number of peers that received the frame (excluding
        rate-limited drops). NEVER raises - per-peer emit failures log
        and degrade.
        """
        dispatched = 0
        for peer_id, sub in self._subs.items():
            if agent_id not in sub.agent_ids:
                continue
            if not self._under_rate_limit(peer_id):
                logger.debug(
                    "AD-722b-5: rate-limited peer=%s agent_id=%s frame_type=%s",
                    peer_id, agent_id, frame_type,
                )
                continue
            try:
                await self._emit_callback(peer_id, agent_id, frame_type, payload)
                self._note_emit(peer_id)
                dispatched += 1
            except Exception:
                logger.warning(
                    "AD-722b-5: emit failed peer=%s agent_id=%s",
                    peer_id, agent_id, exc_info=True,
                )
        return dispatched

    def dispatch_log(self) -> list[tuple[str, str, dict]]:
        """Test helper: snapshot of frames dispatched via the default callback."""
        return list(self._dispatch_log)

    def reset_dispatch_log(self) -> None:
        self._dispatch_log.clear()

    def _under_rate_limit(self, peer_id: str) -> bool:
        now = time.time()
        window = self._rate.setdefault(peer_id, deque())
        cutoff = now - 1.0
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) < self._max_per_sec

    def _note_emit(self, peer_id: str) -> None:
        self._rate.setdefault(peer_id, deque()).append(time.time())

    async def _default_emit(
        self,
        peer_id: str,
        agent_id: str,
        frame_type: str,
        payload: dict,
    ) -> None:
        """Test-only callback: records dispatch shape to an in-memory log."""
        self._dispatch_log.append((peer_id, agent_id, {
            "type": frame_type,
            "payload": payload,
        }))
