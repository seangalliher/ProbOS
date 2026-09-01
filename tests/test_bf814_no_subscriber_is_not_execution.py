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

AD-1297 (BF-870, #1346) closed the federation half. BF-814 carved federation out
using ``forwards_to_peers`` -- transport CONFIGURED -- which is a proxy for
delivery and not delivery itself, so a wired mesh with nobody answering still
consumed one-shot orders. ``FederationForwardOutcome`` carries what the peers
actually said, and the rule is asymmetric on purpose: only an explicit "I had no
candidate" counts as absence. Silence, an old peer, a partial report or a
transport fault are all UNKNOWN, and UNKNOWN falls back to consuming -- because
the other direction strands every order on a mixed-version mesh forever.
"""

from __future__ import annotations

import time

import pytest

from probos.federation.bridge import FederationForwardOutcome
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
    the duplicate side effect this whole design exists to prevent.

    AD-1297: the callback here returns a PLAIN LIST, so after AD-1297 this pins
    the LEGACY path specifically -- a pre-AD-1297 federation handler reports no
    admission at all, which is UNKNOWN and must still consume. It no longer
    proves the general federated case; the admission tests below do that."""
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
async def test_federation_configured_but_no_peer_admitting_does_not_consume() -> None:
    """AD-1297 (BF-870, #1346). This test previously asserted the OPPOSITE.

    It was written as a pinned KNOWN LIMITATION: ``forwards_to_peers`` reported
    that federation was CONFIGURED, not that a peer accepted the work, so with a
    transport wired and nobody answering the order was consumed having done
    nothing. Its own docstring said "when the admission signal lands, this
    assertion FAILS and forces the behaviour to be corrected here."

    That signal is ``FederationForwardOutcome``. The assertion is updated, not
    removed -- the old one recorded a real defect, and deleting it would erase
    the only evidence the defect existed.

    Two zeros are required and they are not the same: nothing admitted AND
    nothing unknown. A peer that answered "no candidate" is a KNOWN absence.
    """
    bus = _bus()

    async def _peer_answered_with_no_candidate(
        intent: IntentMessage,
    ) -> FederationForwardOutcome:
        return FederationForwardOutcome(
            peers_attempted=1,
            peers_answered=1,
            peers_admitted=0,
            peers_unknown=0,
        )

    bus.set_federation_handler(_peer_answered_with_no_candidate)
    assert bus.candidate_agent_ids("nobody_anywhere") == set(), (
        "premise: no local candidate either"
    )
    order = _order(intent_type="nobody_anywhere")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()

    assert order.active is True, (
        "no local candidate and no peer admitted it -- nobody ran this, so the "
        "order must survive to be run later"
    )
    assert order.executed_count == 0


@pytest.mark.asyncio
async def test_federation_peers_that_never_answer_consume_the_order() -> None:
    """Peers were attempted and none replied. That is UNKNOWN, not absence.

    This test previously asserted the opposite, on the reasoning that "nothing
    claimed the work, so nothing can have run it". A peer can receive the send,
    execute the handler with side effects, and have its reply lost -- so
    silence proves nothing. Keeping the order active on that basis re-dispatches
    work that may already have run, which is BF-814 attempt 1 one layer out and
    was measured producing duplicate remote side effects.

    The trade is deliberate and asymmetric: a lost order is recoverable by
    reissuing it, a duplicated side effect is not. The genuine no-delivery case
    -- no peer selected at all -- is covered by the test above, where nothing
    was sent and the order rightly survives.
    """
    bus = _bus()

    async def _nobody_answered(intent: IntentMessage) -> FederationForwardOutcome:
        # What the real bridge now produces for two silent peers.
        return FederationForwardOutcome(
            peers_attempted=2, peers_answered=0, peers_unknown=2,
        )

    bus.set_federation_handler(_nobody_answered)
    order = _order(intent_type="nobody_anywhere")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()

    assert order.active is False, (
        "silence was treated as proof nobody ran it, so the order stayed "
        "active and will re-fire work that may already have executed"
    )
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_a_peer_that_admits_and_returns_nothing_consumes_the_order() -> None:
    """The positive control for AD-1297, and the reason an empty list cannot be
    the signal: the remote handler RAN, acted, and returned nothing.

    Leaving the order active here would re-fire the remote side effect on the
    next sweep -- the duplicate-execution failure the whole design prevents.
    """
    bus = _bus()
    forwarded: list[str] = []

    async def _peer_admits(intent: IntentMessage) -> FederationForwardOutcome:
        forwarded.append(intent.intent)
        return FederationForwardOutcome(
            peers_attempted=1,
            peers_answered=1,
            peers_admitted=1,
            peers_unknown=0,
        )

    bus.set_federation_handler(_peer_admits)
    order = _order(intent_type="remote_handler_returns_none")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()
    await wm._dispatch_due_orders()

    assert forwarded == ["remote_handler_returns_none"], (
        "premise: forwarded exactly once, so the remote side effect fired once"
    )
    assert order.active is False, "a peer admitted it -- that is delivery"
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_a_legacy_federation_callback_is_unknown_not_absent() -> None:
    """MIXED VERSION. A callback predating ``FederationForwardOutcome`` returns
    a plain list and reports nothing about admission.

    Reading that as "no candidate" is this defect inverted: on a mesh with one
    un-upgraded node every order would sit active forever, re-dispatched on
    every sweep. UNKNOWN must fall back to today's behaviour -- consume it --
    because that is the direction that cannot strand work.
    """
    bus = _bus()

    async def _legacy(intent: IntentMessage) -> list[IntentResult]:
        return []

    bus.set_federation_handler(_legacy)
    order = _order(intent_type="old_peer_out_there")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()

    assert order.active is False
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_a_partial_outcome_shape_is_unknown_not_absent() -> None:
    """Same rule, one step subtler: an object carrying SOME counters but not
    both. Half a report is not a report, so it is UNKNOWN."""
    bus = _bus()

    class _HalfOutcome(list):
        peers_admitted = 0  # ...and no peers_unknown

    async def _partial(intent: IntentMessage) -> list[IntentResult]:
        return _HalfOutcome()

    bus.set_federation_handler(_partial)
    order = _order(intent_type="half_a_report")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()

    assert order.active is False, "an incomplete report cannot prove absence"
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_a_federation_transport_failure_is_unknown_not_absent() -> None:
    """``broadcast`` swallows a federation exception by design. That is an
    infrastructure fault, not evidence that no peer had a handler -- a peer may
    have received and run the intent before the failure."""
    bus = _bus()

    async def _explodes(intent: IntentMessage) -> list[IntentResult]:
        raise RuntimeError("transport down")

    bus.set_federation_handler(_explodes)
    order = _order(intent_type="transport_is_broken")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()

    assert order.active is False, (
        "an infrastructure failure must not be reported as no-subscriber"
    )
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_a_federation_callback_returning_a_non_iterable_still_degrades() -> None:
    """``broadcast`` has always swallowed a bad federation return; AD-1297 must
    not widen what escapes it.

    Reading the counters after ``extend`` would have moved that ``extend`` out
    of the guarded block, so a non-iterable return would newly propagate out of
    ``broadcast`` to callers that have never handled it.
    """
    bus = _bus()

    async def _returns_garbage(intent: IntentMessage) -> list[IntentResult]:
        return 42  # type: ignore[return-value]

    bus.set_federation_handler(_returns_garbage)
    order = _order(intent_type="bad_callback")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    # Must not raise out of publish.
    results = await bus.publish(
        IntentMessage(intent="bad_callback", params={}),
        raise_on_no_subscriber=False,
    )
    assert results == []

    await wm._dispatch_due_orders()
    assert order.active is False, "a malformed callback is UNKNOWN, not absence"
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_a_local_candidate_beats_a_silent_federation() -> None:
    """Federation reporting nothing does not override a LOCAL handler that ran.

    The predicate needs every clause; this is the one that fails if the local
    half is dropped in favour of the new federation half."""
    bus = _bus()
    side_effects: list[str] = []

    async def acts_then_returns_none(msg: IntentMessage) -> None:
        side_effects.append(msg.intent)
        return None

    bus.subscribe("worker", acts_then_returns_none, ["local_and_federated"])

    async def _nobody(intent: IntentMessage) -> FederationForwardOutcome:
        return FederationForwardOutcome(peers_attempted=1, peers_answered=1)

    bus.set_federation_handler(_nobody)
    order = _order(intent_type="local_and_federated")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()
    await wm._dispatch_due_orders()

    assert side_effects == ["local_and_federated"]
    assert order.active is False
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_a_remote_result_beats_a_miscounted_admission() -> None:
    """Defence in depth. Even if the counters said nobody admitted it, a
    returned remote result is proof the work reached someone."""
    bus = _bus()

    async def _returned_a_result(intent: IntentMessage) -> FederationForwardOutcome:
        return FederationForwardOutcome(
            [IntentResult(intent_id=intent.id, agent_id="remote", success=True)],
            peers_attempted=1,
            peers_answered=1,
            peers_admitted=0,
            peers_unknown=0,
        )

    bus.set_federation_handler(_returned_a_result)
    order = _order(intent_type="answered_anyway")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()

    assert order.active is False
    assert order.executed_count == 1


@pytest.mark.asyncio
async def test_end_to_end_a_real_bridge_carries_the_admission_to_the_order() -> None:
    """THE WHOLE CHAIN: real ``FederationBridge`` -> real ``IntentBus`` ->
    real watch bridge -> ``WatchManager``.

    Every other test here stops at a callback double, and a double cannot show
    that the fact survives the trip. The two halves passing separately is
    exactly the failure mode this repository sees most: the responder sets a
    key nothing reads, or the forwarder counts one nobody sends.

    Both peers here answer honestly and neither has a handler, so the order must
    survive -- which under BF-814's ``forwards_to_peers`` proxy it would not.
    """
    from probos.federation.bridge import FederationBridge
    from probos.federation.router import FederationRouter
    from probos.config import FederationConfig
    from probos.types import FederationMessage, NodeSelfModel

    class _PeerSaysNoCandidate:
        @property
        def connected_peers(self) -> list[str]:
            return ["node-b"]

        async def send_to_peer(self, peer_node_id: str, message) -> None:
            return None

        async def receive_with_timeout(self, *_a, **_k):
            return FederationMessage(
                type="intent_response",
                source_node="node-b",
                message_id="m1",
                payload={"results": [], "admitted": False},
                timestamp=0.0,
            )

    bus = _bus()
    bridge = FederationBridge(
        node_id="node-a",
        transport=_PeerSaysNoCandidate(),
        router=FederationRouter(),
        intent_bus=bus,
        config=FederationConfig(
            enabled=True, node_id="node-a",
            forward_timeout_ms=50, gossip_interval_seconds=1000.0,
            validate_remote_results=False,
        ),
        self_model_fn=lambda: NodeSelfModel(node_id="node-a"),
    )
    bus.set_federation_handler(bridge.forward_intent)

    order = _order(intent_type="nobody_on_either_node")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()

    assert bus.forwards_to_peers is True, "premise: federation really is wired"
    assert order.active is True, (
        "the peer answered that it had no candidate, so nobody ran this"
    )
    assert order.executed_count == 0


@pytest.mark.asyncio
async def test_end_to_end_a_real_bridge_consumes_when_the_peer_admits() -> None:
    """The pair to the above, through the same real chain: the peer says it
    HAD a handler and returns nothing. That is delivery, and re-dispatching it
    would run the remote work twice."""
    from probos.federation.bridge import FederationBridge
    from probos.federation.router import FederationRouter
    from probos.config import FederationConfig
    from probos.types import FederationMessage, NodeSelfModel

    forwarded: list[str] = []

    class _PeerAdmits:
        @property
        def connected_peers(self) -> list[str]:
            return ["node-b"]

        async def send_to_peer(self, peer_node_id: str, message) -> None:
            forwarded.append(message.payload["intent"])

        async def receive_with_timeout(self, *_a, **_k):
            return FederationMessage(
                type="intent_response",
                source_node="node-b",
                message_id="m1",
                payload={"results": [], "admitted": True},
                timestamp=0.0,
            )

    bus = _bus()
    bridge = FederationBridge(
        node_id="node-a",
        transport=_PeerAdmits(),
        router=FederationRouter(),
        intent_bus=bus,
        config=FederationConfig(
            enabled=True, node_id="node-a",
            forward_timeout_ms=50, gossip_interval_seconds=1000.0,
            validate_remote_results=False,
        ),
        self_model_fn=lambda: NodeSelfModel(node_id="node-a"),
    )
    bus.set_federation_handler(bridge.forward_intent)

    order = _order(intent_type="handled_on_node_b")
    wm = WatchManager(dispatch_fn=_bridge(bus))
    wm._captain_orders.append(order)

    await wm._dispatch_due_orders()
    await wm._dispatch_due_orders()

    assert forwarded == ["handled_on_node_b"], "premise: forwarded exactly once"
    assert order.active is False
    assert order.executed_count == 1


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
