"""AD-1276 Section 1 (BF-789, #1253): consumer-side AD-698 enforcement.

Three paths reached a subscriber's handler with the authorization hook never
consulted -- the NATS request/reply callback, the JetStream callback, and the
JetStream -> AD-654b cognitive queue. Every enforcement test here drives a
CONNECTED ``MockNATSBus`` round trip; none replaces the transport with an
``AsyncMock``, because a transport that is skipped proves nothing about a check
that sits on it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from probos.cognitive.queue import AgentCognitiveQueue
from probos.extensions import overlay
from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_hooks():
    """AD-698's registry is module-level; leaking a hook would poison the suite."""
    before = list(overlay._PRE_INTENT_AUTH_HOOKS)
    overlay._PRE_INTENT_AUTH_HOOKS.clear()
    yield
    overlay._PRE_INTENT_AUTH_HOOKS.clear()
    overlay._PRE_INTENT_AUTH_HOOKS.extend(before)


class _Handler:
    """Records whether the handler actually ran -- the thing a bypass proves."""

    def __init__(self, agent_id: str = "agent-1") -> None:
        self.agent_id = agent_id
        self.calls: list[str] = []

    async def __call__(self, intent: IntentMessage) -> IntentResult:
        self.calls.append(intent.id)
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.agent_id,
            success=True,
            result="answered",
            confidence=1.0,
        )


class _CountingHook:
    """Counts every evaluation, so double-charging is visible, not inferred."""

    def __init__(self, *, allow: bool) -> None:
        self.allow = allow
        self.calls = 0

    def __call__(self, _intent: Any) -> bool:
        self.calls += 1
        return self.allow


@pytest.fixture
async def mock_bus():
    bus = MockNATSBus()
    await bus.start()
    yield bus
    await bus.stop()


async def _settle(bus: IntentBus) -> None:
    """Await the subscription tasks ``subscribe()`` spawned.

    Waits on the exact state the assertions depend on -- the tasks themselves --
    rather than sleeping for a duration that only correlates with it.
    """
    pending = [t for t in bus._pending_sub_tasks if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _connected_bus(
    mock: MockNATSBus,
    handler: _Handler,
    *,
    agent_id: str = "agent-1",
    dispatch: bool = False,
) -> IntentBus:
    bus = IntentBus(SignalManager())
    bus.set_nats_bus(mock)
    bus.subscribe(agent_id, handler)
    await _settle(bus)
    if dispatch:
        # The production path finalize.py takes once the subject prefix is stable.
        await bus.create_dispatch_consumers()
    return bus


def _intent(intent_id: str = "i-1", target: str = "agent-1") -> IntentMessage:
    return IntentMessage(
        intent="probe", params={}, id=intent_id, target_agent_id=target
    )


async def _drain_queue(queue: AgentCognitiveQueue, handler: _Handler) -> None:
    """Let the queue processor run until it has handled what it was given."""
    for _ in range(50):
        if handler.calls:
            return
        if queue.pending_count() == 0 and not queue.is_processing():
            await asyncio.sleep(0)
            if queue.pending_count() == 0 and not queue.is_processing():
                return
        await asyncio.sleep(0.01)


# ── Enforcement: connected transport, no transport mocking ────────────────


class TestADeniedIntentNeverReachesAHandler:
    async def test_a_denied_intent_never_reaches_the_handler_over_request_reply(
        self, mock_bus
    ):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler)
        overlay.register_pre_intent_authorization_hook(
            "deny_all", _CountingHook(allow=False)
        )

        # Straight onto the wire: the cross-node shape, so no producer on this
        # node authorized it.
        await mock_bus.request("intent.agent-1", IntentBus._serialize_intent(_intent()))

        assert handler.calls == [], (
            "the handler ran for an intent policy refused; this is the BF-789 "
            "bypass on the request/reply callback"
        )

    async def test_a_denied_intent_never_reaches_the_handler_over_jetstream(
        self, mock_bus
    ):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler, dispatch=True)
        overlay.register_pre_intent_authorization_hook(
            "deny_all", _CountingHook(allow=False)
        )

        await mock_bus.js_publish(
            "intent.dispatch.agent-1", IntentBus._serialize_intent(_intent())
        )

        assert handler.calls == []

    async def test_a_denied_intent_is_never_enqueued_on_the_cognitive_queue(
        self, mock_bus
    ):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler, dispatch=True)
        queue = AgentCognitiveQueue(agent_id="agent-1", handler=handler)
        bus.register_queue("agent-1", queue)
        await queue.start()
        overlay.register_pre_intent_authorization_hook(
            "deny_all", _CountingHook(allow=False)
        )
        try:
            await mock_bus.js_publish(
                "intent.dispatch.agent-1", IntentBus._serialize_intent(_intent())
            )
            await _drain_queue(queue, handler)

            assert queue.pending_count() == 0, "a denied intent sits in the queue"
            assert handler.calls == [], "the queue ran a denied intent"
        finally:
            await queue.shutdown()

    async def test_an_allowed_intent_still_reaches_the_handler_on_both_transports(
        self, mock_bus
    ):
        """The benign control: a fix that denies everything passes the three
        tests above and destroys the ship."""
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler, dispatch=True)
        overlay.register_pre_intent_authorization_hook(
            "allow_all", _CountingHook(allow=True)
        )

        await mock_bus.request(
            "intent.agent-1", IntentBus._serialize_intent(_intent("rr-1"))
        )
        await mock_bus.js_publish(
            "intent.dispatch.agent-1", IntentBus._serialize_intent(_intent("js-1"))
        )

        assert handler.calls == ["rr-1", "js-1"]

    async def test_an_allowed_intent_is_still_enqueued_on_the_cognitive_queue(
        self, mock_bus
    ):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler, dispatch=True)
        queue = AgentCognitiveQueue(agent_id="agent-1", handler=handler)
        bus.register_queue("agent-1", queue)
        await queue.start()
        overlay.register_pre_intent_authorization_hook(
            "allow_all", _CountingHook(allow=True)
        )
        try:
            await mock_bus.js_publish(
                "intent.dispatch.agent-1", IntentBus._serialize_intent(_intent("q-1"))
            )
            await _drain_queue(queue, handler)

            assert handler.calls == ["q-1"]
        finally:
            await queue.shutdown()


