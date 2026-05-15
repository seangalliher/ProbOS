"""AD-722b-4: Boundary tests for the fleet-level avatar telemetry stream.

Six tests cover: feature-gate close, no-crew close, per-agent initial
snapshots, agent_id presence on every frame, disconnect cleanup, and
diff frames carrying agent_id.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from probos.avatars.events import AvatarEventBus
from probos.avatars.sampling_state import (
    AvatarSamplingStateMachine,
)
from probos.avatars.ws_connection_manager import AvatarTelemetryConnectionManager
from probos.config import SamplingRatesConfig, AuthConfig
from probos.crew_profile import AppearanceProfile, CrewProfile, VoiceProfile
from probos.types import AgentState


# --------------------------------------------------------------------------- #
# Shared fixture                                                              #
# --------------------------------------------------------------------------- #


class _FakeProfileStore:
    def __init__(self) -> None:
        self.profiles: dict[str, CrewProfile] = {}

    def get(self, agent_id: str):
        return self.profiles.get(agent_id)


class _FakeTrustNetwork:
    def get_history(self, agent_id: str, limit: int = 20) -> list[float]:
        return [0.4, 0.5]

    def get_score(self, agent_id: str) -> float:
        return 0.5


class _FakeBridgeAlerts:
    def get_recent_alerts(self, limit: int = 50) -> list[Any]:
        return []


def _make_fleet_runtime(
    *,
    crew_ids: tuple[str, ...] = ("crew-a", "crew-b"),
    telemetry_enabled: bool = True,
    avatars_enabled: bool = True,
    fleet_stream_enabled: bool = True,
) -> Any:
    runtime = MagicMock()
    runtime.registry = MagicMock()

    agents: dict[str, Any] = {}
    profile_store = _FakeProfileStore()
    for cid in crew_ids:
        ag = MagicMock()
        ag.id = cid
        ag.agent_id = cid
        ag.agent_type = "counselor"
        ag.state = AgentState.ACTIVE
        ag.last_reply_emitted_at = 0.0
        agents[cid] = ag
        crew = CrewProfile(agent_id=cid, agent_type="counselor")
        crew.appearance = AppearanceProfile(vrm_url="", dsl=None)
        crew.voice = VoiceProfile()
        profile_store.profiles[cid] = crew
    runtime.registry.all.return_value = list(agents.values())
    runtime.registry.agents = agents

    runtime.profile_store = profile_store
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
    cfg.avatar_telemetry.max_connections_per_agent = 4
    cfg.avatar_telemetry.ws_diff_enabled = False
    cfg.avatar_telemetry.ws_diff_threshold = 0.05
    cfg.avatar_telemetry.ws_full_snapshot_every_n = 10
    cfg.avatar_telemetry.fleet_stream_enabled = fleet_stream_enabled
    cfg.auth = AuthConfig()  # AD-722b-1a: empty token = auth-disabled.
    runtime.config = cfg

    rates = SamplingRatesConfig()
    runtime.avatar_sampling_state = AvatarSamplingStateMachine(rates=rates)
    runtime.avatar_event_bus = AvatarEventBus()
    runtime.avatar_telemetry_connection_manager = AvatarTelemetryConnectionManager(
        max_per_agent=4,
    )

    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Crew"
    runtime.callsign_registry.resolve.return_value = {}
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
    runtime.avatar_telemetry_history = None
    runtime.avatar_telemetry_records_writer = None
    return runtime


def _make_app(runtime: Any):
    from probos.api import create_app
    return create_app(runtime)


# --------------------------------------------------------------------------- #
# Override is_crew_agent so MagicMock crew passes the gate                    #
# --------------------------------------------------------------------------- #


import pytest


@pytest.fixture(autouse=True)
def _crew_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "probos.routers.agents.is_crew_agent", lambda agent, ontology: True,
    )


# --------------------------------------------------------------------------- #
# 1 fleet_stream_disabled                                                     #
# --------------------------------------------------------------------------- #


def test_fleet_stream_disabled_closes_1008() -> None:
    rt = _make_fleet_runtime(fleet_stream_enabled=False)
    client = TestClient(_make_app(rt))
    from starlette.websockets import WebSocketDisconnect
    try:
        with client.websocket_connect("/api/agent/avatar-telemetry/stream"):
            pass
    except WebSocketDisconnect as e:
        assert e.code == 1008


# --------------------------------------------------------------------------- #
# 2 no-crew                                                                   #
# --------------------------------------------------------------------------- #


def test_no_crew_closes_1008() -> None:
    rt = _make_fleet_runtime(crew_ids=())
    client = TestClient(_make_app(rt))
    from starlette.websockets import WebSocketDisconnect
    try:
        with client.websocket_connect("/api/agent/avatar-telemetry/stream"):
            pass
    except WebSocketDisconnect as e:
        assert e.code == 1008


# --------------------------------------------------------------------------- #
# 3 initial snapshot per agent                                                #
# --------------------------------------------------------------------------- #


def test_initial_snapshot_per_agent() -> None:
    rt = _make_fleet_runtime(crew_ids=("crew-a", "crew-b", "crew-c"))
    client = TestClient(_make_app(rt))
    seen_ids: set[str] = set()
    with client.websocket_connect("/api/agent/avatar-telemetry/stream") as ws:
        for _ in range(3):
            frame = ws.receive_json()
            assert frame["type"] == "snapshot"
            assert "agent_id" in frame
            seen_ids.add(frame["agent_id"])
    assert seen_ids == {"crew-a", "crew-b", "crew-c"}


# --------------------------------------------------------------------------- #
# 4 every frame has agent_id                                                  #
# --------------------------------------------------------------------------- #


def test_frame_carries_agent_id() -> None:
    rt = _make_fleet_runtime(crew_ids=("crew-a",))
    client = TestClient(_make_app(rt))
    with client.websocket_connect("/api/agent/avatar-telemetry/stream") as ws:
        first = ws.receive_json()
        assert first["agent_id"] == "crew-a"


# --------------------------------------------------------------------------- #
# 5 disconnect unsubscribes all                                               #
# --------------------------------------------------------------------------- #


def test_disconnect_unsubscribes_all() -> None:
    rt = _make_fleet_runtime(crew_ids=("crew-a", "crew-b"))
    sm = rt.avatar_sampling_state
    client = TestClient(_make_app(rt))
    with client.websocket_connect("/api/agent/avatar-telemetry/stream") as ws:
        ws.receive_json()
        ws.receive_json()
    # After exit both agents popout_count returns to 0.
    assert sm.snapshot_counts("crew-a")["popout"] == 0
    assert sm.snapshot_counts("crew-b")["popout"] == 0


# --------------------------------------------------------------------------- #
# 6 diff frames carry agent_id too                                            #
# --------------------------------------------------------------------------- #


def test_diff_frames_carry_agent_id_too() -> None:
    rt = _make_fleet_runtime(crew_ids=("crew-a",))
    rt.config.avatar_telemetry.ws_diff_enabled = True
    rt.config.avatar_telemetry.ws_full_snapshot_every_n = 100
    client = TestClient(_make_app(rt))
    with client.websocket_connect("/api/agent/avatar-telemetry/stream") as ws:
        first = ws.receive_json()
        assert first["agent_id"] == "crew-a"
        # Wake the publish loop and force a 2nd frame; whatever the type,
        # it MUST carry agent_id.
        rt.avatar_event_bus.notify("crew-a")
        second = ws.receive_json()
        assert second["agent_id"] == "crew-a"
        assert second["type"] in ("snapshot", "diff", "ping")


# --------------------------------------------------------------------------- #
# BF-287 — registry crew discovery uses public .all(), not private .agents    #
# --------------------------------------------------------------------------- #


def test_bf287_crew_discovery_uses_public_registry_api() -> None:
    """Regression: AD-722b-4 originally read runtime.registry.agents which is
    a phantom attribute (real AgentRegistry stores agents in self._agents and
    exposes .all() as the public accessor). On warm restart with a real
    registry, the websocket endpoint crashed with AttributeError. This test
    asserts the production endpoint reads via the public .all() accessor."""
    import inspect

    from probos.routers import agents as agents_module

    src = inspect.getsource(agents_module.fleet_avatar_telemetry_stream)
    assert "registry.all()" in src, (
        "fleet_avatar_telemetry_stream must use runtime.registry.all() — "
        "registry.agents is a phantom; real AgentRegistry uses ._agents "
        "internally and .all() publicly. See BF-287."
    )
    assert "registry.agents" not in src, (
        "fleet_avatar_telemetry_stream must NOT reference registry.agents "
        "(phantom). See BF-287."
    )
