"""BF-814 (#1278): a dispatch that reached no subscriber is not an execution.

``WatchManager`` inferred delivery from the ABSENCE OF AN EXCEPTION, and
``publish`` returns ``[]`` without raising when nobody is subscribed. So a
one-shot Captain's order naming an unhandled intent was consumed on its first
sweep, counted executed, and never ran.

The obvious repair -- treat an empty result list as non-delivery -- was built
and REVERTED, because it is wrong in a way that is worse than the defect:

    handler ACTS then returns None  -> results: []   handler_ran: ['x']
    zero subscribers                -> results: []

Those are indistinguishable, so retrying on an empty list re-fires real side
effects. The safe question is not "did anything come back" but "was any handler
INVOKED", and that is knowable BEFORE publishing. ``candidate_agent_ids`` answers
it, and the bridge raises ``IntentNoSubscriber`` so ``WatchManager``'s existing
exception paths -- which already leave an order active and uncounted -- handle it
with no change to their logic.
"""

from __future__ import annotations

import time

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.pre_intent_auth import IntentNoSubscriber
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult
from probos.watch_rotation import CaptainOrder, StandingTask, WatchManager


# ── candidate_agent_ids: the predicate the fix rests on ───────────────────


def _bus() -> IntentBus:
    return IntentBus(SignalManager())


async def _noop(msg: IntentMessage) -> None:
    return None


def test_no_subscribers_means_no_candidates() -> None:
    assert _bus().candidate_agent_ids("anything") == set()


def test_a_filtered_subscriber_is_a_candidate_for_its_own_intent() -> None:
    bus = _bus()
    bus.subscribe("a1", _noop, ["mine"])
    assert bus.candidate_agent_ids("mine") == {"a1"}


def test_an_unfiltered_subscriber_is_a_candidate_for_every_intent() -> None:
    """The fallback that makes "no subscriber" narrower than it looks: an agent
    registering no intent_names is reached by everything."""
    bus = _bus()
    bus.subscribe("catch_all", _noop)
    assert bus.candidate_agent_ids("anything_at_all") == {"catch_all"}


def test_a_filtered_subscriber_is_not_a_candidate_for_another_indexed_intent() -> None:
    """Only discriminates once the other intent is in the index -- otherwise the
    fallback branch applies and everyone is a candidate."""
    bus = _bus()
    bus.subscribe("a1", _noop, ["mine"])
    bus.subscribe("a2", _noop, ["yours"])
    assert bus.candidate_agent_ids("mine") == {"a1"}
    assert bus.candidate_agent_ids("yours") == {"a2"}


@pytest.mark.asyncio
async def test_the_predicate_agrees_with_what_broadcast_actually_invokes() -> None:
    """The two must not drift: broadcast reads this same computation. A
    predicate that disagreed with the fan-out would be worse than none."""
    bus = _bus()
    invoked: list[str] = []

    async def record(msg: IntentMessage) -> IntentResult:
        invoked.append("a1")
        return IntentResult(intent_id=msg.id, agent_id="a1", success=True)

    bus.subscribe("a1", record, ["mine"])
    predicted = bus.candidate_agent_ids("mine")
    await bus.publish(IntentMessage(intent="mine", params={}))
    assert set(invoked) == predicted


# ── the bridge refuses AFTER publishing ───────────────────────────────────
# Ordering matters and is load-bearing: refusing first would skip the
# pre-intent hooks, and BF-790a's guard records that raising before publish is
# how this path went silent. It also lets a policy denial win over a topology
# fact.


class _Runtime:
    """Just enough runtime for the real bridge method."""

    def __init__(self, bus: IntentBus) -> None:
        self.intent_bus = bus

    _dispatch_watch_intent = staticmethod(object())  # replaced below


def _bridge(bus: IntentBus):
    from probos.runtime import ProbOSRuntime

    rt = _Runtime(bus)
    return lambda i, p: ProbOSRuntime._dispatch_watch_intent(rt, i, p)


@pytest.mark.asyncio
async def test_the_bridge_raises_when_nobody_would_be_invoked() -> None:
    with pytest.raises(IntentNoSubscriber):
        await _bridge(_bus())("unhandled", {})


@pytest.mark.asyncio
async def test_the_bridge_does_not_raise_when_a_handler_would_be_invoked() -> None:
    bus = _bus()
    bus.subscribe("a1", _noop, ["handled"])
    await _bridge(bus)("handled", {})  # must not raise


