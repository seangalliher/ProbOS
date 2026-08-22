"""BF-833 (#1298): a result must belong to the broadcast that launched it.

`_invoke_handler` decided whether to record a result by testing whether the
intent ID was PRESENT in `_pending_results` -- presence, not which broadcast the
entry belonged to. `broadcast()` recreates that key on every call.

So a straggler from round 1 that suppressed its `CancelledError` and finished
during round 2 of the SAME intent ID found the key present again, belonging to a
different round, and appended into it:

    first=0  second=[('stale-first','STALE'), ('fresh','FRESH')]  CONTAMINATED=True

Identical with `HEAD:src/probos/mesh/intent.py` restored in place, so it was
pre-existing rather than introduced by BF-829.

It is a learning defect as well as a return-value one. `submit_intent` feeds
every result to Hebbian routing (runtime.py ~3741), and the consensus path feeds
them to Hebbian AND quorum (~3959) -- so on those paths a misattributed result
reinforces the wrong intent->agent edge and votes in a round it was never in.
Direct `broadcast()` callers do neither and simply get a wrong list. It is
well-formed either way, so nothing logs and nothing fails.

The fix hands each handler THIS round's list object, captured synchronously in
`broadcast` before the task is scheduled. Once a round returns, its list is
dropped and nothing else holds it, so a late append is inert instead of
misattributed.

ON THE CANCELLATION SHAPE -- load-bearing. A handler that RE-RAISES
`CancelledError` reaches neither append branch (traced
`executed=[(1423, False), (1443, False)]`), so a test written that way passes
with both guards deleted and pins nothing. Every straggler here SUPPRESSES its
cancellation and then completes. The re-raise case is covered as a negative
control by
`tests/test_intent.py::...::test_cancelled_invoke_propagates_without_sample_warning_or_result`.
"""

from __future__ import annotations

import asyncio

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult


@pytest.fixture(autouse=True)
async def _leave_no_stranded_tasks():
    """Cancel and await any handler task still live when a test ends.

    Bounded on purpose: an unbounded `gather` deadlocks on a handler that
    blocks inside its own cancellation handler, and a suite that hangs on
    regression turns a red gate into a stalled one (BF-829).
    """
    yield
    live = [
        t for t in asyncio.all_tasks()
        if t.get_name().startswith("intent-") and not t.done()
    ]
    for t in live:
        t.cancel()
    if live:
        await asyncio.wait(live, timeout=1.0)


def _bus() -> IntentBus:
    return IntentBus(SignalManager())


async def _two_rounds(bus: IntentBus, straggler, fresh, *, intent: IntentMessage):
    """Round 1 times out leaving `straggler` behind; round 2 reuses the ID.

    Returns (round_one_results, round_two_results).
    """
    bus.subscribe("agent-straggler", straggler, ["direct_message"])
    first = await bus.broadcast(intent, timeout=0.05)

    # Round 2, same intent object -- so the same ID, which recreates the key.
    bus._subscribers.clear()
    bus._intent_index.clear()
    bus.subscribe("agent-fresh", fresh, ["direct_message"])
    second = await bus.broadcast(intent, timeout=2)
    return first, second


# ── the defect: both append branches ──────────────────────────────


@pytest.mark.asyncio
async def test_a_late_returning_straggler_does_not_land_in_the_next_round() -> None:
    """The return branch.

    The straggler must genuinely COMPLETE -- if it never got past its sleep,
    "round two is clean" would be true for the wrong reason.
    """
    bus = _bus()
    completed = asyncio.Event()

    async def straggler(intent: IntentMessage) -> IntentResult:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass                       # suppressed, then carries on
        completed.set()
        return IntentResult(
            intent_id=intent.id, agent_id="stale-first",
            success=True, result="STALE", confidence=1.0,
        )

    async def fresh(intent: IntentMessage) -> IntentResult:
        await asyncio.sleep(0.3)       # long enough for the straggler to land
        return IntentResult(
            intent_id=intent.id, agent_id="fresh",
            success=True, result="FRESH", confidence=1.0,
        )

    intent = IntentMessage(intent="direct_message", params={})
    first, second = await _two_rounds(bus, straggler, fresh, intent=intent)

    # POSITIVE PREMISE: the straggler really did finish during round 2.
    assert completed.is_set(), "the straggler never completed; nothing was proved"

    assert [r.agent_id for r in second] == ["fresh"], second
    assert not any(r.agent_id == "stale-first" for r in second)
    assert first == []


