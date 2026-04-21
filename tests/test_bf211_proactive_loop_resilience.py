"""BF-211: Proactive loop resilience — sleep inside try/except."""

import asyncio

import pytest


class TestProactiveLoopResilience:
    """Verify _think_loop survives errors and respects cancellation."""

    @pytest.mark.asyncio
    async def test_think_loop_survives_cycle_failure(self):
        """Loop continues after _run_cycle raises an exception."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._interval = 0.01
        loop._runtime = None

        call_count = 0

        async def _failing_cycle():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("simulated failure")

        loop._run_cycle = _failing_cycle

        task = asyncio.create_task(loop._think_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert call_count >= 3, f"Loop should have retried after failure, got {call_count} calls"

    @pytest.mark.asyncio
    async def test_think_loop_cancelled_error_propagates(self):
        """CancelledError during cycle still propagates (clean shutdown)."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._interval = 0.01
        loop._runtime = None

        async def _cancelling_cycle():
            raise asyncio.CancelledError()

        loop._run_cycle = _cancelling_cycle

        task = asyncio.create_task(loop._think_loop())
        with pytest.raises(asyncio.CancelledError):
            await task
