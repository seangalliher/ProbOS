"""AD-1292 (#1330): ``send`` stops publishing to the wire for a LOCAL target.

A locally-subscribed agent also subscribes to its own ``intent.{id}`` subject,
so a ``send`` to that agent re-entered this same process: the producer
authorized, the message crossed the wire, and ``_authorize_inbound`` charged
the AD-698 hook a second time for one logical delivery. A stateful hook -- a
rate limiter -- therefore over-counted and throttled early.

Measured before the design, connected versus disconnected against the same
handler and the same hook: connected gave 1 handler invocation and **2**
evaluations, disconnected gave 1 and **1** and still delivered. The control
delivered, so it discriminates: the wire was the cause.

The fix suppresses the loopback DELIVERY at the producer rather than the second
EVALUATION at the consumer, so there is no suppression record to mint, spend or
forge -- see ``TestThereIsNoSuppressionLedger`` in the AD-1276 file for the
three bypasses that killed the ledger-shaped answer.

Every test here drives a CONNECTED ``MockNATSBus``; none replaces the transport
with an ``AsyncMock``, because a transport that is skipped proves nothing about
a route-selection decision that exists to avoid it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.extensions import overlay
from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
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
    """Records whether the handler actually ran -- the premise every count needs."""

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
            confidence=0.75,
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
    handler: Any,
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


def _subjects(mock: MockNATSBus) -> list[str]:
    return [subject for subject, _payload in mock.published]


# ── The charge, and the control that stops over-suppression ───────────────


class TestOneLogicalDeliveryIsOneEvaluation:
    async def test_a_local_send_consults_the_hook_exactly_once(self, mock_bus):
        """End-to-end across the seam: caller -> send -> route selection ->
        local handler -> envelope, asserting the hook is consulted once and the
        handler runs once for one call.

        Confirmed FAILING at HEAD c75428bb with ``hook.calls == 2``.
        """
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler)
        hook = _CountingHook(allow=True)
        overlay.register_pre_intent_authorization_hook("counting", hook)

        result = await bus.send(_intent("local-send"))

        # PREMISE: delivery happened at all, or the count proves nothing.
        assert result is not None, "the send did not deliver"
        assert handler.calls == ["local-send"], "exactly one delivery, or the count is meaningless"
        assert hook.calls == 1, (
            "AD-1292: `send` no longer publishes to the wire when the target "
            "is subscribed on this node, so one logical delivery is one "
            "evaluation. A count of 2 means the loopback is back; a count of "
            "0 means a suppression LEDGER is back -- read "
            "TestThereIsNoSuppressionLedger before changing this"
        )

    async def test_a_send_to_a_target_that_is_not_local_still_crosses_the_wire(
        self, mock_bus
    ):
        """The negative control. Without it, test 1 passes just as well if
        ``send`` stopped publishing entirely -- which would strand every
        cross-node intent on the ship."""
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler)
        overlay.register_pre_intent_authorization_hook(
            "counting", _CountingHook(allow=True)
        )

        # PREMISE: the target really is not local, or "it crossed the wire"
        # would be the only thing it could have done.
        assert not bus.has_subscriber("agent-remote")

        await bus.send(_intent("remote-send", target="agent-remote"))

        assert any(s.endswith("intent.agent-remote") for s in _subjects(mock_bus)), (
            "suppression became 'never publish': a non-local target no longer "
            f"reaches the wire. Subjects seen: {_subjects(mock_bus)}"
        )
        assert handler.calls == [], "the wrong agent's handler ran"


# ── Result parity for the cases that HAVE a shared shape ─────────────────


class TestTheSuppressedRouteReturnsWhatTheWireWouldHave:
    async def test_a_local_send_returns_the_result_the_handler_produced(
        self, mock_bus
    ):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler)
        overlay.register_pre_intent_authorization_hook(
            "counting", _CountingHook(allow=True)
        )

        result = await bus.send(_intent("parity-1"))

        assert result is not None
        assert result.success is True
        assert result.result == "answered"
        assert result.confidence == 0.75
        assert result.agent_id == "agent-1"
        assert result.intent_id == "parity-1"

    async def test_a_declining_handler_still_yields_None(self, mock_bus):
        seen: list[str] = []

        async def _decline(intent: IntentMessage) -> None:
            seen.append(intent.id)
            return None

        bus = await _connected_bus(mock_bus, _decline)
        overlay.register_pre_intent_authorization_hook(
            "counting", _CountingHook(allow=True)
        )

        result = await bus.send(_intent("decline-1"))

        # PREMISE: the handler ran, so None is a decline and not a miss.
        assert seen == ["decline-1"]
        assert result is None

    async def test_a_handler_exception_propagates_and_is_never_wrapped(
        self, mock_bus
    ):
        """The one case that must NOT be harmonized, and the reason why.

        AD-1292's first cut wrapped a handler exception into the wire path's
        ``IntentResult(success=False, error=str(exc))`` so the caller could not
        tell which route ran. ``federation/bridge.py`` catches that exception on
        purpose -- it substitutes the generic ``federation_target_delivery_failed``
        and logs the TYPE alone, so an exception MESSAGE never reaches a peer
        node. The wrap meant that ``except`` never fired and ``str(exc)`` was
        sent over federation. Two AD-730-4 tests caught it.

        So the exception propagates, exactly as it did before AD-1292. Every
        ``send`` caller was already written against that contract: the
        disconnected local path has always raised.
        """
        seen: list[str] = []

        async def _explode(intent: IntentMessage) -> IntentResult:
            seen.append(intent.id)
            raise ValueError("boom")

        bus = await _connected_bus(mock_bus, _explode)
        overlay.register_pre_intent_authorization_hook(
            "counting", _CountingHook(allow=True)
        )

        with pytest.raises(ValueError, match="boom"):
            await bus.send(_intent("boom-1"))

        assert seen == ["boom-1"], "the handler never ran; the raise proves nothing"

    async def test_a_suppressed_send_does_not_leak_the_message_to_federation(
        self, mock_bus
    ):
        """Spans the seam the wrap broke: bus -> the consumer that MUST see a raise.

        ``bridge.py`` is the named consumer of this contract, and it is a
        security control rather than error handling -- reproduced here in
        miniature so a future harmonization fails HERE and not only in
        ``test_ad730_4_directed_federated_vision_dm.py``.
        """
        canary = "CANARY_SECRET_AAAA"

        async def _explode(intent: IntentMessage) -> IntentResult:
            raise RuntimeError(canary)

        bus = await _connected_bus(mock_bus, _explode)
        overlay.register_pre_intent_authorization_hook(
            "counting", _CountingHook(allow=True)
        )

        # The bridge's shape at federation/bridge.py:1949-1968.
        try:
            outbound = await bus.send(_intent("fed-1"))
        except asyncio.CancelledError:
            raise
        except Exception:
            outbound = IntentResult(
                intent_id="fed-1",
                agent_id="agent-1",
                success=False,
                error="federation_target_delivery_failed",
                confidence=0.0,
            )

        assert outbound is not None
        assert outbound.error == "federation_target_delivery_failed"
        assert canary not in str(outbound.error)

    async def test_cancellation_still_propagates(self, mock_bus):
        """Cancellation escapes ``send`` rather than becoming the timeout
        envelope. ``asyncio.CancelledError`` derives from ``BaseException``, so
        catching it here would make shutdown hang."""
        seen: list[str] = []

        async def _cancelled(intent: IntentMessage) -> IntentResult:
            seen.append(intent.id)
            raise asyncio.CancelledError()

        bus = await _connected_bus(mock_bus, _cancelled)
        overlay.register_pre_intent_authorization_hook(
            "counting", _CountingHook(allow=True)
        )

        with pytest.raises(asyncio.CancelledError):
            await bus.send(_intent("cancel-1"))

        assert seen == ["cancel-1"], "the handler never ran; the raise proves nothing"


# ── Capture once: a concurrent unsubscribe must not strand a message ──────


class TestSuppressionIsAnAttemptNotACommitment:
    async def test_a_concurrent_unsubscribe_does_not_strand_the_send(self, mock_bus):
        """``send`` reads ``_subscribers`` ONCE and delivers to that object.

        This is parity with the wire, not a leak: ``_on_nats_intent`` closes
        over its ``handler`` argument and keeps delivering after the dict entry
        is gone. Re-reading the dict after the route decision would let a
        concurrent ``unsubscribe`` drop a message the wire would have carried.
        """
        entered = asyncio.Event()
        released = asyncio.Event()
        seen: list[str] = []

        async def _slow(intent: IntentMessage) -> IntentResult:
            seen.append(intent.id)
            entered.set()
            await released.wait()
            return IntentResult(
                intent_id=intent.id,
                agent_id="agent-1",
                success=True,
                result="late",
                confidence=1.0,
            )

        bus = await _connected_bus(mock_bus, _slow)
        overlay.register_pre_intent_authorization_hook(
            "counting", _CountingHook(allow=True)
        )

        task = asyncio.create_task(bus.send(_intent("strand-1")))
        # PREMISE: the send is genuinely in flight before the subscription goes.
        await asyncio.wait_for(entered.wait(), timeout=5.0)

        bus.unsubscribe("agent-1")
        assert not bus.has_subscriber("agent-1"), (
            "the subscription is still registered; the race was never created"
        )

        released.set()
        result = await asyncio.wait_for(task, timeout=5.0)

        assert seen == ["strand-1"]
        assert result is not None, "a concurrent unsubscribe stranded the send"
        assert result.result == "late"

    async def test_a_denied_local_send_is_denied_exactly_once(self, mock_bus):
        """Enforcement is unchanged; only the duplicate charge is gone."""
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler)
        hook = _CountingHook(allow=False)
        overlay.register_pre_intent_authorization_hook("deny_all", hook)

        result = await bus.send(_intent("denied-1"))

        assert result is None, "a denied send must keep its `None` shape"
        assert handler.calls == [], "a denied intent reached the handler"
        assert hook.calls == 1


# ── The half that is deliberately NOT changed ─────────────────────────────


class TestTheDispatchLoopbackIsLeftAlone:
    async def test_a_dispatch_loopback_is_still_evaluated_twice(self, mock_bus):
        handler = _Handler()
        bus = await _connected_bus(mock_bus, handler, dispatch=True)
        hook = _CountingHook(allow=True)
        overlay.register_pre_intent_authorization_hook("counting", hook)

        admission = await bus.dispatch_async(_intent("loop-dispatch"))
        await asyncio.sleep(0.05)

        assert admission.admitted is True
        assert handler.calls == ["loop-dispatch"], "the dispatch never arrived"
        assert hook.calls == 2, (
            "AD-1292 deliberately did NOT suppress the dispatch loopback, and "
            "this is not an oversight to finish off. That publish is a DURABLE "
            "JetStream delivery -- durable=, stream='INTENT_DISPATCH', "
            "manual_ack=True, max_deliver=10, 5-minute retention -- so it "
            "survives a crash and is redelivered on restart. The local "
            "fallback has no JetStream backing (see intent.py's own "
            "`js_msg=None` comment), so suppressing it would trade "
            "crash-recovery redelivery for an in-memory task: message loss on "
            "restart, bought to fix a rate limiter's accounting. Over-charging "
            "a stateful hook is the smaller harm, and it never under-"
            "authorizes. See #1330 before changing this"
        )
