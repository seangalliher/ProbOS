"""AD-843c-1: device.notify actuation governance loop (brain->limb) (#818).

Wires the AD-843a/b device tier into a single, bus-agnostic service that
completes the NON-consensus actuation loop for ``device.notify``::

    authorize -> actuate(NoOp) -> record trust -> store episode

``DeviceNodeService`` is constructor-injected (mirrors ``AgentGroupChatService``):
it owns the ``DeviceNodeRegistry`` + a ``DeviceNodeAdapter`` and receives the
``TrustNetwork`` (typed ``Any`` -- the trust Protocol lacks ``record_outcome``)
plus episodic memory via a late-bind provider (episodic is created after the
runtime ``__init__`` that constructs this service).

The sensitive consensus intents (``device.location`` / ``device.camera`` /
``device.screen``) are NOT handled here -- they are AD-843c-2 and remain
UNREACHABLE in c-1 (``handle_intent`` returns ``None`` for them). There is no
governance bypass: a one-shot non-consensus path cannot reach the sensitive
intents, which still require the deferred consensus gate.

Layer discipline: substrate. Imports ONLY ``probos.substrate.device_node`` +
``probos.types`` + stdlib. NO consensus/cognitive/mesh/federation/runtime
imports (trust is ``Any``; episodic flows through a ``Callable`` provider).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from probos.substrate.device_node import DeviceNodeAdapter, DeviceNodeRegistry
from probos.types import AnchorFrame, Episode, IntentMessage, IntentResult

logger = logging.getLogger(__name__)

DEVICE_NODE_SERVICE_ID = "device_node_service"


class DeviceNodeService:
    """AD-843c-1: device.notify actuation governance loop (brain->limb).

    Constructor-injected, bus-agnostic. Owns the registry + adapter; the
    TrustNetwork (Any -- the Protocol lacks record_outcome) and episodic
    memory (late-bind provider) are injected -- substrate stays clean.
    """

    def __init__(
        self,
        *,
        registry: DeviceNodeRegistry,
        adapter: DeviceNodeAdapter,
        trust_network: Any | None = None,
        episodic_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._registry = registry
        self._adapter = adapter
        self._trust_network = trust_network
        self._episodic_provider = episodic_provider

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        # c-1 handles ONLY device.notify; the consensus intents
        # (device.location/camera/screen) are AD-843c-2 and unreachable here.
        if intent.intent != "device.notify":
            return None
        device_id = str(intent.params.get("device_id", ""))

        authorized, reason = self._registry.authorize(device_id, intent.intent)
        if not authorized:
            result = IntentResult(
                intent_id=intent.id,
                agent_id=f"device:{device_id}",
                success=False,
                error=reason,
                confidence=0.0,
            )
            await self._store_episode(
                intent, device_id, authorized=False, success=False, reason=reason
            )
            return result

        device = self._registry.get_device(device_id)
        if device is None:
            # BF-652: fail CLOSED, never -O-strippable. authorize() should imply
            # the device exists, but a race (unpair between authorize and get)
            # must not fall through to actuate(None). No actuation attempted =>
            # no trust record. Mirrors the consensus path's device_missing guard
            # (runtime.submit_device_actuate_with_consensus).
            logger.warning(
                "BF-652: device %s passed authorize() but is absent from the "
                "registry; failing closed (no actuation, no trust write)",
                device_id,
            )
            await self._store_episode(
                intent, device_id, authorized=True, success=False, reason="device_missing"
            )
            return IntentResult(
                intent_id=intent.id,
                agent_id=f"device:{device_id}",
                success=False,
                error="device_missing",
                confidence=0.0,
            )
        result = await self._adapter.actuate(device, intent)

        if self._trust_network is not None and device.trust_record_id:
            try:
                self._trust_network.record_outcome(
                    device.trust_record_id,
                    success=result.success,
                    intent_type=intent.intent,
                    source="device",
                )
            except Exception:
                logger.warning(
                    "AD-843c-1: trust record_outcome failed for %s",
                    device.trust_record_id,
                    exc_info=True,
                )

        await self._store_episode(
            intent, device_id, authorized=True, success=result.success, reason=""
        )
        return result

    async def _store_episode(
        self,
        intent: IntentMessage,
        device_id: str,
        *,
        authorized: bool,
        success: bool,
        reason: str,
    ) -> None:
        episodic = self._episodic_provider() if self._episodic_provider else None
        if episodic is None:
            return
        try:
            episode = Episode(
                user_input=f"[device] {intent.intent} -> {device_id}",
                timestamp=time.time(),
                agent_ids=[f"device:{device_id}"] if device_id else [],
                outcomes=[
                    {
                        "kind": "device_actuate",
                        "intent": intent.intent,
                        "device_id": device_id,
                        "authorized": authorized,
                        "success": success,
                        "reason": reason,
                    }
                ],
                dag_summary={},
                anchors=AnchorFrame(channel="device", trigger_type=intent.intent),
            )
            await episodic.store(episode)
        except Exception:
            logger.debug(
                "AD-843c-1: failed to store device episode (%s)",
                device_id,
                exc_info=True,
            )
