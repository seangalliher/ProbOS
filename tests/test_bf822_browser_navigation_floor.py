"""BF-822 (#1286): navigation past the FIRST url was unvalidated.

``BrowserTool._check_domain`` judged the url the agent typed and nothing after
it, so a page answering ``302 Location: http://169.254.169.254/`` was followed.
The Captain's reproduction (``logs/probe_bf822.py``) observed exactly that: the
guard refuses the target, and the browser requested it anyway.

Honesty caveat carried over from that reproduction: its start url was bound to
``127.0.0.1``, which the guard would have refused too, so it could not tell
"the first url was allowed and the hop was not" from "nothing was checked at
all". These tests remove the ambiguity WITHOUT weakening the target. One server
is reached under two spellings:

* start  -- ``http://localhost:PORT/...``  a NAME, not an IP literal, so
  ``check_url_shape`` returns None and the tool's floor ALLOWS it. (That a name
  pointing at a private address is still reachable is the residual BF-743
  already states on ``_check_domain``; it is what makes this fixture possible.)
* target -- ``http://127.0.0.1:PORT/...``  an IP literal in a loopback range,
  which the floor REFUSES.

Both spellings hit the SAME live server, so the target is genuinely reachable
and the only reason it goes unrequested is the guard. Every test asserts that
premise before asserting the fix.

Measured while building the fix, and the reason it is not the abort/continue
handler the issue describes: Chromium follows a 3xx OUTSIDE route interception.
With a plain ``route.continue_()`` handler the redirect target was still
fetched and the handler was never consulted for it. That vector is covered here
by ``test_real_redirect_...`` and ``test_real_chained_redirect_...``, both of
which fail against an abort/continue-only handler.

NOT covered, deliberately: DNS rebinding (Playwright resolves the hostname
itself, after the check), which the issue tracks separately.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from probos.config import BrowserToolConfig
from probos.security.url_guard import check_url_shape
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.url_route_guard import (
    MAX_REISSUES_PER_WINDOW,
    ROUTE_PATTERN,
    UrlRouteGuard,
    install_url_route_guard,
)

# ---------------------------------------------------------------------------
# Fixture server: one origin, two spellings
# ---------------------------------------------------------------------------


class _Server:
    """A live server reachable as both ``localhost`` (allowed) and ``127.0.0.1``
    (refused), recording every path it is actually asked for."""

    def __init__(self) -> None:
        self.hits: list[str] = []
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _body(self, body: bytes, ctype: str = "text/html") -> None:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _redirect(self, location: str) -> None:
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                outer.hits.append(self.path)
                path = self.path
                if path == "/redirect-to-private":
                    return self._redirect(outer.private("/secret"))
                if path == "/chain-hop-1":
                    return self._redirect(outer.allowed("/chain-hop-2"))
                if path == "/chain-hop-2":
                    return self._redirect(outer.private("/secret"))
                if path == "/redirect-to-allowed":
                    return self._redirect(outer.allowed("/landing"))
                if path == "/link-to-private":
                    return self._body(
                        f'<a id="go" href="{outer.private("/secret")}">go</a>'.encode()
                    )
                if path == "/image-from-private":
                    return self._body(
                        f'<img src="{outer.private("/secret.png")}">'.encode()
                    )
                return self._body(
                    f"<html><head><title>T{path}</title></head>"
                    f"<body>{path}</body></html>".encode()
                )

            def log_message(self, *_a: Any) -> None:
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._httpd.server_port
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def allowed(self, path: str) -> str:
        """Same origin, spelled as a NAME -- the floor permits it."""
        return f"http://localhost:{self.port}{path}"

    def private(self, path: str) -> str:
        """Same origin, spelled as a loopback LITERAL -- the floor refuses it."""
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def server():
    srv = _Server()
    try:
        yield srv
    finally:
        srv.close()


def _assert_fixture_premise(srv: _Server) -> None:
    """The fixture is only meaningful if the floor splits the two spellings."""
    assert check_url_shape(srv.allowed("/x")) is None, (
        "the START url must be ALLOWED, or a passing test proves nothing about "
        "navigation past the first url"
    )
    assert check_url_shape(srv.private("/x")) == "Blocked private/reserved IP: 127.0.0.1"


# ---------------------------------------------------------------------------
# Real Chromium -- the only tests that can prove production works
# ---------------------------------------------------------------------------


def _skip_reason_if_no_chromium() -> str | None:
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        return f"playwright is not installed: {exc}"
    return None


_NO_CHROMIUM = _skip_reason_if_no_chromium()
real_browser = pytest.mark.skipif(_NO_CHROMIUM is not None, reason=_NO_CHROMIUM or "")


class _RealSession:
    """A real ``BrowserSession`` -- the production wiring, not a hand-rolled context."""

    def __init__(self) -> None:
        self._session: BrowserSession | None = None

    async def __aenter__(self) -> BrowserSession:
        session = BrowserSession(
            session_id="bf822",
            config=BrowserToolConfig(enabled=True, headless=True),
            agent_id="test-agent",
        )
        try:
            await session.start()
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"chromium binary unavailable: {type(exc).__name__}: {exc}")
        self._session = session
        return session

    async def __aexit__(self, *_exc: Any) -> None:
        if self._session is not None:
            await self._session.stop()


async def _goto(page: Any, url: str, *, timeout: float = 10000) -> None:
    """Navigate, tolerating the load failure a refusal produces."""
    try:
        await page.goto(url, timeout=timeout)
    except Exception:
        pass


@real_browser
async def test_real_redirect_to_a_private_address_is_never_requested(server) -> None:
    """The seam the issue asks for: 302 -> private, driven through a real goto.

    Asserted on what the SERVER was asked for, not on the tool's return value:
    an aborted request still surfaces on ``page.on("request")``, so that event
    cannot distinguish blocked from fetched.
    """
    _assert_fixture_premise(server)
    async with _RealSession() as session:
        await _goto(session.page, server.allowed("/redirect-to-private"))
        await asyncio.sleep(0.5)

    assert "/redirect-to-private" in server.hits, (
        "the START url was never fetched, so the test proves nothing"
    )
    assert "/secret" not in server.hits, (
        f"the browser followed a redirect to a refused address: {server.hits}"
    )


@real_browser
async def test_real_chained_redirect_through_an_allowed_host_is_never_requested(
    server,
) -> None:
    """One allowed hop then a private one -- the trivial bypass of a one-hop check."""
    _assert_fixture_premise(server)
    async with _RealSession() as session:
        await _goto(session.page, server.allowed("/chain-hop-1"))
        await asyncio.sleep(0.7)

    assert "/chain-hop-2" in server.hits, "the allowed hop must still be followed"
    assert "/secret" not in server.hits, (
        f"a chained redirect reached a refused address: {server.hits}"
    )


@real_browser
async def test_real_click_navigating_to_a_private_address_is_never_requested(
    server,
) -> None:
    _assert_fixture_premise(server)
    async with _RealSession() as session:
        page = session.page
        await _goto(page, server.allowed("/link-to-private"))
        try:
            await page.click("#go", timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(0.5)

    assert "/link-to-private" in server.hits
    assert "/secret" not in server.hits, (
        f"a click navigated to a refused address: {server.hits}"
    )


@real_browser
async def test_real_subresource_from_a_private_address_is_never_requested(
    server,
) -> None:
    _assert_fixture_premise(server)
    async with _RealSession() as session:
        await _goto(session.page, server.allowed("/image-from-private"))
        await asyncio.sleep(0.5)

    assert "/image-from-private" in server.hits
    assert "/secret.png" not in server.hits, (
        f"a sub-resource load reached a refused address: {server.hits}"
    )


@real_browser
async def test_real_back_and_forward_traverse_the_guard(server) -> None:
    """``back``/``forward`` re-request through the same interception point.

    A REFUSED url cannot be planted in history to navigate back to -- the guard
    stops it entering history in the first place, which is the stronger
    property. What is provable here is that these verbs are not a side door:
    each re-issues a request that the guard judges, so a history entry the
    floor refuses would be aborted by the same handler that aborts a goto.
    ``Cache-Control: no-store`` keeps Chromium from serving them from bfcache,
    so the re-request is observable on the server.
    """
    _assert_fixture_premise(server)
    async with _RealSession() as session:
        page = session.page
        await _goto(page, server.allowed("/first"))
        await _goto(page, server.allowed("/second"))
        server.hits.clear()
        await page.go_back(timeout=10000)
        await page.go_forward(timeout=10000)
        await asyncio.sleep(0.4)
        title = await page.title()

    assert server.hits == ["/first", "/second"], (
        f"back/forward did not re-request through the guard: {server.hits}"
    )
    assert title == "T/second"


@real_browser
async def test_real_allowed_redirect_still_lands_on_its_destination(server) -> None:
    """No-regression: the guard must not break ordinary redirect following."""
    _assert_fixture_premise(server)
    async with _RealSession() as session:
        page = session.page
        await page.goto(server.allowed("/redirect-to-allowed"), timeout=10000)
        url = page.url
        title = await page.title()

    assert "/landing" in url, f"redirect did not land on its destination: {url}"
    assert title == "T/landing"
    assert "/landing" in server.hits


@real_browser
async def test_real_ordinary_page_still_loads_and_runs_script(server) -> None:
    """No-regression: fetch+fulfill must not break a plain navigation."""
    async with _RealSession() as session:
        page = session.page
        await page.goto(server.allowed("/plain"), timeout=10000)
        text = await page.inner_text("body")

    assert text.strip() == "/plain"


# ---------------------------------------------------------------------------
# Handler boundaries -- no browser required
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status: int, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}


class _FakeRequest:
    def __init__(
        self, url: str, *, navigation: bool = True, method: str = "GET",
    ) -> None:
        self.url = url
        self.method = method
        self._navigation = navigation

    def is_navigation_request(self) -> bool:
        return self._navigation


class _FakeRoute:
    def __init__(
        self,
        url: str,
        *,
        navigation: bool = True,
        response: _FakeResponse | None = None,
        fetch_error: BaseException | None = None,
        method: str = "GET",
    ) -> None:
        self.request = _FakeRequest(url, navigation=navigation, method=method)
        self.aborted = False
        self.continued = False
        self.fulfilled: dict[str, Any] | None = None
        self._response = response
        self._fetch_error = fetch_error
        self.fetch_kwargs: dict[str, Any] | None = None

    async def abort(self) -> None:
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True

    async def fetch(self, **kwargs: Any) -> _FakeResponse:
        self.fetch_kwargs = kwargs
        if self._fetch_error is not None:
            raise self._fetch_error
        return self._response or _FakeResponse(200)

    async def fulfill(self, **kwargs: Any) -> None:
        self.fulfilled = kwargs


def _guard() -> UrlRouteGuard:
    return UrlRouteGuard(session_id="s-test")


async def test_handler_aborts_a_request_the_floor_refuses() -> None:
    route = _FakeRoute("http://169.254.169.254/latest/meta-data/")
    await _guard().handle(route)
    assert route.aborted is True
    assert route.continued is False
    assert route.fetch_kwargs is None, "a refused url must never be fetched"


async def test_handler_continues_an_allowed_subresource() -> None:
    route = _FakeRoute("http://example.com/logo.png", navigation=False)
    await _guard().handle(route)
    assert route.continued is True
    assert route.aborted is False


async def test_handler_aborts_a_refused_subresource() -> None:
    route = _FakeRoute("http://127.0.0.1:9/x.png", navigation=False)
    await _guard().handle(route)
    assert route.aborted is True
    assert route.continued is False


async def test_handler_fetches_a_navigation_without_following_redirects() -> None:
    route = _FakeRoute("http://example.com/", response=_FakeResponse(200))
    await _guard().handle(route)
    assert route.fetch_kwargs == {"max_redirects": 0}
    assert route.fulfilled == {"response": route._response}


async def test_handler_aborts_a_redirect_to_a_refused_address() -> None:
    route = _FakeRoute(
        "http://example.com/start",
        response=_FakeResponse(302, {"location": "http://169.254.169.254/"}),
    )
    await _guard().handle(route)
    assert route.aborted is True
    assert route.fulfilled is None


async def test_handler_reissues_an_allowed_redirect_as_a_fresh_navigation() -> None:
    route = _FakeRoute(
        "http://example.com/start",
        response=_FakeResponse(302, {"location": "http://example.com/landing"}),
    )
    await _guard().handle(route)
    assert route.aborted is False
    assert route.fulfilled is not None
    body = route.fulfilled["body"]
    assert "http://example.com/landing" in body
    assert "location.replace" in body


async def test_handler_resolves_a_relative_redirect_before_judging_it() -> None:
    route = _FakeRoute(
        "http://example.com/a/b",
        response=_FakeResponse(302, {"location": "/landing"}),
    )
    await _guard().handle(route)
    assert route.fulfilled is not None
    assert "http://example.com/landing" in route.fulfilled["body"]


async def test_handler_cannot_be_broken_out_of_by_a_hostile_redirect_target() -> None:
    """A ``Location`` is attacker-controlled; the re-issue document embeds it.

    ``json.dumps`` closes the JS-string escape but leaves ``<`` alone, so
    ``</script>`` in the header would end the element and run the remainder as
    markup in the ORIGINAL url's origin.
    """
    hostile = 'http://example.com/x");alert(1)//</script><img src=x onerror=alert(2)>'
    route = _FakeRoute(
        "http://example.com/start",
        response=_FakeResponse(302, {"location": hostile}),
    )
    await _guard().handle(route)
    assert route.fulfilled is not None
    body = route.fulfilled["body"]

    prefix = "<!doctype html><script>location.replace("
    suffix = ")</script>"
    assert body.startswith(prefix) and body.endswith(suffix)
    assert body.count("<script>") == 1
    assert body.count("</script>") == 1
    assert "<img" not in body

    # The payload survives intact INSIDE the literal -- escaped, not stripped.
    literal = body[len(prefix): -len(suffix)]
    assert json.loads(literal) == hostile


async def test_handler_serves_a_redirect_with_no_location_as_is() -> None:
    response = _FakeResponse(302, {})
    route = _FakeRoute("http://example.com/start", response=response)
    await _guard().handle(route)
    assert route.fulfilled == {"response": response}
    assert route.aborted is False


async def test_handler_aborts_when_the_prefetch_fails() -> None:
    """Fail closed: an unfetchable navigation's redirect target is unjudgeable."""
    route = _FakeRoute("http://example.com/", fetch_error=RuntimeError("boom"))
    await _guard().handle(route)
    assert route.aborted is True
    assert route.continued is False


