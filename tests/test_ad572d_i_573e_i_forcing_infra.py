"""AD-572d-i + AD-573e-i: forcing-function infra tests."""
from __future__ import annotations

import asyncio
import pytest


# ---------------------------------------------------------------------------
# AD-572d-i — interruptible-wait on proactive _think_loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interruptible_sleep_returns_after_timeout() -> None:
    from probos.proactive import ProactiveCognitiveLoop

    loop = ProactiveCognitiveLoop(interval=10.0)
    start = asyncio.get_event_loop().time()
    await loop._interruptible_sleep(0.05)
    elapsed = asyncio.get_event_loop().time() - start
    # Allow generous lower bound; main constraint is that it does sleep.
    assert elapsed >= 0.04


@pytest.mark.asyncio
async def test_trigger_wakeup_cuts_sleep_short() -> None:
    from probos.proactive import ProactiveCognitiveLoop

    loop = ProactiveCognitiveLoop(interval=10.0)

    async def waker():
        # Allow the sleep to start before triggering
        await asyncio.sleep(0.02)
        loop.trigger_wakeup()

    start = asyncio.get_event_loop().time()
    await asyncio.gather(loop._interruptible_sleep(5.0), waker())
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed < 1.0  # well below the 5s ceiling


@pytest.mark.asyncio
async def test_trigger_wakeup_before_sleep_event_initialized_is_safe() -> None:
    from probos.proactive import ProactiveCognitiveLoop

    loop = ProactiveCognitiveLoop(interval=10.0)
    # Must not raise even though _wakeup is still None
    loop.trigger_wakeup()
    assert loop._wakeup is None


@pytest.mark.asyncio
async def test_wakeup_clears_after_firing() -> None:
    from probos.proactive import ProactiveCognitiveLoop

    loop = ProactiveCognitiveLoop(interval=10.0)

    async def waker():
        await asyncio.sleep(0.02)
        loop.trigger_wakeup()

    await asyncio.gather(loop._interruptible_sleep(5.0), waker())
    # Event cleared so the next sleep waits the full interval (we use a tiny one)
    start = asyncio.get_event_loop().time()
    await loop._interruptible_sleep(0.05)
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed >= 0.04


# ---------------------------------------------------------------------------
# AD-573e-i — recent_for_agent on CognitiveJournal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_for_agent_alias_returns_same_rows(tmp_path) -> None:
    from probos.cognitive.journal import CognitiveJournal

    db_path = tmp_path / "j.db"
    j = CognitiveJournal(db_path=str(db_path))
    await j.start()
    try:
        for i in range(5):
            await j.record(
                entry_id=f"e{i}",
                timestamp=1000.0 + i,
                agent_id="alpha",
                agent_type="cognitive",
                tier="standard",
                total_tokens=10 * i,
                latency_ms=20.0,
                intent="test",
                intent_id=f"i{i}",
                success=True,
            )
        a = await j.get_reasoning_chain("alpha", limit=3)
        b = await j.recent_for_agent("alpha", limit=3)
        # Both should be ordered most-recent-first; whichever id field
        # exists, must match across both calls.
        assert len(a) == 3
        assert len(b) == 3
        assert a == b


    finally:
        await j.stop()
