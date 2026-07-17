"""AD-722b-5a: federation avatar telemetry relay tests."""

from __future__ import annotations

import asyncio
import inspect
import math
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import probos.federation.telemetry_relay as relay_module
from probos.avatars.events import AvatarEventBus
from probos.avatars.sampling_state import AvatarSamplingStateMachine
from probos.avatars.telemetry import (
    AgentSignalsSnapshot,
    AvatarTelemetrySnapshot,
    DslSummarySnapshot,
    ModulationSnapshot,
)
from probos.avatars.telemetry_frames import (
    AvatarTelemetryFrame,
    avatar_telemetry_frame_to_ws,
    is_safe_avatar_agent_id,
    project_avatar_telemetry_data_for_federation,
    select_avatar_telemetry_frame,
    validate_avatar_telemetry_data,
)
from probos.config import (
    FederationConfig,
    MedicalConfig,
    PeerConfig,
    SamplingRatesConfig,
    ScalingConfig,
    SelfModConfig,
    SystemConfig,
    UtilityAgentsConfig,
)
from probos.federation.relay import (
    FederationRelayTopic,
    finalize_relay_wire_payload,
)
from probos.federation.telemetry_relay import (
    AVATAR_TELEMETRY_TOPIC,
    FederationTelemetryRelay,
    RemoteAvatarTelemetryCache,
    parse_avatar_telemetry_payload,
    validate_avatar_telemetry_payload,
)
from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
from probos.mesh.signal import SignalManager
from probos.runtime import ProbOSRuntime
from probos.startup.federation_telemetry import (
    build_federation_avatar_relay_topics,
    start_federation_avatar_telemetry,
)
from probos.startup.fleet_organization import organize_fleet
from probos.startup.results import FleetOrganizationResult
from probos.substrate.agent import BaseAgent
from probos.substrate.pool_group import PoolGroupRegistry
from probos.substrate.registry import AgentRegistry
from probos.types import NodeSelfModel


_STREAM_ID = "0123456789abcdef0123456789abcdef"
_AGENT_ID = "counselor_bridge_0_ab12cd34"
_MAX_SEQUENCE = 9_007_199_254_740_991
_MAX_SAMPLING_RATE_MS = 2_147_483_647


class _StrSubclass(str):
    pass


class _DictSubclass(dict):
    def keys(self) -> Any:
        raise AssertionError("dict subclass override invoked")


class _ListSubclass(list):
    def __iter__(self) -> Any:
        raise AssertionError("list subclass override invoked")


class _IntSubclass(int):
    pass


class _FloatSubclass(float):
    pass


class _FakeAgent(BaseAgent):
    agent_type = "test_avatar_agent"

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return intent

    async def decide(self, observation: Any) -> Any:
        return observation

    async def act(self, plan: Any) -> Any:
        return plan

    async def report(self, result: Any) -> dict[str, Any]:
        return {"result": result}


class _AcceptingBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.stopped = False

    async def relay_one_way(
        self,
        peer_id: str,
        topic: str,
        payload: dict[str, Any],
    ) -> bool:
        self.calls.append((peer_id, topic, payload))
        return True

    async def stop(self) -> None:
        self.stopped = True


class _FakeTransport:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def _snapshot(
    *,
    agent_id: str = _AGENT_ID,
    palette: str = "teal",
    trust_delta: float = 0.0,
    observed_at: float = 1_000.0,
    sampling_rate_ms: int = 250,
    sampling_tier: str = "high",
) -> AvatarTelemetrySnapshot:
    return AvatarTelemetrySnapshot(
        agent_id=agent_id,
        expression_resting="neutral",
        current_signals=AgentSignalsSnapshot(
            trust_delta=trust_delta,
            load=0.25,
            working_state="responding",
            tier3_alert=False,
        ),
        mouth_active=True,
        applied_modulation=ModulationSnapshot(
            pitch_factor=1.0,
            rate_factor=1.1,
            volume_factor=0.8,
            fired_rules=("responding_rate", "intent_warm"),
        ),
        dsl_summary=DslSummarySnapshot(
            body_type="average",
            hair_style="short",
            primary_color="#A1b2C3",
            outfit_style="uniform",
            color_palette_hint=palette,
        ),
        last_observed_at=observed_at,
        degraded_reasons=("crew_profile_seeded",),
        sampling_rate_ms=sampling_rate_ms,
        sampling_tier=sampling_tier,
    )


def _snapshot_data(**kwargs: Any) -> dict[str, Any]:
    data = _snapshot(**kwargs).to_dict()
    data.pop("agent_id")
    return data


def _payload(
    *,
    agent_id: str = _AGENT_ID,
    frame_type: str = "snapshot",
    stream_id: str = _STREAM_ID,
    sequence: int = 0,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "frame_type": frame_type,
        "stream_id": stream_id,
        "sequence": sequence,
        "data": _snapshot_data() if data is None else data,
    }


def _diff_data(**changes: Any) -> dict[str, Any]:
    return changes or {"mouth_active": False}


def _system_config(
    *,
    node_id: str,
    peers: list[PeerConfig],
) -> SystemConfig:
    return SystemConfig(
        federation=FederationConfig(
            enabled=True,
            node_id=node_id,
            peers=peers,
            forward_timeout_ms=100,
            gossip_interval_seconds=1_000.0,
            validate_remote_results=False,
        ),
        scaling=ScalingConfig(enabled=False),
        utility_agents=UtilityAgentsConfig(enabled=False),
        medical=MedicalConfig(enabled=False),
        self_mod=SelfModConfig(enabled=False),
    )


async def _organize_node(
    *,
    config: SystemConfig,
    nats_bus: MockNATSBus,
    topics: tuple[FederationRelayTopic, ...],
) -> FleetOrganizationResult:
    return await organize_fleet(
        config=config,
        pools={},
        pool_groups=PoolGroupRegistry(),
        escalation_manager=SimpleNamespace(),
        intent_bus=IntentBus(SignalManager()),
        trust_network=SimpleNamespace(),
        llm_client=SimpleNamespace(),
        build_pool_intent_map_fn=dict,
        find_consensus_pools_fn=set,
        build_self_model_fn=lambda: NodeSelfModel(
            node_id=config.federation.node_id,
        ),
        validate_remote_result_fn=None,
        attachment_resolver_fn=None,
        relay_topics=topics,
        nats_bus=nats_bus,
    )


async def _stop_organized(result: FleetOrganizationResult | None) -> None:
    if result is None:
        return
    if result.federation_bridge is not None:
        await result.federation_bridge.stop()
    if result.federation_transport is not None:
        await result.federation_transport.stop()