async def test_handler_aborts_once_the_redirect_budget_is_spent() -> None:
    """Re-issuing hides the chain from Chromium's own 20-hop cap; restore one."""
    guard = _guard()
    for _ in range(MAX_REISSUES_PER_WINDOW):
        route = _FakeRoute(
            "http://example.com/loop",
            response=_FakeResponse(302, {"location": "http://example.com/loop2"}),
        )
        await guard.handle(route)
        assert route.fulfilled is not None

    route = _FakeRoute(
        "http://example.com/loop",
        response=_FakeResponse(302, {"location": "http://example.com/loop2"}),
    )
    await guard.handle(route)
    assert route.aborted is True
    assert route.fulfilled is None


async def test_handler_aborts_rather_than_raising_on_a_broken_route() -> None:
    class _Broken:
        request = _FakeRequest("http://example.com/")

        def __init__(self) -> None:
            self.aborted = False

        async def abort(self) -> None:
            self.aborted = True

        async def fetch(self, **_kw: Any) -> Any:
            return object()  # no .status/.headers -> handler must not escape

        async def fulfill(self, **_kw: Any) -> None:
            raise RuntimeError("fulfill exploded")

    route = _Broken()
    await UrlRouteGuard(session_id="s").handle(route)
    assert route.aborted is True


