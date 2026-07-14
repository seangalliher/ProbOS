"""BF-654/BF-659: per-endpoint in-flight concurrency correctness.

On ``probos serve`` boot, a burst of ~80 concurrent background LLM calls all
hit the AD-636 lane-acquire timeout together and FAIL OPEN (``sem = None``) at
once, flooding the shared Copilot proxy into an empty-content storm. BF-654
adds a per-endpoint in-flight semaphore (keyed by ``base_url|api_format`` — the
httpx pool key) that bounds TOTAL simultaneous requests to each upstream,
composing with — not replacing — the priority lanes. BF-659 makes that cap
fail-closed for background transport, follows the actual fallback endpoint,
and guarantees cancellation restores every acquired permit. CRITICAL
(interactive) calls bypass the cap so the Captain is never throttled; distinct
endpoints (the proxy vs. ollama for vision) get independent caps.

These tests use a REAL ``OpenAICompatibleClient`` (BF-287: real fixtures at the
substrate boundary) and patch only the transport (``_call_api`` /
``_complete_inner``) so the concurrency control flow is exercised without a
live endpoint. The lane is made large in the helper so the ENDPOINT cap — not
the lane — is the constraint under test.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import CognitiveConfig
from probos.types import LLMRequest, LLMResponse, Priority


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeRateConfig:
    """Minimal LLMRateConfig stub with the BF-654 field.

    RPM defaults are deliberately huge so the AD-617 per-tier rate limiter
    never throttles — isolating the endpoint in-flight cap as the sole
    concurrency constraint under test.
    """
    rpm_fast: int = 100_000
    rpm_standard: int = 100_000
    rpm_deep: int = 100_000
    max_wait_seconds: float = 30.0
    cache_max_entries: int = 10
    per_agent_hourly_token_cap: int = 0
    max_concurrent_calls: int = 6
    interactive_reserved_slots: int = 2
    max_inflight_per_endpoint: int = 8


def _make_config(**overrides) -> CognitiveConfig:
    defaults = {
        "llm_base_url": "http://127.0.0.1:8080/v1",
        "llm_api_key": "test-key",
        "llm_model_fast": "claude-sonnet-4.6",
        "llm_model_standard": "claude-sonnet-4.6",
        "llm_model_deep": "claude-opus-4.6",
    }
    defaults.update(overrides)
    return CognitiveConfig(**defaults)


def _make_client(
    *, max_inflight: int = 8, max_concurrent: int = 100, interactive_reserved: int = 2,
    config: CognitiveConfig | None = None,
) -> OpenAICompatibleClient:
    """Build a real client with a LARGE lane so the ENDPOINT cap binds first."""
    rate = _FakeRateConfig(
        max_concurrent_calls=max_concurrent,
        interactive_reserved_slots=interactive_reserved,
        max_inflight_per_endpoint=max_inflight,
    )
    return OpenAICompatibleClient(config=config, rate_config=rate)


class _ConcurrencyCounter:
    """Counts simultaneous entries into the faked transport, tracking the peak."""

    def __init__(self, dwell: float = 0.02) -> None:
        self.cur = 0
        self.peak = 0
        self.total = 0
        self._dwell = dwell

    async def call(self, request, model, client, **kwargs) -> LLMResponse:  # noqa: ANN001
        self.cur += 1
        self.total += 1
        self.peak = max(self.peak, self.cur)
        try:
            await asyncio.sleep(self._dwell)
            return LLMResponse(content="ok", model=model, tier="standard")
        finally:
            self.cur -= 1


def _http_429(*, retry_after: str = "0") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://rate-limited.invalid/v1")
    response = httpx.Response(
        429,
        headers={"Retry-After": retry_after},
        request=request,
    )
    return httpx.HTTPStatusError(
        "429 Too Many Requests",
        request=request,
        response=response,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBF654EndpointConcurrencyCap:
    """BF-654: the per-endpoint in-flight cap and its composition with lanes."""

    @pytest.mark.asyncio
    async def test_endpoint_semaphores_created_by_default(self):
        """Default construction (no rate_config) creates the text endpoint cap at 8."""
        client = OpenAICompatibleClient()
        try:
            text_key = client._client_key("standard")
            assert text_key in client._endpoint_semaphores
            assert client._endpoint_semaphores[text_key]._value == 8
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_disabled_when_zero_no_semaphores(self):
        """max_inflight_per_endpoint <= 0 => no endpoint semaphores (escape hatch)."""
        client = _make_client(max_inflight=0)
        try:
            assert client._endpoint_semaphores == {}
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_at_most_N_concurrent_inflight_to_one_endpoint(self):
        """HEADLINE: at most `cap` requests are ever concurrently in flight to
        one endpoint under a 30-call background burst — and the SAME burst
        floods past 8 when the cap is disabled (proving the cap is load-bearing).
        """
        # WITH the cap (8): peak concurrent in-flight to the one text endpoint <= 8.
        counter = _ConcurrencyCounter()
        client = _make_client(max_inflight=8, max_concurrent=100)
        try:
            client._call_api = counter.call
            reqs = [LLMRequest(prompt=f"r{i}", tier="standard") for i in range(30)]
            results = await asyncio.gather(
                *(client.complete(r, priority=Priority.NORMAL) for r in reqs)
            )
            assert len(results) == 30
            assert all(r.content == "ok" for r in results)
            assert counter.total == 30  # every call really reached the transport
            assert counter.peak <= 8, f"endpoint cap breached: peak={counter.peak}"
            assert counter.peak >= 2  # sanity: calls genuinely overlapped
        finally:
            await client.close()

        # COUNTERFACTUAL: with the cap DISABLED, the identical 30-call burst
        # floods the endpoint (peak >> 8) — the BF-654 bug the cap fixes. If
        # this ever fails, the burst isn't 30-wide and the assertion above is
        # vacuous (i.e. the headline would still pass with the cap deleted).
        counter2 = _ConcurrencyCounter()
        disabled = _make_client(max_inflight=0, max_concurrent=100)
        try:
            disabled._call_api = counter2.call
            reqs2 = [LLMRequest(prompt=f"d{i}", tier="standard") for i in range(30)]
            await asyncio.gather(
                *(disabled.complete(r, priority=Priority.NORMAL) for r in reqs2)
            )
            assert counter2.peak > 8, (
                f"burst not wide enough to prove the cap: peak={counter2.peak}"
            )
        finally:
            await disabled.close()

    @pytest.mark.asyncio
    async def test_ollama_endpoint_independent_of_copilot_cap(self):
        """A distinct vision/ollama endpoint gets its own cap; text saturation
        never throttles it."""
        cfg = _make_config(
            llm_base_url_vision="http://127.0.0.1:11434",
            llm_model_vision="qwen2.5vl:3b",
            llm_api_format_vision="ollama",
        )
        client = _make_client(max_inflight=8, max_concurrent=100, config=cfg)
        try:
            text_key = client._client_key("standard")
            vision_key = client._client_key("vision")
            # Two distinct endpoints => two independent caps.
            assert text_key != vision_key
            assert text_key in client._endpoint_semaphores
            assert vision_key in client._endpoint_semaphores

            # Drain the TEXT endpoint cap to zero.
            text_sem = client._endpoint_semaphores[text_key]
            for _ in range(8):
                await text_sem.acquire()
            assert text_sem._value == 0

            # A vision call still completes promptly — its cap is untouched.
            counter = _ConcurrencyCounter()
            client._call_api = counter.call
            result = await asyncio.wait_for(
                client.complete(
                    LLMRequest(prompt="describe", tier="vision"),
                    priority=Priority.NORMAL,
                ),
                timeout=2.0,
            )
            assert result.content == "ok"
            assert text_sem._value == 0  # the vision call never touched the text cap
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_critical_still_bypasses_actual_attempt_endpoint(self):
        """CRITICAL transport enters even when its attempt endpoint is drained."""
        client = _make_client(max_inflight=8, max_concurrent=100)
        text_sem = client._endpoint_semaphores[client._client_key("standard")]
        try:
            for _ in range(8):
                await text_sem.acquire()  # drain to 0
            assert text_sem._value == 0

            transport_entered = asyncio.Event()

            async def critical_call(request, model, client_, **kwargs):  # noqa: ANN001
                transport_entered.set()
                return LLMResponse(content="ok", model=model, tier="standard")

            client._call_api = critical_call

            result = await asyncio.wait_for(
                client.complete(
                    LLMRequest(prompt="captain", tier="standard"),
                    priority=Priority.CRITICAL,
                ),
                timeout=2.0,
            )
            assert result.content == "ok"
            assert transport_entered.is_set()
            # CRITICAL bypassed the cap entirely — the drained sem is untouched.
            assert text_sem._value == 0
        finally:
            for _ in range(8 - text_sem._value):
                text_sem.release()
            await client.close()

    @pytest.mark.asyncio
    async def test_no_deadlock_mixed_priorities(self):
        """Interactive CRITICAL calls proceed while background calls hold the
        endpoint cap — no cyclic wait, no hang."""
        client = _make_client(max_inflight=4, max_concurrent=6, interactive_reserved=2)

        async def fast_call(request, model, client_, **kwargs):  # noqa: ANN001
            await asyncio.sleep(0.01)
            return LLMResponse(content="ok", model=model, tier="standard")

        try:
            client._call_api = fast_call
            tasks = [
                asyncio.create_task(
                    client.complete(
                        LLMRequest(prompt=f"b{i}", tier="standard"),
                        priority=Priority.NORMAL,
                    )
                )
                for i in range(6)
            ]
            tasks += [
                asyncio.create_task(
                    client.complete(
                        LLMRequest(prompt=f"c{i}", tier="standard"),
                        priority=Priority.CRITICAL,
                    )
                )
                for i in range(3)
            ]
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5.0)
            assert len(results) == 9
            assert all(r.content == "ok" for r in results)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_endpoint_timeout_cannot_fail_open_past_cap(self):
        """A long endpoint wait never lets a background herd exceed cap=1."""
        client = _make_client(max_inflight=1, max_concurrent=100)
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        current = 0
        peak = 0
        total = 0

        async def held_call(request, model, client_, **kwargs):  # noqa: ANN001
            nonlocal current, peak, total
            current += 1
            total += 1
            peak = max(peak, current)
            try:
                if total == 1:
                    first_entered.set()
                    await release_first.wait()
                return LLMResponse(content="ok", model=model, tier="standard")
            finally:
                current -= 1

        tasks: list[asyncio.Task[LLMResponse]] = []
        try:
            client._call_api = held_call
            # Counterfactual hook for the removed BF-654 timeout: on the old
            # implementation this short value plus zero jitter lets all four
            # waiters fail open while the first transport remains blocked.
            client._endpoint_acquire_timeout = 0.02
            with patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                tasks = [
                    asyncio.create_task(
                        client.complete(
                            LLMRequest(prompt=f"wait-{i}", tier="standard"),
                            priority=Priority.NORMAL,
                        )
                    )
                    for i in range(5)
                ]
                await asyncio.wait_for(first_entered.wait(), timeout=2.0)
                await asyncio.sleep(0.08)
                assert total == 1
                assert peak == 1
                release_first.set()
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks), timeout=2.0
                )
            assert len(results) == 5
            assert all(result.content == "ok" for result in results)
            assert peak == 1
        finally:
            release_first.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_during_endpoint_wait_restores_lane(self):
        """Cancellation while waiting for the endpoint releases the held lane."""
        client = _make_client(
            max_inflight=1,
            max_concurrent=3,
            interactive_reserved=2,
        )
        endpoint_sem = client._endpoint_semaphores[client._client_key("standard")]
        lane_initial = client._background_semaphore._value
        await endpoint_sem.acquire()
        task = asyncio.create_task(
            client.complete(
                LLMRequest(prompt="cancel-wait", tier="standard"),
                priority=Priority.NORMAL,
            )
        )
        try:
            for _ in range(20):
                if client._background_semaphore._value == lane_initial - 1:
                    break
                await asyncio.sleep(0)
            assert client._background_semaphore._value == lane_initial - 1
            assert endpoint_sem._value == 0

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert client._background_semaphore._value == lane_initial
            assert endpoint_sem._value == 0
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            endpoint_sem.release()
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_during_lane_wait_acquires_no_endpoint_or_lease(self):
        client = _make_client(
            max_inflight=1,
            max_concurrent=3,
            interactive_reserved=2,
        )
        key = client._client_key("standard")
        lane = client._background_semaphore
        endpoint = client._endpoint_semaphores[key]
        state = client._client_pool_states[key]
        await lane.acquire()
        task = asyncio.create_task(
            client.complete(
                LLMRequest(prompt="cancel-lane-wait", tier="standard"),
                priority=Priority.NORMAL,
            )
        )
        try:
            for _ in range(100):
                if lane._waiters:
                    break
                await asyncio.sleep(0)
            assert lane._waiters is not None
            assert len(lane._waiters) == 1
            assert endpoint._value == 1
            assert state.borrowers == {}

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert lane._value == 0
            assert endpoint._value == 1
            assert state.borrowers == {}
            assert state.retired == {}
        finally:
            lane.release()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_during_retry_jitter_restores_lane_and_endpoint(self):
        """Cancellation in BF-612 jitter releases both acquired permits."""
        client = _make_client(
            max_inflight=1,
            max_concurrent=3,
            interactive_reserved=2,
        )
        endpoint_sem = client._endpoint_semaphores[client._client_key("standard")]
        lane_initial = client._background_semaphore._value
        endpoint_initial = endpoint_sem._value
        jitter_entered = asyncio.Event()
        hold_jitter = asyncio.Event()

        async def empty_call(request, model, client_, **kwargs):  # noqa: ANN001
            return LLMResponse(content="", model=model, tier="standard")

        async def blocking_sleep(delay):  # noqa: ANN001
            jitter_entered.set()
            await hold_jitter.wait()

        client._call_api = empty_call
        task: asyncio.Task[LLMResponse] | None = None
        try:
            with patch(
                "probos.cognitive.llm_client.asyncio.sleep", new=blocking_sleep
            ), patch.object(
                client, "_refresh_client", new_callable=AsyncMock
            ) as mock_refresh:
                task = asyncio.create_task(
                    client.complete(
                        LLMRequest(prompt="cancel-jitter", tier="standard"),
                        priority=Priority.NORMAL,
                    )
                )
                await asyncio.wait_for(jitter_entered.wait(), timeout=2.0)
                assert client._background_semaphore._value == lane_initial - 1
                assert endpoint_sem._value == endpoint_initial - 1

                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

                assert client._background_semaphore._value == lane_initial
                assert endpoint_sem._value == endpoint_initial
                mock_refresh.assert_not_awaited()
        finally:
            hold_jitter.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_waiter_resolves_current_client_after_holder_refresh(self):
        """A waiter never retains the client that its permit holder replaces."""
        cfg = _make_config(
            llm_base_url_vision="http://single-openai.invalid/v1",
            llm_model_vision="single-openai-model",
            llm_api_format_vision="openai",
        )
        client = _make_client(
            max_inflight=1,
            max_concurrent=3,
            interactive_reserved=1,
            config=cfg,
        )
        endpoint_key = client._client_key("vision")
        endpoint_sem = client._endpoint_semaphores[endpoint_key]
        old_client = client._clients[endpoint_key]
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        a_calls = 0
        b_observations: list[tuple[bool, bool]] = []
        tasks: list[asyncio.Task[LLMResponse]] = []

        async def empty_refresh_then_success(
            request, model, http_client, **kwargs  # noqa: ANN001
        ):
            nonlocal a_calls
            if request.prompt == "call-a":
                a_calls += 1
                if a_calls == 1:
                    assert http_client is old_client
                    assert not http_client.is_closed
                    first_entered.set()
                    await release_first.wait()
                    return LLMResponse(content="", model=model, tier="vision")
                assert http_client is client._clients[endpoint_key]
                assert not http_client.is_closed
                return LLMResponse(content="a-ok", model=model, tier="vision")

            is_current = http_client is client._clients[endpoint_key]
            is_closed = http_client.is_closed
            b_observations.append((is_current, is_closed))
            if not is_current or is_closed:
                return LLMResponse(
                    content="",
                    model=model,
                    tier="vision",
                    error="waiter received stale client",
                )
            return LLMResponse(content="b-ok", model=model, tier="vision")

        try:
            client._call_api = empty_refresh_then_success
            with patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                tasks.append(
                    asyncio.create_task(
                        client.complete(
                            LLMRequest(prompt="call-a", tier="vision"),
                            priority=Priority.NORMAL,
                        )
                    )
                )
                await asyncio.wait_for(first_entered.wait(), timeout=2.0)

                tasks.append(
                    asyncio.create_task(
                        client.complete(
                            LLMRequest(prompt="call-b", tier="vision"),
                            priority=Priority.NORMAL,
                        )
                    )
                )
                for _ in range(100):
                    if endpoint_sem._waiters and len(endpoint_sem._waiters) == 1:
                        break
                    await asyncio.sleep(0)
                assert endpoint_sem._waiters is not None
                assert len(endpoint_sem._waiters) == 1

                release_first.set()
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks), timeout=2.0
                )

            assert [result.content for result in results] == ["a-ok", "b-ok"]
            assert old_client.is_closed
            assert client._clients[endpoint_key] is not old_client
            assert b_observations == [(True, False)]
            assert endpoint_sem._value == 1
        finally:
            release_first.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_inside_initial_call_restores_lane_and_endpoint(self):
        """Cancellation in the initial transport propagates without leaks."""
        client = _make_client(
            max_inflight=1,
            max_concurrent=3,
            interactive_reserved=2,
        )
        endpoint_sem = client._endpoint_semaphores[client._client_key("standard")]
        lane_initial = client._background_semaphore._value
        endpoint_initial = endpoint_sem._value
        call_entered = asyncio.Event()
        hold_call = asyncio.Event()

        async def blocking_call(request, model, http_client, **kwargs):  # noqa: ANN001
            call_entered.set()
            await hold_call.wait()
            return LLMResponse(content="late", model=model, tier="standard")

        client._call_api = blocking_call
        task = asyncio.create_task(
            client.complete(
                LLMRequest(prompt="cancel-initial", tier="standard"),
                priority=Priority.NORMAL,
            )
        )
        try:
            await asyncio.wait_for(call_entered.wait(), timeout=2.0)
            assert client._background_semaphore._value == lane_initial - 1
            assert endpoint_sem._value == endpoint_initial - 1

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert client._background_semaphore._value == lane_initial
            assert endpoint_sem._value == endpoint_initial
        finally:
            hold_call.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_post_swap_retirement_close_drains_then_propagates(self):
        """Cancellation after the atomic swap drains old-generation close."""
        client = _make_client(
            max_inflight=1,
            max_concurrent=3,
            interactive_reserved=2,
        )
        endpoint_key = client._client_key("standard")
        endpoint_sem = client._endpoint_semaphores[endpoint_key]
        old_client = client._clients[endpoint_key]
        lane_initial = client._background_semaphore._value
        endpoint_initial = endpoint_sem._value
        close_entered = asyncio.Event()
        hold_close = asyncio.Event()
        close_calls = 0

        async def empty_call(request, model, http_client, **kwargs):  # noqa: ANN001
            return LLMResponse(content="", model=model, tier="standard")

        async def blocking_close() -> None:
            nonlocal close_calls
            close_calls += 1
            close_entered.set()
            await hold_close.wait()

        client._call_api = empty_call
        task: asyncio.Task[LLMResponse] | None = None
        try:
            with patch.object(old_client, "aclose", new=blocking_close), patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                task = asyncio.create_task(
                    client.complete(
                        LLMRequest(prompt="cancel-refresh", tier="standard"),
                        priority=Priority.NORMAL,
                    )
                )
                await asyncio.wait_for(close_entered.wait(), timeout=2.0)
                assert client._background_semaphore._value == lane_initial - 1
                assert endpoint_sem._value == endpoint_initial - 1
                assert client._clients[endpoint_key] is not old_client
                assert client._client_pool_states[endpoint_key].generation == 1
                assert 0 in client._client_pool_states[endpoint_key].retirement_closes

                task.cancel()
                await asyncio.sleep(0)
                assert task.done() is False
                hold_close.set()
                with pytest.raises(asyncio.CancelledError):
                    await task

                assert client._background_semaphore._value == lane_initial
                assert endpoint_sem._value == endpoint_initial
                assert client._clients[endpoint_key] is not old_client
                assert client._client_pool_states[endpoint_key].generation == 1
                assert client._client_pool_states[endpoint_key].retired == {}
                assert client._client_pool_states[endpoint_key].retirement_closes == {}
                assert close_calls == 1
        finally:
            hold_close.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_retry_transport_releases_new_generation_lease(self):
        """Cancellation in BF-612's second transport restores both permits."""
        client = _make_client(
            max_inflight=1,
            max_concurrent=3,
            interactive_reserved=2,
        )
        endpoint_key = client._client_key("standard")
        endpoint_sem = client._endpoint_semaphores[endpoint_key]
        old_client = client._clients[endpoint_key]
        lane_initial = client._background_semaphore._value
        endpoint_initial = endpoint_sem._value
        second_entered = asyncio.Event()
        hold_second = asyncio.Event()
        calls = 0
        second_used_current = False

        async def empty_then_block(
            request, model, http_client, **kwargs  # noqa: ANN001
        ):
            nonlocal calls, second_used_current
            calls += 1
            if calls == 1:
                assert http_client is old_client
                return LLMResponse(content="", model=model, tier="standard")
            second_used_current = (
                http_client is client._clients[endpoint_key]
                and not http_client.is_closed
            )
            second_entered.set()
            await hold_second.wait()
            return LLMResponse(content="late", model=model, tier="standard")

        client._call_api = empty_then_block
        task: asyncio.Task[LLMResponse] | None = None
        try:
            with patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                task = asyncio.create_task(
                    client.complete(
                        LLMRequest(prompt="cancel-second", tier="standard"),
                        priority=Priority.NORMAL,
                    )
                )
                await asyncio.wait_for(second_entered.wait(), timeout=2.0)
                assert calls == 2
                assert second_used_current
                assert old_client.is_closed
                assert client._background_semaphore._value == lane_initial - 1
                assert endpoint_sem._value == endpoint_initial - 1

                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

                assert client._background_semaphore._value == lane_initial
                assert endpoint_sem._value == endpoint_initial
        finally:
            hold_second.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_during_429_backoff_restores_lane_and_endpoint(self):
        """Cancellation in AD-617 backoff propagates and restores permits."""
        client = _make_client(
            max_inflight=1,
            max_concurrent=3,
            interactive_reserved=2,
        )
        endpoint_sem = client._endpoint_semaphores[client._client_key("fast")]
        lane_initial = client._background_semaphore._value
        endpoint_initial = endpoint_sem._value
        backoff_entered = asyncio.Event()
        hold_backoff = asyncio.Event()
        calls = 0

        async def rate_limited(request, model, http_client, **kwargs):  # noqa: ANN001
            nonlocal calls
            calls += 1
            raise _http_429(retry_after="60")

        async def blocking_backoff(delay):  # noqa: ANN001
            backoff_entered.set()
            await hold_backoff.wait()

        client._call_api = rate_limited
        task: asyncio.Task[LLMResponse] | None = None
        try:
            with patch(
                "probos.cognitive.llm_client.asyncio.sleep", new=blocking_backoff
            ):
                task = asyncio.create_task(
                    client.complete(
                        LLMRequest(prompt="cancel-429", tier="fast"),
                        priority=Priority.NORMAL,
                    )
                )
                await asyncio.wait_for(backoff_entered.wait(), timeout=2.0)
                assert calls == 1
                assert client._background_semaphore._value == lane_initial - 1
                assert endpoint_sem._value == endpoint_initial - 1

                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

                assert client._background_semaphore._value == lane_initial
                assert endpoint_sem._value == endpoint_initial
        finally:
            hold_backoff.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_nested_priority_context_restores_direct_default_governance(self):
        """Nested NORMAL overrides CRITICAL, then direct calls regain default."""
        cfg = _make_config(
            llm_base_url_vision="http://nested-openai.invalid/v1",
            llm_model_vision="nested-openai-model",
            llm_api_format_vision="openai",
        )
        client = _make_client(
            max_inflight=1,
            max_concurrent=3,
            interactive_reserved=1,
            config=cfg,
        )
        endpoint_sem = client._endpoint_semaphores[client._client_key("vision")]
        interactive_initial = client._interactive_semaphore._value
        background_initial = client._background_semaphore._value
        endpoint_initial = endpoint_sem._value
        endpoint_values: list[tuple[str, int]] = []
        direct_entered = asyncio.Event()

        async def nested_call(request, model, http_client, **kwargs):  # noqa: ANN001
            endpoint_values.append((request.prompt, endpoint_sem._value))
            if request.prompt == "outer-critical":
                nested = await client.complete(
                    LLMRequest(prompt="nested-normal", tier="vision"),
                    priority=Priority.NORMAL,
                )
                assert nested.content == "nested-ok"
                outer_probe = await client._complete_inner(
                    LLMRequest(prompt="outer-after-nested", tier="vision")
                )
                assert outer_probe.content == "outer-probe-ok"
                return LLMResponse(content="outer-ok", model=model, tier="vision")
            if request.prompt == "direct-after":
                direct_entered.set()
                return LLMResponse(content="direct-ok", model=model, tier="vision")
            if request.prompt == "outer-after-nested":
                return LLMResponse(
                    content="outer-probe-ok", model=model, tier="vision"
                )
            return LLMResponse(content="nested-ok", model=model, tier="vision")

        client._call_api = nested_call
        direct_task: asyncio.Task[LLMResponse] | None = None
        endpoint_preheld = False
        try:
            outer = await client.complete(
                LLMRequest(prompt="outer-critical", tier="vision"),
                priority=Priority.CRITICAL,
            )
            assert outer.content == "outer-ok"
            assert endpoint_values == [
                ("outer-critical", 1),
                ("nested-normal", 0),
                ("outer-after-nested", 1),
            ]
            assert client._interactive_semaphore._value == interactive_initial
            assert client._background_semaphore._value == background_initial
            assert endpoint_sem._value == endpoint_initial

            await endpoint_sem.acquire()
            endpoint_preheld = True
            direct_task = asyncio.create_task(
                client._complete_inner(
                    LLMRequest(prompt="direct-after", tier="vision")
                )
            )
            for _ in range(100):
                if direct_entered.is_set() or endpoint_sem._waiters:
                    break
                await asyncio.sleep(0)
            assert not direct_entered.is_set()
            assert endpoint_sem._waiters is not None
            assert len(endpoint_sem._waiters) == 1

            endpoint_sem.release()
            endpoint_preheld = False
            direct = await asyncio.wait_for(direct_task, timeout=2.0)
            assert direct.content == "direct-ok"
            assert endpoint_sem._value == endpoint_initial
        finally:
            if endpoint_preheld:
                endpoint_sem.release()
            if direct_task is not None and not direct_task.done():
                direct_task.cancel()
                await asyncio.gather(direct_task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_lane_timeout_stays_endpoint_governed_without_overrelease(self):
        """NORMAL lane fail-open neither bypasses endpoint nor releases lane."""
        client = _make_client(
            max_inflight=1,
            max_concurrent=3,
            interactive_reserved=2,
        )
        lane_sem = client._background_semaphore
        endpoint_sem = client._endpoint_semaphores[client._client_key("standard")]
        lane_initial = lane_sem._value
        endpoint_initial = endpoint_sem._value
        endpoint_values: list[int] = []

        async def governed_call(request, model, http_client, **kwargs):  # noqa: ANN001
            endpoint_values.append(endpoint_sem._value)
            return LLMResponse(content="ok", model=model, tier="standard")

        client._call_api = governed_call
        try:
            with patch.object(
                lane_sem,
                "acquire",
                new_callable=AsyncMock,
                side_effect=asyncio.TimeoutError,
            ) as mock_acquire:
                result = await client.complete(
                    LLMRequest(prompt="lane-timeout", tier="standard"),
                    priority=Priority.NORMAL,
                )

            assert result.content == "ok"
            mock_acquire.assert_awaited_once()
            assert endpoint_values == [endpoint_initial - 1]
            assert endpoint_sem._value == endpoint_initial
            assert lane_sem._value == lane_initial
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_fallback_uses_actual_target_endpoint_cap(self):
        """Distinct fast→deep fallback waits for and respects deep's cap."""
        cfg = _make_config(
            llm_base_url_fast="http://fast.invalid/v1",
            llm_base_url_standard="http://standard.invalid/v1",
            llm_base_url_deep="http://deep.invalid/v1",
        )
        client = _make_client(
            max_inflight=1,
            max_concurrent=100,
            config=cfg,
        )
        deep_sem = client._endpoint_semaphores[client._client_key("deep")]
        await deep_sem.acquire()
        deep_preheld = True
        standard_failures = 0
        both_waiting_for_deep = asyncio.Event()
        deep_current = 0
        deep_peak = 0
        deep_total = 0

        async def fallback_call(request, model, http_client, **kwargs):  # noqa: ANN001
            nonlocal standard_failures, deep_current, deep_peak, deep_total
            url = str(http_client.base_url)
            if "fast.invalid" in url:
                raise httpx.ConnectError("force fast fallback")
            if "standard.invalid" in url:
                standard_failures += 1
                if standard_failures == 2:
                    both_waiting_for_deep.set()
                raise httpx.ConnectError("force standard fallback")
            assert "deep.invalid" in url
            deep_current += 1
            deep_total += 1
            deep_peak = max(deep_peak, deep_current)
            try:
                await asyncio.sleep(0.01)
                return LLMResponse(content="deep-ok", model=model, tier="deep")
            finally:
                deep_current -= 1

        tasks: list[asyncio.Task[LLMResponse]] = []
        try:
            client._call_api = fallback_call
            tasks = [
                asyncio.create_task(
                    client.complete(
                        LLMRequest(prompt=f"fallback-{i}", tier="fast"),
                        priority=Priority.NORMAL,
                    )
                )
                for i in range(2)
            ]
            await asyncio.wait_for(both_waiting_for_deep.wait(), timeout=2.0)
            await asyncio.sleep(0)
            assert deep_total == 0

            deep_sem.release()
            deep_preheld = False
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=2.0)

            assert [result.content for result in results] == ["deep-ok", "deep-ok"]
            assert deep_total == 2
            assert deep_peak == 1
        finally:
            if deep_preheld:
                deep_sem.release()
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_permit_covers_bf612_retry(self):
        """The same endpoint permit remains held for both BF-612 transports."""
        client = _make_client(max_inflight=1, max_concurrent=100)
        endpoint_sem = client._endpoint_semaphores[client._client_key("standard")]
        permit_values: list[int] = []
        responses = [
            LLMResponse(content="", model="test", tier="standard"),
            LLMResponse(content="recovered", model="test", tier="standard"),
        ]

        async def empty_then_full(request, model, http_client, **kwargs):  # noqa: ANN001
            permit_values.append(endpoint_sem._value)
            return responses.pop(0)

        try:
            client._call_api = empty_then_full
            with patch.object(
                client, "_refresh_client", wraps=client._refresh_client
            ), patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                result = await client.complete(
                    LLMRequest(prompt="bf612", tier="standard"),
                    priority=Priority.NORMAL,
                )

            assert result.content == "recovered"
            assert permit_values == [0, 0]
            assert endpoint_sem._value == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_permit_covers_429_backoff_and_retry(self):
        """The endpoint permit stays held through 429 backoff and retry."""
        client = _make_client(max_inflight=1, max_concurrent=100)
        endpoint_sem = client._endpoint_semaphores[client._client_key("fast")]
        permit_values: list[int] = []
        backoff_values: list[int] = []

        async def rate_limited_then_full(request, model, http_client, **kwargs):  # noqa: ANN001
            permit_values.append(endpoint_sem._value)
            if len(permit_values) == 1:
                raise _http_429()
            return LLMResponse(content="ok", model=model, tier="fast")

        async def observe_backoff(delay):  # noqa: ANN001
            backoff_values.append(endpoint_sem._value)

        try:
            client._call_api = rate_limited_then_full
            with patch(
                "probos.cognitive.llm_client.asyncio.sleep", new=observe_backoff
            ):
                result = await client.complete(
                    LLMRequest(prompt="429", tier="fast"),
                    priority=Priority.NORMAL,
                )

            assert result.content == "ok"
            assert permit_values == [0, 0]
            assert backoff_values == [0]
            assert endpoint_sem._value == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_direct_complete_inner_call_is_background_governed(self):
        """Direct `_complete_inner()` callers inherit background governance."""
        client = _make_client(max_inflight=1, max_concurrent=100)
        counter = _ConcurrencyCounter(dwell=0.02)
        try:
            client._call_api = counter.call
            results = await asyncio.gather(
                client._complete_inner(
                    LLMRequest(prompt="direct-1", tier="standard")
                ),
                client._complete_inner(
                    LLMRequest(prompt="direct-2", tier="standard")
                ),
            )

            assert [result.content for result in results] == ["ok", "ok"]
            assert counter.total == 2
            assert counter.peak == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_default_safe_byte_identical_path(self):
        """max_inflight_per_endpoint <= 0: no endpoint semaphores and no acquire
        attempt — byte-identical to pre-BF-654."""
        client = _make_client(max_inflight=0, max_concurrent=100)
        try:
            assert client._endpoint_semaphores == {}
            mock_resp = LLMResponse(content="ok", model="t", tier="standard")
            client._complete_inner = AsyncMock(return_value=mock_resp)
            result = await client.complete(
                LLMRequest(prompt="x", tier="standard"), priority=Priority.NORMAL
            )
            assert result.content == "ok"
            assert client._complete_inner.await_count == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_endpoint_semaphores_keyed_per_client_key(self):
        """The endpoint semaphore dict is keyed by _client_key (base_url|format),
        so text tiers collapse to one shared cap and vision keeps its own."""
        cfg = _make_config(
            llm_base_url_vision="http://127.0.0.1:11434",
            llm_model_vision="qwen2.5vl:3b",
            llm_api_format_vision="ollama",
        )
        client = _make_client(max_inflight=8, config=cfg)
        try:
            # fast/standard/deep all resolve to the one Copilot-proxy key.
            assert (
                client._client_key("fast")
                == client._client_key("standard")
                == client._client_key("deep")
            )
            text_sem = client._endpoint_semaphores[client._client_key("standard")]
            assert client._endpoint_semaphores[client._client_key("fast")] is text_sem
            assert client._endpoint_semaphores[client._client_key("deep")] is text_sem
            # vision is a separate key => a separate semaphore object.
            vision_sem = client._endpoint_semaphores[client._client_key("vision")]
            assert vision_sem is not text_sem
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_bf612_jitter_only_when_cap_enabled(self):
        """The BF-612 empty-200 recycle jitter fires only when the endpoint cap
        is enabled; a disabled client's retry path is byte-identical (no jitter).
        """
        empty = LLMResponse(content="", model="claude-sonnet-4.6", tier="standard")
        full = LLMResponse(content="hi", model="claude-sonnet-4.6", tier="standard")

        # ENABLED (default 8, no rate_config): the retry path jitters exactly once.
        enabled = OpenAICompatibleClient(config=_make_config())
        try:
            assert enabled._endpoint_semaphores  # cap enabled
            with patch.object(
                enabled, "_call_api", new_callable=AsyncMock, side_effect=[empty, full]
            ), patch.object(
                enabled, "_refresh_client", wraps=enabled._refresh_client
            ), patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ) as mock_unif:
                result = await enabled.complete(LLMRequest(prompt="hi", tier="standard"))
                assert result.content == "hi"
                assert mock_unif.call_count == 1  # jitter fired
        finally:
            await enabled.close()

        # DISABLED (0): identical retry path, NO jitter added.
        disabled = OpenAICompatibleClient(
            config=_make_config(),
            rate_config=_FakeRateConfig(max_inflight_per_endpoint=0),
        )
        try:
            assert disabled._endpoint_semaphores == {}  # cap disabled
            with patch.object(
                disabled, "_call_api", new_callable=AsyncMock, side_effect=[empty, full]
            ), patch.object(
                disabled, "_refresh_client", wraps=disabled._refresh_client
            ), patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ) as mock_unif2:
                result2 = await disabled.complete(LLMRequest(prompt="hi", tier="standard"))
                assert result2.content == "hi"
                assert mock_unif2.call_count == 0  # byte-identical: no jitter
        finally:
            await disabled.close()

    @pytest.mark.asyncio
    async def test_refresh_does_not_close_inflight_peer_at_cap_gt_one(self):
        client = _make_client(max_inflight=2, max_concurrent=100)
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        old = client._clients[key]
        peer_entered = asyncio.Event()
        release_peer = asyncio.Event()
        peer_saw_open_after_swap = False
        calls: dict[str, int] = {"empty": 0, "peer": 0}

        async def transport(request, model, http_client, **kwargs):  # noqa: ANN001
            nonlocal peer_saw_open_after_swap
            calls[request.prompt] += 1
            if request.prompt == "peer":
                assert http_client is old
                peer_entered.set()
                await release_peer.wait()
                peer_saw_open_after_swap = not http_client.is_closed
                return LLMResponse(content="peer-ok", model=model, tier="standard")
            if calls["empty"] == 1:
                await peer_entered.wait()
                return LLMResponse(content="", model=model, tier="standard")
            assert http_client is client._clients[key]
            assert http_client is not old
            return LLMResponse(content="refreshed", model=model, tier="standard")

        client._call_api = transport
        tasks: list[asyncio.Task[LLMResponse]] = []
        try:
            with patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                tasks = [
                    asyncio.create_task(
                        client.complete(LLMRequest(prompt="peer", tier="standard"))
                    ),
                    asyncio.create_task(
                        client.complete(LLMRequest(prompt="empty", tier="standard"))
                    ),
                ]
                await asyncio.wait_for(peer_entered.wait(), timeout=2.0)
                while state.generation == 0:
                    await asyncio.sleep(0)
                assert state.generation == 1
                assert state.borrowers.get(0) == 1
                assert state.borrowers.get(1, 0) <= 1
                assert state.retired == {0: old}
                assert old.is_closed is False
                release_peer.set()
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks), timeout=2.0
                )

            assert [result.content for result in results] == ["peer-ok", "refreshed"]
            assert peer_saw_open_after_swap is True
            assert old.is_closed is True
            assert state.borrowers == {}
            assert state.retired == {}
        finally:
            release_peer.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_concurrent_empty_callers_swap_one_observed_generation(self):
        client = _make_client(max_inflight=4, max_concurrent=100)
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        old = client._clients[key]
        all_initial_entered = asyncio.Event()
        release_initial = asyncio.Event()
        initial_count = 0
        seen_clients: list[httpx.AsyncClient] = []
        built: list[httpx.AsyncClient] = []
        original_build = client._build_client

        def counted_build(tier: str) -> httpx.AsyncClient:
            replacement = original_build(tier)
            built.append(replacement)
            return replacement

        async def transport(request, model, http_client, **kwargs):  # noqa: ANN001
            nonlocal initial_count
            seen_clients.append(http_client)
            if http_client is old:
                initial_count += 1
                if initial_count == 4:
                    all_initial_entered.set()
                await release_initial.wait()
                return LLMResponse(content="", model=model, tier="standard")
            return LLMResponse(content="ok", model=model, tier="standard")

        client._call_api = transport
        client._build_client = counted_build
        tasks = [
            asyncio.create_task(
                client.complete(LLMRequest(prompt=f"empty-{i}", tier="standard"))
            )
            for i in range(4)
        ]
        try:
            with patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                await asyncio.wait_for(all_initial_entered.wait(), timeout=2.0)
                assert state.borrowers == {0: 4}
                release_initial.set()
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks), timeout=2.0
                )

            assert all(result.content == "ok" for result in results)
            assert len(built) == 1
            assert state.generation == 1
            assert client._clients[key] is built[0]
            assert seen_clients.count(old) == 4
            assert seen_clients.count(built[0]) == 4
            assert old.is_closed is True
            assert state.borrowers == {}
            assert state.retired == {}
        finally:
            release_initial.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_stale_empty_observer_retries_installed_generation_without_second_swap(self):
        client = _make_client(max_inflight=2, max_concurrent=100)
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        old = client._clients[key]
        both_initial_entered = asyncio.Event()
        release_initial = asyncio.Event()
        initial_count = 0
        build_count = 0
        original_build = client._build_client

        def counted_build(tier: str) -> httpx.AsyncClient:
            nonlocal build_count
            build_count += 1
            return original_build(tier)

        async def transport(request, model, http_client, **kwargs):  # noqa: ANN001
            nonlocal initial_count
            if http_client is old:
                initial_count += 1
                if initial_count == 2:
                    both_initial_entered.set()
                await release_initial.wait()
                return LLMResponse(content="", model=model, tier="standard")
            return LLMResponse(
                content=f"new-{request.prompt}", model=model, tier="standard"
            )

        client._build_client = counted_build
        client._call_api = transport
        tasks = [
            asyncio.create_task(
                client.complete(LLMRequest(prompt="a", tier="standard"))
            ),
            asyncio.create_task(
                client.complete(LLMRequest(prompt="b", tier="standard"))
            ),
        ]
        try:
            with patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                await asyncio.wait_for(both_initial_entered.wait(), timeout=2.0)
                release_initial.set()
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks), timeout=2.0
                )

            assert {result.content for result in results} == {"new-a", "new-b"}
            assert build_count == 1
            assert state.generation == 1
            assert state.borrowers == {}
            assert state.retired == {}
        finally:
            release_initial.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_retired_generation_closes_only_after_final_borrower(self):
        client = _make_client(max_inflight=2)
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        old = client._clients[key]
        first_exit = asyncio.Event()
        second_exit = asyncio.Event()
        first_entered = asyncio.Event()
        second_entered = asyncio.Event()

        async def borrower(exit_event: asyncio.Event, entered: asyncio.Event) -> None:
            async with client._client_lease("standard") as lease:
                assert lease.client is old
                entered.set()
                await exit_event.wait()

        first = asyncio.create_task(borrower(first_exit, first_entered))
        second = asyncio.create_task(borrower(second_exit, second_entered))
        try:
            await asyncio.wait_for(
                asyncio.gather(first_entered.wait(), second_entered.wait()),
                timeout=2.0,
            )
            assert state.borrowers == {0: 2}
            assert await client._refresh_client(
                "standard", observed_generation=0
            ) is True
            assert old.is_closed is False
            assert state.retired == {0: old}

            first_exit.set()
            await asyncio.wait_for(first, timeout=2.0)
            assert old.is_closed is False
            assert state.borrowers == {0: 1}

            second_exit.set()
            await asyncio.wait_for(second, timeout=2.0)
            assert old.is_closed is True
            assert state.borrowers == {}
            assert state.retired == {}
        finally:
            first_exit.set()
            second_exit.set()
            for task in (first, second):
                if not task.done():
                    task.cancel()
            await asyncio.gather(first, second, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_critical_bypasses_cap_but_holds_lifetime_lease(self):
        client = _make_client(max_inflight=1, max_concurrent=3, interactive_reserved=1)
        key = client._client_key("standard")
        endpoint = client._endpoint_semaphores[key]
        state = client._client_pool_states[key]
        observed: list[tuple[int, dict[int, int]]] = []

        async def transport(request, model, http_client, **kwargs):  # noqa: ANN001
            observed.append((endpoint._value, dict(state.borrowers)))
            return LLMResponse(content="ok", model=model, tier="standard")

        await endpoint.acquire()
        try:
            client._call_api = transport
            result = await client.complete(
                LLMRequest(prompt="critical-lease", tier="standard"),
                priority=Priority.CRITICAL,
            )
            assert result.content == "ok"
            assert observed == [(0, {0: 1})]
            assert state.borrowers == {}
            assert state.borrowers_zero.is_set()
        finally:
            endpoint.release()
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_waiting_refresh_lock_restores_lane_endpoint_and_state(self):
        client = _make_client(max_inflight=1, max_concurrent=3, interactive_reserved=2)
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        endpoint = client._endpoint_semaphores[key]
        lane = client._background_semaphore
        old = client._clients[key]
        await state.refresh_lock.acquire()

        async def empty(request, model, http_client, **kwargs):  # noqa: ANN001
            return LLMResponse(content="", model=model, tier="standard")

        client._call_api = empty
        task: asyncio.Task[LLMResponse] | None = None
        try:
            with patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                task = asyncio.create_task(
                    client.complete(LLMRequest(prompt="refresh-wait", tier="standard"))
                )
                for _ in range(100):
                    if state.refresh_lock._waiters:
                        break
                    await asyncio.sleep(0)
                assert state.refresh_lock._waiters is not None
                assert len(state.refresh_lock._waiters) == 1
                assert state.borrowers == {}
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

            assert lane._value == 1
            assert endpoint._value == 1
            assert state.generation == 0
            assert client._clients[key] is old
            assert state.borrowers == {}
            assert state.retired == {}
        finally:
            state.refresh_lock.release()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_waiting_lease_state_lock_restores_lane_endpoint_and_state(self):
        client = _make_client(max_inflight=1, max_concurrent=3, interactive_reserved=2)
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        endpoint = client._endpoint_semaphores[key]
        lane = client._background_semaphore
        old = client._clients[key]
        await state.state_lock.acquire()
        task = asyncio.create_task(
            client.complete(LLMRequest(prompt="lease-lock-wait", tier="standard"))
        )
        try:
            for _ in range(100):
                if state.state_lock._waiters:
                    break
                await asyncio.sleep(0)
            assert state.state_lock._waiters is not None
            assert len(state.state_lock._waiters) == 1
            assert lane._value == 0
            assert endpoint._value == 0
            assert state.borrowers == {}

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert lane._value == 1
            assert endpoint._value == 1
            assert state.generation == 0
            assert client._clients[key] is old
            assert state.borrowers == {}
            assert state.retired == {}
        finally:
            state.state_lock.release()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_waiting_swap_state_lock_makes_no_mutation(self):
        client = _make_client(max_inflight=1)
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        old = client._clients[key]
        await state.state_lock.acquire()
        task = asyncio.create_task(
            client._refresh_client("standard", observed_generation=0)
        )
        try:
            for _ in range(100):
                if state.state_lock._waiters:
                    break
                await asyncio.sleep(0)
            assert state.state_lock._waiters is not None
            assert len(state.state_lock._waiters) == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert state.generation == 0
            assert client._clients[key] is old
            assert state.retired == {}
        finally:
            state.state_lock.release()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_cancel_final_borrower_cleanup_closes_once_and_leaves_no_task(self):
        client = _make_client(max_inflight=1)
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        old = client._clients[key]
        lease_entered = asyncio.Event()
        release_lease = asyncio.Event()
        close_entered = asyncio.Event()
        release_close = asyncio.Event()
        close_calls = 0

        async def blocking_close() -> None:
            nonlocal close_calls
            close_calls += 1
            close_entered.set()
            await release_close.wait()

        async def borrower() -> None:
            async with client._client_lease("standard"):
                lease_entered.set()
                await release_lease.wait()

        task: asyncio.Task[None] | None = None
        try:
            with patch.object(old, "aclose", new=blocking_close):
                task = asyncio.create_task(borrower())
                await asyncio.wait_for(lease_entered.wait(), timeout=2.0)
                assert await client._refresh_client(
                    "standard", observed_generation=0
                ) is True
                release_lease.set()
                await asyncio.wait_for(close_entered.wait(), timeout=2.0)
                task.cancel()
                await asyncio.sleep(0)
                assert task.done() is False
                release_close.set()
                with pytest.raises(asyncio.CancelledError):
                    await task

            assert close_calls == 1
            assert state.borrowers == {}
            assert state.retired == {}
            assert state.retirement_closes == {}
            await asyncio.sleep(0)
            assert not any(
                pending.get_name().startswith("probos-llm-client-")
                for pending in asyncio.all_tasks()
                if pending is not asyncio.current_task() and not pending.done()
            )
        finally:
            release_lease.set()
            release_close.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.close()

    @pytest.mark.asyncio
    async def test_close_waits_for_active_generation_lease_then_closes_once(self):
        client = _make_client()
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        current = client._clients[key]
        lease_entered = asyncio.Event()
        release_lease = asyncio.Event()
        close_calls = 0
        original_close = current.aclose

        async def counted_close() -> None:
            nonlocal close_calls
            close_calls += 1
            await original_close()

        async def borrower() -> None:
            async with client._client_lease("standard"):
                lease_entered.set()
                await release_lease.wait()

        borrower_task = asyncio.create_task(borrower())
        close_task: asyncio.Task[None] | None = None
        try:
            with patch.object(current, "aclose", new=counted_close):
                await asyncio.wait_for(lease_entered.wait(), timeout=2.0)
                close_task = asyncio.create_task(client.close())
                while not client._closing:
                    await asyncio.sleep(0)
                assert close_task.done() is False
                assert close_calls == 0
                assert state.borrowers == {0: 1}
                release_lease.set()
                await asyncio.wait_for(borrower_task, timeout=2.0)
                await asyncio.wait_for(close_task, timeout=2.0)
            assert close_calls == 1
            assert client._closed is True
            assert state.closed is True
            assert state.borrowers == {}
            assert state.retired == {}
        finally:
            release_lease.set()
            for task in (borrower_task, close_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (borrower_task, close_task) if task is not None),
                return_exceptions=True,
            )
            if not client._closed:
                await client.close()

    @pytest.mark.asyncio
    async def test_close_closes_current_and_retired_distinct_clients_once(self):
        client = _make_client()
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        retired = client._clients[key]
        current = client._build_client("standard")
        assert current is not retired
        retired_close_entered = asyncio.Event()
        release_retired_close = asyncio.Event()
        current_close_finished = asyncio.Event()
        close_waiting_for_retirement = asyncio.Event()
        close_calls = {"retired": 0, "current": 0}
        retired_close = retired.aclose
        current_close = current.aclose
        refresh_task: asyncio.Task[bool] | None = None
        close_task: asyncio.Task[None] | None = None

        async def blocking_retired_close() -> None:
            close_calls["retired"] += 1
            retired_close_entered.set()
            await release_retired_close.wait()
            await retired_close()

        async def counted_current_close() -> None:
            close_calls["current"] += 1
            await current_close()
            current_close_finished.set()

        try:
            with patch.object(
                client, "_build_client", return_value=current
            ), patch.object(
                retired, "aclose", new=blocking_retired_close
            ), patch.object(
                current, "aclose", new=counted_current_close
            ):
                refresh_task = asyncio.create_task(
                    client._refresh_client("standard", observed_generation=0)
                )
                await asyncio.wait_for(retired_close_entered.wait(), timeout=2.0)
                assert state.generation == 1
                assert client._clients[key] is current
                assert close_calls == {"retired": 1, "current": 0}
                assert state.borrowers == {}
                assert state.retired == {}
                assert set(state.retirement_closes) == {0}
                assert retired.is_closed is False
                retirement_event = state.retirement_closes[0]
                assert retirement_event.is_set() is False
                retirement_wait = retirement_event.wait

                async def observed_retirement_wait() -> bool:
                    close_waiting_for_retirement.set()
                    return await retirement_wait()

                with patch.object(
                    retirement_event, "wait", new=observed_retirement_wait
                ):
                    close_task = asyncio.create_task(client.close())
                    await asyncio.wait_for(
                        current_close_finished.wait(), timeout=2.0
                    )
                    await asyncio.wait_for(
                        close_waiting_for_retirement.wait(), timeout=2.0
                    )
                    assert close_task.done() is False
                    assert retirement_event.is_set() is False
                    assert close_calls == {"retired": 1, "current": 1}
                    release_retired_close.set()
                    assert await asyncio.wait_for(refresh_task, timeout=2.0) is True
                    await asyncio.wait_for(close_task, timeout=2.0)

            assert retired.is_closed is True
            assert current.is_closed is True
            assert close_calls == {"retired": 1, "current": 1}
            assert client._clients == {}
            assert state.borrowers == {}
            assert state.retired == {}
            assert state.retirement_closes == {}
            assert all(
                pool_state.borrowers == {}
                and pool_state.retired == {}
                and pool_state.retirement_closes == {}
                for pool_state in client._client_pool_states.values()
            )
        finally:
            release_retired_close.set()
            for task in (refresh_task, close_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (refresh_task, close_task) if task is not None),
                return_exceptions=True,
            )
            if not client._closed:
                await client.close()
            if not current.is_closed:
                await current.aclose()

    @pytest.mark.asyncio
    async def test_close_rejects_new_lease_after_closing_begins(self):
        client = _make_client()
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        lease_entered = asyncio.Event()
        release_lease = asyncio.Event()

        async def borrower() -> None:
            async with client._client_lease("standard"):
                lease_entered.set()
                await release_lease.wait()

        borrower_task = asyncio.create_task(borrower())
        close_task: asyncio.Task[None] | None = None
        try:
            await asyncio.wait_for(lease_entered.wait(), timeout=2.0)
            close_task = asyncio.create_task(client.close())
            while not state.closing:
                await asyncio.sleep(0)
            with pytest.raises(RuntimeError, match="closing"):
                async with client._client_lease("standard"):
                    pytest.fail("closing client admitted a new lease")
            assert state.borrowers == {0: 1}
            release_lease.set()
            await asyncio.wait_for(borrower_task, timeout=2.0)
            await asyncio.wait_for(close_task, timeout=2.0)
        finally:
            release_lease.set()
            for task in (borrower_task, close_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (borrower_task, close_task) if task is not None),
                return_exceptions=True,
            )
            if not client._closed:
                await client.close()

    @pytest.mark.asyncio
    async def test_refresh_waiter_cannot_publish_after_close_begins(self):
        client = _make_client()
        key = client._client_key("standard")
        state = client._client_pool_states[key]
        old = client._clients[key]
        await state.refresh_lock.acquire()
        refresh_task = asyncio.create_task(
            client._refresh_client("standard", observed_generation=0)
        )
        close_task = asyncio.create_task(client.close())
        try:
            while not state.closing:
                await asyncio.sleep(0)
            state.refresh_lock.release()
            assert await asyncio.wait_for(refresh_task, timeout=2.0) is False
            await asyncio.wait_for(close_task, timeout=2.0)
            assert state.generation == 0
            assert old.is_closed is True
            assert client._clients == {}
        finally:
            if state.refresh_lock.locked():
                state.refresh_lock.release()
            for task in (refresh_task, close_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(refresh_task, close_task, return_exceptions=True)
            if not client._closed:
                await client.close()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self):
        client = _make_client()
        clients = list(client._clients.values())
        await client.close()
        await client.close()
        assert client._closed is True
        assert client._clients == {}
        assert all(http_client.is_closed for http_client in clients)

    @pytest.mark.asyncio
    async def test_concurrent_close_callers_share_one_cleanup(self):
        client = _make_client()
        current = client._clients[client._client_key("standard")]
        close_entered = asyncio.Event()
        release_close = asyncio.Event()
        close_calls = 0

        async def blocking_close() -> None:
            nonlocal close_calls
            close_calls += 1
            close_entered.set()
            await release_close.wait()

        tasks: list[asyncio.Task[None]] = []
        try:
            with patch.object(current, "aclose", new=blocking_close):
                tasks = [asyncio.create_task(client.close()) for _ in range(3)]
                await asyncio.wait_for(close_entered.wait(), timeout=2.0)
                assert client._close_task is not None
                assert all(task.done() is False for task in tasks)
                release_close.set()
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=2.0)
            assert close_calls == 1
            assert client._closed is True
        finally:
            release_close.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if not client._closed:
                await client.close()

    @pytest.mark.asyncio
    async def test_cancel_close_drains_clients_then_propagates(self):
        client = _make_client()
        current = client._clients[client._client_key("standard")]
        close_entered = asyncio.Event()
        release_close = asyncio.Event()
        close_calls = 0

        async def blocking_close() -> None:
            nonlocal close_calls
            close_calls += 1
            close_entered.set()
            await release_close.wait()

        task: asyncio.Task[None] | None = None
        try:
            with patch.object(current, "aclose", new=blocking_close):
                task = asyncio.create_task(client.close())
                await asyncio.wait_for(close_entered.wait(), timeout=2.0)
                task.cancel()
                await asyncio.sleep(0)
                assert task.done() is False
                release_close.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert close_calls == 1
            assert client._closed is True
            assert client._clients == {}
            assert all(
                state.borrowers == {}
                and state.retired == {}
                and state.retirement_closes == {}
                and state.closed
                for state in client._client_pool_states.values()
            )
        finally:
            release_close.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if not client._closed:
                await client.close()