# ── A loopback is evaluated on BOTH sides, by design ────────────────────


class TestALoopbackIsEvaluatedOnBothSides:
    """A locally-subscribed agent also subscribes to its own NATS and JetStream
    subjects, so a loopback can re-enter this same process. AD-1292 removed the
    ``send`` half of that -- it no longer publishes to the wire when the target
    is subscribed here -- but ``dispatch_async`` still publishes and is still
    evaluated twice, deliberately: its publish is a DURABLE JetStream delivery
    (``durable=``, ``manual_ack=True``, ``max_deliver=10``, 5-minute
    retention), so suppressing it would trade crash-recovery redelivery for an
    in-memory task -- message loss, bought to fix a rate limiter's accounting.

    That is deliberate, and these tests pin it so nobody "fixes" it by adding a
    suppression ledger back without reading why the last one was removed. Three
    adversarial review rounds each reproduced a DIFFERENT way for a suppression
    record to be spent by a delivery it was not minted for. Suppression is an
    optimization; enforcement is the fix.

    The remaining cost is real but bounded: a stateless RBAC hook does not care,
    and a stateful one over-counts. It never under-authorizes.
    """

    async def test_a_loopback_send_is_charged_once_now_that_it_does_not_publish(
        self, mock_bus
    ):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler)
        hook = _CountingHook(allow=True)
        overlay.register_pre_intent_authorization_hook("counting", hook)

        result = await bus.send(_intent("loop-send"))

        # PREMISE: the delivery actually completed, or the count proves nothing.
        assert result is not None, "the send did not deliver"
        assert handler.calls == ["loop-send"]
        # Was ``== 2``: it pinned the producer + consumer double charge that
        # AD-1292 removed. Edited rather than deleted so the cost that used to
        # be accepted here stays on the record.
        assert hook.calls == 1, (
            "AD-1292: `send` no longer publishes to the wire when the target "
            "is subscribed on this node, so one logical delivery is one "
            "evaluation. A count of 2 means the loopback is back; a count of "
            "0 means a suppression LEDGER is back -- read "
            "TestThereIsNoSuppressionLedger before changing this"
        )

    async def test_a_loopback_dispatch_charges_the_hook_on_both_sides(self, mock_bus):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler, dispatch=True)
        hook = _CountingHook(allow=True)
        overlay.register_pre_intent_authorization_hook("counting", hook)

        admission = await bus.dispatch_async(_intent("loop-dispatch"))
        await asyncio.sleep(0.05)

        assert admission.admitted is True
        assert handler.calls == ["loop-dispatch"], "the dispatch never arrived"
        assert hook.calls == 2

    async def test_a_redelivered_dispatch_is_evaluated_every_time(self, mock_bus):
        """JetStream redelivers -- BF-234 exists because it does. Every delivery
        is judged on its own merits, so a redelivery cannot ride in on an
        earlier one's verdict."""
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler, dispatch=True)
        hook = _CountingHook(allow=True)
        overlay.register_pre_intent_authorization_hook("counting", hook)

        intent = _intent("loop-redeliver")
        await bus.dispatch_async(intent)
        await asyncio.sleep(0.05)
        calls_after_first = hook.calls
        assert calls_after_first >= 1, "the first delivery never happened"

        await mock_bus.js_publish(
            "intent.dispatch.agent-1", IntentBus._serialize_intent(intent)
        )
        await asyncio.sleep(0.05)

        assert handler.calls == ["loop-redeliver", "loop-redeliver"]
        assert hook.calls > calls_after_first, (
            "the redelivery was waved through on the first delivery's verdict"
        )

    async def test_a_denied_inbound_is_denied_however_many_times_it_arrives(
        self, mock_bus
    ):
        """The property that actually matters: no accumulated state can turn a
        denial into an allow."""
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler)
        hook = _CountingHook(allow=False)
        overlay.register_pre_intent_authorization_hook("deny_all", hook)

        for _ in range(3):
            await mock_bus.publish(
                "intent.agent-1", IntentBus._serialize_intent(_intent("repeat-1"))
            )
        await asyncio.sleep(0.05)

        assert handler.calls == []
        assert hook.calls == 3