async def _wait_until(predicate: Any, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition_not_reached")
        await asyncio.sleep(0.01)


def _sampling_state() -> AvatarSamplingStateMachine:
    return AvatarSamplingStateMachine(
        SamplingRatesConfig(high_ms=250, normal_ms=500, low_ms=1_000),
    )


async def _start_manual_relay(
    *,
    max_per_sec: int = 10,
    callback: Any | None = None,
    peers: tuple[str, ...] = ("node-b",),
) -> FederationTelemetryRelay:
    relay = FederationTelemetryRelay(max_per_sec_per_peer=max_per_sec)
    if callback is not None:
        relay.set_emit_callback(callback)
    for peer_id in peers:
        relay.register_peer(peer_id, [_AGENT_ID])
    await relay.start()
    return relay


# ---------------------------------------------------------------------------
# A. Headline production composition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_browser_two_mesh_composition_delivers_initial_snapshot_to_remote_cache() -> None:
    shared_bus = MockNATSBus()
    await shared_bus.start()
    agent = _FakeAgent(agent_id=_AGENT_ID, pool="bridge")
    registry = AgentRegistry()
    await registry.register(agent)
    event_bus = AvatarEventBus()
    sampling_state = _sampling_state()
    receiver_cache = RemoteAvatarTelemetryCache(max_entries=256)
    origin_cache = RemoteAvatarTelemetryCache(max_entries=256)
    origin_config = _system_config(
        node_id="node-a",
        peers=[PeerConfig(
            node_id="node-b",
            address="tcp://127.0.0.1:65001",
            avatar_telemetry_agent_ids=[_AGENT_ID],
        )],
    )
    receiver_config = _system_config(
        node_id="node-b",
        peers=[PeerConfig(
            node_id="node-a",
            address="tcp://127.0.0.1:65002",
        )],
    )
    origin = None
    receiver = None
    relay = None

    async def _builder(agent_id: str) -> AvatarTelemetrySnapshot:
        assert agent_id == _AGENT_ID
        return _snapshot(agent_id=agent_id)

    try:
        origin = await _organize_node(
            config=origin_config,
            nats_bus=shared_bus,
            topics=build_federation_avatar_relay_topics(
                enabled=True,
                cache=origin_cache,
            ),
        )
        receiver = await _organize_node(
            config=receiver_config,
            nats_bus=shared_bus,
            topics=build_federation_avatar_relay_topics(
                enabled=True,
                cache=receiver_cache,
            ),
        )
        relay = await start_federation_avatar_telemetry(
            bridge=origin.federation_bridge,
            peers=origin_config.federation.peers,
            registry=registry,
            event_bus=event_bus,
            sampling_state=sampling_state,
            snapshot_builder=_builder,
            diff_enabled=True,
            diff_threshold=0.05,
            full_every_n=10,
        )

        await _wait_until(
            lambda: receiver_cache.get("node-a", _AGENT_ID) is not None,
        )

        record = receiver_cache.get("node-a", _AGENT_ID)
        assert record is not None
        assert record["source_node"] == "node-a"
        assert record["agent_id"] == _AGENT_ID
        assert record["snapshot"]["agent_id"] == _AGENT_ID
        assert receiver_cache.get("decoy", _AGENT_ID) is None
        assert receiver_cache.get("node-a", "decoy") is None
        assert event_bus.subscriber_count(_AGENT_ID) == 1
    finally:
        if relay is not None:
            await relay.stop()
        await _stop_organized(receiver)
        await _stop_organized(origin)
        await shared_bus.stop()


@pytest.mark.asyncio
async def test_no_browser_event_notify_delivers_contiguous_diff() -> None:
    snapshots = [
        _snapshot(trust_delta=0.0),
        _snapshot(trust_delta=0.5, observed_at=1_001.0),
    ]
    emitted: list[dict[str, Any]] = []
    event_bus = AvatarEventBus()

    async def _builder(_agent_id: str) -> AvatarTelemetrySnapshot:
        return snapshots.pop(0) if len(snapshots) > 1 else snapshots[0]

    async def _emit(_peer_id: str, payload: dict[str, Any]) -> bool:
        emitted.append(payload)
        return True

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=_sampling_state(),
        diff_enabled=True,
        diff_threshold=0.05,
        full_every_n=10,
    )
    relay.register_peer("node-b", [_AGENT_ID])
    relay.set_emit_callback(_emit)
    try:
        await relay.start()
        await _wait_until(lambda: len(emitted) == 1)
        event_bus.notify(_AGENT_ID)
        await _wait_until(lambda: len(emitted) == 2)
        assert emitted[0]["frame_type"] == "snapshot"
        assert emitted[1]["frame_type"] == "diff"
        assert emitted[1]["sequence"] == emitted[0]["sequence"] + 1
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_receiver_only_empty_exports_register_topic_without_producer() -> None:
    cache = RemoteAvatarTelemetryCache(max_entries=256)
    topics = build_federation_avatar_relay_topics(enabled=True, cache=cache)
    relay = await start_federation_avatar_telemetry(
        bridge=_AcceptingBridge(),
        peers=[PeerConfig(node_id="node-a", address="tcp://127.0.0.1:1")],
        registry=AgentRegistry(),
        event_bus=AvatarEventBus(),
        sampling_state=_sampling_state(),
        snapshot_builder=lambda _agent_id: None,  # not invoked
        diff_enabled=True,
        diff_threshold=0.05,
        full_every_n=10,
    )
    assert len(topics) == 1
    assert relay is None


def test_default_config_has_empty_exports_and_disabled_federation() -> None:
    config = SystemConfig()
    assert config.federation.enabled is False
    assert all(not peer.avatar_telemetry_agent_ids for peer in config.federation.peers)


# ---------------------------------------------------------------------------
# B. Exact semantic schema, palette policy B, and privacy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("frame_type", ["snapshot", "diff"])
def test_exact_valid_payload_accepts(frame_type: str) -> None:
    data = _snapshot_data() if frame_type == "snapshot" else _diff_data()
    payload = _payload(frame_type=frame_type, data=data)
    assert validate_avatar_telemetry_payload(payload) is True
    assert parse_avatar_telemetry_payload(payload) == payload


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {key: item for key, item in value.items() if key != "agent_id"},
        lambda value: {**value, "extra": 1},
        lambda value: _DictSubclass(value),
        lambda value: {1: value["agent_id"], **{k: v for k, v in value.items() if k != "agent_id"}},
        lambda value: {**value, "agent_id": _StrSubclass(value["agent_id"])},
        lambda value: {**value, "frame_type": _StrSubclass("snapshot")},
        lambda value: {**value, "stream_id": _StrSubclass(value["stream_id"])},
        lambda value: {**value, "sequence": _IntSubclass(0)},
        lambda value: {**value, "data": _DictSubclass(value["data"])},
    ],
)
def test_top_level_exact_shape_rejects(mutation: Any) -> None:
    value = mutation(_payload())
    assert validate_avatar_telemetry_payload(value) is False
    assert parse_avatar_telemetry_payload(value) is None


@pytest.mark.parametrize(
    ("agent_id", "expected"),
    [
        ("a", True),
        ("A" * 128, True),
        ("", False),
        ("a" * 129, False),
        ("a/b", False),
        ("a\\b", False),
        ("a:b", False),
        ("a b", False),
        ("a\nb", False),
        (_StrSubclass("agent"), False),
    ],
)
def test_agent_id_grammar_is_exact(agent_id: str, expected: bool) -> None:
    assert is_safe_avatar_agent_id(agent_id) is expected
    assert validate_avatar_telemetry_payload(_payload(agent_id=agent_id)) is expected


@pytest.mark.parametrize(
    "frame_type",
    ["", "full", "SNAPSHOT", _StrSubclass("snapshot")],
)
def test_frame_type_rejects_non_literals(frame_type: str) -> None:
    assert validate_avatar_telemetry_payload(_payload(frame_type=frame_type)) is False


@pytest.mark.parametrize(
    ("stream_id", "expected"),
    [
        (_STREAM_ID, True),
        ("ABCDEF0123456789ABCDEF0123456789", False),
        ("0" * 31, False),
        ("0" * 33, False),
        ("g" * 32, False),
        (_StrSubclass(_STREAM_ID), False),
    ],
)
def test_stream_id_grammar_is_exact(stream_id: str, expected: bool) -> None:
    assert validate_avatar_telemetry_payload(_payload(stream_id=stream_id)) is expected


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        (0, True),
        (_MAX_SEQUENCE, True),
        (-1, False),
        (_MAX_SEQUENCE + 1, False),
        (True, False),
        (_IntSubclass(1), False),
    ],
)
def test_sequence_bounds_are_exact(sequence: int, expected: bool) -> None:
    assert validate_avatar_telemetry_payload(_payload(sequence=sequence)) is expected


@pytest.mark.parametrize("missing", list(_snapshot_data().keys()))
def test_snapshot_requires_all_nine_fields(missing: str) -> None:
    data = _snapshot_data()
    data.pop(missing)
    assert validate_avatar_telemetry_payload(_payload(data=data)) is False


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"agent_id": _AGENT_ID},
        {"last_observed_at": 1.0},
        {"unknown": True},
        {"current_signals": {"load": 0.5}},
    ],
)
def test_diff_requires_nonempty_allowlisted_complete_fields(data: dict[str, Any]) -> None:
    assert validate_avatar_telemetry_payload(
        _payload(frame_type="diff", data=data),
    ) is False


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("expression_resting",), "unknown"),
        (("current_signals", "trust_delta"), -1.01),
        (("current_signals", "trust_delta"), math.nan),
        (("current_signals", "load"), 1.01),
        (("current_signals", "load"), 1),
        (("current_signals", "working_state"), "working"),
        (("current_signals", "tier3_alert"), 1),
        (("mouth_active",), 1),
        (("applied_modulation", "pitch_factor"), 2.01),
        (("applied_modulation", "rate_factor"), 0.09),
        (("applied_modulation", "volume_factor"), -0.01),
        (("last_observed_at",), 1),
        (("last_observed_at",), math.inf),
        (("sampling_rate_ms",), 249),
        (("sampling_rate_ms",), True),
        (("sampling_tier",), "medium"),
        (("dsl_summary", "body_type"), "tall"),
        (("dsl_summary", "hair_style"), "mohawk"),
        (("dsl_summary", "primary_color"), "red"),
        (("dsl_summary", "outfit_style"), "spacesuit"),
    ],
)
def test_nested_field_ranges_and_enums_reject(
    path: tuple[str, ...],
    value: Any,
) -> None:
    data = _snapshot_data()
    target: dict[str, Any] = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert validate_avatar_telemetry_data(data, "snapshot") is None


@pytest.mark.parametrize(
    "palette",
    ["", "red", "brand_1", "A-b", "#abc", "#abcd", "#A1b2C3", "#A1b2C3d4"],
)
def test_federation_palette_projection_supported_values_preserved(palette: str) -> None:
    source = _snapshot_data(palette=palette)
    projected = project_avatar_telemetry_data_for_federation(source)
    assert projected["dsl_summary"]["color_palette_hint"] == palette
    assert projected is not source
    assert projected["dsl_summary"] is not source["dsl_summary"]
    assert validate_avatar_telemetry_data(projected, "snapshot") is not None