@pytest.mark.asyncio
async def test_a_late_raising_straggler_does_not_land_in_the_next_round() -> None:
    """The exception branch, which is a SEPARATE append site.

    `_invoke_handler` records failures too, through its own append. One fix can
    close the return branch and miss this one.
    """
    bus = _bus()
    raised = asyncio.Event()

    async def straggler(intent: IntentMessage) -> IntentResult:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass
        raised.set()
        raise RuntimeError("stale-first-error")

    async def fresh(intent: IntentMessage) -> IntentResult:
        await asyncio.sleep(0.3)
        return IntentResult(
            intent_id=intent.id, agent_id="fresh",
            success=True, result="FRESH", confidence=1.0,
        )

    intent = IntentMessage(intent="direct_message", params={})
    _first, second = await _two_rounds(bus, straggler, fresh, intent=intent)

    assert raised.is_set(), "the straggler never raised; nothing was proved"

    assert [r.agent_id for r in second] == ["fresh"], second
    assert not any(r.error == "stale-first-error" for r in second), second
    assert all(r.success for r in second), second


# ── the positive premise for the whole file ───────────────────────


@pytest.mark.asyncio
async def test_a_result_from_the_CURRENT_round_is_still_recorded() -> None:
    """Without this, every assertion above is satisfied by a bus that records
    nothing at all."""
    bus = _bus()

    async def handler(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id, agent_id="agent-ok",
            success=True, result="OK", confidence=1.0,
        )

    bus.subscribe("agent-ok", handler, ["direct_message"])
    intent = IntentMessage(intent="direct_message", params={})

    results = await bus.broadcast(intent, timeout=5)

    assert [(r.agent_id, r.result) for r in results] == [("agent-ok", "OK")]


@pytest.mark.asyncio
async def test_a_failure_from_the_CURRENT_round_is_still_recorded() -> None:
    """The same premise for the exception branch."""
    bus = _bus()

    async def handler(intent: IntentMessage) -> IntentResult:
        raise RuntimeError("boom")

    bus.subscribe("agent-bad", handler, ["direct_message"])
    intent = IntentMessage(intent="direct_message", params={})

    results = await bus.broadcast(intent, timeout=5)

    assert len(results) == 1, results
    assert results[0].success is False
    assert results[0].error == "boom"


# ── the mechanism, not just the symptom ───────────────────────────


@pytest.mark.asyncio
async def test_two_overlapping_broadcasts_of_one_id_keep_their_results_apart() -> None:
    """Concurrent rounds, not sequential ones. This is the case that matters.

    My first attempt fixed only the appends and left the read and the pop keyed
    by ID. Review then ran two OVERLAPPING broadcasts of one ID and showed
    round 1 returning round 2's result and deleting round 2's registry entry --
    the same silent misattribution, plus the loss of a whole round.

    Measured before the read/pop were made round-owned:

        round1 returned: []                          <- lost its own result
        round2 returned: [('round2-fast', 'R2')]

    Identical at HEAD, so it was never introduced -- but a fix for BF-833 that
    left it would have closed the narrow case and not the wide one.
    """
    bus = _bus()
    intent = IntentMessage(intent="direct_message", params={})
    hold = asyncio.Event()

    async def slow(i: IntentMessage) -> IntentResult:
        await hold.wait()
        return IntentResult(
            intent_id=i.id, agent_id="round1-slow",
            success=True, result="R1", confidence=1.0,
        )

    async def fast(i: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=i.id, agent_id="round2-fast",
            success=True, result="R2", confidence=1.0,
        )

    bus.subscribe("a1", slow, ["direct_message"])
    t1 = asyncio.create_task(bus.broadcast(intent, timeout=5))
    await asyncio.sleep(0.05)

    bus._subscribers.clear()
    bus._intent_index.clear()
    bus.subscribe("a2", fast, ["direct_message"])
    t2 = asyncio.create_task(bus.broadcast(intent, timeout=5))
    await asyncio.sleep(0.05)

    r2 = await t2
    hold.set()
    r1 = await t1

    assert [(x.agent_id, x.result) for x in r1] == [("round1-slow", "R1")], r1
    assert [(x.agent_id, x.result) for x in r2] == [("round2-fast", "R2")], r2
    assert bus._pending_results == {}, bus._pending_results


@pytest.mark.asyncio
async def test_two_broadcasts_released_together_each_get_exactly_one_result() -> None:
    """Both rounds created in the SAME loop iteration -- the tightest window.

    This is the ordering I could not find and review did. `asyncio.wait` yields,
    but a newly created handler task does not jump ahead of tasks already in the
    ready queue: when two broadcasts of one ID are released together, round 2
    can replace the registry entry before round 1's handler runs its first line.

    So capturing the sink on the task's first line -- rather than synchronously
    in `broadcast`, as the code does -- reopens the defect. Measured under that
    variant, 10 runs out of 10:

        results = [[('agent-N', N), ('agent-N', N)], []]

    one round taking both results and the other none. My own attempt with
    SEQUENTIAL rounds could not open it in 33 orderings, which is exactly why
    this case is pinned rather than argued about.
    """
    bus = _bus()
    intent = IntentMessage(intent="direct_message", params={})
    calls = 0

    async def handler(i: IntentMessage) -> IntentResult:
        nonlocal calls
        calls += 1
        n = calls
        await asyncio.sleep(0.02)
        return IntentResult(
            intent_id=i.id, agent_id=f"call-{n}",
            success=True, result=n, confidence=1.0,
        )

    bus.subscribe("a", handler, ["direct_message"])

    # No await between them: both are queued in one iteration.
    t1 = asyncio.create_task(bus.broadcast(intent, timeout=5))
    t2 = asyncio.create_task(bus.broadcast(intent, timeout=5))
    r1, r2 = await asyncio.gather(t1, t2)

    assert calls == 2, calls
    assert len(r1) == 1, (r1, r2)
    assert len(r2) == 1, (r1, r2)
    assert {r1[0].agent_id, r2[0].agent_id} == {"call-1", "call-2"}, (r1, r2)
    assert bus._pending_results == {}, bus._pending_results


