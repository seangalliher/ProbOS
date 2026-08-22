"""BF-829 (#1293): a cancelled broadcast stranded its children and leaked state.

`broadcast()` fanned out into tasks, awaited `asyncio.wait(...)`, and then --
BELOW the await, on the normal path only -- cancelled stragglers, popped
`_pending_results` and untracked the intent.

A caller cancelled mid-flight raised `CancelledError` out of `asyncio.wait` and
skipped all three. Measured against the real bus before the fix:

    pending_results leaked : True
    child tasks STILL ALIVE: 1
    handler outcomes       : []
    signal_manager._signals leaked: True

`handler outcomes: []` is the damning line -- the child was neither cancelled
nor completed. It was still sleeping, detached, with nothing left holding a
reference that would ever cancel it.

Reached by any cancellable caller: request timeouts, shutdown, and nested
broadcasts where an outer handler is itself a straggler being cancelled. The
nested case compounds -- stranding the inner broadcast's children strands
theirs in turn.
"""

from __future__ import annotations

import asyncio

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult


def _bus() -> IntentBus:
    return IntentBus(SignalManager())


def _intent() -> IntentMessage:
    return IntentMessage(intent="direct_message", params={"text": "hi"})


def _live_children(intent: IntentMessage) -> list[asyncio.Task]:
    prefix = f"intent-{intent.id[:8]}"
    return [
        t for t in asyncio.all_tasks()
        if t.get_name().startswith(prefix) and not t.done()
    ]


async def _cancel_mid_flight(
    bus: IntentBus, intent: IntentMessage, started: asyncio.Event,
) -> None:
    """Start a broadcast, wait until a handler is actually in flight, cancel.

    ``started`` is created inside each test, not at module scope: an
    ``asyncio.Event`` binds to the first loop that touches it, and every test
    here gets a fresh loop.
    """
    task = asyncio.create_task(bus.broadcast(intent, timeout=30))
    await asyncio.wait_for(started.wait(), timeout=5)
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


_STARTED_PREFIX = "intent-"


@pytest.fixture(autouse=True)
async def _leave_no_stranded_tasks():
    """Cancel and await any handler task still live when a test ends.

    These tests deliberately create handlers that sleep far longer than any
    timeout they use. Left pending, loop teardown -- not the assertion --
    decides when the file finishes.

    Measured: the mutant that never cancels stragglers correctly FAILED three
    tests, and then the file HUNG past 240s at the seventh, sailing straight
    through a 15s `--timeout-method=thread` cap. A suite that hangs on
    regression is worse than one that fails: it turns a red gate into a
    stalled one, and nothing in the output says which assertion was wrong.

    The drain is BOUNDED, and that is not defensiveness for its own sake. The
    first version awaited an unbounded `gather` and deadlocked on exactly the
    handler below that blocks INSIDE its cancellation handler -- cancelling a
    task does not mean it will finish, so a teardown that waits forever for
    one is just a slower hang.
    """
    yield
    live = [
        t for t in asyncio.all_tasks()
        if t.get_name().startswith(_STARTED_PREFIX) and not t.done()
    ]
    for t in live:
        t.cancel()
    if live:
        await asyncio.wait(live, timeout=1.0)


# ── the positive premise: the rig genuinely runs a broadcast ──────


@pytest.mark.asyncio
async def test_an_uncancelled_broadcast_still_returns_its_results() -> None:
    """Without this, every 'did not leak' assertion below is vacuous.

    A bus that never fans out leaks nothing either.
    """
    bus = _bus()

    async def handler(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id, agent_id="agent-ok", success=True, confidence=1.0,
        )

    bus.subscribe("agent-ok", handler, ["direct_message"])
    intent = _intent()

    results = await bus.broadcast(intent, timeout=5)

    assert [r.success for r in results] == [True]
    assert intent.id not in bus._pending_results
    assert intent.id not in bus._signal_manager._signals


