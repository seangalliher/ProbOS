"""AD-722b-1 (Wave 161) - crew-scope auth substrate for telemetry surfaces.

Eight tests cover HTTP (4) + WebSocket (4) paths:
- Auth disabled (empty config token) -> pass-through.
- Auth enabled, missing/wrong token -> 401 / WS 1008.
- Auth enabled, correct token -> allowed through.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars.events import AvatarEventBus
from probos.avatars.sampling_state import AvatarSamplingStateMachine
from probos.avatars.ws_connection_manager import AvatarTelemetryConnectionManager
from probos.config import SamplingRatesConfig
from probos.crew_profile import AppearanceProfile, CrewProfile, VoiceProfile
from probos.types import AgentState


def _make_runtime(*, crew_scope_token: str = "") -> Any:
    runtime = MagicMock()
    runtime.registry = MagicMock()

    cid = "crew-a"
    ag = MagicMock()
    ag.id = cid
    ag.agent_id = cid
    ag.agent_type = "counselor"
    ag.state = AgentState.ACTIVE
    ag.last_reply_emitted_at = 0.0
    runtime.registry.agents = {cid: ag}
    runtime.registry.get = lambda aid: runtime.registry.agents.get(aid)

    crew = CrewProfile(agent_id=cid, agent_type="counselor")
    crew.appearance = AppearanceProfile(vrm_url="", dsl=None)
    crew.voice = VoiceProfile()
    profile_store = MagicMock()
    profile_store.profiles = {cid: crew}
    profile_store.get = lambda aid: profile_store.profiles.get(aid)
    runtime.profile_store = profile_store

    runtime.trust_network = MagicMock()
    runtime.trust_network.get_history.return_value = []
    runtime.trust_network.get_score.return_value = 0.5
    runtime.bridge_alerts = MagicMock()
    runtime.bridge_alerts.get_recent_alerts.return_value = []

    cfg = MagicMock()
    cfg.avatars = MagicMock()
    cfg.avatars.enabled = True
    cfg.avatars.avatars_dir = "data/avatars"
    cfg.avatars.max_vrm_size_bytes = 25 * 1024 * 1024
    cfg.avatar_telemetry = MagicMock()
    cfg.avatar_telemetry.enabled = True
    cfg.avatar_telemetry.inject_into_agent_context = False
    cfg.avatar_telemetry.mouth_active_window_seconds = 3.0
    cfg.avatar_telemetry.polling_interval_ms = 2000
    cfg.avatar_telemetry.max_connections_per_agent = 4
    cfg.avatar_telemetry.ws_diff_enabled = False
    cfg.avatar_telemetry.ws_diff_threshold = 0.05
    cfg.avatar_telemetry.ws_full_snapshot_every_n = 10
    cfg.avatar_telemetry.fleet_stream_enabled = True
    cfg.avatar_telemetry.history_enabled = False
    cfg.avatar_telemetry.history_retention_days = 7
    cfg.auth = MagicMock()
    cfg.auth.crew_scope_token = crew_scope_token
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


@pytest.fixture(autouse=True)
def _crew_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "probos.routers.agents.is_crew_agent", lambda agent, ontology: True,
    )


# ── HTTP tests ──────────────────────────────────────────────────────────


def test_http_auth_disabled_allows_through() -> None:
    rt = _make_runtime(crew_scope_token="")
    client = TestClient(_make_app(rt))
    resp = client.get("/api/agent/crew-a/avatar-telemetry")
    assert resp.status_code != 401


def test_http_auth_enabled_missing_header_returns_401() -> None:
    rt = _make_runtime(crew_scope_token="secret")
    client = TestClient(_make_app(rt))
    resp = client.get("/api/agent/crew-a/avatar-telemetry")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_or_malformed_authorization"


def test_http_auth_enabled_wrong_token_returns_401() -> None:
    rt = _make_runtime(crew_scope_token="secret")
    client = TestClient(_make_app(rt))
    resp = client.get(
        "/api/agent/crew-a/avatar-telemetry",
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_token"


def test_http_auth_enabled_correct_token_allows_through() -> None:
    rt = _make_runtime(crew_scope_token="secret")
    client = TestClient(_make_app(rt))
    resp = client.get(
        "/api/agent/crew-a/avatar-telemetry",
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code != 401


# ── WebSocket tests ─────────────────────────────────────────────────────


def test_ws_auth_disabled_allows_connect() -> None:
    rt = _make_runtime(crew_scope_token="")
    client = TestClient(_make_app(rt))
    # No ?token=; connection should proceed past the auth gate.
    with client.websocket_connect("/api/agent/crew-a/avatar-telemetry-stream") as ws:
        ws.close()


def test_ws_auth_enabled_missing_token_closes_1008() -> None:
    from starlette.websockets import WebSocketDisconnect
    rt = _make_runtime(crew_scope_token="secret")
    client = TestClient(_make_app(rt))
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/api/agent/crew-a/avatar-telemetry-stream"
        ) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


def test_ws_auth_enabled_wrong_token_closes_1008() -> None:
    from starlette.websockets import WebSocketDisconnect
    rt = _make_runtime(crew_scope_token="secret")
    client = TestClient(_make_app(rt))
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/api/agent/crew-a/avatar-telemetry-stream?token=wrong"
        ) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


def test_ws_auth_enabled_correct_token_accepts() -> None:
    rt = _make_runtime(crew_scope_token="secret")
    client = TestClient(_make_app(rt))
    with client.websocket_connect(
        "/api/agent/crew-a/avatar-telemetry-stream?token=secret"
    ) as ws:
        ws.close()
