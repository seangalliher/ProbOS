"""BF-695: Playwright runs on a subprocess-capable loop, reached through a proxy.

The suite itself runs on a subprocess-capable loop, so the capability predicate
reports "capable" and every other browser test takes the passthrough path
unchanged — which is the evidence that the boundary is transparent. It also
means the host path is never exercised by accident, so the tests here force it
explicitly by stubbing the predicate.

No real Chromium and no network: the Playwright driver is replaced by fakes
whose every call records which event loop it ran on.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import threading
import traceback
from typing import Any

import pytest

from probos.config import BrowserToolConfig
from probos.tools.browser import session as session_mod
from probos.tools.browser.actions import dispatch_action
from probos.tools.browser.loop_host import (
    PlaywrightLoopHost,
    PlaywrightProxyError,
    _new_subprocess_capable_loop,
    loop_supports_subprocess,
    wrap_host_object,
)
from probos.tools.browser.session import BrowserSession

_HOST_THREAD_NAME = "probos-playwright-host"


# ---------------------------------------------------------------------------
# Section 1: the capability predicate
# ---------------------------------------------------------------------------


def test_predicate_accepts_a_subprocess_capable_loop() -> None:
    loop = _new_subprocess_capable_loop()
    try:
        assert loop_supports_subprocess(loop) is True
    finally:
        loop.close()


def test_predicate_accepts_the_loop_this_suite_runs_on() -> None:
    # The whole "existing suites stay green unchanged" claim rests on this.
    loop = asyncio.new_event_loop()
    try:
        assert loop_supports_subprocess(loop) is True
    finally:
        loop.close()


def test_predicate_rejects_a_loop_that_inherits_the_base_transport() -> None:
    class _Incapable(asyncio.BaseEventLoop):
        """Inherits BaseEventLoop._make_subprocess_transport, which raises."""

    # The predicate only reads the type, so no loop machinery is needed.
    # ``_closed`` is set purely so BaseEventLoop.__del__ stays quiet on GC.
    loop = _Incapable.__new__(_Incapable)
    loop._closed = True  # noqa: SLF001 - suppress __del__ on an uninitialised loop
    assert loop_supports_subprocess(loop) is False


def test_predicate_rejects_the_windows_selector_loop() -> None:
    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_cls is None:
        pytest.skip("WindowsSelectorEventLoopPolicy exists only on Windows")
    loop = policy_cls().new_event_loop()
    try:
        assert loop_supports_subprocess(loop) is False
    finally:
        loop.close()


def test_predicate_rejects_an_object_with_no_transport_hook() -> None:
    class _NotALoop:
        pass

    assert loop_supports_subprocess(_NotALoop()) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Section 2: the host loop
# ---------------------------------------------------------------------------


async def test_run_executes_on_a_different_loop_and_returns_the_result() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        caller_loop = asyncio.get_running_loop()

        async def _work() -> tuple[Any, int]:
            return asyncio.get_running_loop(), 42

        loop_seen, value = await host.run(_work)

        assert value == 42
        assert loop_seen is host.loop
        assert loop_seen is not caller_loop
        assert asyncio.get_running_loop() is caller_loop
    finally:
        await host.aclose()


async def test_run_creates_the_coroutine_on_the_host_thread() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        creating_thread: list[str] = []

        def _factory() -> Any:
            creating_thread.append(threading.current_thread().name)
            return _noop()

        async def _noop() -> None:
            return None

        await host.run(_factory)

        assert creating_thread == [_HOST_THREAD_NAME]
    finally:
        await host.aclose()


async def test_exception_crosses_the_boundary_with_type_and_traceback() -> None:
    class _Boom(RuntimeError):
        pass

    host = PlaywrightLoopHost()
    host.start()
    try:

        async def _work() -> None:
            raise _Boom("bf695 detonation")

        with pytest.raises(_Boom) as excinfo:
            await host.run(_work)

        assert str(excinfo.value) == "bf695 detonation"
        rendered = "".join(
            traceback.format_exception(
                type(excinfo.value), excinfo.value, excinfo.value.__traceback__,
            )
        )
        # The host-side frame survived the hop, not just the message.
        assert "_work" in rendered
    finally:
        await host.aclose()


async def test_cancelling_the_caller_cancels_host_side_work() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        started = threading.Event()
        cancelled = threading.Event()

        async def _work() -> None:
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(host.run(_work))
        loop = asyncio.get_running_loop()
        assert await loop.run_in_executor(None, started.wait, 5.0) is True

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert await loop.run_in_executor(None, cancelled.wait, 5.0) is True
    finally:
        await host.aclose()


async def test_aclose_joins_the_thread_and_a_second_aclose_is_a_noop() -> None:
    host = PlaywrightLoopHost()
    host.start()
    thread = next(
        t for t in threading.enumerate() if t.name == _HOST_THREAD_NAME and t.is_alive()
    )
    assert host.is_running is True

    await host.aclose()

    assert thread.is_alive() is False
    assert host.is_running is False
    assert host.loop is None

    # Idempotent: no raise, nothing to join.
    await host.aclose()
    assert host.is_running is False


async def test_run_after_aclose_reports_that_the_host_is_down() -> None:
    host = PlaywrightLoopHost()
    host.start()
    await host.aclose()

    async def _work() -> None:
        return None

    with pytest.raises(RuntimeError, match="not running"):
        await host.run(_work)


async def test_host_restarts_after_aclose() -> None:
    host = PlaywrightLoopHost()
    host.start()
    first_loop = host.loop
    await host.aclose()

    host.start()
    try:
        assert host.is_running is True
        assert host.loop is not first_loop

        async def _work() -> int:
            return 7

        assert await host.run(_work) == 7
    finally:
        await host.aclose()


async def test_start_is_idempotent() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        loop = host.loop
        host.start()
        assert host.loop is loop
        live = [
            t for t in threading.enumerate()
            if t.name == _HOST_THREAD_NAME and t.is_alive()
        ]
        assert len(live) == 1
    finally:
        await host.aclose()


# ---------------------------------------------------------------------------
# Section 3: fakes for the proxy
# ---------------------------------------------------------------------------


class _FakeMouse:
    def __init__(self, calls: list[tuple[str, Any]]) -> None:
        self._calls = calls

    async def click(self, x: int, y: int, button: str = "left") -> None:
        self._calls.append(("mouse.click", asyncio.get_running_loop()))

    async def move(self, x: int, y: int) -> None:
        self._calls.append(("mouse.move", asyncio.get_running_loop()))

    async def wheel(self, dx: float, dy: float) -> None:
        self._calls.append(("mouse.wheel", asyncio.get_running_loop()))


class _FakeKeyboard:
    def __init__(self, calls: list[tuple[str, Any]]) -> None:
        self._calls = calls
        self.typed: list[str] = []

    async def type(self, text: str, delay: int | None = None) -> None:
        self._calls.append(("keyboard.type", asyncio.get_running_loop()))
        self.typed.append(text)

    async def press(self, key: str) -> None:
        self._calls.append(("keyboard.press", asyncio.get_running_loop()))


class _FakeDownload:
    suggested_filename = "bf695-report.pdf"


class _FakeEventInfo:
    def __init__(self, calls: list[tuple[str, Any]]) -> None:
        self._calls = calls
        self._download = _FakeDownload()

    @property
    async def value(self) -> _FakeDownload:
        self._calls.append(("dl_info.value", asyncio.get_running_loop()))
        return self._download


class _FakeExpectDownload:
    def __init__(self, calls: list[tuple[str, Any]]) -> None:
        # Real Playwright schedules host-loop tasks during construction
        # (Waiter.reject_on_timeout -> loop.create_task), which is why the
        # proxy must defer construction rather than run it inline.
        calls.append(("expect_download.constructed", _maybe_running_loop()))
        self._calls = calls
        self._info = _FakeEventInfo(calls)

    async def __aenter__(self) -> _FakeEventInfo:
        self._calls.append(("expect_download.aenter", asyncio.get_running_loop()))
        return self._info

    async def __aexit__(self, *args: Any) -> bool:
        self._calls.append(("expect_download.aexit", asyncio.get_running_loop()))
        return False


class _FakeLocator:
    def __init__(self, selector: str, calls: list[tuple[str, Any]]) -> None:
        self.selector = selector
        self._calls = calls
        self.dragged_to: Any = None

    async def drag_to(self, target: Any) -> None:
        self._calls.append(("locator.drag_to", asyncio.get_running_loop()))
        self.dragged_to = target


class _NotReallyAwaitable:
    def __await__(self) -> Any:  # pragma: no cover - never awaited by design
        yield
        return None


class _FakePage:
    """A Page-shaped fake covering every attribute kind the proxy classifies."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.mouse = _FakeMouse(self.calls)
        self.keyboard = _FakeKeyboard(self.calls)
        self.url = "https://example.test/bf695"
        self.viewport_size = {"width": 1280, "height": 720}
        self.locators: list[_FakeLocator] = []
        self.default_timeout_set: int | None = None
        self.goto_urls: list[str] = []
        self.stray_awaitable = _NotReallyAwaitable()

    async def goto(self, url: str) -> None:
        self.calls.append(("page.goto", asyncio.get_running_loop()))
        self.goto_urls.append(url)

    async def title(self) -> str:
        self.calls.append(("page.title", asyncio.get_running_loop()))
        return "BF-695 fake page"

    async def screenshot(self, **kwargs: Any) -> bytes:
        self.calls.append(("page.screenshot", asyncio.get_running_loop()))
        return b"bf695-png-bytes"

    async def click(self, selector: str) -> None:
        self.calls.append(("page.click", asyncio.get_running_loop()))

    def expect_download(self) -> _FakeExpectDownload:
        return _FakeExpectDownload(self.calls)

    def locator(self, selector: str) -> _FakeLocator:
        loc = _FakeLocator(selector, self.calls)
        self.locators.append(loc)
        return loc

    def set_default_timeout(self, timeout_ms: int) -> None:
        # Deliberately NOT proxy-callable: the real one writes to the driver
        # transport. Reached only from start()/connect(), already host-side.
        self.default_timeout_set = timeout_ms


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.new_context_kwargs: dict[str, Any] | None = None

    async def new_page(self) -> _FakePage:
        return self._page

    async def close(self) -> None:
        return None


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.launched_on: Any = None

    async def new_context(self, **kwargs: Any) -> _FakeContext:
        return _FakeContext(self._page)

    async def close(self) -> None:
        return None


