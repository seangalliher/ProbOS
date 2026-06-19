"""AD-979d slice 1: distributed cross-agent associative recall (service half).

When an agent's own sovereign recall returns a WEAK Feeling-of-Knowing band —
the *slow-gap* case (something relevant is present but under the confident-recall
bar; a vocabulary-mismatch miss, AD-979a/c), not a strong recall and not a
genuine absence — a human would turn to a colleague: "you were there, what was
that thing?". This service is that mechanism. It escalates the query to the
single most-associated peer (Hebbian ``REL_SOCIAL`` top-1) and surfaces *that
peer's CONFIDENT recall* with SECONDHAND provenance (AD-541), so the requesting
agent learns from a colleague's memory without confabulating its own.

Slice 1 is the **mechanism only**, and it is deliberately narrow:

* **FOK-gated.** Escalation fires *only* on a ``weak`` own band. A ``strong``
  band needs no help; a ``none`` band is a genuine absence and must not be
  papered over with a peer's guess.
* **Hebbian top-1.** A single peer — the one the requester is most associated
  with — is queried. No multi-peer fan-out, no fusion.
* **In-process.** ProbOS stores every agent's episodes in ONE shared collection,
  sharded by ``agent_ids`` metadata. A "peer query" is just
  ``recall_for_agent_with_confidence(peer_id, ...)`` on that same store — no
  IntentBus transport, no rate limiter (those are only needed for
  out-of-process peers).
* **Governed.** Refused outright under the ``OWN_SHARD_ONLY`` access policy
  (AD-607e).
* **Trust raw, never weighted.** The peer's Beta ``(alpha, beta)`` trust
  parameters are attached verbatim (repo rule: never a derived mean); slice 1
  does not weight or rank by them.
* **Default OFF.** With ``enabled=False`` (the default), :meth:`escalate_recall`
  returns ``[]`` before touching any dependency — byte-identical to not having
  the service at all.

Dependency Inversion: the service is constructor-injected with the three
collaborators it needs (episodic store, Hebbian router, optional trust network)
and the peer set is *passed in* per call. It never imports the agent registry or
reaches into the runtime.

Deferred to follow-on slices (do NOT add here): live ``cognitive_agent.py``
wiring, IntentBus transport + per-domain rate limiter (out-of-process peers),
multi-peer aggregation, trust-WEIGHTED fusion, and reconsolidation / storing the
peer's memory into the requester's own shard (#907).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from probos.cognitive.memory_security import MemoryAccessPolicy
from probos.mesh.routing import REL_SOCIAL
from probos.types import Episode, MemorySource

if TYPE_CHECKING:  # type-only: zero runtime coupling, DIP preserved at load
    from probos.cognitive.episodic import EpisodicMemory
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.routing import HebbianRouter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PeerRecall:
    """A single episode recalled from a peer's sovereign shard on the
    requesting agent's behalf, carried with SECONDHAND provenance.

    ``peer_alpha`` / ``peer_beta`` are the peer's RAW Beta trust parameters
    (repo rule: never a derived mean score) — attached for downstream callers,
    NOT used to weight or rank anything in slice 1.
    """

    peer_id: str
    peer_callsign: str
    episode: Episode
    peer_similarity: float
    peer_band: str
    peer_alpha: float = 2.0
    peer_beta: float = 2.0
    source: MemorySource = MemorySource.SECONDHAND


class CrossAgentRecallService:
    """FOK-gated, Hebbian-routed, in-process governed cross-agent recall.

    See the module docstring for the full slice-1 contract. Every guard in
    :meth:`escalate_recall` returns ``[]`` (the no-op / honest-degrade path), so
    a disabled or refused or ungated call is indistinguishable from the service
    not existing.
    """

    def __init__(
        self,
        *,
        episodic_memory: "EpisodicMemory",
        hebbian_router: "HebbianRouter",
        trust_network: "TrustNetwork | None" = None,
        enabled: bool = False,
        access_policy: str = "permissive",
    ) -> None:
        self._episodic = episodic_memory
        self._hebbian = hebbian_router
        self._trust = trust_network
        self._enabled = bool(enabled)
        self._access_policy = access_policy

    async def escalate_recall(
        self,
        requesting_agent_id: str,
        query: str,
        own_band: str,
        *,
        peer_candidates: list[str],
        callsigns: dict[str, str] | None = None,
        k: int = 3,
    ) -> list[PeerRecall]:
        """Escalate a weak-FOK recall to the most-associated peer.

        ``own_band`` is the requesting agent's *already-computed* Feeling-of-
        Knowing band for ``query`` (the service does not recompute it). Returns
        the peer's confident recall as SECONDHAND :class:`PeerRecall` items, or
        ``[]`` if any gate refuses.
        """
        # 1. OFF gate — byte-identical default (no dependency is touched).
        if not self._enabled:
            return []

        # 2. Governance — refuse cross-shard escalation under OWN_SHARD_ONLY (AD-607e).
        if self._access_policy == MemoryAccessPolicy.OWN_SHARD_ONLY.value:
            return []

        # 3. FOK gate — escalate ONLY on a weak own band (slow-gap / vocab miss).
        #    Strong recall needs no help; a "none" absence must not be papered
        #    over with a peer's guess.
        if own_band != "weak":
            return []

        # 4. Candidate peers, requester excluded.
        peers = [p for p in peer_candidates if p != requesting_agent_id]
        if not peers:
            return []

        # 5. Hebbian top-1 — the single most-associated peer (REL_SOCIAL).
        ranked = self._hebbian.get_preferred_targets(
            requesting_agent_id, peers, rel_type=REL_SOCIAL
        )
        if not ranked:
            return []
        peer_id = ranked[0]

        # 6. Tier-2 around the peer recall — degrade to [] on any failure.
        try:
            episodes, peer_conf = await self._episodic.recall_for_agent_with_confidence(
                peer_id, query, k
            )
        except Exception:
            logger.warning(
                "AD-979d: peer recall failed for %s; degrading to no cross-agent recall",
                peer_id,
                exc_info=True,
            )
            return []

        # 7. Surface ONLY a peer's CONFIDENT recall — never a confabulated
        #    corroboration from a peer who is itself merely guessing.
        if peer_conf.band != "strong":
            return []

        # 8. Raw Beta trust params (NO weighting — repo rule: never a derived mean).
        rec = self._trust.get_record(peer_id) if self._trust else None
        alpha, beta = (rec.alpha, rec.beta) if rec else (2.0, 2.0)

        # 9. SECONDHAND-provenance peer recalls (bounded — episodes is k-capped).
        callsign_map = callsigns or {}
        peer_callsign = callsign_map.get(peer_id, peer_id)
        return [
            PeerRecall(
                peer_id=peer_id,
                peer_callsign=peer_callsign,
                episode=ep,
                peer_similarity=peer_conf.best_similarity,
                peer_band=peer_conf.band,
                peer_alpha=alpha,
                peer_beta=beta,
                source=MemorySource.SECONDHAND,
            )
            for ep in episodes
        ]
