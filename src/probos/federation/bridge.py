"""FederationBridge — connects the local IntentBus to the federation transport layer."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Awaitable
from typing import Any, TYPE_CHECKING

from probos.config import FederationConfig
from probos.federation.router import FederationRouter
from probos.types import FederationMessage, IntentMessage, IntentResult, NodeSelfModel

if TYPE_CHECKING:
    from probos.federation.mock_transport import MockFederationTransport
    from probos.mesh.intent import IntentBus

logger = logging.getLogger(__name__)


class FederationBridge:
    """Connects the local IntentBus to the federation transport layer.

    Outbound: Forwards local intents to peers, collects remote results.
    Inbound: Receives intents from peers, broadcasts locally, returns results.
    Gossip: Periodically sends this node's self-model to all peers.
    """

    def __init__(
        self,
        node_id: str,
        transport: Any,  # FederationTransport or MockFederationTransport
        router: FederationRouter,
        intent_bus: Any,  # IntentBus
        config: FederationConfig,
        self_model_fn: Callable[[], NodeSelfModel],
        validate_fn: Callable[..., Awaitable[bool]] | None = None,
    ) -> None:
        self._node_id = node_id
        self._transport = transport
        self._router = router
        self._intent_bus = intent_bus
        self._config = config
        self._self_model_fn = self_model_fn
        self._validate_fn = validate_fn
        self._gossip_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._stats = {
            "intents_forwarded": 0,
            "intents_received": 0,
            "results_collected": 0,
        }

    async def start(self) -> None:
        """Start the bridge: register as transport inbound handler, start gossip loop."""
        self._stopped = False
        self._transport._inbound_handler = self.handle_inbound
        self._gossip_task = asyncio.create_task(
            self._gossip_loop(), name="federation-gossip"
        )

    async def stop(self) -> None:
        """Stop gossip loop."""
        self._stopped = True
        if self._gossip_task is not None:
            self._gossip_task.cancel()
            try:
                await self._gossip_task
            except asyncio.CancelledError:
                pass
            self._gossip_task = None

    async def forward_intent(self, intent: IntentMessage) -> list[IntentResult]:
        """Forward an intent to selected peers and collect results.

        This is the function registered as IntentBus._federation_fn.
        """
        peers = self._router.select_peers(
            intent.intent, self._transport.connected_peers
        )
        if not peers:
            return []

        msg = FederationMessage(
            type="intent_request",
            source_node=self._node_id,
            payload={
                "intent": intent.intent,
                "params": intent.params,
                "urgency": intent.urgency,
                "context": intent.context,
                "id": intent.id,
                "ttl_seconds": intent.ttl_seconds,
            },
            timestamp=time.monotonic(),
        )

        # Send to each peer
        for peer_id in peers:
            await self._transport.send_to_peer(peer_id, msg)
        self._stats["intents_forwarded"] += 1

        # Collect responses with timeout
        results: list[IntentResult] = []
        for peer_id in peers:
            response = await self._transport.receive_with_timeout(
                peer_id, self._config.forward_timeout_ms
            )
            if response is None:
                continue
            # Deserialize results from response payload
            remote_results = response.payload.get("results", [])
            for rr in remote_results:
                ir = IntentResult(
                    intent_id=rr.get("intent_id", intent.id),
                    agent_id=rr.get("agent_id", f"{peer_id}:remote"),
                    success=rr.get("success", False),
                    result=rr.get("result"),
                    error=rr.get("error"),
                    confidence=rr.get("confidence", 0.0),
                )
                # Validate if validation function is set
                if self._validate_fn:
                    try:
                        valid = await self._validate_fn(ir)
                        if not valid:
                            continue
                    except Exception:
                        logger.warning("Federation message validator failed — message passed without validation", exc_info=True)
                results.append(ir)
                self._stats["results_collected"] += 1

        return results

    async def handle_inbound(self, message: FederationMessage) -> None:
        """Handle a message received from a peer.

        Dispatches by message type:
        - intent_request: broadcast locally (federated=False), send results back
        - intent_response: route to pending request (correlation by message_id)
        - gossip_self_model: update router's peer model
        - ping: respond with pong
        """
        if message.type == "intent_request":
            await self._handle_intent_request(message)
        elif message.type == "intent_response":
            # Route to pending request by delivering to transport's response queue
            await self._transport.deliver_response(message.source_node, message)
        elif message.type == "gossip_self_model":
            self._handle_gossip(message)
        elif message.type == "ping":
            pong = FederationMessage(
                type="pong",
                source_node=self._node_id,
                message_id=message.message_id,
                timestamp=time.monotonic(),
            )
            await self._transport.send_to_peer(message.source_node, pong)

    async def _handle_intent_request(self, message: FederationMessage) -> None:
        """Handle an inbound intent request from a peer."""
        self._stats["intents_received"] += 1

        payload = message.payload
        intent = IntentMessage(
            intent=payload.get("intent", ""),
            params=payload.get("params", {}),
            urgency=payload.get("urgency", 0.5),
            context=payload.get("context", ""),
            id=payload.get("id", uuid.uuid4().hex),
            ttl_seconds=payload.get("ttl_seconds", 30.0),
        )

        # Broadcast locally with federated=False to prevent loop
        local_results = await self._intent_bus.broadcast(intent, federated=False)

        # Build response
        serialized_results = []
        for r in local_results:
            serialized_results.append({
                "intent_id": r.intent_id,
                "agent_id": r.agent_id,
                "success": r.success,
                "result": r.result,
                "error": r.error,
                "confidence": r.confidence,
            })

        response = FederationMessage(
            type="intent_response",
            source_node=self._node_id,
            message_id=message.message_id,
            payload={"results": serialized_results},
            timestamp=time.monotonic(),
        )
        await self._transport.send_to_peer(message.source_node, response)

    def _handle_gossip(self, message: FederationMessage) -> None:
        """Handle an inbound gossip self-model message."""
        payload = message.payload
        model = NodeSelfModel(
            node_id=payload.get("node_id", message.source_node),
            capabilities=payload.get("capabilities", []),
            pool_sizes=payload.get("pool_sizes", {}),
            agent_count=payload.get("agent_count", 0),
            health=payload.get("health", 0.0),
            uptime_seconds=payload.get("uptime_seconds", 0.0),
            timestamp=payload.get("timestamp", 0.0),
        )
        self._router.update_peer_model(model)

    async def _gossip_loop(self) -> None:
        """Periodically broadcast this node's self-model to all peers."""
        while not self._stopped:
            try:
                await asyncio.sleep(self._config.gossip_interval_seconds)
                model = self._self_model_fn()
                msg = FederationMessage(
                    type="gossip_self_model",
                    source_node=self._node_id,
                    payload={
                        "node_id": model.node_id,
                        "capabilities": model.capabilities,
                        "pool_sizes": model.pool_sizes,
                        "agent_count": model.agent_count,
                        "health": model.health,
                        "uptime_seconds": model.uptime_seconds,
                        "timestamp": model.timestamp,
                    },
                    timestamp=time.monotonic(),
                )
                await self._transport.send_to_all_peers(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Gossip loop error: %s", e)

    def federation_status(self) -> dict[str, Any]:
        """Return federation status for shell/panels."""
        peer_models = {}
        for nid, model in self._router.known_peers.items():
            peer_models[nid] = {
                "capabilities": model.capabilities,
                "pool_sizes": model.pool_sizes,
                "agent_count": model.agent_count,
                "health": model.health,
                "uptime_seconds": model.uptime_seconds,
                "timestamp": model.timestamp,
            }

        return {
            "node_id": self._node_id,
            "bind_address": self._config.bind_address,
            "connected_peers": self._transport.connected_peers,
            "peer_models": peer_models,
            "intents_forwarded": self._stats["intents_forwarded"],
            "intents_received": self._stats["intents_received"],
            "results_collected": self._stats["results_collected"],
            "gossip_interval": self._config.gossip_interval_seconds,
        }
