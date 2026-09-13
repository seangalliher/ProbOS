"""Selected-session lifecycle regressions with real browser owners."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import asdict
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from probos.capability_request import CapabilityRequest, CapabilityRequestStore
from probos.config import SystemConfig
from probos.events import EventType
from probos.tools.browser.lifecycle import (
    BrowserActor, BrowserAuthorityBasis, BrowserLifecycleConflict,
    BrowserLifecycleState,
)
from probos.tools.browser.loop_host import PlaywrightLoopHost
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool
from probos.tools.protocol import ToolResult


class _FakeKeyboard:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.typed: list[str] = []

    async def type(self, text: str) -> None:
        self.entered.set()
        await self.release.wait()
        self.typed.append(text)


class _FakePage:
    def __init__(self) -> None:
        self.keyboard = _FakeKeyboard()
        self.default_timeout: int | None = None
        self.close_count = 0
        self.frames = 0
        self.fail_screenshot = False
        self.url = ""

    async def goto(self, url: str) -> None:
        self.url = url

    async def title(self) -> str:
        return "Local test page"

    async def inner_text(self, selector: str) -> str:
        return "Selected local page"

    async def screenshot(self, **kwargs: Any) -> bytes:
        self.frames += 1
        if self.fail_screenshot:
            raise RuntimeError("screenshot failed")
        return b"jpeg-frame"

    def set_default_timeout(self, timeout: int) -> None:
        self.default_timeout = timeout

    async def close(self) -> None:
        self.close_count += 1


class _FakeContext:
    def __init__(self) -> None:
        self.pages = [_FakePage()]
        self.close_count = 0
        self.fail_close = False

    async def new_page(self) -> _FakePage:
        return self.pages[0]

    async def route(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def close(self) -> None:
        self.close_count += 1
        if self.fail_close:
            raise RuntimeError("context finalization failed")


class _FakeBrowser:
    def __init__(self) -> None:
        self.contexts = [_FakeContext()]
        self.disconnect_count = 0
        self.fail_close = False

    async def new_context(self, **kwargs: Any) -> _FakeContext:
        return self.contexts[0]

    async def close(self) -> None:
        self.disconnect_count += 1
        if self.fail_close:
            raise RuntimeError("disconnect failed")


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser
        self.endpoints: list[str] = []

    async def launch(self, **kwargs: Any) -> _FakeBrowser:
        return self.browser

    async def connect_over_cdp(self, endpoint: str) -> _FakeBrowser:
        self.endpoints.append(endpoint)
        return self.browser


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = _FakeChromium(_FakeBrowser())
        self.stop_count = 0

    async def start(self) -> _FakePlaywright:
        return self

    async def stop(self) -> None:
        self.stop_count += 1


@pytest.mark.asyncio
async def test_end_session_without_actor_or_confirmation_preserves_both_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drivers: list[_FakePlaywright] = []

    def fake_async_playwright() -> _FakePlaywright:
        driver = _FakePlaywright()
        drivers.append(driver)
        return driver

    playwright_module = ModuleType("playwright.async_api")
    setattr(playwright_module, "async_playwright", fake_async_playwright)
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", playwright_module)
    monkeypatch.setattr(
        "probos.tools.browser.session.loop_supports_subprocess", lambda loop: True,
    )
    config = SystemConfig()
    config.browser_tool.enabled = True
    config.browser_tool.bridge_enabled = True
    config.browser_tool.input_forwarding_enabled = True
    tool = BrowserTool(config=config.browser_tool)
    sessions: list[BrowserSession] = []
    input_task: asyncio.Task[dict[str, object]] | None = None

    try:
        for port in (9222, 9223):
            endpoint = f"http://127.0.0.1:{port}"
            opened = await tool.connect_bridge_session(
                endpoint, agent_id="captain", confirm=True,
            )
            assert opened["connected"] is True, opened
            session = tool.get_session(opened["session_id"])
            assert isinstance(session, BrowserSession)
            sessions.append(session)
            assert session.is_connected is True
            assert drivers[-1].chromium.endpoints == [endpoint]
            assert session.page is drivers[-1].chromium.browser.contexts[0].pages[0]
            assert session.page.default_timeout == config.browser_tool.default_timeout_ms

        selected, other = sessions
        assert selected.session_id != other.session_id
        assert tool.session_count == 2
        keyboard = selected.page.keyboard
        input_task = asyncio.create_task(tool.forward_input(
            selected.session_id, {"kind": "type", "text": "before end"},
            agent_id="captain",
        ))
        await asyncio.wait_for(keyboard.entered.wait(), timeout=2)
        assert not input_task.done()
        assert keyboard.typed == []
        keyboard.release.set()
        assert (await asyncio.wait_for(input_task, timeout=2))["forwarded"] is True
        assert keyboard.typed == ["before end"]

        await tool.end_session(selected.session_id, actor=None, confirm=False)

        assert tool.session_count == 2
        for session, driver in zip(sessions, drivers, strict=True):
            assert tool.get_session(session.session_id) is session
            assert session.is_connected is True
            browser = driver.chromium.browser
            context = browser.contexts[0]
            assert browser.disconnect_count == 0
            assert context.close_count == 0
            assert context.pages[0].close_count == 0
            assert driver.stop_count == 0
            session.page.keyboard.release.set()
            forwarded = await tool.forward_input(
                session.session_id, {"kind": "type", "text": "still usable"},
                agent_id="captain",
            )
            assert forwarded["forwarded"] is True
            assert session.page.keyboard.typed[-1] == "still usable"
    finally:
        for driver in drivers:
            driver.chromium.browser.contexts[0].pages[0].keyboard.release.set()
        if input_task is not None:
            if not input_task.done():
                input_task.cancel()
            await asyncio.gather(input_task, return_exceptions=True)
        for session in sessions:
            await session.stop()


class _OperatorPolicy:
    def allows(self, actor: BrowserActor) -> bool:
        return actor.authority_basis is BrowserAuthorityBasis.SHARED_CREW_SCOPE

    def is_known_crew_owner(self, agent_id: str) -> bool:
        return agent_id == "crew-one"

    def pending_browser_work(self, session_id: str) -> int | None:
        return 0


_ACTOR = BrowserActor(BrowserAuthorityBasis.SHARED_CREW_SCOPE)


async def _run_real_browser_case(case: Callable[[], Coroutine[Any, Any, None]]) -> None:
    host = PlaywrightLoopHost()
    try:
        host.start()
        assert host.is_running
        await host.run(case)
    finally:
        await host.aclose()


@pytest.mark.skipif(
    os.environ.get("PROBOS_PLAYWRIGHT_REAL") != "1",
    reason="Requires real Playwright + Chromium (set PROBOS_PLAYWRIGHT_REAL=1).",
)
@pytest.mark.asyncio
async def test_real_chromium_end_closes_launched_pages_context_and_browser() -> None:
    async def scenario() -> None:
        from playwright.async_api import Page

        config = SystemConfig().browser_tool
        config.enabled = True
        config.headless = True
        policy = _OperatorPolicy()
        events: list[tuple[Any, dict[str, Any]]] = []
        tool = BrowserTool(
            config=config, authorization=policy, ownership=policy, pending_work=policy,
            emit_event=lambda kind, payload: events.append((kind, payload)),
        )
        try:
            opened = await tool.invoke({"action": "state"}, {"agent_id": "captain"})
            assert opened.error is None, opened.error
            session_id = opened.metadata["session_id"]
            session = tool.get_session(session_id)
            assert isinstance(session, BrowserSession)
            page = session.page
            assert isinstance(page, Page), "The opt-in test must use a real Playwright page"
            context = page.context
            browser = context.browser
            assert browser is not None and browser.is_connected()
            assert browser.version
            assert not page.is_closed()
            await page.set_content("<title>Disposable launched page</title><p>owned-session</p>")
            assert await page.title() == "Disposable launched page"
            other_page = await context.new_page()
            await other_page.set_content("<p>second-owned-page</p>")
            assert len(context.pages) == 2
            context_closed: list[bool] = []
            context.on("close", lambda: context_closed.append(True))

            ended = await tool.end_session(session_id, actor=_ACTOR, confirm=True)

            assert ended.outcome == "completed", ended
            assert ended.status_code == 200
            assert page.is_closed() and other_page.is_closed()
            assert context_closed == [True]
            assert context.pages == []
            assert not browser.is_connected()
            assert tool.get_session(session_id) is None
            assert tool.session_snapshot(session_id).state is BrowserLifecycleState.ENDED
            repeated = await tool.end_session(session_id, actor=_ACTOR, confirm=True)
            assert repeated == ended
            assert context_closed == [True]
            assert sum(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events) == 1
        finally:
            await tool.stop()

    await _run_real_browser_case(scenario)


@pytest.mark.skipif(
    os.environ.get("PROBOS_PLAYWRIGHT_REAL") != "1",
    reason="Requires real Playwright + Chromium (set PROBOS_PLAYWRIGHT_REAL=1).",
)
@pytest.mark.asyncio
async def test_real_chromium_end_disconnects_external_cdp_and_preserves_browser(tmp_path: Path) -> None:
    async def scenario() -> None:
        from playwright.async_api import Page, async_playwright

        config = SystemConfig().browser_tool
        config.enabled = config.bridge_enabled = True
        config.headless = True
        config.bridge_allowed_hosts = ["127.0.0.1"]
        policy = _OperatorPolicy()
        events: list[tuple[Any, dict[str, Any]]] = []
        tool = BrowserTool(
            config=config, authorization=policy, ownership=policy, pending_work=policy,
            emit_event=lambda kind, payload: events.append((kind, payload)),
        )
        async with async_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
            assert executable.is_file(), f"Real Chromium prerequisite missing: {executable}"
            profile = tmp_path / "disposable-external-profile"
            external_context = None
            try:
                external_context = await playwright.chromium.launch_persistent_context(
                    str(profile), headless=True, executable_path=str(executable),
                    args=["--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1"],
                )
                external_browser = external_context.browser
                assert external_browser is not None and external_browser.is_connected()
                port_file = profile / "DevToolsActivePort"
                for _attempt in range(100):
                    if port_file.is_file():
                        break
                    await asyncio.sleep(0.05)
                assert port_file.is_file(), "Disposable Chromium did not publish its CDP port; Worker prerequisite probe required"
                endpoint_lines = port_file.read_text(encoding="utf-8").splitlines()
                assert len(endpoint_lines) == 2 and endpoint_lines[0].isdigit(), endpoint_lines
                assert endpoint_lines[1].startswith("/devtools/browser/"), endpoint_lines
                port = int(endpoint_lines[0])
                assert 0 < port < 65536
                endpoint = f"http://127.0.0.1:{port}"
                page = external_context.pages[0]
                assert isinstance(page, Page) and not page.is_closed()
                await page.set_content("<title>Disposable external page</title><p>external-marker</p>")
                context_closed: list[bool] = []
                external_context.on("close", lambda: context_closed.append(True))
                attached = await tool.connect_bridge_session(endpoint, agent_id="captain", confirm=True)
                assert attached["connected"] is True, attached
                session_id = attached["session_id"]
                session = tool.get_session(session_id)
                assert isinstance(session, BrowserSession) and session.is_connected
                attached_page = session.page
                assert isinstance(attached_page, Page)
                assert await attached_page.title() == "Disposable external page"
                assert await attached_page.inner_text("p") == "external-marker"
                other_page = await external_context.new_page()
                await other_page.set_content("<title>Untouched external tab</title>")
                attached_browser = attached_page.context.browser
                assert attached_browser is not None and attached_browser.is_connected()
                assert tool.session_snapshot(session_id).external_browser is True

                ended = await tool.end_session(session_id, actor=_ACTOR, confirm=True)

                assert ended.status_code == 200 and ended.outcome == "completed", ended
                assert not attached_browser.is_connected()
                assert external_browser.is_connected(), "Ending ProbOS must not close the external browser"
                assert not page.is_closed() and not other_page.is_closed()
                assert context_closed == []
                assert len(external_context.pages) == 2
                assert await page.title() == "Disposable external page"
                assert await other_page.title() == "Untouched external tab"
                await page.evaluate("document.querySelector('p').textContent = 'still-alive'")
                assert await page.inner_text("p") == "still-alive"
                fresh_page = await external_context.new_page()
                await fresh_page.set_content("<title>External browser still creates pages</title>")
                assert await fresh_page.title() == "External browser still creates pages"
                assert tool.get_session(session_id) is None
                assert (await tool.end_session(session_id, actor=_ACTOR, confirm=True)) == ended
                assert sum(kind == EventType.BROWSER_BRIDGE_DISCONNECTED for kind, _ in events) == 1
                assert sum(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events) == 1
            finally:
                try:
                    await tool.stop()
                finally:
                    if external_context is not None:
                        await external_context.close()

    await _run_real_browser_case(scenario)


@pytest.fixture
def lifecycle_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest,
) -> tuple[BrowserTool, list[_FakePlaywright], list[tuple[Any, dict[str, Any]]]]:
    drivers: list[_FakePlaywright] = []
    events: list[tuple[Any, dict[str, Any]]] = []

    def factory() -> _FakePlaywright:
        driver = _FakePlaywright()
        drivers.append(driver)
        return driver

    module = ModuleType("playwright.async_api")
    setattr(module, "async_playwright", factory)
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    monkeypatch.setattr("probos.tools.browser.session.loop_supports_subprocess", lambda loop: True)
    config = SystemConfig().browser_tool
    config.enabled = config.bridge_enabled = config.input_forwarding_enabled = True
    config.streaming_enabled = True
    config.recording_enabled = True
    config.recording_dir = str(tmp_path)
    config.default_min_interval_seconds = 0
    if hasattr(request, "param"):
        config.session_max_duration_seconds = request.param
    policy = _OperatorPolicy()
    return BrowserTool(
        config=config, authorization=policy, ownership=policy, pending_work=policy,
        emit_event=lambda kind, payload: events.append((kind, payload)),
    ), drivers, events


@pytest.fixture
def browser_clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    clock = SimpleNamespace(now=2_000_000_000.0)
    dependency = SimpleNamespace(time=lambda: clock.now, monotonic=time.monotonic)
    monkeypatch.setattr("probos.tools.browser.session.time", dependency)
    monkeypatch.setattr("probos.tools.browser.tool.time", dependency)
    return clock


@pytest.fixture
def browser_invocations(
    wired_browser_runtime: Any, monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[dict[str, Any], dict[str, Any], ToolResult]]:
    runtime, _, _ = wired_browser_runtime
    tool = runtime.browser_tool
    assert runtime.tool_registry.get_tool("browser") is tool
    original_invoke = tool.invoke
    calls: list[tuple[dict[str, Any], dict[str, Any], ToolResult]] = []

    async def observed_invoke(
        params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        result = await original_invoke(params, context)
        calls.append((dict(params), dict(context or {}), result))
        return result

    monkeypatch.setattr(tool, "invoke", observed_invoke)
    return calls


async def _bridge(tool: BrowserTool, owner: str = "captain") -> str:
    opened = await tool.connect_bridge_session("http://127.0.0.1:9222", agent_id=owner, confirm=True)
    assert opened["connected"] is True, opened
    assert isinstance(tool.get_session(opened["session_id"]), BrowserSession)
    return opened["session_id"]


class _CrewRegistry:
    def __init__(self) -> None:
        self.agents = {
            "crew-one": SimpleNamespace(id="crew-one", agent_type="counselor"),
            "probationary": SimpleNamespace(id="probationary", agent_type="counselor"),
        }

    def get(self, agent_id: str) -> Any:
        return self.agents.get(agent_id)


class _CrewOntology:
    def get_crew_agent_types(self) -> list[str]:
        return ["counselor"]

    def get_agent_department(self, agent_type: str) -> str:
        return "medical"


class _CrewTrust:
    def get_score(self, agent_id: str) -> float:
        return 0.1 if agent_id == "probationary" else 0.7


@pytest_asyncio.fixture
async def wired_browser_runtime(
    lifecycle_tool: Any, request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[Any, list[_FakePlaywright], list[tuple[Any, dict[str, Any]]]]]:
    from probos.capability_request import CapabilityRequestStore
    from probos.security.audit import AuditLog
    from probos.startup.finalize import _wire_browser_tool
    from probos.tools.registry import ToolRegistry

    _, drivers, events = lifecycle_tool
    config = SystemConfig()
    config.auth.crew_scope_token = getattr(request, "param", "secret")
    config.browser_tool.enabled = config.browser_tool.bridge_enabled = True
    config.browser_tool.streaming_enabled = config.browser_tool.input_forwarding_enabled = True
    config.browser_tool.streaming_fps = 30
    config.browser_tool.default_min_interval_seconds = 0
    config.agentic_tools.browser_enabled = True
    requests = CapabilityRequestStore()
    await requests.start()
    runtime = SimpleNamespace(
        config=config, registry=_CrewRegistry(), ontology=_CrewOntology(),
        trust_network=_CrewTrust(), tool_registry=ToolRegistry(),
        capability_request_store=requests, audit_log=AuditLog(),
        emit_event=lambda kind, payload: events.append((kind, payload)),
    )
    assert _wire_browser_tool(runtime=runtime, config=config) is True
    assert runtime.tool_registry.get_tool("browser") is runtime.browser_tool
    try:
        yield runtime, drivers, events
    finally:
        for pending in await requests.list_pending():
            await requests.decide(pending.id, False)
        await runtime.browser_tool.stop()
        await requests.stop()


def browser_app(runtime: Any) -> Any:
    from fastapi import FastAPI
    from probos.routers.browser_stream import router
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app


async def _park_lifecycle_approval(
    runtime: Any, monkeypatch: pytest.MonkeyPatch, session_id: str | None = None,
    *, explicit_session_id: str | None = None,
) -> CapabilityRequest:
    from probos.cognitive.agentic_dispatch import DispatchToolExecutor
    from probos.tools.protocol import ToolResult

    tool = runtime.browser_tool
    store = runtime.capability_request_store
    assert isinstance(tool, BrowserTool)
    assert isinstance(store, CapabilityRequestStore)
    assert runtime.tool_registry.get_tool("browser") is tool
    runtime.config.approval_inbox.enabled = True
    executor = DispatchToolExecutor(registry=runtime.tool_registry)
    executor.arm_approval_inbox(
        request_store=store, approval_store=None, config=runtime.config.approval_inbox,
    )
    entered: list[dict[str, Any]] = []
    original_invoke = tool.invoke

    async def observed_invoke(
        params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        entered.append(params)
        return await original_invoke(params, context)

    assert await store.list_pending() == []
    params = {"action": "eval_js", "expression": "1"}
    if explicit_session_id is not None:
        params["session_id"] = explicit_session_id
    original_params = dict(params)
    async with tool.reserve_use(session_id, agent_id="crew-one") as use:
        assert tool.is_use_active(use)
        with monkeypatch.context() as patch:
            patch.setattr(tool, "invoke", observed_invoke)
            result = await executor.invoke(
                "crew-one", "browser", params,
                context={"browser_session_id": session_id} if session_id else {},
            )
        assert result.error is not None and "filed for review" in result.error
        assert entered == [], "The parked action must not enter BrowserTool.invoke"
        assert params == original_params
    assert not tool.is_use_active(use)
    pending = await store.list_pending()
    assert len(pending) == 1
    request = pending[0]
    assert request.kind == "action" and request.status == "pending"
    assert request.payload["tool_id"] == "browser"
    expected_session_id = explicit_session_id or session_id
    assert request.payload["session_id"] == expected_session_id
    assert request.payload["action"] == original_params["action"]
    stored_params = {key: value for key, value in original_params.items() if key != "action"}
    assert request.payload["params"] == (
        {**stored_params, "session_id": expected_session_id}
        if expected_session_id else stored_params
    )
    assert await store.get(request.id) == request
    return request


@pytest.mark.asyncio
@pytest.mark.parametrize("bridge,interruption,cleanup_failure", [
    (False, "failure", False), (True, "failure", False),
    (False, "cancel", False), (True, "cancel", False),
    (False, "failure", True), (True, "failure", True),
])
async def test_unpublished_initialization_cleanup_ignores_unbound_approval(
    wired_browser_runtime: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    bridge: bool, interruption: str, cleanup_failure: bool,
) -> None:
    from probos.startup.finalize import BrowserLifecycleAdapter

    runtime, drivers, events = wired_browser_runtime
    tool = runtime.browser_tool
    store = runtime.capability_request_store
    reader = tool._pending_work_reader
    assert isinstance(reader, BrowserLifecycleAdapter)
    assert reader._request_store is store
    request = await _park_lifecycle_approval(runtime, monkeypatch)
    before_request = asdict(request)
    assert await reader.read_pending_browser_work("unpublished-probe") is None
    runtime.config.browser_tool.recording_enabled = True
    runtime.config.browser_tool.recording_dir = str(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()
    external_contexts: list[_FakeContext] = []
    original_connect = _FakeChromium.connect_over_cdp
    original_new_page = _FakeContext.new_page

    async def connect_without_default_context(
        chromium: _FakeChromium, endpoint: str,
    ) -> _FakeBrowser:
        browser = await original_connect(chromium, endpoint)
        external_contexts.extend(browser.contexts)
        browser.contexts = []
        return browser

    async def gated_new_context(browser: _FakeBrowser, **kwargs: Any) -> _FakeContext:
        assert browser is drivers[0].chromium.browser
        entered.set()
        await release.wait()
        if interruption == "failure":
            raise RuntimeError("initialization boundary failed")
        return external_contexts[0]

    async def gated_new_page(context: _FakeContext) -> _FakePage:
        assert context is drivers[0].chromium.browser.contexts[0]
        entered.set()
        await release.wait()
        if interruption == "failure":
            raise RuntimeError("initialization boundary failed")
        return await original_new_page(context)

    if bridge:
        monkeypatch.setattr(_FakeChromium, "connect_over_cdp", connect_without_default_context)
        monkeypatch.setattr(_FakeBrowser, "new_context", gated_new_context)
    else:
        monkeypatch.setattr(_FakeContext, "new_page", gated_new_page)
    opening = asyncio.create_task(
        tool.connect_bridge_session("http://127.0.0.1:9222", agent_id="captain", confirm=True)
        if bridge else tool._get_or_create_session(None, "crew-one")
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert len(drivers) == 1 and not opening.done()
        rows = await tool.list_session_metadata()
        assert len(rows) == 1
        selected = rows[0].session_id
        assert rows[0].state is BrowserLifecycleState.CREATING
        assert rows[0].pending_work is None
        session = tool.get_session(selected)
        assert isinstance(session, BrowserSession)
        browser = drivers[0].chromium.browser
        context = external_contexts[0] if bridge else browser.contexts[0]
        assert session._browser is browser
        assert session._initialization_task is not None
        assert not session._initialization_task.done()
        assert not session.is_expired()
        assert tool.captain_session is None
        async with tool.reserve_use(agent_id="crew-one") as use:
            assert use.session is None
        with pytest.raises(BrowserLifecycleConflict):
            async with tool.reserve_use(selected):
                pytest.fail("Creating identity was admitted for crew use")
        with pytest.raises(BrowserLifecycleConflict):
            await tool.admit_stream(selected)
        assert (await tool.forward_input(
            selected, {"kind": "type", "text": "not admitted"}, agent_id="captain",
        ))["forwarded"] is False
        assert context.pages[0].keyboard.typed == []
        assert tool.active_viewers == 0
        browser.fail_close = cleanup_failure and bridge
        context.fail_close = cleanup_failure and not bridge
        if interruption == "cancel":
            opening.cancel()
            await asyncio.sleep(0)
            assert not opening.done()
            assert drivers[0].stop_count == 0
        release.set()
        if interruption == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(opening, 2)
        elif bridge:
            assert (await asyncio.wait_for(opening, 2))["connected"] is False
        else:
            with pytest.raises(RuntimeError, match="initialization boundary failed"):
                await asyncio.wait_for(opening, 2)
        assert session._initialization_task.done()
        assert not any(kind in (
            EventType.BROWSER_SESSION_OPENED, EventType.BROWSER_BRIDGE_CONNECTED,
        ) for kind, _ in events)
        assert asdict(await store.get(request.id)) == before_request
        assert await store.list_pending() == [request]
        if cleanup_failure:
            assert drivers[0].stop_count == 0
            assert session._browser is browser
            assert (browser.disconnect_count if bridge else context.close_count) >= 1
            assert tool.get_session(selected) is session
            assert tool.session_snapshot(selected).state is BrowserLifecycleState.CLEANUP_FAILED
            assert not any(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events)
            browser.fail_close = context.fail_close = False
            assert not session.is_expired(), "Unpublished cleanup retry must not depend on TTL"
            assert await tool.reap_expired() == 1
        else:
            assert drivers[0].stop_count == browser.disconnect_count == 1
            assert session._browser is None
            assert context.close_count == (0 if bridge else 1)
            assert context.pages[0].close_count == (1 if not bridge and interruption == "cancel" else 0)
        assert tool.get_session(selected) is None, "Closed resources must not leave owner bookkeeping"
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ENDED
        assert drivers[0].stop_count == 1
        if bridge:
            assert context.close_count == context.pages[0].close_count == 0
            assert await context.pages[0].title() == "Local test page"
        counts = (browser.disconnect_count, context.close_count, context.pages[0].close_count)
        assert await tool.reap_expired() == 0
        stale = await tool.invoke({"action": "screenshot"}, {"browser_session_id": selected})
        assert stale.error == "session_not_active"
        with pytest.raises(RuntimeError):
            await session.start()
        with pytest.raises(RuntimeError):
            await session.connect("http://127.0.0.1:9222")
        assert len(drivers) == 1
        assert counts == (browser.disconnect_count, context.close_count, context.pages[0].close_count)
        assert sum(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events) == 1
        assert sum(kind == EventType.BROWSER_BRIDGE_DISCONNECTED for kind, _ in events) == int(bridge)
        assert sum(kind == EventType.BROWSER_RECORDING_STARTED for kind, _ in events) == int(not bridge)
        assert sum(kind == EventType.BROWSER_RECORDING_STOPPED for kind, _ in events) == int(not bridge)
        assert sum(kind == EventType.BROWSER_RECORDING_FAILED for kind, _ in events) == int(cleanup_failure and not bridge)
        assert asdict(await store.get(request.id)) == before_request
        assert await store.list_pending() == [request]
    finally:
        release.set()
        await asyncio.gather(opening, return_exceptions=True)
        for driver in drivers:
            driver.chromium.browser.fail_close = False
            for context in driver.chromium.browser.contexts:
                context.fail_close = False


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", [False, True])
async def test_published_expiry_after_dispatch_scope_release_preserves_pending_approval(
    wired_browser_runtime: Any, monkeypatch: pytest.MonkeyPatch, bound: bool,
) -> None:
    runtime, drivers, events = wired_browser_runtime
    tool = runtime.browser_tool
    store = runtime.capability_request_store
    selected = await _bridge(tool)
    other = await _bridge(tool)
    request = await _park_lifecycle_approval(runtime, monkeypatch, selected if bound else None)
    before_request = asdict(request)
    session = tool.get_session(selected)
    assert isinstance(session, BrowserSession)
    runtime.config.browser_tool.session_max_duration_seconds = 0
    assert session.is_expired() and tool.get_session(other).is_expired()
    metadata = {row.session_id: row for row in await tool.list_session_metadata()}
    assert metadata[selected].pending_work == (1 if bound else None)
    assert metadata[other].pending_work == (0 if bound else None)
    assert metadata[selected].expires_at == session.expires_at
    assert await tool.reap_expired() == int(bound)
    await tool._discard_session(selected, reason="open_failed")
    await tool._discard_session(selected, reason="open_refused")
    assert tool.get_session(selected) is session
    assert tool.session_snapshot(selected).state is BrowserLifecycleState.ACTIVE
    for action in (tool.end_session, tool.hand_to_crew):
        result = await action(selected, actor=_ACTOR, confirm=True)
        assert result.status_code == 409
        assert result.session.pending_work == (1 if bound else None)
    assert drivers[0].stop_count == drivers[0].chromium.browser.disconnect_count == 0
    assert drivers[1].stop_count == int(bound)
    assert asdict(await store.get(request.id)) == before_request
    assert await store.list_pending() == [request]
    decided = await store.decide(request.id, True)
    assert decided is not None and decided.status == "approved"
    assert await store.list_pending() == []
    assert drivers[0].stop_count == 0
    assert all(row.pending_work == 0 for row in await tool.list_session_metadata())
    assert await tool.reap_expired() == (1 if bound else 2)
    assert await tool.reap_expired() == 0
    assert drivers[0].stop_count == drivers[1].stop_count == 1
    for session_id in (selected, other):
        assert tool.session_snapshot(session_id).state is BrowserLifecycleState.ENDED
        assert sum(kind == EventType.BROWSER_SESSION_CLOSED and payload["session_id"] == session_id for kind, payload in events) == 1


@pytest.mark.asyncio
async def test_published_expiry_reservation_blocks_until_release_with_known_zero_control(
    wired_browser_runtime: Any,
) -> None:
    runtime, drivers, events = wired_browser_runtime
    tool = runtime.browser_tool
    selected = await _bridge(tool)
    other = await _bridge(tool)
    assert await runtime.capability_request_store.list_pending() == []
    async with tool.reserve_use(selected) as use:
        assert tool.is_use_active(use)
        runtime.config.browser_tool.session_max_duration_seconds = 0
        assert tool.get_session(selected).is_expired() and tool.get_session(other).is_expired()
        metadata = {row.session_id: row for row in await tool.list_session_metadata()}
        assert metadata[selected].pending_work == 1 and metadata[other].pending_work == 0
        assert await tool.reap_expired() == 1
        await tool._discard_session(selected, reason="open_failed")
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ACTIVE
        assert drivers[0].stop_count == 0 and drivers[1].stop_count == 1
        assert tool.is_use_active(use)
    assert not tool.is_use_active(use)
    assert (await tool.list_session_metadata())[0].pending_work == 0
    assert await tool.reap_expired() == 1
    assert await tool.reap_expired() == 0
    assert drivers[0].stop_count == 1
    assert sum(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raises", "malformed"])
async def test_published_expiry_unknown_reader_defers_without_cleanup_failure(
    wired_browser_runtime: Any, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    runtime, drivers, events = wired_browser_runtime
    tool = runtime.browser_tool
    selected = await _bridge(tool)
    session = tool.get_session(selected)
    assert isinstance(session, BrowserSession)
    assert await runtime.capability_request_store.list_pending() == []
    runtime.config.browser_tool.session_max_duration_seconds = 0
    assert session.is_expired()
    calls: list[str] = []

    async def unreadable_pending() -> list[CapabilityRequest]:
        calls.append(failure)
        if failure == "raises":
            raise RuntimeError("request store unavailable")
        return [CapabilityRequest(kind="action", payload={})]

    with monkeypatch.context() as patch:
        patch.setattr(runtime.capability_request_store, "list_pending", unreadable_pending)
        rows = await tool.list_session_metadata()
        assert calls == [failure]
        assert rows[0].pending_work is None
        assert rows[0].expires_at == session.expires_at
        assert await tool.reap_expired() == 0
        await tool._discard_session(selected, reason="open_failed")
        for action in (tool.end_session, tool.hand_to_crew):
            result = await action(selected, actor=_ACTOR, confirm=True)
            assert result.status_code == 409 and result.session.pending_work is None
        assert tool.get_session(selected) is session
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ACTIVE
        assert drivers[0].stop_count == drivers[0].chromium.browser.disconnect_count == 0
        assert not any(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events)
    assert await runtime.capability_request_store.list_pending() == []
    assert (await tool.list_session_metadata())[0].pending_work == 0
    assert await tool.reap_expired() == 1
    assert await tool.reap_expired() == 0
    assert drivers[0].stop_count == 1
    assert sum(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events) == 1


@pytest.mark.asyncio
async def test_end_drains_input_closes_two_viewers_and_preserves_other_recording(lifecycle_tool: Any) -> None:
    tool, drivers, events = lifecycle_tool
    selected = await _bridge(tool)
    other = await tool._get_or_create_session(None, "captain")
    assert other.recording_state == "recording"
    viewers = [tool.stream_frames(selected), tool.stream_frames(selected)]
    tasks: list[asyncio.Task[Any]] = []
    keyboard = drivers[0].chromium.browser.contexts[0].pages[0].keyboard
    try:
        for viewer in viewers:
            assert await anext(viewer) == b"jpeg-frame"
        assert drivers[0].chromium.browser.contexts[0].pages[0].frames == 2
        assert tool.active_viewers == 2
        pending_input = asyncio.create_task(tool.forward_input(selected, {"kind": "type", "text": "admitted"}, agent_id="captain"))
        tasks.append(pending_input)
        await asyncio.wait_for(keyboard.entered.wait(), 2)
        ending = asyncio.create_task(tool.end_session(selected, actor=_ACTOR, confirm=True))
        tasks.append(ending)
        await asyncio.sleep(0)
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ENDING
        assert not ending.done()
        assert (await tool.forward_input(selected, {"kind": "type", "text": "late"}, agent_id="captain"))["forwarded"] is False
        repeat = asyncio.create_task(tool.end_session(selected, actor=_ACTOR, confirm=True))
        tasks.append(repeat)
        keyboard.release.set()
        assert (await pending_input)["forwarded"] is True
        assert (await ending).status_code == 200
        assert await repeat == await tool.end_session(selected, actor=_ACTOR, confirm=True)
        assert keyboard.typed == ["admitted"]
        assert tool.active_viewers == 0
        for viewer in viewers:
            with pytest.raises(StopAsyncIteration):
                await anext(viewer)
        browser = drivers[0].chromium.browser
        assert browser.disconnect_count == 1
        assert browser.contexts[0].close_count == browser.contexts[0].pages[0].close_count == 0
        assert tool.get_session(other.session_id) is other
        assert other.recording_state == "recording"
        assert drivers[1].chromium.browser.contexts[0].close_count == 0
        assert sum(kind == EventType.BROWSER_SESSION_CLOSED and payload["session_id"] == selected for kind, payload in events) == 1
        assert sum(kind == EventType.BROWSER_STREAM_CLOSED for kind, _ in events) == 2
        assert sum(kind == EventType.BROWSER_BRIDGE_DISCONNECTED for kind, _ in events) == 1
    finally:
        keyboard.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        for viewer in viewers:
            await viewer.aclose()
        await tool.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("actor,confirm,status", [
    (None, True, 403), ({"authority_basis": "shared_crew_scope"}, True, 403),
    (BrowserActor("shared_crew_scope"), True, 403),
    (BrowserActor(BrowserAuthorityBasis.SINGLE_OPERATOR_COMPATIBILITY), True, 403),
    (_ACTOR, False, 422), (_ACTOR, 1, 422), (_ACTOR, "true", 422),
])
async def test_end_rejects_forged_authority_and_nonexact_confirmation(lifecycle_tool: Any, actor: Any, confirm: Any, status: int) -> None:
    tool, drivers, _ = lifecycle_tool
    selected = await _bridge(tool)
    try:
        result = await tool.end_session(selected, actor=actor, confirm=confirm)
        assert result.status_code == status
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ACTIVE
        assert drivers[0].stop_count == 0
    finally:
        await tool.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id,status", [("", 422), (None, 422), ("../bad", 422), ("unknown", 404)])
async def test_end_validates_identity(lifecycle_tool: Any, session_id: Any, status: int) -> None:
    tool, _, _ = lifecycle_tool
    assert (await tool.end_session(session_id, actor=_ACTOR, confirm=True)).status_code == status


@pytest.mark.asyncio
async def test_unknown_owner_blocks_end_and_crew_owner_cannot_handoff(lifecycle_tool: Any) -> None:
    tool, _, _ = lifecycle_tool
    unknown = await _bridge(tool, "unregistered")
    crew = await _bridge(tool, "crew-one")
    try:
        assert (await tool.end_session(unknown, actor=_ACTOR, confirm=True)).reason == "unknown_ownership"
        assert (await tool.hand_to_crew(crew, actor=_ACTOR, confirm=True)).status_code == 403
        assert (await tool.end_session(crew, actor=_ACTOR, confirm=True)).status_code == 200
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_cleanup_failure_retains_identity_and_retry_disconnects_once(lifecycle_tool: Any) -> None:
    tool, drivers, events = lifecycle_tool
    selected = await _bridge(tool)
    browser = drivers[0].chromium.browser
    browser.fail_close = True
    try:
        result = await tool.end_session(selected, actor=_ACTOR, confirm=True)
        assert result.reason == "cleanup_failed"
        assert tool.get_session(selected) is not None
        assert result.session.state is BrowserLifecycleState.CLEANUP_FAILED
        assert not any(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events)
        assert (await tool.invoke({"action": "state", "session_id": selected})).error == "session_not_active"
        browser.fail_close = False
        assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200
        assert drivers[0].stop_count == 1
        assert sum(kind == EventType.BROWSER_BRIDGE_DISCONNECTED for kind, _ in events) == 1
    finally:
        browser.fail_close = False
        await tool.stop()


@pytest.mark.asyncio
async def test_cancelled_end_request_does_not_cancel_cleanup(lifecycle_tool: Any) -> None:
    tool, drivers, _ = lifecycle_tool
    selected = await _bridge(tool)
    keyboard = drivers[0].chromium.browser.contexts[0].pages[0].keyboard
    pending = asyncio.create_task(tool.forward_input(selected, {"kind": "type", "text": "settles"}, agent_id="captain"))
    ending: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(keyboard.entered.wait(), 2)
        ending = asyncio.create_task(tool.end_session(selected, actor=_ACTOR, confirm=True))
        await asyncio.sleep(0)
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ENDING
        ending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await ending
        keyboard.release.set()
        assert (await pending)["forwarded"] is True
        assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200
        assert drivers[0].stop_count == 1
    finally:
        keyboard.release.set()
        await asyncio.gather(pending, *([ending] if ending else []), return_exceptions=True)
        await tool.stop()


@pytest.mark.asyncio
async def test_cancel_before_end_admission_keeps_session_active(lifecycle_tool: Any) -> None:
    tool, _, _ = lifecycle_tool
    selected = await _bridge(tool)
    try:
        ending = asyncio.create_task(tool.end_session(selected, actor=_ACTOR, confirm=True))
        ending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await ending
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ACTIVE
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_screenshot_failure_and_viewer_withdrawal_leave_session_active(lifecycle_tool: Any) -> None:
    tool, drivers, _ = lifecycle_tool
    selected = await _bridge(tool)
    first = tool.stream_frames(selected)
    second = tool.stream_frames(selected)
    try:
        assert await anext(first) == await anext(second) == b"jpeg-frame"
        await first.aclose()
        assert tool.active_viewers == 1
        drivers[0].chromium.browser.contexts[0].pages[0].fail_screenshot = True
        with pytest.raises(StopAsyncIteration):
            await anext(second)
        assert tool.active_viewers == 0
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ACTIVE
        assert drivers[0].stop_count == 0
    finally:
        await first.aclose()
        await second.aclose()
        await tool.stop()


@pytest.mark.asyncio
async def test_reservation_handoff_and_stale_context_never_relaunch(lifecycle_tool: Any) -> None:
    tool, drivers, _ = lifecycle_tool
    selected = await _bridge(tool)
    other = await _bridge(tool)
    try:
        assert (await tool.hand_to_crew(selected, actor=_ACTOR, confirm=True)).status_code == 200
        assert tool.captain_session_id == selected
        async with tool.reserve_use() as use:
            assert use.session.session_id == selected
            assert tool.is_use_active(use)
            assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 409
            assert (await tool.hand_to_crew(other, actor=_ACTOR, confirm=True)).status_code == 409
            assert (await tool.invoke({"action": "screenshot"}, {"agent_id": "crew-one", "browser_session_id": selected})).error is None
        assert not tool.is_use_active(use)
        assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200
        assert tool.captain_session_id is None
        async with tool.reserve_use(agent_id="crew-one") as next_use:
            assert next_use.session is None
            assert next_use.page_url == ""
        with pytest.raises(BrowserLifecycleConflict):
            async with tool.reserve_use(selected, agent_id="crew-one"):
                pytest.fail("explicit terminal selection admitted")
        assert (await tool.invoke({"action": "state"}, {"browser_session_id": selected})).error == "session_not_active"
        assert len(drivers) == 2
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_recording_cleanup_failure_retry_preserves_file_and_emits_once(lifecycle_tool: Any, tmp_path: Path) -> None:
    tool, drivers, events = lifecycle_tool
    session = await tool._get_or_create_session(None, "captain")
    recording = tmp_path / session.session_id / "capture.webm"
    recording.write_bytes(b"retained recording")
    context = drivers[0].chromium.browser.contexts[0]
    try:
        context.fail_close = True
        assert (await tool.end_session(session.session_id, actor=_ACTOR, confirm=True)).reason == "cleanup_failed"
        assert session.recording_state == "cleanup_failed"
        assert drivers[0].chromium.browser.disconnect_count == 0
        context.fail_close = False
        assert (await tool.end_session(session.session_id, actor=_ACTOR, confirm=True)).status_code == 200
        await session.stop()
        assert session.recording_state == "finalized"
        assert recording.read_bytes() == b"retained recording"
        assert sum(kind == EventType.BROWSER_RECORDING_STOPPED for kind, _ in events) == 1
        assert sum(kind == EventType.BROWSER_RECORDING_FAILED for kind, _ in events) == 1
        with pytest.raises(RuntimeError):
            await session.start()
        with pytest.raises(RuntimeError):
            await session.connect("http://127.0.0.1:9222")
    finally:
        context.fail_close = False
        await tool.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle_tool", [0], indirect=True)
async def test_expired_own_session_retained_by_run_allows_fresh_browser(lifecycle_tool: Any) -> None:
    tool, drivers, _ = lifecycle_tool
    async with tool.reserve_use(agent_id="crew-one"):
        first = await tool.invoke({"action": "state"}, {"agent_id": "crew-one"})
        assert first.error is None
        first_id = first.metadata["session_id"]
        assert tool.get_session(first_id).is_expired()
        assert (await tool.end_session(first_id, actor=_ACTOR, confirm=True)).status_code == 409
        second = await tool.invoke({"action": "state"}, {"agent_id": "crew-one"})
        assert second.error is None
        assert second.metadata["session_id"] != first_id
        assert len(drivers) == 2
        assert tool.get_session(first_id) is not None
        assert drivers[0].stop_count == 0
        assert (await tool.end_session(first_id, actor=_ACTOR, confirm=True)).status_code == 409
    assert await tool.reap_expired() == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle_tool", [0], indirect=True)
async def test_initial_navigation_with_zero_ttl_then_reap_fences_identity(lifecycle_tool: Any) -> None:
    tool, drivers, events = lifecycle_tool
    try:
        result = await tool.invoke(
            {"action": "goto", "url": "https://example.com/"},
            {"agent_id": "crew-one"},
        )
        assert result.error is None
        selected = result.metadata["session_id"]
        assert selected
        assert tool.get_session(selected) is not None
        assert drivers[0].chromium.browser.contexts[0].pages[0].url == "https://example.com/"
        assert await tool.reap_expired() == 1
        assert tool.get_session(selected) is None
        stale = await tool.invoke({"action": "screenshot"}, {"browser_session_id": selected})
        assert stale.error == "session_not_active"
        assert len(drivers) == 1
        assert sum(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events) == 1
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_shutdown_discards_confirmations_but_explicit_end_preserves_them(lifecycle_tool: Any) -> None:
    tool, drivers, events = lifecycle_tool
    selected = await _bridge(tool)
    other = await _bridge(tool)
    try:
        for session_id in (selected, other):
            tool.seed_confirmation_token(token=session_id, session_id=session_id, action="click")
        assert tool.session_snapshot(selected).pending_work == 1
        assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).reason == "pending_or_unknown_work"
        assert tool.session_snapshot(selected).pending_work == 1
        assert tool.session_snapshot(other).pending_work == 1
        assert drivers[0].stop_count == drivers[1].stop_count == 0
        await tool.stop()
        assert tool.session_count == 0
        assert drivers[0].stop_count == drivers[1].stop_count == 1
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ENDED
        assert tool.session_snapshot(selected).pending_work == 0
        assert tool.session_snapshot(other).pending_work == 0
        assert (await tool.invoke({"action": "click", "session_id": selected, "confirmation_token": selected})).error
        assert sum(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events) == 2
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_shutdown_with_reservation_refuses_without_cancelling_crew(lifecycle_tool: Any) -> None:
    tool, drivers, _ = lifecycle_tool
    selected = await _bridge(tool)
    try:
        async with tool.reserve_use(selected) as use:
            tool.seed_confirmation_token(token="pending", session_id=selected, action="click")
            with pytest.raises(BrowserLifecycleConflict, match="pending_or_unknown_work"):
                await tool.stop()
            assert tool.is_use_active(use)
            assert tool.get_session(selected) is not None
            assert drivers[0].stop_count == 0
        await tool.stop()
        assert drivers[0].stop_count == 1
    finally:
        await tool.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("hosted", [False, True])
@pytest.mark.parametrize("bridge", [False, True])
async def test_pending_creation_cancelled_after_host_entry_cleans_resources(
    lifecycle_tool: Any, monkeypatch: pytest.MonkeyPatch, hosted: bool, bridge: bool,
) -> None:
    tool, drivers, events = lifecycle_tool
    entered = threading.Event()
    release = threading.Event()
    host = PlaywrightLoopHost()
    original_launch = _FakeChromium.launch
    original_connect = _FakeChromium.connect_over_cdp

    async def gated_launch(chromium: _FakeChromium, **kwargs: Any) -> _FakeBrowser:
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.001)
        return await original_launch(chromium, **kwargs)

    async def gated_connect(chromium: _FakeChromium, endpoint: str) -> _FakeBrowser:
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.001)
        return await original_connect(chromium, endpoint)

    monkeypatch.setattr(_FakeChromium, "launch", gated_launch)
    monkeypatch.setattr(_FakeChromium, "connect_over_cdp", gated_connect)
    if hosted:
        monkeypatch.setattr("probos.tools.browser.session.loop_supports_subprocess", lambda loop: False)
        monkeypatch.setattr("probos.tools.browser.session.get_playwright_host", lambda: host)
    opening = asyncio.create_task(
        tool.connect_bridge_session("http://127.0.0.1:9222", agent_id="captain", confirm=True)
        if bridge else tool.invoke(
            {"action": "goto", "url": "https://example.com/"}, {"agent_id": "captain"},
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 2), "initialization never reached the gate"
        assert host.is_running is hosted
        rows = tool.list_sessions()
        assert len(rows) == 1
        selected = rows[0]["session_id"]
        assert rows[0]["state"] is BrowserLifecycleState.CREATING
        assert tool.captain_session is None
        assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).reason == "session_creating"
        assert (await tool.hand_to_crew(selected, actor=_ACTOR, confirm=True)).status_code == 409
        assert (await tool.forward_input(selected, {"kind": "key", "key": "Enter"}, agent_id="captain"))["forwarded"] is False
        viewer = tool.stream_frames(selected)
        try:
            with pytest.raises(BrowserLifecycleConflict):
                await anext(viewer)
        finally:
            await viewer.aclose()
        assert tool.active_viewers == 0
        opening.cancel()
        await asyncio.sleep(0)
        assert not opening.done()
        assert drivers[0].stop_count == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(opening, 2)
        assert tool.session_count == 0
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ENDED
        assert len(drivers) == 1
        browser = drivers[0].chromium.browser
        assert drivers[0].stop_count == browser.disconnect_count == 1
        assert browser.contexts[0].close_count == (0 if bridge else 1)
        assert browser.contexts[0].pages[0].close_count == (0 if bridge else 1)
        assert not any(kind in (EventType.BROWSER_SESSION_OPENED, EventType.BROWSER_BRIDGE_CONNECTED) for kind, _ in events)
        assert sum(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events) == 1
        if not bridge:
            recording_events = [kind for kind, _ in events if kind in (
                EventType.BROWSER_RECORDING_STARTED, EventType.BROWSER_RECORDING_STOPPED,
            )]
            assert recording_events == [EventType.BROWSER_RECORDING_STARTED, EventType.BROWSER_RECORDING_STOPPED]
        stale = await tool.invoke({"action": "screenshot"}, {"browser_session_id": selected})
        assert stale.error == "session_not_active"
        assert len(drivers) == 1
    finally:
        release.set()
        await asyncio.gather(opening, return_exceptions=True)
        await tool.stop()
        await host.aclose()


@pytest.mark.asyncio
async def test_dispatch_approval_uses_bound_identity_and_blocks_only_selected_session(
    wired_browser_runtime: Any,
) -> None:
    from probos.cognitive.agentic_dispatch import DispatchToolExecutor

    runtime, drivers, _ = wired_browser_runtime
    tool = runtime.browser_tool
    selected = await _bridge(tool)
    other = await _bridge(tool)
    runtime.config.approval_inbox.enabled = True
    executor = DispatchToolExecutor(registry=runtime.tool_registry)
    executor.arm_approval_inbox(
        request_store=runtime.capability_request_store, approval_store=None,
        config=runtime.config.approval_inbox,
    )
    params = {"action": "eval_js", "expression": "1"}
    result = await executor.invoke("crew-one", "browser", params, context={"browser_session_id": selected})
    assert result.error is not None and "filed for review" in result.error
    assert "session_id" not in params
    pending = await runtime.capability_request_store.list_pending()
    assert len(pending) == 1
    assert pending[0].payload["session_id"] == selected
    assert pending[0].payload["params"]["session_id"] == selected
    metadata = {row.session_id: row for row in await tool.list_session_metadata()}
    assert metadata[selected].pending_work == 1
    assert metadata[other].pending_work == 0
    assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).reason == "pending_or_unknown_work"
    assert (await tool.hand_to_crew(selected, actor=_ACTOR, confirm=True)).status_code == 409
    assert (await tool.end_session(other, actor=_ACTOR, confirm=True)).status_code == 200
    assert drivers[0].stop_count == 0
    await runtime.capability_request_store.decide(pending[0].id, False)
    assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_parked_context_identity_does_not_transfer_to_fresh_own_session(
    wired_browser_runtime: Any, monkeypatch: pytest.MonkeyPatch,
    browser_clock: SimpleNamespace, explicit: bool,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    tool = runtime.browser_tool
    store = runtime.capability_request_store
    opened = await tool.invoke(
        {"action": "goto", "url": "https://selected.example/original"},
        {"agent_id": "crew-one"},
    )
    assert opened.error is None
    selected = opened.metadata["session_id"]
    session = tool.get_session(selected)
    assert isinstance(session, BrowserSession) and not session.is_expired()
    browser_clock.now += 10
    other = await _bridge(tool)
    request = await _park_lifecycle_approval(
        runtime, monkeypatch, other if explicit else selected,
        explicit_session_id=selected if explicit else None,
    )
    before_request = asdict(request)
    assert request.payload["session_id"] == selected
    assert request.payload["params"]["session_id"] == selected
    browser_clock.now = session.expires_at + 1
    assert session.is_expired() and not tool.get_session(other).is_expired()
    assert await tool.reap_expired() == 0
    fresh = await tool.invoke(
        {"action": "goto", "url": "https://fresh.example/document"},
        {"agent_id": "crew-one"},
    )
    assert fresh.error is None
    fresh_id = fresh.metadata["session_id"]
    assert fresh_id not in (selected, other)
    assert len(drivers) == 3
    assert tool.get_session(selected) is session
    assert session.last_url == "https://selected.example/original"
    old_browser = drivers[0].chromium.browser
    old_context = old_browser.contexts[0]
    assert drivers[0].stop_count == old_browser.disconnect_count == 0
    assert old_context.close_count == old_context.pages[0].close_count == 0
    metadata = {row.session_id: row for row in await tool.list_session_metadata()}
    assert metadata[selected].pending_work == 1
    assert metadata[other].pending_work == metadata[fresh_id].pending_work == 0
    assert asdict(await store.get(request.id)) == before_request
    assert await store.list_pending() == [request]
    stale = await tool.invoke(
        {"action": "state"}, {"agent_id": "crew-one", "browser_session_id": selected},
    )
    assert stale.error == "session_expired"
    assert stale.metadata["session_id"] == selected
    assert asdict(await store.get(request.id)) == before_request
    continued = await tool.invoke({"action": "state"}, {"agent_id": "crew-one"})
    assert continued.error is None and continued.metadata["session_id"] == fresh_id
    assert len(drivers) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch", [False, True])
@pytest.mark.parametrize("unavailable", ["expired", "ended"])
@pytest.mark.parametrize("explicit", [False, True])
async def test_supplied_unavailable_context_is_identity_fenced_with_explicit_precedence(
    wired_browser_runtime: Any, browser_clock: SimpleNamespace,
    browser_invocations: list[tuple[dict[str, Any], dict[str, Any], ToolResult]],
    dispatch: bool, unavailable: str, explicit: bool,
) -> None:
    from probos.cognitive.agentic_dispatch import DispatchToolExecutor

    runtime, drivers, _ = wired_browser_runtime
    tool = runtime.browser_tool
    selected = await _bridge(tool)
    session = tool.get_session(selected)
    assert isinstance(session, BrowserSession) and not session.is_expired()
    browser_clock.now += 10
    own = await tool.invoke(
        {"action": "goto", "url": "https://own.example/untouched"}, {"agent_id": "crew-one"},
    )
    assert own.error is None
    own_id = own.metadata["session_id"]
    if unavailable == "expired":
        browser_clock.now = session.expires_at + 1
        assert session.is_expired()
    else:
        assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ENDED
    assert not tool.get_session(own_id).is_expired()
    params = {"action": "goto", "url": "https://requested.example/document"}
    if explicit:
        params["session_id"] = own_id
    original_params = dict(params)
    context = {"agent_id": "crew-one", "browser_session_id": selected}
    browser_invocations.clear()
    if dispatch:
        result = await DispatchToolExecutor(registry=runtime.tool_registry).invoke(
            "crew-one", "browser", params, context=context,
            agent_department="medical", agent_rank="commander",
        )
    else:
        result = await tool.invoke(params, context)
    assert params == original_params
    assert context == {"agent_id": "crew-one", "browser_session_id": selected}
    assert len(browser_invocations) == 1
    actual_params, actual_context, actual_result = browser_invocations[0]
    assert actual_result is result
    assert actual_context["browser_session_id"] == selected
    if explicit:
        assert actual_params["session_id"] == own_id
        assert result.error is None
        assert result.metadata["session_id"] == own_id
        assert tool.get_session(own_id).last_url == "https://requested.example/document"
    else:
        if dispatch:
            assert actual_params["session_id"] == selected
        else:
            assert "session_id" not in actual_params
        assert result.error == ("session_expired" if unavailable == "expired" else "session_not_active")
        assert result.metadata["session_id"] == selected
        assert tool.get_session(own_id).last_url == "https://own.example/untouched"
    assert len(drivers) == 2
    assert drivers[1].stop_count == 0
    assert session.last_url == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raises", "malformed", "unbound"])
async def test_pending_reader_unknown_never_becomes_zero_or_allows_teardown(
    wired_browser_runtime: Any, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    from probos.capability_request import CapabilityRequest

    runtime, drivers, _ = wired_browser_runtime
    selected = await _bridge(runtime.browser_tool)

    async def unreadable_pending() -> list[Any]:
        if failure == "raises":
            raise RuntimeError("request store unavailable")
        if failure == "malformed":
            return [CapabilityRequest(kind="action", payload={})]
        return [CapabilityRequest(kind="action", payload={
            "tool_id": "browser", "action": "click", "params": {},
            "scope_key": "example.com", "session_id": None, "thread_id": "",
        })]

    with monkeypatch.context() as patch:
        patch.setattr(runtime.capability_request_store, "list_pending", unreadable_pending)
        rows = await runtime.browser_tool.list_session_metadata()
        assert rows[0].pending_work is None
        for action in (runtime.browser_tool.end_session, runtime.browser_tool.hand_to_crew):
            result = await action(selected, actor=_ACTOR, confirm=True)
            assert result.status_code == 409
            assert result.session.pending_work is None
        assert drivers[0].stop_count == 0
    assert (await runtime.browser_tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200


@pytest.mark.asyncio
async def test_end_rechecks_reservations_after_awaited_pending_read(
    wired_browser_runtime: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    tool = runtime.browser_tool
    selected = await _bridge(tool)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = runtime.capability_request_store.list_pending

    async def gated_pending() -> list[Any]:
        entered.set()
        await release.wait()
        return await original()

    with monkeypatch.context() as patch:
        patch.setattr(runtime.capability_request_store, "list_pending", gated_pending)
        ending = asyncio.create_task(tool.end_session(selected, actor=_ACTOR, confirm=True))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert tool.session_snapshot(selected).state is BrowserLifecycleState.ACTIVE
            async with tool.reserve_use(selected):
                release.set()
                result = await asyncio.wait_for(ending, 2)
                assert result.status_code == 409
                assert result.session.pending_work == 1
                assert drivers[0].stop_count == 0
        finally:
            release.set()
            await asyncio.gather(ending, return_exceptions=True)
    assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200


@pytest.mark.asyncio
async def test_end_cancellation_during_pending_read_never_admits_teardown(
    wired_browser_runtime: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    selected = await _bridge(runtime.browser_tool)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def gated_pending() -> list[Any]:
        entered.set()
        await release.wait()
        return []

    with monkeypatch.context() as patch:
        patch.setattr(runtime.capability_request_store, "list_pending", gated_pending)
        ending = asyncio.create_task(runtime.browser_tool.end_session(selected, actor=_ACTOR, confirm=True))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            ending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await ending
            assert runtime.browser_tool.session_snapshot(selected).state is BrowserLifecycleState.ACTIVE
            assert drivers[0].stop_count == 0
        finally:
            release.set()
            await asyncio.gather(ending, return_exceptions=True)


@pytest.mark.asyncio
async def test_stream_admission_rejects_unknown_identity_and_forged_release(lifecycle_tool: Any) -> None:
    from probos.tools.browser.lifecycle import BrowserStream

    tool, _, _ = lifecycle_tool
    selected = await _bridge(tool)
    try:
        with pytest.raises(BrowserLifecycleConflict, match="session_not_found"):
            await tool.admit_stream("missing")
        stream = await tool.admit_stream(selected)
        assert tool.active_viewers == 1
        tool.release_stream(BrowserStream(stream.viewer_id, stream.session_id))
        assert tool.active_viewers == 1
        tool.release_stream(stream)
        tool.release_stream(stream)
        assert tool.active_viewers == 0
        assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200
        with pytest.raises(BrowserLifecycleConflict, match="session_not_active"):
            await tool.admit_stream(selected)
    finally:
        await tool.stop()


@pytest.mark.parametrize("owner", [None, SimpleNamespace(), SimpleNamespace(id="other", agent_type="counselor"), SimpleNamespace(id="crew-one", agent_type=42)])
def test_startup_ownership_adapter_rejects_missing_or_malformed_registry_owner(owner: Any) -> None:
    from probos.startup.finalize import BrowserLifecycleAdapter

    registry = _CrewRegistry()
    registry.agents["crew-one"] = owner
    policy = BrowserLifecycleAdapter(
        registry=registry, request_store=None, authority_basis=BrowserAuthorityBasis.SHARED_CREW_SCOPE,
        approval_tracking_required=False, crew_check=lambda agent: True,
    )
    assert policy.is_known_crew_owner("crew-one") is False
    assert policy.is_known_crew_owner("") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("required,expected", [(False, 0), (True, None)])
async def test_startup_pending_adapter_missing_required_store_is_unknown(required: bool, expected: int | None) -> None:
    from probos.startup.finalize import BrowserLifecycleAdapter

    policy = BrowserLifecycleAdapter(
        registry=None, request_store=None, authority_basis=BrowserAuthorityBasis.SHARED_CREW_SCOPE,
        approval_tracking_required=required, crew_check=lambda agent: False,
    )
    assert await policy.read_pending_browser_work("session") == expected
    assert policy.is_known_crew_owner("crew-one") is False
    assert policy.allows(_ACTOR) is True
    assert policy.allows(BrowserActor(BrowserAuthorityBasis.SINGLE_OPERATOR_COMPATIBILITY)) is False


@pytest.mark.asyncio
async def test_end_rechecks_owner_after_awaited_pending_read(
    wired_browser_runtime: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    selected = await _bridge(runtime.browser_tool, "crew-one")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def gated_pending() -> list[Any]:
        entered.set()
        await release.wait()
        return []

    with monkeypatch.context() as patch:
        patch.setattr(runtime.capability_request_store, "list_pending", gated_pending)
        ending = asyncio.create_task(runtime.browser_tool.end_session(selected, actor=_ACTOR, confirm=True))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            runtime.registry.agents.pop("crew-one")
            release.set()
            assert (await ending).reason == "unknown_ownership"
            assert drivers[0].stop_count == 0
        finally:
            release.set()
            await asyncio.gather(ending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle_tool", [0], indirect=True)
@pytest.mark.parametrize("racer", ["expiry", "shutdown"])
async def test_end_racing_expiry_or_shutdown_closes_resources_and_recording_once(
    lifecycle_tool: Any, racer: str,
) -> None:
    tool, drivers, events = lifecycle_tool
    result = await tool.invoke({"action": "goto", "url": "https://example.com/"}, {"agent_id": "captain"})
    assert result.error is None
    selected = result.metadata["session_id"]
    assert tool.get_session(selected).is_expired()
    assert tool.get_session(selected).recording_state == "recording"
    ending = asyncio.create_task(tool.end_session(selected, actor=_ACTOR, confirm=True))
    racing = asyncio.create_task(tool.reap_expired() if racer == "expiry" else tool.stop())
    try:
        ended, _ = await asyncio.gather(ending, racing)
        assert ended.status_code == 200
        assert drivers[0].stop_count == 1
        assert drivers[0].chromium.browser.contexts[0].close_count == 1
        assert sum(kind == EventType.BROWSER_SESSION_CLOSED for kind, _ in events) == 1
        assert sum(kind == EventType.BROWSER_RECORDING_STOPPED for kind, _ in events) == 1
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.ENDED
    finally:
        await asyncio.gather(ending, racing, return_exceptions=True)
        await tool.stop()