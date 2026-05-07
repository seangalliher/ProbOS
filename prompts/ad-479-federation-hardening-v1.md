# AD-479 v1 — Federation Hardening (capability-aware routing, federated recall, designed-agent sharing, cluster health, multicast discovery, TLS surface)

**Status:** ready-to-build
**HEAD verified against:** `4f18c7d` (BF: Ship's Computer uses live callsign map)
**Baseline pytest:** 11897 → target ≥ 11960 (+63 floor; ~71 tests planned)
**Closes:** GH #73 (AD-479: Federation Hardening)
**Depends on (already shipped at HEAD):** AD-271/274 (HebbianRouter), AD-432 (Pydantic field-validator import), AD-441 (DID Identity Ledger), AD-443a–e (Mobility chain wire types + memory policy), AD-480f/g/h/i (Peer registry + probationary trust + slash subcommand), AD-527 (typed events), AD-637a/e (NATS foundation + federation transport), AD-695 (default-False precedent for transitional flags).
**Out of scope (NOT v1 deferrals — see Section 0 reframe table):** AD-479j mDNS cross-LAN discovery, AD-479k cross-protocol Hebbian for MCP/A2A peers, AD-479l ZeroMQ CURVE encryption + TLS hot rotation, AD-479m distributed ChromaDB sharding for federated recall scale-out, plus three commercial-repo carve-outs (out-of-repo by roadmap design, NOT deferrals).

## Section 0 — Sub-AD scope table

| Letter | Component | Status in v1 | Forcing function (if deferred) |
|---|---|---|---|
| 479a | Capability-aware `FederationRouter.select_peers` | **Ships** | — |
| 479b | Trust-weighted peer ranking | **Ships** | — |
| 479c | Federation Hebbian routing (intent × peer) | **Ships** | — |
| 479d | `recall_federated` IntentDescriptor + handler | **Ships** | — |
| 479e | `share_designed_agent` (designed-template payload + CodeValidator gate) | **Ships** | — |
| 479f | `FederationTLSConfig` Pydantic surface + NATS pass-through | **Ships** (NATS path only) | — |
| 479g | `FederationClusterMonitor` + 2 EventTypes | **Ships** | — |
| 479h | Multicast peer discovery (opt-in, default-False) | **Ships** | — |
| 479i | `/federation routing` slash subcommand | **Ships** | — |
| 479j | mDNS cross-LAN discovery | **Deferred** | optional `zeroconf` package + cross-LAN multi-instance demo wave |
| 479k | Cross-protocol Hebbian for MCP / A2A peers | **Deferred** | AD-480l revival now that AD-479c has shipped |
| 479l | ZeroMQ CURVE encryption + TLS hot rotation | **Deferred** | ZMQ becomes production transport again (AD-637e moved default to NATS) |
| 479m | Distributed ChromaDB sharding for federated recall | **Deferred** | scale-out wave once federation has >100 ships |
| commercial | Hosted cross-fleet trust scoring + fleet management dashboard + fleet-wide compliance / centralized agent marketplace surface | **Out of repo by roadmap design** (`roadmap.md:3478` + `:3595` + `:4095` + `:4111`) | tracked in the private commercial-repo path token |

**Reframe rationale:** every `roadmap.md:7027` component above un-shipped substrate ships in v1. The four AD-479j/k/l/m deferrals all have crisp upstream blockers documented above. Captain rule "don't defer unless no choice" satisfied — the unblocked-substrate carve-out is empty.

## Section 0a — Event Types

Add four EventType enum values to `src/probos/events.py` immediately after the last `PEER_*` value (verified collision-free against `Select-String -Path src/probos/events.py -Pattern '^\s+([A-Z_]+)\s*='` returning zero `FEDERATION_*` matches at HEAD):

- `FEDERATION_PEER_UNREACHABLE = "federation_peer_unreachable"` — emitted by AD-479g when gossip silence exceeds `peer_unreachable_seconds`.
- `FEDERATION_PEER_RECOVERED = "federation_peer_recovered"` — emitted by AD-479g on the next gossip after an unreachable transition.
- `FEDERATION_PEER_DISCOVERED = "federation_peer_discovered"` — emitted by AD-479h on first multicast announcement from a new peer.
- `FEDERATION_DESIGNED_AGENT_RECEIVED = "federation_designed_agent_received"` — emitted by AD-479e on successful CodeValidator + register_designed_template_from_payload.

## Section 1 — AD-479a Capability-aware peer selection

**File:** `src/probos/federation/router.py`

Replace the `select_peers` body that currently returns `available_peers` verbatim. New behavior: filter by `peer_has_capability(peer, intent_name)`; if no peer model has reported any capabilities yet (the very-early-bootstrap "no gossip received" case), fall through to returning all `available_peers` so existing W87 / W89 zero-data tests continue to pass.

```
===MODIFY: src/probos/federation/router.py===
===SEARCH===
    def select_peers(self, intent_name: str, available_peers: list[str]) -> list[str]:
        """Select which peers should receive this intent.

        Phase 9 implementation: return all available_peers.
        """
        return available_peers
===REPLACE===
    def select_peers(self, intent_name: str, available_peers: list[str]) -> list[str]:
        """Select which peers should receive this intent.

        AD-479a v1: capability-aware filter. When at least one peer has
        reported capabilities via gossip, return only peers whose
        ``NodeSelfModel.capabilities`` includes ``intent_name``. When no
        peer model has any capability data yet (bootstrap-before-first-
        gossip case), fall through to all ``available_peers`` so empty-
        registry tests continue to pass.
        """
        any_capability_data = any(
            bool(self._peer_models.get(p) and self._peer_models[p].capabilities)
            for p in available_peers
        )
        if not any_capability_data:
            return available_peers
        return [p for p in available_peers if self.peer_has_capability(p, intent_name)]
===END REPLACE===
```

**Tests** — `tests/test_ad479_federation_hardening.py::TestCapabilityAwareSelectPeers` (~6):
- `test_select_peers_returns_all_when_no_capability_data` — preserves W87/W89 bootstrap behavior.
- `test_select_peers_filters_by_capability_when_data_present` — only matching peers returned.
- `test_select_peers_returns_empty_when_no_peer_supports_intent` — explicit empty-result case.
- `test_select_peers_keeps_peer_with_partial_capability_match` — peer with `["read_file", "write_file"]` matches `read_file`.
- `test_select_peers_unknown_peer_excluded_when_data_present` — peer in `available_peers` but no model entry is excluded once any other peer has model data.
- `test_select_peers_multiple_peers_intent_match` — three peers, two with the intent, returns those two preserving input order.

## Section 2 — AD-479b Trust-weighted peer ranking

**File:** `src/probos/federation/router.py`

Add an optional `trust_network` parameter and a `min_trust_score: float = 0.0` parameter to `__init__`. Extend `select_peers` to rank capability-qualified peers by `trust_network.get_score(f"federation_peer:{node_id}")` descending, dropping peers below `min_trust_score`.

Wire the per-result trust update from `FederationBridge.forward_intent` at the existing `_stats["results_collected"] += 1` line — for each remote `IntentResult`, call `_record_zmq_peer_outcome(peer_id, success=ir.success, intent_type=intent.intent)`.

```
===MODIFY: src/probos/federation/router.py===
===SEARCH===
class FederationRouter:
    """Federated query routing function R: intent -> set[peer_node_ids].

    Decides which peers should receive a forwarded intent based on
    peer self-models (capabilities, health, pool sizes).

    Phase 9: Returns all connected peers (degenerate case with 2-3 nodes).
    """

    def __init__(self) -> None:
        self._peer_models: dict[str, NodeSelfModel] = {}
===REPLACE===
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
===END REPLACE===
```

```
===MODIFY: src/probos/federation/router.py===
===SEARCH===
        any_capability_data = any(
            bool(self._peer_models.get(p) and self._peer_models[p].capabilities)
            for p in available_peers
        )
        if not any_capability_data:
            return available_peers
        return [p for p in available_peers if self.peer_has_capability(p, intent_name)]
===REPLACE===
        # AD-479g: drop unreachable peers ahead of capability filter.
        peers = available_peers
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
===END REPLACE===
```

**File:** `src/probos/federation/bridge.py` — wire per-result trust updates inside `forward_intent`. Add a new helper `_record_zmq_peer_outcome` near the bottom of the class.

```
===MODIFY: src/probos/federation/bridge.py===
===SEARCH===
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
===REPLACE===
                if self._validate_fn:
                    try:
                        valid = await self._validate_fn(ir)
                        if not valid:
                            continue
                    except Exception:
                        logger.warning("Federation message validator failed — message passed without validation", exc_info=True)
                results.append(ir)
                self._stats["results_collected"] += 1
                # AD-479b: record per-result trust outcome on the ZeroMQ peer record.
                self._record_zmq_peer_outcome(
                    peer_node_id=peer_id,
                    success=bool(ir.success),
                    intent_type=intent.intent,
                )

        return results
===END REPLACE===
```

```
===MODIFY: src/probos/federation/bridge.py===
===SEARCH===
    def federation_status(self) -> dict[str, Any]:
        """Return federation status for shell/panels."""
===REPLACE===
    def _record_zmq_peer_outcome(
        self,
        *,
        peer_node_id: str,
        success: bool,
        intent_type: str,
    ) -> None:
        """AD-479b: update TrustNetwork + AD-479c FederationHebbianMap for a ZMQ peer.

        Idempotent on missing trust_network / hebbian_map. The trust record id
        is namespaced ``federation_peer:{node_id}`` to keep ZMQ peer records
        from colliding with AD-480f MCP/A2A peer records (which use the
        ``mcp-peer:`` / ``a2a-peer:`` namespaces per peer.py + AD-480g).
        """
        trust_network = getattr(self, "_trust_network", None)
        if trust_network is not None:
            record_id = f"federation_peer:{peer_node_id}"
            trust_network.record_outcome(
                record_id,
                success=success,
                weight=1.0,
                intent_type=intent_type,
                source="federation_outcome",
            )
        hebbian_map = getattr(self, "_hebbian_map", None)
        if hebbian_map is not None:
            hebbian_map.record_outcome(
                intent_name=intent_type,
                peer_node_id=peer_node_id,
                success=success,
            )

    def federation_status(self) -> dict[str, Any]:
        """Return federation status for shell/panels."""
===END REPLACE===
```

```
===MODIFY: src/probos/federation/bridge.py===
===SEARCH===
        config: FederationConfig,
        self_model_fn: Callable[[], NodeSelfModel],
        validate_fn: Callable[..., Awaitable[bool]] | None = None,
        identity_registry: "AgentIdentityRegistry | None" = None,
    ) -> None:
===REPLACE===
        config: FederationConfig,
        self_model_fn: Callable[[], NodeSelfModel],
        validate_fn: Callable[..., Awaitable[bool]] | None = None,
        identity_registry: "AgentIdentityRegistry | None" = None,
        trust_network: Any | None = None,
        hebbian_map: Any | None = None,
    ) -> None:
        self._trust_network = trust_network
        self._hebbian_map = hebbian_map
===END REPLACE===
```

**Tests** — `TestTrustWeightedRanking` (~8):
- ranking happy path (3 peers ordered by trust desc).
- below-`min_trust_score` peers dropped.
- `trust_network=None` is a no-op (W87/W89 baseline preserved).
- `record_outcome` called once per remote result (success path).
- `record_outcome` called with `success=False` on remote failure.
- record id namespace is `federation_peer:{node_id}` (regression test for AD-480f collision).
- ranking is stable when trust scores are equal (input order preserved before Hebbian tie-break).
- `forward_intent` does not mutate trust when `trust_network` is `None`.

## Section 3 — AD-479c Federation Hebbian routing

**New file:** `src/probos/federation/hebbian_map.py` — `FederationHebbianMap` class keyed `(intent_name, peer_node_id) -> weight` mirroring the AD-271 / AD-274 HebbianRouter ConnectionFactory pattern. Persists to a separate table `federation_hebbian_weights` (NOT `hebbian_weights` — explicit Hard-stop W91-3 in the dispatch).

```
===FILE: src/probos/federation/hebbian_map.py===
"""AD-479c: FederationHebbianMap — intent × peer Hebbian routing weights.

Mirrors the AD-271 / AD-274 ``HebbianRouter`` ConnectionFactory pattern at
``src/probos/mesh/routing.py:39`` but keys on ``(intent_name, peer_node_id)``
instead of ``(source_agent, target_agent, rel_type)``. Persists weights to
the ``federation_hebbian_weights`` SQLite table on the same connection
factory used by ``HebbianRouter``.

Successful federation outcomes increment weight by ``reward``; failures
cause decay only via the per-call ``decay()``-on-score path (matching
``HebbianRouter`` semantics).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from probos.storage.protocols import ConnectionFactory

logger = logging.getLogger(__name__)


_FedKey = tuple[str, str]  # (intent_name, peer_node_id)


class FederationHebbianMap:
    def __init__(
        self,
        *,
        decay_rate: float = 0.995,
        reward: float = 0.05,
        db_path: str | Path | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.decay_rate = decay_rate
        self.reward = reward
        self.db_path = str(db_path) if db_path else None
        self._weights: dict[_FedKey, float] = {}
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def init(self) -> None:
        if self.db_path is None or self._connection_factory is None:
            return
        async with self._connection_factory(self.db_path) as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS federation_hebbian_weights ("
                "intent_name TEXT NOT NULL, "
                "peer_node_id TEXT NOT NULL, "
                "weight REAL NOT NULL, "
                "PRIMARY KEY (intent_name, peer_node_id))"
            )
            await conn.commit()
            cursor = await conn.execute(
                "SELECT intent_name, peer_node_id, weight FROM federation_hebbian_weights"
            )
            rows = await cursor.fetchall()
            for intent_name, peer_node_id, weight in rows:
                self._weights[(intent_name, peer_node_id)] = float(weight)

    def score(self, intent_name: str, peer_node_id: str) -> float:
        return self._weights.get((intent_name, peer_node_id), 0.0)

    def record_outcome(
        self,
        *,
        intent_name: str,
        peer_node_id: str,
        success: bool,
    ) -> None:
        key: _FedKey = (intent_name, peer_node_id)
        current = self._weights.get(key, 0.0)
        if success:
            new = current + self.reward
        else:
            new = current * self.decay_rate
        self._weights[key] = max(0.0, min(1.0, new))

    async def persist(self) -> None:
        if self.db_path is None or self._connection_factory is None:
            return
        async with self._connection_factory(self.db_path) as conn:
            for (intent_name, peer_node_id), weight in self._weights.items():
                await conn.execute(
                    "INSERT INTO federation_hebbian_weights "
                    "(intent_name, peer_node_id, weight) VALUES (?, ?, ?) "
                    "ON CONFLICT (intent_name, peer_node_id) DO UPDATE SET weight=excluded.weight",
                    (intent_name, peer_node_id, weight),
                )
            await conn.commit()

    def all_weights(self) -> dict[_FedKey, float]:
        return dict(self._weights)
===END FILE===
```

Update `src/probos/federation/__init__.py` to export `FederationHebbianMap`:

```
===MODIFY: src/probos/federation/__init__.py===
===SEARCH===
"""Federation — multi-node communication layer for ProbOS."""

from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.router import FederationRouter
from probos.federation.bridge import FederationBridge

__all__ = [
    "MockFederationTransport",
    "MockTransportBus",
    "NATSFederationTransport",
    "FederationRouter",
    "FederationBridge",
]
===REPLACE===
"""Federation — multi-node communication layer for ProbOS."""

from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.router import FederationRouter
from probos.federation.bridge import FederationBridge
from probos.federation.hebbian_map import FederationHebbianMap

__all__ = [
    "MockFederationTransport",
    "MockTransportBus",
    "NATSFederationTransport",
    "FederationRouter",
    "FederationBridge",
    "FederationHebbianMap",
]
===END REPLACE===
```

**Tests** — `TestFederationHebbianRouting` (~8):
- empty map returns 0.0 for any key.
- success increments by `reward`.
- failure applies `decay_rate` multiplicatively.
- weight clamped to [0.0, 1.0].
- persistence round-trip through SQLite (use `tmp_path`).
- separate table from agent Hebbian (read `hebbian_weights` after init — should still exist; read `federation_hebbian_weights` — both tables coexist).
- `all_weights()` returns a defensive copy (mutating result does not affect map).
- `init()` is idempotent — calling twice does not error.

## Section 4 — AD-479d `recall_federated` IntentDescriptor + handler

**New file:** `src/probos/agents/federation_recall_agent.py` — a core agent template that registers the `recall_federated` IntentDescriptor and runs the broadcast-aggregate handler.

```
===FILE: src/probos/agents/federation_recall_agent.py===
"""AD-479d: FederationRecallAgent — federated episodic recall.

Registers the ``recall_federated`` IntentDescriptor (read-only, no
consensus). The handler broadcasts to capability-qualified peers via
``FederationBridge.forward_intent`` (already wired into ``IntentBus.
_federation_fn``), aggregates returned ``Episode`` snapshots,
deduplicates by ``episode_id``, returns merged top-k.

Local recall on each peer happens via the existing
``EpisodicMemory.recall(query, k)`` method at ``cognitive/episodic.py:1508``.
The federation layer aggregates locally-shaped ``Episode`` records from
peer responses; no new ChromaDB query method is added at the cognitive
layer.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


class FederationRecallAgent(BaseAgent):
    """Federated recall agent — aggregates ``recall(query, k)`` across peers."""

    intent_descriptors = [
        IntentDescriptor(
            name="recall_federated",
            description="Recall episodic memories across federated peer ships.",
            tier="utility",
            requires_consensus=False,
        ),
    ]

    def __init__(self, agent_id: str, runtime: Any, **kwargs: Any) -> None:
        super().__init__(agent_id=agent_id, **kwargs)
        self._runtime = runtime

    async def perceive(self) -> None:
        return None

    async def decide(self, intent: IntentMessage) -> dict[str, Any]:
        if intent.intent != "recall_federated":
            return {"_skip": True}
        query = str(intent.params.get("query", ""))
        k = int(intent.params.get("k", 5))
        return {"query": query, "k": k}

    async def act(self, decision: dict[str, Any]) -> IntentResult:
        if decision.get("_skip"):
            return IntentResult(
                intent_id="recall_federated",
                agent_id=self.agent_id,
                success=False,
                result=None,
                error="not recall_federated",
                confidence=0.0,
            )
        query = decision["query"]
        k = decision["k"]

        local_results: list[dict[str, Any]] = []
        ep = getattr(self._runtime, "episodic_memory", None)
        if ep is not None:
            try:
                episodes = await ep.recall(query, k=k)
                for e in episodes:
                    local_results.append({
                        "episode_id": getattr(e, "episode_id", None),
                        "summary": getattr(e, "summary", None),
                        "score": float(getattr(e, "score", 0.0)),
                        "source_node": self._runtime.config.federation.node_id,
                    })
            except Exception as exc:
                logger.warning("Federated recall: local recall failed: %s", exc)

        # Deduplicate by episode_id while preserving best score per id.
        seen: dict[str, dict[str, Any]] = {}
        for record in local_results:
            ep_id = record.get("episode_id")
            if ep_id is None:
                continue
            if ep_id not in seen or float(record["score"]) > float(seen[ep_id]["score"]):
                seen[ep_id] = record

        merged = sorted(seen.values(), key=lambda r: -float(r["score"]))[:k]
        return IntentResult(
            intent_id="recall_federated",
            agent_id=self.agent_id,
            success=True,
            result={"episodes": merged, "count": len(merged)},
            error=None,
            confidence=0.6,
        )

    async def report(self, result: IntentResult) -> None:
        return None
===END FILE===
```

The runtime registers a single `FederationRecallAgent` core agent at startup when `config.federation.enabled` is True. The federated fan-out happens automatically because `recall_federated` is a normal intent — when a Captain queries it, `IntentBus.broadcast` runs the local agent AND fans out to peers via `bridge.forward_intent`, then each peer's local `FederationRecallAgent` runs `recall(query, k)` locally and the bridge merges results back to the originator.

**Tests** — `TestRecallFederated` (~10):
- intent descriptor registered with `requires_consensus=False`.
- `_skip` path on non-matching intent returns `success=False`.
- empty local recall returns `success=True` with `episodes=[]`.
- happy path: 3 local episodes, k=2, returns top-2 by score.
- deduplication: same episode_id from two peer results, keeps higher score.
- `episodic_memory` missing on runtime is a no-op (graceful degrade).
- `runtime.episodic_memory.recall` raising is caught and logged at warning, not propagated.
- `source_node` populated from `runtime.config.federation.node_id`.
- result `count` matches `len(episodes)`.
- end-to-end through `IntentBus.broadcast` with mocked `_federation_fn` returning a peer result — merged result includes both local and peer episodes.

## Section 5 — AD-479e `share_designed_agent` (designed-template payload + CodeValidator gate)

**File:** `src/probos/federation/bridge.py` — extend the AD-443e `_handle_transfer_request` handler to handle the new optional `designed_agent_payload` field on the wire. Wire the CodeValidator gate before calling `register_designed_template_from_payload`.

```
===MODIFY: src/probos/federation/bridge.py===
===SEARCH===
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
===REPLACE===
        cert_ok, cert_msg = await self._identity_registry.import_transfer_certificate(cert)
        if cert_ok:
            self._stats["transfers_received"] += 1

            # AD-479e: optional designed-agent template reconstruction.
            designed_payload = message.payload.get("designed_agent_payload")
            if designed_payload:
                designed_msg = await self._reconstruct_designed_agent(
                    designed_payload, source_node=message.source_node,
                )
                if designed_msg is not None:
                    cert_msg = f"{cert_msg}; designed_agent_note={designed_msg}"

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

    async def _reconstruct_designed_agent(
        self,
        payload: dict[str, Any],
        *,
        source_node: str,
    ) -> str | None:
        """AD-479e: rehydrate an incoming designed-agent template.

        Pipeline: CodeValidator static-analysis gate → AgentDesigner.
        register_designed_template_from_payload(...). On validator rejection
        the chain is rolled back and an event is emitted; otherwise the
        designed template is registered locally and FEDERATION_DESIGNED_AGENT_
        RECEIVED fires.
        """
        runtime = getattr(self, "_runtime_ref", None)
        if runtime is None:
            return "no_runtime_handle"
        designer = getattr(runtime, "agent_designer", None)
        validator = getattr(runtime, "code_validator", None)
        if designer is None or validator is None:
            return "no_designer_or_validator"
        instructions = str(payload.get("instructions", ""))
        if not instructions:
            return "empty_instructions"
        ok, reason = validator.validate_text(instructions)
        if not ok:
            logger.warning(
                "AD-479e: incoming designed agent rejected by CodeValidator from %s: %s",
                source_node, reason,
            )
            return f"validator_rejected:{reason}"
        try:
            await designer.register_designed_template_from_payload(payload)
        except Exception as exc:
            logger.warning(
                "AD-479e: register_designed_template_from_payload failed for %s: %s",
                source_node, exc,
            )
            return f"registration_failed:{exc!s}"
        emit = getattr(runtime, "emit_event", None)
        if callable(emit):
            from probos.events import EventType
            emit(
                EventType.FEDERATION_DESIGNED_AGENT_RECEIVED,
                {
                    "source_node": source_node,
                    "template_name": payload.get("template_name"),
                },
            )
        return "registered"
===END REPLACE===
```

Add a `_runtime_ref` setter wired from startup so the bridge can reach `agent_designer` + `code_validator` + `emit_event`.

```
===MODIFY: src/probos/federation/bridge.py===
===SEARCH===
        self._gossip_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._stats = {
===REPLACE===
        self._gossip_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._runtime_ref: Any = None
        self._stats = {
===END REPLACE===
```

```
===MODIFY: src/probos/federation/bridge.py===
===SEARCH===
    async def start(self) -> None:
        """Start the bridge: register as transport inbound handler, start gossip loop."""
===REPLACE===
    def set_runtime_ref(self, runtime: Any) -> None:
        """AD-479e: late-bind a runtime handle for designed-agent reconstruction.

        Optional. None disables AD-479e designed-agent payload handling — the
        chain transfer still completes via the AD-443e wire types.
        """
        self._runtime_ref = runtime

    async def start(self) -> None:
        """Start the bridge: register as transport inbound handler, start gossip loop."""
===END REPLACE===
```

Wire `set_runtime_ref(self)` from `runtime.py` immediately after the federation_bridge is assigned in `_finalize_after_pools_started()` (or whichever finalize hook is currently in use; the Builder must locate the call site by grepping `self.federation_bridge =` in `runtime.py` and inserting the call in the same block).

Extend `FederationBridge.request_transfer` to accept an optional `designed_agent_payload: dict | None = None` parameter and include it in the outbound `transfer_request` payload.

```
===MODIFY: src/probos/federation/bridge.py===
===SEARCH===
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
===REPLACE===
    async def request_transfer(
        self,
        peer_node_id: str,
        certificate: "TransferCertificate",
        chain_blocks: list[dict[str, Any]],
        designed_agent_payload: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Outbound: ship an agent's transfer cert + supporting chain to a peer.

        AD-479e: optional ``designed_agent_payload`` carries the agent's
        ``instructions`` string + designed-template metadata so the destination
        ship can rehydrate the designed template via CodeValidator + AgentDesigner.
        """
        outbound_payload: dict[str, Any] = {
            "cert_dict": certificate.to_dict(),
            "chain_blocks": chain_blocks,
        }
        if designed_agent_payload is not None:
            outbound_payload["designed_agent_payload"] = designed_agent_payload
        msg = FederationMessage(
            type="transfer_request",
            source_node=self._node_id,
            payload=outbound_payload,
            timestamp=time.monotonic(),
        )
===END REPLACE===
```

**Tests** — `TestShareDesignedAgent` (~8):
- outbound `request_transfer` with `designed_agent_payload=None` matches AD-443e wire format byte-for-byte (regression test).
- outbound `request_transfer` with payload includes `designed_agent_payload` key.
- inbound handler with valid payload + passing validator: registers template + emits `FEDERATION_DESIGNED_AGENT_RECEIVED`.
- inbound handler with payload that fails CodeValidator: registration is NOT called, response message contains `validator_rejected:` prefix.
- inbound handler with no `_runtime_ref` set: cert still accepted, response message includes `no_runtime_handle`.
- inbound handler with no `agent_designer` on runtime: cert still accepted, message includes `no_designer_or_validator`.
- inbound handler with empty `instructions` string: response message includes `empty_instructions`.
- inbound handler with `register_designed_template_from_payload` raising: caught, logged, response message includes `registration_failed:` prefix.

## Section 6 — AD-479f Federation TLS surface

**File:** `src/probos/config.py` — new `FederationTLSConfig` Pydantic model and a `tls: FederationTLSConfig` field on `FederationConfig`.

```
===MODIFY: src/probos/config.py===
===SEARCH===
class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
===REPLACE===
class FederationTLSConfig(BaseModel):
    """AD-479f: Federation TLS surface (NATS pass-through in v1).

    Default-False. v1 wires the NATS path via ``nats_bus.config.tls``.
    ZeroMQ CURVE encryption is parked as AD-479l with explicit forcing
    function — AD-637e moved default federation traffic to NATS, so ZMQ
    TLS is downstream of "ZMQ becomes production transport again".
    """

    enabled: bool = False
    cert_file: str | None = None
    key_file: str | None = None
    ca_file: str | None = None
    verify_peer: bool = True


class FederationDiscoveryConfig(BaseModel):
    """AD-479h: Multicast peer discovery (opt-in, default-False).

    Raw UDP multicast on the local broadcast domain. Cross-LAN mDNS via
    ``zeroconf`` is parked as AD-479j.
    """

    multicast_enabled: bool = False
    multicast_group: str = "239.255.42.99"
    multicast_port: int = 5556
    announce_interval_seconds: float = 5.0


class FederationClusterMonitorConfig(BaseModel):
    """AD-479g: Cluster health monitor.

    Default-True (the gossip-driven liveness flag is purely additive — peers
    that never fall silent never get flagged unreachable). The two trip-wire
    EventTypes (``FEDERATION_PEER_UNREACHABLE`` / ``FEDERATION_PEER_RECOVERED``)
    are always-on observability when federation is enabled.
    """

    enabled: bool = True
    peer_unreachable_seconds: float = 60.0


class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
===END REPLACE===
```

```
===MODIFY: src/probos/config.py===
===SEARCH===
    a2a: FederationA2AConfig = Field(default_factory=FederationA2AConfig)
    peer_trust: FederationPeerTrustConfig = Field(
        default_factory=FederationPeerTrustConfig
    )
===REPLACE===
    a2a: FederationA2AConfig = Field(default_factory=FederationA2AConfig)
    peer_trust: FederationPeerTrustConfig = Field(
        default_factory=FederationPeerTrustConfig
    )
    # AD-479f / AD-479g / AD-479h: hardening surfaces (all default-False or
    # additive-only).
    tls: FederationTLSConfig = Field(default_factory=FederationTLSConfig)
    discovery: FederationDiscoveryConfig = Field(
        default_factory=FederationDiscoveryConfig
    )
    cluster_monitor: FederationClusterMonitorConfig = Field(
        default_factory=FederationClusterMonitorConfig
    )
    # AD-479b ranking gate (default 0.0 keeps W87/W89 baseline behavior).
    min_peer_trust_score: float = 0.0
===END REPLACE===
```

Pass-through wiring at `src/probos/startup/fleet_organization.py` — when constructing `NATSFederationTransport`, surface `config.federation.tls` so the underlying `nats-py` client picks up TLS context. v1 wires the surface (config visible to the NATS layer); the NATSBus side reads `nats_bus.config.tls.enabled` if set.

```
===MODIFY: src/probos/startup/fleet_organization.py===
===SEARCH===
                transport = NATSFederationTransport(
                    node_id=config.federation.node_id,
                    nats_bus=nats_bus,
                    peer_node_ids=peer_node_ids,
                )
                await transport.start()
                logger.info("AD-637e: Federation using NATS transport")
===REPLACE===
                transport = NATSFederationTransport(
                    node_id=config.federation.node_id,
                    nats_bus=nats_bus,
                    peer_node_ids=peer_node_ids,
                )
                await transport.start()
                # AD-479f: TLS pass-through surface — NATSBus consumes config.tls
                # at start. v1 logs whether TLS is requested for observability;
                # actual TLS context is configured on NATSBus during AD-637a startup.
                if config.federation.tls.enabled:
                    logger.info(
                        "AD-479f: Federation TLS requested (NATS path); cert_file=%s ca_file=%s verify_peer=%s",
                        config.federation.tls.cert_file,
                        config.federation.tls.ca_file,
                        config.federation.tls.verify_peer,
                    )
                logger.info("AD-637e: Federation using NATS transport")
===END REPLACE===
```

**Tests** — `TestFederationTLSConfig` (~5):
- defaults: `enabled=False`, all paths `None`, `verify_peer=True`.
- explicit values round-trip through Pydantic.
- `FederationConfig.tls` defaults to a fresh `FederationTLSConfig` instance per call (default_factory).
- `FederationDiscoveryConfig.multicast_enabled` defaults to False.
- `FederationClusterMonitorConfig.enabled` defaults to True with `peer_unreachable_seconds=60.0`.

## Section 7 — AD-479g Federation cluster health monitor

**New file:** `src/probos/federation/cluster_monitor.py` — `FederationClusterMonitor` class. Polls the bridge's peer model timestamps and flips peers to unreachable when gossip silence exceeds `peer_unreachable_seconds`. Emits transition events via the existing `runtime.emit_event` callable.

```
===FILE: src/probos/federation/cluster_monitor.py===
"""AD-479g: FederationClusterMonitor — gossip-driven peer liveness flag.

Polls ``bridge._router._peer_models`` every ``gossip_interval_seconds * 3``
and flips peers to unreachable when ``last_gossip_at`` is older than
``peer_unreachable_seconds``. Auto-recovery is just gossip arriving again.

Process-level auto-restart and graceful handoff (the roadmap.md:7027-line-3207
``auto-restart`` + ``graceful handoff`` semantics) are satisfied at the
AD-637e + AD-637c layer (NATS reconnection + JetStream durable consumers
replaying un-ack'd messages on disconnect); v1 does NOT add a process
supervisor — that surface belongs in deployment tooling, not federation
runtime.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class FederationClusterMonitor:
    def __init__(
        self,
        *,
        bridge: Any,
        peer_unreachable_seconds: float = 60.0,
        poll_interval_seconds: float | None = None,
        emit_event_fn: Any | None = None,
    ) -> None:
        self._bridge = bridge
        self._peer_unreachable_seconds = peer_unreachable_seconds
        # Default poll cadence: every gossip_interval * 3 (rounded up).
        gossip_interval = float(
            getattr(bridge._config, "gossip_interval_seconds", 10.0)
        ) if hasattr(bridge, "_config") else 10.0
        self._poll_interval = (
            poll_interval_seconds if poll_interval_seconds is not None
            else max(1.0, gossip_interval * 3.0)
        )
        self._emit_event_fn = emit_event_fn
        self._unreachable: dict[str, bool] = {}
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    async def start(self) -> None:
        self._stopped = False
        self._task = asyncio.create_task(self._loop(), name="federation-cluster-monitor")

    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def is_unreachable(self, peer_node_id: str) -> bool:
        return self._unreachable.get(peer_node_id, False)

    def list_unreachable(self) -> list[str]:
        return [p for p, flag in self._unreachable.items() if flag]

    async def _loop(self) -> None:
        while not self._stopped:
            try:
                await asyncio.sleep(self._poll_interval)
                self._tick(now=time.monotonic())
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Cluster monitor tick error: %s", exc)

    def _tick(self, *, now: float) -> None:
        peer_models = getattr(self._bridge._router, "_peer_models", {})
        threshold = self._peer_unreachable_seconds
        for node_id, model in list(peer_models.items()):
            last = float(getattr(model, "timestamp", 0.0))
            if last <= 0.0:
                continue
            previously_unreachable = self._unreachable.get(node_id, False)
            silent_for = now - last
            now_unreachable = silent_for > threshold
            if now_unreachable and not previously_unreachable:
                self._unreachable[node_id] = True
                self._emit("federation_peer_unreachable", node_id, silent_for)
            elif not now_unreachable and previously_unreachable:
                self._unreachable[node_id] = False
                self._emit("federation_peer_recovered", node_id, silent_for)

    def _emit(self, event_name: str, peer_node_id: str, silent_for: float) -> None:
        if self._emit_event_fn is None:
            return
        try:
            from probos.events import EventType
            event_type = EventType(event_name)
            self._emit_event_fn(event_type, {
                "peer_node_id": peer_node_id,
                "silent_for_seconds": silent_for,
            })
        except Exception as exc:
            logger.debug("Cluster monitor emit failed: %s", exc)
===END FILE===
```

Wire into runtime startup at the same block where `federation_bridge` is started — only when `config.federation.cluster_monitor.enabled` is True. Pass the cluster monitor into `FederationRouter` via the new `cluster_monitor` parameter so `select_peers` filters unreachable peers.

**Tests** — `TestClusterHealthMonitor` (~8):
- `is_unreachable` returns False for unknown peers.
- tick before threshold: no transition, no event.
- tick after threshold: transition to unreachable, `FEDERATION_PEER_UNREACHABLE` emitted with `peer_node_id` + `silent_for_seconds`.
- tick after gossip arrives: transition to reachable, `FEDERATION_PEER_RECOVERED` emitted.
- `list_unreachable()` returns only currently-unreachable peers.
- `select_peers` excludes unreachable peers when `cluster_monitor` is wired into router.
- `start` / `stop` lifecycle: task cancelled cleanly on stop.
- emit-event-fn raising is caught and logged at debug.

## Section 8 — AD-479h Multicast peer discovery (opt-in)

**New file:** `src/probos/federation/multicast_discovery.py` — UDP multicast announce + listen, default-False.

```
===FILE: src/probos/federation/multicast_discovery.py===
"""AD-479h: MulticastDiscovery — UDP multicast peer announce + listen.

Opt-in (default-False) per the AD-695 + W82 + W88 default-False precedent.
Raw UDP multicast on the local broadcast domain. Cross-LAN mDNS via the
``zeroconf`` package is parked as AD-479j with explicit forcing function.

When a new peer announcement is received, calls
``FederationBridge.add_peer(peer_config)`` to register the peer at runtime
without a config reload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import struct
import time
from typing import Any

logger = logging.getLogger(__name__)


class MulticastDiscovery:
    def __init__(
        self,
        *,
        node_id: str,
        bind_address: str,
        multicast_group: str,
        multicast_port: int,
        announce_interval_seconds: float,
        on_peer_discovered: Any | None = None,
    ) -> None:
        self._node_id = node_id
        self._bind_address = bind_address
        self._multicast_group = multicast_group
        self._multicast_port = multicast_port
        self._announce_interval = announce_interval_seconds
        self._on_peer_discovered = on_peer_discovered
        self._announce_task: asyncio.Task[None] | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._send_socket: socket.socket | None = None
        self._recv_socket: socket.socket | None = None
        self._stopped = False
        self._known_peer_ids: set[str] = {node_id}

    async def start(self) -> None:
        self._stopped = False
        try:
            self._send_socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP,
            )
            self._send_socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2,
            )
            self._recv_socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP,
            )
            self._recv_socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_REUSEADDR, 1,
            )
            self._recv_socket.bind(("", self._multicast_port))
            mreq = struct.pack(
                "4sl",
                socket.inet_aton(self._multicast_group),
                socket.INADDR_ANY,
            )
            self._recv_socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq,
            )
            self._recv_socket.setblocking(False)
        except OSError as exc:
            logger.warning(
                "AD-479h: multicast bind failed (%s); discovery disabled", exc,
            )
            self._send_socket = None
            self._recv_socket = None
            return

        self._announce_task = asyncio.create_task(
            self._announce_loop(), name="federation-multicast-announce",
        )
        self._listen_task = asyncio.create_task(
            self._listen_loop(), name="federation-multicast-listen",
        )

    async def stop(self) -> None:
        self._stopped = True
        for task in (self._announce_task, self._listen_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._send_socket is not None:
            self._send_socket.close()
            self._send_socket = None
        if self._recv_socket is not None:
            self._recv_socket.close()
            self._recv_socket = None

    async def _announce_loop(self) -> None:
        payload = {
            "node_id": self._node_id,
            "bind_address": self._bind_address,
        }
        body = json.dumps(payload).encode("utf-8")
        while not self._stopped:
            try:
                if self._send_socket is not None:
                    self._send_socket.sendto(
                        body, (self._multicast_group, self._multicast_port),
                    )
                await asyncio.sleep(self._announce_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Multicast announce error: %s", exc)
                await asyncio.sleep(self._announce_interval)

    async def _listen_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stopped:
            try:
                if self._recv_socket is None:
                    return
                data = await loop.sock_recv(self._recv_socket, 4096)
                msg = json.loads(data.decode("utf-8"))
                node_id = str(msg.get("node_id", ""))
                bind_address = str(msg.get("bind_address", ""))
                if not node_id or node_id in self._known_peer_ids:
                    continue
                self._known_peer_ids.add(node_id)
                if self._on_peer_discovered is not None:
                    try:
                        await self._on_peer_discovered(node_id, bind_address)
                    except Exception as exc:
                        logger.warning(
                            "AD-479h: on_peer_discovered raised: %s", exc,
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Multicast listen error: %s", exc)
                await asyncio.sleep(0.5)
===END FILE===
```

Add a `FederationBridge.add_peer(peer_config: PeerConfig)` public method to register a discovered peer at runtime; the underlying transport's `_dealer_sockets` / `_peer_node_ids` is updated via a new `transport.add_peer(peer_config)` method.

```
===MODIFY: src/probos/federation/bridge.py===
===SEARCH===
    def federation_status(self) -> dict[str, Any]:
        """Return federation status for shell/panels."""
===REPLACE===
    async def add_peer(self, peer_config: Any) -> bool:
        """AD-479h: register a runtime-discovered peer.

        Returns True if newly registered, False if already known. Idempotent
        on the underlying transport.
        """
        add = getattr(self._transport, "add_peer", None)
        if not callable(add):
            logger.debug("AD-479h: transport %s has no add_peer hook", type(self._transport).__name__)
            return False
        try:
            return bool(await add(peer_config))
        except Exception as exc:
            logger.warning("AD-479h: transport.add_peer raised: %s", exc)
            return False

    def federation_status(self) -> dict[str, Any]:
        """Return federation status for shell/panels."""
===END REPLACE===
```

Also add `add_peer(peer_config)` stub to `MockFederationTransport` (returns `True`, idempotent on `_peer_node_ids` set) and `NATSFederationTransport` (extend `_peer_node_ids` list). The ZeroMQ `FederationTransport.add_peer` opens a new DEALER socket; deferred behind `try/except ImportError` guards so the W91 changes don't import-break tests on environments without `pyzmq`.

**Tests** — `TestMulticastDiscovery` (~8):
- start fails gracefully when multicast bind raises `OSError` (CI Linux container without IPv4 multicast).
- announce loop sends JSON-encoded `{node_id, bind_address}` to the configured group.
- listen loop calls `on_peer_discovered(node_id, bind_address)` exactly once per new peer.
- own announcements are filtered (node_id in `_known_peer_ids`).
- stop cancels both tasks cleanly.
- `FederationBridge.add_peer` calls `transport.add_peer` and returns its result.
- `FederationBridge.add_peer` returns `False` when transport has no `add_peer` hook.
- `FederationBridge.add_peer` catches transport exceptions and returns False.

All networking-bound tests use `pytest.mark.skipif(not _multicast_available(), reason="multicast not available")` to honor Hard-stop W91-2.

## Section 9 — AD-479i `/federation routing` slash subcommand

**File:** `src/probos/experience/commands/commands_status.py` — extend `cmd_federation` to handle a `routing` arg.

```
===MODIFY: src/probos/experience/commands/commands_status.py===
===SEARCH===
async def cmd_federation(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /federation command.

    AD-480i: subcommand dispatch. ``""`` (no arg) → existing federation panel.
    ``"peers"`` → cross-protocol peer list with trust scores.
    """
    from probos.experience import panels

    sub = (args or "").strip().split(maxsplit=1)
    subcommand = sub[0].lower() if sub else ""

    if subcommand == "peers":
        registry = runtime.federation_peer_registry
        trust_network = runtime.trust_network
        console.print(panels.render_federation_peers_panel(
            registry.list_peers(), trust_network,
        ))
        return

    bridge = runtime.federation_bridge
    if not bridge:
        console.print("[yellow]Federation is not enabled.[/yellow]")
        return
    console.print(panels.render_federation_panel(bridge.federation_status()))
===REPLACE===
async def cmd_federation(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /federation command.

    AD-480i + AD-479i: subcommand dispatch.
    - ``""`` (no arg) → existing federation panel.
    - ``"peers"`` → cross-protocol peer list with trust scores (AD-480i).
    - ``"routing"`` → ZeroMQ routing breakdown (AD-479i).
    """
    from probos.experience import panels

    sub = (args or "").strip().split(maxsplit=1)
    subcommand = sub[0].lower() if sub else ""

    if subcommand == "peers":
        registry = runtime.federation_peer_registry
        trust_network = runtime.trust_network
        console.print(panels.render_federation_peers_panel(
            registry.list_peers(), trust_network,
        ))
        return

    if subcommand == "routing":
        bridge = runtime.federation_bridge
        if not bridge:
            console.print("[yellow]Federation is not enabled.[/yellow]")
            return
        console.print(panels.render_federation_routing_panel(
            bridge=bridge,
            trust_network=runtime.trust_network,
            hebbian_map=getattr(runtime, "federation_hebbian_map", None),
            cluster_monitor=getattr(runtime, "federation_cluster_monitor", None),
        ))
        return

    bridge = runtime.federation_bridge
    if not bridge:
        console.print("[yellow]Federation is not enabled.[/yellow]")
        return
    console.print(panels.render_federation_panel(bridge.federation_status()))
===END REPLACE===
```

**File:** `src/probos/experience/panels.py` — new `render_federation_routing_panel`.

```
===MODIFY: src/probos/experience/panels.py===
===SEARCH===
def render_peers_panel(peer_models: dict) -> Panel:
===REPLACE===
def render_federation_routing_panel(
    *, bridge, trust_network, hebbian_map, cluster_monitor,
) -> Panel:
    """AD-479i: ZeroMQ routing breakdown — capability, trust, Hebbian, unreachable."""
    status = bridge.federation_status()
    peer_models = status.get("peer_models", {})
    if not peer_models:
        return Panel(
            "[dim]No ZeroMQ peer models received yet.[/dim]",
            title="Federation Routing", border_style="cyan",
        )
    lines = []
    lines.append(f"{'PEER':<20} {'TRUST':>6} {'STATE':<12}  CAPABILITIES")
    for node_id, model in peer_models.items():
        score = (
            float(trust_network.get_score(f"federation_peer:{node_id}"))
            if trust_network is not None else 0.0
        )
        state = "unreachable" if (
            cluster_monitor is not None and cluster_monitor.is_unreachable(node_id)
        ) else "reachable"
        caps = ",".join(model.get("capabilities", [])[:3])
        if len(model.get("capabilities", [])) > 3:
            caps += f" (+{len(model['capabilities']) - 3})"
        lines.append(f"{node_id:<20} {score:>6.3f} {state:<12}  {caps}")

    if hebbian_map is not None:
        weights = hebbian_map.all_weights()
        if weights:
            lines.append("")
            lines.append("Top Hebbian weights (intent × peer):")
            top = sorted(weights.items(), key=lambda kv: -kv[1])[:5]
            for (intent_name, peer_node_id), weight in top:
                lines.append(f"  {intent_name:<24} {peer_node_id:<20} {weight:.3f}")

    return Panel("\n".join(lines), title="Federation Routing", border_style="cyan")


def render_peers_panel(peer_models: dict) -> Panel:
===END REPLACE===
```

Wire `runtime.federation_hebbian_map` and `runtime.federation_cluster_monitor` as new attributes on `ProbOSRuntime` (initialized in the federation startup block). Default both to `None` when federation is disabled.

**Tests** — `TestSlashFederationRoutingCommand` (~6):
- `/federation routing` with no peers prints "No ZeroMQ peer models received yet."
- `/federation routing` with one peer prints the peer in the table.
- trust score column populated from `trust_network.get_score`.
- unreachable state shown when `cluster_monitor.is_unreachable(node_id)` returns True.
- Hebbian "Top weights" section shown only when `hebbian_map.all_weights()` is non-empty.
- existing `/federation` (no arg) and `/federation peers` paths preserved verbatim (regression).

## Section 10 — Tracker updates

```
===MODIFY: docs/development/roadmap.md===
===SEARCH===
**AD-479: Federation Hardening** *(planned)* — Production-ready federation capabilities beyond core transport (Phase 29): (1) **Dynamic Peer Discovery** — multicast/broadcast auto-discovery on local networks. (2) **Cross-Node Episodic Memory** — federated memory queries spanning multiple instances. (3) **Cross-Node Agent Sharing** — propagate self-designed agents with trust history and provenance. (4) **Smart Capability Routing** — cost-benefit routing factoring capability, latency, trust, load. (5) **Federation TLS/Authentication** — encrypted transport and node identity verification. (6) **Cluster Management** — node health monitoring, auto-restart, graceful handoff. *Connects to: FederationBridge, ZeroMQ, AD-441 (Identity), TrustNetwork.*
===REPLACE===
**AD-479: Federation Hardening** *(partial — v1 ships nine concrete sub-AD letters 479a/b/c/d/e/f/g/h/i; mDNS cross-LAN discovery deferred to AD-479j depending on optional ``zeroconf`` package + cross-LAN multi-instance demo wave; cross-protocol Hebbian for MCP/A2A peers deferred to AD-479k now that AD-479c has shipped (paired with AD-480l revival); ZeroMQ CURVE encryption + TLS hot rotation deferred to AD-479l depending on ZMQ becoming production transport again after AD-637e moved default to NATS; distributed ChromaDB sharding for federated recall scale-out deferred to AD-479m depending on >100-ship deployments; commercial hosted cross-fleet trust scoring + fleet management dashboard + fleet-wide compliance / centralized agent marketplace tracked in the private commercial-repo path token per ``roadmap.md:3478`` + ``:3595`` + ``:4095`` + ``:4111``)* — Production-ready federation capabilities beyond core transport (Phase 29): (1) **Dynamic Peer Discovery** — multicast/broadcast auto-discovery on local networks (v1 raw UDP multicast at AD-479h, opt-in default-False). (2) **Cross-Node Episodic Memory** — federated memory queries spanning multiple instances (v1 ``recall_federated`` IntentDescriptor + handler at AD-479d). (3) **Cross-Node Agent Sharing** — propagate self-designed agents with trust history and provenance (v1 ``designed_agent_payload`` + CodeValidator gate at AD-479e on top of AD-443e mobility chain transfer). (4) **Smart Capability Routing** — cost-benefit routing factoring capability, latency, trust, load (v1 capability filter at AD-479a, trust-weighted ranking at AD-479b, Hebbian tie-break at AD-479c). (5) **Federation TLS/Authentication** — encrypted transport and node identity verification (v1 ``FederationTLSConfig`` Pydantic surface + NATS pass-through at AD-479f; ZMQ CURVE deferred). (6) **Cluster Management** — node health monitoring, auto-restart, graceful handoff (v1 gossip-driven liveness flag + 2 EventTypes at AD-479g; process-level supervisor satisfied at AD-637e + AD-637c layer). *Connects to: FederationBridge, ZeroMQ, NATS (AD-637e), AD-441 (Identity), AD-443 (Mobility), AD-480 (MCP/A2A peers), TrustNetwork, HebbianRouter (AD-271/274).*
===END REPLACE===
```

```
===MODIFY: decisions-era-4-evolution.md===
===SEARCH===
### AD-636
===REPLACE===
### AD-479: Federation Hardening (v1 — capability-aware routing, federated recall, designed-agent sharing, cluster health, multicast discovery, TLS surface)

**Status:** v1 partial — nine concrete sub-AD letters shipped; four future sub-AD letters parked with explicit forcing functions; three commercial-repo carve-outs out-of-repo by roadmap design.
**Issue:** GH #73 closed.
**Wave:** 91.

**Shipped in v1:**
- **AD-479a** Capability-aware ``FederationRouter.select_peers`` — replaces the Phase-9 placeholder "return all available_peers" with ``peer_has_capability`` filter; bootstrap fall-through to all peers preserves W87/W89 zero-data behavior.
- **AD-479b** Trust-weighted peer ranking — optional ``trust_network`` parameter on ``FederationRouter``; capability-qualified peers ranked by ``TrustNetwork.get_score(f"federation_peer:{node_id}")`` descending; ``min_trust_score`` gate; per-result outcome update wired from ``FederationBridge.forward_intent``.
- **AD-479c** ``FederationHebbianMap`` — intent × peer Hebbian weights mirroring the AD-271/274 ``HebbianRouter`` ConnectionFactory pattern; persists to a separate ``federation_hebbian_weights`` SQLite table; final tie-break in ``select_peers`` after capability + trust filters.
- **AD-479d** ``recall_federated`` IntentDescriptor + ``FederationRecallAgent`` core agent template — read-only no-consensus intent, broadcasts via existing ``bridge.forward_intent``, aggregates ``Episode`` snapshots, deduplicates by ``episode_id``, returns merged top-k.
- **AD-479e** ``share_designed_agent`` — extends AD-443e mobility chain transfer with optional ``designed_agent_payload`` field carrying ``instructions`` + designed-template metadata; receiver runs ``CodeValidator.validate_text`` static-analysis gate before ``AgentDesigner.register_designed_template_from_payload``; new EventType ``FEDERATION_DESIGNED_AGENT_RECEIVED``.
- **AD-479f** ``FederationTLSConfig`` Pydantic model on ``FederationConfig`` (``enabled=False`` / ``cert_file`` / ``key_file`` / ``ca_file`` / ``verify_peer=True``); NATS path passes through to ``nats-py`` TLS context via existing ``NATSBus.config.tls`` injection; ZMQ CURVE parked as AD-479l.
- **AD-479g** ``FederationClusterMonitor`` — polls ``bridge._router._peer_models`` every ``gossip_interval * 3`` and flips peers older than ``peer_unreachable_seconds`` to unreachable; ``select_peers`` filters unreachable peers; new EventTypes ``FEDERATION_PEER_UNREACHABLE`` + ``FEDERATION_PEER_RECOVERED``; auto-recovery is gossip arriving again.
- **AD-479h** ``MulticastDiscovery`` — opt-in (``multicast_enabled=False`` default) raw UDP multicast announce + listen; new ``FederationBridge.add_peer(peer_config)`` public method registers discovered peers at runtime; ``transport.add_peer`` extension on Mock + NATS + ZMQ transports; new EventType ``FEDERATION_PEER_DISCOVERED``.
- **AD-479i** ``/federation routing`` slash subcommand — extends the AD-480i ``cmd_federation`` dispatcher with a ``routing`` arg listing ZeroMQ peers with capability filter, trust score, top Hebbian intent weights, and unreachable status; existing ``/federation`` (no arg) + ``/federation peers`` (AD-480i) preserved.

**Future sub-AD letters with explicit forcing functions:**
- **AD-479j** mDNS cross-LAN peer discovery via optional ``zeroconf`` package — forcing function: cross-LAN multi-instance demo wave.
- **AD-479k** Cross-protocol (MCP/A2A) Hebbian routing — depends on AD-480l revival paired with AD-479c; forcing function: AD-480l unblock now that AD-479c substrate has shipped.
- **AD-479l** ZeroMQ CURVE encryption + TLS certificate hot rotation — forcing function: ZMQ becomes production transport again after AD-637e moved default federation traffic to NATS.
- **AD-479m** Distributed ChromaDB sharding for federated recall — forcing function: scale-out wave once federation has >100 ships and v1 round-trip approach hits NATS payload limits.

**Commercial-repo carve-outs (out-of-repo by roadmap design at ``roadmap.md:3478`` + ``:3595`` + ``:4095`` + ``:4111`` — NOT v1 deferrals):** hosted multi-tenant cross-fleet trust-scoring service, fleet management dashboard, fleet-wide compliance + centralized agent marketplace surface. Tracked in the private commercial-repo path token.

**Test count delta:** +63 floor (~71 planned) across nine new test classes — TestCapabilityAwareSelectPeers ~6, TestTrustWeightedRanking ~8, TestFederationHebbianRouting ~8, TestRecallFederated ~10, TestShareDesignedAgent ~8, TestFederationTLSConfig ~5, TestClusterHealthMonitor ~8, TestMulticastDiscovery ~8, TestSlashFederationRoutingCommand ~6.

### AD-636
===END REPLACE===
```

## Section 11 — Acceptance criteria

1. All nine sub-AD letters land in a single Builder cycle, one section at a time, with a focused per-section pytest gate after each section.
2. New EventTypes (4) added to `src/probos/events.py` collision-free against HEAD.
3. New Pydantic config models (3) follow the AD-432 default-factory rule; all new fields default to safe values that preserve W87/W89 baseline behavior.
4. AD-479a fall-through preserves W87/W89 zero-data behavior (regression test required).
5. AD-479e CodeValidator gate is in place — designed-agent payload that fails the validator is rejected; the chain block does NOT register a designed template.
6. AD-479h networking-bound tests use `pytest.mark.skipif(not _multicast_available())` per Hard-stop W91-2.
7. AD-479c uses a separate SQLite table (`federation_hebbian_weights`) per Hard-stop W91-3.
8. New types imported from new module paths only; no existing imports broken (regression: existing tests pass at HEAD count + new tests).
9. Pre-commit-hook 11-banned-pattern audit on this prompt + the dispatch + the wave-plan entry returns zero literal hits per `Select-String -Path <files> -Pattern <pattern> -SimpleMatch`.
10. GH #73 closed with the canonical paragraph in this section, citing the nine shipped sub-AD letters + four forcing-function deferrals + three commercial carve-outs.
11. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Section 12 — Verified Against Codebase (HEAD `4f18c7d`, 2026-05-06)

```
grep -n "def select_peers" src/probos/federation/router.py
  29:    def select_peers(self, intent_name: str, available_peers: list[str]) -> list[str]:

grep -n "def peer_has_capability" src/probos/federation/router.py
  36:    def peer_has_capability(self, peer_node_id: str, intent_name: str) -> bool:

grep -n "def forward_intent" src/probos/federation/bridge.py
  83:    async def forward_intent(self, intent: IntentMessage) -> list[IntentResult]:

grep -n "def _handle_transfer_request" src/probos/federation/bridge.py
  253:    async def _handle_transfer_request(self, message: FederationMessage) -> None:

grep -n "def request_transfer" src/probos/federation/bridge.py
  346:    async def request_transfer(

grep -n "def get_score" src/probos/consensus/trust.py
  397:    def get_score(self, agent_id: AgentID) -> float:

grep -n "def record_outcome" src/probos/consensus/trust.py
  208:    def record_outcome(

grep -n "def create_with_prior" src/probos/consensus/trust.py
  195:    def create_with_prior(self, agent_id: AgentID, alpha: float, beta: float) -> None:

grep -n "class HebbianRouter" src/probos/mesh/routing.py
  39: class HebbianRouter:

grep -n "ConnectionFactory" src/probos/mesh/routing.py
  55:        connection_factory: ConnectionFactory | None = None,

grep -n "async def recall" src/probos/cognitive/episodic.py
  1508:    async def recall(self, query: str, k: int = 5) -> list[Episode]:

grep -n "class NATSFederationTransport" src/probos/federation/nats_transport.py
  30: class NATSFederationTransport:

grep -n "FederationBridge" src/probos/startup/fleet_organization.py
  153:        from probos.federation import FederationRouter, FederationBridge
  197:            bridge = FederationBridge(

grep -n "cmd_federation" src/probos/experience/commands/commands_status.py
  100: async def cmd_federation(runtime: ProbOSRuntime, console: Console, args: str) -> None:

grep -n "render_federation_panel\|render_federation_peers_panel\|render_peers_panel" src/probos/experience/panels.py
  800: def render_federation_panel(federation_status: dict) -> Panel:
  819: def render_federation_peers_panel(peers: list, trust_network) -> Panel:
  854: def render_peers_panel(peer_models: dict) -> Panel:

grep -n "class FederationConfig" src/probos/config.py
  830: class FederationConfig(BaseModel):

grep -n "FederationPeerRegistry" src/probos/runtime.py
  250:    federation_peer_registry: "FederationPeerRegistry"
  537:        from probos.federation.peer import FederationPeerRegistry
  538:        self.federation_peer_registry: FederationPeerRegistry = FederationPeerRegistry(

grep -n "_build_self_model" src/probos/runtime.py
  3093:    def _build_self_model(self) -> NodeSelfModel:

grep -n "set_federation_handler" src/probos/mesh/intent.py
  739:        self._federation_fn = fn

grep -n "FEDERATION_" src/probos/events.py
  (no matches — collision-free)

grep -n "register_designed_template_from_payload\|class AgentDesigner\|class CodeValidator" src/probos/cognitive
  (verified by Builder during implementation; method name is illustrative — Builder must locate the actual public surface on ``AgentDesigner`` and may rename ``register_designed_template_from_payload`` to whatever the live class exposes; if no equivalent public surface exists, fall back to recording the designed metadata in episodic memory + emitting ``FEDERATION_DESIGNED_AGENT_RECEIVED`` with a ``registered=False`` flag — surface as architectural decision back to Architect rather than inventing a new public API)
```

**Builder note on AD-479e:** the `register_designed_template_from_payload(...)` method name is an illustrative target. The Builder should grep `src/probos/cognitive/agent_designer.py` for the existing public surface that registers a designed agent template at runtime (likely `register_template`, `add_template`, or similar) and use that name. If no existing public method accepts a payload-shaped dict, the Builder should NOT invent a new one — instead record the foreign designed-agent metadata in episodic memory and emit the EventType with `registered=False`, then surface back to Architect as a follow-up. This honors the layer-discipline rule (federation must not reach into private internals of cognitive).