# ── WatchManager: Captain's orders ────────────────────────────────────────


class _Dispatch:
    def __init__(self, *, raises: BaseException | None = None, result: object = None) -> None:
        self._raises = raises
        self._result = result if result is not None else [object()]
        self.calls: list[str] = []

    async def __call__(self, intent_type: str, params: dict) -> object:
        self.calls.append(intent_type)
        if self._raises is not None:
            raise self._raises
        return self._result


def _order(**kw: object) -> CaptainOrder:
    base: dict = {
        "id": "o1", "intent_type": "some_intent", "intent_params": {},
        "target_type": "all", "one_shot": True,
    }
    base.update(kw)
    return CaptainOrder(**base)  # type: ignore[arg-type]


def _mgr(dispatch: _Dispatch, order: CaptainOrder) -> WatchManager:
    wm = WatchManager(dispatch_fn=dispatch)
    wm._captain_orders.append(order)
    return wm


@pytest.mark.asyncio
async def test_a_one_shot_order_reaching_nobody_is_not_consumed() -> None:
    """The reported defect. Unfixed, this ends active=False executed_count=1."""
    dispatch = _Dispatch(raises=IntentNoSubscriber("some_intent"))
    order = _order()
    await _mgr(dispatch, order)._dispatch_due_orders()

    assert dispatch.calls, "premise: it must actually have been dispatched"
    assert order.active is True
    assert order.executed_count == 0


@pytest.mark.asyncio
async def test_a_delivered_order_is_still_consumed_exactly_once() -> None:
    """Positive control. Refusing to consume ANY order would satisfy the test
    above while breaking the feature."""
    order = _order()
    wm = _mgr(_Dispatch(), order)
    await wm._dispatch_due_orders()
    await wm._dispatch_due_orders()

    assert order.active is False
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_a_handler_that_acts_and_returns_none_does_not_re_fire() -> None:
    """THE REGRESSION THAT KILLED THE PREVIOUS ATTEMPT.

    A handler that runs, performs a side effect, and returns None makes
    ``publish`` yield ``[]``. The reverted fix read that as non-delivery, left
    the order active, and re-ran the side effect on every sweep. Driven through
    the REAL bus and the REAL bridge, because a double that returns ``[]``
    cannot reproduce it.
    """
    bus = _bus()
    side_effects: list[str] = []

    async def acts_then_returns_none(msg: IntentMessage) -> None:
        side_effects.append(msg.intent)
        return None

    bus.subscribe("worker", acts_then_returns_none, ["scan_sector"])

    order = _order(intent_type="scan_sector")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()
    await wm._dispatch_due_orders()

    assert side_effects == ["scan_sector"], "the side effect must fire exactly once"
    assert order.active is False, "an invoked handler means delivered, even returning None"
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_an_order_runs_once_a_subscriber_appears() -> None:
    """The point of leaving it active: it must still be able to fire later."""
    order = _order()
    wm = _mgr(_Dispatch(raises=IntentNoSubscriber("some_intent")), order)
    await wm._dispatch_due_orders()
    assert order.active is True

    wm._dispatch_fn = _Dispatch()
    await wm._dispatch_due_orders()
    assert order.executed_count == 1
    assert order.active is False


@pytest.mark.asyncio
async def test_a_recurring_order_reaching_nobody_accrues_no_count() -> None:
    order = _order(one_shot=False)
    await _mgr(_Dispatch(raises=IntentNoSubscriber("some_intent")), order)._dispatch_due_orders()
    assert order.active is True
    assert order.executed_count == 0


@pytest.mark.asyncio
async def test_end_to_end_a_one_shot_order_survives_an_empty_mesh() -> None:
    """WatchManager -> real bridge -> real bus, with nobody subscribed.

    The unit tests above inject a raising double, so they never exercise the
    bridge's decision. This one does, and is what fails if the refusal is
    removed or the predicate stops discriminating.
    """
    bus = _bus()
    order = _order(intent_type="unhandled_everywhere")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()

    assert order.active is True, "nobody could have run it, so it must remain"
    assert order.executed_count == 0


