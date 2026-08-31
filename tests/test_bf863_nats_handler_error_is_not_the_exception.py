"""BF-863 (#1341): a peer never receives a local exception MESSAGE.

``IntentBus._on_nats_intent`` both logged ``str(e)`` and serialized it into the
``IntentResult`` it returned **over the wire**. The exception is raised by a
handler running on THIS node, so its text can carry local filesystem paths,
credentials, or fragments of another caller's payload; the requester is a peer
node. Measured against unfixed HEAD with a connected ``MockNATSBus`` and a
handler raising ``RuntimeError("CANARY_LOCAL_SECRET_/home/captain/.ssh/id_rsa")``::

    LOG> NATS intent handler error for agent-1: CANARY_LOCAL_SECRET_/home/...
    WIRE> "error": "CANARY_LOCAL_SECRET_/home/captain/.ssh/id_rsa"

``federation/bridge.py`` has honoured the opposite contract since AD-730-4 --
log ``exception_type`` alone, substitute a stable code -- and
``test_ad730_4_directed_federated_vision_dm.py`` pins it. Those tests run NATS
**disconnected**, so they reach the target through in-process delivery and the
bridge's ``except``; the connected route, where ``_on_nats_intent`` is the thing
that answers, had no coverage at all. That is why this survived.

Every test here therefore drives the **connected** route end to end -- a sender
bus with no local subscriber, a receiver bus that owns the agent, one
``MockNATSBus`` between them -- and asserts on the canary rather than only on
the replacement code. Asserting the code alone would pass against a payload
that carried the code *and* the message.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import (
    NATSMessage,
    MockNATSBus,
    encoded_header_size,
)
from probos.types import IntentMessage

CANARY = "CANARY_LOCAL_SECRET_/home/captain/.ssh/id_rsa"

# The stable code the peer gets instead. Spelled out rather than imported so a
# rename has to be made deliberately in both places.
GENERIC = "nats_intent_handler_failed"


class _Signals:
    """Stands in for SignalManager: IntentBus only stores it here."""

    def emit(self, *args: Any, **kwargs: Any) -> None:
        return None


def _bus(nats: Any) -> IntentBus:
    bus = IntentBus(_Signals())
    bus._nats_bus = nats
    return bus


async def _connected_pair() -> tuple[IntentBus, IntentBus, MockNATSBus]:
    """A sender with no local subscriber, a receiver that owns the agent.

    AD-1292 suppresses the loopback: a bus that has the target subscribed
    locally never publishes to the wire. One bus therefore cannot exercise the
    connected route at all -- the two-bus shape IS the peer topology.
    """
    nats = MockNATSBus()
    nats._connected = True
    return _bus(nats), _bus(nats), nats


def _rendered(caplog) -> str:
    """Every record as a handler would actually emit it.

    ``repr(record.exc_info)`` is NOT sufficient and this is not a detail: it
    shows the immediate exception only, while ``Formatter.formatException``
    walks ``__context__`` and prints "During handling of the above exception"
    with the ORIGINAL exception's message. Measured -- an ``exc_info=True``
    mutant SURVIVED against the repr-based check and is KILLED by this one.
    """
    formatter = logging.Formatter("%(message)s")
    return "\n".join(formatter.format(r) for r in caplog.records)


# ── the wire ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_peer_never_receives_the_exception_message() -> None:
    """The whole reply payload is searched, not just the error field.

    A leak could also ride in ``result`` or ``metadata``, and a test that reads
    one key cannot see that.
    """
    sender, receiver, nats = await _connected_pair()

    async def _handler(intent: IntentMessage):
        raise RuntimeError(CANARY)

    await IntentBus._nats_subscribe_agent(receiver, "agent-1", _handler)

    seen: dict[str, Any] = {}
    original = IntentBus._deserialize_result

    def _capture(data: dict[str, Any]):
        seen["payload"] = data
        return original(data)

    IntentBus._deserialize_result = staticmethod(_capture)
    try:
        result = await sender.send(
            IntentMessage(
                intent="direct_message",
                params={"text": "hello"},
                target_agent_id="agent-1",
            )
        )
    finally:
        IntentBus._deserialize_result = staticmethod(original)

    assert "payload" in seen, "the wire route did not run -- test proves nothing"
    on_the_wire = json.dumps(seen["payload"])
    assert CANARY not in on_the_wire, on_the_wire
    assert "RuntimeError" not in on_the_wire, on_the_wire

    assert result is not None
    assert result.success is False
    assert result.error == GENERIC
    # routers/agents.py:3373 is the only one of the fourteen ``send`` seams that
    # reads ``.error``: ``elif result and result.error`` then renders it. A
    # falsy replacement would silently reroute it to the "no reply" branch.
    assert bool(result.error) is True


@pytest.mark.asyncio
async def test_the_reply_is_still_a_failure_the_caller_can_act_on() -> None:
    """Withholding the message must not turn into withholding the answer.

    The failure has to survive the round trip, or this fix would have swapped
    an information leak for a silent timeout.
    """
    sender, receiver, _ = await _connected_pair()

    async def _handler(intent: IntentMessage):
        raise RuntimeError(CANARY)

    await IntentBus._nats_subscribe_agent(receiver, "agent-1", _handler)

    result = await sender.send(
        IntentMessage(
            intent="direct_message",
            params={"text": "hello"},
            target_agent_id="agent-1",
        )
    )
    assert result is not None, "the caller was left with silence"
    assert result.success is False
    assert result.result is None
    assert result.confidence == 0.0
    assert result.agent_id == "agent-1"


# ── the log ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_log_names_the_type_and_not_the_message(caplog) -> None:
    """Type only -- the same contract federation/bridge.py holds.

    Checks the formatted record AND ``exc_info``: ``exc_info=True`` would put
    the message back through the traceback while the format string stayed
    clean.
    """
    sender, receiver, _ = await _connected_pair()

    async def _handler(intent: IntentMessage):
        raise RuntimeError(CANARY)

    await IntentBus._nats_subscribe_agent(receiver, "agent-1", _handler)

    with caplog.at_level(logging.DEBUG, logger="probos.mesh.intent"):
        await sender.send(
            IntentMessage(
                intent="direct_message",
                params={"text": "hello"},
                target_agent_id="agent-1",
            )
        )

    rendered = _rendered(caplog)
    assert rendered.strip(), "nothing was logged -- test proves nothing"
    assert CANARY not in rendered, rendered
    assert "RuntimeError" in rendered, rendered


# ── the budget-starved fallback ───────────────────────────────────────


class _RawMsg:
    """Enforces the server's byte ceiling, as BF-805's double does.

    ``Msg.respond`` echoes the REQUEST's headers and the server charges them
    against the reply, so a large header block starves the error envelope and
    drives ``_smallest_error_bytes`` -- the third place the message was copied.
    """

    def __init__(self, max_payload: int, header_bytes: int) -> None:
        self.payloads: list[bytes] = []
        self.headers: dict[str, str] | None = None
        self._max_payload = max_payload
        self._header_bytes = header_bytes

    async def respond(self, payload: bytes) -> None:
        if len(payload) + self._header_bytes > self._max_payload:
            raise RuntimeError("nats: maximum payload exceeded")
        self.payloads.append(payload)


class _RecordingNats:
    """Captures the callback ``_nats_subscribe_agent`` registers.

    ``max_payload`` is not optional decoration: ``_reply_budget`` falls back to
    the whole default limit for a bus that cannot report one, so a double
    without it silently un-starves the budget and the fallback path never runs.
    """

    def __init__(self, max_payload: int = 1024 * 1024) -> None:
        self.callbacks: list[Any] = []
        self.max_payload = max_payload

    async def subscribe(self, subject: str, cb: Any) -> object:
        self.callbacks.append(cb)
        return object()


@pytest.mark.asyncio
async def test_the_budget_starved_error_reply_also_omits_the_message() -> None:
    """``_smallest_error_bytes`` carried ``str(e)`` too.

    Fixing only the ``IntentResult`` would leave this path leaking on exactly
    the requests a hostile peer controls the size of.

    The 120-byte budget is chosen, not arbitrary. Measured: the full envelope
    is 232 bytes so it still raises, the leaking candidate is 109 and the
    generic one 90, so BOTH fit. A looser budget (60) also passes against
    UNFIXED code -- the message is too long for the first candidate, the
    envelope falls back to the one with no ``error`` field at all, and no
    canary appears for a reason that has nothing to do with the fix. That
    probe proves nothing, which is why the assertion below pins its own
    premise: an ``error`` key must be present.
    """
    headers = {f"X-Pad-{i:02d}": "p" * 40 for i in range(6)}
    overhead = encoded_header_size(headers)
    nats = _RecordingNats(max_payload=overhead + 120)
    bus = _bus(nats)

    async def _handler(intent: IntentMessage):
        raise RuntimeError(CANARY)

    await IntentBus._nats_subscribe_agent(bus, "agent-1", _handler)
    on_intent = nats.callbacks[0]

    raw = _RawMsg(max_payload=overhead + 120, header_bytes=overhead)
    raw.headers = headers

    intent = IntentMessage(intent="direct_message", params={"text": "hello"})
    await on_intent(
        NATSMessage(
            subject="intent.agent-1",
            data=json.loads(json.dumps(IntentBus._serialize_intent(intent))),
            reply="_INBOX.1",
            headers=headers,
            _msg=raw,
        )
    )

    assert raw.payloads, "no reply was sent -- the fallback path did not run"
    body = raw.payloads[-1].decode()
    decoded = json.loads(body)
    assert len(body) < 232, "the full envelope fitted -- the fallback never ran"
    assert "error" in decoded, (
        "the envelope dropped the error field, so this budget cannot tell a "
        "leaked message from a generic code"
    )
    assert CANARY not in body, body
    assert decoded["error"] == GENERIC
    assert decoded["success"] is False


@pytest.mark.asyncio
async def test_a_reply_that_cannot_be_sent_is_reported_without_a_traceback(
    caplog,
) -> None:
    """BF-805's ``exc_info=True`` chained the handler's message back in.

    Found by the budget-starved test above: the format string had already been
    cleaned, and ``RuntimeError: CANARY...`` still reached the log through
    "During handling of the above exception". A clean format string is not the
    same property as a clean record.
    """
    nats = _RecordingNats()
    bus = _bus(nats)

    async def _handler(intent: IntentMessage):
        raise RuntimeError(CANARY)

    await IntentBus._nats_subscribe_agent(bus, "agent-1", _handler)
    on_intent = nats.callbacks[0]

    # Sends fine locally, refused at the wire -- the shape BF-805 measured.
    raw = _RawMsg(max_payload=0, header_bytes=0)

    intent = IntentMessage(intent="direct_message", params={"text": "hello"})
    with caplog.at_level(logging.DEBUG, logger="probos.mesh.intent"):
        await on_intent(
            NATSMessage(
                subject="intent.agent-1",
                data=json.loads(json.dumps(IntentBus._serialize_intent(intent))),
                reply="_INBOX.1",
                _msg=raw,
            )
        )

    assert any(
        "could not be sent" in r.getMessage() for r in caplog.records
    ), "the un-sendable-reply branch never ran -- test proves nothing"
    rendered = _rendered(caplog)
    assert CANARY not in rendered, rendered


# ── the JetStream inbound handler ─────────────────────────────────────


@pytest.mark.asyncio
async def test_the_jetstream_dispatch_log_omits_the_message(caplog) -> None:
    """The other inbound handler leaked into the log only.

    ``_on_dispatch`` sends no reply -- it ``term()``s -- so nothing crossed to a
    peer there. The log copy is the same class of disclosure and is fixed with
    it. Asserting the ``term`` proves the callback really reached its except
    branch rather than failing earlier.
    """
    nats = MockNATSBus()
    nats._connected = True
    bus = _bus(nats)

    async def _handler(intent: IntentMessage):
        raise RuntimeError(CANARY)

    await bus._js_subscribe_agent_dispatch("agent-2", _handler)

    intent = IntentMessage(
        intent="direct_message", params={"text": "hello"}, target_agent_id="agent-2"
    )
    with caplog.at_level(logging.DEBUG, logger="probos.mesh.intent"):
        await nats.js_publish(
            "intent.dispatch.agent-2", IntentBus._serialize_intent(intent)
        )

    assert nats.terms, "the dispatch callback never reached its failure branch"
    rendered = _rendered(caplog)
    assert CANARY not in rendered, rendered
    assert "RuntimeError" in rendered, rendered


# ── cancellation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancellation_propagates_out_of_the_request_reply_callback() -> None:
    """Shutdown must not be answered as a handler failure.

    ``CancelledError`` derives from ``BaseException``, so ``except Exception``
    already let it through; the explicit re-raise makes that an assertion
    rather than an accident of the class hierarchy, and this pins it.
    """
    nats = _RecordingNats()
    bus = _bus(nats)

    async def _handler(intent: IntentMessage):
        raise asyncio.CancelledError()

    await IntentBus._nats_subscribe_agent(bus, "agent-1", _handler)
    on_intent = nats.callbacks[0]

    raw = _RawMsg(max_payload=1024 * 1024, header_bytes=0)
    intent = IntentMessage(intent="direct_message", params={"text": "hello"})
    msg = NATSMessage(
        subject="intent.agent-1",
        data=json.loads(json.dumps(IntentBus._serialize_intent(intent))),
        reply="_INBOX.1",
        _msg=raw,
    )

    with pytest.raises(asyncio.CancelledError):
        await on_intent(msg)
    assert raw.payloads == [], "a cancelled request was answered as a failure"


@pytest.mark.asyncio
async def test_cancellation_propagates_out_of_the_dispatch_callback() -> None:
    """And is not swallowed into a ``term()`` either."""
    nats = MockNATSBus()
    nats._connected = True
    bus = _bus(nats)

    async def _handler(intent: IntentMessage):
        raise asyncio.CancelledError()

    await bus._js_subscribe_agent_dispatch("agent-2", _handler)

    intent = IntentMessage(
        intent="direct_message", params={"text": "hello"}, target_agent_id="agent-2"
    )
    with pytest.raises(asyncio.CancelledError):
        await nats.js_publish(
            "intent.dispatch.agent-2", IntentBus._serialize_intent(intent)
        )
    assert nats.terms == [], "a cancelled dispatch was terminated as a failure"
