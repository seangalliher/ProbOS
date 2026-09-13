"""AD-706a (Wave 166) - Captain-watch MJPEG streaming bridge tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient

from probos.avatars.events import AvatarEventBus
from probos.avatars.sampling_state import AvatarSamplingStateMachine
from probos.config import BrowserToolConfig, SamplingRatesConfig, SystemConfig
from probos.crew_profile import AppearanceProfile, CrewProfile, VoiceProfile
from probos.events import EventType
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool
from probos.types import AgentState
from tests.test_browser_session_lifecycle import (
    _bridge, browser_app, lifecycle_tool, wired_browser_runtime,
)


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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["end", "handoff"])
@pytest.mark.parametrize("wired_browser_runtime", ["secret", ""], indirect=True)
async def test_lifecycle_endpoint_confirmed_operator_succeeds(
    wired_browser_runtime: Any, operation: str,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    tool = runtime.browser_tool
    selected = await _bridge(tool)
    other = await _bridge(tool)
    async with AsyncClient(transport=ASGITransport(app=browser_app(runtime)), base_url="http://test") as client:
        listed = await client.get("/api/browser/sessions", headers={"Authorization": "Bearer secret"})
        assert listed.status_code == 200
        basis = "shared_crew_scope" if runtime.config.auth.crew_scope_token else "single_operator_compatibility"
        assert listed.json()["authority_basis"] == basis
        row = next(row for row in listed.json()["sessions"] if row["session_id"] == selected)
        assert row["owner_id"] == "captain"
        assert row["pending_work"] == 0
        assert row["expires_at"] == tool.get_session(selected).expires_at
        assert row["sharing_scope"] == "legacy_ambient_binding"
        response = await client.post(
            f"/api/browser/sessions/{selected}/{operation}", json={"confirm": True},
            headers={"Authorization": "Bearer secret"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["outcome"] == "completed"
        assert response.json()["session"]["session_id"] == selected
        assert other not in response.text
        assert "secret" not in response.text
        assert "recording_path" not in response.text
        assert tool.get_session(other) is not None
        assert drivers[1].stop_count == 0
        if operation == "handoff":
            assert tool.captain_session_id == selected
            assert response.json()["session"]["sharing_scope"] == "explicit_crew_binding"
            assert drivers[0].stop_count == 0
        else:
            assert tool.get_session(selected) is None
            assert drivers[0].stop_count == 1
            repeat = await client.post(
                f"/api/browser/sessions/{selected}/end", json={"confirm": True},
                headers={"Authorization": "Bearer secret"},
            )
            assert repeat.json() == response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["end", "handoff"])
@pytest.mark.parametrize("body", [
    {}, {"confirm": False}, {"confirm": 1}, {"confirm": "true"}, {"confirm": None},
    {"confirm": True, "actor": "captain"}, {"confirm": True, "owner_id": "captain"},
    {"confirm": True, "authority_basis": "shared_crew_scope"},
])
async def test_lifecycle_endpoint_rejects_malformed_and_forged_bodies(
    wired_browser_runtime: Any, operation: str, body: dict[str, Any],
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    selected = await _bridge(runtime.browser_tool)
    async with AsyncClient(transport=ASGITransport(app=browser_app(runtime)), base_url="http://test") as client:
        response = await client.post(
            f"/api/browser/sessions/{selected}/{operation}", json=body,
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == 422
    assert runtime.browser_tool.get_session(selected) is not None
    assert drivers[0].stop_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["end", "handoff"])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
async def test_lifecycle_endpoint_rejects_unauthenticated_operator(
    wired_browser_runtime: Any, operation: str, headers: dict[str, str],
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    selected = await _bridge(runtime.browser_tool)
    async with AsyncClient(transport=ASGITransport(app=browser_app(runtime)), base_url="http://test") as client:
        response = await client.post(
            f"/api/browser/sessions/{selected}/{operation}", json={"confirm": True}, headers=headers,
        )
    assert response.status_code == 401
    assert drivers[0].stop_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["end", "handoff"])
@pytest.mark.parametrize("identity,status", [("unknown", 404), ("bad.id", 422), ("x" * 129, 422)])
async def test_lifecycle_endpoint_validates_identity(
    wired_browser_runtime: Any, operation: str, identity: str, status: int,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    async with AsyncClient(transport=ASGITransport(app=browser_app(runtime)), base_url="http://test") as client:
        response = await client.post(
            f"/api/browser/sessions/{identity}/{operation}", json={"confirm": True},
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == status
    assert drivers == []


@pytest.mark.asyncio
async def test_lifecycle_endpoint_owner_policy_and_cleanup_failure_are_not_success(
    wired_browser_runtime: Any,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    unknown = await _bridge(runtime.browser_tool, "unregistered")
    crew = await _bridge(runtime.browser_tool, "crew-one")
    captain = await _bridge(runtime.browser_tool)
    async with AsyncClient(
        transport=ASGITransport(app=browser_app(runtime)), base_url="http://test",
        headers={"Authorization": "Bearer secret"},
    ) as client:
        response = await client.post(f"/api/browser/sessions/{unknown}/end", json={"confirm": True})
        assert response.status_code == 409
        assert response.json()["reason"] == "unknown_ownership"
        response = await client.post(f"/api/browser/sessions/{crew}/handoff", json={"confirm": True})
        assert response.status_code == 403
        assert (await client.post(f"/api/browser/sessions/{crew}/end", json={"confirm": True})).status_code == 200
        drivers[2].chromium.browser.fail_close = True
        try:
            response = await client.post(f"/api/browser/sessions/{captain}/end", json={"confirm": True})
            assert response.status_code == 409
            assert response.json()["outcome"] == "failed"
            assert response.json()["reason"] == "cleanup_failed"
        finally:
            drivers[2].chromium.browser.fail_close = False
        assert (await client.post(f"/api/browser/sessions/{captain}/end", json={"confirm": True})).status_code == 200
    assert drivers[0].stop_count == 0


class _ASGIViewer:
    def __init__(self, app: Any, session_id: str) -> None:
        self.app = app
        self.session_id = session_id
        self.frame_seen = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.frames = 0
        self.status: int | None = None

    async def run(self) -> None:
        async def receive() -> dict[str, Any]:
            await self.disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.status = message["status"]
            if message["type"] == "http.response.body" and b"jpeg-frame" in message.get("body", b""):
                self.frames += 1
                self.frame_seen.set()

        await self.app({
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": f"/api/browser/sessions/{self.session_id}/stream", "query_string": b"",
            "headers": [(b"authorization", b"Bearer secret")],
            "client": ("127.0.0.1", 1234), "server": ("test", 80), "root_path": "",
        }, receive, send)


@pytest.mark.asyncio
async def test_router_end_drains_admitted_input_and_both_streams_only(
    wired_browser_runtime: Any, tmp_path: Path,
) -> None:
    runtime, drivers, events = wired_browser_runtime
    tool = runtime.browser_tool
    selected = await _bridge(tool)
    runtime.config.browser_tool.recording_enabled = True
    runtime.config.browser_tool.recording_dir = str(tmp_path)
    opened = await tool.open_captain_session("https://other.example/")
    assert opened["opened"] is True
    other = tool.get_session(opened["session_id"])
    assert other.recording_state == "recording"
    app = browser_app(runtime)
    viewers = [_ASGIViewer(app, selected), _ASGIViewer(app, selected)]
    tasks = [asyncio.create_task(viewer.run()) for viewer in viewers]
    keyboard = drivers[0].chromium.browser.contexts[0].pages[0].keyboard
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": "Bearer secret"},
    ) as client:
        try:
            for viewer in viewers:
                await asyncio.wait_for(viewer.frame_seen.wait(), 2)
                assert viewer.frames >= 1 and viewer.status == 200
            assert tool.active_viewers == 2
            entering = asyncio.create_task(client.post(
                f"/api/browser/sessions/{selected}/input", json={"kind": "type", "text": "admitted"},
            ))
            tasks.append(entering)
            await asyncio.wait_for(keyboard.entered.wait(), 2)
            ending = asyncio.create_task(client.post(
                f"/api/browser/sessions/{selected}/end", json={"confirm": True},
            ))
            tasks.append(ending)

            async def wait_for_ending() -> None:
                while tool.session_snapshot(selected).state != "ending":
                    await asyncio.sleep(0)

            await asyncio.wait_for(wait_for_ending(), 2)
            assert not ending.done()
            late = await client.post(
                f"/api/browser/sessions/{selected}/input", json={"kind": "type", "text": "late"},
            )
            assert late.json()["forwarded"] is False
            keyboard.release.set()
            assert (await entering).json()["forwarded"] is True
            assert (await ending).status_code == 200
            await asyncio.wait_for(asyncio.gather(*tasks[:2]), 2)
            assert tool.active_viewers == 0
            assert keyboard.typed == ["admitted"]
            assert (await client.post(f"/api/browser/sessions/{selected}/end", json={"confirm": True})).status_code == 200
            assert (await client.get(f"/api/browser/sessions/{selected}/stream")).status_code == 409
            assert sum(kind == EventType.BROWSER_STREAM_CLOSED and payload["session_id"] == selected for kind, payload in events) == 2
            assert sum(kind == EventType.BROWSER_SESSION_CLOSED and payload["session_id"] == selected for kind, payload in events) == 1
            assert other.recording_state == "recording"
            assert drivers[1].chromium.browser.contexts[0].close_count == 0
            drivers[1].chromium.browser.contexts[0].pages[0].keyboard.release.set()
            forwarded = await client.post(
                f"/api/browser/sessions/{other.session_id}/input", json={"kind": "type", "text": "other still usable"},
            )
            assert forwarded.json()["forwarded"] is True
        finally:
            keyboard.release.set()
            for viewer in viewers:
                viewer.disconnected.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_stream_response_cancellation_before_frames_releases_admission(
    wired_browser_runtime: Any,
) -> None:
    from probos.routers.browser_stream import stream_browser_session

    runtime, drivers, events = wired_browser_runtime
    selected = await _bridge(runtime.browser_tool)
    response = await stream_browser_session(selected, runtime)
    assert runtime.browser_tool.active_viewers == 1

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        assert message["type"] == "http.response.start"
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert runtime.browser_tool.active_viewers == 0
    assert drivers[0].chromium.browser.contexts[0].pages[0].frames == 0
    assert drivers[0].stop_count == 0
    assert sum(kind == EventType.BROWSER_STREAM_CLOSED for kind, _ in events) == 1
