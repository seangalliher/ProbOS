"""BF-183: Sub-Task Chain Budget-Aware Retry Before Fallback — tests."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.sub_task import (
    SubTaskChain,
    SubTaskExecutor,
    SubTaskResult,
    SubTaskSpec,
    SubTaskStepError,
    SubTaskType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_executor(*, max_chains: int = 4) -> SubTaskExecutor:
    config = MagicMock()
    config.enabled = True
    config.max_chain_steps = 6
    config.max_concurrent_chains = max_chains
    return SubTaskExecutor(config=config)


def _ok_result(name: str = "test") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name=name,
        result={"output": "ok"},
        tokens_used=10,
        success=True,
    )


def _make_spec(
    *,
    timeout_ms: int = 5000,
    step_type: SubTaskType = SubTaskType.ANALYZE,
    name: str = "analyze-test",
    required: bool = True,
) -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=step_type,
        name=name,
        timeout_ms=timeout_ms,
        required=required,
    )


def _base_kwargs(*, chain_start_time: float, chain_timeout_ms: int = 30000):
    """Common kwargs for _execute_single_step calls."""
    return dict(
        chain_id="test123", agent_id="a1", agent_type="t",
        intent="test", intent_id="i1", journal=None,
        chain_start_time=chain_start_time,
        chain_timeout_ms=chain_timeout_ms,
    )


# Strategy: patch asyncio.wait_for at the module level to simulate timeouts
# without relying on real async timing. This gives us full control.


class TestRetrySucceeds:
    """Step times out, budget allows retry, retry succeeds."""

    @pytest.mark.asyncio
    async def test_retry_succeeds(self):
        executor = _make_executor()
        handler = AsyncMock(return_value=_ok_result("analyze-test"))
        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=5000)

        # Patch wait_for: first call raises TimeoutError, second succeeds
        orig_wait_for = asyncio.wait_for

        call_idx = [0]
        async def mock_wait_for(coro, *, timeout):
            call_idx[0] += 1
            if call_idx[0] == 1:
                # Cancel the coroutine to avoid "was never awaited"
                coro.close()
                raise asyncio.TimeoutError()
            return await orig_wait_for(coro, timeout=timeout)

        with patch("probos.cognitive.sub_task.asyncio.wait_for", side_effect=mock_wait_for):
            with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await executor._execute_single_step(
                    spec, 0, {}, [],
                    **_base_kwargs(chain_start_time=time.monotonic()),
                )

        assert result.success
        assert handler.call_count == 2  # First creates coroutine (closed), retry succeeds
        mock_sleep.assert_awaited_once_with(2.0)


class TestRetryFails:
    """Step times out, budget allows retry, retry also fails."""

    @pytest.mark.asyncio
    async def test_retry_also_times_out(self):
        executor = _make_executor()
        handler = AsyncMock(return_value=_ok_result("analyze-test"))
        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=5000)

        async def mock_wait_for(coro, *, timeout):
            coro.close()
            raise asyncio.TimeoutError()

        with patch("probos.cognitive.sub_task.asyncio.wait_for", side_effect=mock_wait_for):
            with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(SubTaskStepError, match="retry also failed"):
                    await executor._execute_single_step(
                        spec, 0, {}, [],
                        **_base_kwargs(chain_start_time=time.monotonic()),
                    )


class TestNoBudgetForRetry:
    """Step times out late in chain, insufficient remaining time."""

    @pytest.mark.asyncio
    async def test_no_budget(self):
        executor = _make_executor()
        handler = AsyncMock()
        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=5000)

        async def mock_wait_for(coro, *, timeout):
            coro.close()
            raise asyncio.TimeoutError()

        with patch("probos.cognitive.sub_task.asyncio.wait_for", side_effect=mock_wait_for):
            with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                # 26s elapsed → 4s remaining (need 7s = 5s+2s)
                chain_start = time.monotonic() - 26.0
                with pytest.raises(SubTaskStepError, match="no retry budget"):
                    await executor._execute_single_step(
                        spec, 0, {}, [],
                        **_base_kwargs(chain_start_time=chain_start),
                    )
                mock_sleep.assert_not_awaited()


class TestBudgetBoundary:
    """Budget boundary conditions."""

    @pytest.mark.asyncio
    async def test_exact_budget_retries(self):
        """remaining == step_timeout + backoff → retry attempted."""
        executor = _make_executor()
        handler = AsyncMock(return_value=_ok_result("analyze-test"))
        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=5000)

        orig_wait_for = asyncio.wait_for
        call_idx = [0]

        async def mock_wait_for(coro, *, timeout):
            call_idx[0] += 1
            if call_idx[0] == 1:
                coro.close()
                raise asyncio.TimeoutError()
            return await orig_wait_for(coro, timeout=timeout)

        with patch("probos.cognitive.sub_task.asyncio.wait_for", side_effect=mock_wait_for):
            with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                # Need exactly 7000ms remaining (5000+2000)
                chain_start = time.monotonic() - 23.0  # 23s elapsed → 7s remaining
                result = await executor._execute_single_step(
                    spec, 0, {}, [],
                    **_base_kwargs(chain_start_time=chain_start),
                )
        assert result.success
        mock_sleep.assert_awaited_once_with(2.0)

    @pytest.mark.asyncio
    async def test_just_under_budget_no_retry(self):
        """remaining < step_timeout + backoff → no retry."""
        executor = _make_executor()
        handler = AsyncMock()
        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=5000)

        async def mock_wait_for(coro, *, timeout):
            coro.close()
            raise asyncio.TimeoutError()

        with patch("probos.cognitive.sub_task.asyncio.wait_for", side_effect=mock_wait_for):
            with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                # 6999ms remaining (need 7000)
                chain_start = time.monotonic() - 23.001
                with pytest.raises(SubTaskStepError, match="no retry budget"):
                    await executor._execute_single_step(
                        spec, 0, {}, [],
                        **_base_kwargs(chain_start_time=chain_start),
                    )
                mock_sleep.assert_not_awaited()


class TestNonTimeoutErrorSkipsRetry:
    """Non-timeout errors should NOT trigger retry logic."""

    @pytest.mark.asyncio
    async def test_value_error_no_retry(self):
        executor = _make_executor()

        async def handler(spec, context, prior):
            raise ValueError("bad input")

        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=5000)

        with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(SubTaskStepError, match="bad input"):
                await executor._execute_single_step(
                    spec, 0, {}, [],
                    **_base_kwargs(chain_start_time=time.monotonic()),
                )
            mock_sleep.assert_not_awaited()


class TestBackoffDuration:
    """Verify 2s sleep between attempt and retry."""

    @pytest.mark.asyncio
    async def test_backoff_is_2_seconds(self):
        executor = _make_executor()
        handler = AsyncMock(return_value=_ok_result("analyze-test"))
        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=5000)

        orig_wait_for = asyncio.wait_for
        call_idx = [0]

        async def mock_wait_for(coro, *, timeout):
            call_idx[0] += 1
            if call_idx[0] == 1:
                coro.close()
                raise asyncio.TimeoutError()
            return await orig_wait_for(coro, timeout=timeout)

        with patch("probos.cognitive.sub_task.asyncio.wait_for", side_effect=mock_wait_for):
            with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await executor._execute_single_step(
                    spec, 0, {}, [],
                    **_base_kwargs(chain_start_time=time.monotonic()),
                )
        mock_sleep.assert_awaited_once_with(2.0)


class TestRetryTimeout:
    """Verify retry timeout uses min(step_timeout, remaining - backoff)."""

    @pytest.mark.asyncio
    async def test_retry_timeout_capped_at_step_timeout(self):
        executor = _make_executor()
        handler = AsyncMock(return_value=_ok_result("analyze-test"))
        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=5000)

        orig_wait_for = asyncio.wait_for
        call_idx = [0]
        captured_timeouts = []

        async def mock_wait_for(coro, *, timeout):
            captured_timeouts.append(timeout)
            call_idx[0] += 1
            if call_idx[0] == 1:
                coro.close()
                raise asyncio.TimeoutError()
            return await orig_wait_for(coro, timeout=timeout)

        with patch("probos.cognitive.sub_task.asyncio.wait_for", side_effect=mock_wait_for):
            with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock):
                # Plenty of budget → retry timeout = min(5000, remaining-2000) = 5000
                await executor._execute_single_step(
                    spec, 0, {}, [],
                    **_base_kwargs(chain_start_time=time.monotonic()),
                )

        assert len(captured_timeouts) == 2
        assert captured_timeouts[0] == 5.0  # Original attempt
        assert captured_timeouts[1] == pytest.approx(5.0, abs=0.1)  # Retry capped at step timeout

    @pytest.mark.asyncio
    async def test_retry_timeout_uses_remaining_when_less(self):
        executor = _make_executor()
        handler = AsyncMock(return_value=_ok_result("analyze-test"))
        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=10000)  # 10s step timeout

        orig_wait_for = asyncio.wait_for
        call_idx = [0]
        captured_timeouts = []

        async def mock_wait_for(coro, *, timeout):
            captured_timeouts.append(timeout)
            call_idx[0] += 1
            if call_idx[0] == 1:
                coro.close()
                raise asyncio.TimeoutError()
            return await orig_wait_for(coro, timeout=timeout)

        with patch("probos.cognitive.sub_task.asyncio.wait_for", side_effect=mock_wait_for):
            with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock):
                # 15s elapsed → 15s remaining, after 2s backoff → 13s
                # min(10000, 13000) = 10000 → 10.0s
                chain_start = time.monotonic() - 15.0
                await executor._execute_single_step(
                    spec, 0, {}, [],
                    **_base_kwargs(chain_start_time=chain_start),
                )

        assert len(captured_timeouts) == 2
        assert captured_timeouts[0] == 10.0
        assert captured_timeouts[1] == pytest.approx(10.0, abs=0.1)


class TestJournalRecording:
    """Journal records for timeout and successful retry."""

    @pytest.mark.asyncio
    async def test_journal_records_timeout(self):
        executor = _make_executor()
        handler = AsyncMock(return_value=_ok_result("analyze-test"))
        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=5000)
        journal = AsyncMock()

        orig_wait_for = asyncio.wait_for
        call_idx = [0]

        async def mock_wait_for(coro, *, timeout):
            call_idx[0] += 1
            if call_idx[0] == 1:
                coro.close()
                raise asyncio.TimeoutError()
            return await orig_wait_for(coro, timeout=timeout)

        with patch("probos.cognitive.sub_task.asyncio.wait_for", side_effect=mock_wait_for):
            with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock):
                await executor._execute_single_step(
                    spec, 0, {}, [],
                    chain_id="test123", agent_id="a1", agent_type="t",
                    intent="test", intent_id="i1", journal=journal,
                    chain_start_time=time.monotonic(),
                    chain_timeout_ms=30000,
                )

        # At least 2 journal calls: timeout + success
        assert journal.record.call_count >= 2
        first_kwargs = journal.record.call_args_list[0].kwargs
        assert first_kwargs["dag_node_id"].endswith(":timeout")
        assert first_kwargs["success"] is False
        assert first_kwargs["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_journal_records_retry_success(self):
        executor = _make_executor()
        handler = AsyncMock(return_value=_ok_result("analyze-test"))
        executor.register_handler(SubTaskType.ANALYZE, handler)
        spec = _make_spec(timeout_ms=5000)
        journal = AsyncMock()

        orig_wait_for = asyncio.wait_for
        call_idx = [0]

        async def mock_wait_for(coro, *, timeout):
            call_idx[0] += 1
            if call_idx[0] == 1:
                coro.close()
                raise asyncio.TimeoutError()
            return await orig_wait_for(coro, timeout=timeout)

        with patch("probos.cognitive.sub_task.asyncio.wait_for", side_effect=mock_wait_for):
            with patch("probos.cognitive.sub_task.asyncio.sleep", new_callable=AsyncMock):
                await executor._execute_single_step(
                    spec, 0, {}, [],
                    chain_id="test123", agent_id="a1", agent_type="t",
                    intent="test", intent_id="i1", journal=journal,
                    chain_start_time=time.monotonic(),
                    chain_timeout_ms=30000,
                )

        second_kwargs = journal.record.call_args_list[1].kwargs
        assert not second_kwargs["dag_node_id"].endswith(":timeout")
        assert second_kwargs["success"] is True


class TestOptionalStepTimeout:
    """Optional step with no handler skips gracefully."""

    @pytest.mark.asyncio
    async def test_optional_step_no_handler_skips(self):
        executor = _make_executor()
        result = await executor._execute_single_step(
            _make_spec(step_type=SubTaskType.REFLECT, name="reflect-opt", required=False),
            0, {}, [],
            **_base_kwargs(chain_start_time=time.monotonic()),
        )
        assert result.success


class TestParallelStepRetry:
    """Retry works correctly in full chain with parallel steps."""

    @pytest.mark.asyncio
    async def test_parallel_chain_completes(self):
        executor = _make_executor()
        executor.register_handler(SubTaskType.COMPOSE, AsyncMock(return_value=_ok_result("compose")))
        executor.register_handler(SubTaskType.EVALUATE, AsyncMock(return_value=_ok_result("evaluate")))
        executor.register_handler(SubTaskType.REFLECT, AsyncMock(return_value=_ok_result("reflect")))

        chain = SubTaskChain(
            steps=[
                SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose", timeout_ms=5000),
                SubTaskSpec(sub_task_type=SubTaskType.EVALUATE, name="evaluate", timeout_ms=5000, depends_on=("compose",)),
                SubTaskSpec(sub_task_type=SubTaskType.REFLECT, name="reflect", timeout_ms=5000, depends_on=("compose",)),
            ],
            chain_timeout_ms=30000,
            source="test",
        )

        results = await executor.execute(chain, {}, agent_id="a1", agent_type="t")
        assert len(results) == 3
        assert all(r.success for r in results)
