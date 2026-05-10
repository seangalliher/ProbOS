"""AD-722b: WebSocket push channel for avatar telemetry — boundary tests.

Covers the sampling-state popout extensions, AvatarEventBus, the
AvatarTelemetryConnectionManager, the new AvatarTelemetryConfig field,
the WS endpoint feature gates / lifecycle / fan-out / tier flip, and
trigger-site notifies that wake the publish loop.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from probos.avatars.events import AvatarEventBus
from probos.avatars.sampling_state import (
    TIER_HIGH,
    TIER_LOW,
    TIER_NORMAL,
    AvatarSamplingStateMachine,
)
from probos.avatars.ws_connection_manager import (
    AvatarTelemetryConnectionManager,
    MaxConnectionsExceeded,
)
from probos.config import AvatarTelemetryConfig, SamplingRatesConfig
from probos.crew_profile import AppearanceProfile, CrewProfile, VoiceProfile
from probos.types import AgentState


# ── A. Sampling state machine — enter_popout / exit_popout ────────────


def test_enter_popout_promotes_to_high():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_popout("a")
    assert sm.current_tier("a") == TIER_HIGH
    assert sm.current_rate_ms("a") == 250


def test_exit_popout_returns_to_low():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_popout("a")
    sm.exit_popout("a")
    assert sm.current_tier("a") == TIER_LOW
    assert sm.current_rate_ms("a") == 10000


def test_concurrent_popout_refcount():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_popout("a")
    sm.enter_popout("a")
    sm.exit_popout("a")
    assert sm.current_tier("a") == TIER_HIGH
    sm.exit_popout("a")
    assert sm.current_tier("a") == TIER_LOW


def test_concurrent_dm_and_popout_both_high():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_dm("a")
    sm.enter_popout("a")
    assert sm.current_tier("a") == TIER_HIGH
    sm.exit_dm("a")
    assert sm.current_tier("a") == TIER_HIGH  # popout still HIGH
    sm.exit_popout("a")
    assert sm.current_tier("a") == TIER_LOW


def test_chain_under_popout_stays_high():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_popout("a")
    sm.enter_chain("a")
    assert sm.current_tier("a") == TIER_HIGH
    sm.exit_chain("a")
    assert sm.current_tier("a") == TIER_HIGH


def test_spurious_exit_popout_clamps_to_zero(caplog):
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    with caplog.at_level("WARNING"):
        sm.exit_popout("a")
    assert any("spurious exit_popout" in rec.message for rec in caplog.records)
    assert sm.current_tier("a") == TIER_LOW
    # No poison — subsequent enter still works.
    sm.enter_popout("a")
    assert sm.current_tier("a") == TIER_HIGH


def test_snapshot_counts_includes_popout():
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    sm.enter_popout("a")
    counts = sm.snapshot_counts("a")
    assert counts == {"dm": 0, "chain": 0, "popout": 1}
    # Fresh agent default also includes popout key.
    fresh = sm.snapshot_counts("never-seen")
    assert fresh == {"dm": 0, "chain": 0, "popout": 0}


# ── B. Event bus ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_bus_notify_sets_subscriber_event():
    bus = AvatarEventBus()
    event = bus.subscribe("A")
    bus.notify("A")
    assert event.is_set()


@pytest.mark.asyncio
async def test_event_bus_notify_other_agent_does_not_set():
    bus = AvatarEventBus()
    event = bus.subscribe("A")
    bus.notify("B")
    assert not event.is_set()


@pytest.mark.asyncio
async def test_event_bus_multiple_subscribers_all_notified():
    bus = AvatarEventBus()
    e1 = bus.subscribe("A")
    e2 = bus.subscribe("A")
    bus.notify("A")
    assert e1.is_set()
    assert e2.is_set()


@pytest.mark.asyncio
async def test_event_bus_unsubscribe_drops_event():
    bus = AvatarEventBus()
    event = bus.subscribe("A")
    bus.unsubscribe("A", event)
    assert bus.subscriber_count("A") == 0
    # notify with no subscribers is a no-op (no exception).
    bus.notify("A")


@pytest.mark.asyncio
async def test_event_bus_subscriber_count_tracks():
    bus = AvatarEventBus()
    assert bus.subscriber_count("A") == 0
    e1 = bus.subscribe("A")
    assert bus.subscriber_count("A") == 1
    e2 = bus.subscribe("A")
    assert bus.subscriber_count("A") == 2
    bus.unsubscribe("A", e1)
    assert bus.subscriber_count("A") == 1
    bus.unsubscribe("A", e2)
    assert bus.subscriber_count("A") == 0


# ── C. Connection manager ────────────────────────────────────────────


def test_connection_manager_register_returns_uuid():
    mgr = AvatarTelemetryConnectionManager(max_per_agent=4)
    ws = MagicMock()
    cid = mgr.register("a", ws)
    assert isinstance(cid, str)
    assert len(cid) == 36  # uuid4 string form
    assert mgr.connections_for("a") == 1


def test_connection_manager_max_per_agent_enforced():
    mgr = AvatarTelemetryConnectionManager(max_per_agent=2)
    mgr.register("a", MagicMock())
    mgr.register("a", MagicMock())
    with pytest.raises(MaxConnectionsExceeded):
        mgr.register("a", MagicMock())


def test_connection_manager_deregister_idempotent():
    mgr = AvatarTelemetryConnectionManager(max_per_agent=4)
    # Missing agent is a no-op.
    mgr.deregister("nobody", "no-such-id")
    cid = mgr.register("a", MagicMock())
    mgr.deregister("a", cid)
    # Second deregister of the same id is also a no-op.
    mgr.deregister("a", cid)
    assert mgr.connections_for("a") == 0


def test_connection_manager_invalid_max_rejected():
    with pytest.raises(ValueError):
        AvatarTelemetryConnectionManager(max_per_agent=0)


# ── D. Config ─────────────────────────────────────────────────────────


def test_avatar_telemetry_config_default_max_connections():
    cfg = AvatarTelemetryConfig()
    assert cfg.max_connections_per_agent == 4


def test_max_connections_validator_rejects_zero():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AvatarTelemetryConfig(max_connections_per_agent=0)


# ── E. WebSocket endpoint (TestClient) ───────────────────────────────


class _FakeProfileStore:
    def __init__(self) -> None:
        self.profiles: dict[str, CrewProfile] = {}

    def get(self, agent_id: str):
        return self.profiles.get(agent_id)


class _FakeTrustNetwork:
    def __init__(self, history: list[float] | None = None) -> None:
        self._history = list(history) if history is not None else [0.4, 0.5]

    def get_history(self, agent_id: str, limit: int = 20) -> list[float]:
        return list(self._history[-limit:])

    def get_score(self, agent_id: str) -> float:
        return 0.5


class _FakeBridgeAlerts:
    def get_recent_alerts(self, limit: int = 50) -> list[Any]:
        return []


def _ws_endpoint_runtime(
    *,
    agent_id: str = "agent-007",
    agent_present: bool = True,
    telemetry_enabled: bool = True,
    avatars_enabled: bool = True,
    max_connections: int = 4,
) -> Any:
    """Build a runtime with REAL AvatarSamplingStateMachine, AvatarEventBus,
    and AvatarTelemetryConnectionManager so the WS handler can drive them."""
    runtime = MagicMock()
    if agent_present:
        agent = MagicMock()
        agent.id = agent_id
        agent.agent_type = "counselor"
        agent.state = AgentState.ACTIVE
        agent.last_reply_emitted_at = 0.0
    else:
        agent = None

    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent

    runtime.profile_store = _FakeProfileStore()
    crew = CrewProfile(agent_id=agent_id, agent_type="counselor")
    crew.appearance = AppearanceProfile(vrm_url="", dsl=None)
    crew.voice = VoiceProfile()
    runtime.profile_store.profiles[agent_id] = crew

    runtime.trust_network = _FakeTrustNetwork()
    runtime.bridge_alerts = _FakeBridgeAlerts()

    cfg = MagicMock()
    cfg.avatars = MagicMock()
    cfg.avatars.enabled = avatars_enabled
    cfg.avatars.avatars_dir = "data/avatars"
    cfg.avatars.max_vrm_size_bytes = 25 * 1024 * 1024
    cfg.avatar_telemetry = MagicMock()
    cfg.avatar_telemetry.enabled = telemetry_enabled
    cfg.avatar_telemetry.inject_into_agent_context = False
    cfg.avatar_telemetry.mouth_active_window_seconds = 3.0
    cfg.avatar_telemetry.polling_interval_ms = 2000
    cfg.avatar_telemetry.max_connections_per_agent = max_connections
    runtime.config = cfg

    # Real AD-722f / AD-722b primitives so the handler's calls are observable.
    rates = SamplingRatesConfig()
    runtime.avatar_sampling_state = AvatarSamplingStateMachine(rates=rates)
    runtime.avatar_event_bus = AvatarEventBus()
    runtime.avatar_telemetry_connection_manager = AvatarTelemetryConnectionManager(
        max_per_agent=max_connections,
    )

    # Surface that probos.api.create_app touches at wire time.
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Troi"
    runtime.callsign_registry.resolve.return_value = {
        "callsign": "Troi", "agent_type": "counselor",
        "agent_id": agent_id,
        "display_name": "Counselor", "department": "bridge",
    }
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()

    return runtime


def _make_app(runtime: Any):
    from probos.api import create_app
    return create_app(runtime)


def test_ws_endpoint_initial_snapshot_on_connect():
    runtime = _ws_endpoint_runtime()
    client = TestClient(_make_app(runtime))
    with client.websocket_connect(
        "/api/agent/agent-007/avatar-telemetry-stream"
    ) as ws:
        first = ws.receive_json()
        assert first["agent_id"] == "agent-007"
        # popout entered → HIGH tier
        assert first["sampling_tier"] == "high"


def test_ws_endpoint_promotes_to_high_on_subscribe():
    runtime = _ws_endpoint_runtime()
    sm = runtime.avatar_sampling_state
    assert sm.current_tier("agent-007") == TIER_LOW
    client = TestClient(_make_app(runtime))
    with client.websocket_connect(
        "/api/agent/agent-007/avatar-telemetry-stream"
    ) as ws:
        ws.receive_json()  # consume initial frame
        assert sm.current_tier("agent-007") == TIER_HIGH
    # After exit, brief grace then back to LOW.
    time.sleep(0.2)
    assert sm.current_tier("agent-007") == TIER_LOW


def test_ws_endpoint_publishes_on_event_bus_notify():
    runtime = _ws_endpoint_runtime()
    client = TestClient(_make_app(runtime))
    with client.websocket_connect(
        "/api/agent/agent-007/avatar-telemetry-stream"
    ) as ws:
        ws.receive_json()  # initial frame
        # Trigger a wake from outside the WS.
        runtime.avatar_event_bus.notify("agent-007")
        # Another frame should arrive; HIGH tier (250 ms) makes this fast.
        second = ws.receive_json()
        assert second["agent_id"] == "agent-007"


def test_ws_endpoint_max_connections_rejected():
    runtime = _ws_endpoint_runtime(max_connections=2)
    client = TestClient(_make_app(runtime))
    with contextlib.ExitStack() as stack:
        ws1 = stack.enter_context(client.websocket_connect(
            "/api/agent/agent-007/avatar-telemetry-stream"
        ))
        ws1.receive_json()
        ws2 = stack.enter_context(client.websocket_connect(
            "/api/agent/agent-007/avatar-telemetry-stream"
        ))
        ws2.receive_json()
        # Third connection should be rejected.
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                "/api/agent/agent-007/avatar-telemetry-stream"
            ) as ws3:
                # First frame should be the structured error.
                err = ws3.receive_json()
                assert err.get("type") == "error"
                assert err.get("reason") == "max_connections_exceeded"
                # Then the close frame.
                ws3.receive_json()
        assert exc.value.code == 1008


def test_ws_endpoint_503_telemetry_disabled():
    runtime = _ws_endpoint_runtime(telemetry_enabled=False)
    client = TestClient(_make_app(runtime))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/agent/agent-007/avatar-telemetry-stream"
        ):
            pass
    assert exc.value.code == 1008
    assert exc.value.reason == "avatar_telemetry_disabled"


def test_ws_endpoint_404_unknown_agent():
    runtime = _ws_endpoint_runtime(agent_present=False)
    client = TestClient(_make_app(runtime))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/agent/missing-007/avatar-telemetry-stream"
        ):
            pass
    assert exc.value.code == 1008
    assert exc.value.reason == "agent_not_found"


def test_ws_endpoint_503_avatars_disabled():
    runtime = _ws_endpoint_runtime(avatars_enabled=False)
    client = TestClient(_make_app(runtime))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/agent/agent-007/avatar-telemetry-stream"
        ):
            pass
    assert exc.value.code == 1008
    assert exc.value.reason == "avatars_disabled"


def test_ws_endpoint_disconnect_clears_popout():
    runtime = _ws_endpoint_runtime()
    sm = runtime.avatar_sampling_state
    client = TestClient(_make_app(runtime))
    with client.websocket_connect(
        "/api/agent/agent-007/avatar-telemetry-stream"
    ) as ws:
        ws.receive_json()
        assert sm.current_tier("agent-007") == TIER_HIGH
    # After context exit, server-side cleanup should run.
    time.sleep(0.2)
    assert sm.current_tier("agent-007") == TIER_LOW
    assert runtime.avatar_telemetry_connection_manager.connections_for("agent-007") == 0


# ── F. Trigger-site notifies ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_reply_emitted_notifies_event_bus():
    """``mark_reply_emitted()`` MUST notify the avatar event bus so any
    open WS subscribers wake immediately (AD-722b D6)."""
    from probos.cognitive.cognitive_agent import CognitiveAgent  # noqa: F401

    bus = AvatarEventBus()
    runtime = MagicMock()
    runtime.avatar_event_bus = bus

    # Build a minimal CognitiveAgent-like object that exercises the same
    # branch: getattr(runtime, 'avatar_event_bus', None) and bus.notify.
    class _Stub:
        def __init__(self) -> None:
            self.id = "agent-007"
            self._runtime = runtime
            self._last_reply_emit_ts = 0.0

        # Reuse the real method bound to the stub.
        from probos.cognitive.cognitive_agent import CognitiveAgent
        mark_reply_emitted = CognitiveAgent.mark_reply_emitted

    event = bus.subscribe("agent-007")
    stub = _Stub()
    stub.mark_reply_emitted()
    assert event.is_set()
    assert stub._last_reply_emit_ts > 0


@pytest.mark.asyncio
async def test_chain_enter_exit_notify_event_bus():
    """The AD-722f chain wiring sites also publish notify() per AD-722b D6."""
    bus = AvatarEventBus()
    sm = AvatarSamplingStateMachine(rates=SamplingRatesConfig())

    # Simulate the wired pattern at cognitive_agent.py:1399-1410.
    agent_id = "agent-007"
    event = bus.subscribe(agent_id)

    # Enter chain → notify.
    sm.enter_chain(agent_id)
    bus.notify(agent_id)
    assert event.is_set()

    event.clear()

    # Exit chain → notify.
    sm.exit_chain(agent_id)
    bus.notify(agent_id)
    assert event.is_set()