class _FakeChromium:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    async def launch(self, **kwargs: Any) -> _FakeBrowser:
        return _FakeBrowser(self._page)


class _FakePlaywright:
    def __init__(self, page: _FakePage) -> None:
        self.chromium = _FakeChromium(page)

    async def stop(self) -> None:
        return None


class _FakePlaywrightFactory:
    def __init__(self, page: _FakePage) -> None:
        self._pw = _FakePlaywright(page)

    async def start(self) -> _FakePlaywright:
        return self._pw


def _maybe_running_loop() -> Any:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _loops_for(page: _FakePage, name: str) -> list[Any]:
    return [loop for call, loop in page.calls if call == name]


def _install_fake_playwright(
    monkeypatch: pytest.MonkeyPatch, page: _FakePage,
) -> None:
    monkeypatch.setattr(
        "playwright.async_api.async_playwright",
        lambda: _FakePlaywrightFactory(page),
    )


# ---------------------------------------------------------------------------
# Section 4: proxy transitivity
# ---------------------------------------------------------------------------


async def test_async_method_runs_on_the_host_loop_and_returns_plain_data() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        page = _FakePage()
        proxy = wrap_host_object(page, host)

        title = await proxy.title()

        assert title == "BF-695 fake page"
        assert _loops_for(page, "page.title") == [host.loop]
    finally:
        await host.aclose()


