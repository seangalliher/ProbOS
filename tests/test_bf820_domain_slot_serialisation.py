"""BF-820 (#1284): concurrent DISTINCT URLs on one domain no longer burst.

BF-770 made *identical* concurrent fetches cost one request. Distinct URLs on
the same host still burst, because reserving a rate-limit slot was not atomic:
`_wait_for_rate_limit` read `last_request_time`, computed a delay, and slept --
so every concurrent caller computed the SAME delay from the SAME pre-sleep
value and woke together.

Measured before the fix, three distinct `example.test` URLs at a 50 ms
interval::

    gaps between request starts: [0.062, 0.0]

The second and third went out simultaneously, against a host the limiter had
promised to space. That matters because DuckDuckGo blocks after roughly two
requests in a burst -- the reason #1227 exists -- and a Captain issuing two
different searches, or `WebSearchAgent` fanning to several result pages,
produces exactly this shape.

Assertions here are on observed timings at the point a request would be
issued, not on the limiter's return value: the old code returned a plausible
delay from each caller while they all slept concurrently.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from probos.agents.http_fetch import DomainRateState, HttpFetchAgent
from probos.security.url_guard import PinnedTarget

#: asyncio treats a timer as ready once it is within ONE clock tick of due, so
#: `asyncio.sleep(d)` can return a whole tick EARLY. On Windows that tick is
#: 15.625 ms: measured here, `asyncio.sleep(0.03)` returned in 0.0160 s, 14 ms
#: early. The least gap a correctly-spaced pair can show is therefore
#: `interval - CLOCK_TICK`, NOT `interval`.
CLOCK_TICK = time.get_clock_info("monotonic").resolution

#: How far below a nominal wait a healthy sleep may legitimately land.
#: This replaced a multiplicative `interval * 0.9`, which is unsatisfiable
#: whenever `interval * 0.1 < CLOCK_TICK` -- i.e. for any interval under about
#: 156 ms. This file uses 30 ms and 50 ms intervals, so that form was asking
#: for spacing the platform cannot deliver and flaked under the parallel gate.
SLEEP_UNDERSHOOT = CLOCK_TICK + 0.002


def _floor(nominal: float) -> float:
    """The least duration a healthy wait of ``nominal`` can measure as.

    Additive rather than proportional, because the error being tolerated is a
    fixed timer tick and not a fraction of the interval. It stays far above
    what the BF-820 defect produces -- a burst collapses gaps to ~0, while this
    floor sits at `nominal` minus one tick -- so sensitivity is unaffected.

    Never stricter than the proportional bound it replaced. On a platform with
    a fine-grained clock (Linux reports a nanosecond resolution) the additive
    term would otherwise TIGHTEN the bound to `nominal - 0.002` and could fail
    a run that passes today. Taking the lower of the two means this change can
    only ever relax a bound, never introduce a new failure.
    """
    return max(min(nominal * 0.9, nominal - SLEEP_UNDERSHOOT), 0.0)


@pytest.fixture(autouse=True)
def _clean_class_state():
    HttpFetchAgent._domain_state.clear()
    HttpFetchAgent._domain_locks.clear()
    HttpFetchAgent._inflight.clear()
    HttpFetchAgent._waiters.clear()
    yield
    HttpFetchAgent._domain_state.clear()
    HttpFetchAgent._domain_locks.clear()
    HttpFetchAgent._inflight.clear()
    HttpFetchAgent._waiters.clear()


def _agent() -> HttpFetchAgent:
    return HttpFetchAgent.__new__(HttpFetchAgent)


def _seed(domain: str, interval: float) -> DomainRateState:
    state = DomainRateState(min_interval_seconds=interval)
    HttpFetchAgent._domain_state[domain] = state
    return state


async def _reserve_all(urls: list[str], agent: HttpFetchAgent) -> list[float]:
    """Concurrently reserve a slot per URL; return the times a request would go."""
    starts: list[float] = []

    async def one(url: str) -> None:
        domain, state = agent._get_domain_state(url)
        await agent._wait_for_rate_limit(domain, state)
        # The transport would issue the request here.
        starts.append(time.monotonic())

    await asyncio.gather(*(one(u) for u in urls))
    starts.sort()
    return starts


def _gaps(starts: list[float]) -> list[float]:
    return [starts[i + 1] - starts[i] for i in range(len(starts) - 1)]


# ── the floor itself ──────────────────────────────────────────────


def test_the_spacing_floor_is_achievable_on_this_platform() -> None:
    """The bound must be one the event loop can actually satisfy.

    The previous form, `interval * 0.9`, was not: it is below the achievable
    minimum whenever `interval * 0.1 < CLOCK_TICK`, i.e. for any interval under
    roughly 156 ms, and this file uses 30 ms and 50 ms. That is why it flaked
    under the parallel gate rather than reporting a real defect.
    """
    for interval in (0.03, 0.05, 0.20):
        achievable = interval - CLOCK_TICK
        assert _floor(interval) <= achievable, (
            f"floor {_floor(interval):.4f} for interval {interval} exceeds the "
            f"{achievable:.4f} a healthy sleep can deliver at a "
            f"{CLOCK_TICK:.6f}s tick"
        )
        # And never tighter than the bound this replaced, so a fine-clock
        # platform keeps exactly its previous behaviour.
        assert _floor(interval) <= interval * 0.9, interval
        # A floor of zero would accept a burst; the clamp must stay inactive.
        assert _floor(interval) > 0.0, interval


def test_the_spacing_floor_still_rejects_coalescing() -> None:
    """Widening the floor must not cost sensitivity.

    A real defect collapses gaps toward zero, which is an order of magnitude
    below the floor, so the two never come close. Pinned explicitly because two
    earlier attempts at this fix bought tolerance by giving up detection -- one
    let a single coalesced pair through, the other let the alternating shape
    `[0.06, 0, 0.06, 0, 0.06]` through.
    """
    interval = 0.03
    floor = _floor(interval)

    healthy = [interval - CLOCK_TICK] * 5
    assert all(g >= floor for g in healthy), healthy

    burst = [0.0005, 0.0004, 0.0003, 0.0004, 0.0004]
    assert not all(g >= floor for g in burst), burst

    single_pair = [interval, 0.0, interval, interval, interval]
    assert not all(g >= floor for g in single_pair), single_pair

    alternating = [2 * interval, 0.0, 2 * interval, 0.0, 2 * interval]
    assert not all(g >= floor for g in alternating), alternating


# ── the defect ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_distinct_urls_are_spaced_not_burst() -> None:
    """The measured defect: gaps [0.062, 0.0] for three distinct URLs."""
    interval = 0.05
    _seed("example.test", interval)
    agent = _agent()

    starts = await _reserve_all(
        [f"https://example.test/{p}" for p in ("a", "b", "c")], agent
    )
    gaps = _gaps(starts)

    assert len(gaps) == 2
    for gap in gaps:
        assert gap >= _floor(interval), gaps


@pytest.mark.asyncio
async def test_the_spacing_holds_as_the_burst_grows() -> None:
    """Two callers can pass by luck; six cannot.

    Also pins the cost: N waiters take about N x interval, which is the
    trade this fix makes deliberately -- the alternative is the burst.
    """
    interval = 0.03
    _seed("example.test", interval)
    agent = _agent()

    began = time.monotonic()
    starts = await _reserve_all(
        [f"https://example.test/p{i}" for i in range(6)], agent
    )
    elapsed = time.monotonic() - began

    gaps = _gaps(starts)
    assert len(gaps) == 5
    assert all(g >= _floor(interval) for g in gaps), gaps
    assert elapsed >= 5 * _floor(interval)


@pytest.mark.asyncio
async def test_a_different_domain_is_not_made_to_wait() -> None:
    """The lock is per-domain. Serialising every host would be a new defect:
    one slow host would pace every other."""
    _seed("slow.test", 0.30)
    _seed("fast.test", 0.0)
    agent = _agent()

    slow_domain, slow_state = agent._get_domain_state("https://slow.test/a")
    slow_state.last_request_time = time.monotonic()
    holder = asyncio.create_task(agent._wait_for_rate_limit(slow_domain, slow_state))
    await asyncio.sleep(0.02)

    began = time.monotonic()
    fast_domain, fast_state = agent._get_domain_state("https://fast.test/a")
    await agent._wait_for_rate_limit(fast_domain, fast_state)
    assert time.monotonic() - began < 0.10

    await holder


# ── what the critical section must not break ──────────────────────


@pytest.mark.asyncio
async def test_a_caller_that_gives_up_costs_the_next_one_nothing() -> None:
    """Cancellation while queued or sleeping must release the lock.

    A waiter holding a lock through cancellation would wedge the domain
    permanently -- a far worse failure than the burst being fixed.
    """
    interval = 0.20
    _seed("example.test", interval)
    agent = _agent()
    domain, state = agent._get_domain_state("https://example.test/a")
    state.last_request_time = time.monotonic()

    quitter = asyncio.create_task(agent._wait_for_rate_limit(domain, state))
    await asyncio.sleep(0.02)
    quitter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await quitter

    assert not HttpFetchAgent._domain_lock(domain).locked()

    began = time.monotonic()
    await agent._wait_for_rate_limit(domain, state)
    # It still waits out the ORIGINAL request's interval -- the abandoned
    # waiter neither committed a time nor consumed the slot.
    assert time.monotonic() - began >= interval * 0.5


@pytest.mark.asyncio
async def test_a_cancelled_waiter_does_not_consume_the_servers_directive() -> None:
    """`Retry-After` is the server telling us to stop until a wall-clock time.

    Clearing it when the wait was COMPUTED meant a caller cancelled mid-sleep
    consumed the directive without honouring it, and the next waiter went
    straight out: measured, a 0.50s directive cancelled at 0.03s let the next
    request through at 0.031s. It is cleared only once the wait has been served.
    """
    _seed("example.test", 0.0)
    agent = _agent()
    domain, state = agent._get_domain_state("https://example.test/a")
    deadline = time.monotonic() + 0.30
    state.retry_after = deadline

    quitter = asyncio.create_task(agent._wait_for_rate_limit(domain, state))
    await asyncio.sleep(0.03)
    quitter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await quitter

    assert state.retry_after == deadline, "the directive was consumed unserved"

    began = time.monotonic()
    remaining = deadline - began
    await agent._wait_for_rate_limit(domain, state)
    # `asyncio.sleep` can wake a whole clock tick early, so this is the
    # tolerance the rest of the file uses rather than an exact clock compare.
    assert time.monotonic() - began >= _floor(remaining)
    # Served now, so it is cleared.
    assert state.retry_after is None


@pytest.mark.asyncio
async def test_a_newer_directive_is_not_cleared_by_an_older_wait() -> None:
    """`_update_rate_state` writes `retry_after` from OUTSIDE the lock, so a
    fresher 429 can land while a waiter is asleep on the previous one."""
    _seed("example.test", 0.0)
    agent = _agent()
    domain, state = agent._get_domain_state("https://example.test/a")
    state.retry_after = time.monotonic() + 0.05

    waiter = asyncio.create_task(agent._wait_for_rate_limit(domain, state))
    await asyncio.sleep(0.01)
    newer = time.monotonic() + 5.0
    state.retry_after = newer
    await waiter

    assert state.retry_after == newer


@pytest.mark.asyncio
async def test_retry_after_is_still_honoured_inside_the_lock() -> None:
    """The 429 path reads and clears `retry_after`; both must stay atomic."""
    _seed("example.test", 0.0)
    agent = _agent()
    domain, state = agent._get_domain_state("https://example.test/a")
    state.retry_after = time.monotonic() + 0.08

    began = time.monotonic()
    waited = await agent._wait_for_rate_limit(domain, state)
    assert time.monotonic() - began >= 0.05
    assert waited > 0
    assert state.retry_after is None


@pytest.mark.asyncio
async def test_only_one_waiter_consumes_a_retry_after() -> None:
    """`retry_after` is read-then-cleared. Outside a lock two waiters both read
    it, both sleep the same window, and both wake into the same instant.

    Asserting only the GAP between starts is not enough: run against the old
    algorithm the first request went out at 0.000s -- ignoring the directive
    completely -- and the second one's later wake still produced a 0.109s gap.
    The deadline itself has to be pinned.
    """
    _seed("example.test", 0.05)
    agent = _agent()
    domain, state = agent._get_domain_state("https://example.test/a")
    deadline = time.monotonic() + 0.08
    state.retry_after = deadline

    starts = await _reserve_all(
        ["https://example.test/a", "https://example.test/b"], agent
    )
    # Nobody goes before the server said they could.
    assert starts[0] >= deadline - SLEEP_UNDERSHOOT, starts[0] - deadline
    # And the second is still spaced from the first.
    assert _gaps(starts)[0] >= _floor(0.05)


@pytest.mark.asyncio
async def test_the_delay_reported_is_the_delay_taken() -> None:
    """``rate_limit_delay`` is what the caller is told the limiter cost them.

    Reporting only the sleep after the lock was acquired understates it by the
    queueing: measured, a third concurrent caller reported 0.050s having spent
    0.125s. Concurrent deliberately -- a sequential version of this test passes
    against the understated value.
    """
    interval = 0.05
    _seed("example.test", interval)
    agent = _agent()
    reports: list[tuple[float, float]] = []

    async def one(path: str) -> None:
        domain, state = agent._get_domain_state(f"https://example.test/{path}")
        began = time.monotonic()
        reported = await agent._wait_for_rate_limit(domain, state)
        reports.append((reported, time.monotonic() - began))

    await asyncio.gather(*(one(p) for p in ("a", "b", "c")))

    assert len(reports) == 3
    for reported, actual in reports:
        assert abs(reported - actual) < 0.02, reports
    # The queued callers really did spend more than one interval.
    assert max(r for r, _ in reports) >= 2 * _floor(interval), reports


# ── across the seam into the fetch itself ─────────────────────────


class _Unguarded(HttpFetchAgent):
    """Skips the SSRF hostname resolution so the test hosts need not exist.

    The guard runs before the limiter and is BF-819's subject, with its own
    tests; leaving it in would make every assertion here about DNS.

    BF-821 split the request path onto ``_validate_and_pin``, so both entry
    points are suppressed. It returns no addresses: there is nothing to pin,
    and the request goes out on the name exactly as it did before, which keeps
    these assertions about the rate-limit slot rather than the URL.
    """

    def _validate_url(self, url: str) -> str | None:
        return None

    def _validate_and_pin(self, url: str) -> PinnedTarget:
        return PinnedTarget(None, ())


@pytest.mark.asyncio
async def test_a_caller_that_cannot_get_a_slot_in_time_is_told_so() -> None:
    """The queue must be bounded by the fetch's own budget, not the caller's.

    Serialising the slot made the pre-existing placement dangerous: the first
    reservation sat OUTSIDE `asyncio.timeout(DEFAULT_TIMEOUT)`, so on a
    2s-spaced host the fifth concurrent waiter reached its slot at 10.02s --
    past the DAG executor's own 10s cancel. Measured: the broadcast came back
    with zero results while a request went out to the host anyway. A node that
    is cancelled reports nothing; a node that times out says why.
    """
    _seed("slow.test", 30.0)
    agent = _Unguarded.__new__(_Unguarded)
    domain, state = agent._get_domain_state("https://slow.test/a")
    state.last_request_time = time.monotonic()

    began = time.monotonic()
    result = await agent._fetch_url("https://slow.test/b", "GET")
    elapsed = time.monotonic() - began

    assert result["success"] is False
    assert "timed out" in result["error"], result
    assert elapsed < HttpFetchAgent.DEFAULT_TIMEOUT + 2.0, elapsed


@pytest.mark.asyncio
async def test_the_slot_wait_is_charged_against_the_fetch_budget() -> None:
    """A slot that frees up in time still leaves room to do the request."""
    calls: list[str] = []

    class _Agent(_Unguarded):
        async def _follow_and_fetch(self, url, method, cap, domain, state, delay):
            calls.append(url)
            return {"success": True, "url": url, "rate_limit_delay": round(delay, 2)}

    _seed("example.test", 0.05)
    agent = _Agent.__new__(_Agent)
    domain, state = agent._get_domain_state("https://example.test/a")
    state.last_request_time = time.monotonic()

    result = await agent._fetch_url("https://example.test/b", "GET")
    assert result["success"] is True, result
    assert calls == ["https://example.test/b"]
    # The delay handed onward is the one really spent queueing and sleeping.
    assert result["rate_limit_delay"] >= 0.03


# ── the lock's own lifecycle ──────────────────────────────────────


@pytest.mark.asyncio
async def test_each_domain_gets_its_own_lock_and_keeps_it() -> None:
    a = HttpFetchAgent._domain_lock("one.test")
    b = HttpFetchAgent._domain_lock("two.test")
    assert a is not b
    assert HttpFetchAgent._domain_lock("one.test") is a


def test_a_lock_is_never_shared_across_event_loops() -> None:
    """`_domain_state` is class-level and outlives any one loop. An
    `asyncio.Lock` belongs to the loop that created it, so a lock carried into
    a second loop is either never awaited or raises when it is.

    Keyed on the loop OBJECT, weakly, not `id(loop)`: ids are recycled after
    collection, and an id key could hand a brand-new loop a dead loop's lock.
    """
    async def _grab():
        return HttpFetchAgent._domain_lock("example.test")

    first = asyncio.run(_grab())
    second = asyncio.run(_grab())
    assert first is not second


def test_the_lock_table_does_not_outlive_the_loops_that_own_it() -> None:
    """One dict per loop, retained for the life of the process, would be a
    slow leak in a long-running vessel that recycles loops.

    The locks must be CONTENDED before the loop closes. An uncontended
    ``asyncio.Lock`` never binds its loop, so a version of this test that only
    creates one passes against a table that leaks every loop that did real work
    -- which is all of them.
    """
    import gc

    async def _contend():
        _seed("example.test", 0.01)
        agent = _agent()
        domain, state = agent._get_domain_state("https://example.test/a")
        # Two concurrent waiters, so the lock actually blocks and binds.
        await asyncio.gather(
            agent._wait_for_rate_limit(domain, state),
            agent._wait_for_rate_limit(domain, state),
        )

    for _ in range(5):
        asyncio.run(_contend())
        HttpFetchAgent._domain_state.clear()
    gc.collect()

    # Only the sweep can shrink this: each closed loop is held alive by its own
    # bound lock, so the weak key alone would keep every one of them.
    async def _final():
        HttpFetchAgent._domain_lock("example.test")
        return len(HttpFetchAgent._domain_locks)

    assert asyncio.run(_final()) == 1, dict(HttpFetchAgent._domain_locks)
