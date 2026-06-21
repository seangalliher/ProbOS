"""AD-1052b — Browser Workstation BRIDGE mode tests.

BF-287 real fixtures: real ``BrowserToolConfig`` / ``BrowserSession`` /
``BrowserTool`` and a real ``SystemConfig()`` at the auth boundary (NOT a
MagicMock config). NO real Chrome — the session ``connect()`` path is exercised
by monkeypatching ``playwright.async_api.async_playwright``; the tool path
injects a ``_FakeSession`` via ``tool._session_factory`` (the AD-706 seam).

Endpoint scaffolding mirrors ``tests/test_ad1052a_browser_sessions.py``.
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
from probos.events import EventType
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool
from probos.types import AgentState


# ---------------------------------------------------------------------------
# Fakes for BrowserSession.connect() — monkeypatched async_playwright (no Chrome)
# ---------------------------------------------------------------------------


class _FakeCdpPage:
    def __init__(self) -> None:
        self.default_timeout_set: int | None = None

    def set_default_timeout(self, ms: int) -> None:
        self.default_timeout_set = ms


class _FakeCdpContext:
    def __init__(self, pages: list[_FakeCdpPage]) -> None:
        self.pages = pages
        self.new_page_called = False

    async def new_page(self) -> _FakeCdpPage:
        self.new_page_called = True
        return _FakeCdpPage()


class _FakeCdpBrowser:
    def __init__(self, contexts: list[_FakeCdpContext]) -> None:
        self.contexts = contexts
        self.new_context_called = False

    async def new_context(self) -> _FakeCdpContext:
        self.new_context_called = True
        return _FakeCdpContext([])


class _FakeChromium:
    def __init__(self, browser: _FakeCdpBrowser) -> None:
        self._browser = browser

    async def connect_over_cdp(self, endpoint: str) -> _FakeCdpBrowser:
        return self._browser


class _FakePlaywrightObj:
    def __init__(self, browser: _FakeCdpBrowser) -> None:
        self.chromium = _FakeChromium(browser)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class _FakePlaywrightCM:
    def __init__(self, browser: _FakeCdpBrowser) -> None:
        self._browser = browser

    async def start(self) -> _FakePlaywrightObj:
        return _FakePlaywrightObj(self._browser)


# ---------------------------------------------------------------------------
# Section 1: BrowserSession.connect() + disconnect-not-close stop()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_connect_attaches_existing_context_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakeCdpPage()
    ctx = _FakeCdpContext([page])
    browser = _FakeCdpBrowser([ctx])

    def _fake_async_playwright() -> _FakePlaywrightCM:
        return _FakePlaywrightCM(browser)

    monkeypatch.setattr(
        "playwright.async_api.async_playwright", _fake_async_playwright
    )

    cfg = BrowserToolConfig(enabled=True, bridge_enabled=True)
    sess = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    await sess.connect("http://127.0.0.1:9222")

    assert sess.page is page
    assert sess.is_connected is True
    # The user's REAL context/page are reused — never a fresh cookie-less one.
    assert browser.new_context_called is False
    assert ctx.new_page_called is False
    assert page.default_timeout_set == cfg.default_timeout_ms


@pytest.mark.asyncio
async def test_session_stop_connected_disconnects_not_closes() -> None:
    cfg = BrowserToolConfig(enabled=True, bridge_enabled=True)
    events: list[tuple[Any, dict]] = []
    sess = BrowserSession(
        session_id="s1", agent_id="a1", config=cfg,
        emit_event=lambda et, d: events.append((et, d)),
    )
    sess._connected = True
    browser = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    playwright = AsyncMock()
    sess._browser = browser
    sess._context = context
    sess._page = page
    sess._playwright = playwright

    await sess.stop()

    # Disconnect (browser.close) + playwright.stop, but NEVER the user's tabs.
    browser.close.assert_awaited_once()
    page.close.assert_not_called()
    context.close.assert_not_called()
    playwright.stop.assert_awaited_once()
    assert sess.is_connected is False
    assert sess._browser is None
    assert sess._context is None
    assert sess._page is None
    assert sess._playwright is None
    assert any(et == EventType.BROWSER_BRIDGE_DISCONNECTED for et, _ in events)


@pytest.mark.asyncio
async def test_session_stop_launched_unchanged() -> None:
    # DD-5 regression guard: a LAUNCHED session still closes page+context+browser.
    cfg = BrowserToolConfig(enabled=True)
    sess = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    assert sess.is_connected is False
    browser = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    playwright = AsyncMock()
    sess._browser = browser
    sess._context = context
    sess._page = page
    sess._playwright = playwright

    await sess.stop()

    page.close.assert_awaited_once()
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# Section 3: BrowserTool — consent + allowlist + connect (no playwright)
# ---------------------------------------------------------------------------


def _bridge_factory(*, raise_on_connect: bool = False) -> Any:
    class _FakeBridgeSession(BrowserSession):
        async def connect(self, endpoint: str) -> None:  # type: ignore[override]
            if raise_on_connect:
                raise ConnectionError("unreachable")
            self._connected = True
            self.set_last_url(endpoint)

    return _FakeBridgeSession


def _make_bridge_tool(
    *, config: BrowserToolConfig, raise_on_connect: bool = False,
) -> tuple[BrowserTool, list[tuple[Any, dict]]]:
    events: list[tuple[Any, dict]] = []
    tool = BrowserTool(config=config, emit_event=lambda et, d: events.append((et, d)))
    tool._session_factory = _bridge_factory(raise_on_connect=raise_on_connect)
    return tool, events


@pytest.mark.asyncio
async def test_connect_bridge_disabled_refused() -> None:
    cfg = BrowserToolConfig(enabled=True, bridge_enabled=False)
    tool, events = _make_bridge_tool(config=cfg)
    res = await tool.connect_bridge_session(
        "http://127.0.0.1:9222", agent_id="captain", confirm=True,
    )
    assert res["connected"] is False
    assert "Bridge mode is disabled" in res["reason"]
    assert tool.session_count == 0
    assert any(et == EventType.BROWSER_BRIDGE_REFUSED for et, _ in events)


@pytest.mark.asyncio
async def test_connect_requires_confirm() -> None:
    cfg = BrowserToolConfig(enabled=True, bridge_enabled=True)
    tool, events = _make_bridge_tool(config=cfg)
    res = await tool.connect_bridge_session(
        "http://127.0.0.1:9222", agent_id="captain", confirm=False,
    )
    assert res["connected"] is False
    assert "consent" in res["reason"].lower()
    assert tool.session_count == 0
    assert any(
        et == EventType.BROWSER_BRIDGE_REFUSED and d.get("reason") == "consent"
        for et, d in events
    )


@pytest.mark.asyncio
async def test_connect_endpoint_not_allowed_refused() -> None:
    cfg = BrowserToolConfig(enabled=True, bridge_enabled=True)
    tool, events = _make_bridge_tool(config=cfg)
    res = await tool.connect_bridge_session(
        "http://evil.example.com:9222", agent_id="captain", confirm=True,
    )
    assert res["connected"] is False
    assert "not allowed" in res["reason"].lower()
    assert tool.session_count == 0
    assert any(
        et == EventType.BROWSER_BRIDGE_REFUSED and d.get("reason") == "endpoint_not_allowed"
        for et, d in events
    )


@pytest.mark.asyncio
async def test_connect_localhost_happy_path() -> None:
    cfg = BrowserToolConfig(enabled=True, bridge_enabled=True, streaming_enabled=True)
    tool, events = _make_bridge_tool(config=cfg)
    res = await tool.connect_bridge_session(
        "http://127.0.0.1:9222", agent_id="captain", confirm=True,
    )
    assert res["connected"] is True
    sid = res["session_id"]
    assert sid in tool._sessions
    assert res["streaming_url"] == f"/api/browser/sessions/{sid}/stream"
    assert any(
        et == EventType.BROWSER_BRIDGE_CONNECTED and d.get("host") == "127.0.0.1"
        for et, d in events
    )


@pytest.mark.asyncio
async def test_connect_unreachable_refused() -> None:
    cfg = BrowserToolConfig(enabled=True, bridge_enabled=True)
    tool, events = _make_bridge_tool(config=cfg, raise_on_connect=True)
    res = await tool.connect_bridge_session(
        "http://127.0.0.1:9222", agent_id="captain", confirm=True,
    )
    assert res["connected"] is False
    assert "Could not connect" in res["reason"]
    assert tool.session_count == 0
    assert any(
        et == EventType.BROWSER_BRIDGE_REFUSED and d.get("reason") == "unreachable"
        for et, d in events
    )


def test_validate_cdp_endpoint_allowlist() -> None:
    cfg = BrowserToolConfig(enabled=True, bridge_enabled=True)
    tool = BrowserTool(config=cfg)
    # Localhost family allowed (incl. the IPv6 loopback the default advertises).
    assert tool._validate_cdp_endpoint("http://127.0.0.1:9222") == "127.0.0.1"
    assert tool._validate_cdp_endpoint("http://localhost:9222") == "localhost"
    assert tool._validate_cdp_endpoint("http://[::1]:9222") == "::1"
    assert tool._validate_cdp_endpoint("ws://localhost:9222") == "localhost"
    # SSRF guards: remote host + the .evil.com host-suffix bypass + bad scheme.
    assert tool._validate_cdp_endpoint("http://evil.com:9222") == ""
    assert tool._validate_cdp_endpoint("http://127.0.0.1.evil.com:9222") == ""
    assert tool._validate_cdp_endpoint("file:///x") == ""
    assert tool._validate_cdp_endpoint("") == ""


def test_validate_cdp_endpoint_custom_allowlist() -> None:
    cfg = BrowserToolConfig(
        enabled=True, bridge_enabled=True, bridge_allowed_hosts=["10.0.0.5"],
    )
    tool = BrowserTool(config=cfg)
    assert tool._validate_cdp_endpoint("http://10.0.0.5:9222") == "10.0.0.5"
    # The default localhost is no longer allowed under a custom allowlist.
    assert tool._validate_cdp_endpoint("http://127.0.0.1:9222") == ""


# ---------------------------------------------------------------------------
# Endpoint scaffolding (copied from test_ad1052a_browser_sessions.py).
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


def _make_app(runtime: Any) -> Any:
    from probos.api import create_app
    return create_app(runtime)


@pytest.fixture(autouse=True)
def _crew_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "probos.routers.agents.is_crew_agent", lambda agent, ontology: True,
    )


# ---------------------------------------------------------------------------
# Section 4: POST /api/browser/bridge/connect endpoint
# ---------------------------------------------------------------------------


def test_endpoint_tool_disabled_honest_degrade() -> None:
    rt = _make_runtime()
    rt.browser_tool = None
    client = TestClient(_make_app(rt))
    resp = client.post(
        "/api/browser/bridge/connect",
        json={"endpoint": "http://127.0.0.1:9222", "confirm": True},
    )
    assert resp.status_code == 200
    assert resp.json() == {"connected": False, "reason": "Browser tool is disabled."}


def test_endpoint_connects() -> None:
    rt = _make_runtime()
    cfg = rt.config.browser_tool
    cfg.enabled = True
    cfg.bridge_enabled = True
    cfg.streaming_enabled = True
    tool = BrowserTool(config=cfg, emit_event=rt.emit_event, runtime=rt)
    tool._session_factory = _bridge_factory()
    rt.browser_tool = tool

    client = TestClient(_make_app(rt))
    resp = client.post(
        "/api/browser/bridge/connect",
        json={"endpoint": "http://127.0.0.1:9222", "confirm": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    sid = data["session_id"]
    assert sid in tool._sessions
    assert data["streaming_url"] == f"/api/browser/sessions/{sid}/stream"


def test_endpoint_auth_token_set_401() -> None:
    rt_auth = _make_runtime(crew_scope_token="secret")
    cfg = rt_auth.config.browser_tool
    cfg.enabled = True
    cfg.bridge_enabled = True
    tool = BrowserTool(config=cfg, emit_event=rt_auth.emit_event, runtime=rt_auth)
    tool._session_factory = _bridge_factory()
    rt_auth.browser_tool = tool

    client = TestClient(_make_app(rt_auth))
    resp = client.post(
        "/api/browser/bridge/connect",
        json={"endpoint": "http://127.0.0.1:9222", "confirm": True},
    )
    assert resp.status_code == 401