# ── Denial shape ──────────────────────────────────────────────────────────


class TestTheDenialShapeReachesTheCaller:
    async def test_a_remote_denial_surfaces_as_intent_authorization_denied_not_a_timeout(
        self, mock_bus
    ):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler)
        overlay.register_pre_intent_authorization_hook(
            "deny_all", _CountingHook(allow=False)
        )

        # The producer gate is what a real caller hits first, so drive the
        # consumer conversion directly: a reply carrying the denial envelope.
        with pytest.raises(IntentAuthorizationDenied) as excinfo:
            await bus._nats_send(_intent("deny-rr"), raise_on_denial=True)

        assert excinfo.value.reason == "deny_all"
        assert handler.calls == []

    async def test_a_remote_denial_is_distinguishable_from_a_decline(self, mock_bus):
        """Both are ``None`` at the seam without a distinct key, so the wire
        payload is where the difference has to live."""
        declining = _Handler()

        async def _decline(_intent: IntentMessage) -> None:
            declining.calls.append(_intent.id)
            return None

        bus = IntentBus(SignalManager())
        bus.set_nats_bus(mock_bus)
        bus.subscribe("agent-1", _decline)
        await _settle(bus)
        overlay.register_pre_intent_authorization_hook(
            "allow_all", _CountingHook(allow=True)
        )
        reply = await mock_bus.request(
            "intent.agent-1", IntentBus._serialize_intent(_intent("decline-1"))
        )
        assert reply is not None and reply.data == {"declined": True}

        overlay._PRE_INTENT_AUTH_HOOKS.clear()
        overlay.register_pre_intent_authorization_hook(
            "deny_all", _CountingHook(allow=False)
        )
        denied = await mock_bus.request(
            "intent.agent-1", IntentBus._serialize_intent(_intent("deny-1"))
        )

        assert denied is not None, "a denial that sends nothing reads as a timeout"
        assert denied.data.get("denied") is True
        assert "declined" not in denied.data, (
            "reusing the decline key collapses a policy refusal into an "
            "agent's own choice"
        )
        assert denied.data.get("reason") == "deny_all"

    async def test_the_default_send_shape_for_a_remote_denial_is_still_none(
        self, mock_bus
    ):
        """None of the 14 ``send`` seams may see a type it did not handle."""
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler)
        overlay.register_pre_intent_authorization_hook(
            "deny_all", _CountingHook(allow=False)
        )

        assert await bus._nats_send(_intent("deny-default")) is None

    async def test_a_denial_envelope_that_cannot_fit_the_budget_is_not_submitted(
        self, mock_bus
    ):
        """BF-827 parity. An oversized reply is accepted locally and refused by
        the server asynchronously, so the caller times out holding nothing."""
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler)
        mock_bus.max_payload = 40  # the smallest denial is 15 bytes
        overlay.register_pre_intent_authorization_hook(
            "deny_all", _CountingHook(allow=False)
        )

        reply = await mock_bus.request(
            "intent.agent-1",
            IntentBus._serialize_intent(_intent("budget-1")),
            headers={"X-Pad": "p" * 200},
        )

        assert reply is None, (
            "a denial larger than the budget was submitted; the server would "
            "refuse it asynchronously and the caller would time out"
        )
        assert handler.calls == []

    async def test_a_denial_degrades_to_a_smaller_form_before_it_gives_up(self):
        """A peer told only 'denied' is better informed than one that times
        out, so the reason is dropped before the fact of the denial is."""
        full = IntentBus._denial_bytes("some_hook", "nats_inbound", 1000)
        assert full is not None and json.loads(full) == {
            "denied": True,
            "reason": "some_hook",
            "entry_point": "nats_inbound",
        }

        # 36 bytes encoded, so 40 admits it and the 70-byte full form is out.
        smaller = IntentBus._denial_bytes("some_hook", "nats_inbound", 40)
        assert smaller is not None and json.loads(smaller) == {
            "denied": True,
            "reason": "some_hook",
        }

        smallest = IntentBus._denial_bytes("some_hook", "nats_inbound", 16)
        assert smallest == b'{"denied":true}'

        assert IntentBus._denial_bytes("some_hook", "nats_inbound", 14) is None

    async def test_a_denied_jetstream_message_is_termed_and_not_acked(self, mock_bus):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler, dispatch=True)
        overlay.register_pre_intent_authorization_hook(
            "deny_all", _CountingHook(allow=False)
        )

        await mock_bus.js_publish(
            "intent.dispatch.agent-1", IntentBus._serialize_intent(_intent("term-1"))
        )

        assert len(mock_bus.terms) == 1, (
            "the denied dispatch was not termed; acking it instead would "
            "report the work as done"
        )
        assert mock_bus.acks == [], (
            "the denied dispatch was acked; ack and term must stay "
            "distinguishable or this assertion proves nothing"
        )

    async def test_an_allowed_jetstream_message_is_acked_and_not_termed(self, mock_bus):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler, dispatch=True)
        overlay.register_pre_intent_authorization_hook(
            "allow_all", _CountingHook(allow=True)
        )

        await mock_bus.js_publish(
            "intent.dispatch.agent-1", IntentBus._serialize_intent(_intent("ack-1"))
        )

        assert len(mock_bus.acks) == 1 and mock_bus.terms == []