@pytest.mark.parametrize(
    "palette",
    [
        "rgb(1 2 3)",
        "rgba(1,2,3,.5)",
        "hsl(10 20% 30%)",
        "hsla(10,20%,30%,.5)",
        "color(display-p3 1 0 0)",
        "lab(50% 20 30)",
        "lch(50% 20 30)",
        "oklab(50% 0 0)",
        "oklch(50% 0 0)",
        "var(--crew-color)",
        "url(https://example.test/a)",
        "bad\nvalue",
        "a" * 33,
        "two words",
    ],
)
def test_federation_palette_projection_unsupported_maps_empty_only_on_wire(
    palette: str,
) -> None:
    source = _snapshot_data(palette=palette)
    source_dsl = source["dsl_summary"]
    projected = project_avatar_telemetry_data_for_federation(source)
    parsed = validate_avatar_telemetry_data(projected, "snapshot")
    assert parsed is not None
    assert parsed["dsl_summary"]["color_palette_hint"] == ""
    assert source["dsl_summary"]["color_palette_hint"] == palette
    assert source["dsl_summary"] is source_dsl
    local = avatar_telemetry_frame_to_ws(
        AvatarTelemetryFrame(_AGENT_ID, "snapshot", source),
    )
    assert local["dsl_summary"]["color_palette_hint"] == palette


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data["dsl_summary"].pop("color_palette_hint"),
        lambda data: data["dsl_summary"].__setitem__("color_palette_hint", 1),
        lambda data: data.__setitem__("dsl_summary", "bad"),
        lambda data: data.__setitem__("dsl_summary", _DictSubclass(data["dsl_summary"])),
        lambda data: data["dsl_summary"].__setitem__("color_palette_hint", _StrSubclass("red")),
    ],
)
def test_federation_palette_projection_malformed_shape_still_rejects_without_aliasing(
    mutator: Any,
) -> None:
    source = _snapshot_data()
    mutator(source)
    projected = project_avatar_telemetry_data_for_federation(source)
    assert validate_avatar_telemetry_data(projected, "snapshot") is None
    if type(source) is dict:
        assert projected is not source


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "source_node",
        "origin_mesh_id",
        "profile",
        "vrm_url",
        "url",
        "notes",
        "asset",
        "image",
        "attachment",
        "password",
        "secret",
        "token",
        "api_key",
        "authorization",
        "private_key",
        "client_secret",
    ],
)
def test_unknown_and_privacy_fields_reject_before_semantic_use(
    forbidden_key: str,
) -> None:
    data = _snapshot_data()
    data[forbidden_key] = "sensitive-value"
    assert validate_avatar_telemetry_payload(_payload(data=data)) is False


def test_semantic_maximum_fits_complete_ad1123_finalizer() -> None:
    data = _snapshot_data()
    data["degraded_reasons"] = list(relay_module.DEGRADED_REASON_VALUES)
    data["applied_modulation"]["fired_rules"] = list(
        relay_module.FIRED_RULE_VALUES,
    )[:16]
    payload = _payload(data=data, sequence=_MAX_SEQUENCE)
    assert validate_avatar_telemetry_payload(payload) is True
    finalized = finalize_relay_wire_payload(
        source_node="node-a",
        message_id="0123456789abcdef0123456789abcdef",
        relay_payload={
            "relay_version": 1,
            "target_node_id": "node-b",
            "topic": AVATAR_TELEMETRY_TOPIC,
            "payload": payload,
            "hop_count": 0,
        },
        timestamp=0.0,
    )
    assert finalized is not None


def test_parser_returns_detached_builtins_without_mutating_input() -> None:
    original = _payload()
    parsed = parse_avatar_telemetry_payload(original)
    assert parsed == original
    assert parsed is not original
    assert parsed["data"] is not original["data"]
    assert parsed["data"]["current_signals"] is not original["data"]["current_signals"]
    parsed["data"]["current_signals"]["load"] = 0.9
    assert original["data"]["current_signals"]["load"] == 0.25


def test_nullable_and_exact_numeric_boundaries_accept() -> None:
    data = _snapshot_data()
    data["expression_resting"] = None
    data["applied_modulation"] = None
    data["dsl_summary"] = None
    data["current_signals"] = {
        "trust_delta": -1.0,
        "load": 1.0,
        "working_state": "blocked",
        "tier3_alert": True,
    }
    data["last_observed_at"] = float(_MAX_SEQUENCE)
    data["sampling_rate_ms"] = 2_147_483_647
    assert validate_avatar_telemetry_data(data, "snapshot") is not None


@pytest.mark.parametrize(
    "fired_rules",
    [
        ["responding_rate", "custom_warmth"],
        ["responding_rate", "responding_rate"],
        ["unknown_rule"],
        [f"custom_{index}" for index in range(17)],
    ],
)
def test_fired_rules_allowlist_custom_grammar_uniqueness_and_bound(
    fired_rules: list[str],
) -> None:
    data = _snapshot_data()
    data["applied_modulation"]["fired_rules"] = fired_rules
    expected = fired_rules == ["responding_rate", "custom_warmth"]
    assert (validate_avatar_telemetry_data(data, "snapshot") is not None) is expected


@pytest.mark.parametrize(
    "reasons",
    [
        ["agent_not_found"],
        ["agent_not_found", "agent_not_found"],
        ["unknown_reason"],
        list(relay_module.DEGRADED_REASON_VALUES) + ["agent_not_found"],
    ],
)
def test_degraded_reasons_allowlist_uniqueness_and_bound(
    reasons: list[str],
) -> None:
    data = _snapshot_data()
    data["degraded_reasons"] = reasons
    expected = reasons == ["agent_not_found"]
    assert (validate_avatar_telemetry_data(data, "snapshot") is not None) is expected


# ---------------------------------------------------------------------------
# C. Shared frame selector and local WebSocket parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("previous", "tick", "diff_enabled", "full_every_n", "force_full"),
    [
        (None, 0, True, 10, False),
        (_snapshot_data(), 1, True, 10, True),
        (_snapshot_data(), 1, False, 10, False),
        (_snapshot_data(), 10, True, 10, False),
    ],
)
def test_select_frame_full_conditions(
    previous: dict[str, Any] | None,
    tick: int,
    diff_enabled: bool,
    full_every_n: int,
    force_full: bool,
) -> None:
    frame, cursor = select_avatar_telemetry_frame(
        _snapshot(trust_delta=0.5),
        previous_snapshot=previous,
        tick_count=tick,
        diff_enabled=diff_enabled,
        diff_threshold=0.05,
        full_every_n=full_every_n,
        force_full=force_full,
    )
    assert frame is not None
    assert frame.frame_type == "snapshot"
    assert cursor == frame.data
    assert "agent_id" not in frame.data


def test_select_frame_significant_diff_shallow_merges_cursor() -> None:
    previous = _snapshot_data(trust_delta=0.0)
    frame, cursor = select_avatar_telemetry_frame(
        _snapshot(trust_delta=0.5),
        previous_snapshot=previous,
        tick_count=1,
        diff_enabled=True,
        diff_threshold=0.05,
        full_every_n=10,
    )
    assert frame is not None
    assert frame.frame_type == "diff"
    assert set(frame.data) == {"current_signals"}
    assert cursor == {**previous, **frame.data}


def test_select_frame_empty_and_timestamp_only_leave_cursor_unchanged() -> None:
    previous = _snapshot_data(observed_at=1_000.0)
    frame, cursor = select_avatar_telemetry_frame(
        _snapshot(observed_at=1_001.0),
        previous_snapshot=previous,
        tick_count=1,
        diff_enabled=True,
        diff_threshold=0.05,
        full_every_n=10,
    )
    assert frame is None
    assert cursor is previous


def test_select_frame_diff_exception_falls_back_full(monkeypatch, caplog) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("diff-fault")

    import probos.avatars.telemetry_frames as frame_module

    monkeypatch.setattr(frame_module, "compute_diff", _raise)
    frame, cursor = select_avatar_telemetry_frame(
        _snapshot(),
        previous_snapshot=_snapshot_data(),
        tick_count=1,
        diff_enabled=True,
        diff_threshold=0.05,
        full_every_n=10,
    )
    assert frame is not None and frame.frame_type == "snapshot"
    assert cursor == frame.data
    assert "falling back to full snapshot" in caplog.text
    assert _AGENT_ID in caplog.text
    assert "RuntimeError" in caplog.text
    assert "diff-fault" not in caplog.text


def test_ws_adapters_match_existing_snapshot_and_diff_shapes() -> None:
    snapshot_data = _snapshot_data(palette="rgb(1 2 3)")
    full = avatar_telemetry_frame_to_ws(
        AvatarTelemetryFrame(_AGENT_ID, "snapshot", snapshot_data),
    )
    diff = avatar_telemetry_frame_to_ws(
        AvatarTelemetryFrame(_AGENT_ID, "diff", {"mouth_active": False}),
    )
    assert full == {
        "type": "snapshot",
        "agent_id": _AGENT_ID,
        **snapshot_data,
    }
    assert full["dsl_summary"]["color_palette_hint"] == "rgb(1 2 3)"
    assert diff == {
        "type": "diff",
        "agent_id": _AGENT_ID,
        "changed": {"mouth_active": False},
    }


# ---------------------------------------------------------------------------
# D. Config, subscriptions, callback, rate, and sequence semantics
# ---------------------------------------------------------------------------


