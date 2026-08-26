"""BF-822: apply the URL floor to every request a browser context makes.

``BrowserTool._check_domain`` judged the one URL the agent typed and nothing
after it. A page that answered ``302 Location: http://169.254.169.254/`` was
followed, and the browser is worse than ``http_fetch`` here because it also
executes script on whatever it lands on.

The interception point is the BrowserContext rather than a page, so a popup or
a tab opened later is covered by the same registration, and clicks, ``back`` /
``forward``, downloads and sub-resource loads are all judged at one place
instead of by enumerating navigation verbs.

Measured, not assumed -- Chromium follows a 3xx *outside* route interception.
``route.continue_()`` on the first hop lets the browser fetch the redirect
target without the handler ever being consulted, so an abort/continue handler
alone would leave the exact vector in the issue wide open. A navigation is
therefore fetched with ``max_redirects=0`` so the ``Location`` can be judged
before anything follows it, and an allowed hop is handed back to the page as a
fresh navigation so the *next* hop re-enters this handler too. Fulfilling the
3xx itself would hand the rest of the chain to the browser unvalidated.

This does NOT close the DNS-rebinding variant: Playwright resolves the hostname
itself, a moment after the check, so a name that resolves to a private address
still reaches the browser. That is tracked separately, and the same residual is
already stated on ``BrowserTool._check_domain``.

Nor is it installed on an AD-1052b bridge session, and that is a DECISION
rather than a gap (Captain, 2026-08-25: "it shouldn't be policed at all, it's
my own browser"). That context is the Captain's own running browser, adopted
over CDP rather than created here, and intercepting it would police their own
tabs -- including the loopback literals a developer types all day. The boundary
is ownership: this module guards contexts ProbOS created, not contexts it was
lent. Agent-driven navigation inside a bridged browser is judged only at the
url the agent supplies, exactly as it was before this module existed.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from probos.security.url_guard import check_url_shape

logger = logging.getLogger(__name__)

#: Every request in the context. Popups and sub-resources included.
ROUTE_PATTERN = "**/*"

# Chromium caps a redirect chain at 20 hops. Re-issuing a hop as a fresh
# navigation hides the chain from that cap, so a server answering a -> b -> a
# would spin forever. Restore an equivalent ceiling here.
MAX_REISSUES_PER_WINDOW = 20
REISSUE_WINDOW_SECONDS = 10.0

# 307/308 promise the destination gets the SAME method and body; 301/302/303
# permit the downgrade to GET that a re-issue performs anyway.
_METHOD_PRESERVING_REDIRECTS = frozenset({307, 308})
_REISSUABLE_METHODS = frozenset({"GET", "HEAD"})


def _log_safe(url: str) -> str:
    """Drop query, fragment AND userinfo so a log line cannot carry a secret.

    Review measured the userinfo half: a hostile ``Location`` of
    ``http://user:pass@169.254.169.254/...`` was refused correctly and then
    written to the warning below complete with its credentials. Stripping the
    query alone is not enough when the attacker chooses the whole URL.
    """
    try:
        parts = urlparse(url)
        netloc = parts.hostname or ""
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        if parts.username or parts.password:
            netloc = f"<redacted>@{netloc}"
        return parts._replace(
            netloc=netloc, query="", fragment="",
        ).geturl()
    except Exception:
        return "<unparseable URL>"


def _reissue_document(location: str) -> str:
    """A document whose only job is to navigate to ``location``.

    ``location.replace`` rather than a meta refresh for two measured reasons:
    it leaves no extra history entry, so ``back`` still skips the hop, and the
    navigation starts during parse, so ``page.goto()`` resolves on the
    destination instead of on this document.

    ``json.dumps`` alone is not enough: it leaves ``<`` untouched, so a
    ``Location`` containing ``</script>`` would close this element and run the
    rest as markup in the ORIGINAL url's origin. The angle brackets and
    ampersand are pushed to escapes so no tag can be spelled at all.
    """
    literal = (
        json.dumps(location)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return "<!doctype html><script>location.replace(" + literal + ")</script>"


class UrlRouteGuard:
    """Judges every routed request against the ``url_guard`` floor.

    One instance per BrowserContext; it carries the redirect-chain ceiling.
    """

    def __init__(self, *, session_id: str) -> None:
        self._session_id = session_id
        self._reissues: list[float] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    def refusal_reason(self, url: str) -> str | None:
        """Return the floor's reason for refusing ``url``, else ``None``.

        Deliberately the shape-only half of the floor, matching what
        ``BrowserTool._check_domain`` already enforces: resolution is a
        blocking ``getaddrinfo`` on the request path, and it reports a
        transient DNS failure as a refusal.
        """
        return check_url_shape(url)

    def _reissue_budget_exhausted(self) -> bool:
        now = time.monotonic()
        cutoff = now - REISSUE_WINDOW_SECONDS
        self._reissues = [t for t in self._reissues if t >= cutoff]
        if len(self._reissues) >= MAX_REISSUES_PER_WINDOW:
            return True
        self._reissues.append(now)
        return False

    async def handle(self, route: Any) -> None:
        """Route handler. Never raises -- a raise leaves the request hanging."""
        try:
            await self._handle(route)
        except Exception:
            logger.exception(
                "BF-822: browser session %s hit an unexpected error judging a "
                "request; aborting it rather than letting it through",
                self._session_id,
            )
            await _abort(route)

    async def _handle(self, route: Any) -> None:
        request = getattr(route, "request", None)
        url = getattr(request, "url", "") or ""

        reason = self.refusal_reason(url)
        if reason is not None:
            logger.warning(
                "BF-822: browser session %s refused %s -- %s. The request was "
                "aborted; the page sees a failed load.",
                self._session_id, _log_safe(url), reason,
            )
            await _abort(route)
            return

        if not _is_navigation(request):
            await route.continue_()
            return

        try:
            response = await route.fetch(max_redirects=0)
        except Exception as exc:
            logger.warning(
                "BF-822: browser session %s could not pre-fetch %s (%s: %s), so "
                "its redirect target cannot be judged; aborting rather than "
                "letting the browser follow an unchecked chain.",
                self._session_id, _log_safe(url), type(exc).__name__, exc,
            )
            await _abort(route)
            return

        status = int(getattr(response, "status", 0) or 0)
        location = ""
        if 300 <= status < 400:
            headers = getattr(response, "headers", None) or {}
            location = urljoin(url, headers.get("location") or "")

        if not location or location == url:
            # Not a redirect, or a 3xx with no usable Location -- hand the
            # response we already have to the page rather than fetching twice.
            await route.fulfill(response=response)
            return

        reason = self.refusal_reason(location)
        if reason is not None:
            logger.warning(
                "BF-822: browser session %s refused the redirect %s -> %s -- %s. "
                "The hop was aborted; the page sees a failed load.",
                self._session_id, _log_safe(url), _log_safe(location), reason,
            )
            await _abort(route)
            return

        if self._reissue_budget_exhausted():
            logger.warning(
                "BF-822: browser session %s exceeded %d redirects in %.0fs at "
                "%s; aborting the hop as a redirect loop.",
                self._session_id, MAX_REISSUES_PER_WINDOW,
                REISSUE_WINDOW_SECONDS, _log_safe(url),
            )
            await _abort(route)
            return

        # A re-issue is a document GET. For 307/308 that is not the same
        # request: those codes exist to preserve method and body, and review
        # measured a POST arriving at the destination as a GET with ``Origin``
        # dropped -- which can change what the server authorises. Allowing the
        # hop while silently rewriting it is the worst of the three options, so
        # a method the re-issue cannot carry fails CLOSED instead.
        #
        # GET and HEAD are unaffected: re-issuing a GET as a GET is the same
        # request, which is why the bound is on the method rather than on the
        # status code.
        method = str(getattr(request, "method", "GET") or "GET").upper()
        if status in _METHOD_PRESERVING_REDIRECTS and method not in _REISSUABLE_METHODS:
            logger.warning(
                "BF-822: browser session %s refused a %d redirect of a %s to "
                "%s -- the validated hop can only be re-issued as a GET, and "
                "downgrading it would drop the body and Origin the server may "
                "be authorising on. The hop was aborted; the page sees a "
                "failed load.",
                self._session_id, status, method, _log_safe(location),
            )
            await _abort(route)
            return

        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_reissue_document(location),
        )


def _is_navigation(request: Any) -> bool:
    probe = getattr(request, "is_navigation_request", None)
    if probe is None:
        return False
    try:
        return bool(probe())
    except Exception:
        return False


async def _abort(route: Any) -> None:
    try:
        await route.abort()
    except Exception:
        logger.debug("BF-822: route.abort() failed", exc_info=True)


async def install_url_route_guard(context: Any, *, session_id: str) -> UrlRouteGuard | None:
    """Register the floor on ``context``. Returns the guard, or None if refused.

    Returns None only when the object has no ``route`` -- a test double, or a
    Playwright too old to intercept. A real BrowserContext always has it, so
    the warning marks a browser running without the floor rather than a
    condition production is expected to reach.
    """
    register = getattr(context, "route", None)
    if register is None:
        logger.warning(
            "BF-822: browser session %s has no route() on its context, so the "
            "URL floor covers only the URL the agent supplies; navigation past "
            "it is unchecked.",
            session_id,
        )
        return None
    guard = UrlRouteGuard(session_id=session_id)
    await register(ROUTE_PATTERN, guard.handle)
    return guard