# ── the defect ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancelling_the_caller_cancels_the_children() -> None:
    """The child must be CANCELLED, not merely un-awaited.

    Asserts the handler observed its own cancellation. Counting live tasks
    alone would pass against a child that had already run to completion --
    a different bug wearing the same result.
    """
    bus = _bus()
    outcomes: list[str] = []
    started = asyncio.Event()

    async def slow(intent: IntentMessage) -> None:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            outcomes.append("cancelled")
            raise
        outcomes.append("COMPLETED-ORPHANED")

    bus.subscribe("agent-slow", slow, ["direct_message"])
    intent = _intent()

    await _cancel_mid_flight(bus, intent, started)
    await asyncio.sleep(0.1)  # let the child unwind

    assert outcomes == ["cancelled"], outcomes
    assert _live_children(intent) == []


@pytest.mark.asyncio
async def test_cancelling_the_caller_does_not_leak_pending_results() -> None:
    bus = _bus()
    started = asyncio.Event()

    async def slow(intent: IntentMessage) -> None:
        started.set()
        await asyncio.sleep(30)

    bus.subscribe("agent-slow", slow, ["direct_message"])
    intent = _intent()

    assert intent.id not in bus._pending_results  # premise
    await _cancel_mid_flight(bus, intent, started)

    assert intent.id not in bus._pending_results
    assert bus._pending_results == {}


@pytest.mark.asyncio
async def test_cancelling_the_caller_does_not_leak_the_signal_entry() -> None:
    """The SignalManager leak the original report did not name."""
    bus = _bus()
    started = asyncio.Event()

    async def slow(intent: IntentMessage) -> None:
        started.set()
        await asyncio.sleep(30)

    bus.subscribe("agent-slow", slow, ["direct_message"])
    intent = _intent()

    await _cancel_mid_flight(bus, intent, started)

    assert intent.id not in bus._signal_manager._signals


# ── the nested case, which is how this compounds ──────────────────


@pytest.mark.asyncio
async def test_cancelling_an_outer_broadcast_does_not_strand_the_inner_one() -> None:
    """An outer handler that itself broadcasts: cancelling the outer must
    reach the grandchild, not stop at the child."""
    bus = _bus()
    grandchild: list[str] = []
    inner_ids: list[str] = []
    started = asyncio.Event()

    async def inner(intent: IntentMessage) -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            grandchild.append("cancelled")
            raise

    async def outer(intent: IntentMessage) -> None:
        nested = IntentMessage(intent="nested", params={})
        inner_ids.append(nested.id)
        started.set()
        await bus.broadcast(nested, timeout=30)

    bus.subscribe("agent-inner", inner, ["nested"])
    bus.subscribe("agent-outer", outer, ["direct_message"])
    intent = _intent()

    await _cancel_mid_flight(bus, intent, started)
    await asyncio.sleep(0.1)

    assert grandchild == ["cancelled"], grandchild
    assert bus._pending_results == {}, bus._pending_results
    assert inner_ids and inner_ids[0] not in bus._signal_manager._signals


# ── the deliberate non-await, and why ─────────────────────────────


@pytest.mark.asyncio
async def test_a_slow_cancelling_handler_does_not_block_the_timeout_path() -> None:
    """Stragglers are cancelled but NOT awaited, and that is deliberate.

    Awaiting them in the `finally` would be tidier, and would let one handler
    with slow cancellation cleanup block every broadcast that times out.

    Asserted with an event rather than elapsed time: a wall-clock bound is
    load-sensitive under `-n 16`, and it also let the test finish while the
    child was still live. Here the broadcast must be DONE while the handler is
    still inside its cleanup -- which is the actual property -- and the child
    is released and awaited before the test returns.
    """
    bus = _bus()
    in_cleanup = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def stubborn(intent: IntentMessage) -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            in_cleanup.set()
            await release.wait()   # cleanup that outlives the broadcast
            finished.set()
            raise

    bus.subscribe("agent-stubborn", stubborn, ["direct_message"])
    intent = _intent()

    task = asyncio.create_task(bus.broadcast(intent, timeout=0.05))
    try:
        await asyncio.wait_for(in_cleanup.wait(), timeout=5)

        # The broadcast must already be finished while cleanup is still blocked.
        await asyncio.wait_for(task, timeout=5)
        assert not release.is_set(), "premise: the handler is still in cleanup"
        assert not finished.is_set(), "broadcast waited for cancellation cleanup"
        assert intent.id not in bus._pending_results
        assert intent.id not in bus._signal_manager._signals
    finally:
        # Even on a failed assertion. The handler blocks inside its own
        # cancellation until this fires, so skipping it strands a task that
        # cannot be cancelled -- which is how a failing test becomes a hanging
        # one.
        release.set()

    await asyncio.wait_for(finished.wait(), timeout=5)


