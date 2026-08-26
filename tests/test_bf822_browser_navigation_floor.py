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
from types import SimpleNamespace
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
        #: ``(path, body)`` for every POST, so a test can prove the BODY of a
        #: method-preserving hop survived rather than only its verb.
        self.posts: list[tuple[str, str]] = []
        #: Set by the ``peer`` fixture: a SECOND allowed origin (same hostname,
        #: different port) so a released redirect can be shown to commit at the
        #: target's own origin rather than the origin it started from.
        self.peer: _Server | None = None
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

            def _redirect(self, location: str, status: int = 302) -> None:
                self.send_response(status)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _form(self, action: str) -> None:
                self._body(
                    (
                        f'<form id="f" method="POST" action="{action}">'
                        f'<input name="k" value="v">'
                        f'<button id="go" type="submit">go</button></form>'
                    ).encode()
                )

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
                if path == "/form-307":
                    return self._form(outer.allowed("/post-307"))
                if path == "/form-chain":
                    return self._form(outer.allowed("/post-chain"))
                return self._body(
                    f"<html><head><title>T{path}</title></head>"
                    f"<body>{path}</body></html>".encode()
                )

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
                outer.hits.append(self.path)
                outer.posts.append((self.path, raw))
                peer = outer.peer
                if self.path == "/post-307" and peer is not None:
                    # 307 keeps the method and body -- the case a re-issue
                    # cannot carry and the escalation exists for.
                    return self._redirect(peer.allowed("/sink"), status=307)
                if self.path == "/post-chain" and peer is not None:
                    return self._redirect(peer.allowed("/hop"), status=307)
                if self.path == "/hop" and peer is not None:
                    return self._redirect(peer.allowed("/far"), status=307)
                return self._body(
                    f"<html><head><title>P{self.path}</title></head>"
                    f"<body>{self.path}</body></html>".encode()
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


@pytest.fixture
def paired_servers():
    """Two ALLOWED origins -- same hostname, different ports.

    Both spellings pass ``check_url_shape``, so a redirect between them is a
    hop the floor permits and the only thing that can stop it is the
    method-preserving bound. Different ports means different ORIGINS, which is
    what makes "where did the document commit" a real question.
    """
    origin, target = _Server(), _Server()
    origin.peer = target
    target.peer = origin
    try:
        yield origin, target
    finally:
        origin.close()
        target.close()


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

    def __init__(self, runtime: Any | None = None) -> None:
        self._session: BrowserSession | None = None
        self._runtime = runtime

    async def __aenter__(self) -> BrowserSession:
        session = BrowserSession(
            session_id="bf822",
            config=BrowserToolConfig(enabled=True, headless=True),
            agent_id="test-agent",
            runtime=self._runtime,
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


async def _origin_of(page: Any) -> str:
    """``location.origin``, retried once past an in-flight navigation.

    A gate under 16-way load destroyed the execution context between
    ``wait_for_load_state`` and ``evaluate``. Retrying once after the page
    settles distinguishes "the document moved under us" from "the origin is
    wrong", which is the thing the caller is actually asserting.
    """
    for attempt in (0, 1):
        try:
            return await page.evaluate("location.origin")
        except Exception:
            if attempt:
                raise
            await page.wait_for_load_state("load", timeout=8000)
    raise AssertionError("unreachable")


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


# ═══════════════════════════════════════════════════════════════════════════
# A refused method-preserving redirect ESCALATES rather than dead-ending.
#
# The Captain ruled that aborting a non-GET 307/308 whose target the floor
# allows must not be the end of it (DP-13(c): authority routes capability, it
# does not ration it). Two measured constraints shaped what "escalate" can
# mean here:
#
#   * a route handler cannot wait for a human -- sleeping 8s under a 5s
#     navigation timeout raises TimeoutError at 5.0s -- so the shape is
#     abort -> escalate -> grant -> RETRY, and the first attempt still fails;
#   * ``route.continue_(url=...)`` preserves method and body and commits the
#     target's document at the ORIGIN's origin, so it is a cross-origin
#     injection rather than a redirect. Fulfilling the 3xx UNCHANGED and
#     letting Chromium perform the hop measured byte-identical to no
#     interception at all, and that is the release used here.
# ═══════════════════════════════════════════════════════════════════════════


def _approval_runtime(*, standing_rules_enabled: bool = True) -> Any:
    """A runtime stub carrying the REAL approval store, not a mock of it.

    ``ActionApprovalStore(db_path="")`` is the store's own documented
    cache-only mode, so ``is_approved_sync`` here is the same code the dispatch
    path runs -- a mock would pin how the guard CONSUMES a verdict and nothing
    about how the store PRODUCES one.
    """
    from types import SimpleNamespace

    from probos.tools.action_approvals import ActionApprovalStore

    return SimpleNamespace(
        action_approval_store=ActionApprovalStore(db_path=""),
        capability_request_store=None,
        config=SimpleNamespace(
            approval_inbox=SimpleNamespace(
                standing_rules_enabled=standing_rules_enabled
            )
        ),
    )


async def _grant(runtime: Any, agent_id: str, scope_key: str) -> None:
    from probos.tools.browser.url_route_guard import (
        REDIRECT_ACTION,
        REDIRECT_TOOL_ID,
    )

    await runtime.action_approval_store.issue_approval(
        agent_id,
        REDIRECT_TOOL_ID,
        REDIRECT_ACTION,
        scope_key=scope_key,
        ttl_seconds=3600.0,
    )


def _assert_paired_premise(origin: _Server, target: _Server) -> None:
    """Both origins must be ALLOWED, or a refusal proves the wrong thing."""
    assert check_url_shape(origin.allowed("/x")) is None
    assert check_url_shape(target.allowed("/x")) is None
    assert origin.port != target.port, "two ports, or 'which origin' is not a question"


# ── real Chromium ────────────────────────────────────────────────


@real_browser
async def test_real_a_post_307_to_an_allowed_target_is_refused_and_escalated(
    paired_servers,
) -> None:
    """The hop stops, and something exists to approve.

    The target is ALLOWED by the floor -- the only reason it goes unrequested
    is that a re-issue would turn the POST into a GET.
    """
    origin, target = paired_servers
    _assert_paired_premise(origin, target)

    async with _RealSession() as session:
        page = session.page
        await _goto(page, origin.allowed("/form-307"))
        origin.hits.clear()
        try:
            await page.click("#go", timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(0.6)
        records = session.drain_redirect_escalations()

    assert ("/post-307", "k=v") in origin.posts, (
        f"the POST never reached the origin, so nothing was redirected: "
        f"{origin.posts}"
    )
    assert target.posts == [], (
        f"a 307 of a POST reached its target as a rewritten request: "
        f"{target.posts}"
    )
    assert len(records) == 1, f"the refused hop was not escalated: {records}"
    record = records[0]
    assert record.method == "POST"
    assert record.status == 307
    assert record.scope_key == "localhost"
    assert record.agent_id == "test-agent"
    assert "/post-307" in record.origin
    assert "/sink" in record.target


@real_browser
async def test_real_a_granted_post_307_reaches_its_target_with_the_body_intact(
    paired_servers,
) -> None:
    """The retry after approval: the hop happens, unrewritten.

    Two properties, and the second is the one that rules out every alternative
    release: the target must receive the POST *and its body*, and the document
    must commit at the TARGET's origin. ``continue_(url=...)`` satisfies the
    first and fails the second -- measured, it committed the target's document
    at the origin's origin, letting the target's script read the origin's
    storage.
    """
    origin, target = paired_servers
    _assert_paired_premise(origin, target)
    runtime = _approval_runtime()
    await _grant(runtime, "test-agent", "localhost")

    async with _RealSession(runtime=runtime) as session:
        page = session.page
        await _goto(page, origin.allowed("/form-307"))
        origin.hits.clear()
        try:
            await page.click("#go", timeout=8000)
            # Wait for the DESTINATION, not for a fixed interval. A bare sleep
            # here raced under a loaded gate: the navigation was still in
            # flight, so `page.evaluate` ran against an execution context that
            # was destroyed under it. Waiting on the thing the hop is supposed
            # to produce is both deterministic and the stronger assertion.
            await page.wait_for_url(lambda url: "/sink" in url, timeout=8000)
            await page.wait_for_load_state("load", timeout=8000)
        except Exception:
            pass
        landed_url = page.url
        committed_origin = await _origin_of(page)
        records = session.drain_redirect_escalations()

    assert ("/sink", "k=v") in target.posts, (
        f"the granted hop did not deliver the POST body to its target: "
        f"{target.posts}"
    )
    assert committed_origin == f"http://localhost:{target.port}", (
        f"the target's document committed at the wrong origin ({committed_origin} "
        f"for {landed_url}) -- that is a cross-origin injection, not a redirect"
    )
    assert records == [], "a released hop must not also be escalated"


@real_browser
async def test_real_a_released_hop_is_not_escalated_and_the_chain_is_unjudged(
    paired_servers,
) -> None:
    """CHARACTERISATION of the residual the approval prompt states.

    Once released, Chromium follows the rest of the chain outside interception.
    Measured here end to end: origin -> target/hop -> origin/far, with the
    handler judging only the first request and ``/far`` reached anyway.

    If this test starts failing because the later hops ARE judged, the residual
    has narrowed and ``REDIRECT_RESIDUAL_NOTICE`` now overstates what is being
    consented to -- correct the wording and re-point this test. Do not delete
    it: it is the only thing tying the prompt's promise to the behaviour.
    """
    origin, target = paired_servers
    _assert_paired_premise(origin, target)
    runtime = _approval_runtime()
    await _grant(runtime, "test-agent", "localhost")

    async with _RealSession(runtime=runtime) as session:
        page = session.page
        await _goto(page, origin.allowed("/form-chain"))
        origin.posts.clear()
        target.posts.clear()
        try:
            await page.click("#go", timeout=8000)
            await page.wait_for_load_state("load", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(0.5)

    assert ("/post-chain", "k=v") in origin.posts, "the chain never started"
    assert ("/hop", "k=v") in target.posts, "the released hop did not happen"
    assert ("/far", "k=v") in origin.posts, (
        f"the chain past the released hop was judged after all -- the stated "
        f"residual is now wider than reality: {origin.posts}"
    )


@real_browser
async def test_real_a_grant_for_a_different_action_does_not_release_the_hop(
    paired_servers,
) -> None:
    """A standing rule for ``browser.goto`` on the same host releases nothing.

    The four-field exact match is what keeps the redirect grant from being
    something an operator can acquire by approving an ordinary navigation.
    """
    origin, target = paired_servers
    _assert_paired_premise(origin, target)
    runtime = _approval_runtime()
    await runtime.action_approval_store.issue_approval(
        "test-agent", "browser", "goto", scope_key="localhost", ttl_seconds=3600.0,
    )

    async with _RealSession(runtime=runtime) as session:
        page = session.page
        await _goto(page, origin.allowed("/form-307"))
        try:
            await page.click("#go", timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(0.6)
        records = session.drain_redirect_escalations()

    assert target.posts == [], f"a goto rule released a redirect: {target.posts}"
    assert len(records) == 1


# ── handler boundaries ───────────────────────────────────────────


def _guard_with(granted: set[str] | None = None) -> UrlRouteGuard:
    allowed = granted or set()
    return UrlRouteGuard(
        session_id="s-test",
        agent_id="a1",
        is_granted=lambda scope: scope in allowed,
    )


def _post_307(location: str, *, url: str = "http://origin.test/start") -> _FakeRoute:
    return _FakeRoute(
        url,
        method="POST",
        response=_FakeResponse(307, {"location": location}),
    )


async def test_an_ungranted_method_preserving_hop_records_one_escalation() -> None:
    guard = _guard_with()
    route = _post_307("http://target.test/next")

    await guard.handle(route)

    assert route.aborted is True
    assert route.fulfilled is None
    records = guard.drain_escalations()
    assert len(records) == 1
    assert records[0].scope_key == "target.test"
    assert records[0].origin == "http://origin.test/start"
    assert records[0].target == "http://target.test/next"
    assert records[0].method == "POST"
    assert records[0].status == 307
    assert records[0].agent_id == "a1"


async def test_a_granted_method_preserving_hop_is_released_as_the_raw_3xx() -> None:
    """Fulfilled with the 3xx ITSELF -- not a re-issue document, not a rewrite.

    Handing the page the redirect is what lets Chromium perform the hop with
    its own method, body and origin handling. A re-issue document here would
    be the silent GET downgrade; a rewritten request would be the cross-origin
    injection.
    """
    guard = _guard_with({"target.test"})
    route = _post_307("http://target.test/next")

    await guard.handle(route)

    assert route.aborted is False
    assert route.continued is False
    assert route.fulfilled == {"response": route._response}
    assert guard.drain_escalations() == [], "a released hop must not be escalated"


async def test_the_grant_is_consulted_for_the_TARGET_host_not_the_origin() -> None:
    """A rule on the page you are leaving would let it redirect a POST anywhere."""
    guard = _guard_with({"origin.test"})
    route = _post_307("http://target.test/next")

    await guard.handle(route)

    assert route.aborted is True
    assert guard.drain_escalations()[0].scope_key == "target.test"


async def test_the_grant_scope_is_lowercased() -> None:
    guard = _guard_with()
    await guard.handle(_post_307("http://TARGET.Test/next"))
    assert guard.drain_escalations()[0].scope_key == "target.test"


async def test_an_escalation_never_carries_credentials_from_the_location() -> None:
    """The record is PERSISTED and shown to the Captain, so it needs the same
    redaction the log line got -- the attacker chooses the whole ``Location``."""
    guard = _guard_with()
    route = _post_307(
        "http://user:pass@target.test/next?token=abc#frag",
        url="http://user2:pass2@origin.test/start?q=1",
    )

    await guard.handle(route)

    record = guard.drain_escalations()[0]
    joined = f"{record.origin} {record.target}"
    for secret in ("pass", "user", "token", "abc"):
        assert secret not in joined, f"{secret!r} survived into {joined!r}"
    assert "target.test" in record.target
    assert record.scope_key == "target.test"


async def test_the_same_refused_hop_twice_records_one_escalation() -> None:
    guard = _guard_with()
    for _ in range(3):
        await guard.handle(_post_307("http://target.test/next"))
    assert len(guard.drain_escalations()) == 1


async def test_distinct_refused_hops_each_record_an_escalation() -> None:
    guard = _guard_with()
    await guard.handle(_post_307("http://target.test/a"))
    await guard.handle(_post_307("http://target.test/b"))
    assert len(guard.drain_escalations()) == 2


async def test_pending_escalations_are_bounded() -> None:
    """A page can refuse many hops between two tool calls; the ask is a
    notification, not an audit log."""
    from probos.tools.browser.url_route_guard import MAX_PENDING_ESCALATIONS

    guard = _guard_with()
    for i in range(MAX_PENDING_ESCALATIONS + 5):
        route = _post_307(f"http://target.test/{i}")
        await guard.handle(route)
        assert route.aborted is True, "the hop must be refused even when unrecorded"

    assert len(guard.drain_escalations()) == MAX_PENDING_ESCALATIONS


async def test_draining_leaves_the_guard_empty() -> None:
    guard = _guard_with()
    await guard.handle(_post_307("http://target.test/next"))
    assert len(guard.drain_escalations()) == 1
    assert guard.drain_escalations() == []


async def test_a_hop_the_floor_refuses_is_never_escalated() -> None:
    """The address check comes first, so there is nothing to approve.

    Escalating it would offer the Captain a button that grants reaching a
    link-local address -- the one thing the floor exists to refuse.
    """
    guard = _guard_with()
    route = _post_307("http://169.254.169.254/latest/meta-data/")

    await guard.handle(route)

    assert route.aborted is True
    assert guard.drain_escalations() == []


@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_a_reissuable_method_is_never_escalated(method) -> None:
    route = _FakeRoute(
        "http://origin.test/start",
        method=method,
        response=_FakeResponse(307, {"location": "http://target.test/next"}),
    )
    guard = _guard_with()

    await guard.handle(route)

    assert route.fulfilled is not None
    assert guard.drain_escalations() == []


async def test_a_method_preserving_hop_does_not_spend_the_reissue_budget() -> None:
    """Neither outcome is a re-issue, so neither may charge the ceiling.

    A released hop is followed by Chromium under its own 20-hop cap and a
    refused one is followed by nobody. Charging the budget would let one page's
    refused POSTs starve navigations that never happened.
    """
    guard = _guard_with()
    for i in range(MAX_REISSUES_PER_WINDOW + 3):
        await guard.handle(_post_307(f"http://target.test/{i}"))

    route = _FakeRoute(
        "http://origin.test/start",
        response=_FakeResponse(302, {"location": "http://target.test/landing"}),
    )
    await guard.handle(route)

    assert route.fulfilled is not None, "the re-issue budget was spent on aborts"
    assert "location.replace" in route.fulfilled["body"]


async def test_a_guard_with_no_grant_check_still_refuses_and_escalates() -> None:
    """No runtime is wired (a fixture, a bridge) -- the hop must not be released."""
    guard = UrlRouteGuard(session_id="s", agent_id="a1")
    route = _post_307("http://target.test/next")

    await guard.handle(route)

    assert route.aborted is True
    assert len(guard.drain_escalations()) == 1


# ── the grant predicate ──────────────────────────────────────────


def test_no_grant_check_exists_without_a_runtime_or_a_store() -> None:
    from types import SimpleNamespace

    from probos.tools.browser.url_route_guard import make_redirect_grant_check

    assert make_redirect_grant_check(None, "a1") is None
    assert make_redirect_grant_check(SimpleNamespace(), "a1") is None
    assert make_redirect_grant_check(
        SimpleNamespace(action_approval_store=None), "a1"
    ) is None


async def test_the_grant_check_matches_the_exact_four_field_shape() -> None:
    from probos.tools.browser.url_route_guard import make_redirect_grant_check

    runtime = _approval_runtime()
    check = make_redirect_grant_check(runtime, "a1")
    assert check is not None
    assert check("target.test") is False, "premise: nothing is granted yet"

    await _grant(runtime, "a1", "target.test")

    assert check("target.test") is True
    assert check("other.test") is False, "a rule is scoped to one host"
    assert make_redirect_grant_check(runtime, "a2")("target.test") is False


async def test_the_grant_check_reads_the_arming_flag_at_check_time() -> None:
    """Turning standing rules off must lapse rules already issued, not only
    prevent new ones."""
    from probos.tools.browser.url_route_guard import make_redirect_grant_check

    runtime = _approval_runtime()
    await _grant(runtime, "a1", "target.test")
    check = make_redirect_grant_check(runtime, "a1")
    assert check("target.test") is True, "premise: the rule is live"

    runtime.config.approval_inbox.standing_rules_enabled = False

    assert check("target.test") is False


async def test_the_grant_check_fails_closed_when_the_store_raises() -> None:
    from types import SimpleNamespace

    from probos.tools.browser.url_route_guard import make_redirect_grant_check

    class _Exploding:
        def is_approved_sync(self, *_a: Any) -> bool:
            raise RuntimeError("cache read exploded")

    runtime = SimpleNamespace(
        action_approval_store=_Exploding(),
        config=SimpleNamespace(
            approval_inbox=SimpleNamespace(standing_rules_enabled=True)
        ),
    )

    assert make_redirect_grant_check(runtime, "a1")("target.test") is False


# ── the ask payload and its Captain-facing text ──────────────────


def test_the_ask_payload_passes_the_real_validator() -> None:
    """Driven through ``validate_action_payload`` itself: a payload that fails
    it is never filed, so the escalation would silently produce no ask."""
    from probos.capability_request import validate_action_payload
    from probos.tools.browser.url_route_guard import (
        RedirectEscalation,
        build_redirect_ask_payload,
    )

    payload = build_redirect_ask_payload(
        RedirectEscalation(
            agent_id="a1",
            origin="http://origin.test/start",
            target="http://target.test/next",
            method="POST",
            status=307,
            scope_key="target.test",
        ),
        session_id="sess-1",
        thread_id="thread-1",
    )

    assert validate_action_payload(payload) is not None
    assert payload["scope_key"] == "target.test"
    assert payload["params"]["method"] == "POST"
    assert payload["params"]["status"] == 307


def test_an_oversized_url_still_produces_a_fileable_payload() -> None:
    from probos.capability_request import validate_action_payload
    from probos.tools.browser.url_route_guard import (
        RedirectEscalation,
        build_redirect_ask_payload,
    )

    huge = "http://target.test/" + ("q" * 9000)
    payload = build_redirect_ask_payload(
        RedirectEscalation(
            agent_id="a1", origin=huge, target=huge, method="POST",
            status=308, scope_key="target.test",
        ),
        session_id="s", thread_id="",
    )

    assert validate_action_payload(payload) is not None


def test_the_rationale_bound_matches_the_stores_own_truncation() -> None:
    """Restated rather than imported; pinned here so a change upstream reddens."""
    from probos.capability_request import _RATIONALE_MAX as store_max
    from probos.tools.browser.url_route_guard import _RATIONALE_MAX as ours

    assert ours == store_max


@pytest.mark.parametrize("host", ["t.test", "sub." + "x" * 240 + ".test"])
def test_the_residual_survives_truncation_whatever_the_host(host) -> None:
    """``file_request`` truncates at 280; the residual is the half that must
    never be the part that is lost.

    A prompt that lost its last sentence would name a destination and say
    nothing about the chain past it -- consenting to something narrower than
    what is actually granted.
    """
    from probos.capability_request import _RATIONALE_MAX as store_max
    from probos.tools.browser.url_route_guard import (
        REDIRECT_RESIDUAL_NOTICE,
        redirect_rationale,
    )

    text = redirect_rationale("POST", 307, host)

    assert len(text) <= store_max, f"{len(text)} chars would be truncated on write"
    assert text.endswith(REDIRECT_RESIDUAL_NOTICE)
    assert text.startswith("A POST was answered 307 to ")


def test_the_residual_names_a_private_address_as_a_possible_ending() -> None:
    """"The rest is unchecked" undersells it. The chain can end at exactly the
    class of address the floor exists to refuse, and the prompt has to say so
    or the Captain grants more than they were shown."""
    from probos.tools.browser.url_route_guard import REDIRECT_RESIDUAL_NOTICE

    lowered = REDIRECT_RESIDUAL_NOTICE.lower()
    assert "private address" in lowered
    assert "nothing after that hop is checked" in lowered


# ── filing: escalation -> ask -> approval -> grant, end to end ───


def _real_request_store(tmp_path: Any) -> Any:
    from probos.capability_request import CapabilityRequestStore

    return CapabilityRequestStore(db_path=str(tmp_path / "capreq.db"))


def _record(target: str = "http://target.test/next") -> Any:
    from probos.tools.browser.url_route_guard import RedirectEscalation

    return RedirectEscalation(
        agent_id="a1",
        origin="http://origin.test/start",
        target=target,
        method="POST",
        status=307,
        scope_key="target.test",
    )


async def test_filing_produces_a_pending_action_ask(tmp_path) -> None:
    from probos.tools.browser.url_route_guard import (
        REDIRECT_ACTION,
        REDIRECT_TOOL_ID,
        file_redirect_escalations,
    )

    store = _real_request_store(tmp_path)
    await store.start()
    try:
        runtime = SimpleNamespace(capability_request_store=store)
        filed = await file_redirect_escalations(
            runtime, [_record()], session_id="sess-1", thread_id="t-1",
        )
        pending = await store.list_pending()
    finally:
        await store.stop()

    assert filed == 1
    assert len(pending) == 1
    ask = pending[0]
    assert ask.kind == "action"
    assert ask.agent_id == "a1"
    assert ask.payload is not None
    assert ask.payload["tool_id"] == REDIRECT_TOOL_ID
    assert ask.payload["action"] == REDIRECT_ACTION
    assert ask.payload["scope_key"] == "target.test"
    assert "private address" in ask.rationale, (
        "the Captain-facing text lost the residual on the way to the store"
    )


async def test_filing_the_same_hop_twice_produces_one_ask(tmp_path) -> None:
    from probos.tools.browser.url_route_guard import file_redirect_escalations

    store = _real_request_store(tmp_path)
    await store.start()
    try:
        runtime = SimpleNamespace(capability_request_store=store)
        for _ in range(2):
            await file_redirect_escalations(
                runtime, [_record()], session_id="sess-1", thread_id="",
            )
        pending = await store.list_pending()
    finally:
        await store.stop()

    assert len(pending) == 1


async def test_filing_without_a_store_degrades_to_zero(tmp_path) -> None:
    from probos.tools.browser.url_route_guard import file_redirect_escalations

    assert await file_redirect_escalations(
        None, [_record()], session_id="s", thread_id="",
    ) == 0
    assert await file_redirect_escalations(
        SimpleNamespace(capability_request_store=None), [_record()],
        session_id="s", thread_id="",
    ) == 0


async def test_filing_survives_a_store_that_raises(tmp_path) -> None:
    from probos.tools.browser.url_route_guard import file_redirect_escalations

    class _Exploding:
        async def file_action_request(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("store is down")

    filed = await file_redirect_escalations(
        SimpleNamespace(capability_request_store=_Exploding()),
        [_record()], session_id="s", thread_id="",
    )

    assert filed == 0


async def test_approving_the_ask_grants_exactly_what_the_guard_consults(
    tmp_path,
) -> None:
    """The whole chain, through the REAL production components at every link.

    escalation -> ``file_action_request`` -> ``_maybe_issue_standing_rule``
    (the router's own approval handler) -> ``ActionApprovalStore`` -> the
    guard's predicate saying yes. Each half of this has its own tests; this is
    the one that crosses the seams, because a shape mismatch anywhere between
    them leaves the Captain approving something no guard will ever match.
    """
    from probos.api_models import CapabilityRequestDecideRequest
    from probos.routers.capability_requests import _maybe_issue_standing_rule
    from probos.tools.action_approvals import ActionApprovalStore
    from probos.tools.browser.url_route_guard import (
        file_redirect_escalations,
        make_redirect_grant_check,
    )

    request_store = _real_request_store(tmp_path)
    approval_store = ActionApprovalStore(db_path="")
    await request_store.start()
    try:
        runtime = SimpleNamespace(
            capability_request_store=request_store,
            action_approval_store=approval_store,
            config=SimpleNamespace(
                approval_inbox=SimpleNamespace(
                    standing_rules_enabled=True,
                    standing_rule_max_ttl_hours=168,
                    standing_rule_default_ttl_hours=24,
                )
            ),
        )
        check = make_redirect_grant_check(runtime, "a1")
        assert check("target.test") is False, "premise: no rule exists yet"

        await file_redirect_escalations(
            runtime, [_record()], session_id="sess-1", thread_id="",
        )
        ask = (await request_store.list_pending())[0]
        decided = await request_store.decide(ask.id, approve=True, decided_by="captain")

        rule = await _maybe_issue_standing_rule(
            runtime,
            decided,
            CapabilityRequestDecideRequest(approve=True, grant_standing=True),
        )
    finally:
        await request_store.stop()

    assert rule is not None, "approving with grant_standing issued no rule"
    assert rule["tool_id"] == "browser"
    assert rule["action"] == "follow_method_preserving_redirect"
    assert rule["scope_key"] == "target.test"
    assert check("target.test") is True, (
        "the Captain approved an ask the guard will never match"
    )
    assert check("elsewhere.test") is False


# ── the tool files what the guard recorded ───────────────────────


class _RecordingRequestStore:
    def __init__(self) -> None:
        self.filed: list[tuple[str, dict[str, Any], str]] = []

    async def file_action_request(
        self, agent_id: str, payload: dict[str, Any], *, rationale: str = "",
        work_item_id: str | None = None,
    ) -> Any:
        self.filed.append((agent_id, payload, rationale))
        return SimpleNamespace(id=f"req-{len(self.filed)}")


def _tool_with_guarded_session(store: Any, *, raise_on_action: bool) -> Any:
    """A ``BrowserTool`` whose session refuses one hop during dispatch.

    Both exits matter: a refused hop makes ``page.goto`` FAIL, so filing only
    on the success path would lose the ask in exactly the case that produces
    one.
    """
    from probos.config import BrowserToolConfig
    from probos.tools.browser.tool import BrowserTool

    runtime = SimpleNamespace(capability_request_store=store)
    tool = BrowserTool(config=BrowserToolConfig(enabled=True), runtime=runtime)

    class _Session(BrowserSession):
        async def start(self) -> None:  # type: ignore[override]
            self._route_guard = UrlRouteGuard(
                session_id=self.session_id, agent_id=self._agent_id,
            )
            self._route_guard._record_escalation(_record())

        @property
        def page(self) -> Any:
            if raise_on_action:
                raise RuntimeError("net::ERR_ABORTED")
            return SimpleNamespace()

    tool._session_factory = _Session
    return tool


@pytest.mark.parametrize("raise_on_action", [True, False])
async def test_the_tool_files_the_guards_escalations_on_both_exits(
    raise_on_action, monkeypatch,
) -> None:
    from probos.tools.browser import tool as tool_mod

    async def _dispatch(_session: Any, _action: str, _params: Any) -> Any:
        if raise_on_action:
            raise RuntimeError("net::ERR_ABORTED")
        return {"url": "http://origin.test/start"}

    monkeypatch.setattr(tool_mod, "dispatch_action", _dispatch)
    store = _RecordingRequestStore()
    tool = _tool_with_guarded_session(store, raise_on_action=raise_on_action)

    result = await tool.invoke(
        {"action": "goto", "url": "http://origin.test/start"},
        {"agent_id": "a1", "thread_id": "t-1"},
    )

    assert (result.error is not None) is raise_on_action
    assert len(store.filed) == 1, (
        f"the ask was lost on the {'failure' if raise_on_action else 'success'} "
        f"exit: {store.filed}"
    )
    agent_id, payload, rationale = store.filed[0]
    assert agent_id == "a1"
    assert payload["action"] == "follow_method_preserving_redirect"
    assert payload["thread_id"] == "t-1"
    assert "private address" in rationale


async def test_the_tool_hands_its_runtime_to_the_sessions_it_creates() -> None:
    """Without this the guard has nothing to ask about a grant, so an approved
    redirect would be refused again on every retry."""
    from probos.config import BrowserToolConfig
    from probos.tools.browser.tool import BrowserTool

    runtime = SimpleNamespace(capability_request_store=None)
    tool = BrowserTool(config=BrowserToolConfig(enabled=True), runtime=runtime)
    seen: dict[str, Any] = {}

    class _Session(BrowserSession):
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)
            super().__init__(**kwargs)

        async def start(self) -> None:  # type: ignore[override]
            pass

    tool._session_factory = _Session
    await tool._get_or_create_session(None, "a1")

    assert seen["runtime"] is runtime


# ── the three adversarial-review repairs ─────────────────────────


def test_the_handoff_between_the_two_threads_loses_nothing() -> None:
    """The guard is written from the Playwright host thread and drained from
    the runtime's loop -- two real threads on Windows (BF-695).

    An earlier read-then-append against an unlocked swap lost records: the
    duplicate scan sits between reading the attribute and appending to it, so a
    drain landing in that window hands back a list the appender then writes
    into. Measured 39-41 lost per 20,000.

    A sequential premise runs first: if THAT loses records the harness is
    broken and a concurrent loss would prove nothing. And the concurrent run
    must actually interleave -- a drainer that only runs after the producer
    finished never opens the window at all.
    """
    import threading

    from probos.tools.browser import url_route_guard as guard_mod

    def _rec(i: int) -> Any:
        return guard_mod.RedirectEscalation(
            agent_id="a1", origin=f"http://o.test/{i}",
            target=f"http://t.test/{i}", method="POST", status=307,
            scope_key="t.test",
        )

    total = 4000
    original_cap = guard_mod.MAX_PENDING_ESCALATIONS
    guard_mod.MAX_PENDING_ESCALATIONS = total * 2
    try:
        guard = UrlRouteGuard(session_id="s", agent_id="a1")
        for i in range(100):
            guard._record_escalation(_rec(i))
        assert len(guard.drain_escalations()) == 100, (
            "the sequential premise failed -- the harness is broken, not the code"
        )

        guard = UrlRouteGuard(session_id="s", agent_id="a1")
        collected: list[Any] = []
        interleavings = 0
        done = threading.Event()

        def _produce() -> None:
            for i in range(total):
                guard._record_escalation(_rec(i))
            done.set()

        def _drain() -> None:
            nonlocal interleavings
            while not done.is_set():
                got = guard.drain_escalations()
                if got:
                    interleavings += 1
                collected.extend(got)
            collected.extend(guard.drain_escalations())

        producer = threading.Thread(target=_produce)
        drainer = threading.Thread(target=_drain)
        drainer.start()
        producer.start()
        producer.join()
        drainer.join()
    finally:
        guard_mod.MAX_PENDING_ESCALATIONS = original_cap

    assert interleavings > 1, (
        f"the drainer never ran while the producer was writing "
        f"({interleavings} non-empty drains), so this proves nothing"
    )
    assert len(collected) == total, (
        f"{total - len(collected)} escalation(s) were lost across the thread "
        f"boundary; each one is a hop the Captain is never asked about"
    )


async def test_a_host_too_long_to_scope_is_refused_without_a_dangling_ask() -> None:
    """Review measured a 265-character host passing the floor and then failing
    ``validate_action_payload``, so the ask silently never existed.

    Recording it anyway would leave the tool filing nothing while the log said
    an escalation had been made. Truncating the host to fit would be worse:
    two hosts sharing a 253-character prefix would then share one rule.
    """
    from probos.capability_request import validate_action_payload
    from probos.tools.browser.url_route_guard import (
        RedirectEscalation,
        build_redirect_ask_payload,
    )

    long_host = "a" * 260 + ".test"
    assert check_url_shape(f"http://{long_host}/x") is None, (
        "premise: the floor must ALLOW this host, or it never reaches the "
        "escalation path"
    )
    # premise: it is the SCOPE that the store refuses, not something else.
    assert validate_action_payload(
        build_redirect_ask_payload(
            RedirectEscalation(
                agent_id="a1", origin="http://o.test/", target="http://t.test/",
                method="POST", status=307, scope_key=long_host,
            ),
            session_id="s", thread_id="",
        )
    ) is None

    guard = _guard_with()
    route = _post_307(f"http://{long_host}/next")

    await guard.handle(route)

    assert route.aborted is True
    assert route.fulfilled is None
    assert guard.drain_escalations() == [], (
        "an escalation was recorded that no store could ever accept"
    )


def test_an_unscopeable_host_can_never_be_released_by_a_grant() -> None:
    """The empty scope must not become a wildcard the long host slips through."""
    from probos.tools.browser.url_route_guard import _scope_host

    assert _scope_host("http://" + "a" * 260 + ".test/x") == ""
    assert _scope_host("http://ok.test/x") == "ok.test"


async def test_cancelling_the_tool_mid_filing_hands_the_escalations_back(
    monkeypatch,
) -> None:
    """Cancellation is propagated, not swallowed -- but the records must not go
    down with it.

    They have already left the guard by the time the store is awaited, so a
    cancellation there would discard exactly the escalations the call produced.
    """
    from probos.tools.browser import tool as tool_mod

    async def _dispatch(_session: Any, _action: str, _params: Any) -> Any:
        return {"url": "http://origin.test/start"}

    monkeypatch.setattr(tool_mod, "dispatch_action", _dispatch)

    class _CancellingStore:
        def __init__(self) -> None:
            self.calls = 0

        async def file_action_request(self, *_a: Any, **_kw: Any) -> Any:
            self.calls += 1
            raise asyncio.CancelledError()

    store = _CancellingStore()
    tool = _tool_with_guarded_session(store, raise_on_action=False)
    session_holder: dict[str, Any] = {}

    original = tool._session_factory

    class _Capturing(original):  # type: ignore[misc, valid-type]
        async def start(self) -> None:  # type: ignore[override]
            await super().start()
            session_holder["session"] = self

    tool._session_factory = _Capturing

    with pytest.raises(asyncio.CancelledError):
        await tool.invoke(
            {"action": "goto", "url": "http://origin.test/start"},
            {"agent_id": "a1", "thread_id": "t-1"},
        )

    assert store.calls == 1, "premise: the store was actually reached"
    session = session_holder["session"]
    assert len(session.drain_redirect_escalations()) == 1, (
        "the escalation was lost when the browser call was cancelled"
    )


async def test_an_ordinary_failure_mid_filing_also_hands_them_back(
    monkeypatch,
) -> None:
    """Round-2 review measured the first draft restoring on cancellation ONLY.

    An ordinary fault at this seam therefore discarded the asks permanently --
    the same loss class as the unlocked handoff, on a different lane. The next
    browser call must still be able to file them.
    """
    from probos.tools.browser import tool as tool_mod

    async def _dispatch(_session: Any, _action: str, _params: Any) -> Any:
        return {"url": "http://origin.test/start"}

    monkeypatch.setattr(tool_mod, "dispatch_action", _dispatch)

    calls: list[int] = []

    async def _exploding_filer(*_a: Any, **_kw: Any) -> int:
        calls.append(1)
        raise RuntimeError("the filer itself fell over")

    monkeypatch.setattr(tool_mod, "file_redirect_escalations", _exploding_filer)

    tool = _tool_with_guarded_session(_RecordingRequestStore(), raise_on_action=False)
    session_holder: dict[str, Any] = {}
    original = tool._session_factory

    class _Capturing(original):  # type: ignore[misc, valid-type]
        async def start(self) -> None:  # type: ignore[override]
            await super().start()
            session_holder["session"] = self

    tool._session_factory = _Capturing

    result = await tool.invoke(
        {"action": "goto", "url": "http://origin.test/start"},
        {"agent_id": "a1", "thread_id": "t-1"},
    )

    assert calls == [1], "premise: the filing path was actually reached"
    assert result.error is None, "a filing fault must not become the tool's answer"
    session = session_holder["session"]
    assert len(session.drain_redirect_escalations()) == 1, (
        "the escalation was lost when filing failed for an ordinary reason"
    )


def test_a_sanitised_url_is_bounded() -> None:
    """The attacker chooses the length as well as the content, and the same
    string reaches a log, a persisted payload and the Captain's screen."""
    from probos.tools.browser.url_route_guard import _URL_MAX, _log_safe

    safe = _log_safe("http://target.test/" + "q" * 9000)

    assert len(safe) <= _URL_MAX + len("...<truncated>")
    assert safe.startswith("http://target.test/")
    assert safe.endswith("...<truncated>")


def test_truncation_never_cuts_the_part_a_grant_is_scoped_to() -> None:
    """Two long urls sharing a prefix render identically, and that is safe
    ONLY because the authority always survives.

    Review raised the collision as a forensic risk and proposed appending a
    digest. Declined on this arithmetic instead: the widest authority
    ``_log_safe`` can emit is 278 characters, so the host -- the one part a
    standing rule is ever scoped to -- is never the part that is cut. A digest
    would add noise to text the Captain reads to distinguish paths that cannot
    change what is granted.
    """
    from probos.tools.browser.url_route_guard import (
        _SCOPE_KEY_MAX,
        _URL_MAX,
        _log_safe,
    )

    widest = len("https://") + len("<redacted>@") + _SCOPE_KEY_MAX + len(":65535")
    assert widest <= _URL_MAX, (
        f"an authority can now be {widest} chars against a {_URL_MAX} bound, so "
        f"truncation can hide which host was involved"
    )

    host = "h" * _SCOPE_KEY_MAX
    safe = _log_safe(f"https://user:pw@{host}:65535/" + "p" * 9000)
    assert host in safe
    assert "<redacted>@" in safe
    assert "pw" not in safe.replace("<redacted>@", "")


def test_a_refusal_reason_is_bounded_before_it_reaches_a_log() -> None:
    """``check_url_shape`` echoes the offending SCHEME back, and the scheme
    comes from the same attacker-chosen ``Location``.

    Measured: a 5,016-character reason from one url, against 19 for a normal
    refusal. Unbounded, that is log amplification on a path an attacker can
    trigger at will.
    """
    from probos.tools.browser.url_route_guard import _REASON_MAX, _log_reason

    ordinary = check_url_shape("ftp://x.test/")
    assert ordinary is not None and len(ordinary) < _REASON_MAX, (
        "premise: an ordinary refusal must fit, or the bound would truncate "
        "every real reason"
    )
    assert _log_reason(ordinary) == ordinary

    hostile = check_url_shape(("x" * 5000) + "://target.test/p")
    assert hostile is not None and len(hostile) > 5000, (
        "premise: the reason really is attacker-sized"
    )
    bounded = _log_reason(hostile)
    assert len(bounded) <= _REASON_MAX + len("...<truncated>")
    assert bounded.startswith("Blocked scheme: ")


def test_the_scope_bound_matches_the_stores_own(
) -> None:
    """Restated rather than imported; pinned so a change upstream reddens."""
    from probos.capability_request import _SCOPE_KEY_MAX as store_max
    from probos.tools.browser.url_route_guard import _SCOPE_KEY_MAX as ours

    assert ours == store_max


