"""AD-1161 — Captain-initiated browser session.

``BrowserTool.open_captain_session`` + ``POST /api/browser/sessions``.

No live network and no real Chromium: the ``_FakePage`` / ``_make_session_factory``
seam from ``tests/test_ad706_browser_tool.py`` is reused verbatim (the AD-1153 /
AD-1154 precedent). Endpoint scaffolding mirrors
``tests/test_ad1052b_browser_bridge.py``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars.events import AvatarEventBus
from probos.avatars.sampling_state import AvatarSamplingStateMachine
from probos.config import BrowserToolConfig, SamplingRatesConfig, SystemConfig
from probos.crew_profile import AppearanceProfile, CrewProfile, VoiceProfile
from probos.events import EventType
from probos.security.audit import AuditLog
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool
from probos.types import AgentState
from tests.test_ad706_browser_tool import _FakePage, _make_session_factory


def _make_tool(
    *,
    config: BrowserToolConfig | None = None,
    page: _FakePage | None = None,
) -> tuple[BrowserTool, _FakePage, AuditLog, list[tuple[Any, Any]]]:
    cfg = config or BrowserToolConfig(enabled=True)
    audit_log = AuditLog()
    events: list[tuple[Any, Any]] = []
    fp = page or _FakePage(title="Example Domain")
    tool = BrowserTool(
        config=cfg, audit_log=audit_log, emit_event=lambda et, d: events.append((et, d)),
    )
    tool._session_factory = _make_session_factory(page=fp)
    return tool, fp, audit_log, events


# ---------------------------------------------------------------------------
# Section 1: BrowserTool.open_captain_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_captain_session_happy_path() -> None:
    cfg = BrowserToolConfig(enabled=True, streaming_enabled=True)
    tool, page, _, events = _make_tool(config=cfg)

    res = await tool.open_captain_session("https://example.test/docs")

    assert res["opened"] is True
    sid = res["session_id"]
    assert sid and sid in tool._sessions
    assert res["streaming_url"] == f"/api/browser/sessions/{sid}/stream"
    assert res["url"] == "https://example.test/docs"
    assert res["page_title"] == "Example Domain"
    # Reused the goto path — the page really navigated.
    assert ("goto", ("https://example.test/docs",), {}) in page.calls
    assert any(et == EventType.BROWSER_SESSION_OPENED for et, _ in events)


@pytest.mark.asyncio
async def test_open_captain_session_attributes_to_captain() -> None:
    """The session is attributable: agent_id distinguishes Captain from agent."""
    tool, _, _, _ = _make_tool()

    res = await tool.open_captain_session("https://example.test")

    assert tool._sessions[res["session_id"]].agent_id == "captain"
    row = tool.list_sessions()[0]
    assert row["agent_id"] == "captain"
    assert row["session_id"] == res["session_id"]


@pytest.mark.asyncio
async def test_open_captain_session_custom_agent_id() -> None:
    tool, _, _, _ = _make_tool()

    res = await tool.open_captain_session("https://example.test", agent_id="crew-a")

    assert res["opened"] is True
    assert tool._sessions[res["session_id"]].agent_id == "crew-a"


@pytest.mark.asyncio
async def test_open_captain_session_disabled_tool_honest_degrade() -> None:
    tool, _, _, _ = _make_tool(config=BrowserToolConfig(enabled=False))

    res = await tool.open_captain_session("https://example.test")

    assert res == {"opened": False, "reason": "Browser tool is disabled."}
    assert tool.session_count == 0


@pytest.mark.asyncio
async def test_open_captain_session_empty_url_honest_degrade() -> None:
    tool, _, _, _ = _make_tool()

    for bad in ("", "   "):
        res = await tool.open_captain_session(bad)
        assert res["opened"] is False
        assert "URL is required" in res["reason"]
    assert tool.session_count == 0


@pytest.mark.asyncio
async def test_open_captain_session_denylisted_domain_refused() -> None:
    cfg = BrowserToolConfig(enabled=True, domain_denylist=["evil.test"])
    tool, page, _, _ = _make_tool(config=cfg)

    res = await tool.open_captain_session("https://evil.test/login")

    assert res["opened"] is False
    assert "denylist" in res["reason"]
    assert "session_id" not in res
    # The domain gate fired BEFORE navigation — the page never moved (the one
    # recorded call is the discard closing the session the gate refused).
    assert [name for name, _, _ in page.calls] == ["close"]


@pytest.mark.asyncio
async def test_open_captain_session_not_in_allowlist_refused() -> None:
    cfg = BrowserToolConfig(enabled=True, domain_allowlist=["intranet.test"])
    tool, _, _, _ = _make_tool(config=cfg)

    res = await tool.open_captain_session("https://elsewhere.test")

    assert res["opened"] is False
    assert "not in allowlist" in res["reason"]


@pytest.mark.asyncio
async def test_open_captain_session_allowlisted_domain_opens() -> None:
    cfg = BrowserToolConfig(enabled=True, domain_allowlist=["intranet.test"])
    tool, _, _, _ = _make_tool(config=cfg)

    res = await tool.open_captain_session("https://intranet.test/home")

    assert res["opened"] is True
    assert tool.session_count == 1


@pytest.mark.asyncio
async def test_open_captain_session_malformed_url_honest_degrade() -> None:
    """A URL the page refuses to load degrades honestly, never raises."""

    class _RefusingPage(_FakePage):
        async def goto(self, url: str) -> None:  # type: ignore[override]
            raise ValueError(f"net::ERR_INVALID_URL at {url}")

    tool, _, _, _ = _make_tool(page=_RefusingPage())

    res = await tool.open_captain_session("http://[not-a-url")

    assert res["opened"] is False
    assert "ERR_INVALID_URL" in res["reason"]


@pytest.mark.asyncio
async def test_rejected_navigation_leaves_no_live_session() -> None:
    """The leak guard: a refused navigation must not strand a live session.

    ``invoke`` creates the session BEFORE the domain gate runs, so the refusal
    path has a live session in hand that nothing else will ever close.
    """
    cfg = BrowserToolConfig(enabled=True, domain_denylist=["evil.test"])
    tool, _, _, events = _make_tool(config=cfg)
    before = tool.list_sessions()

    res = await tool.open_captain_session("https://evil.test/login")

    assert res["opened"] is False
    assert tool.list_sessions() == before == []
    assert tool.session_count == 0
    assert any(
        et == EventType.BROWSER_SESSION_CLOSED and d.get("reason") == "open_failed"
        for et, d in events
    )


@pytest.mark.asyncio
async def test_rejected_navigation_leaves_prior_sessions_untouched() -> None:
    """Discarding the refused session must not disturb sessions already open."""
    cfg = BrowserToolConfig(enabled=True, domain_denylist=["evil.test"])
    tool, _, _, _ = _make_tool(config=cfg)
    ok = await tool.open_captain_session("https://good.test")
    before = tool.list_sessions()

    res = await tool.open_captain_session("https://evil.test")

    assert res["opened"] is False
    assert tool.list_sessions() == before
    assert list(tool._sessions) == [ok["session_id"]]


@pytest.mark.asyncio
async def test_navigation_failure_leaves_no_live_session() -> None:
    """Same leak guard for a page-level failure (session created, goto raised)."""

    class _RefusingPage(_FakePage):
        async def goto(self, url: str) -> None:  # type: ignore[override]
            raise RuntimeError("navigation timeout")

    tool, _, _, _ = _make_tool(page=_RefusingPage())

    res = await tool.open_captain_session("https://slow.test")

    assert res["opened"] is False
    assert tool.session_count == 0
    assert tool.list_sessions() == []


@pytest.mark.asyncio
async def test_session_launch_failure_honest_degrade() -> None:
    """A Chromium that will not launch must not raise through the router.

    ``invoke`` creates the session OUTSIDE its own try block, so a start()
    failure propagates out of it.
    """

    class _UnlaunchableSession(BrowserSession):
        async def start(self) -> None:  # type: ignore[override]
            raise RuntimeError("Executable doesn't exist: chromium")

    tool, _, _, _ = _make_tool()
    tool._session_factory = _UnlaunchableSession

    res = await tool.open_captain_session("https://example.test")

    assert res["opened"] is False
    assert "Could not open a browser" in res["reason"]
    assert tool.session_count == 0


@pytest.mark.asyncio
async def test_open_captain_session_writes_audit_row() -> None:
    """Reusing goto means the AD-706 audit row binds automatically."""
    tool, _, audit_log, _ = _make_tool()

    await tool.open_captain_session("https://example.test/p?token=secret")

    assert audit_log.entries, "audit log should have at least one entry"
    last = audit_log.entries[-1]
    assert last.category == "browser_tool"
    detail = json.loads(last.detail)
    assert detail["action"] == "goto"
    assert detail["agent_id"] == "captain"
    assert detail["success"] is True
    # D5 sanitization still applies to a Captain-opened URL.
    assert detail["url_sanitized"] == "https://example.test/p"
    assert "token=secret" not in last.detail


@pytest.mark.asyncio
async def test_open_captain_session_streaming_disabled_returns_none_url() -> None:
    cfg = BrowserToolConfig(enabled=True, streaming_enabled=False)
    tool, _, _, _ = _make_tool(config=cfg)

    res = await tool.open_captain_session("https://example.test")

    assert res["opened"] is True
    assert res["streaming_url"] is None


@pytest.mark.asyncio
async def test_open_captain_session_no_confirm_parameter() -> None:
    """AD-1161: opening a fresh session is NOT consent-gated (unlike the bridge).

    Guards the docstring's explicit instruction against 'hardening' this by
    analogy to ``connect_bridge_session``.
    """
    import inspect

    sig = inspect.signature(BrowserTool.open_captain_session)
    assert "confirm" not in sig.parameters
    assert sig.parameters["agent_id"].default == "captain"


def test_browser_loop_actions_unchanged() -> None:
    """AD-1161 must not widen the AD-1153 unattended-loop allowlist."""
    from probos.cognitive.agentic_dispatch import _BROWSER_LOOP_ACTIONS

    assert _BROWSER_LOOP_ACTIONS == frozenset(
        {"goto", "state", "extract_text", "back", "forward", "wait"}
    )


# ---------------------------------------------------------------------------
# Endpoint scaffolding (mirrors tests/test_ad1052b_browser_bridge.py).
# ---------------------------------------------------------------------------


class _FakeProfileStore:
    def __init__(self, profiles: dict[str, CrewProfile]) -> None:
        self.profiles = dict(profiles)

    def get(self, agent_id: str) -> CrewProfile | None:
        return self.profiles.get(agent_id)


class _FakeRegistry:
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
    runtime.emit_event = lambda event_type, payload: events.append((event_type, payload))
    return runtime


def _make_app(runtime: Any) -> Any:
    from probos.api import create_app
    return create_app(runtime)


@pytest.fixture(autouse=True)
def _crew_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "probos.routers.agents.is_crew_agent", lambda agent, ontology: True,
    )


def _attach_tool(rt: Any, *, page: _FakePage | None = None) -> BrowserTool:
    cfg = rt.config.browser_tool
    cfg.enabled = True
    cfg.streaming_enabled = True
    tool = BrowserTool(config=cfg, emit_event=rt.emit_event, runtime=rt)
    tool._session_factory = _make_session_factory(page=page or _FakePage(title="T"))
    rt.browser_tool = tool
    return tool


# ---------------------------------------------------------------------------
# Section 2: POST /api/browser/sessions endpoint
# ---------------------------------------------------------------------------


def test_endpoint_opens_session() -> None:
    rt = _make_runtime()
    tool = _attach_tool(rt)
    client = TestClient(_make_app(rt))

    resp = client.post("/api/browser/sessions", json={"url": "https://example.test"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["opened"] is True
    sid = data["session_id"]
    assert sid in tool._sessions
    assert data["streaming_url"] == f"/api/browser/sessions/{sid}/stream"
    assert data["url"] == "https://example.test"
    assert data["page_title"] == "T"


def test_endpoint_tool_disabled_honest_degrade() -> None:
    rt = _make_runtime()
    rt.browser_tool = None
    client = TestClient(_make_app(rt))

    resp = client.post("/api/browser/sessions", json={"url": "https://example.test"})

    assert resp.status_code == 200
    assert resp.json() == {"opened": False, "reason": "Browser tool is disabled."}


def test_endpoint_missing_url_422() -> None:
    rt = _make_runtime()
    _attach_tool(rt)
    client = TestClient(_make_app(rt))

    assert client.post("/api/browser/sessions", json={}).status_code == 422
    assert client.post("/api/browser/sessions", json={"url": 17}).status_code == 422


def test_endpoint_denied_domain_honest_degrade_no_session() -> None:
    rt = _make_runtime()
    tool = _attach_tool(rt)
    tool._config.domain_denylist = ["evil.test"]
    client = TestClient(_make_app(rt))

    resp = client.post("/api/browser/sessions", json={"url": "https://evil.test"})

    assert resp.status_code == 200
    assert resp.json()["opened"] is False
    assert tool.session_count == 0


def test_endpoint_opened_session_appears_in_list() -> None:
    """End-to-end: the Captain opens a session, then the picker can see it."""
    rt = _make_runtime()
    _attach_tool(rt)
    client = TestClient(_make_app(rt))

    opened = client.post(
        "/api/browser/sessions", json={"url": "https://example.test"},
    ).json()
    listed = client.get("/api/browser/sessions").json()

    assert listed["enabled"] is True
    assert [s["session_id"] for s in listed["sessions"]] == [opened["session_id"]]
    assert listed["sessions"][0]["agent_id"] == "captain"


def test_endpoint_auth_token_set_401() -> None:
    rt_auth = _make_runtime(crew_scope_token="secret")
    _attach_tool(rt_auth)
    client = TestClient(_make_app(rt_auth))

    resp = client.post("/api/browser/sessions", json={"url": "https://example.test"})

    assert resp.status_code == 401
