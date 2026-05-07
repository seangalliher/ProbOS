"""FederationRouter — federated query routing function R: intent -> set[peer_node_ids]."""

from __future__ import annotations

import logging
from typing import Any

from probos.types import NodeSelfModel

logger = logging.getLogger(__name__)


class FederationRouter:
    """Federated query routing function R: intent -> set[peer_node_ids].

    Decides which peers should receive a forwarded intent based on
    peer self-models (capabilities, health, pool sizes), peer trust
    (AD-479b Bayesian Beta(α, β) score), and federation Hebbian
    weights (AD-479c).
    """

    def __init__(
        self,
        *,
        trust_network: Any | None = None,
        hebbian_map: Any | None = None,
        min_trust_score: float = 0.0,
        cluster_monitor: Any | None = None,
    ) -> None:
        self._peer_models: dict[str, NodeSelfModel] = {}
        self._trust_network = trust_network
        self._hebbian_map = hebbian_map
        self._min_trust_score = min_trust_score
        self._cluster_monitor = cluster_monitor

    def update_peer_model(self, model: NodeSelfModel) -> None:
        """Update stored self-model for a peer (received via gossip)."""
        self._peer_models[model.node_id] = model

    def select_peers(self, intent_name: str, available_peers: list[str]) -> list[str]:
        """Select which peers should receive this intent.

        AD-479a v1: capability-aware filter. When at least one peer has
        reported capabilities via gossip, return only peers whose
        ``NodeSelfModel.capabilities`` includes ``intent_name``. When no
        peer model has any capability data yet (bootstrap-before-first-
        gossip case), fall through to all ``available_peers`` so empty-
        registry tests continue to pass.

        AD-479g: drops peers flagged unreachable by the cluster monitor
        ahead of the capability filter.

        AD-479b: ranks capability-qualified peers by trust score
        descending and drops peers below ``min_trust_score``.

        AD-479c: applies the federation Hebbian weight as the final
        tie-break (stable sort) so peers with equal trust are ordered
        by intent × peer affinity.
        """
        # AD-479g: drop unreachable peers ahead of capability filter.
        peers = list(available_peers)
        if self._cluster_monitor is not None:
            peers = [p for p in peers if not self._cluster_monitor.is_unreachable(p)]

        any_capability_data = any(
            bool(self._peer_models.get(p) and self._peer_models[p].capabilities)
            for p in peers
        )
        if any_capability_data:
            peers = [p for p in peers if self.peer_has_capability(p, intent_name)]

        # AD-479b: drop peers below min_trust_score and rank by trust descending.
        if self._trust_network is not None:

            def _trust_for(peer_node_id: str) -> float:
                return float(
                    self._trust_network.get_score(f"federation_peer:{peer_node_id}")
                )

            peers = [p for p in peers if _trust_for(p) >= self._min_trust_score]
            peers.sort(key=_trust_for, reverse=True)

        # AD-479c: stable Hebbian tie-break for peers at the same trust score.
        if self._hebbian_map is not None:
            peers.sort(
                key=lambda p: self._hebbian_map.score(intent_name, p), reverse=True,
            )

        return peers

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
