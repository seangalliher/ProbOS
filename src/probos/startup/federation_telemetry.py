"""Composition helpers for federation avatar telemetry (AD-722b-5a)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from probos.federation.relay import (
    FederationRelayTopic,
    is_safe_relay_node_id,
)
from probos.federation.telemetry_relay import (
    AVATAR_TELEMETRY_TOPIC,
    MAX_TELEMETRY_AGENTS,
    FederationTelemetryRelay,
    RemoteAvatarTelemetryCache,
    TelemetrySnapshotBuilder,
    validate_avatar_telemetry_payload,
)

if TYPE_CHECKING:
    from probos.avatars.events import AvatarEventBus
    from probos.avatars.sampling_state import AvatarSamplingStateMachine
    from probos.config import PeerConfig
    from probos.federation.bridge import FederationBridge
    from probos.substrate.registry import AgentRegistry


def build_federation_avatar_relay_topics(
    *,
    enabled: bool,
    cache: RemoteAvatarTelemetryCache,
) -> tuple[FederationRelayTopic, ...]:
    """Return the one closed avatar topic when the complete feature is on."""
    if not enabled:
        return ()
    return (
        FederationRelayTopic(
            name=AVATAR_TELEMETRY_TOPIC,
            validate_payload=validate_avatar_telemetry_payload,
            sink=cache.ingest,
        ),
    )


async def start_federation_avatar_telemetry(
    *,
    bridge: "FederationBridge | None",
    peers: list["PeerConfig"],
    registry: "AgentRegistry",
    event_bus: "AvatarEventBus",
    sampling_state: "AvatarSamplingStateMachine",
    snapshot_builder: TelemetrySnapshotBuilder,
    diff_enabled: bool,
    diff_threshold: float,
    full_every_n: int,
) -> FederationTelemetryRelay | None:
    """Validate static exports, start producers, and clean before re-raise."""
    if bridge is None:
        return None
    configured = [peer for peer in peers if peer.avatar_telemetry_agent_ids]
    if not configured:
        return None
    if len(configured) > 16:
        raise ValueError("telemetry_peer_cap_exceeded")

    peer_ids: set[str] = set()
    unique_agent_ids: set[str] = set()
    for peer in configured:
        if not is_safe_relay_node_id(peer.node_id):
            raise ValueError(f"telemetry_peer_node_id_invalid:{peer.node_id}")
        if peer.node_id in peer_ids:
            raise ValueError("telemetry_duplicate_peer_node_id")
        peer_ids.add(peer.node_id)
        unique_agent_ids.update(peer.avatar_telemetry_agent_ids)
    if len(unique_agent_ids) > MAX_TELEMETRY_AGENTS:
        raise ValueError("telemetry_agent_cap_exceeded")
    for agent_id in sorted(unique_agent_ids):
        if registry.get(agent_id) is None:
            raise ValueError(f"telemetry_unknown_agent_id:{agent_id}")

    relay = FederationTelemetryRelay(
        snapshot_builder=snapshot_builder,
        event_bus=event_bus,
        sampling_state=sampling_state,
        diff_enabled=diff_enabled,
        diff_threshold=diff_threshold,
        full_every_n=full_every_n,
    )
    try:
        for peer in configured:
            relay.register_peer(
                peer.node_id,
                peer.avatar_telemetry_agent_ids,
            )

        async def _emit_to_bridge(
            peer_id: str,
            payload: dict[str, object],
        ) -> bool:
            return await bridge.relay_one_way(
                peer_id,
                AVATAR_TELEMETRY_TOPIC,
                payload,
            )

        relay.set_emit_callback(_emit_to_bridge)
        await relay.start()
        return relay
    except BaseException:
        await relay.stop()
        raise