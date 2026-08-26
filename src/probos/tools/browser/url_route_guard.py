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

A non-GET 307/308 whose target the floor ALLOWS does not dead-end here. It
cannot be re-issued (a re-issue is a document GET, and those codes exist to
preserve method and body), so the hop is aborted -- and an escalation is
recorded naming origin, target, method and the residual, which
``BrowserTool.invoke`` files as a ``kind="action"`` capability request once it
is back on the runtime's own loop. Approving it with ``grant_standing`` issues
an ``ActionApprovalStore`` rule, and the agent's NEXT attempt is released.
Abort -> escalate -> grant -> retry, and NOT pause -> continue: a route handler
sleeping 8s under a 5s navigation timeout raises TimeoutError at 5.0s, so a
decision cannot be awaited from inside the callback (measured).

The release is ``route.fulfill(response=<the 3xx>)`` -- hand Chromium the
redirect and let it perform the hop itself. Both alternatives were measured and
both are worse:

* ``route.continue_(url=...)`` preserves method and body and is a CROSS-ORIGIN
  INJECTION. Across two real origins A -> B it committed B's document at A's
  origin: B's script ran with A's cookies and wrote A's ``localStorage``. That
  trades an SSRF for "any site you visit can 307 to an attacker and run its
  script as you", which is not a trade. Fulfilling B's *body* has the identical
  defect -- ``fulfill`` always commits at the ORIGINAL request url.
* Fulfilling the 3xx measured byte-identical to no interception at all: the
  target received the POST with its body, the document committed at the
  target's own origin, and each server saw exactly one request.

The residual is TOTAL and the approval prompt says so: Chromium follows the
rest of the chain outside interception. Measured A -> B -> C with the handler
consulted exactly once, C committed. So the chain may end somewhere the floor
would have refused, including a private address.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
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

# The shape an escalation is filed under and a standing rule is granted for.
# ``browser`` shares AD-1154's namespace so the Captain finds it where the
# tool's other asks live; the ACTION is not a browser verb, and the store
# matches all four fields exactly, so a rule for ``goto`` can never release a
# redirect and vice versa.
REDIRECT_TOOL_ID = "browser"
REDIRECT_ACTION = "follow_method_preserving_redirect"

#: How many undelivered escalations one context holds before it starts dropping
#: them. A page can refuse many hops between two tool calls; the ask is a
#: notification, not an audit log, and ``file_action_request`` dedups durably
#: anyway. Bounded so a session whose tool never drains cannot grow without end.
MAX_PENDING_ESCALATIONS = 8

#: Mirrors ``probos.capability_request._RATIONALE_MAX``, which truncates on
#: write. Restated rather than imported so this module keeps no dependency on a
#: private name; ``test_bf822_*`` pins the two equal, so a change there reddens.
_RATIONALE_MAX = 280
_RATIONALE_HOST_MAX = 60

#: Mirrors ``probos.capability_request._SCOPE_KEY_MAX``, pinned the same way. A
#: scope longer than this fails ``validate_action_payload``, so an escalation
#: carrying one would file nothing at all.
_SCOPE_KEY_MAX = 253

#: Ceiling on a sanitised url. The ``Location`` is attacker-chosen, and the
#: same string reaches a log line, a persisted payload and the Captain's
#: screen; an unbounded one is log amplification in the first and a payload
#: that fails validation in the second.
#:
#: Two long urls sharing a prefix therefore render identically. That is
#: deliberate and safe rather than a gap: the AUTHORITY always survives, since
#: the widest one this can carry is ``https://`` + ``<redacted>@`` + a 253-char
#: host + ``:65535`` = 278 characters. So the host -- the only part a grant is
#: ever scoped to -- is never the part that is cut.
_URL_MAX = 300

#: Ceiling on a refusal reason before it is logged. ``check_url_shape`` echoes
#: the offending scheme back in its message, and the scheme comes from the same
#: attacker-chosen ``Location``: review measured a 5,016-character reason from
#: one url (a normal one is 19). Bounded here rather than in ``url_guard``,
#: whose other callers have their own output discipline.
_REASON_MAX = 120

#: The half of the rationale that must never be truncated away. Anything vaguer
#: grants more than it describes: once released, NOTHING after the hop is
#: judged, so naming only the target would understate what is being consented
#: to.
REDIRECT_RESIDUAL_NOTICE = (
    "Approving lets the browser follow it natively; nothing after that hop is "
    "checked, so the chain may end anywhere the URL floor would refuse, "
    "including a private address."
)


