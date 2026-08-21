"""BF-770 (#1227): the mesh's fan-out no longer costs six outbound requests.

`IntentBus.broadcast()` invokes EVERY subscriber. The fleet runs three
`HttpFetchAgent`s and two `WebSearchAgent`s, and each search broadcasts, so one
Captain-visible search made **six** DuckDuckGo requests. DDG serves roughly two
queries then blocks the rest of a burst. The rate limiting was self-inflicted.

Identical in-flight fetches are now coalesced: the N agents still each reason
over the result -- best-of-N is deliberate -- but acquisition is single.

The issue is explicit that a test calling one agent's `perceive()` directly
does not exercise the outer multiplier and would pass while the defect is
present. These count ACTUAL outbound requests across the real fan-out.
"""

from __future__ import annotations

import asyncio

import pytest

from probos.agents.http_fetch import HttpFetchAgent


@pytest.fixture(autouse=True)
def _clean_class_state():
    HttpFetchAgent._inflight.clear()
    HttpFetchAgent._waiters.clear()
    HttpFetchAgent._domain_state.clear()
    yield
    HttpFetchAgent._inflight.clear()
    HttpFetchAgent._waiters.clear()
    HttpFetchAgent._domain_state.clear()


class _CountingAgent(HttpFetchAgent):
    """Counts real outbound requests. Overrides the UNCOALESCED worker, so the
    coalescing layer under test is the production one."""

    outbound: list[str] = []

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)

    async def _fetch_url_uncoalesced(self, url, method, cap):
        _CountingAgent.outbound.append(url)
        await asyncio.sleep(0.02)  # hold it open so peers arrive mid-flight
        return {
            "success": True,
            "data": {"url": url, "status_code": 200, "body": "ok",
                     "headers": {}, "body_length": 2, "truncated": False,
                     "total_bytes": 2, "rate_limit_delay": 0.0},
        }


def _agents(n: int) -> list[_CountingAgent]:
    return [_CountingAgent(agent_id=f"http-{i}", pool="http") for i in range(n)]


URL = "https://html.duckduckgo.com/html/?q=x"


class TestTheFanOutCostsOneRequest:
    async def test_three_agents_fetching_the_same_url_make_one_request(self):
        """The measured shape: three HttpFetchAgents, one broadcast."""
        _CountingAgent.outbound = []
        agents = _agents(3)

        results = await asyncio.gather(
            *(a._fetch_url(URL, "GET") for a in agents)
        )

        assert len(_CountingAgent.outbound) == 1, (
            f"expected one outbound request, got "
            f"{len(_CountingAgent.outbound)}: {_CountingAgent.outbound}"
        )
        assert all(r["success"] for r in results)
        assert all(r["data"]["body"] == "ok" for r in results)

    async def test_the_full_six_way_multiplier_collapses_to_one(self):
        """Two WebSearchAgents x three HttpFetchAgents = the six in the issue."""
        _CountingAgent.outbound = []
        agents = _agents(3)

        await asyncio.gather(
            *(a._fetch_url(URL, "GET") for a in agents),
            *(a._fetch_url(URL, "GET") for a in agents),
        )

        assert len(_CountingAgent.outbound) == 1

    async def test_every_caller_gets_the_result(self):
        _CountingAgent.outbound = []
        agents = _agents(3)

        results = await asyncio.gather(
            *(a._fetch_url(URL, "GET") for a in agents)
        )

        assert len(results) == 3
        assert all(r["data"]["url"] == URL for r in results)


