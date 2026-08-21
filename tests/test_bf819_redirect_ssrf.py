"""BF-819 (#1283): a redirect no longer walks past the SSRF guard.

`HttpFetchAgent` validated the URL it was GIVEN and then handed it to httpx with
`follow_redirects=True`. No hop after the first was ever checked.

Measured against the real guard before the fix -- a real, resolvable public host
redirecting onward:

    https://example.com/start  ->  http://127.0.0.1/private          200, body returned
    https://example.com/start  ->  http://169.254.169.254/latest/    200, body returned
    https://example.com/start  ->  http://[::1]/private              200, body returned

`validate_public_url` refused all three when asked. It was simply never asked.
The middle one is the cloud instance-metadata endpoint, i.e. the classic
credential-theft target.

Redirects are now followed by hand, bounded, with the guard and the per-domain
rate limiter applied to every hop. The strong property these tests pin is that
the private host is never REQUESTED -- not merely that its body is withheld,
since a request to an internal service can have effects of its own.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from probos.agents.http_fetch import HttpFetchAgent


@pytest.fixture(autouse=True)
def _clean():
    HttpFetchAgent._inflight.clear()
    HttpFetchAgent._waiters.clear()
    HttpFetchAgent._domain_state.clear()
    yield
    HttpFetchAgent._inflight.clear()
    HttpFetchAgent._waiters.clear()
    HttpFetchAgent._domain_state.clear()


def _wire(monkeypatch, handler):
    """Install a MockTransport and disarm rate limiting. The SSRF guard is left
    REAL -- stubbing it is what made an earlier draft of this file vacuous."""
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )

    async def _no_wait(self, _domain, state):
        state.last_request_time = 0
        return 0.0

    monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _no_wait)


def _redirect_to(target: str, *, status: int = 302, body: bytes = b"PRIVATE"):
    """example.com redirects once to `target`; anything else serves `body`."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "example.com":
            return httpx.Response(
                status, headers={"location": target}, request=request
            )
        return httpx.Response(200, content=body, request=request)

    return handler, seen


# ── the hole ─────────────────────────────────────────────────────


class TestARedirectCannotReachAPrivateHost:
    @pytest.mark.parametrize(
        "target,needle",
        [
            ("http://127.0.0.1/private", "127.0.0.1"),
            ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
            ("http://[::1]/private", "::1"),
            ("http://10.0.0.5/internal", "10.0.0.5"),
            ("http://192.168.1.1/admin", "192.168.1.1"),
        ],
    )
    async def test_the_private_host_is_refused_and_never_requested(
        self, monkeypatch, target, needle
    ):
        handler, seen = _redirect_to(target)
        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="ssrf", pool="http")

        result = await agent._fetch_url("https://example.com/start", "GET")

        assert result["success"] is False
        assert "SSRF protection" in result["error"]
        assert needle in result["error"]
        assert seen == ["https://example.com/start"], (
            f"the private host was contacted: {seen}"
        )

    async def test_the_body_of_a_blocked_hop_is_not_returned(self, monkeypatch):
        handler, _seen = _redirect_to(
            "http://127.0.0.1/private", body=b"SECRET FROM LOOPBACK"
        )
        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="ssrf-body", pool="http")

        result = await agent._fetch_url("https://example.com/start", "GET")

        assert "SECRET" not in str(result)

    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    async def test_every_redirect_status_is_guarded(self, monkeypatch, status):
        """A guard on 302 alone would leave four open doors."""
        handler, seen = _redirect_to("http://127.0.0.1/x", status=status)
        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id=f"ssrf-{status}", pool="http")

        result = await agent._fetch_url("https://example.com/start", "GET")

        assert result["success"] is False
        assert seen == ["https://example.com/start"]

    async def test_a_private_host_reached_on_the_second_hop_is_refused(
        self, monkeypatch
    ):
        """The guard has to run on EVERY hop, not just the first redirect."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.host == "example.com":
                return httpx.Response(
                    302, headers={"location": "https://example.org/next"}, request=request
                )
            if request.url.host == "example.org":
                return httpx.Response(
                    302, headers={"location": "http://127.0.0.1/deep"}, request=request
                )
            return httpx.Response(200, content=b"PRIVATE", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="ssrf-deep", pool="http")

        result = await agent._fetch_url("https://example.com/start", "GET")

        assert result["success"] is False
        assert "SSRF protection" in result["error"]
        assert seen == ["https://example.com/start", "https://example.org/next"]

    async def test_a_relative_location_is_resolved_before_it_is_judged(
        self, monkeypatch
    ):
        """A relative Location is legal. Resolving it wrongly would hand the
        guard a string it cannot judge, which is a bypass by another route."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path == "/start":
                return httpx.Response(
                    302, headers={"location": "/moved"}, request=request
                )
            return httpx.Response(200, content=b"ok", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="rel", pool="http")

        result = await agent._fetch_url("https://example.com/start", "GET")

        assert result["success"] is True
        assert seen == ["https://example.com/start", "https://example.com/moved"]
        assert result["data"]["url"] == "https://example.com/moved"


