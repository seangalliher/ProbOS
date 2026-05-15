# AD-722b-5 — Federation cross-mesh telemetry push

**Wave:** 162
**Closes:** #602
**Status:** **CONDITIONAL** — see Section 0. Build only if AD-722b-1c (federation-bridge JWT verification, per DECISIONS.md:2854) has matured to the point where the bridge transport supports authenticated relay of WS frames. Otherwise: STOP and surface to Architect.
**Dependencies:** AD-722b (Wave 142 — per-agent WS push); AD-722b-4 (Wave 160 — fleet-wide WS); AD-722b-1 (Wave 161 — local crew-scope auth); AD-480 family (federation framework + FederationBridge + NATS transport).
**Estimated tests:** +8 pytest (+0 vitest — server-side relay only; UI consumer is forward marker AD-722b-5a).
**Scope tag:** Server-only. No new pip/npm deps. Apache 2.0. Federation cross-mesh feature — touches `federation/` boundary.

---

## Section 0 — Pre-flight CONDITIONAL gate

This AD requires authenticated cross-mesh transport for WebSocket-style streaming frames. The AD-722b-1 (Wave 161) `crew_scope_token` is in-mesh only; federation auth (AD-480e/g for A2A peer trust, AD-480a for MCP) operates per-message, not per-stream.

**Builder pre-flight:**
1. Grep `src/probos/federation/bridge.py` for any existing streaming/relay support (look for `forward_stream`, `relay_ws`, or similar).
2. If `FederationBridge` only supports `forward_intent` (single-shot RPC-style), STOP. Surface to Architect. This AD becomes "AD-722b-5 design phase" — write a design doc to `docs/development/federation-streaming.md` and exit.
3. If a streaming primitive exists, proceed with Sections 1-5.

The user-facing problem (cross-mesh telemetry observability) is real; the right shape depends on what the federation transport already provides. Do NOT invent a new streaming wire format inside this AD — that's an AD-480-family scope expansion, not a sub-AD of 722b.

---

## Problem

AD-722b v1 (Wave 142) shipped a per-agent WS endpoint `/api/agent/{id}/avatar-telemetry-stream`; AD-722b-4 (Wave 160) added the fleet endpoint `/api/agent/avatar-telemetry/stream`. Both serve **local HXI only** — Captain in Mesh A sees Mesh A's agents.

The federation vision (AD-480 family) is multi-mesh: Maya in Mesh A interacts with Ezri in Mesh B. For Maya's HXI to surface Ezri's avatar telemetry, Mesh B must push telemetry frames across the federation bridge to Mesh A's HXI consumer.