class TestCoalescingDoesNotOverReach:
    async def test_different_urls_are_not_shared(self):
        _CountingAgent.outbound = []
        agents = _agents(2)

        await asyncio.gather(
            agents[0]._fetch_url(URL, "GET"),
            agents[1]._fetch_url("https://example.com/other", "GET"),
        )

        assert len(_CountingAgent.outbound) == 2

    async def test_different_methods_are_not_shared(self):
        _CountingAgent.outbound = []
        agents = _agents(2)

        await asyncio.gather(
            agents[0]._fetch_url(URL, "GET"),
            agents[1]._fetch_url(URL, "HEAD"),
        )

        assert len(_CountingAgent.outbound) == 2

    async def test_a_larger_cap_is_not_served_the_shorter_answer(self):
        """Sharing across caps would hand a caller less body than it asked for."""
        _CountingAgent.outbound = []
        agents = _agents(2)

        await asyncio.gather(
            agents[0]._fetch_url(URL, "GET", max_body_bytes=100),
            agents[1]._fetch_url(URL, "GET", max_body_bytes=999_999),
        )

        assert len(_CountingAgent.outbound) == 2

    async def test_a_later_sequential_fetch_is_not_served_a_stale_result(self):
        """Coalescing is for CONCURRENT callers only; it must not become a cache."""
        _CountingAgent.outbound = []
        agent = _agents(1)[0]

        await agent._fetch_url(URL, "GET")
        await agent._fetch_url(URL, "GET")

        assert len(_CountingAgent.outbound) == 2

    async def test_a_finished_but_still_registered_task_is_not_reused(self):
        """The done-callback clears the entry a tick AFTER completion, so there
        is a window where a finished task is still in the map. Reusing it there
        would serve a stale body."""
        _CountingAgent.outbound = []
        agent = _agents(1)[0]

        stale = asyncio.create_task(
            agent._fetch_url_uncoalesced(URL, "GET", HttpFetchAgent.MAX_BODY_BYTES)
        )
        await stale
        # Placed by hand, mimicking the pre-callback window.
        HttpFetchAgent._inflight[("GET", URL, HttpFetchAgent.MAX_BODY_BYTES)] = stale
        before = len(_CountingAgent.outbound)

        await agent._fetch_url(URL, "GET")

        assert len(_CountingAgent.outbound) == before + 1, (
            "a completed task was reused, turning coalescing into a cache"
        )

    async def test_each_caller_gets_its_own_dict(self):
        """A consumer mutating its reply must not reach into another agent's."""
        _CountingAgent.outbound = []
        agents = _agents(2)

        first, second = await asyncio.gather(
            agents[0]._fetch_url(URL, "GET"),
            agents[1]._fetch_url(URL, "GET"),
        )

        assert first is not second
        assert first["data"] is not second["data"]
        first["data"]["body"] = "mutated"
        assert second["data"]["body"] == "ok"

    async def test_headers_are_not_shared_between_callers(self):
        """`headers` sits one level deeper than `data`. A shallow copy of `data`
        leaves it aliased, so the isolation would be claimed but not provided."""
        _CountingAgent.outbound = []
        agents = _agents(2)

        first, second = await asyncio.gather(
            agents[0]._fetch_url(URL, "GET"),
            agents[1]._fetch_url(URL, "GET"),
        )

        assert first["data"]["headers"] is not second["data"]["headers"]
        first["data"]["headers"]["x-trace"] = "caller-one"
        assert "x-trace" not in second["data"]["headers"]


