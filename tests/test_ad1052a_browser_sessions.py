"""AD-1052a — Browser Workstation WATCH mode: sessions-list surface tests.

BF-287 real fixtures: real ``BrowserToolConfig`` / ``BrowserSession`` /
``BrowserTool`` and a real ``SystemConfig()`` at the auth boundary (NOT a
MagicMock config). Sessions are seeded into ``tool._sessions`` directly (no
``session.start()`` / Playwright), mirroring
``tests/test_ad706a_browser_streaming.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars.events import AvatarEventBus
from probos.avatars.sampling_state import AvatarSamplingStateMachine
from probos.config import BrowserToolConfig, SamplingRatesConfig, SystemConfig
from probos.crew_profile import AppearanceProfile, CrewProfile, VoiceProfile
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool
from probos.types import AgentState


# ---------------------------------------------------------------------------
# Section 1: session public properties (agent_id / last_url)
# ---------------------------------------------------------------------------


def test_session_agent_id_property() -> None:
    cfg = BrowserToolConfig(enabled=True)
    sess = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    assert sess.agent_id == "a1"


def test_session_last_url_defaults_empty() -> None:
    cfg = BrowserToolConfig(enabled=True)
    sess = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    assert sess.last_url == ""


# ---------------------------------------------------------------------------
# Section 2: BrowserTool.list_sessions()
# ---------------------------------------------------------------------------


def test_list_sessions_empty() -> None:
    cfg = BrowserToolConfig(enabled=True)
    tool = BrowserTool(config=cfg)
    assert tool.list_sessions() == []


def test_list_sessions_streaming_disabled_url_none() -> None:
    cfg = BrowserToolConfig(enabled=True)  # streaming_enabled defaults False
    assert cfg.streaming_enabled is False
    tool = BrowserTool(config=cfg)
    tool._sessions["s1"] = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    rows = tool.list_sessions()
    assert len(rows) == 1
    entry = rows[0]
    assert entry["streaming_url"] is None
    assert entry["session_id"] == "s1"
    assert entry["agent_id"] == "a1"
    assert entry["last_url"] == ""


def test_list_sessions_streaming_enabled_url_path() -> None:
    cfg = BrowserToolConfig(enabled=True, streaming_enabled=True)
    tool = BrowserTool(config=cfg)
    tool._sessions["s1"] = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    rows = tool.list_sessions()
    assert rows[0]["streaming_url"] == "/api/browser/sessions/s1/stream"


# ---------------------------------------------------------------------------
# Endpoint scaffolding (copied verbatim from test_ad706a_browser_streaming.py —
# the proven create_app + real-SystemConfig + crew pass-through wiring).
# ---------------------------------------------------------------------------


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

    # BF-287: real Pydantic SystemConfig() so substrate auth code reads real
    # values rather than MagicMock auto-attributes.
    runtime.config = SystemConfig()
    runtime.config.auth.crew_scope_token = crew_scope_token

    runtime.avatar_sampling_state = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    runtime.avatar_event_bus = AvatarEventBus()
    runtime.avatar_telemetry_connection_manager = MagicMock()
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

    events: list[tuple[Any, dict]] = []
    runtime._emitted_events = events

    def _emit(event_type: Any, payload: dict) -> None:
        events.append((event_type, payload))

    runtime.emit_event = _emit
    return runtime


def _make_app(runtime: Any):
    from probos.api import create_app
    return create_app(runtime)


@pytest.fixture(autouse=True)
def _crew_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "probos.routers.agents.is_crew_agent", lambda agent, ontology: True,
    )


# ---------------------------------------------------------------------------
# Section 3: GET /api/browser/sessions endpoint
# ---------------------------------------------------------------------------


def test_endpoint_disabled_honest_degrade() -> None:
    rt = _make_runtime()
    # finalize._wire_browser_tool returns early when the tool is disabled ->
    # runtime.browser_tool is never set; getattr(...,"browser_tool",None) is None.
    rt.browser_tool = None
    client = TestClient(_make_app(rt))
    resp = client.get("/api/browser/sessions")
    assert resp.status_code == 200
    # AD-1052c added the additive `input_forwarding_enabled` field (default-OFF).
    assert resp.json() == {"enabled": False, "sessions": [], "input_forwarding_enabled": False}


def test_endpoint_lists_seeded_sessions() -> None:
    rt = _make_runtime()
    cfg = rt.config.browser_tool
    cfg.enabled = True
    cfg.streaming_enabled = True
    tool = BrowserTool(config=cfg, emit_event=rt.emit_event, runtime=rt)
    for sid, aid in (("s1", "a1"), ("s2", "a2")):
        tool._sessions[sid] = BrowserSession(session_id=sid, agent_id=aid, config=cfg)
    rt.browser_tool = tool

    client = TestClient(_make_app(rt))
    resp = client.get("/api/browser/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert len(data["sessions"]) == 2
    assert {s["session_id"] for s in data["sessions"]} == {"s1", "s2"}
    s1 = next(s for s in data["sessions"] if s["session_id"] == "s1")
    assert s1["agent_id"] == "a1"
    assert s1["streaming_url"] == "/api/browser/sessions/s1/stream"
    assert s1["last_url"] == ""

    # Auth: a configured crew-scope token + no token -> 401 (mirror AD-706a).
    rt_auth = _make_runtime(crew_scope_token="secret")
    cfg2 = rt_auth.config.browser_tool
    cfg2.enabled = True
    tool2 = BrowserTool(config=cfg2, emit_event=rt_auth.emit_event, runtime=rt_auth)
    tool2._sessions["s1"] = BrowserSession(session_id="s1", agent_id="a1", config=cfg2)
    rt_auth.browser_tool = tool2
    client2 = TestClient(_make_app(rt_auth))
    resp2 = client2.get("/api/browser/sessions")
    assert resp2.status_code == 401