@dataclass(frozen=True)
class RedirectEscalation:
    """One refused method-preserving hop, awaiting a filing on the main loop.

    Frozen so identical repeats collapse on ``==`` before they are recorded.
    ``origin`` and ``target`` are already log-safe: an attacker chooses the
    ``Location``, and this record is persisted AND shown to the Captain, so
    ``user:pass@`` must not survive into either.
    """

    agent_id: str
    origin: str
    target: str
    method: str
    status: int
    scope_key: str


def _log_safe(url: str) -> str:
    """Drop query, fragment AND userinfo so a log line cannot carry a secret.

    Review measured the userinfo half: a hostile ``Location`` of
    ``http://user:pass@169.254.169.254/...`` was refused correctly and then
    written to the warning below complete with its credentials. Stripping the
    query alone is not enough when the attacker chooses the whole URL.

    Bounded for the same reason: the attacker also chooses the LENGTH, and this
    string is written to a log, persisted in an approval payload and shown to
    the Captain.
    """
    try:
        parts = urlparse(url)
        netloc = parts.hostname or ""
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        if parts.username or parts.password:
            netloc = f"<redacted>@{netloc}"
        cleaned = parts._replace(
            netloc=netloc, query="", fragment="",
        ).geturl()
    except Exception:
        return "<unparseable URL>"
    if len(cleaned) > _URL_MAX:
        return cleaned[:_URL_MAX] + "...<truncated>"
    return cleaned


def _log_reason(reason: str) -> str:
    """A refusal reason bounded for a log line.

    ``check_url_shape`` echoes the offending scheme back, and the scheme comes
    from the same attacker-chosen ``Location``.
    """
    if len(reason) > _REASON_MAX:
        return reason[:_REASON_MAX] + "...<truncated>"
    return reason


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


