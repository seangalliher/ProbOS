# BF-211: Proactive Loop Dies Silently — Build Prompt

**BF:** 211  
**Issue:** #296  
**Related:** AD-636 (Proactive Stagger), BF-198 (Double-Post Prevention)  
**Scope:** ~3 lines in 1 file. Zero new modules.

---

## Problem

`_think_loop()` in `proactive.py` (line 352-361) has `asyncio.sleep(self._interval)` **outside** the try/except block:

```python
async def _think_loop(self) -> None:
    """Main loop: iterate agents every interval seconds."""
    while True:
        try:
            await self._run_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ProactiveCognitiveLoop cycle failed (fail-open)")
        await asyncio.sleep(self._interval)  # <-- OUTSIDE try/except
```

If a `CancelledError` is raised during `asyncio.sleep` (e.g., task cancellation during shutdown, or any asyncio disruption), the exception propagates unhandled and the task dies silently. There is no monitoring or restart mechanism — once dead, zero proactive activity for the rest of the session.

**Observed:** Proactive loop ran exactly one cycle after restart, then silence for 40+ minutes. No `proactive_think` intents after the first cycle.

---

## Fix

Move `asyncio.sleep` inside the try/except block in `_think_loop()` (proactive.py line 352-361).

Replace the current method:

```python
    async def _think_loop(self) -> None:
        """Main loop: iterate agents every interval seconds."""
        while True:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ProactiveCognitiveLoop cycle failed (fail-open)")
            await asyncio.sleep(self._interval)
```

With:

```python
    async def _think_loop(self) -> None:
        """Main loop: iterate agents every interval seconds."""
        while True:
            try:
                await self._run_cycle()
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ProactiveCognitiveLoop cycle failed (fail-open)")
                # BF-211: Sleep inside try/except so the loop survives
                # non-cancellation errors during sleep.
                await asyncio.sleep(self._interval)
```

**Why duplicate the sleep?** The `CancelledError` re-raise (line 357) correctly propagates intentional cancellation (shutdown). The issue is only with non-cancellation exceptions during sleep. By having sleep in both the try and except branches, the loop always sleeps before the next cycle, but only `CancelledError` can kill it.

---

## Verification Checklist

1. [ ] `asyncio.sleep(self._interval)` is inside the try/except block (happy path)
2. [ ] `asyncio.sleep(self._interval)` also present in the except branch (error recovery)
3. [ ] `CancelledError` still re-raises (intentional shutdown still works)
4. [ ] All existing tests pass (`pytest tests/ -x -q`)
5. [ ] No imports changed, no new modules

---

## Tests (tests/test_bf211_proactive_loop_resilience.py)

```python
"""BF-211: Proactive loop resilience — sleep inside try/except."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


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
```

Test count: 2 tests.

---

## Engineering Principles Compliance

- **Fail Fast (log-and-degrade):** Loop logs the exception and continues — proactive activity is non-critical (degradation, not crash).
- **SOLID (S):** No new responsibilities. Same method, same purpose, tighter error handling.
- **Defense in Depth:** Sleep in both branches ensures the loop always pauses regardless of error path.