# ── what must keep working ───────────────────────────────────────


class TestLegitimateRedirectsStillResolve:
    async def test_an_off_site_bang_redirect_still_lands(self, monkeypatch):
        """A DuckDuckGo bang (`!w langchain`) redirects off-site, and that body
        is the page the Captain asked for. Disabling redirects outright would
        have regressed this -- which is why the fix follows them rather than
        refusing them."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.host == "html.duckduckgo.com":
                return httpx.Response(
                    302,
                    headers={"location": "https://en.wikipedia.org/wiki/LangChain"},
                    request=request,
                )
            return httpx.Response(200, content=b"<html>LangChain</html>", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="bang", pool="http")

        result = await agent._fetch_url(
            "https://html.duckduckgo.com/html/?q=%21w+langchain", "GET"
        )

        assert result["success"] is True
        assert "LangChain" in result["data"]["body"]
        assert result["data"]["url"] == "https://en.wikipedia.org/wiki/LangChain"
        assert len(seen) == 2

    async def test_a_page_with_no_redirect_costs_one_request(self, monkeypatch):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, content=b"plain", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="plain", pool="http")

        result = await agent._fetch_url("https://example.com/plain", "GET")

        assert result["success"] is True
        assert result["data"]["body"] == "plain"
        assert len(seen) == 1

    async def test_the_chain_is_bounded(self, monkeypatch):
        """A hand-rolled follow needs its own stop, or a redirect loop hangs
        the fetch until the DAG timeout kills it."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            n = len(seen)
            return httpx.Response(
                302, headers={"location": f"https://example.com/hop{n}"}, request=request
            )

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="loop", pool="http")

        result = await agent._fetch_url("https://example.com/start", "GET")

        assert result["success"] is False
        assert "Too many redirects" in result["error"]
        assert len(seen) == HttpFetchAgent.MAX_REDIRECTS + 1, (
            "the bound is off by one against the stated limit"
        )

    async def test_a_chain_at_the_limit_still_succeeds(self, monkeypatch):
        """The bound must permit exactly MAX_REDIRECTS, not one fewer."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            n = len(seen)
            if n <= HttpFetchAgent.MAX_REDIRECTS:
                return httpx.Response(
                    302,
                    headers={"location": f"https://example.com/hop{n}"},
                    request=request,
                )
            return httpx.Response(200, content=b"arrived", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="limit", pool="http")

        result = await agent._fetch_url("https://example.com/start", "GET")

        assert result["success"] is True
        assert result["data"]["body"] == "arrived"


class TestTheMethodFollowsTheSpec:
    @pytest.mark.parametrize("status", [301, 302, 303])
    async def test_a_post_becomes_a_get(self, monkeypatch, status):
        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            methods.append(request.method)
            if request.url.path == "/start":
                return httpx.Response(
                    status, headers={"location": "/after"}, request=request
                )
            return httpx.Response(200, content=b"ok", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id=f"m{status}", pool="http")

        await agent._fetch_url("https://example.com/start", "POST")

        assert methods == ["POST", "GET"]

    @pytest.mark.parametrize("status", [307, 308])
    async def test_307_and_308_preserve_the_method(self, monkeypatch, status):
        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            methods.append(request.method)
            if request.url.path == "/start":
                return httpx.Response(
                    status, headers={"location": "/after"}, request=request
                )
            return httpx.Response(200, content=b"ok", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id=f"m{status}", pool="http")

        await agent._fetch_url("https://example.com/start", "POST")

        assert methods == ["POST", "POST"]

    async def test_a_get_stays_a_get(self, monkeypatch):
        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            methods.append(request.method)
            if request.url.path == "/start":
                return httpx.Response(
                    302, headers={"location": "/after"}, request=request
                )
            return httpx.Response(200, content=b"ok", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="mget", pool="http")

        await agent._fetch_url("https://example.com/start", "GET")

        assert methods == ["GET", "GET"]

    @pytest.mark.parametrize("status", [301, 302, 303])
    async def test_a_head_stays_a_head(self, monkeypatch, status):
        """httpx exempts HEAD from every downgrade. A hand-rolled rule that
        turned a HEAD into a GET would be a silent behaviour change riding
        along with a security fix."""
        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            methods.append(request.method)
            if request.url.path == "/start":
                return httpx.Response(
                    status, headers={"location": "/after"}, request=request
                )
            return httpx.Response(200, request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id=f"h{status}", pool="http")

        await agent._fetch_url("https://example.com/start", "HEAD")

        assert methods == ["HEAD", "HEAD"]

    @pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
    async def test_a_301_preserves_everything_except_post(self, monkeypatch, method):
        """httpx downgrades only POST on a 301."""
        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            methods.append(request.method)
            if request.url.path == "/start":
                return httpx.Response(
                    301, headers={"location": "/after"}, request=request
                )
            return httpx.Response(200, content=b"ok", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id=f"p{method}", pool="http")

        await agent._fetch_url("https://example.com/start", method)

        assert methods == [method, method]

    async def test_the_helper_matches_httpx_exactly(self):
        """Pinned against httpx's own table rather than a reading of the RFC,
        because following redirects by hand should change WHO validates a hop
        and nothing else."""
        cases = [
            ("POST", 301, "GET"), ("PUT", 301, "PUT"), ("HEAD", 301, "HEAD"),
            ("POST", 302, "GET"), ("PUT", 302, "GET"), ("HEAD", 302, "HEAD"),
            ("POST", 303, "GET"), ("PUT", 303, "GET"), ("HEAD", 303, "HEAD"),
            ("POST", 307, "POST"), ("PUT", 308, "PUT"), ("GET", 307, "GET"),
        ]
        for method, status, expected in cases:
            assert HttpFetchAgent._redirect_method(method, status) == expected, (
                f"{method} + {status} should stay {expected}"
            )

    async def test_a_304_is_not_followed(self, monkeypatch):
        """A 304 can legally carry a Location, and httpx treats it as a cache
        answer rather than a redirect. Chasing it makes an extra request and
        returns the wrong response."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                304, headers={"location": "https://example.com/elsewhere"},
                request=request,
            )

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="304", pool="http")

        result = await agent._fetch_url("https://example.com/cached", "GET")

        assert len(seen) == 1, f"a 304 was chased: {seen}"
        assert result["data"]["status_code"] == 304