def _scope_host(url: str) -> str:
    """The lowercased hostname a redirect grant is scoped to, or ``""``.

    Empty means *no scope can be formed*, which the caller treats as
    unappealable rather than as a wildcard. Two ways that happens, and both
    come from a string the attacker chose:

    * no hostname at all -- unreachable in practice, since ``check_url_shape``
      refuses that before a scope is ever needed, but not worth asserting;
    * a hostname past ``_SCOPE_KEY_MAX``. Review measured a 265-character host
      passing the floor and then failing ``validate_action_payload``, so the
      ask silently never existed. Truncating it would be worse than dropping
      it: two different hosts sharing a 253-character prefix would then share
      one standing rule.

    Scoped to the TARGET rather than the origin deliberately. A rule keyed on
    the origin would let that one page redirect a POST anywhere; keyed on the
    target it names the destination the Captain was actually shown.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host or len(host) > _SCOPE_KEY_MAX:
        return ""
    return host


def redirect_rationale(method: str, status: int, host: str) -> str:
    """Captain-facing text for a redirect ask, residual first-class.

    ``file_request`` truncates at ``_RATIONALE_MAX``, so the FACT is trimmed to
    fit around the residual rather than the other way round: a prompt that lost
    its last sentence would consent to something narrower than what it grants.
    """
    fact = f"A {method} was answered {status} to {host[:_RATIONALE_HOST_MAX]}."
    budget = _RATIONALE_MAX - len(REDIRECT_RESIDUAL_NOTICE) - 1
    if len(fact) > budget:
        fact = fact[:budget]
    return f"{fact} {REDIRECT_RESIDUAL_NOTICE}"


def build_redirect_ask_payload(
    record: RedirectEscalation, *, session_id: str, thread_id: str
) -> dict[str, Any]:
    """The AD-1154 six-key action payload for a refused method-preserving hop.

    ``params`` feeds the dedup key, so one page refusing the same hop twice
    files one ask; the urls are bounded because an over-long payload fails
    ``validate_action_payload`` and would file nothing at all.
    """
    return {
        "tool_id": REDIRECT_TOOL_ID,
        "action": REDIRECT_ACTION,
        "params": {
            "origin": record.origin[:_URL_MAX],
            "target": record.target[:_URL_MAX],
            "method": record.method,
            "status": record.status,
        },
        "scope_key": record.scope_key,
        "session_id": session_id or None,
        "thread_id": thread_id,
    }


def make_redirect_grant_check(
    runtime: Any, agent_id: str
) -> Callable[[str], bool] | None:
    """A zero-I/O predicate answering "may this agent follow a hop to X?".

    Returns ``None`` when nothing could ever say yes -- no runtime, no
    approval store -- so the guard holds no callable it would only ever get
    ``False`` from.

    The returned predicate is safe to call from the BF-695 Playwright host
    thread: ``is_approved_sync`` is a documented zero-I/O read over a list the
    store only ever REBINDS, never mutates in place, so a reader on another
    thread sees one whole generation or the next.

    ``standing_rules_enabled`` is read at CHECK time, not captured here, so
    turning the flag off takes effect on rules already issued rather than only
    on future ones.
    """
    if runtime is None:
        return None
    store = getattr(runtime, "action_approval_store", None)
    if store is None:
        return None

    def _granted(scope_key: str) -> bool:
        config = getattr(getattr(runtime, "config", None), "approval_inbox", None)
        if not getattr(config, "standing_rules_enabled", False):
            return False
        try:
            return bool(
                store.is_approved_sync(
                    agent_id, REDIRECT_TOOL_ID, REDIRECT_ACTION, scope_key
                )
            )
        except Exception:
            logger.warning(
                "BF-822: the standing-approval lookup for %s in scope %r "
                "raised; treating the hop as NOT approved so it is escalated "
                "rather than released",
                agent_id[:12], scope_key, exc_info=True,
            )
            return False

    return _granted


class UrlRouteGuard:
    """Judges every routed request against the ``url_guard`` floor.

    One instance per BrowserContext; it carries the redirect-chain ceiling and
    the escalations its owner has not filed yet.
    """

    def __init__(
        self,
        *,
        session_id: str,
        agent_id: str = "",
        is_granted: Callable[[str], bool] | None = None,
    ) -> None:
        self._session_id = session_id
        self._agent_id = agent_id
        self._is_granted = is_granted
        self._reissues: list[float] = []
        # Recorded from the Playwright host thread, drained from the runtime's
        # own loop -- two real threads on Windows (BF-695). A plain
        # read-then-append against a swap LOSES records: measured 39-41 gone
        # per 20,000 with the cap raised, because the duplicate scan sits
        # between reading the attribute and appending to it, and a drain landing
        # in that window returns a list the appender then writes into. The lock
        # is never held across an await, so it cannot stall either loop.
        self._escalation_lock = threading.Lock()
        self._escalations: list[RedirectEscalation] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def drain_escalations(self) -> list[RedirectEscalation]:
        """Take every recorded escalation, leaving the guard empty."""
        with self._escalation_lock:
            pending, self._escalations = self._escalations, []
        return pending

    def restore_escalations(self, records: list[RedirectEscalation]) -> None:
        """Put drained records back after a filing that did not complete.

        Re-filing anything that DID land is harmless: ``file_action_request``
        dedups durably on the same key, which is why handing everything back is
        preferable to tracking which half of an interrupted drain succeeded.
        """
        for record in records:
            self._record_escalation(record)

    def _record_escalation(self, record: RedirectEscalation) -> None:
        with self._escalation_lock:
            pending = self._escalations
            if record in pending:
                return
            if len(pending) >= MAX_PENDING_ESCALATIONS:
                over_cap = True
            else:
                pending.append(record)
                over_cap = False
        if over_cap:
            logger.warning(
                "BF-822: browser session %s already holds %d unfiled redirect "
                "escalations; dropping this one. The hop was still refused -- "
                "only the Captain-facing ask is lost.",
                self._session_id, MAX_PENDING_ESCALATIONS,
            )

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
                self._session_id, _log_safe(url), _log_reason(reason),
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
                self._session_id, _log_safe(url), _log_safe(location),
                _log_reason(reason),
            )
            await _abort(route)
            return

        # A re-issue is a document GET. For 307/308 that is not the same
        # request: those codes exist to preserve method and body, and review
        # measured a POST arriving at the destination as a GET with ``Origin``
        # dropped -- which can change what the server authorises.
        #
        # GET and HEAD are unaffected: re-issuing a GET as a GET is the same
        # request, which is why the bound is on the method rather than on the
        # status code.
        #
        # Judged BEFORE the re-issue budget, because neither outcome below is a
        # re-issue: a released hop is followed by Chromium under its own 20-hop
        # cap, and a refused one is followed by nobody. Charging the budget for
        # a hop that is then aborted would let a page starve the ceiling for
        # navigations that never happened.
        method = str(getattr(request, "method", "GET") or "GET").upper()
        if status in _METHOD_PRESERVING_REDIRECTS and method not in _REISSUABLE_METHODS:
            await self._handle_method_preserving_redirect(
                route, response, url=url, location=location,
                method=method, status=status,
            )
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

        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_reissue_document(location),
        )

    async def _handle_method_preserving_redirect(
        self,
        route: Any,
        response: Any,
        *,
        url: str,
        location: str,
        method: str,
        status: int,
    ) -> None:
        """Release a 307/308 of a non-GET under a grant, else escalate it.

        The release hands the page the 3xx UNCHANGED so Chromium performs the
        hop itself. Measured against no interception at all: same method, same
        body, and the document commits at the TARGET's origin. Rewriting the
        request instead -- ``continue_(url=...)``, or fulfilling the target's
        body -- commits the target's document inside the ORIGIN's security
        context, which is a cross-origin injection rather than a redirect.
        """
        scope_key = _scope_host(location)
        if not scope_key:
            logger.warning(
                "BF-822: browser session %s refused a %d redirect of a %s to "
                "%s and could not escalate it -- no usable grant scope can be "
                "formed from that host, so there is nothing an approval could "
                "match. The hop stays refused.",
                self._session_id, status, method, _log_safe(location),
            )
            await _abort(route)
            return

        granted = self._is_granted
        if granted is not None and granted(scope_key):
            logger.warning(
                "BF-822: browser session %s released a %d redirect of a %s to "
                "%s under a standing approval for %r. Chromium follows it "
                "natively, so the method and body survive AND nothing after "
                "this hop is judged -- the chain may end anywhere the url "
                "floor would refuse.",
                self._session_id, status, method, _log_safe(location), scope_key,
            )
            await route.fulfill(response=response)
            return

        self._record_escalation(
            RedirectEscalation(
                agent_id=self._agent_id,
                origin=_log_safe(url),
                target=_log_safe(location),
                method=method,
                status=status,
                scope_key=scope_key,
            )
        )
        logger.warning(
            "BF-822: browser session %s refused a %d redirect of a %s to %s -- "
            "the validated hop can only be re-issued as a GET, and downgrading "
            "it would drop the body and Origin the server may be authorising "
            "on. The hop was aborted and an escalation recorded; approving it "
            "releases the NEXT attempt.",
            self._session_id, status, method, _log_safe(location),
        )
        await _abort(route)


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


async def install_url_route_guard(
    context: Any,
    *,
    session_id: str,
    agent_id: str = "",
    is_granted: Callable[[str], bool] | None = None,
) -> UrlRouteGuard | None:
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
    guard = UrlRouteGuard(
        session_id=session_id, agent_id=agent_id, is_granted=is_granted
    )
    await register(ROUTE_PATTERN, guard.handle)
    return guard


async def file_redirect_escalations(
    runtime: Any,
    records: list[RedirectEscalation],
    *,
    session_id: str,
    thread_id: str,
) -> int:
    """File one ``kind="action"`` ask per refused hop. Returns how many landed.

    Called from the runtime's OWN loop, never from the route handler: the
    handler runs on the BF-695 Playwright host thread, where awaiting an
    aiosqlite store bound to the main loop would raise inside a broad ``except``
    and silently lose the ask. It also cannot wait -- a handler sleeping 8s
    under a 5s navigation timeout kills the navigation (measured).

    Never raises. The hop was already refused, so a store outage costs the
    Captain-facing notification and nothing else.
    """
    if not records:
        return 0
    store = getattr(runtime, "capability_request_store", None) if runtime else None
    if store is None:
        logger.warning(
            "BF-822: %d method-preserving redirect(s) were refused in browser "
            "session %s but no capability-request store is wired, so the "
            "Captain cannot be asked. The hops stay refused.",
            len(records), session_id,
        )
        return 0

    filed = 0
    for record in records:
        payload = build_redirect_ask_payload(
            record, session_id=session_id, thread_id=thread_id
        )
        try:
            request = await store.file_action_request(
                record.agent_id,
                payload,
                rationale=redirect_rationale(
                    record.method, record.status, record.scope_key
                ),
                work_item_id=None,
            )
        except Exception:
            logger.warning(
                "BF-822: filing the redirect escalation for %s -> %s failed; "
                "the hop stays refused and the Captain is not asked",
                record.origin, record.target, exc_info=True,
            )
            continue
        if request is None or not getattr(request, "id", ""):
            logger.warning(
                "BF-822: the redirect escalation for %s -> %s was not "
                "recorded, so no ask exists to approve",
                record.origin, record.target,
            )
            continue
        filed += 1
        logger.info(
            "BF-822: escalated a %d redirect of a %s from %s to %s as request "
            "%s (scope=%r); approving it releases the next attempt",
            record.status, record.method, record.origin, record.target,
            request.id[:12], record.scope_key,
        )
    return filed