class TestFailureIsNotSharedBeyondItsFlight:
    async def test_the_map_is_cleared_after_completion(self):
        _CountingAgent.outbound = []
        agent = _agents(1)[0]

        await agent._fetch_url(URL, "GET")
        await asyncio.sleep(0)

        assert HttpFetchAgent._inflight == {}, (
            "a completed fetch stayed registered and would be replayed"
        )

    async def test_a_raising_fetch_does_not_poison_the_key(self):
        class _Boom(_CountingAgent):
            async def _fetch_url_uncoalesced(self, url, method, cap):
                raise RuntimeError("network down")

        agent = _Boom(agent_id="http-x", pool="http")

        with pytest.raises(RuntimeError):
            await agent._fetch_url(URL, "GET")
        await asyncio.sleep(0)

        assert HttpFetchAgent._inflight == {}, (
            "a failed fetch stayed registered, so every later caller would "
            "await a dead task"
        )

    async def test_a_task_from_a_dead_loop_is_not_awaited(self):
        """The map is class-level and outlives any one event loop. Awaiting a
        closed loop's task raises instead of fetching, so it must be replaced.

        The stranded task is left PENDING and uncancelled -- a cancelled one
        would be rejected by the cancellation guard instead, which would leave
        this guard untested."""
        _CountingAgent.outbound = []
        agent = _agents(1)[0]
        key = ("GET", URL, HttpFetchAgent.MAX_BODY_BYTES)

        dead = asyncio.new_event_loop()
        coro = asyncio.sleep(60)
        try:
            stranded = dead.create_task(coro)
            # It will never run; silence the pending-destruction report.
            stranded._log_destroy_pending = False
            HttpFetchAgent._inflight[key] = stranded
        finally:
            dead.close()

        assert not stranded.done() and stranded.cancelling() == 0, (
            "the stranded task must be pending and uncancelled, or this test "
            "exercises a different guard"
        )

        result = await agent._fetch_url(URL, "GET")

        assert result["success"] is True
        assert len(_CountingAgent.outbound) == 1
        coro.close()

    async def test_a_finished_tasks_callback_does_not_evict_its_replacement(self):
        """A completed task's done-callback runs a tick LATER. If a new caller
        takes the key in that window, an unguarded pop evicts that LIVE task and
        the next caller starts a duplicate acquisition -- the fan-out this fix
        removes, reintroduced by a race.

        The window is opened deterministically: the worker queues the injection
        before returning, so it lands ahead of this task's own real `_release`.
        """
        key = ("GET", URL, HttpFetchAgent.MAX_BODY_BYTES)
        _CountingAgent.outbound = []
        replacement: list[asyncio.Task] = []

        def _inject() -> None:
            t = asyncio.get_running_loop().create_task(asyncio.sleep(5))
            HttpFetchAgent._inflight[key] = t
            replacement.append(t)

        class _Injecting(_CountingAgent):
            async def _fetch_url_uncoalesced(self, url, method, cap):
                _CountingAgent.outbound.append(url)
                asyncio.get_running_loop().call_soon(_inject)
                return {"success": True, "data": {"url": url, "headers": {}}}

        agent = _Injecting(agent_id="http-inject", pool="http")
        await agent._fetch_url(URL, "GET")
        for _ in range(4):
            await asyncio.sleep(0)

        assert replacement, "the injection never ran; the test proves nothing"
        try:
            assert HttpFetchAgent._inflight.get(key) is replacement[0], (
                "the finished flight's cleanup evicted a live replacement task"
            )
        finally:
            replacement[0].cancel()

    async def test_one_caller_cancelling_does_not_kill_the_shared_fetch(self):
        _CountingAgent.outbound = []
        agents = _agents(2)

        first = asyncio.create_task(agents[0]._fetch_url(URL, "GET"))
        await asyncio.sleep(0)
        second = asyncio.create_task(agents[1]._fetch_url(URL, "GET"))
        await asyncio.sleep(0)
        first.cancel()

        result = await second

        assert result["success"] is True, (
            "cancelling one awaiter cancelled the fetch its peer was waiting on"
        )
        assert len(_CountingAgent.outbound) == 1

    async def test_the_last_caller_leaving_cancels_the_fetch(self):
        """`broadcast` cancels straggler handlers on timeout. The shield must
        not let a request nobody can still receive keep a socket and a rate
        slot open."""
        started = asyncio.Event()

        class _Slow(_CountingAgent):
            async def _fetch_url_uncoalesced(self, url, method, cap):
                _CountingAgent.outbound.append(url)
                started.set()
                await asyncio.sleep(30)
                return {"success": True, "data": {}}

        _CountingAgent.outbound = []
        agent = _Slow(agent_id="http-slow", pool="http")
        key = ("GET", URL, HttpFetchAgent.MAX_BODY_BYTES)

        first = asyncio.create_task(agent._fetch_url(URL, "GET"))
        second = asyncio.create_task(agent._fetch_url(URL, "GET"))
        await started.wait()
        shared = HttpFetchAgent._inflight[key]

        first.cancel()
        await asyncio.sleep(0)
        assert not shared.cancelled(), "one caller leaving killed the shared fetch"

        second.cancel()
        for _ in range(4):
            await asyncio.sleep(0)

        assert shared.cancelled(), (
            "every caller gave up but the fetch kept running unobserved"
        )

    async def test_the_waiter_count_does_not_leak(self):
        _CountingAgent.outbound = []
        agents = _agents(3)

        await asyncio.gather(*(a._fetch_url(URL, "GET") for a in agents))

        assert HttpFetchAgent._waiters == {}, (
            "a leaked waiter count would keep later fetches from being cancelled"
        )

    async def test_the_waiter_count_does_not_leak_when_the_fetch_raises(self):
        class _Boom(_CountingAgent):
            async def _fetch_url_uncoalesced(self, url, method, cap):
                raise RuntimeError("network down")

        agent = _Boom(agent_id="http-boom", pool="http")

        with pytest.raises(RuntimeError):
            await agent._fetch_url(URL, "GET")

        assert HttpFetchAgent._waiters == {}

    async def test_a_replacements_only_caller_leaving_cancels_the_replacement(self):
        """One request key sees many flights. If the count is shared across
        them, a still-counted waiter from the PREVIOUS flight vouches for the
        replacement, and the replacement runs on with nobody to receive it.

        The precondition -- a waiter of the previous generation still counted
        while the replacement's own caller gives up -- is seeded directly, in
        both possible representations, so the test does not depend on which one
        the implementation chose.
        """
        started = asyncio.Event()
        key = ("GET", URL, HttpFetchAgent.MAX_BODY_BYTES)

        class _Slow(_CountingAgent):
            async def _fetch_url_uncoalesced(self, url, method, cap):
                _CountingAgent.outbound.append(url)
                started.set()
                await asyncio.sleep(30)
                return {"success": True, "data": {"url": url, "headers": {}}}

        _CountingAgent.outbound = []
        agent = _Slow(agent_id="http-gen", pool="http")

        previous = asyncio.get_running_loop().create_task(asyncio.sleep(30))
        HttpFetchAgent._waiters[previous] = 1  # per-task representation
        HttpFetchAgent._waiters[key] = 1  # per-key representation

        only_caller = asyncio.create_task(agent._fetch_url(URL, "GET"))
        await started.wait()
        replacement = HttpFetchAgent._inflight[key]

        only_caller.cancel()
        for _ in range(4):
            await asyncio.sleep(0)

        try:
            assert replacement.cancelled(), (
                "the replacement's only caller gave up, but a previous "
                "flight's waiter count kept it alive and unobserved"
            )
        finally:
            previous.cancel()

    async def test_a_fresh_caller_does_not_attach_to_a_cancelled_flight(self):
        """`cancel()` is only a REQUEST -- until the task runs again `done()` is
        False. A caller arriving in that exact window would shield a doomed task
        and be handed CancelledError instead of a fetch.

        Timed to one tick: enough for the abandoning waiter's cleanup to run,
        not enough for the doomed task to process its own cancellation.
        """
        started = asyncio.Event()
        key = ("GET", URL, HttpFetchAgent.MAX_BODY_BYTES)

        class _Slow(_CountingAgent):
            async def _fetch_url_uncoalesced(self, url, method, cap):
                _CountingAgent.outbound.append(url)
                started.set()
                await asyncio.sleep(30)
                return {"success": True, "data": {"url": url, "headers": {}}}

        _CountingAgent.outbound = []
        agent = _Slow(agent_id="http-doomed", pool="http")

        abandoned = asyncio.create_task(agent._fetch_url(URL, "GET"))
        await started.wait()
        doomed = HttpFetchAgent._inflight[key]

        abandoned.cancel()
        await asyncio.sleep(0)  # the waiter's except block runs here

        assert not doomed.done(), (
            "the doomed task finished too early; the window under test never "
            "existed and this test proves nothing"
        )

        fresh = asyncio.create_task(agent._fetch_url(URL, "GET"))
        await asyncio.sleep(0)  # fresh runs its admission check in the window
        admitted_to = HttpFetchAgent._inflight.get(key)
        await asyncio.sleep(0)  # the replacement's worker starts

        try:
            assert admitted_to is not doomed, (
                "a flight whose last caller gave up is still registered; the "
                "next caller attached to its wreckage"
            )
            assert len(_CountingAgent.outbound) == 2, (
                "the abandoned flight was reused rather than replaced"
            )
            assert not fresh.done(), (
                "the fresh caller was handed the doomed flight's cancellation"
            )
        finally:
            fresh.cancel()
            for _ in range(4):
                await asyncio.sleep(0)