class TestTheDestinationDomainIsCharged:
    async def test_a_hop_to_a_new_host_consults_that_hosts_limiter(
        self, monkeypatch
    ):
        """Charging the origin domain for a hop somewhere else is how a redirect
        chain slips the per-domain limiter entirely."""
        charged: list[str] = []

        async def _record(self, domain, state):
            charged.append(domain)
            state.last_request_time = 0
            return 0.0

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "example.com":
                return httpx.Response(
                    302,
                    headers={"location": "https://elsewhere.test/landing"},
                    request=request,
                )
            return httpx.Response(200, content=b"ok", request=request)

        real = httpx.AsyncClient
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
        )
        monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _record)
        monkeypatch.setattr(HttpFetchAgent, "_validate_url", lambda self, url: None)

        agent = HttpFetchAgent(agent_id="charge", pool="http")
        await agent._fetch_url("https://example.com/start", "GET")

        assert "example.com" in charged
        assert "elsewhere.test" in charged, (
            "the destination host was fetched without ever being rate-limited"
        )


class TestTheChainStaysInsideTheCallersBudget:
    """A per-request timeout stopped bounding this the moment a chain could hold
    several requests plus a rate-limit wait before each. The DAG executor
    cancels the broadcast at 10s, so a legal chain vanished as "no agent
    responded" -- a fetch that fails by disappearing rather than by saying so.
    """

    async def test_a_same_host_chain_does_not_re_pace_itself(self, monkeypatch):
        """A hop within one host is the rest of a request already charged for,
        not a new one. Charging it again is what spent the whole budget on
        sleeping."""
        waits: list[str] = []

        async def _record(self, domain, state):
            waits.append(domain)
            state.last_request_time = 0
            return 0.0

        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            n = len(seen)
            if n <= HttpFetchAgent.MAX_REDIRECTS:
                return httpx.Response(
                    302,
                    headers={"location": f"https://example.com/hop{n}"},
                    request=request,
                )
            return httpx.Response(200, content=b"done", request=request)

        real = httpx.AsyncClient
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
        )
        monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _record)

        agent = HttpFetchAgent(agent_id="samehost", pool="http")
        result = await agent._fetch_url("https://example.com/start", "GET")

        assert result["success"] is True
        assert waits == ["example.com"], (
            f"a same-host chain paced itself {len(waits)} times: {waits}"
        )

    async def test_a_slow_chain_reports_a_timeout_rather_than_vanishing(
        self, monkeypatch
    ):
        """With the budget spent, the fetch says so. Before, it ran past the
        caller's deadline and the caller reported no response at all."""
        def handler(request: httpx.Request) -> httpx.Response:
            # Alternating hosts, so every hop is cross-domain and pays the
            # limiter. A same-host chain is deliberately free (above).
            nxt = "b.test" if request.url.host != "b.test" else "a.test"
            return httpx.Response(
                302, headers={"location": f"https://{nxt}/x"}, request=request
            )

        real = httpx.AsyncClient
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
        )
        monkeypatch.setattr(HttpFetchAgent, "_validate_url", lambda self, url: None)
        monkeypatch.setattr(HttpFetchAgent, "DEFAULT_TIMEOUT", 0.25)

        async def _slow(self, domain, state):
            await asyncio.sleep(0.2)
            state.last_request_time = 0
            return 0.2

        monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _slow)

        agent = HttpFetchAgent(agent_id="slow", pool="http")
        started = time.monotonic()
        result = await agent._fetch_url("https://example.com/start", "GET")
        elapsed = time.monotonic() - started

        assert result["success"] is False
        assert "timed out" in result["error"]
        assert elapsed < 2.0, (
            f"the chain ran {elapsed:.1f}s past a 0.25s budget"
        )