def test_peer_config_default_empty_and_valid_list() -> None:
    empty = PeerConfig(node_id="node-b", address="tcp://127.0.0.1:1")
    valid = PeerConfig(
        node_id="node-b",
        address="tcp://127.0.0.1:1",
        avatar_telemetry_agent_ids=[_AGENT_ID],
    )
    assert empty.avatar_telemetry_agent_ids == []
    assert valid.avatar_telemetry_agent_ids == [_AGENT_ID]


@pytest.mark.parametrize(
    "agent_ids",
    [
        [_AGENT_ID, _AGENT_ID],
        ["bad/id"],
        [f"agent-{index}" for index in range(33)],
    ],
)
def test_peer_config_rejects_duplicate_invalid_and_33rd_id(
    agent_ids: list[str],
) -> None:
    with pytest.raises(ValidationError):
        PeerConfig(
            node_id="node-b",
            address="tcp://127.0.0.1:1",
            avatar_telemetry_agent_ids=agent_ids,
        )


def test_peer_config_oversized_list_rejects_before_entry_validation(
    monkeypatch,
) -> None:
    import probos.avatars.telemetry_frames as frame_module

    predicate_calls = 0

    def _record_predicate(_value: Any) -> bool:
        nonlocal predicate_calls
        predicate_calls += 1
        return True

    monkeypatch.setattr(
        frame_module,
        "is_safe_avatar_agent_id",
        _record_predicate,
    )
    with pytest.raises(ValidationError):
        PeerConfig(
            node_id="node-b",
            address="tcp://127.0.0.1:1",
            avatar_telemetry_agent_ids=[
                f"agent-{index}"
                for index in range(33)
            ],
        )
    assert predicate_calls == 0


def test_sampling_rate_config_upper_bound_matches_wire_contract() -> None:
    import probos.avatars.telemetry_frames as frame_module

    assert frame_module.MAX_AVATAR_SAMPLING_RATE_MS == _MAX_SAMPLING_RATE_MS
    rates = SamplingRatesConfig(
        high_ms=_MAX_SAMPLING_RATE_MS,
        normal_ms=_MAX_SAMPLING_RATE_MS,
        low_ms=_MAX_SAMPLING_RATE_MS,
    )
    sampling_state = AvatarSamplingStateMachine(rates)
    assert sampling_state.current_rate_ms(_AGENT_ID) == _MAX_SAMPLING_RATE_MS

    data = _snapshot_data(sampling_rate_ms=_MAX_SAMPLING_RATE_MS)
    assert parse_avatar_telemetry_payload(_payload(data=data)) is not None

    for field_name in ("high_ms", "normal_ms", "low_ms"):
        values = {
            "high_ms": _MAX_SAMPLING_RATE_MS,
            "normal_ms": _MAX_SAMPLING_RATE_MS,
            "low_ms": _MAX_SAMPLING_RATE_MS,
        }
        values[field_name] = _MAX_SAMPLING_RATE_MS + 1
        with pytest.raises(
            ValidationError,
            match="sampling-rate field must be <= 2147483647",
        ):
            SamplingRatesConfig(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("peers", "reason"),
    [
        (
            [
                PeerConfig(node_id="node-b", address="tcp://1", avatar_telemetry_agent_ids=[_AGENT_ID]),
                PeerConfig(node_id="node-b", address="tcp://2", avatar_telemetry_agent_ids=[_AGENT_ID]),
            ],
            "telemetry_duplicate_peer_node_id",
        ),
        (
            [
                PeerConfig(node_id=f"node-{index}", address=f"tcp://{index}", avatar_telemetry_agent_ids=[_AGENT_ID])
                for index in range(17)
            ],
            "telemetry_peer_cap_exceeded",
        ),
        (
            [
                PeerConfig(
                    node_id=f"node-{peer_index}",
                    address=f"tcp://{peer_index}",
                    avatar_telemetry_agent_ids=[
                        f"agent-{peer_index * 32 + index}"
                        for index in range(32 if peer_index < 2 else 1)
                    ],
                )
                for peer_index in range(3)
            ],
            "telemetry_agent_cap_exceeded",
        ),
    ],
)
async def test_start_helper_rejects_global_caps_before_task_creation(
    peers: list[PeerConfig],
    reason: str,
) -> None:
    event_bus = AvatarEventBus()
    with pytest.raises(ValueError, match=f"^{reason}$"):
        await start_federation_avatar_telemetry(
            bridge=_AcceptingBridge(),
            peers=peers,
            registry=AgentRegistry(),
            event_bus=event_bus,
            sampling_state=_sampling_state(),
            snapshot_builder=lambda _agent_id: None,
            diff_enabled=True,
            diff_threshold=0.05,
            full_every_n=10,
        )
    assert event_bus._subscribers == {}


@pytest.mark.asyncio
async def test_start_helper_unknown_registry_id_rejects_before_task_creation() -> None:
    event_bus = AvatarEventBus()
    with pytest.raises(ValueError, match="^telemetry_unknown_agent_id:"):
        await start_federation_avatar_telemetry(
            bridge=_AcceptingBridge(),
            peers=[PeerConfig(
                node_id="node-b",
                address="tcp://1",
                avatar_telemetry_agent_ids=[_AGENT_ID],
            )],
            registry=AgentRegistry(),
            event_bus=event_bus,
            sampling_state=_sampling_state(),
            snapshot_builder=lambda _agent_id: None,
            diff_enabled=True,
            diff_threshold=0.05,
            full_every_n=10,
        )
    assert event_bus._subscribers == {}


@pytest.mark.parametrize(
    ("value", "accepted"),
    [(1, True), (10, True), (True, False), (0, False), (11, False), (1.0, False)],
)
def test_relay_rate_constructor_exact_bounds(value: Any, accepted: bool) -> None:
    if accepted:
        assert FederationTelemetryRelay(max_per_sec_per_peer=value)
    else:
        with pytest.raises(ValueError, match="^telemetry_rate_limit_invalid$"):
            FederationTelemetryRelay(max_per_sec_per_peer=value)


@pytest.mark.asyncio
async def test_exact_filter_multicast_and_unsubscribed_no_rate_slot() -> None:
    relay = FederationTelemetryRelay()
    relay.register_peer("node-b", [_AGENT_ID])
    relay.register_peer("node-c", [_AGENT_ID])
    relay.register_peer("node-d", ["other-agent"])
    await relay.start()
    try:
        dispatched = await relay.on_local_telemetry_frame(
            agent_id=_AGENT_ID,
            frame_type="snapshot",
            payload=_snapshot_data(),
        )
        assert dispatched == 2
        assert set(relay._rate) == {"node-b", "node-c"}
        assert {entry[0] for entry in relay.dispatch_log()} == {"node-b", "node-c"}
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_rate_claim_first_ten_eleventh_drop_peer_independent(monkeypatch) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr(relay_module.time, "monotonic", lambda: clock["now"])
    relay = await _start_manual_relay(peers=("node-b", "node-c"))
    try:
        for _ in range(10):
            assert await relay.on_local_telemetry_frame(
                agent_id=_AGENT_ID,
                frame_type="snapshot",
                payload=_snapshot_data(),
            ) == 2
        assert await relay.on_local_telemetry_frame(
            agent_id=_AGENT_ID,
            frame_type="snapshot",
            payload=_snapshot_data(),
        ) == 0
        clock["now"] += 1.01
        assert await relay.on_local_telemetry_frame(
            agent_id=_AGENT_ID,
            frame_type="snapshot",
            payload=_snapshot_data(),
        ) == 2
    finally:
        await relay.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(("result", "expected"), [(True, 1), (False, 0), (None, 0), (1, 0)])
async def test_callback_only_literal_true_counts(result: Any, expected: int) -> None:
    async def _emit(_peer_id: str, _payload: dict[str, Any]) -> bool:
        return result

    relay = await _start_manual_relay(callback=_emit)
    try:
        assert await relay.on_local_telemetry_frame(
            agent_id=_AGENT_ID,
            frame_type="snapshot",
            payload=_snapshot_data(),
        ) == expected
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_callback_exception_degrades_but_consumes_attempt(caplog) -> None:
    calls = 0

    async def _emit(_peer_id: str, _payload: dict[str, Any]) -> bool:
        nonlocal calls
        calls += 1
        raise RuntimeError("emit-fault")

    relay = await _start_manual_relay(max_per_sec=1, callback=_emit)
    try:
        assert await relay.on_local_telemetry_frame(
            agent_id=_AGENT_ID,
            frame_type="snapshot",
            payload=_snapshot_data(),
        ) == 0
        assert await relay.on_local_telemetry_frame(
            agent_id=_AGENT_ID,
            frame_type="snapshot",
            payload=_snapshot_data(),
        ) == 0
        assert calls == 1
        assert "frame dropped" in caplog.text
        assert "emit-fault" not in caplog.text
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_callback_false_consumes_reserved_attempt_slot() -> None:
    calls = 0

    async def _emit(_peer_id: str, _payload: dict[str, Any]) -> bool:
        nonlocal calls
        calls += 1
        return False

    relay = await _start_manual_relay(max_per_sec=1, callback=_emit)
    try:
        for _ in range(2):
            assert await relay.on_local_telemetry_frame(
                agent_id=_AGENT_ID,
                frame_type="snapshot",
                payload=_snapshot_data(),
            ) == 0
        assert calls == 1
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_concurrent_attempts_cannot_exceed_ten_callbacks() -> None:
    entered = 0
    release = asyncio.Event()

    async def _emit(_peer_id: str, _payload: dict[str, Any]) -> bool:
        nonlocal entered
        entered += 1
        await release.wait()
        return True

    relay = await _start_manual_relay(callback=_emit)
    tasks = [
        asyncio.create_task(relay.on_local_telemetry_frame(
            agent_id=_AGENT_ID,
            frame_type="snapshot",
            payload=_snapshot_data(),
        ))
        for _ in range(20)
    ]
    try:
        await _wait_until(lambda: entered == 10)
        await asyncio.sleep(0)
        assert entered == 10
        release.set()
        results = await asyncio.gather(*tasks)
        assert sum(results) == 10
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await relay.stop()