async def test_sync_properties_returning_plain_data_pass_through_unwrapped() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        page = _FakePage()
        proxy = wrap_host_object(page, host)

        assert proxy.url == "https://example.test/bf695"
        assert proxy.viewport_size == {"width": 1280, "height": 720}
        assert isinstance(proxy.viewport_size, dict)
        assert await proxy.screenshot() == b"bf695-png-bytes"
    finally:
        await host.aclose()


async def test_mouse_sub_object_is_proxied_not_handed_over_raw() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        page = _FakePage()
        proxy = wrap_host_object(page, host)

        mouse = proxy.mouse
        assert mouse is not page.mouse

        await mouse.click(10, 20, button="left")
        await mouse.move(1, 2)
        await mouse.wheel(0.0, 120.0)

        assert _loops_for(page, "mouse.click") == [host.loop]
        assert _loops_for(page, "mouse.move") == [host.loop]
        assert _loops_for(page, "mouse.wheel") == [host.loop]
    finally:
        await host.aclose()


async def test_keyboard_sub_object_is_proxied_not_handed_over_raw() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        page = _FakePage()
        proxy = wrap_host_object(page, host)

        keyboard = proxy.keyboard
        assert keyboard is not page.keyboard

        await keyboard.type("hello", delay=5)
        await keyboard.press("Enter")

        assert page.keyboard.typed == ["hello"]
        assert _loops_for(page, "keyboard.type") == [host.loop]
        assert _loops_for(page, "keyboard.press") == [host.loop]
    finally:
        await host.aclose()