@pytest.mark.asyncio
async def test_a_round_does_not_delete_a_later_round_s_registry_entry() -> None:
    """The pop is conditional on identity, and that condition must bite.

    Round 2 registers over round 1's entry while round 1 is still running. When
    round 1 finishes it must NOT pop, because the entry is no longer its own --
    doing so would strand round 2's handlers appending into a list nothing
    reads, and make BF-829's leak assertions lie.
    """
    bus = _bus()
    intent = IntentMessage(intent="direct_message", params={})
    hold = asyncio.Event()
    seen_during_round2: list[object] = []

    async def slow(i: IntentMessage) -> None:
        await hold.wait()
        return None

    async def fast(i: IntentMessage) -> None:
        seen_during_round2.append(bus._pending_results.get(i.id))
        return None

    bus.subscribe("a1", slow, ["direct_message"])
    t1 = asyncio.create_task(bus.broadcast(intent, timeout=5))
    await asyncio.sleep(0.05)

    bus._subscribers.clear()
    bus._intent_index.clear()
    bus.subscribe("a2", fast, ["direct_message"])
    t2 = asyncio.create_task(bus.broadcast(intent, timeout=5))
    await asyncio.sleep(0.05)

    # Round 2's registered list, observed from inside round 2.
    assert seen_during_round2 and seen_during_round2[0] is not None
    round2_list = seen_during_round2[0]

    await t2
    hold.set()
    await t1

    # Round 1 finished LAST and must not have removed a foreign entry, nor
    # left its own behind.
    assert bus._pending_results == {}, bus._pending_results
    assert round2_list is not None


@pytest.mark.asyncio
async def test_a_round_finishing_first_leaves_the_live_round_registered() -> None:
    """The conditional pop, exercised in the order that can actually bite.

    The sibling test above has round 1 finish LAST, where an unconditional pop
    is a harmless no-op on an already-missing key -- so it cannot tell the two
    implementations apart. Here round 1 finishes FIRST, while round 2 is still
    running: an unconditional pop deletes a LIVE round's entry, and the
    registry then claims nothing is in flight while a handler is still going.
    """
    bus = _bus()
    intent = IntentMessage(intent="direct_message", params={})
    gate1 = asyncio.Event()
    gate2 = asyncio.Event()

    async def round_one(i: IntentMessage) -> None:
        await gate1.wait()
        return None

    async def round_two(i: IntentMessage) -> None:
        await gate2.wait()
        return None

    bus.subscribe("a1", round_one, ["direct_message"])
    t1 = asyncio.create_task(bus.broadcast(intent, timeout=5))
    await asyncio.sleep(0.05)          # round 1 in flight, blocked

    bus._subscribers.clear()
    bus._intent_index.clear()
    bus.subscribe("a2", round_two, ["direct_message"])
    t2 = asyncio.create_task(bus.broadcast(intent, timeout=5))
    await asyncio.sleep(0.05)          # round 2 has registered over round 1

    gate1.set()
    await t1                           # round 1 finishes; round 2 still blocked

    assert not t2.done(), "premise: round 2 must still be live"
    assert intent.id in bus._pending_results, (
        "round 1's cleanup deleted the live round's registry entry"
    )

    gate2.set()
    await t2
    assert bus._pending_results == {}, bus._pending_results


@pytest.mark.asyncio
async def test_a_straggler_append_does_not_recreate_the_popped_key() -> None:
    """BF-829's guarantee must survive BF-833.

    The old presence test doubled as the thing that stopped a late append
    re-creating the key. Removing it must not bring that leak back -- the
    straggler now holds the list itself and never touches the dict.
    """
    bus = _bus()
    completed = asyncio.Event()

    async def straggler(intent: IntentMessage) -> IntentResult:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass
        completed.set()
        return IntentResult(
            intent_id=intent.id, agent_id="late",
            success=True, confidence=1.0,
        )

    bus.subscribe("agent-late", straggler, ["direct_message"])
    intent = IntentMessage(intent="direct_message", params={})

    await bus.broadcast(intent, timeout=0.05)
    await asyncio.wait_for(completed.wait(), timeout=5)
    await asyncio.sleep(0.05)

    assert completed.is_set()
    assert bus._pending_results == {}, bus._pending_results
    assert intent.id not in bus._signal_manager._signals