@pytest.mark.asyncio
async def test_callback_cancellation_propagates() -> None:
    async def _emit(_peer_id: str, _payload: dict[str, Any]) -> bool:
        raise asyncio.CancelledError

    relay = await _start_manual_relay(callback=_emit)
    try:
        with pytest.raises(asyncio.CancelledError):
            await relay.on_local_telemetry_frame(
                agent_id=_AGENT_ID,
                frame_type="snapshot",
                payload=_snapshot_data(),
            )
    finally:
        await relay.stop()


@pytest.mark.parametrize(
    "callback_factory",
    [
        lambda: (lambda _peer_id, _payload: True),
        lambda: (lambda *_args: True),
        lambda: (lambda _peer_id, *, payload: True),
        lambda: (lambda _peer_id, _payload, _extra=None: True),
    ],
)
def test_callback_registration_rejects_non_async_or_wrong_signature(
    callback_factory: Any,
) -> None:
    relay = FederationTelemetryRelay()
    with pytest.raises(ValueError, match="^telemetry_emit_callback_invalid$"):
        relay.set_emit_callback(callback_factory())


def test_callback_registration_accepts_exact_async_and_decorated() -> None:
    async def _emit(_peer_id: str, _payload: dict[str, Any]) -> bool:
        return True

    async def _decorated(peer_id: str, payload: dict[str, Any]) -> bool:
        return await _emit(peer_id, payload)

    relay = FederationTelemetryRelay()
    relay.set_emit_callback(_emit)
    relay.set_emit_callback(_decorated)


def test_callback_hostile_ordinary_metadata_normalizes(monkeypatch) -> None:
    async def _emit(_peer_id: str, _payload: dict[str, Any]) -> bool:
        return True

    def _raise(_value: Any) -> Any:
        raise RuntimeError("hostile-metadata")

    monkeypatch.setattr(relay_module.inspect, "signature", _raise)
    with pytest.raises(ValueError) as exc_info:
        FederationTelemetryRelay().set_emit_callback(_emit)
    assert type(exc_info.value) is ValueError
    assert exc_info.value.args == ("telemetry_emit_callback_invalid",)


def test_callback_metadata_baseexception_propagates(monkeypatch) -> None:
    marker = BaseException("lifecycle")

    async def _emit(_peer_id: str, _payload: dict[str, Any]) -> bool:
        return True

    def _raise(_value: Any) -> Any:
        raise marker

    monkeypatch.setattr(relay_module.inspect, "signature", _raise)
    with pytest.raises(BaseException) as exc_info:
        FederationTelemetryRelay().set_emit_callback(_emit)
    assert exc_info.value is marker


@pytest.mark.asyncio
async def test_running_mutation_rejects_before_callback_inspection() -> None:
    relay = FederationTelemetryRelay()
    await relay.start()
    try:
        with pytest.raises(RuntimeError, match="^telemetry_relay_running$"):
            relay.register_peer("node-b", [_AGENT_ID])
        with pytest.raises(RuntimeError, match="^telemetry_relay_running$"):
            relay.unregister_peer("node-b")
        with pytest.raises(RuntimeError, match="^telemetry_relay_running$"):
            relay.set_emit_callback(object())
    finally:
        await relay.stop()
    relay.register_peer("node-b", [_AGENT_ID])


@pytest.mark.asyncio
async def test_invalid_semantic_frame_consumes_no_sequence_rate_or_callback() -> None:
    calls = 0

    async def _emit(_peer_id: str, _payload: dict[str, Any]) -> bool:
        nonlocal calls
        calls += 1
        return True

    relay = await _start_manual_relay(callback=_emit)
    try:
        assert await relay.on_local_telemetry_frame(
            agent_id="bad/id",
            frame_type="snapshot",
            payload=_snapshot_data(),
        ) == 0
        assert calls == 0
        assert relay._sequences == {}
        assert relay._rate == {}
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_valid_multicast_uses_one_common_sequence() -> None:
    captured: list[dict[str, Any]] = []

    async def _emit(_peer_id: str, payload: dict[str, Any]) -> bool:
        captured.append(payload)
        return True

    relay = await _start_manual_relay(callback=_emit, peers=("node-b", "node-c"))
    try:
        assert await relay.on_local_telemetry_frame(
            agent_id=_AGENT_ID,
            frame_type="snapshot",
            payload=_snapshot_data(),
        ) == 2
        assert len(captured) == 2
        assert captured[0] == captured[1]
        assert captured[0]["sequence"] == 0
        assert relay._sequences == {_AGENT_ID: 1}
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_multi_agent_sequences_are_per_agent_and_shared_across_peer_copies() -> None:
    agent_b = "agent-b"
    caches = {
        "node-b": RemoteAvatarTelemetryCache(max_entries=256),
        "node-c": RemoteAvatarTelemetryCache(max_entries=256),
    }
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _emit(peer_id: str, payload: dict[str, Any]) -> bool:
        captured.append((peer_id, payload))
        await caches[peer_id].ingest("node-a", payload)
        return True

    relay = FederationTelemetryRelay()
    relay.register_peer("node-b", [_AGENT_ID, agent_b])
    relay.register_peer("node-c", [_AGENT_ID])
    relay.set_emit_callback(_emit)
    await relay.start()
    try:
        assert await relay.on_local_telemetry_frame(
            agent_id=_AGENT_ID,
            frame_type="snapshot",
            payload=_snapshot_data(agent_id=_AGENT_ID),
        ) == 2
        assert await relay.on_local_telemetry_frame(
            agent_id=agent_b,
            frame_type="snapshot",
            payload=_snapshot_data(agent_id=agent_b),
        ) == 1
        assert await relay.on_local_telemetry_frame(
            agent_id=_AGENT_ID,
            frame_type="diff",
            payload={"mouth_active": False},
        ) == 2
        assert await relay.on_local_telemetry_frame(
            agent_id=agent_b,
            frame_type="diff",
            payload={"mouth_active": False},
        ) == 1

        observed = {
            (peer_id, payload["agent_id"]): []
            for peer_id, payload in captured
        }
        for peer_id, payload in captured:
            observed[(peer_id, payload["agent_id"])].append(payload["sequence"])
        assert observed == {
            ("node-b", _AGENT_ID): [0, 1],
            ("node-b", agent_b): [0, 1],
            ("node-c", _AGENT_ID): [0, 1],
        }
        assert relay._sequences == {_AGENT_ID: 2, agent_b: 2}
        assert caches["node-b"].get("node-a", _AGENT_ID)["sequence"] == 1
        assert caches["node-b"].get("node-a", agent_b)["sequence"] == 1
        assert caches["node-c"].get("node-a", _AGENT_ID)["sequence"] == 1
        assert caches["node-b"].get(
            "node-a",
            _AGENT_ID,
        )["snapshot"]["mouth_active"] is False
        assert caches["node-b"].get(
            "node-a",
            agent_b,
        )["snapshot"]["mouth_active"] is False
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_default_dispatch_log_is_ordered_and_bounded_to_256(monkeypatch) -> None:
    clock = {"now": 0.0}

    def _monotonic() -> float:
        clock["now"] += 1.01
        return clock["now"]

    monkeypatch.setattr(relay_module.time, "monotonic", _monotonic)
    relay = await _start_manual_relay()
    try:
        for _ in range(300):
            assert await relay.on_local_telemetry_frame(
                agent_id=_AGENT_ID,
                frame_type="snapshot",
                payload=_snapshot_data(),
            ) == 1
        log = relay.dispatch_log()
        assert len(log) == 256
        assert log[0][1]["sequence"] == 44
        assert log[-1][1]["sequence"] == 299
    finally:
        await relay.stop()


