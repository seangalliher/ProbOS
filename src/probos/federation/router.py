"""FederationRouter — federated query routing function R: intent -> set[peer_node_ids]."""

from __future__ import annotations

import logging
from typing import Any

from probos.types import NodeSelfModel

logger = logging.getLogger(__name__)


class FederationRouter:
    """Federated query routing function R: intent -> set[peer_node_ids].

    Decides which peers should receive a forwarded intent based on
    peer self-models (capabilities, health, pool sizes).

    Phase 9: Returns all connected peers (degenerate case with 2-3 nodes).
    """

    def __init__(self) -> None:
        self._peer_models: dict[str, NodeSelfModel] = {}

    def update_peer_model(self, model: NodeSelfModel) -> None:
        """Update stored self-model for a peer (received via gossip)."""
        self._peer_models[model.node_id] = model

    def select_peers(self, intent_name: str, available_peers: list[str]) -> list[str]:
        """Select which peers should receive this intent.

        Phase 9 implementation: return all available_peers.
        """
        return available_peers

    def peer_has_capability(self, peer_node_id: str, intent_name: str) -> bool:
        """Check if a peer has advertised capability for this intent."""
        model = self._peer_models.get(peer_node_id)
        if model is None:
            return False
        return intent_name in model.capabilities

    @property
    def known_peers(self) -> dict[str, NodeSelfModel]:
        """Return all known peer self-models."""
        return dict(self._peer_models)