class TestSsrfStillRunsPerCaller:
    async def test_a_blocked_url_never_reaches_the_fetch(self):
        _CountingAgent.outbound = []
        agent = _agents(1)[0]

        result = await agent._fetch_url("http://169.254.169.254/latest", "GET")

        assert result["success"] is False
        assert "SSRF" in result["error"]
        assert _CountingAgent.outbound == []


class TestThroughTheRealBus:
    """The issue is explicit that driving one agent's handler directly does not
    exercise the outer multiplier and would pass while the defect is present.
    These go through the real ``IntentBus.broadcast``, which fans out to every
    subscriber concurrently, and count actual outbound requests."""

    async def test_one_broadcast_to_three_agents_makes_one_request(self):
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager
        from probos.types import IntentMessage

        _CountingAgent.outbound = []
        bus = IntentBus(SignalManager())
        agents = _agents(3)
        for a in agents:
            bus.subscribe(a.id, a.handle_intent, ["http_fetch"])

        results = await bus.broadcast(
            IntentMessage(intent="http_fetch", params={"url": URL})
        )

        assert len(_CountingAgent.outbound) == 1, (
            f"one broadcast cost {len(_CountingAgent.outbound)} outbound "
            f"requests: {_CountingAgent.outbound}"
        )
        assert len(results) == 3, "each agent must still report its own result"

    async def test_the_six_way_multiplier_costs_one_request(self):
        """Two WebSearchAgents each broadcasting to three HttpFetchAgents."""
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager
        from probos.types import IntentMessage

        _CountingAgent.outbound = []
        bus = IntentBus(SignalManager())
        for a in _agents(3):
            bus.subscribe(a.id, a.handle_intent, ["http_fetch"])

        await asyncio.gather(
            bus.broadcast(IntentMessage(intent="http_fetch", params={"url": URL})),
            bus.broadcast(IntentMessage(intent="http_fetch", params={"url": URL})),
        )

        assert len(_CountingAgent.outbound) == 1, (
            f"the six-way fan-out still costs {len(_CountingAgent.outbound)} "
            f"requests -- this is the defect BF-770 measured"
        )

    async def test_a_search_after_a_timed_out_one_still_fetches(self):
        """`broadcast` cancels straggler handlers on timeout without awaiting
        them. The Captain retrying immediately must get a real fetch, not the
        wreckage of the one that timed out."""
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager
        from probos.types import IntentMessage

        gate = asyncio.Event()

        class _FirstHangs(_CountingAgent):
            async def _fetch_url_uncoalesced(self, url, method, cap):
                _CountingAgent.outbound.append(url)
                if len(_CountingAgent.outbound) == 1:
                    await gate.wait()
                return {
                    "success": True,
                    "data": {"url": url, "status_code": 200, "body": "ok",
                             "headers": {}, "body_length": 2, "truncated": False,
                             "total_bytes": 2, "rate_limit_delay": 0.0},
                }

        _CountingAgent.outbound = []
        bus = IntentBus(SignalManager())
        for i in range(3):
            a = _FirstHangs(agent_id=f"http-t{i}", pool="http")
            bus.subscribe(a.id, a.handle_intent, ["http_fetch"])

        timed_out = await bus.broadcast(
            IntentMessage(intent="http_fetch", params={"url": URL}), timeout=0.05
        )
        assert timed_out == [], "the first broadcast was expected to time out"

        try:
            second = await asyncio.wait_for(
                bus.broadcast(IntentMessage(intent="http_fetch", params={"url": URL})),
                timeout=5,
            )
        finally:
            gate.set()

        assert len(second) == 3, (
            "the retry returned nothing -- it attached to the cancelled flight "
            "instead of starting a new one"
        )
        assert all(r.success for r in second)