async def test_expect_download_is_constructed_and_entered_on_the_host_loop() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        page = _FakePage()
        proxy = wrap_host_object(page, host)

        async with proxy.expect_download() as dl_info:
            await proxy.goto("https://example.test/file")
        download = await dl_info.value

        # Construction is deferred: it happens on the host loop, not inline on
        # the caller's thread where it would schedule foreign-loop tasks.
        assert _loops_for(page, "expect_download.constructed") == [host.loop]
        assert _loops_for(page, "expect_download.aenter") == [host.loop]
        assert _loops_for(page, "expect_download.aexit") == [host.loop]
        # The yielded object and its async property are proxied too.
        assert _loops_for(page, "dl_info.value") == [host.loop]
        assert getattr(download, "suggested_filename", None) == "bf695-report.pdf"
    finally:
        await host.aclose()


async def test_pure_sync_constructor_result_is_proxied_and_arguments_unwrap() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        page = _FakePage()
        proxy = wrap_host_object(page, host)

        src = proxy.locator("#from")
        dst = proxy.locator("#to")
        assert src is not page.locators[0]

        await src.drag_to(dst)

        assert _loops_for(page, "locator.drag_to") == [host.loop]
        # Playwright must receive the real locator, never the proxy.
        assert page.locators[0].dragged_to is page.locators[1]
    finally:
        await host.aclose()


async def test_unrecognised_sync_call_raises_instead_of_leaking_the_raw_object() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        page = _FakePage()
        proxy = wrap_host_object(page, host)

        with pytest.raises(PlaywrightProxyError) as excinfo:
            proxy.set_default_timeout  # noqa: B018 - attribute access is the act

        message = str(excinfo.value)
        assert "set_default_timeout" in message
        assert "_INLINE_SYNC_CALLABLES" in message
    finally:
        await host.aclose()


async def test_already_created_awaitable_raises_instead_of_leaking() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        page = _FakePage()
        proxy = wrap_host_object(page, host)

        with pytest.raises(PlaywrightProxyError, match="stray_awaitable"):
            proxy.stray_awaitable  # noqa: B018 - attribute access is the act
    finally:
        await host.aclose()


async def test_missing_attribute_still_raises_attribute_error() -> None:
    # Several handlers branch on hasattr(page, ...); the proxy must not turn a
    # genuinely absent attribute into a hard failure.
    host = PlaywrightLoopHost()
    host.start()
    try:
        proxy = wrap_host_object(_FakePage(), host)
        assert hasattr(proxy, "list_elements") is False
        assert hasattr(proxy, "inner_text") is False
        assert hasattr(proxy, "expect_download") is True
        assert hasattr(proxy, "url") is True
        with pytest.raises(AttributeError):
            proxy.no_such_thing  # noqa: B018 - attribute access is the act
    finally:
        await host.aclose()