Forward marker [#602](https://github.com/seangalliher/ProbOS/issues/602). Issue body confirms: *"Hard precondition: AD-722b-1 (auth) must ship first. AD-480 federation framework provides the transport surface."*

---

## Solution overview

1. New `FederationTelemetryRelay` (sibling of FederationBridge's intent forwarding) that subscribes to local telemetry events and re-emits them to peer meshes via the federation transport.
2. Each peer registration carries a `subscribe_telemetry: list[str]` field — list of remote agent_ids whose telemetry this peer wants. Empty list = no subscription.
3. Inbound side: a peer relay handler receives federated telemetry frames and re-injects them into the local fleet WS broadcaster with an `origin_mesh_id` tag — so Mesh A's HXI knows "this snapshot is from Mesh B."
4. Auth: every cross-mesh frame is signed using the existing AD-480e/g peer trust mechanism. The receiver verifies the signature before broadcasting locally; signature failures log + drop (never raise, never surface to UI).
5. Rate-limit: per-peer outbound rate cap to prevent a chatty mesh from flooding peers — default 10 frames/sec/peer (configurable).

### What this does NOT change

- Per-agent / fleet WS endpoints (already shipped).
- AD-722b-1 local crew-scope auth (unchanged — applies to LOCAL HXI connections).
- AD-480 federation transport primitives (this AD consumes them, doesn't extend them).
- The HXI render path — fleet WS hook (AD-722b-4a Wave 161) already handles frames; this AD just ensures REMOTE frames also arrive on the local fleet WS with an `origin_mesh_id` tag.
- AD-731 attachment-ref invariant — telemetry frames already use refs not bytes.

---

## Section 1 — `FederationTelemetryRelay` outbound

NEW FILE: `src/probos/federation/telemetry_relay.py`

Subscribes to the existing AD-722b broadcaster. For each frame, checks which peers subscribe to that `agent_id` and emits via `FederationBridge.forward_telemetry(peer_id, frame)`.

```python
"""AD-722b-5: federation cross-mesh telemetry push relay.

Wires the existing AD-722b telemetry broadcaster to the federation bridge,
so remote peers can subscribe to specific agent_ids and receive
WS-like telemetry frames over the federation transport.
"""
from __future__ import annotations

import asyncio
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
    def __init__(
        self,
        bridge,  # FederationBridge
        max_per_sec_per_peer: int = 10,
    ):
        self._bridge = bridge
        self._subs: dict[str, PeerTelemetrySubscription] = {}
        self._rate_state: dict[str, deque[float]] = {}
        self._max_per_sec = max_per_sec_per_peer

    def register_peer(self, peer_id: str, agent_ids: list[str]) -> None:
        self._subs[peer_id] = PeerTelemetrySubscription(
            peer_id=peer_id, agent_ids=frozenset(agent_ids),
        )

    async def on_local_telemetry_frame(
        self,
        agent_id: str,
        frame_type: str,  # "snapshot" | "diff" | "ping"
        payload: dict,
    ) -> None:
        """Hook called by AD-722b broadcaster for every locally-emitted frame."""
        for sub in list(self._subs.values()):
            if agent_id not in sub.agent_ids:
                continue
            if not self._under_rate_limit(sub.peer_id):
                logger.debug(
                    "AD-722b-5: rate-limited frame to peer=%s agent_id=%s",
                    sub.peer_id, agent_id,
                )
                continue
            try:
                await self._bridge.forward_telemetry(
                    peer_id=sub.peer_id,
                    payload={
                        "frame_type": frame_type,
                        "agent_id": agent_id,
                        "data": payload,
                        "origin_mesh_id": self._bridge.local_mesh_id,
                    },
                )
                self._note_send(sub.peer_id)
            except Exception:
                logger.warning(
                    "AD-722b-5: federation forward_telemetry failed peer=%s",
                    sub.peer_id, exc_info=True,
                )

    def _under_rate_limit(self, peer_id: str) -> bool:
        now = time.time()
        window = self._rate_state.setdefault(peer_id, deque())
        cutoff = now - 1.0
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) < self._max_per_sec

    def _note_send(self, peer_id: str) -> None:
        self._rate_state.setdefault(peer_id, deque()).append(time.time())
```

Builder: `FederationBridge.forward_telemetry` is a NEW method this AD introduces on the bridge (Section 2). The above class consumes it.

---

## Section 2 — `FederationBridge.forward_telemetry` + inbound handler

Add to `src/probos/federation/bridge.py`:

```python
async def forward_telemetry(
    self,
    *,
    peer_id: str,
    payload: dict,
) -> None:
    """AD-722b-5: relay an avatar telemetry frame to a peer mesh.

    Uses the same signed-envelope transport as forward_intent. Drops silently
    on transport failure (telemetry is best-effort observability, never
    blocks the local broadcaster).
    """
    envelope = self._sign_envelope(
        recipient=peer_id,
        kind="telemetry",
        payload=payload,
    )
    await self._transport.send(peer_id, envelope)


async def on_inbound_telemetry(self, envelope: dict) -> None:
    """Inbound handler — called by the transport layer for kind=telemetry envelopes."""
    if not self._verify_envelope(envelope):
        logger.warning(
            "AD-722b-5: dropping unverified telemetry envelope from=%s",
            envelope.get("sender"),
        )
        return
    payload = envelope["payload"]
    # Re-inject into the local fleet broadcaster with origin_mesh_id tag preserved.
    await self._fleet_broadcaster.broadcast_remote(
        agent_id=payload["agent_id"],
        frame_type=payload["frame_type"],
        data=payload["data"],
        origin_mesh_id=payload["origin_mesh_id"],
    )
```

Builder: `_sign_envelope` / `_verify_envelope` should already exist for `forward_intent` (AD-480e/g). Confirm by grep before writing — reuse not re-implement.

---

## Section 3 — `FleetBroadcaster.broadcast_remote`

In whichever module hosts the AD-722b-4 fleet broadcaster (find it via grep for `avatar-telemetry/stream`), add:

```python
async def broadcast_remote(
    self,
    agent_id: str,
    frame_type: str,
    data: dict,
    origin_mesh_id: str,
) -> None:
    """AD-722b-5: emit a frame received from a remote mesh.

    Frames are tagged with origin_mesh_id so the HXI can render the source.
    LOCAL frames retain origin_mesh_id == self.local_mesh_id.
    """
    await self._broadcast({
        "type": frame_type,
        "agent_id": agent_id,
        "origin_mesh_id": origin_mesh_id,
        **data,
    })
```

Local frames (the existing AD-722b-4 path) should also carry `origin_mesh_id == self.local_mesh_id` — Builder: update the LOCAL broadcast call site to include the tag. This is a frame-contract change; UI consumers (Wave 161 AD-722b-4a hook) must tolerate the extra field. Vitest tests that snapshot the frame shape may need an update — surface to Architect if any vitest fails.

---

## Section 4 — Peer subscription config

In `src/probos/config.py`, extend the federation peer config (AD-480e shape):

```python
# AD-722b-5: per-peer telemetry subscription. Empty list = no subscription.
subscribe_telemetry: list[str] = Field(default_factory=list)
```

Builder: locate the existing A2A peer config (line 1439-1456 per grep). Add the field with `default_factory=list` (Pydantic v2 — avoid mutable default anti-pattern).

---

## Section 5 — Wire from runtime

In `runtime.py`, after the existing `FederationBridge` construction, construct the relay and subscribe to the fleet broadcaster:

```python
from probos.federation.telemetry_relay import FederationTelemetryRelay

self.federation_telemetry_relay = FederationTelemetryRelay(bridge=self.federation_bridge)
for peer in self.config.federation.a2a.outbound_peers:
    if peer.subscribe_telemetry:
        self.federation_telemetry_relay.register_peer(peer.peer_id, peer.subscribe_telemetry)
self.fleet_broadcaster.on_frame(self.federation_telemetry_relay.on_local_telemetry_frame)
```

`on_frame` is a new subscription hook on the fleet broadcaster — Builder: if the broadcaster doesn't have an existing observer interface, add one (or reuse an existing `register_listener` pattern).

---

## Tests

`tests/test_ad722b_5_federation_telemetry.py` — 8 tests:

1. `test_relay_forwards_subscribed_agent_only` — Mesh A peer subscribes to agent X; emit telemetry for X and Y; only X gets forwarded.
2. `test_relay_drops_unsubscribed`.
3. `test_rate_limit_10_per_sec_per_peer` — 11 frames in 1s; 11th dropped (with debug log).
4. `test_inbound_unverified_envelope_dropped` — envelope signature fails verification; bridge logs warning, no local broadcast.
5. `test_inbound_verified_envelope_broadcasts_locally_with_origin_tag` — happy path; LOCAL fleet WS receives the frame with `origin_mesh_id=<remote>`.
6. `test_outbound_transport_failure_logs_and_continues` — `_transport.send` raises; relay catches, never propagates.
7. `test_local_frames_carry_local_mesh_id` — frame-contract regression: LOCAL path includes `origin_mesh_id`.
8. `test_peer_subscribe_telemetry_config_default_empty` — Pydantic default_factory=list (no mutable-default anti-pattern).

---

## Tracking

- `PROGRESS.md` — Wave 162 bullet.
- `docs/development/roadmap.md` — flip AD-722b-5 row to SHIPPED Wave 162; file forward marker AD-722b-5a (HXI surface to render remote agents with `origin_mesh_id` badge; technical trigger: when ≥2 meshes federate AND ≥1 cross-mesh telemetry subscription exists).
- `DECISIONS.md` — append entry; cross-link to AD-480e/g peer-trust record.

---

## Acceptance criteria

- `FederationTelemetryRelay` lands at `src/probos/federation/telemetry_relay.py`.
- `FederationBridge.forward_telemetry` + `on_inbound_telemetry` methods exist.
- `FleetBroadcaster.broadcast_remote` exists; LOCAL frames also carry `origin_mesh_id` tag (frame-contract update).
- Per-peer subscription config field lands on the A2A peer model.
- Signed-envelope verification reuses AD-480e/g primitives (not reimplemented).
- Rate limit 10 frames/sec/peer enforced.
- 8 new pytest tests green at `-n 0` and parallel.
- Vitest frame-shape snapshots (if any) updated for the `origin_mesh_id` field.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-15)

- `src/probos/federation/bridge.py:25` — `class FederationBridge:` confirmed.
- `src/probos/federation/bridge.py:1` — `"FederationBridge — connects the local IntentBus to the federation transport layer."` confirmed.
- `src/probos/agents/federation_recall_agent.py:6` — `FederationBridge.forward_intent` wired into `IntentBus._federation_fn` confirmed (this AD adds `forward_telemetry` as a sibling).
- `src/probos/config.py:1439-1456` — AD-480e outbound peer + A2A inbound/outbound shape confirmed.
- `src/probos/federation/nats_transport.py:34` — transport abstraction `FederationBridge can use any interchangeably` confirmed.
- AD-722b WS surface confirmed in `src/probos/avatars/telemetry.py:25,36` and roadmap AD-722b-4 SHIPPED Wave 160.