@pytest.mark.asyncio
async def test_a_straggler_that_resumes_after_the_pop_cannot_re_leak_the_key() -> None:
    """The non-await is only safe because `_invoke_handler` guards its append.

    The handler must SUPPRESS its cancellation and run on to the append --
    review caught the first version of this test re-raising `CancelledError`,
    which reaches neither append branch, so it would have passed with both
    guards deleted. Traced: `executed=[(1423, False), (1443, False)]`.

    Covers both branches: one straggler returns a result, one raises.
    """
    bus = _bus()
    appended = asyncio.Event()

    async def returns_late(intent: IntentMessage) -> IntentResult:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass                      # suppressed on purpose
        appended.set()
        return IntentResult(
            intent_id=intent.id, agent_id="late-ok", success=True, confidence=1.0,
        )

    async def raises_late(intent: IntentMessage) -> IntentResult:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass
        raise RuntimeError("late failure")

    bus.subscribe("agent-late-ok", returns_late, ["direct_message"])
    bus.subscribe("agent-late-err", raises_late, ["direct_message"])
    intent = _intent()

    await bus.broadcast(intent, timeout=0.05)
    assert intent.id not in bus._pending_results  # popped by the broadcast

    await asyncio.wait_for(appended.wait(), timeout=5)
    await asyncio.sleep(0.05)   # let both stragglers reach their append

    assert bus._pending_results == {}, bus._pending_results
    assert intent.id not in bus._signal_manager._signals


@pytest.mark.asyncio
async def test_a_synchronous_raise_during_setup_leaks_nothing(monkeypatch) -> None:
    """The `try` must open BEFORE the registration it exists to unwind.

    Review measured this: with the `try` opening at the fan-out, a logging
    handler whose `emit()` raised left BOTH registries dirty --
    `pending=True signal=True`. Nothing between `track()` and the fan-out
    awaits, so cancellation cannot land there, but a synchronous raise can,
    and a `try` that starts after the registration only moves the leak
    somewhere quieter.
    """
    bus = _bus()

    async def handler(intent: IntentMessage) -> None:
        return None

    bus.subscribe("agent-ok", handler, ["direct_message"])
    intent = _intent()

    def _boom(*_a, **_kw):
        raise RuntimeError("forced failure between track() and fan-out")

    monkeypatch.setattr(
        "probos.mesh.intent.logger.info", _boom,
    )

    with pytest.raises(RuntimeError, match="forced failure"):
        await bus.broadcast(intent, timeout=5)

    assert intent.id not in bus._pending_results, "pending_results leaked"
    assert intent.id not in bus._signal_manager._signals, "signal entry leaked"


@pytest.mark.asyncio
async def test_one_handler_erroring_does_not_strand_the_others() -> None:
    """Cleanup must cover every child, not stop at the first that misbehaves."""
    bus = _bus()
    outcomes: list[str] = []
    started = asyncio.Event()

    async def explodes(intent: IntentMessage) -> None:
        started.set()
        raise RuntimeError("handler blew up")

    async def slow(intent: IntentMessage) -> None:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            outcomes.append("cancelled")
            raise

    bus.subscribe("agent-boom", explodes, ["direct_message"])
    bus.subscribe("agent-slow", slow, ["direct_message"])
    intent = _intent()

    await _cancel_mid_flight(bus, intent, started)
    await asyncio.sleep(0.1)

    assert outcomes == ["cancelled"], outcomes
    assert bus._pending_results == {}
    assert intent.id not in bus._signal_manager._signals