async def test_proxy_refuses_attribute_writes() -> None:
    host = PlaywrightLoopHost()
    host.start()
    try:
        proxy = wrap_host_object(_FakePage(), host)
        with pytest.raises(AttributeError):
            proxy.url = "https://elsewhere.test"
    finally:
        await host.aclose()


# ---------------------------------------------------------------------------
# Section 5: BrowserSession — passthrough vs host
# ---------------------------------------------------------------------------


def _config() -> BrowserToolConfig:
    return BrowserToolConfig(enabled=True)


async def test_capable_loop_starts_no_thread_and_returns_the_raw_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    _install_fake_playwright(monkeypatch, page)
    sess = BrowserSession(session_id="s-direct", agent_id="a1", config=_config())

    await sess.start()
    try:
        assert sess._host is None  # noqa: SLF001 - the decision under test
        assert sess.page is page
        assert page.default_timeout_set == _config().default_timeout_ms
        assert not [
            t for t in threading.enumerate()
            if t.name == _HOST_THREAD_NAME and t.is_alive()
        ]
        out = await dispatch_action(sess, "goto", {"url": "https://example.test/x"})
        assert out["page_title"] == "BF-695 fake page"
        assert _loops_for(page, "page.goto") == [asyncio.get_running_loop()]
    finally:
        await sess.stop()


async def test_incapable_loop_routes_every_page_touch_through_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlaywrightLoopHost()
    monkeypatch.setattr(session_mod, "loop_supports_subprocess", lambda loop: False)
    monkeypatch.setattr(session_mod, "get_playwright_host", lambda: host)
    page = _FakePage()
    _install_fake_playwright(monkeypatch, page)
    sess = BrowserSession(session_id="s-hosted", agent_id="a1", config=_config())

    try:
        await sess.start()
        assert sess._host is host  # noqa: SLF001 - the decision under test
        assert sess.page is not page
        assert sess.page is sess.page  # proxy is cached, not rebuilt per access

        caller_loop = asyncio.get_running_loop()

        goto = await dispatch_action(sess, "goto", {"url": "https://example.test/x"})
        assert goto["page_title"] == "BF-695 fake page"
        assert page.goto_urls == ["https://example.test/x"]

        shot = await dispatch_action(sess, "screenshot", {})
        assert shot["screenshot_b64"]

        typed = await dispatch_action(
            sess, "key_type", {"text": "bf695", "delay_ms": 5},
        )
        assert typed["typed"] == 5
        assert page.keyboard.typed == ["bf695"]

        forwarded = await sess.forward_input(
            {"kind": "click", "nx": 0.5, "ny": 0.5, "button": "left"},
        )
        assert forwarded["forwarded"] is True

        down = await dispatch_action(
            sess, "download", {"selector_or_url": "https://example.test/file"},
        )
        assert down["suggested_filename"] == "bf695-report.pdf"

        # Not one Playwright call ran on the caller's loop.
        assert page.calls, "the fake page recorded no calls"
        assert all(loop is host.loop for _call, loop in page.calls)
        assert caller_loop not in [loop for _call, loop in page.calls]
        assert asyncio.get_running_loop() is caller_loop
    finally:
        await sess.stop()
        await host.aclose()


async def test_hosted_session_stop_closes_playwright_and_emits_on_the_caller_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlaywrightLoopHost()
    monkeypatch.setattr(session_mod, "loop_supports_subprocess", lambda loop: False)
    monkeypatch.setattr(session_mod, "get_playwright_host", lambda: host)
    page = _FakePage()
    _install_fake_playwright(monkeypatch, page)
    emit_loops: list[Any] = []
    sess = BrowserSession(
        session_id="s-stop",
        agent_id="a1",
        config=BrowserToolConfig(enabled=True, recording_enabled=True),
        emit_event=lambda et, payload: emit_loops.append(_maybe_running_loop()),
    )
    try:
        await sess.start()
        await sess.stop()

        assert sess.page is None
        assert emit_loops, "no lifecycle event was emitted"
        # Events must never be raised from the Playwright host thread: the
        # runtime's bus and its listeners belong to the caller's loop.
        assert all(loop is asyncio.get_running_loop() for loop in emit_loops)

        # Idempotent.
        await sess.stop()
    finally:
        await host.aclose()