# ---------------------------------------------------------------------------
# E. Producer lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_producer_per_unique_agent_and_never_enters_popout() -> None:
    event_bus = AvatarEventBus()
    sampling = _sampling_state()

    async def _builder(agent_id: str) -> AvatarTelemetrySnapshot:
        return _snapshot(agent_id=agent_id)

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=sampling,
    )
    relay.register_peer("node-b", [_AGENT_ID])
    relay.register_peer("node-c", [_AGENT_ID])
    try:
        await relay.start()
        assert set(relay._producer_tasks) == {_AGENT_ID}
        assert event_bus.subscriber_count(_AGENT_ID) == 1
        assert sampling.snapshot_counts(_AGENT_ID)["popout"] == 0
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_zero_subscriptions_zero_tasks_events_and_callback() -> None:
    calls = 0
    event_bus = AvatarEventBus()

    async def _builder(_agent_id: str) -> AvatarTelemetrySnapshot:
        raise AssertionError("builder invoked")

    async def _emit(_peer_id: str, _payload: dict[str, Any]) -> bool:
        nonlocal calls
        calls += 1
        return True

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=_sampling_state(),
    )
    relay.set_emit_callback(_emit)
    await relay.start()
    assert relay._producer_tasks == {}
    assert event_bus._subscribers == {}
    assert calls == 0
    await relay.stop()


@pytest.mark.asyncio
async def test_producer_stop_unsubscribes_reaps_and_clears_state() -> None:
    event_bus = AvatarEventBus()

    async def _builder(agent_id: str) -> AvatarTelemetrySnapshot:
        return _snapshot(agent_id=agent_id)

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=_sampling_state(),
    )
    relay.register_peer("node-b", [_AGENT_ID])
    await relay.start()
    tasks = tuple(relay._producer_tasks.values())
    await relay.stop()
    assert all(task.done() for task in tasks)
    assert event_bus.subscriber_count(_AGENT_ID) == 0
    assert relay._producer_tasks == {}
    assert relay._rate == {}
    assert relay._frame_cursors == {}
    assert relay._sequences == {}
    assert relay._stream_id is None
    await relay.stop()


@pytest.mark.asyncio
async def test_start_stop_start_new_stream_and_no_event_leak() -> None:
    event_bus = AvatarEventBus()
    emitted: list[dict[str, Any]] = []

    async def _builder(agent_id: str) -> AvatarTelemetrySnapshot:
        return _snapshot(agent_id=agent_id)

    async def _emit(_peer_id: str, payload: dict[str, Any]) -> bool:
        emitted.append(payload)
        return True

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=_sampling_state(),
    )
    relay.register_peer("node-b", [_AGENT_ID])
    relay.set_emit_callback(_emit)
    await relay.start()
    await _wait_until(lambda: len(emitted) == 1)
    first_stream = emitted[-1]["stream_id"]
    await relay.stop()
    await relay.start()
    await _wait_until(lambda: len(emitted) == 2)
    second_stream = emitted[-1]["stream_id"]
    assert second_stream != first_stream
    assert event_bus.subscriber_count(_AGENT_ID) == 1
    await relay.stop()
    assert event_bus.subscriber_count(_AGENT_ID) == 0


@pytest.mark.asyncio
async def test_partial_create_task_failure_cleans_and_permits_restart(monkeypatch) -> None:
    event_bus = AvatarEventBus()
    agent_b = "agent-b"

    async def _builder(agent_id: str) -> AvatarTelemetrySnapshot:
        return _snapshot(agent_id=agent_id)

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=_sampling_state(),
    )
    relay.register_peer("node-b", [_AGENT_ID, agent_b])
    real_create_task = relay_module.asyncio.create_task
    producer_calls = 0

    def _fail_second(coro: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        nonlocal producer_calls
        if name and name.startswith("federation-avatar-telemetry"):
            producer_calls += 1
            if producer_calls == 2:
                coro.close()
                raise RuntimeError("task-create-fault")
        return real_create_task(coro, name=name)

    monkeypatch.setattr(relay_module.asyncio, "create_task", _fail_second)
    with pytest.raises(RuntimeError, match="task-create-fault"):
        await relay.start()
    assert relay._producer_tasks == {}
    assert event_bus._subscribers == {}
    monkeypatch.setattr(relay_module.asyncio, "create_task", real_create_task)
    await relay.start()
    assert set(relay._producer_tasks) == {_AGENT_ID, agent_b}
    await relay.stop()


@pytest.mark.asyncio
async def test_producer_subscription_failure_is_observed_cleans_and_permits_restart(
    monkeypatch,
) -> None:
    class _SubscribeFaultEventBus(AvatarEventBus):
        def __init__(self) -> None:
            super().__init__()
            self.fail_second = True
            self.subscribe_calls = 0

        def subscribe(self, agent_id: str) -> asyncio.Event:
            self.subscribe_calls += 1
            if self.fail_second and self.subscribe_calls == 2:
                raise RuntimeError("subscribe-fault")
            return super().subscribe(agent_id)

    event_bus = _SubscribeFaultEventBus()
    agent_b = "agent-b"

    async def _builder(agent_id: str) -> AvatarTelemetrySnapshot:
        return _snapshot(agent_id=agent_id)

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=_sampling_state(),
    )
    relay.register_peer("node-b", [_AGENT_ID, agent_b])
    real_create_task = relay_module.asyncio.create_task
    producer_tasks: list[asyncio.Task[Any]] = []

    def _record_producer_task(
        coro: Any,
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        task = real_create_task(coro, name=name)
        if name and name.startswith("federation-avatar-telemetry"):
            producer_tasks.append(task)
        return task

    monkeypatch.setattr(relay_module.asyncio, "create_task", _record_producer_task)
    try:
        with pytest.raises(RuntimeError, match="subscribe-fault"):
            await relay.start()
        assert len(producer_tasks) == 2
        assert all(task.done() for task in producer_tasks)
        assert relay._producer_tasks == {}
        assert event_bus._subscribers == {}
        assert relay._rate == {}
        assert relay._frame_cursors == {}
        assert relay._tick_counts == {}
        assert relay._stream_id is None
        assert relay._sequences == {}
        assert relay._running is False

        event_bus.fail_second = False
        await relay.start()
        assert set(relay._producer_tasks) == {_AGENT_ID, agent_b}
        assert event_bus.subscriber_count(_AGENT_ID) == 1
        assert event_bus.subscriber_count(agent_b) == 1
    finally:
        event_bus.fail_second = False
        await relay.stop()
    assert event_bus._subscribers == {}


@pytest.mark.asyncio
async def test_late_producer_failure_is_observed_without_unretrieved_exception(
    caplog,
) -> None:
    class _LateFaultSamplingState:
        def __init__(self) -> None:
            self.fail = False

        def current_rate_ms(self, _agent_id: str) -> int:
            if self.fail:
                raise RuntimeError("late-rate-fault")
            return 10_000

    event_bus = AvatarEventBus()
    sampling_state = _LateFaultSamplingState()

    async def _builder(agent_id: str) -> AvatarTelemetrySnapshot:
        return _snapshot(agent_id=agent_id)

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=sampling_state,
    )
    relay.register_peer("node-b", [_AGENT_ID])
    loop = asyncio.get_running_loop()
    prior_handler = loop.get_exception_handler()
    loop_contexts: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: loop_contexts.append(context))
    try:
        await relay.start()
        await _wait_until(lambda: len(relay.dispatch_log()) == 1)
        sampling_state.fail = True
        event_bus.notify(_AGENT_ID)
        task = relay._producer_tasks[_AGENT_ID]
        await _wait_until(task.done)
        await asyncio.sleep(0)
        assert _AGENT_ID in caplog.text
        assert "RuntimeError" in caplog.text
        assert "producer stopped" in caplog.text
        assert "relay restart required" in caplog.text
        assert "late-rate-fault" not in caplog.text
        assert loop_contexts == []
    finally:
        loop.set_exception_handler(prior_handler)
        await relay.stop()


@pytest.mark.asyncio
async def test_stop_and_concurrent_restart_are_serialized_without_orphaning_new_producer() -> None:
    event_bus = AvatarEventBus()
    blocked_build_entered = asyncio.Event()
    cancellation_seen = asyncio.Event()
    allow_cancel_cleanup = asyncio.Event()
    build_calls = 0

    async def _builder(agent_id: str) -> AvatarTelemetrySnapshot:
        nonlocal build_calls
        build_calls += 1
        if build_calls != 2:
            return _snapshot(agent_id=agent_id)
        blocked_build_entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await allow_cancel_cleanup.wait()
            raise

    async def _replacement_emit(
        _peer_id: str,
        _payload: dict[str, Any],
    ) -> bool:
        return True

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=_sampling_state(),
    )
    relay.register_peer("node-b", [_AGENT_ID])
    await relay.start()
    old_stream = relay._stream_id
    event_bus.notify(_AGENT_ID)
    await blocked_build_entered.wait()
    stop_task = asyncio.create_task(relay.stop())
    restart_task: asyncio.Task[None] | None = None
    try:
        await cancellation_seen.wait()
        restart_task = asyncio.create_task(relay.start())
        await asyncio.sleep(0)
        assert restart_task.done() is False
        with pytest.raises(RuntimeError, match="^telemetry_relay_running$"):
            relay.unregister_peer("missing-peer")
        with pytest.raises(RuntimeError, match="^telemetry_relay_running$"):
            relay.register_peer("node-c", [_AGENT_ID])
        with pytest.raises(RuntimeError, match="^telemetry_relay_running$"):
            relay.set_emit_callback(_replacement_emit)

        allow_cancel_cleanup.set()
        await stop_task
        await restart_task
        assert relay._stream_id is not None
        assert relay._stream_id != old_stream
        assert set(relay._producer_tasks) == {_AGENT_ID}
        assert relay._producer_tasks[_AGENT_ID].done() is False
        assert event_bus.subscriber_count(_AGENT_ID) == 1
    finally:
        allow_cancel_cleanup.set()
        if not stop_task.done():
            await stop_task
        if restart_task is not None and not restart_task.done():
            await restart_task
        await relay.stop()