class TestTheRateLimitKeyIsTheHost:
    async def test_userinfo_does_not_buy_a_second_budget(self):
        """`netloc` carries `user:pass@`, so the same host under two credentials
        got two independent budgets -- and the credentials were written into the
        service-profile store as part of the key."""
        agent = HttpFetchAgent(agent_id="key", pool="http")

        plain, _ = agent._get_domain_state("https://example.com/a")
        creds, _ = agent._get_domain_state("https://u1:p1@example.com/a")
        other, _ = agent._get_domain_state("https://u2:p2@example.com/a")

        assert plain == creds == other == "example.com"
        assert len(HttpFetchAgent._domain_state) == 1

    async def test_no_credential_reaches_the_rate_limit_key(self):
        agent = HttpFetchAgent(agent_id="key2", pool="http")

        agent._get_domain_state("https://alice:hunter2@example.com/a")

        assert not any("hunter2" in k for k in HttpFetchAgent._domain_state)

    async def test_case_does_not_buy_a_second_budget(self):
        agent = HttpFetchAgent(agent_id="key3", pool="http")

        lower, _ = agent._get_domain_state("https://example.com/a")
        upper, _ = agent._get_domain_state("https://EXAMPLE.COM/a")

        assert lower == upper == "example.com"

    async def test_the_port_is_still_part_of_the_key(self):
        agent = HttpFetchAgent(agent_id="key4", pool="http")

        bare, _ = agent._get_domain_state("https://example.com/a")
        ported, _ = agent._get_domain_state("https://example.com:8443/a")

        assert bare != ported


class TestTheExistingContractSurvives:
    async def test_the_429_retry_still_fires(self, monkeypatch):
        seen: list[str] = []
        statuses = iter([429, 200])

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(next(statuses), content=b"after retry", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="retry", pool="http")

        result = await agent._fetch_url("https://example.com/x", "GET")

        assert len(seen) == 2
        assert result["data"]["status_code"] == 200
        assert result["data"]["body"] == "after retry"

    async def test_truncation_is_still_reported_after_a_redirect(self, monkeypatch):
        """BF-807's fields are produced on the final hop's body."""
        full = b"z" * 4000

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/start":
                return httpx.Response(
                    302, headers={"location": "/big"}, request=request
                )
            return httpx.Response(200, content=full, request=request)

        _wire(monkeypatch, handler)
        monkeypatch.setattr(HttpFetchAgent, "MAX_BODY_BYTES", 500)
        agent = HttpFetchAgent(agent_id="trunc", pool="http")

        result = await agent._fetch_url("https://example.com/start", "GET")

        assert result["data"]["truncated"] is True
        assert result["data"]["total_bytes"] == len(full)
        assert result["data"]["body_length"] == 500

    async def test_a_redirect_without_a_location_is_treated_as_the_answer(
        self, monkeypatch
    ):
        """A 3xx with no Location is malformed; following nothing is correct,
        and looping forever on it would not be."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(302, content=b"no location here", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="noloc", pool="http")

        result = await agent._fetch_url("https://example.com/x", "GET")

        assert result["success"] is True
        assert result["data"]["status_code"] == 302
        assert len(seen) == 1

    async def test_the_submitted_url_is_still_validated(self, monkeypatch):
        """The original guard must not have been lost in the restructure."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, content=b"x", request=request)

        _wire(monkeypatch, handler)
        agent = HttpFetchAgent(agent_id="first", pool="http")

        result = await agent._fetch_url("http://169.254.169.254/latest", "GET")

        assert result["success"] is False
        assert "SSRF protection" in result["error"]
        assert seen == []