@pytest.mark.asyncio
async def test_end_to_end_the_same_order_fires_once_an_agent_registers() -> None:
    """The pair to the above: the order survived, so it must still be able to
    run when the handling agent finally appears."""
    bus = _bus()
    order = _order(intent_type="arrives_later")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()
    assert order.active is True

    delivered: list[str] = []

    async def handler(msg: IntentMessage) -> IntentResult:
        delivered.append(msg.intent)
        return IntentResult(intent_id=msg.id, agent_id="late", success=True)

    bus.subscribe("late", handler, ["arrives_later"])
    await wm._dispatch_due_orders()

    assert delivered == ["arrives_later"]
    assert order.active is False
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_a_federated_bus_is_never_reported_as_no_subscriber() -> None:
    """Found by review. ``broadcast`` forwards to peers, so a remote agent may
    have run the order even with zero LOCAL candidates. Reporting non-delivery
    there would leave the order active and re-execute it remotely next sweep --
    the duplicate side effect this whole design exists to prevent."""
    bus = _bus()
    remote_calls: list[str] = []

    async def _federate(intent: IntentMessage) -> list[IntentResult]:
        remote_calls.append(intent.intent)
        return []

    bus.set_federation_handler(_federate)
    assert bus.candidate_agent_ids("remote_only") == set(), "premise: no local candidate"
    assert bus.forwards_to_peers is True

    order = _order(intent_type="remote_only")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()

    assert remote_calls == ["remote_only"], "premise: it really was forwarded"
    assert order.active is False, "forwarded is delivered -- must not retry"
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_known_limitation_federation_configured_but_no_peer_still_consumes() -> None:
    """KNOWN LIMITATION, pinned so it is visible rather than discovered.

    ``forwards_to_peers`` reports that federation is CONFIGURED, not that a peer
    accepted the work. With federation wired and no peer answering, the order is
    still consumed having done nothing.

    This is NOT a regression -- it is exactly what HEAD does for every order --
    and it is NOT the desirable contract. Closing it needs a delivery-admission
    signal from the federation bridge, which does not exist; filed separately.

    Federation is disabled by default (``FederationConfig.enabled = False``), so
    a default single-node vessel is fully protected by the tests above. This
    test exists so that when the admission signal lands, this assertion FAILS
    and forces the behaviour to be corrected here.
    """
    bus = _bus()

    async def _no_peers(intent: IntentMessage) -> list[IntentResult]:
        return []  # configured, but nothing accepted it

    bus.set_federation_handler(_no_peers)
    order = _order(intent_type="nobody_anywhere")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()

    assert order.active is False, (
        "documents today's behaviour, not the desired one -- when federation "
        "gains a delivery-admission signal this must become active=True"
    )


@pytest.mark.asyncio
async def test_without_federation_an_empty_mesh_still_refuses() -> None:
    """The control: the BF-814 protection must survive the federation carve-out,
    and this is the DEFAULT configuration."""
    bus = _bus()
    assert bus.forwards_to_peers is False
    with pytest.raises(IntentNoSubscriber):
        await _bridge(bus)("nobody", {})


# ── WatchManager: standing tasks, same seam ───────────────────────────────


def _task_mgr(dispatch: _Dispatch, task: StandingTask) -> WatchManager:
    wm = WatchManager(dispatch_fn=dispatch)
    wm._standing_tasks.append(task)
    wm.assign_to_watch("agent-a", wm._current_watch)
    assert wm.get_on_duty(), "premise: dispatch returns early with nobody on duty"
    return wm


def _task() -> StandingTask:
    return StandingTask(
        id="t1", intent_type="some_intent", intent_params={},
        interval_seconds=1.0, enabled=True, last_executed=0.0,
    )


@pytest.mark.asyncio
async def test_a_standing_task_reaching_nobody_stays_due() -> None:
    """``last_executed`` gates ``is_due``, so stamping it would idle the task
    for a full interval over work that never ran."""
    dispatch = _Dispatch(raises=IntentNoSubscriber("some_intent"))
    task = _task()
    await _task_mgr(dispatch, task)._dispatch_due_tasks()

    assert dispatch.calls, "premise: it must actually have been dispatched"
    assert task.last_executed == 0.0


@pytest.mark.asyncio
async def test_a_delivered_standing_task_is_stamped() -> None:
    dispatch = _Dispatch()
    task = _task()
    before = time.time()
    await _task_mgr(dispatch, task)._dispatch_due_tasks()

    assert dispatch.calls, "premise: it must actually have been dispatched"
    assert task.last_executed >= before