class TestAtTheLiteralHttpBoundary:
    """The tests above count acquisition calls, having replaced the worker.
    This one leaves the whole production worker in place -- rate limiting, body
    capping, 429 handling -- and counts requests at the transport, so the claim
    is about real outbound HTTP."""

    async def test_three_agents_issue_one_transport_request(self, monkeypatch):
        import httpx

        seen: list[str] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, text="hello", headers={"x-served": "1"})

        transport = httpx.MockTransport(_handler)
        real_client = httpx.AsyncClient

        def _client(**kw):
            kw.pop("transport", None)
            return real_client(transport=transport, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", _client)
        monkeypatch.setattr(HttpFetchAgent, "_validate_url", lambda self, url: None)

        async def _no_wait(self, _domain, state):
            state.last_request_time = 0
            return 0.0

        monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _no_wait)

        agents = [
            HttpFetchAgent(agent_id=f"http-real-{i}", pool="http") for i in range(3)
        ]
        results = await asyncio.gather(
            *(a._fetch_url("https://example.test/page", "GET") for a in agents)
        )

        assert len(seen) == 1, f"three agents made {len(seen)} real requests: {seen}"
        assert all(r["success"] for r in results)
        assert all(r["data"]["body"] == "hello" for r in results)
        assert results[0]["data"]["headers"] is not results[1]["data"]["headers"]