async def test_browser_tool_stop_closes_the_process_wide_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.tools.browser import loop_host as loop_host_mod
    from probos.tools.browser.tool import BrowserTool

    host = PlaywrightLoopHost()
    monkeypatch.setattr(loop_host_mod, "_HOST", host)
    host.start()
    assert host.is_running is True

    tool = BrowserTool(config=_config())
    await tool.stop()

    assert host.is_running is False


# ---------------------------------------------------------------------------
# Section 6: the Playwright touch-site enumeration
# ---------------------------------------------------------------------------

# Every attribute the browser tool reaches on a Playwright object, or on an
# object obtained from one. The proxy at ``BrowserSession.page`` covers all of
# them, so a new entry here is a new thing the proxy must classify correctly and
# a removed entry is dead surface. The two ``self._page`` entries are the only
# raw-object touches, and both sit inside the lifecycle halves that already run
# on whichever loop owns the objects.
#
# When this list changes, confirm the new touch is a kind the proxy recognises
# (async method / sub-object / async context manager / plain data) before
# updating it. A kind it does not recognise raises at runtime on Windows only.
_PLAYWRIGHT_TOUCH_SITES: tuple[str, ...] = (
    "actions.py::_action_back::page.go_back",
    "actions.py::_action_back::page.title",
    "actions.py::_action_click::hasattr(page, url)",
    "actions.py::_action_click::page.click",
    "actions.py::_action_click::page.title",
    "actions.py::_action_click::page.url",
    "actions.py::_action_download::dl_info.value",
    "actions.py::_action_download::getattr(download, suggested_filename)",
    "actions.py::_action_download::hasattr(page, expect_download)",
    "actions.py::_action_download::page.click",
    "actions.py::_action_download::page.expect_download",
    "actions.py::_action_download::page.goto",
    "actions.py::_action_drag::hasattr(page, drag_and_drop)",
    "actions.py::_action_drag::page.drag_and_drop",
    "actions.py::_action_drag::page.locator",
    "actions.py::_action_drag::src.drag_to",
    "actions.py::_action_eval_js::page.evaluate",
    "actions.py::_action_extract_text::hasattr(page, inner_text)",
    "actions.py::_action_extract_text::page.inner_text",
    "actions.py::_action_forward::page.go_forward",
    "actions.py::_action_forward::page.title",
    "actions.py::_action_goto::page.goto",
    "actions.py::_action_goto::page.title",
    "actions.py::_action_key_combo::getattr(page, keyboard)",
    "actions.py::_action_key_combo::keyboard.press",
    "actions.py::_action_key_type::getattr(page, keyboard)",
    "actions.py::_action_key_type::keyboard.type",
    "actions.py::_action_mouse_button::getattr(page, mouse)",
    "actions.py::_action_mouse_button::mouse.down",
    "actions.py::_action_mouse_button::mouse.up",
    "actions.py::_action_mouse_move::getattr(page, mouse)",
    "actions.py::_action_mouse_move::mouse.move",
    "actions.py::_action_screenshot::hasattr(page, viewport_size)",
    "actions.py::_action_screenshot::page.screenshot",
    "actions.py::_action_screenshot::page.viewport_size",
    "actions.py::_action_scroll::page.evaluate",
    "actions.py::_action_state::hasattr(page, list_elements)",
    "actions.py::_action_state::page.list_elements",
    "actions.py::_action_type::hasattr(page, fill)",
    "actions.py::_action_type::page.fill",
    "actions.py::_action_type::page.type",
    "actions.py::_action_upload_file::page.set_input_files",
    "actions.py::_action_wait::page.wait_for_selector",
    "actions.py::action_verify::page.screenshot",
    "browser_stream.py::_generate::page.screenshot",
    "compute_use.py::action_compute_use_click::getattr(page, mouse)",
    "compute_use.py::action_compute_use_click::mouse.click",
    "compute_use.py::action_compute_use_click::page.screenshot",
    "credentials.py::action_fill_credential::page.fill",
    "session.py::_connect_impl::self._page.set_default_timeout",
    "session.py::_resolve_viewport::getattr(page, viewport_size)",
    "session.py::_start_impl::self._page.set_default_timeout",
    "session.py::forward_input::getattr(page, keyboard)",
    "session.py::forward_input::getattr(page, mouse)",
    "session.py::forward_input::keyboard.press",
    "session.py::forward_input::keyboard.type",
    "session.py::forward_input::mouse.click",
    "session.py::forward_input::mouse.move",
    "session.py::forward_input::mouse.wheel",
)

