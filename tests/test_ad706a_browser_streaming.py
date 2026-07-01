"""AD-706a (Wave 166) - Captain-watch MJPEG streaming bridge tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars.events import AvatarEventBus
from probos.avatars.sampling_state import AvatarSamplingStateMachine
from probos.config import BrowserToolConfig, SamplingRatesConfig, SystemConfig
from probos.crew_profile import AppearanceProfile, CrewProfile, VoiceProfile
from probos.events import EventType
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool
from probos.types import AgentState


# ---------------------------------------------------------------------------
# Section 3 / 1: get_streaming_url + config defaults
# ---------------------------------------------------------------------------


def test_streaming_disabled_by_default() -> None:
    cfg = BrowserToolConfig(enabled=True)
    assert cfg.streaming_enabled is False
    sess = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    assert sess.get_streaming_url() is None


def test_streaming_enabled_populates_url() -> None:
    cfg = BrowserToolConfig(enabled=True, streaming_enabled=True)
    sess = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    assert sess.get_streaming_url() == "/api/browser/sessions/s1/stream"


# ---------------------------------------------------------------------------
# Section 2a: viewer-slot public API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_decrements_viewer_count_on_disconnect() -> None:
    cfg = BrowserToolConfig(enabled=True, streaming_max_concurrent_viewers=2)
    tool = BrowserTool(config=cfg)
    assert tool.active_viewers == 0
    assert await tool.acquire_viewer_slot() is True
    assert tool.active_viewers == 1
    await tool.release_viewer_slot()
    assert tool.active_viewers == 0


# ---------------------------------------------------------------------------
# Section 2: endpoint behaviours (use TestClient with a real FastAPI app)
# ---------------------------------------------------------------------------


class _FakePage:
    """Stub Playwright page yielding fake JPEG bytes for a bounded number of frames.

    After ``max_frames`` calls, ``screenshot()`` raises to terminate the
    streaming generator (so TestClient's blocking request finishes). The
    generator's Tier-2 except-handler emits ``BROWSER_STREAM_CLOSED``.
    """

    def __init__(self, max_frames: int = 2) -> None:
        self.calls = 0
        self._max_frames = max_frames

    async def screenshot(self, *, type: str = "jpeg", quality: int = 60) -> bytes:  # noqa: A002
        self.calls += 1
        if self.calls > self._max_frames:
            raise RuntimeError("ad706a-test: terminate stream")
        # Minimal JPEG SOI/EOI markers, padded with the call number.
        return b"\xff\xd8" + bytes([self.calls % 256]) * 16 + b"\xff\xd9"


def _seed_browser_tool(
    runtime: Any, *, viewer_cap: int = 4, max_frames: int = 2
) -> tuple[BrowserTool, BrowserSession, _FakePage]:
    cfg = runtime.config.browser_tool
    cfg.enabled = True
    cfg.streaming_enabled = True
    cfg.streaming_fps = 30  # tight loop, completes quickly
    cfg.streaming_jpeg_quality = 50
    cfg.streaming_max_concurrent_viewers = viewer_cap

    tool = BrowserTool(config=cfg, emit_event=runtime.emit_event, runtime=runtime)
    page = _FakePage(max_frames=max_frames)
    session = BrowserSession(session_id="sess-1", agent_id="a1", config=cfg)
    session._page = page  # noqa: SLF001 - test seam matches existing browser tests
    tool._sessions["sess-1"] = session  # noqa: SLF001
    runtime.browser_tool = tool
    return tool, session, page


class _FakeProfileStore:
    """Minimal real ProfileStore stand-in: typed ``get`` over a dict of CrewProfile.

    Replaces ``MagicMock()`` so a production read of any profile-store method
    other than ``get`` surfaces (AttributeError) instead of being auto-faked.
    """

    def __init__(self, profiles: dict[str, CrewProfile]) -> None:
        self.profiles = dict(profiles)

    def get(self, agent_id: str) -> CrewProfile | None:
        return self.profiles.get(agent_id)


class _FakeRegistry:
    """Minimal real AgentRegistry stand-in: typed get/get_by_pool/all over a dict."""

    def __init__(self, agents: dict[str, Any]) -> None:
        self.agents = dict(agents)

    def get(self, agent_id: str) -> Any:
        return self.agents.get(agent_id)

    def get_by_pool(self, pool_name: str) -> list[Any]:
        return [a for a in self.agents.values() if getattr(a, "pool", None) == pool_name]

    def all(self) -> list[Any]:
        return list(self.agents.values())


def _make_runtime(*, crew_scope_token: str = "") -> Any:
    runtime = MagicMock()

    cid = "crew-a"
    ag = MagicMock()
    ag.id = cid
    ag.agent_id = cid
    ag.agent_type = "counselor"
    ag.state = AgentState.ACTIVE
    ag.last_reply_emitted_at = 0.0
    runtime.registry = _FakeRegistry({cid: ag})

    crew = CrewProfile(agent_id=cid, agent_type="counselor")
    crew.appearance = AppearanceProfile(vrm_url="", dsl=None)
    crew.voice = VoiceProfile()
    runtime.profile_store = _FakeProfileStore({cid: crew})

    runtime.trust_network = MagicMock()
    runtime.trust_network.get_history.return_value = []
    runtime.trust_network.get_score.return_value = 0.5
    runtime.bridge_alerts = MagicMock()
    runtime.bridge_alerts.get_recent_alerts.return_value = []

    # AD-706a / BF-287: real Pydantic SystemConfig() so substrate auth code
    # reads real values rather than MagicMock auto-attributes.
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


def test_endpoint_404_on_unknown_session() -> None:
    rt = _make_runtime()
    _seed_browser_tool(rt)
    client = TestClient(_make_app(rt))
    resp = client.get("/api/browser/sessions/does-not-exist/stream")
    assert resp.status_code == 404


def test_endpoint_503_when_viewer_cap_exhausted() -> None:
    rt = _make_runtime()
    tool, _, _ = _seed_browser_tool(rt, viewer_cap=1)
    # Manually pre-fill the cap so the next request gets 503 deterministically.
    tool._active_viewers = 1  # noqa: SLF001
    client = TestClient(_make_app(rt))
    resp = client.get("/api/browser/sessions/sess-1/stream")
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "5"


def test_endpoint_yields_jpeg_frames_at_configured_fps() -> None:
    rt = _make_runtime()
    _seed_browser_tool(rt, max_frames=3)
    client = TestClient(_make_app(rt))
    resp = client.get("/api/browser/sessions/sess-1/stream")
    assert resp.status_code == 200
    assert "multipart/x-mixed-replace" in resp.headers["content-type"]
    body = resp.content
    assert b"image/jpeg" in body
    assert b"\xff\xd8" in body  # JPEG SOI marker


def test_endpoint_emits_open_and_close_events() -> None:
    rt = _make_runtime()
    _seed_browser_tool(rt, max_frames=1)
    client = TestClient(_make_app(rt))
    resp = client.get("/api/browser/sessions/sess-1/stream")
    assert resp.status_code == 200
    event_types = {et for et, _ in rt._emitted_events}
    assert EventType.BROWSER_STREAM_OPENED in event_types
    assert EventType.BROWSER_STREAM_CLOSED in event_types


# ---------------------------------------------------------------------------
# Section 5: require_crew_scope auth surface
# ---------------------------------------------------------------------------


def test_endpoint_requires_crew_scope_token_when_configured() -> None:
    rt = _make_runtime(crew_scope_token="secret")
    _seed_browser_tool(rt)
    client = TestClient(_make_app(rt))
    resp = client.get("/api/browser/sessions/sess-1/stream")
    assert resp.status_code == 401


def test_endpoint_accepts_query_param_token() -> None:
    rt = _make_runtime(crew_scope_token="secret")
    _seed_browser_tool(rt, max_frames=1)
    client = TestClient(_make_app(rt))
    resp = client.get("/api/browser/sessions/sess-1/stream?token=secret")
    assert resp.status_code == 200


def test_require_crew_scope_header_only_callers_unchanged() -> None:
    """Regression: AD-722b-1 header-only callers must still work."""
    rt = _make_runtime(crew_scope_token="secret")
    _seed_browser_tool(rt)
    client = TestClient(_make_app(rt))
    # Hit an existing require_crew_scope-protected endpoint via header only.
    resp = client.get(
        "/api/agent/crew-a/avatar-telemetry",
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code != 401


def test_require_crew_scope_empty_query_token_rejected() -> None:
    """``?token=`` (empty value) MUST 401 - empty string is not a valid token."""
    rt = _make_runtime(crew_scope_token="secret")
    _seed_browser_tool(rt)
    client = TestClient(_make_app(rt))
    resp = client.get("/api/browser/sessions/sess-1/stream?token=")
    assert resp.status_code == 401
