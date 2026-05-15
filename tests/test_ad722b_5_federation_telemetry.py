"""AD-722b-5: federation cross-mesh telemetry relay tests (local-mesh portion).

The federation hop is forward-marked (AD-722b-5a) since FederationBridge
exposes only forward_intent today. These tests verify the local
plumbing: subscription, rate-limit, agent_id filter, dispatch shape.
"""
from __future__ import annotations

import time

import pytest

from probos.federation.telemetry_relay import (
    FederationTelemetryRelay,
    PeerTelemetrySubscription,
)


@pytest.mark.asyncio
async def test_register_peer_records_subscription() -> None:
    relay = FederationTelemetryRelay()
    relay.register_peer("mesh-b", ["ezri", "echo"])
    assert "mesh-b" in relay._subs
    sub = relay._subs["mesh-b"]
    assert sub.agent_ids == frozenset({"ezri", "echo"})


@pytest.mark.asyncio
async def test_emit_filters_by_agent_id_subscription() -> None:
    relay = FederationTelemetryRelay()
    relay.register_peer("mesh-b", ["ezri"])
    relay.register_peer("mesh-c", ["echo"])

    dispatched = await relay.on_local_telemetry_frame(
        agent_id="ezri", frame_type="snapshot", payload={"emotion": "warm"},
    )
    assert dispatched == 1
    log = relay.dispatch_log()
    assert len(log) == 1
    peer_id, agent_id, frame = log[0]
    assert peer_id == "mesh-b"
    assert agent_id == "ezri"
    assert frame["type"] == "snapshot"
    assert frame["payload"] == {"emotion": "warm"}


@pytest.mark.asyncio
async def test_emit_no_subscribers_returns_zero() -> None:
    relay = FederationTelemetryRelay()
    dispatched = await relay.on_local_telemetry_frame(
        agent_id="orphan", frame_type="snapshot", payload={},
    )
    assert dispatched == 0


@pytest.mark.asyncio
async def test_emit_multicast_when_two_peers_subscribe_same_agent() -> None:
    relay = FederationTelemetryRelay()
    relay.register_peer("mesh-b", ["ezri"])
    relay.register_peer("mesh-c", ["ezri"])
    dispatched = await relay.on_local_telemetry_frame(
        agent_id="ezri", frame_type="diff", payload={"emotion": "calm"},
    )
    assert dispatched == 2
    peers = {entry[0] for entry in relay.dispatch_log()}
    assert peers == {"mesh-b", "mesh-c"}


@pytest.mark.asyncio
async def test_rate_limit_caps_outbound_per_peer() -> None:
    relay = FederationTelemetryRelay(max_per_sec_per_peer=3)
    relay.register_peer("mesh-b", ["ezri"])
    # 3 frames go through; 4th is rate-limited.
    for _ in range(3):
        d = await relay.on_local_telemetry_frame(
            agent_id="ezri", frame_type="snapshot", payload={},
        )
        assert d == 1
    d4 = await relay.on_local_telemetry_frame(
        agent_id="ezri", frame_type="snapshot", payload={},
    )
    assert d4 == 0
    assert len(relay.dispatch_log()) == 3


@pytest.mark.asyncio
async def test_rate_limit_recovers_after_window(monkeypatch) -> None:
    relay = FederationTelemetryRelay(max_per_sec_per_peer=1)
    relay.register_peer("mesh-b", ["ezri"])
    await relay.on_local_telemetry_frame(
        agent_id="ezri", frame_type="snapshot", payload={},
    )
    d = await relay.on_local_telemetry_frame(
        agent_id="ezri", frame_type="snapshot", payload={},
    )
    assert d == 0
    # Advance clock past the 1s window.
    import probos.federation.telemetry_relay as mod
    real_time = time.time
    monkeypatch.setattr(mod.time, "time", lambda: real_time() + 2.0)
    d_after = await relay.on_local_telemetry_frame(
        agent_id="ezri", frame_type="snapshot", payload={},
    )
    assert d_after == 1


@pytest.mark.asyncio
async def test_unregister_peer_stops_emits() -> None:
    relay = FederationTelemetryRelay()
    relay.register_peer("mesh-b", ["ezri"])
    relay.unregister_peer("mesh-b")
    d = await relay.on_local_telemetry_frame(
        agent_id="ezri", frame_type="snapshot", payload={},
    )
    assert d == 0


@pytest.mark.asyncio
async def test_custom_emit_callback_invoked_with_full_shape() -> None:
    """AD-722b-5a hookup contract: when a real callback is set, it
    receives (peer_id, agent_id, frame_type, payload) and the default
    dispatch log is NOT used."""
    captured: list = []

    async def my_emit(peer_id, agent_id, frame_type, payload):
        captured.append((peer_id, agent_id, frame_type, payload))

    relay = FederationTelemetryRelay()
    relay.set_emit_callback(my_emit)
    relay.register_peer("mesh-b", ["ezri"])
    await relay.on_local_telemetry_frame(
        agent_id="ezri", frame_type="snapshot", payload={"x": 1},
    )
    assert len(captured) == 1
    assert captured[0] == ("mesh-b", "ezri", "snapshot", {"x": 1})
    assert relay.dispatch_log() == []  # default callback not invoked