async def test_handler_treats_an_empty_url_as_refused() -> None:
    route = _FakeRoute("")
    await _guard().handle(route)
    assert route.aborted is True


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


class _FakeContext:
    def __init__(self) -> None:
        self.registered: list[Any] = []

    async def route(self, pattern: str, handler: Any) -> None:
        self.registered.append((pattern, handler))


async def test_install_registers_the_guard_for_every_request() -> None:
    context = _FakeContext()
    guard = await install_url_route_guard(context, session_id="s1")
    assert guard is not None
    assert guard.session_id == "s1"
    assert len(context.registered) == 1
    pattern, handler = context.registered[0]
    assert pattern == ROUTE_PATTERN == "**/*"
    assert handler == guard.handle


async def test_install_degrades_when_the_context_cannot_route() -> None:
    guard = await install_url_route_guard(object(), session_id="s1")
    assert guard is None


async def test_session_start_installs_the_guard_on_the_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring, asserted at the seam production uses.

    Registration happens on the CONTEXT and BEFORE the first page exists, so a
    popup opened later is covered by the same registration.
    """
    import sys
    import types

    context = _FakeContext()
    order: list[str] = []

    class _Page:
        def set_default_timeout(self, _ms: int) -> None:
            pass

    async def _new_page() -> _Page:
        order.append("new_page")
        return _Page()

    context.new_page = _new_page  # type: ignore[attr-defined]
    original_route = context.route

    async def _route(pattern: str, handler: Any) -> None:
        order.append("route")
        await original_route(pattern, handler)

    context.route = _route  # type: ignore[assignment]

    class _Browser:
        async def new_context(self, **_kw: Any) -> _FakeContext:
            return context

    class _Chromium:
        async def launch(self, **_kw: Any) -> _Browser:
            return _Browser()

    class _Playwright:
        chromium = _Chromium()

        async def stop(self) -> None:
            pass

    class _Factory:
        async def start(self) -> _Playwright:
            return _Playwright()

    module = types.ModuleType("playwright.async_api")
    module.async_playwright = lambda: _Factory()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)

    session = BrowserSession(
        session_id="wired", config=BrowserToolConfig(enabled=True), agent_id="a1"
    )
    await session.start()

    assert len(context.registered) == 1, "the context was left without the floor"
    assert context.registered[0][0] == ROUTE_PATTERN
    assert order == ["route", "new_page"], (
        f"the guard must be registered before any page exists: {order}"
    )


# ── the two adversarial-review repairs ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [307, 308])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_a_method_preserving_redirect_is_not_downgraded_to_a_get(
    status, method,
) -> None:
    """307/308 exist to preserve method and body; a re-issue cannot.

    Review measured a POST arriving at the destination as a GET with `Origin`
    dropped, which can change what the server authorises. Allowing the hop
    while silently rewriting it is worse than either alternative, so a method
    the re-issue cannot carry now fails CLOSED.
    """
    route = _FakeRoute(
        "http://localtest.me/start",
        method=method,
        response=_FakeResponse(status, {"location": "http://localtest.me/next"}),
    )

    await UrlRouteGuard(session_id="s").handle(route)

    assert route.aborted is True
    assert route.fulfilled is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [307, 308])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_a_method_preserving_redirect_of_a_get_still_travels(
    status, method,
) -> None:
    """The bound is the METHOD, not the status code.

    Re-issuing a GET as a GET is the same request, so 307/308 must not become
    a blanket refusal -- that would remove a capability to buy nothing.
    """
    route = _FakeRoute(
        "http://localtest.me/start",
        method=method,
        response=_FakeResponse(status, {"location": "http://localtest.me/next"}),
    )

    await UrlRouteGuard(session_id="s").handle(route)

    assert route.aborted is False
    assert route.fulfilled is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 303])
async def test_a_downgrading_redirect_of_a_post_still_travels(status) -> None:
    """301/302/303 already permit the GET a re-issue performs."""
    route = _FakeRoute(
        "http://localtest.me/start",
        method="POST",
        response=_FakeResponse(status, {"location": "http://localtest.me/next"}),
    )

    await UrlRouteGuard(session_id="s").handle(route)

    assert route.aborted is False
    assert route.fulfilled is not None


@pytest.mark.asyncio
async def test_a_refused_method_preserving_redirect_is_refused_for_that_reason(
) -> None:
    """The address check comes first: a refused target is refused as a target.

    Otherwise the log would blame the method for a hop that was never allowed
    to happen, and the operator would chase the wrong repair.
    """
    route = _FakeRoute(
        "http://localtest.me/start",
        method="POST",
        response=_FakeResponse(307, {"location": "http://127.0.0.1/secret"}),
    )

    await UrlRouteGuard(session_id="s").handle(route)

    assert route.aborted is True


def test_a_refusal_log_cannot_carry_credentials() -> None:
    """Review measured `user:pass@` reaching the warning intact.

    The attacker chooses the whole `Location`, so stripping the query alone is
    not enough -- userinfo is the half that was left.
    """
    from probos.tools.browser.url_route_guard import _log_safe

    safe = _log_safe(
        "http://user:pass@169.254.169.254/latest/meta-data?token=abc#frag"
    )

    assert "pass" not in safe
    assert "user" not in safe
    assert "token" not in safe
    assert "abc" not in safe
    # Still identifies WHERE, or the log stops being actionable.
    assert "169.254.169.254" in safe
    assert "/latest/meta-data" in safe


def test_a_log_safe_url_keeps_host_port_and_path() -> None:
    from probos.tools.browser.url_route_guard import _log_safe

    assert _log_safe("http://example.com:8080/a/b?q=1#f") == (
        "http://example.com:8080/a/b"
    )


def test_log_safe_never_raises_on_junk() -> None:
    from probos.tools.browser.url_route_guard import _log_safe

    for junk in ("", "not a url", "http://[", "://"):
        assert isinstance(_log_safe(junk), str)