# ── The marker is never on the wire ───────────────────────────────────────


class TestTheLedgerNeverTravels:
    async def test_no_authorization_marker_appears_in_the_serialized_intent(self):
        """A peer-settable flag would be a remote policy bypass -- strictly
        worse than the gap this AD closes."""
        wire = IntentBus._serialize_intent(_intent("wire-1"))

        for key in wire:
            assert "author" not in key.lower(), f"{key!r} leaks the ledger"
        assert "denied" not in wire

    async def test_a_peer_setting_an_authorization_field_is_not_believed(self):
        bus = IntentBus(SignalManager())
        overlay.register_pre_intent_authorization_hook(
            "deny_all", _CountingHook(allow=False)
        )
        hostile = IntentBus._serialize_intent(_intent("hostile-1"))
        hostile["authorized"] = True
        hostile["_authorized"] = True

        intent = IntentBus._deserialize_intent(hostile)
        allowed, _ = bus._authorize_inbound(
            intent, entry_point="nats_inbound", agent_id="agent-1"
        )

        assert allowed is False


# ── No suppression ledger, deliberately ───────────────────────────────


class TestThereIsNoSuppressionLedger:
    """Guards the decision, not just the code.

    Three review rounds each reproduced a different escape from a suppression
    ledger: keyed on the peer-controlled ``intent.id``; minted before route
    selection, so a transport-less ``send`` left a spendable orphan; and minted
    for one channel but spendable from another. Every fix was sound and the next
    round found the invariant broken elsewhere.

    If someone reintroduces suppression, these fail and point at the reasoning.
    """

    async def test_the_bus_holds_no_authorization_ledger_state(self):
        bus = IntentBus(SignalManager())

        assert not hasattr(bus, "_authorized_intents"), (
            "a suppression ledger is back; it needs a delivery identity the "
            "peer cannot influence AND that names the channel, or it reopens "
            "one of the three reproduced bypasses"
        )

    async def test_an_id_authorized_for_one_agent_does_not_waive_policy_for_another(
        self, mock_bus
    ):
        """The round-1 bypass, kept as a regression: ``intent.id`` is a WIRE
        field, so a locally-authorized id must not waive policy for an unrelated
        inbound message reusing it -- even when the peer SPOOFS
        ``target_agent_id`` to the agent that was authorized."""
        handler = _Handler(agent_id="agent-b")
        bus = await _connected_bus(mock_bus, handler, agent_id="agent-b")
        bus.subscribe("agent-a", _Handler(agent_id="agent-a"))

        allowing = _CountingHook(allow=True)
        overlay.register_pre_intent_authorization_hook("allow_all", allowing)
        await bus.send(_intent("collision-id", target="agent-a"))
        assert allowing.calls >= 1, "the authorized send never happened"

        overlay._PRE_INTENT_AUTH_HOOKS.clear()
        denying = _CountingHook(allow=False)
        overlay.register_pre_intent_authorization_hook("deny_all", denying)

        await mock_bus.publish(
            "intent.agent-b",
            IntentBus._serialize_intent(_intent("collision-id", target="agent-a")),
        )
        await asyncio.sleep(0.05)

        assert denying.calls == 1, "the hook was skipped -- policy was bypassed"
        assert handler.calls == [], "a denied intent reached the handler"

    async def test_a_transport_less_send_leaves_nothing_a_later_inbound_can_spend(
        self,
    ):
        """The round-2 bypass, kept as a regression: a ``send`` with no
        transport ran the handler in-process, and the charge it left behind was
        spendable by a later inbound reusing that id -- past a DENYING hook."""
        bus = IntentBus(SignalManager())
        handler = _Handler()
        bus.subscribe("agent-1", handler)
        allowing = _CountingHook(allow=True)
        overlay.register_pre_intent_authorization_hook("allow_all", allowing)

        # PREMISE: no transport, so this delivery can never loop back.
        assert bus._nats_bus is None
        assert await bus.send(_intent("orphan-1")) is not None, (
            "the direct path did not run; the orphan window was never opened"
        )

        overlay._PRE_INTENT_AUTH_HOOKS.clear()
        denying = _CountingHook(allow=False)
        overlay.register_pre_intent_authorization_hook("deny_all", denying)
        allowed, _ = bus._authorize_inbound(
            _intent("orphan-1"), entry_point="nats_inbound", agent_id="agent-1"
        )

        assert allowed is False and denying.calls == 1

    async def test_a_dispatch_charge_cannot_be_spent_by_a_request_reply_inbound(
        self,
    ):
        """The round-3 bypass, kept as a regression: a charge minted on the
        dispatch path was spendable from the request/reply consumer, because
        both popped the same key."""
        bus = IntentBus(SignalManager())
        bus.subscribe("agent-1", _Handler())
        allowing = _CountingHook(allow=True)
        overlay.register_pre_intent_authorization_hook("allow_all", allowing)

        admission = await bus.dispatch_async(_intent("cross-1"))
        assert admission is not None, "dispatch did not run"

        overlay._PRE_INTENT_AUTH_HOOKS.clear()
        denying = _CountingHook(allow=False)
        overlay.register_pre_intent_authorization_hook("deny_all", denying)
        allowed, _ = bus._authorize_inbound(
            _intent("cross-1"), entry_point="nats_inbound", agent_id="agent-1"
        )

        assert allowed is False and denying.calls == 1
