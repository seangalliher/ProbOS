"""HTTP fetch agent — fetches URLs via HTTP."""

from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx

from probos.security.url_guard import validate_public_url
from probos.substrate.agent import BaseAgent
from probos.types import (
    CapabilityDescriptor,
    HandlerLatencyClass,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)

#: Exactly the set httpx's `Response.has_redirect_location` uses. 300 and 304
#: are deliberately absent: a 304 can legally carry a Location and is a cache
#: answer, not a redirect.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass
class DomainRateState:
    """Per-domain rate-limit tracking (AD-270)."""

    last_request_time: float = 0.0
    min_interval_seconds: float = 2.0
    retry_after: float | None = None
    remaining: int | None = None
    reset_time: float | None = None
    consecutive_429s: int = 0


class HttpFetchAgent(BaseAgent):
    """Concrete agent that fetches URLs via HTTP.

    Read-only: GET requests are non-destructive and don't require
    consensus.  URL safety is enforced by red team verification.

    Capabilities: http_fetch.
    """

    agent_type: str = "http_fetch"
    tier = "core"
    handler_latency_class: HandlerLatencyClass = HandlerLatencyClass.NETWORK
    default_capabilities = [
        CapabilityDescriptor(
            can="http_fetch",
            detail="Fetch a URL via HTTP and return the response",
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = [
        IntentDescriptor(name="http_fetch", params={"url": "<url>", "method": "GET"}, description="Fetch a URL", requires_consensus=False),
    ]

    _handled_intents = {"http_fetch"}

    # Security constants
    # Must be less than the DAG executor broadcast timeout (10s) so httpx
    # either completes or raises TimeoutException before asyncio.wait()
    # cancels the task.
    DEFAULT_TIMEOUT: float = 8.0
    # BF-819: what this defends and what it costs, per Design Principle 13(a).
    #
    # DEFENDS: bounded work per fetch. Redirects are now followed by hand so the
    # SSRF guard sees every hop, and a hand-rolled loop needs its own stop.
    #
    # COSTS: a chain longer than this fails rather than resolving. Five is above
    # what the paths we actually use need -- a DuckDuckGo bang is one hop, a
    # canonical-host plus http->https pairing is two -- and well under httpx's
    # own default of 20, which is sized for a browser rather than an agent.
    MAX_REDIRECTS: int = 5
    # BF-729: what this defends and what it costs, per Design Principle 13(a)
    # (a capability ceiling must be a decision, never an inheritance).
    #
    # DEFENDS: the fetched body is returned INLINE in this agent's result dict
    # and therefore crosses the intent bus as an ``IntentResult``. That is the
    # shape AD-731 exists to prevent -- the bus carries refs, the store carries
    # bytes -- after the 2026-05-11 OOM crash (#636). This cap is what keeps an
    # arbitrary remote response from becoming an arbitrary bus payload.
    #
    # COSTS: a JSON document larger than this arrives cut mid-structure, so it
    # no longer parses. Measured 2026-08-07: boto3's PyPI JSON is 3,233,027
    # bytes, and the agent could not read a version it had successfully
    # fetched (#1182).
    #
    # So do NOT raise this to widen capability -- that reintroduces #636. The
    # path for large bodies is AD-1221 (#1183), where the body never enters the
    # bus at all. Truncation is reported explicitly below so an agent can tell
    # a whole document from a prefix instead of inferring it from the size.
    MAX_BODY_BYTES: int = 1024 * 1024
    USER_AGENT: str = "ProbOS/0.1.0 (https://github.com/seangalliher/ProbOS)"

    # Only expose safe response headers
    _SAFE_HEADERS = frozenset({
        "content-type",
        "content-length",
        "server",
        "date",
        "last-modified",
        "retry-after",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-ratelimit-limit",
    })

    # Class-level shared state — all pool members share rate limit knowledge (AD-270)
    _domain_state: ClassVar[dict[str, DomainRateState]] = {}

    # BF-770: identical fetches in flight at the same moment, keyed by
    # (method, url, cap). CLASS-level, like `_domain_state`, because the
    # multiplier being fixed is across INSTANCES: `IntentBus.broadcast()`
    # invokes every subscriber, the fleet runs three HttpFetchAgents, and two
    # WebSearchAgents each broadcast -- so one Captain-visible search made six
    # outbound DuckDuckGo requests, and DDG blocks after roughly two. The rate
    # limit was self-inflicted.
    _inflight: ClassVar[dict[tuple[str, str, int], asyncio.Task]] = {}

    # How many callers are still awaiting each in-flight fetch. When the last
    # one leaves via cancellation the fetch is cancelled too: `asyncio.shield`
    # keeps one caller's exit from killing the request its peers need, but a
    # request nobody can still receive should not keep a socket or a rate slot.
    # Keyed by TASK rather than by request key: one key sees many flights, and
    # a shared counter would let a finished flight's waiters vouch for its
    # replacement.
    _waiters: ClassVar[dict[asyncio.Task, int]] = {}

    # Persistent service profile store (AD-382) — set via runtime wiring
    _profile_store: ClassVar[Any] = None

    @classmethod
    def set_profile_store(cls, store: Any) -> None:
        """Wire or disconnect the ServiceProfileStore."""
        cls._profile_store = store

    # AD-456b: Egress policy (active enforcement) — set via runtime wiring when
    # config.security_infra.egress_active_enforcement is True. Default None
    # preserves AD-456 v1 consultation-only behavior.
    _egress_policy: ClassVar[Any] = None

    @classmethod
    def set_egress_policy(cls, policy: Any) -> None:
        """Wire or disconnect the EgressPolicy for active SSRF enforcement."""
        cls._egress_policy = policy

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report."""
        import time as _time
        _start = _time.monotonic()
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

        result = await self.act(plan)
        report = await self.report(result)

        success = report.get("success", False)
        self.update_confidence(success)

        # AD-571b: record operational call outcome on the runtime tracker.
        # self._runtime can be None in sandbox per repo-notes; in production it
        # is the live runtime and operational_status_tracker is guaranteed by
        # runtime.py:304. Telemetry must never break a fetch (swallow tier).
        _rt = getattr(self, "_runtime", None)
        if _rt is not None:
            try:
                _latency_ms = (_time.monotonic() - _start) * 1000.0
                _rt.operational_status_tracker.record_call(self.id, bool(success), _latency_ms)
            except Exception:
                pass  # AD-571b: telemetry must never break a fetch.

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Check if this intent is something we handle."""
        intent_name = intent.get("intent", "")
        if intent_name not in self._handled_intents:
            return None
        return {
            "intent": intent_name,
            "params": intent.get("params", {}),
        }

    async def decide(self, observation: Any) -> Any:
        """Plan what to do based on the perceived intent."""
        params = observation["params"]
        url = params.get("url", "")
        method = params.get("method", "GET")

        if not url:
            return {"action": "error", "error": "No URL specified"}

        return {"action": "fetch", "url": url, "method": method}

    async def act(self, plan: Any) -> Any:
        """Execute the planned operation."""
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "fetch":
            return await self._fetch_url(plan["url"], plan["method"])

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result

    # BF-743: the metadata-host list lives in security.url_guard now, so the
    # browser tool enforces the same one.

    def _validate_url(self, url: str) -> str | None:
        """Validate URL is safe to fetch. Returns error message or None if safe.

        BF-743: the scheme / metadata-host / DNS / private-address checks moved
        to ``security.url_guard`` so the browser tool enforces the identical
        floor. They were here and nowhere else, which made ``browser.goto`` a
        route around them. Refusal strings are unchanged.
        """
        error = validate_public_url(url)
        if error is not None:
            return error

        # AD-456b: Egress policy consultation (active enforcement). Defense in
        # depth — runs AFTER scheme/host/private-IP guards. EgressPolicy emits
        # EGRESS_BLOCKED itself; we only need to surface the block to the
        # caller. When _egress_policy is None (config.security_infra.
        # egress_active_enforcement=False, the v1 default), this block is a
        # no-op and AD-456 consultation-only behavior is preserved.
        policy = type(self)._egress_policy
        if policy is not None:
            try:
                if not policy.is_allowed(url):
                    return "Egress policy: blocked by AD-456b runtime sandboxing"
            except Exception:
                logger.warning(
                    "AD-456b: EgressPolicy.is_allowed failed; allowing request",
                    exc_info=True,
                )

        return None

    async def fetch_governed(
        self,
        url: str,
        method: str = "GET",
        *,
        max_body_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Public governed fetch: SSRF validation, per-domain rate limiting,
        429 retry and profile recording, exactly as the ``http_fetch`` intent
        gets them.

        Exists so an in-process consumer (AD-1221's sandbox fetch broker) can
        reach the governed path without reaching into a private method, and
        without the body transiting the intent bus. ``max_body_bytes`` lets
        such a consumer choose its own cap: :attr:`MAX_BODY_BYTES` is sized to
        protect the bus (see its comment and the #636 OOM), and a caller that
        does not put the body on the bus is not the thing that cap defends.
        """
        return await self._fetch_url(url, method, max_body_bytes=max_body_bytes)

    async def _fetch_url(
        self, url: str, method: str, *, max_body_bytes: int | None = None
    ) -> dict[str, Any]:
        """Fetch a URL, sharing one outbound request across identical callers.

        BF-770: the N agents still each reason over the result -- best-of-N
        cognition is deliberate and preserved -- but ACQUISITION is single.
        Rate limiting stays inside the shared work, so one shared fetch consumes
        one slot rather than N.

        The key includes ``cap``: a caller asking for more body than an
        in-flight one must not be handed the shorter answer.

        A task belonging to a different (typically closed) event loop is never
        reused: the map is class-level and outlives any one loop, and awaiting
        a dead loop's task raises rather than fetching.
        """
        error = self._validate_url(url)
        if error:
            return {"success": False, "error": f"SSRF protection: {error}"}

        cap = self.MAX_BODY_BYTES if max_body_bytes is None else max_body_bytes
        key = (method, url, cap)

        task = self._inflight.get(key)
        if (
            task is None
            or task.done()
            or task.cancelling() > 0
            or task.get_loop() is not asyncio.get_running_loop()
        ):
            task = asyncio.create_task(self._fetch_url_uncoalesced(url, method, cap))
            self._inflight[key] = task
            # Cleared by the task itself, not by any awaiter: an awaiter that is
            # cancelled must not strand the entry for everyone else. Guarded on
            # identity -- a finished task's callback runs a tick later, by which
            # time a NEW task may hold the key, and an unguarded pop would evict
            # that live one and let the next caller start a duplicate fetch.
            def _release(finished: asyncio.Task, _k: Any = key) -> None:
                if self._inflight.get(_k) is finished:
                    del self._inflight[_k]

            task.add_done_callback(_release)

        # Shielded so one caller's cancellation does not cancel the fetch the
        # other callers are waiting on. Counted per TASK, not per key: a key
        # outlives the flight under it, so a shared counter would let one
        # generation's waiters vouch for the next one's.
        self._waiters[task] = self._waiters.get(task, 0) + 1
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            # The shield protects the fetch from ONE caller leaving; it must not
            # outlive ALL of them. `broadcast` cancels straggler handlers on
            # timeout, and an unobserved fetch would keep burning a socket and a
            # rate slot for a request nobody can still receive.
            if self._waiters.get(task, 0) <= 1:
                # Deregistered BEFORE cancelling, because `cancel()` is only a
                # REQUEST: until the task runs again `done()` is False, and a
                # fresh caller would attach to a doomed flight and be handed a
                # CancelledError instead of a fetch.
                if self._inflight.get(key) is task:
                    del self._inflight[key]
                task.cancel()
            raise
        finally:
            remaining = self._waiters.get(task, 0) - 1
            if remaining > 0:
                self._waiters[task] = remaining
            else:
                self._waiters.pop(task, None)

        # Copied per caller: the result is shared, and a consumer mutating its
        # own reply must not reach into another agent's. `headers` is nested one
        # deeper and needs its own copy, or the isolation is only claimed.
        copied = dict(result)
        data = copied.get("data")
        if isinstance(data, dict):
            data = dict(data)
            headers = data.get("headers")
            if isinstance(headers, dict):
                data["headers"] = dict(headers)
            copied["data"] = data
        return copied

    async def _fetch_url_uncoalesced(
        self, url: str, method: str, cap: int
    ) -> dict[str, Any]:
        """One real outbound request, with timeout, body capping and per-domain
        rate limiting. Callers go through ``_fetch_url``.

        BF-819: redirects are followed HERE rather than by httpx, because
        ``follow_redirects=True`` validated only the URL the caller submitted.
        Measured: ``https://example.com/`` redirecting to ``127.0.0.1``,
        ``169.254.169.254`` and ``[::1]`` all fetched successfully and returned
        the private body, while ``validate_public_url`` refused every one of
        them when asked. The guard was correct and simply never consulted past
        hop one. Each hop's URL is now validated before it is requested.

        What that does NOT close: the guard resolves the hostname, and httpx
        resolves it again when connecting, so a hostile nameserver can answer
        differently for the two lookups. Closing that needs the connection
        pinned to the address the guard approved -- tracked separately, and not
        claimed here.
        """
        domain, state = self._get_domain_state(url)
        delay = await self._wait_for_rate_limit(domain, state)

        # One budget for the whole chain, expressed once rather than per
        # request. Per-request timeouts stopped bounding this the moment a chain
        # could hold several requests plus a rate-limit wait before each: five
        # hops against a 2s-spaced host spends 10s sleeping, and the DAG
        # executor cancels the broadcast at 10s, so a legal chain vanished as
        # "no agent responded" rather than saying it had timed out. The comment
        # on DEFAULT_TIMEOUT states that invariant; this keeps it true.
        try:
            async with asyncio.timeout(self.DEFAULT_TIMEOUT):
                return await self._follow_and_fetch(url, method, cap, domain, state, delay)
        except TimeoutError:
            return {
                "success": False,
                "error": (
                    f"Request timed out after {self.DEFAULT_TIMEOUT}s "
                    f"following redirects"
                ),
            }

    async def _follow_and_fetch(
        self,
        url: str,
        method: str,
        cap: int,
        domain: str,
        state: DomainRateState,
        delay: float,
    ) -> dict[str, Any]:
        """The redirect chain itself. Split out so one ``asyncio.timeout`` can
        bound every request and every rate-limit wait in it."""
        try:
            async with httpx.AsyncClient(
                timeout=self.DEFAULT_TIMEOUT,
                headers={"User-Agent": self.USER_AGENT},
                follow_redirects=False,
            ) as client:
                current = url
                for hop in range(self.MAX_REDIRECTS + 1):
                    req_start = time.monotonic()
                    response = await client.request(method, current)
                    latency_ms = (time.monotonic() - req_start) * 1000

                    self._update_rate_state(state, response)
                    self._record_to_profile(domain, latency_ms, response.status_code)

                    # Auto-retry once on 429 (AD-270)
                    if response.status_code == 429:
                        retry_delay = await self._wait_for_rate_limit(domain, state)
                        state.last_request_time = time.monotonic()
                        req_start2 = time.monotonic()
                        response = await client.request(method, current)
                        latency_ms2 = (time.monotonic() - req_start2) * 1000
                        self._update_rate_state(state, response)
                        self._record_to_profile(
                            domain, latency_ms2, response.status_code
                        )
                        delay += retry_delay

                    # httpx's own predicate, spelled out rather than read off
                    # `response.has_redirect_location` so a duck-typed response
                    # still works. Same statuses, same Location requirement: a
                    # bare `300 <= code < 400` would also chase a 304, which
                    # httpx treats as a cache answer rather than a redirect.
                    if not (
                        response.status_code in _REDIRECT_STATUSES
                        and response.headers.get("location")
                    ):
                        break

                    if hop >= self.MAX_REDIRECTS:
                        return {
                            "success": False,
                            "error": (
                                f"Too many redirects (limit {self.MAX_REDIRECTS})"
                            ),
                        }

                    # Relative Locations are legal and common, and resolving them
                    # wrongly would hand the guard a string it cannot judge.
                    previous = httpx.URL(current)
                    current = str(previous.join(response.headers["location"]))

                    error = self._validate_url(current)
                    if error:
                        return {
                            "success": False,
                            "error": f"SSRF protection: {error}",
                        }

                    method = self._redirect_method(method, response.status_code)

                    # A new host is a new budget: charging the origin domain for
                    # a hop elsewhere is how a chain slips the limiter. A hop
                    # within the SAME host is not a new request to that host --
                    # it is the rest of the one already charged for, and pacing
                    # it again is what blew the deadline above.
                    next_domain, next_state = self._get_domain_state(current)
                    if next_domain != domain:
                        domain, state = next_domain, next_state
                        delay += await self._wait_for_rate_limit(domain, state)

                raw = response.content
                truncated = len(raw) > cap
                body = raw[:cap].decode("utf-8", errors="replace")

                safe_headers = {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() in self._SAFE_HEADERS
                }

                return {
                    "success": True,
                    "data": {
                        "url": str(response.url),
                        "status_code": response.status_code,
                        "headers": safe_headers,
                        "body": body,
                        "body_length": len(body),
                        # BF-729: state the truncation instead of leaving it to
                        # be inferred. Without these two an agent holding a
                        # 1,048,576-char prefix cannot tell it apart from a
                        # complete document, and on 2026-08-07 that produced a
                        # confident wrong explanation ("this sandbox has no
                        # network access") for data that had in fact arrived.
                        "truncated": truncated,
                        "total_bytes": len(raw),
                        "rate_limit_delay": round(delay, 2),
                    },
                }
        except httpx.ConnectError as e:
            return {"success": False, "error": f"Connection error: {e}"}
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": f"Request timed out after {self.DEFAULT_TIMEOUT}s",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def _redirect_method(method: str, status_code: int) -> str:
        """The method for the next hop, mirroring ``httpx._client._redirect_method``.

        Kept identical to httpx rather than to a reading of RFC 9110, because
        following redirects by hand should change WHO validates the hop and
        nothing else. A hand-rolled rule that turned a HEAD into a GET, or a
        301-on-PUT into a GET, would be a silent behaviour change riding along
        with a security fix.
        """
        if status_code == 303 and method != "HEAD":
            return "GET"
        if status_code == 302 and method != "HEAD":
            return "GET"
        if status_code == 301 and method == "POST":
            return "GET"
        return method

    def _get_domain_state(self, url: str) -> tuple[str, DomainRateState]:
        """Look up or create rate-limit state for the URL's domain.

        BF-819: keyed on host[:port], NOT on ``netloc``. ``netloc`` carries any
        ``user:pass@`` prefix, so the same host under two credentials got two
        independent budgets -- a redirect chain varying the userinfo could pace
        itself out of the limiter entirely -- and the credentials were then
        written into the service-profile store as part of the key.
        """
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.rpartition("@")[2].lower()
        if domain not in self._domain_state:
            if self._profile_store:
                interval = self._profile_store.get_interval(domain)
            else:
                from probos.service_profile import DEFAULT_INTERVAL, _SEED_INTERVALS
                interval = _SEED_INTERVALS.get(domain, DEFAULT_INTERVAL)
            self._domain_state[domain] = DomainRateState(min_interval_seconds=interval)
        return domain, self._domain_state[domain]

    async def _wait_for_rate_limit(self, domain: str, state: DomainRateState) -> float:
        """Sleep if the domain was requested too recently. Returns delay in seconds."""
        now = time.monotonic()

        # Respect Retry-After if set
        wait = 0.0
        if state.retry_after is not None and state.retry_after > now:
            wait = state.retry_after - now
            state.retry_after = None
        elif state.last_request_time > 0:
            elapsed = now - state.last_request_time
            if elapsed < state.min_interval_seconds:
                wait = state.min_interval_seconds - elapsed

        if wait > 0:
            wait = min(wait, 10.0)  # Never wait more than 10s — fail fast
            logger.debug("Rate limit courtesy delay: %.1fs for %s", wait, domain)
            await asyncio.sleep(wait)

        state.last_request_time = time.monotonic()
        return wait

    def _update_rate_state(self, state: DomainRateState, response: httpx.Response) -> None:
        """Update domain rate state from response status and headers."""
        if response.status_code == 429:
            state.consecutive_429s = min(state.consecutive_429s + 1, 3)
            # Retry-After header (seconds or HTTP-date — we only handle seconds)
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    state.retry_after = time.monotonic() + float(retry_after)
                except (ValueError, TypeError):
                    pass
            # Exponential backoff capped at 60s
            state.min_interval_seconds = min(2 ** state.consecutive_429s, 60)
        else:
            state.consecutive_429s = 0

        # X-RateLimit-Remaining: pre-emptively slow down when near limit
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            try:
                state.remaining = int(remaining)
                if state.remaining <= 2:
                    state.min_interval_seconds = max(state.min_interval_seconds, state.min_interval_seconds * 2)
            except (ValueError, TypeError):
                pass

        # X-RateLimit-Reset: Unix timestamp
        reset_hdr = response.headers.get("x-ratelimit-reset")
        if reset_hdr is not None:
            try:
                reset_unix = float(reset_hdr)
                now_unix = time.time()
                if reset_unix > now_unix:
                    state.reset_time = time.monotonic() + (reset_unix - now_unix)
            except (ValueError, TypeError):
                pass

    def _record_to_profile(self, domain: str, latency_ms: float, status_code: int) -> None:
        """Record request to persistent ServiceProfile (AD-382)."""
        if not self._profile_store:
            return
        try:
            profile = self._profile_store.get_or_create(domain)
            profile.record_request(latency_ms, status_code)
            self._profile_store.save(profile)
        except Exception:
            logger.debug("HTTP fetch context failed", exc_info=True)
