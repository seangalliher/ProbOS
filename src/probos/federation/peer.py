"""AD-480f: FederationPeer + FederationPeerRegistry — protocol-polymorphic peer model.

Maintains a parallel structure to FederationRouter._peer_models (which is
ZeroMQ-keyed by node_id only). Each peer carries a protocol discriminator
("zmq" | "mcp" | "a2a") and the trust_record_id used by TrustNetwork for
the Beta(alpha, beta) probationary prior wiring.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal


PeerProtocol = Literal["zmq", "mcp", "a2a"]


@dataclass
class FederationPeer:
    """One federated peer.

    For ZeroMQ peers, peer_id == node_id and endpoint == bind address.
    For MCP peers, peer_id == server URL and endpoint == server URL.
    For A2A peers, peer_id == peer URL and endpoint == peer URL.
    """

    protocol: PeerProtocol
    peer_id: str
    endpoint: str
    trust_record_id: str
    discovered_at: float = field(default_factory=time.time)
    last_outcome_at: float = 0.0
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class FederationPeerRegistry:
    """In-memory registry of federated peers across all three protocols."""

    def __init__(
        self,
        *,
        trust_network: Any | None = None,
        probationary_alpha: float = 1.0,
        probationary_beta: float = 3.0,
    ) -> None:
        self._peers: dict[str, FederationPeer] = {}
        self._lock = asyncio.Lock()
        self._trust_network = trust_network
        self._probationary_alpha = probationary_alpha
        self._probationary_beta = probationary_beta

    async def register_peer(self, peer: FederationPeer) -> bool:
        """Register a peer. Returns True if newly registered, False if already known."""
        async with self._lock:
            if peer.peer_id in self._peers:
                return False
            self._peers[peer.peer_id] = peer
        # AD-480g: probationary trust prior on first registration.
        if self._trust_network is not None:
            self._trust_network.create_with_prior(
                peer.trust_record_id,
                self._probationary_alpha,
                self._probationary_beta,
            )
        return True

    async def unregister_peer(self, peer_id: str) -> bool:
        async with self._lock:
            return self._peers.pop(peer_id, None) is not None

    def get_peer(self, peer_id: str) -> FederationPeer | None:
        return self._peers.get(peer_id)

    def list_peers(
        self, protocol: PeerProtocol | None = None
    ) -> list[FederationPeer]:
        peers = list(self._peers.values())
        if protocol is not None:
            peers = [p for p in peers if p.protocol == protocol]
        return peers

    def peers_supporting(self, intent_name: str) -> list[FederationPeer]:
        return [p for p in self._peers.values() if intent_name in p.capabilities]

    def record_outcome(
        self,
        peer_id: str,
        success: bool,
        *,
        intent_type: str = "",
    ) -> None:
        peer = self._peers.get(peer_id)
        if peer is None:
            return
        peer.last_outcome_at = time.time()
        if self._trust_network is not None:
            self._trust_network.record_outcome(
                peer.trust_record_id,
                success=success,
                weight=1.0,
                intent_type=intent_type,
                source="federation_outcome",
            )

    def __len__(self) -> int:
        return len(self._peers)
