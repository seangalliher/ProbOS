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
    from probos.identity import AgentIdentityRegistry
    from probos.mesh.intent import IntentBus
    from probos.mobility import TransferCertificate

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
        identity_registry: "AgentIdentityRegistry | None" = None,
    ) -> None:
        self._node_id = node_id
        self._transport = transport
        self._router = router
        self._intent_bus = intent_bus
        self._config = config
        self._self_model_fn = self_model_fn
        self._validate_fn = validate_fn
        # AD-443e: Identity registry handle — required for transfer/chain
        # message handling; None disables the mobility wire types.
        self._identity_registry = identity_registry
        self._gossip_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._stats = {
            "intents_forwarded": 0,
            "intents_received": 0,
            "results_collected": 0,
            "transfers_sent": 0,
            "transfers_received": 0,
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
        elif message.type == "chain_request":
            await self._handle_chain_request(message)
        elif message.type == "chain_response":
            await self._transport.deliver_response(message.source_node, message)
        elif message.type == "transfer_request":
            await self._handle_transfer_request(message)
        elif message.type == "transfer_response":
            await self._transport.deliver_response(message.source_node, message)

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

    # ── AD-443e: Mobility wire-protocol handlers ──────────────────────────

    async def _handle_chain_request(self, message: FederationMessage) -> None:
        """Peer asks for our exported Identity Ledger chain."""
        if self._identity_registry is None:
            response = FederationMessage(
                type="chain_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={"blocks": [], "error": "identity_registry not wired"},
                timestamp=time.monotonic(),
            )
        else:
            blocks = await self._identity_registry.export_chain()
            response = FederationMessage(
                type="chain_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={"blocks": blocks},
                timestamp=time.monotonic(),
            )
        await self._transport.send_to_peer(message.source_node, response)

    async def _handle_transfer_request(self, message: FederationMessage) -> None:
        """Peer wants to transfer an agent to us.

        Pipeline: import_chain (validates) -> import_transfer_certificate
        (validates). Slot reassignment is NOT performed automatically.
        """
        from probos.mobility import TransferCertificate

        if self._identity_registry is None:
            response = FederationMessage(
                type="transfer_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={
                    "accepted": False,
                    "message": "identity_registry not wired",
                    "agent_uuid": None,
                },
                timestamp=time.monotonic(),
            )
            await self._transport.send_to_peer(message.source_node, response)
            return

        cert_dict = message.payload.get("cert_dict") or {}
        chain_blocks = message.payload.get("chain_blocks") or []
        try:
            cert = TransferCertificate.from_dict(cert_dict)
        except (KeyError, TypeError) as exc:
            response = FederationMessage(
                type="transfer_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={
                    "accepted": False,
                    "message": f"malformed cert_dict: {exc!s}",
                    "agent_uuid": None,
                },
                timestamp=time.monotonic(),
            )
            await self._transport.send_to_peer(message.source_node, response)
            return

        chain_ok, chain_msg = await self._identity_registry.import_chain(chain_blocks)
        if not chain_ok:
            response = FederationMessage(
                type="transfer_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={
                    "accepted": False,
                    "message": f"chain rejected: {chain_msg}",
                    "agent_uuid": None,
                },
                timestamp=time.monotonic(),
            )
            await self._transport.send_to_peer(message.source_node, response)
            return

        cert_ok, cert_msg = await self._identity_registry.import_transfer_certificate(cert)
        if cert_ok:
            self._stats["transfers_received"] += 1
        response = FederationMessage(
            type="transfer_response",
            source_node=self._node_id,
            message_id=message.message_id,
            payload={
                "accepted": cert_ok,
                "message": cert_msg,
                "agent_uuid": cert.agent_uuid if cert_ok else None,
            },
            timestamp=time.monotonic(),
        )
        await self._transport.send_to_peer(message.source_node, response)

    async def request_chain(self, peer_node_id: str) -> list[dict[str, Any]]:
        """Outbound: ask a specific peer for its exported chain."""
        msg = FederationMessage(
            type="chain_request",
            source_node=self._node_id,
            payload={},
            timestamp=time.monotonic(),
        )
        await self._transport.send_to_peer(peer_node_id, msg)
        response = await self._transport.receive_with_timeout(
            peer_node_id, self._config.forward_timeout_ms
        )
        if response is None:
            logger.warning(
                "Chain request to %s timed out; returning empty chain", peer_node_id,
            )
            return []
        return list(response.payload.get("blocks", []))

    async def request_transfer(
        self,
        peer_node_id: str,
        certificate: "TransferCertificate",
        chain_blocks: list[dict[str, Any]],
    ) -> tuple[bool, str]:
        """Outbound: ship an agent's transfer cert + supporting chain to a peer."""
        msg = FederationMessage(
            type="transfer_request",
            source_node=self._node_id,
            payload={
                "cert_dict": certificate.to_dict(),
                "chain_blocks": chain_blocks,
            },
            timestamp=time.monotonic(),
        )
        await self._transport.send_to_peer(peer_node_id, msg)
        self._stats["transfers_sent"] += 1
        response = await self._transport.receive_with_timeout(
            peer_node_id, self._config.forward_timeout_ms
        )
        if response is None:
            logger.warning(
                "Transfer request to %s timed out; agent %s remains on origin ship",
                peer_node_id, certificate.did,
            )
            return False, "timeout"
        accepted = bool(response.payload.get("accepted", False))
        message_text = str(response.payload.get("message", ""))
        return accepted, message_text

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
