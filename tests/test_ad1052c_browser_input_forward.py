"""AD-1052c — Browser Workstation INPUT-FORWARDING tests (the human DRIVES).

BF-287 real fixtures: real ``BrowserToolConfig`` / ``BrowserSession`` /
``BrowserTool`` and a real ``SystemConfig()`` at the auth boundary (NOT a
MagicMock config). NO real browser — a ``_FakePage`` with ``mouse`` / ``keyboard``
recorder objects and a settable ``viewport_size`` is assigned to the session,
and ``tool._sessions[sid] = session`` is seeded directly (the AD-706 seam).

Endpoint scaffolding mirrors ``tests/test_ad1052b_browser_bridge.py``.
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
# Fakes — a Playwright Page with mouse/keyboard recorders + a viewport_size
# property (NO real Chrome).
# ---------------------------------------------------------------------------


class _FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int, str]] = []
        self.moves: list[tuple[int, int]] = []
        self.wheels: list[tuple[float, float]] = []

    async def click(self, x: int, y: int, button: str = "left") -> None:
        self.clicks.append((x, y, button))

    async def move(self, x: int, y: int) -> None:
        self.moves.append((x, y))

    async def wheel(self, dx: float, dy: float) -> None:
        self.wheels.append((dx, dy))


class _FakeKeyboard:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.pressed: list[str] = []

    async def type(self, text: str) -> None:
        self.typed.append(text)

    async def press(self, key: str) -> None:
        self.pressed.append(key)


class _FakePage:
    def __init__(self, viewport_size: dict[str, int] | None) -> None:
        self.mouse = _FakeMouse()
        self.keyboard = _FakeKeyboard()
        # Playwright Page.viewport_size is a PROPERTY (dict|None), not a coroutine.
        self.viewport_size = viewport_size


def _session_with_page(
    *, viewport_size: dict[str, int] | None, config: BrowserToolConfig | None = None,
) -> tuple[BrowserSession, _FakePage]:
    cfg = config or BrowserToolConfig(enabled=True)
    sess = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    page = _FakePage(viewport_size)
    sess._page = page  # test seam: no real browser, no public setter
    return sess, page


# ---------------------------------------------------------------------------
# Section 1: BrowserSession.forward_input — coordinate map + reuse primitives
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_click_maps_normalized_to_viewport_pixels() -> None:
    sess, page = _session_with_page(viewport_size={"width": 1280, "height": 720})
    result = await sess.forward_input({"kind": "click", "nx": 0.5, "ny": 0.5})
    assert page.mouse.clicks == [(640, 360, "left")]
    assert result["forwarded"] is True
    assert result["x"] == 640 and result["y"] == 360


@pytest.mark.asyncio
async def test_forward_click_viewport_none_uses_config_fallback() -> None:
    cfg = BrowserToolConfig(enabled=True, viewport_width=1000, viewport_height=500)
    sess, page = _session_with_page(viewport_size=None, config=cfg)
    await sess.forward_input({"kind": "click", "nx": 0.5, "ny": 0.5})
    assert page.mouse.clicks == [(500, 250, "left")]


@pytest.mark.asyncio
async def test_forward_click_clamps_out_of_range_coords() -> None:
    sess, page = _session_with_page(viewport_size={"width": 1280, "height": 720})
    await sess.forward_input({"kind": "click", "nx": 1.5, "ny": -0.2})
    assert page.mouse.clicks == [(1280, 0, "left")]


@pytest.mark.asyncio
async def test_forward_scroll_moves_then_wheels() -> None:
    sess, page = _session_with_page(viewport_size={"width": 1280, "height": 720})
    result = await sess.forward_input({"kind": "scroll", "nx": 0.5, "ny": 0.5, "dy": 120})
    assert page.mouse.moves == [(640, 360)]
    assert page.mouse.wheels == [(0.0, 120.0)]
    assert result["forwarded"] is True


@pytest.mark.asyncio
async def test_forward_type_caps_text_at_4096() -> None:
    sess, page = _session_with_page(viewport_size={"width": 1280, "height": 720})
    result = await sess.forward_input({"kind": "type", "text": "x" * 5000})
    assert len(page.keyboard.typed) == 1
    assert len(page.keyboard.typed[0]) == 4096
    assert result["len"] == 4096


@pytest.mark.asyncio
async def test_forward_key_allowlisted_presses() -> None:
    sess, page = _session_with_page(viewport_size={"width": 1280, "height": 720})
    result = await sess.forward_input({"kind": "key", "key": "Enter"})
    assert page.keyboard.pressed == ["Enter"]
    assert result["forwarded"] is True and result["key"] == "Enter"


@pytest.mark.asyncio
async def test_forward_key_not_allowlisted_rejected() -> None:
    sess, page = _session_with_page(viewport_size={"width": 1280, "height": 720})
    result = await sess.forward_input({"kind": "key", "key": "Control+w"})
    assert result == {"forwarded": False, "reason": "key_not_allowed"}
    assert page.keyboard.pressed == []


@pytest.mark.asyncio
async def test_forward_no_page_honest_degrades() -> None:
    cfg = BrowserToolConfig(enabled=True)
    sess = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    # _page is None by default — no real browser started.
    result = await sess.forward_input({"kind": "click", "nx": 0.5, "ny": 0.5})
    assert result == {"forwarded": False, "reason": "no_page"}


@pytest.mark.asyncio
async def test_forward_unknown_kind_honest_degrades() -> None:
    sess, page = _session_with_page(viewport_size={"width": 1280, "height": 720})
    result = await sess.forward_input({"kind": "paste"})
    assert result == {"forwarded": False, "reason": "unknown_kind"}
    assert page.mouse.clicks == [] and page.keyboard.typed == []


# ---------------------------------------------------------------------------
# Section 2: BrowserTool.forward_input — gate + audit + per-episode latch
# ---------------------------------------------------------------------------


def _tool_with_session(
    *, enabled: bool, viewport_size: dict[str, int] | None = None,
) -> tuple[BrowserTool, str, _FakePage, list[tuple[Any, dict]]]:
    cfg = BrowserToolConfig(enabled=True, input_forwarding_enabled=enabled)
    events: list[tuple[Any, dict]] = []
    tool = BrowserTool(config=cfg, emit_event=lambda et, d: events.append((et, d)))
    sid = "sess-1"
    sess = BrowserSession(session_id=sid, agent_id="a1", config=cfg)
    page = _FakePage(viewport_size or {"width": 1280, "height": 720})
    sess._page = page  # test seam
    tool._sessions[sid] = sess
    return tool, sid, page, events


@pytest.mark.asyncio
async def test_tool_gate_off_refuses_and_never_touches_page() -> None:
    tool, sid, page, events = _tool_with_session(enabled=False)
    result = await tool.forward_input(
        sid, {"kind": "click", "nx": 0.5, "ny": 0.5}, agent_id="captain",
    )
    assert result == {"forwarded": False, "reason": "Input forwarding is disabled."}
    assert page.mouse.clicks == [] and page.keyboard.typed == []
    refused = [e for e in events if e[0] is EventType.BROWSER_INPUT_REFUSED]
    assert len(refused) == 1 and refused[0][1]["reason"] == "disabled"


@pytest.mark.asyncio
async def test_tool_session_not_found_refuses() -> None:
    tool, _sid, _page, events = _tool_with_session(enabled=True)
    result = await tool.forward_input(
        "nope", {"kind": "click", "nx": 0.5, "ny": 0.5}, agent_id="captain",
    )
    assert result["forwarded"] is False
    refused = [e for e in events if e[0] is EventType.BROWSER_INPUT_REFUSED]
    assert refused and refused[-1][1]["reason"] == "session_not_found"


@pytest.mark.asyncio
async def test_tool_forwarded_emitted_once_per_episode() -> None:
    tool, sid, _page, events = _tool_with_session(enabled=True)
    await tool.forward_input(sid, {"kind": "click", "nx": 0.5, "ny": 0.5}, agent_id="captain")
    await tool.forward_input(sid, {"kind": "click", "nx": 0.1, "ny": 0.1}, agent_id="captain")
    forwarded = [e for e in events if e[0] is EventType.BROWSER_INPUT_FORWARDED]
    refused = [e for e in events if e[0] is EventType.BROWSER_INPUT_REFUSED]
    assert len(forwarded) == 1
    assert len(refused) == 0


def test_input_forwarding_enabled_property_reflects_config() -> None:
    off = BrowserTool(config=BrowserToolConfig(enabled=True))
    assert off.input_forwarding_enabled is False
    on = BrowserTool(config=BrowserToolConfig(enabled=True, input_forwarding_enabled=True))
    assert on.input_forwarding_enabled is True


# ---------------------------------------------------------------------------
# Endpoint scaffolding (copied from test_ad1052b_browser_bridge.py).
# ---------------------------------------------------------------------------


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
# Section 3: POST /api/browser/sessions/{id}/input + GET /sessions flag
# ---------------------------------------------------------------------------


def test_endpoint_tool_disabled_honest_degrade() -> None:
    rt = _make_runtime()
    rt.browser_tool = None
    client = TestClient(_make_app(rt))
    resp = client.post(
        "/api/browser/sessions/x/input",
        json={"kind": "click", "nx": 0.5, "ny": 0.5},
    )
    assert resp.status_code == 200
    assert resp.json() == {"forwarded": False, "reason": "Browser tool is disabled."}


def test_endpoint_forwards_click() -> None:
    rt = _make_runtime()
    cfg = rt.config.browser_tool
    cfg.enabled = True
    cfg.input_forwarding_enabled = True
    tool = BrowserTool(config=cfg, emit_event=rt.emit_event, runtime=rt)
    sid = "sess-ep"
    sess = BrowserSession(session_id=sid, agent_id="captain", config=cfg)
    sess._page = _FakePage({"width": 1280, "height": 720})  # test seam
    tool._sessions[sid] = sess
    rt.browser_tool = tool

    client = TestClient(_make_app(rt))
    resp = client.post(
        f"/api/browser/sessions/{sid}/input",
        json={"kind": "click", "nx": 0.5, "ny": 0.5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["forwarded"] is True
    assert data["x"] == 640 and data["y"] == 360


def test_get_sessions_surfaces_input_forwarding_flag() -> None:
    rt_off = _make_runtime()
    rt_off.browser_tool = None
    client_off = TestClient(_make_app(rt_off))
    resp_off = client_off.get("/api/browser/sessions")
    assert resp_off.status_code == 200
    assert resp_off.json()["input_forwarding_enabled"] is False

    rt_on = _make_runtime()
    cfg = rt_on.config.browser_tool
    cfg.enabled = True
    cfg.input_forwarding_enabled = True
    rt_on.browser_tool = BrowserTool(config=cfg, emit_event=rt_on.emit_event, runtime=rt_on)
    client_on = TestClient(_make_app(rt_on))
    resp_on = client_on.get("/api/browser/sessions")
    assert resp_on.status_code == 200
    assert resp_on.json()["input_forwarding_enabled"] is True


def test_endpoint_auth_token_set_401() -> None:
    rt_auth = _make_runtime(crew_scope_token="secret")
    cfg = rt_auth.config.browser_tool
    cfg.enabled = True
    cfg.input_forwarding_enabled = True
    rt_auth.browser_tool = BrowserTool(config=cfg, emit_event=rt_auth.emit_event, runtime=rt_auth)
    client = TestClient(_make_app(rt_auth))
    resp = client.post(
        "/api/browser/sessions/x/input",
        json={"kind": "click", "nx": 0.5, "ny": 0.5},
    )
    assert resp.status_code == 401