@pytest.mark.asyncio
async def test_temporary_waiter_second_create_failure_reaps_first_waiter(
    monkeypatch,
    caplog,
) -> None:
    event_bus = AvatarEventBus()
    release_initial_build = asyncio.Event()

    async def _builder(agent_id: str) -> AvatarTelemetrySnapshot:
        await release_initial_build.wait()
        return _snapshot(agent_id=agent_id)

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=_sampling_state(),
    )
    relay.register_peer("node-b", [_AGENT_ID])
    await relay.start()
    real_create_task = relay_module.asyncio.create_task
    unnamed_calls = 0
    first_waiter: asyncio.Task[Any] | None = None

    def _fail_second_waiter(
        coro: Any,
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        nonlocal unnamed_calls, first_waiter
        if name is None:
            unnamed_calls += 1
            if unnamed_calls == 2:
                coro.close()
                raise RuntimeError("waiter-create-fault")
        task = real_create_task(coro, name=name)
        if name is None and unnamed_calls == 1:
            first_waiter = task
        return task

    monkeypatch.setattr(relay_module.asyncio, "create_task", _fail_second_waiter)
    try:
        release_initial_build.set()
        producer_task = relay._producer_tasks[_AGENT_ID]
        await _wait_until(producer_task.done)
        await asyncio.sleep(0)
        assert len(relay.dispatch_log()) == 1
        assert first_waiter is not None
        assert first_waiter.done()
        assert _AGENT_ID in caplog.text
        assert "RuntimeError" in caplog.text
        assert "producer stopped" in caplog.text
        assert "relay restart required" in caplog.text
        assert "waiter-create-fault" not in caplog.text
    finally:
        if first_waiter is not None and not first_waiter.done():
            first_waiter.cancel()
            await asyncio.gather(first_waiter, return_exceptions=True)
        await relay.stop()
    assert relay._producer_tasks == {}
    assert event_bus._subscribers == {}


@pytest.mark.asyncio
async def test_snapshot_builder_ordinary_failure_retries(caplog) -> None:
    event_bus = AvatarEventBus()
    attempts = 0
    emitted: list[dict[str, Any]] = []

    async def _builder(agent_id: str) -> AvatarTelemetrySnapshot:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("builder-fault")
        return _snapshot(agent_id=agent_id)

    async def _emit(_peer_id: str, payload: dict[str, Any]) -> bool:
        emitted.append(payload)
        return True

    relay = FederationTelemetryRelay(
        snapshot_builder=_builder,
        event_bus=event_bus,
        sampling_state=_sampling_state(),
    )
    relay.register_peer("node-b", [_AGENT_ID])
    relay.set_emit_callback(_emit)
    try:
        await relay.start()
        await _wait_until(lambda: attempts >= 1)
        event_bus.notify(_AGENT_ID)
        await _wait_until(lambda: len(emitted) == 1)
        assert "snapshot build failed" in caplog.text
        assert "builder-fault" not in caplog.text
    finally:
        await relay.stop()


# ---------------------------------------------------------------------------
# F. Volatile ordered LRU cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_snapshot_opens_and_diff_before_snapshot_drops() -> None:
    cache = RemoteAvatarTelemetryCache(max_entries=256)
    await cache.ingest(
        "node-a",
        _payload(frame_type="diff", sequence=0, data=_diff_data()),
    )
    assert cache.get("node-a", _AGENT_ID) is None
    await cache.ingest("node-a", _payload())
    assert cache.get("node-a", _AGENT_ID) is not None


@pytest.mark.asyncio
async def test_cache_contiguous_diff_merges_stale_duplicate_gap_drop() -> None:
    cache = RemoteAvatarTelemetryCache(max_entries=256)
    await cache.ingest("node-a", _payload(sequence=0))
    await cache.ingest(
        "node-a",
        _payload(frame_type="diff", sequence=1, data={"mouth_active": False}),
    )
    assert cache.get("node-a", _AGENT_ID)["snapshot"]["mouth_active"] is False
    for sequence in (1, 0, 3):
        await cache.ingest(
            "node-a",
            _payload(frame_type="diff", sequence=sequence, data={"mouth_active": True}),
        )
    record = cache.get("node-a", _AGENT_ID)
    assert record["sequence"] == 1
    assert record["snapshot"]["mouth_active"] is False


@pytest.mark.asyncio
async def test_cache_greater_snapshot_resync_and_new_stream_snapshot_only() -> None:
    cache = RemoteAvatarTelemetryCache(max_entries=256)
    await cache.ingest("node-a", _payload(sequence=0))
    await cache.ingest(
        "node-a",
        _payload(frame_type="diff", sequence=2, data={"mouth_active": False}),
    )
    await cache.ingest("node-a", _payload(sequence=3, data=_snapshot_data(trust_delta=0.5)))
    assert cache.get("node-a", _AGENT_ID)["sequence"] == 3
    new_stream = "f" * 32
    await cache.ingest(
        "node-a",
        _payload(frame_type="diff", stream_id=new_stream, sequence=0, data=_diff_data()),
    )
    assert cache.get("node-a", _AGENT_ID)["stream_id"] == _STREAM_ID
    await cache.ingest("node-a", _payload(stream_id=new_stream, sequence=0))
    assert cache.get("node-a", _AGENT_ID)["stream_id"] == new_stream


@pytest.mark.asyncio
async def test_cache_composite_identity_and_source_is_sink_owned() -> None:
    cache = RemoteAvatarTelemetryCache(max_entries=256)
    spoof = _payload()
    await cache.ingest("node-a", spoof)
    await cache.ingest("node-b", spoof)
    assert cache.get("node-a", _AGENT_ID)["source_node"] == "node-a"
    assert cache.get("node-b", _AGENT_ID)["source_node"] == "node-b"
    assert len(cache.list()) == 2


@pytest.mark.asyncio
async def test_cache_entry_257_evicts_exact_lru_and_invalid_does_not_refresh() -> None:
    cache = RemoteAvatarTelemetryCache(max_entries=256)
    for index in range(256):
        await cache.ingest(
            "node-a",
            _payload(agent_id=f"agent-{index}", sequence=0),
        )
    await cache.ingest(
        "node-a",
        _payload(
            agent_id="agent-0",
            frame_type="diff",
            sequence=2,
            data=_diff_data(),
        ),
    )
    await cache.ingest("node-a", _payload(agent_id="agent-256", sequence=0))
    assert len(cache.list()) == 256
    assert cache.get("node-a", "agent-0") is None
    assert cache.get("node-a", "agent-1") is not None
    assert cache.get("node-a", "agent-256") is not None


@pytest.mark.asyncio
async def test_cache_reads_exact_deterministic_and_detached() -> None:
    cache = RemoteAvatarTelemetryCache(max_entries=256)
    await cache.ingest("node-z", _payload(agent_id="agent-z"))
    await cache.ingest("node-a", _payload(agent_id="agent-b"))
    await cache.ingest("node-a", _payload(agent_id="agent-a"))
    records = cache.list()
    assert [(row["source_node"], row["agent_id"]) for row in records] == [
        ("node-a", "agent-a"),
        ("node-a", "agent-b"),
        ("node-z", "agent-z"),
    ]
    assert set(records[0]) == {
        "source_node",
        "agent_id",
        "stream_id",
        "sequence",
        "last_frame_type",
        "received_at",
        "snapshot",
    }
    records[0]["snapshot"]["mouth_active"] = False
    assert cache.get("node-a", "agent-a")["snapshot"]["mouth_active"] is True
    cache.clear()
    assert cache.list() == []


@pytest.mark.asyncio
async def test_cache_ingest_has_no_registry_or_event_bus_side_effects() -> None:
    registry = AgentRegistry()
    local_agent = _FakeAgent(agent_id="local-agent")
    await registry.register(local_agent)
    event_bus = AvatarEventBus()
    cache = RemoteAvatarTelemetryCache(max_entries=256)
    before_ids = [agent.id for agent in registry.all()]
    await cache.ingest("node-a", _payload())
    assert [agent.id for agent in registry.all()] == before_ids
    assert registry.count == 1
    assert event_bus._subscribers == {}


# ---------------------------------------------------------------------------
# G. Composition, runtime containment, shutdown, and source invariants
# ---------------------------------------------------------------------------


def test_topic_factory_disabled_enabled_exact_contract() -> None:
    cache = RemoteAvatarTelemetryCache(max_entries=256)
    assert build_federation_avatar_relay_topics(enabled=False, cache=cache) == ()
    topics = build_federation_avatar_relay_topics(enabled=True, cache=cache)
    assert type(topics) is tuple and len(topics) == 1
    topic = topics[0]
    assert type(topic) is FederationRelayTopic
    assert topic.name == AVATAR_TELEMETRY_TOPIC
    assert topic.validate_payload is validate_avatar_telemetry_payload
    assert inspect.iscoroutinefunction(topic.sink)
    assert len(inspect.signature(topic.sink).parameters) == 2


@pytest.mark.asyncio
async def test_start_helper_absent_bridge_returns_none_without_resources() -> None:
    event_bus = AvatarEventBus()
    relay = await start_federation_avatar_telemetry(
        bridge=None,
        peers=[PeerConfig(
            node_id="node-b",
            address="tcp://1",
            avatar_telemetry_agent_ids=[_AGENT_ID],
        )],
        registry=AgentRegistry(),
        event_bus=event_bus,
        sampling_state=_sampling_state(),
        snapshot_builder=lambda _agent_id: None,
        diff_enabled=True,
        diff_threshold=0.05,
        full_every_n=10,
    )
    assert relay is None
    assert event_bus._subscribers == {}


def test_runtime_source_wires_topic_before_bridge_and_helper_after_finalize() -> None:
    source = inspect.getsource(ProbOSRuntime.start)
    topic_index = source.index("relay_topics = build_federation_avatar_relay_topics")
    organize_index = source.index("org = await organize_fleet")
    finalize_index = source.index("finalize_startup")
    helper_index = source.index("start_federation_avatar_telemetry")
    complete_index = source.index("self._startup_complete = True")
    assert topic_index < organize_index < finalize_index < helper_index < complete_index
    assert "relay_topics=relay_topics" in source
    assert "except Exception as exc:" in source[helper_index:complete_index]


def test_shutdown_source_orders_producer_bridge_cache_transport() -> None:
    from probos.startup.shutdown import shutdown

    source = inspect.getsource(shutdown)
    producer_index = source.index("await federation_telemetry_relay.stop()")
    bridge_index = source.index("await runtime.federation_bridge.stop()")
    cache_index = source.index("remote_avatar_telemetry_cache.clear()")
    transport_index = source.index("await runtime._federation_transport.stop()")
    assert producer_index < bridge_index < cache_index < transport_index


async def _install_runtime_federation_stub(monkeypatch, runtime: ProbOSRuntime) -> None:
    import probos.startup.fleet_organization as fleet_module

    bridge = _AcceptingBridge()
    transport = _FakeTransport()

    async def _organize(**_kwargs: Any) -> FleetOrganizationResult:
        return FleetOrganizationResult(
            pool_scaler=None,
            federation_bridge=bridge,
            federation_transport=transport,
        )

    monkeypatch.setattr(fleet_module, "organize_fleet", _organize)
    runtime._ad722b5a_test_bridge = bridge
    runtime._ad722b5a_test_transport = transport


@pytest.mark.asyncio
async def test_runtime_contains_federation_telemetry_start_exception_and_completes_boot(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    config = _system_config(
        node_id="node-a",
        peers=[PeerConfig(
            node_id="node-b",
            address="tcp://1",
            avatar_telemetry_agent_ids=["missing-agent"],
        )],
    )
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data")
    await _install_runtime_federation_stub(monkeypatch, runtime)
    try:
        await runtime.start()
        assert runtime._started is True
        assert runtime._startup_complete is True
        assert runtime.federation_telemetry_relay is None
        assert "telemetry_unknown_agent_id:missing-agent" in caplog.text
        assert "telemetry disabled" in caplog.text
        assert "startup continues" in caplog.text
    finally:
        await runtime.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("peer_factory", "reason"),
    [
        (
            lambda: [PeerConfig(node_id="node-b", address="tcp://1", avatar_telemetry_agent_ids=["missing-agent"])],
            "telemetry_unknown_agent_id:missing-agent",
        ),
        (
            lambda: [
                PeerConfig(node_id="node-b", address="tcp://1", avatar_telemetry_agent_ids=[_AGENT_ID]),
                PeerConfig(node_id="node-b", address="tcp://2", avatar_telemetry_agent_ids=[_AGENT_ID]),
            ],
            "telemetry_duplicate_peer_node_id",
        ),
        (
            lambda: [
                PeerConfig(node_id=f"node-{index}", address=f"tcp://{index}", avatar_telemetry_agent_ids=[_AGENT_ID])
                for index in range(17)
            ],
            "telemetry_peer_cap_exceeded",
        ),
        (
            lambda: [
                PeerConfig(
                    node_id=f"node-{peer_index}",
                    address=f"tcp://{peer_index}",
                    avatar_telemetry_agent_ids=[
                        f"agent-{peer_index * 32 + index}"
                        for index in range(32 if peer_index < 2 else 1)
                    ],
                )
                for peer_index in range(3)
            ],
            "telemetry_agent_cap_exceeded",
        ),
    ],
)
async def test_runtime_contains_telemetry_configuration_error_without_resources(
    peer_factory: Any,
    reason: str,
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    config = _system_config(node_id="node-a", peers=peer_factory())
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / reason.replace(":", "_"))
    await _install_runtime_federation_stub(monkeypatch, runtime)
    if reason == "telemetry_duplicate_peer_node_id":
        await runtime.registry.register(_FakeAgent(agent_id=_AGENT_ID))
    try:
        await runtime.start()
        assert runtime._startup_complete is True
        assert runtime.federation_telemetry_relay is None
        assert reason in caplog.text
        assert runtime.avatar_event_bus._subscribers == {}
    finally:
        await runtime.stop()


async def _run_runtime_partial_start_fault(
    *,
    tmp_path: Path,
    monkeypatch: Any,
    fault: BaseException,
) -> tuple[ProbOSRuntime, tuple[asyncio.Task[Any], ...]]:
    config = _system_config(
        node_id="node-a",
        peers=[PeerConfig(
            node_id="node-b",
            address="tcp://1",
            avatar_telemetry_agent_ids=["agent-one", "agent-two"],
        )],
    )
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path)
    await runtime.registry.register(_FakeAgent(agent_id="agent-one"))
    await runtime.registry.register(_FakeAgent(agent_id="agent-two"))
    await _install_runtime_federation_stub(monkeypatch, runtime)
    real_create_task = relay_module.asyncio.create_task
    producer_tasks: list[asyncio.Task[Any]] = []
    producer_calls = 0

    def _fault_second(coro: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        nonlocal producer_calls
        if name and name.startswith("federation-avatar-telemetry"):
            producer_calls += 1
            if producer_calls == 2:
                coro.close()
                raise fault
        task = real_create_task(coro, name=name)
        if name and name.startswith("federation-avatar-telemetry"):
            producer_tasks.append(task)
        return task

    monkeypatch.setattr(relay_module.asyncio, "create_task", _fault_second)
    return runtime, tuple(producer_tasks)


@pytest.mark.asyncio
async def test_runtime_contains_partial_telemetry_start_failure_without_leak(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    runtime, _ = await _run_runtime_partial_start_fault(
        tmp_path=tmp_path / "ordinary",
        monkeypatch=monkeypatch,
        fault=RuntimeError("partial-start-fault"),
    )
    try:
        await runtime.start()
        assert runtime._startup_complete is True
        assert runtime.federation_telemetry_relay is None
        assert runtime.avatar_event_bus._subscribers == {}
        assert "partial-start-fault" in caplog.text
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_telemetry_start_cancellation_propagates(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    runtime, _ = await _run_runtime_partial_start_fault(
        tmp_path=tmp_path / "cancel",
        monkeypatch=monkeypatch,
        fault=asyncio.CancelledError(),
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await runtime.start()
        assert runtime.avatar_event_bus._subscribers == {}
        assert runtime._startup_complete is False
        assert "telemetry disabled" not in caplog.text
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_telemetry_start_baseexception_propagates(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    marker = BaseException("telemetry-lifecycle")
    runtime, _ = await _run_runtime_partial_start_fault(
        tmp_path=tmp_path / "baseexception",
        monkeypatch=monkeypatch,
        fault=marker,
    )
    try:
        with pytest.raises(BaseException) as exc_info:
            await runtime.start()
        assert exc_info.value is marker
        assert runtime.avatar_event_bus._subscribers == {}
        assert runtime._startup_complete is False
        assert "telemetry disabled" not in caplog.text
    finally:
        await runtime.stop()


def test_changed_production_has_no_forbidden_governance_or_browser_paths() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "src/probos/avatars/telemetry_frames.py",
        root / "src/probos/federation/telemetry_relay.py",
        root / "src/probos/startup/federation_telemetry.py",
    ]
    forbidden = (
        "IntentMessage",
        "IntentBus",
        "EventType",
        "emit_event",
        "record_outcome",
        "hebbian",
        "episodic",
        "origin_mesh_id",
        "vrm_url",
        "Queue(",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for token in forbidden:
        assert token not in combined