_SCANNED_MODULES: tuple[str, ...] = (
    "src/probos/tools/browser/actions.py",
    "src/probos/tools/browser/compute_use.py",
    "src/probos/tools/browser/credentials.py",
    "src/probos/tools/browser/session.py",
    "src/probos/routers/browser_stream.py",
)

_PAGE_DERIVED_LOCALS = frozenset(
    {"page", "mouse", "keyboard", "src", "dst", "dl_info", "download"}
)


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def _touch_root(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name) and node.id in _PAGE_DERIVED_LOCALS:
        return node.id
    if (
        isinstance(node, ast.Attribute)
        and node.attr in ("_page", "page")
        and isinstance(node.value, ast.Name)
        and node.value.id in ("self", "session")
    ):
        return f"{node.value.id}.{node.attr}"
    return None


def _enclosing_function(tree: ast.Module, node: ast.AST) -> str:
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    line = getattr(node, "lineno", 0)
    for candidate in ast.walk(tree):
        if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = candidate.end_lineno or candidate.lineno
            if candidate.lineno <= line <= end:
                if best is None or candidate.lineno > best.lineno:
                    best = candidate
    return best.name if best is not None else "<module>"


def _scan_playwright_touch_sites() -> tuple[str, ...]:
    found: set[str] = set()
    for rel in _SCANNED_MODULES:
        path = _repo_root() / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = path.name
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                root = _touch_root(node.value)
                if root is not None and node.attr not in ("page", "_page"):
                    found.add(f"{module}::{_enclosing_function(tree, node)}::{root}.{node.attr}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("getattr", "hasattr")
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                root = _touch_root(node.args[0])
                if root is not None:
                    found.add(
                        f"{module}::{_enclosing_function(tree, node)}::"
                        f"{node.func.id}({root}, {node.args[1].value})"
                    )
    return tuple(sorted(found))


def test_playwright_touch_sites_match_the_frozen_enumeration() -> None:
    actual = _scan_playwright_touch_sites()
    added = sorted(set(actual) - set(_PLAYWRIGHT_TOUCH_SITES))
    removed = sorted(set(_PLAYWRIGHT_TOUCH_SITES) - set(actual))
    assert not added, (
        "New Playwright touch site(s) added outside the BF-695 enumeration: "
        f"{added}. Confirm the proxy classifies this attribute kind, then add "
        "it to _PLAYWRIGHT_TOUCH_SITES."
    )
    assert not removed, (
        f"Playwright touch site(s) disappeared: {removed}. Remove them from "
        "_PLAYWRIGHT_TOUCH_SITES if the deletion was intended."
    )


def test_only_the_session_lifecycle_touches_raw_playwright_objects() -> None:
    raw_sites = [
        site for site in _scan_playwright_touch_sites() if "self._page" in site
    ]
    enclosing = sorted({site.split("::")[1] for site in raw_sites})
    assert enclosing == ["_connect_impl", "_start_impl"], (
        "Only the BrowserSession lifecycle halves may use the raw page; "
        "everything else must go through the proxied ``page`` property. "
        f"Found: {raw_sites}"
    )


def test_no_module_outside_session_reaches_the_private_playwright_handles() -> None:
    offenders: list[str] = []
    for rel in _SCANNED_MODULES:
        if rel.endswith("session.py"):
            continue
        source = (_repo_root() / rel).read_text(encoding="utf-8")
        for private in ("._page", "._context", "._browser", "._playwright"):
            if private in source:
                offenders.append(f"{rel} references {private}")
    assert not offenders, (
        "Reaching a session's private Playwright handle bypasses the BF-695 "
        f"proxy entirely: {offenders}"
    )
