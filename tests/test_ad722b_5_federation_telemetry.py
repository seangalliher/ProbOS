"""AD-722b-5: federation cross-mesh telemetry relay tests (local-mesh portion).

The federation hop is forward-marked (AD-722b-5a) since FederationBridge
exposes only forward_intent today. These tests verify the local
plumbing: subscription, rate-limit, agent_id filter, dispatch shape.
"""
from __future__ import annotations

import pytest

import probos.federation.telemetry_relay as relay_module
from probos.federation.telemetry_relay import (
    FederationTelemetryRelay,
    PeerTelemetrySubscription,
)


_AGENT_ID = "ezri"


def _valid_snapshot_data() -> dict:
    return {
        "expression_resting": "neutral",
        "current_signals": {
            "trust_delta": 0.0,
            "load": 0.0,
            "working_state": "idle",
            "tier3_alert": False,
        },
        "mouth_active": False,
        "applied_modulation": None,
        "dsl_summary": None,
        "last_observed_at": 1.0,
        "degraded_reasons": [],
        "sampling_rate_ms": 250,
        "sampling_tier": "high",
    }


def _valid_diff_data() -> dict:
    return {"mouth_active": True}


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
    await relay.start()
    try:
        dispatched = await relay.on_local_telemetry_frame(
            agent_id="ezri",
            frame_type="snapshot",
            payload=_valid_snapshot_data(),
        )
        assert dispatched == 1
        log = relay.dispatch_log()
        assert len(log) == 1
        peer_id, frame = log[0]
        assert peer_id == "mesh-b"
        assert frame["agent_id"] == "ezri"
        assert frame["frame_type"] == "snapshot"
        assert frame["data"] == _valid_snapshot_data()
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_emit_no_subscribers_returns_zero() -> None:
    relay = FederationTelemetryRelay()
    await relay.start()
    try:
        dispatched = await relay.on_local_telemetry_frame(
            agent_id="orphan",
            frame_type="snapshot",
            payload=_valid_snapshot_data(),
        )
        assert dispatched == 0
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_emit_multicast_when_two_peers_subscribe_same_agent() -> None:
    relay = FederationTelemetryRelay()
    relay.register_peer("mesh-b", ["ezri"])
    relay.register_peer("mesh-c", ["ezri"])
    await relay.start()
    try:
        dispatched = await relay.on_local_telemetry_frame(
            agent_id="ezri",
            frame_type="diff",
            payload=_valid_diff_data(),
        )
        assert dispatched == 2
        peers = {entry[0] for entry in relay.dispatch_log()}
        assert peers == {"mesh-b", "mesh-c"}
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_rate_limit_caps_outbound_per_peer() -> None:
    relay = FederationTelemetryRelay(max_per_sec_per_peer=3)
    relay.register_peer("mesh-b", ["ezri"])
    await relay.start()
    try:
        # 3 frames go through; 4th is rate-limited.
        for _ in range(3):
            d = await relay.on_local_telemetry_frame(
                agent_id="ezri",
                frame_type="snapshot",
                payload=_valid_snapshot_data(),
            )
            assert d == 1
        d4 = await relay.on_local_telemetry_frame(
            agent_id="ezri",
            frame_type="snapshot",
            payload=_valid_snapshot_data(),
        )
        assert d4 == 0
        assert len(relay.dispatch_log()) == 3
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_rate_limit_recovers_after_window(monkeypatch) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr(
        relay_module.time,
        "monotonic",
        lambda: clock["now"],
    )
    relay = FederationTelemetryRelay(max_per_sec_per_peer=1)
    relay.register_peer("mesh-b", ["ezri"])
    await relay.start()
    try:
        await relay.on_local_telemetry_frame(
            agent_id="ezri",
            frame_type="snapshot",
            payload=_valid_snapshot_data(),
        )
        d = await relay.on_local_telemetry_frame(
            agent_id="ezri",
            frame_type="snapshot",
            payload=_valid_snapshot_data(),
        )
        assert d == 0
        clock["now"] += 1.01
        d_after = await relay.on_local_telemetry_frame(
            agent_id="ezri",
            frame_type="snapshot",
            payload=_valid_snapshot_data(),
        )
        assert d_after == 1
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_unregister_peer_stops_emits() -> None:
    relay = FederationTelemetryRelay()
    relay.register_peer("mesh-b", ["ezri"])
    relay.unregister_peer("mesh-b")
    await relay.start()
    try:
        d = await relay.on_local_telemetry_frame(
            agent_id="ezri",
            frame_type="snapshot",
            payload=_valid_snapshot_data(),
        )
        assert d == 0
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_custom_emit_callback_invoked_with_full_shape() -> None:
    """The typed callback receives peer_id and one exact topic payload."""
    captured: list = []

    async def my_emit(peer_id: str, payload: dict) -> bool:
        captured.append((peer_id, payload))
        return True

    relay = FederationTelemetryRelay()
    relay.set_emit_callback(my_emit)
    relay.register_peer("mesh-b", ["ezri"])
    await relay.start()
    try:
        await relay.on_local_telemetry_frame(
            agent_id="ezri",
            frame_type="snapshot",
            payload=_valid_snapshot_data(),
        )
        assert len(captured) == 1
        assert captured[0][0] == "mesh-b"
        assert captured[0][1]["agent_id"] == "ezri"
        assert captured[0][1]["frame_type"] == "snapshot"
        assert captured[0][1]["data"] == _valid_snapshot_data()
        assert relay.dispatch_log() == []
    finally:
        await relay.stop()
