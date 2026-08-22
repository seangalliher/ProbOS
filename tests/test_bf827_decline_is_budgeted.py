"""BF-827 (#1291): the 'agent declined' reply was the one un-budgeted path.

BF-805 (#1269) made both `IntentResult` reply sites measure their bytes against
what the wire will actually take. The decline reply did not: it sent
`msg.respond({"declined": True})` with no budget at all.

The body is 18 bytes, so it cannot overflow on its own. It can be refused when
the ECHOED REQUEST HEADERS nearly fill `max_payload` — `Msg.respond`
republishes the request's headers and the server counts body + headers, which
is the byte class BF-805 measured against a live server (body 1,048,568 +
headers 279 refused at a 1,048,576 limit).

The failure mode is the bad one: nats-py's own guard checks the body alone, so
the send succeeds locally, the server then resets the responder connection
asynchronously, and the requester times out holding nothing — no local
exception, no error reply.

Reaching it needs a peer that sends a tiny body under a very large header
block. Every ProbOS caller sends a full serialized intent, so this is a
non-standard or hostile peer — which is what a budget is for.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import NATSMessage, encoded_header_size
from probos.types import IntentMessage

DECLINE = json.dumps({"declined": True}).encode()


class _RawMsg:
    """Enforces the server's ceiling: body + echoed headers, as the server does.

    ``attempted`` records EVERY call, before the limit check. Without it,
    "never submitted" and "submitted and refused" are indistinguishable --
    review showed a mutant that submits an oversized payload anyway, lets the
    fake reject it, and swallows the raise still passed a test asserting
    ``payloads == []``.
    """

    def __init__(self, max_payload: int, headers: dict | None = None) -> None:
        self.payloads: list[bytes] = []
        self.attempted: list[bytes] = []
        self.headers = headers
        self._max_payload = max_payload
        self._header_bytes = encoded_header_size(headers)

    async def respond(self, payload: bytes) -> None:
        self.attempted.append(payload)
        if len(payload) + self._header_bytes > self._max_payload:
            raise RuntimeError("nats: maximum payload exceeded")
        self.payloads.append(payload)


class _FakeNats:
    def __init__(self, max_payload: int) -> None:
        self.callbacks: list = []
        self.max_payload = max_payload

    async def subscribe(self, subject, cb):
        self.callbacks.append(cb)
        return object()


async def _decline(*, max_payload: int, headers: dict | None = None):
    """Run the real adapter with a handler that DECLINES."""
    nats = _FakeNats(max_payload=max_payload)
    bus = IntentBus.__new__(IntentBus)
    bus._nats_bus = nats

    async def _handler(intent: IntentMessage):
        return None  # declined

    await IntentBus._nats_subscribe_agent(bus, "agent-ezri", _handler)
    on_intent = nats.callbacks[0]

    raw = _RawMsg(max_payload, headers)
    intent = IntentMessage(intent="direct_message", params={"text": "hello"})
    msg = NATSMessage(
        subject="intent.agent-ezri",
        data=json.loads(json.dumps(IntentBus._serialize_intent(intent))),
        reply="_INBOX.1",
        _msg=raw,
    )
    await on_intent(msg)
    return raw


# ── the ordinary case must be byte-identical ──────────────────────


@pytest.mark.asyncio
async def test_a_decline_still_reaches_the_caller_unchanged() -> None:
    raw = await _decline(max_payload=1024 * 1024)
    assert raw.payloads == [DECLINE]
    assert json.loads(raw.payloads[0].decode()) == {"declined": True}


@pytest.mark.asyncio
async def test_headers_that_leave_room_do_not_change_anything() -> None:
    headers = {"Nats-Msg-Id": "abc", "X-Trace": "sha256:deadbeef"}
    raw = await _decline(max_payload=1024 * 1024, headers=headers)
    assert raw.payloads == [DECLINE]


# ── the gap BF-805 left ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_decline_that_cannot_fit_is_not_submitted(caplog) -> None:
    """Submitting it would pass nats-py's body-only guard and be refused by
    the SERVER asynchronously — the caller times out with no local error.

    Refusing locally does not get the decline delivered; below 17 bytes
    nothing can. It stops the connection being reset, and it puts the loss in
    the log where an operator can see it, instead of nowhere.

    Asserts on ``attempted``, not ``payloads``: the fake raises on an
    oversized call, so ``payloads`` stays empty either way and cannot tell a
    refusal from a rejected submission.
    """
    import logging

    headers = {f"X-Pad-{i:02d}": "p" * 200 for i in range(6)}
    overhead = encoded_header_size(headers)

    with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
        raw = await _decline(max_payload=overhead + 16, headers=headers)

    assert raw.attempted == [], "an unsendable decline was submitted anyway"
    assert raw.payloads == []
    assert any("BF-827" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


@pytest.mark.asyncio
async def test_seventeen_bytes_is_enough_because_json_whitespace_is_optional(
) -> None:
    """The blocker review found against a live server.

    The ordinary encoding is 18 bytes, but `{"declined":true}` is 17 and
    decodes to exactly the same object. The first version of this fix logged
    and gave up at a 17-byte budget — refusing where delivery was possible,
    which is a capability ceiling nobody chose rather than a safety property.
    """
    headers = {f"X-Pad-{i:02d}": "p" * 200 for i in range(6)}
    overhead = encoded_header_size(headers)

    raw = await _decline(max_payload=overhead + 17, headers=headers)

    assert raw.payloads == [b'{"declined":true}']
    assert json.loads(raw.payloads[0].decode()) == {"declined": True}


@pytest.mark.asyncio
async def test_eighteen_bytes_still_gets_the_historical_encoding() -> None:
    """The compact form is a FALLBACK. With room for the ordinary one, every
    peer must receive exactly what it always has."""
    headers = {f"X-Pad-{i:02d}": "p" * 200 for i in range(6)}
    overhead = encoded_header_size(headers)

    raw = await _decline(max_payload=overhead + 18, headers=headers)
    assert raw.payloads == [DECLINE]
    assert raw.payloads[0] == b'{"declined": true}'


def test_the_decline_ladder_is_smallest_last_and_both_decode() -> None:
    for limit, expected in ((18, b'{"declined": true}'), (17, b'{"declined":true}')):
        got = IntentBus._decline_bytes(limit)
        assert got == expected, (limit, got)
        assert json.loads(got.decode()) == {"declined": True}
    assert IntentBus._decline_bytes(16) is None
    assert IntentBus._decline_bytes(0) is None
    assert IntentBus._decline_bytes(1024) == b'{"declined": true}'


@pytest.mark.asyncio
async def test_the_logged_budget_is_the_one_the_decision_was_made_on(caplog) -> None:
    """The budget is read ONCE, so the warning cannot name a size nobody decided on.

    Review measured this against a stateful transport: two reads returned 16
    and 17, so the code declined on 16 and then reported "17 bytes" -- a log
    confabulating its own reason, and the hardest kind to debug because it
    describes a state the code never saw.

    Production's `max_payload` is a synchronous attribute read with no await
    between the two, so it cannot drift there today. That is exactly why this
    needs pinning rather than trusting: nothing else stops a future reader
    from reintroducing the second call.
    """
    import logging

    bus = IntentBus.__new__(IntentBus)
    bus._nats_bus = _FakeNats(max_payload=1024)
    reads: list[int] = []

    def _drifting_budget(_msg):
        reads.append(16 + len(reads))  # 16, then 17, then 18 ...
        return reads[-1]

    bus._reply_budget = _drifting_budget

    async def _handler(intent: IntentMessage):
        return None

    await IntentBus._nats_subscribe_agent(bus, "agent-ezri", _handler)
    raw = _RawMsg(1024)
    msg = NATSMessage(
        subject="intent.agent-ezri",
        data=json.loads(json.dumps(IntentBus._serialize_intent(
            IntentMessage(intent="direct_message", params={}),
        ))),
        reply="_INBOX.1",
        _msg=raw,
    )
    with caplog.at_level(logging.WARNING):
        await bus._nats_bus.callbacks[0](msg)

    assert raw.attempted == [], "16 bytes cannot carry any decline"
    assert len(reads) == 1, f"budget read {len(reads)} times, must be once"
    assert "16 bytes" in caplog.text, caplog.text
    assert "17 bytes" not in caplog.text, caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("wire", [b'{"declined": true}', b'{"declined":true}'])
async def test_both_rungs_are_read_as_a_decline_by_the_real_consumer(wire: bytes) -> None:
    """Cross the seam: the bytes this emits must reach the code that acts on them.

    Every other test here stops at the encoder and decodes with ``json.loads``.
    That proves the producer, not the chain -- and this repo's most common
    defect is every link correct with the chain dead. The compact rung is new;
    nothing had ever carried it through ``NATSBus.request``'s decoder into the
    ``data.get("declined")`` check that turns it into ``None``.

    ``None`` is the contract: it means "this agent declined, ask another".
    Falling through to ``_deserialize_result`` would instead manufacture a
    result out of a decline.
    """
    from probos.mesh.nats_bus import NATSBus

    class _Response:
        subject, reply, headers = "intent.a", "", None
        data = wire

    class _Nc:
        is_connected = True

        async def request(self, subject, payload, timeout=None):
            return _Response()

    bus = NATSBus.__new__(NATSBus)
    bus._nc = _Nc()
    bus._connected = True
    bus._subject_prefix = "probos"

    ib = IntentBus.__new__(IntentBus)
    ib._nats_bus = bus
    ib._serialize_intent = lambda i: {"id": i.id}

    intent = IntentMessage(intent="ping", params={}, target_agent_id="a")
    intent.ttl_seconds = 5.0

    # POSITIVE PREMISE. `_nats_send` also returns None when the request raises
    # or the reply is None, so `is None` alone is satisfied by a fake that
    # never worked. Prove this rig can carry a real result first -- otherwise
    # the assertion below is vacuous and would survive any mutation.
    _Response.data = b'{"success": true, "output": "pong", "confidence": 1.0}'
    carried = await ib._nats_send(intent)
    assert carried is not None and carried.success, carried

    _Response.data = wire
    assert await ib._nats_send(intent) is None


@pytest.mark.asyncio
async def test_the_decline_is_measured_against_the_same_budget_as_a_reply(
) -> None:
    """One budget, not two. If the decline used the global limit while the
    replies used the header-adjusted one, the gap would simply move."""
    headers = {f"X-Pad-{i:02d}": "p" * 200 for i in range(6)}
    overhead = encoded_header_size(headers)
    raw = _RawMsg(overhead + 100, headers)
    msg = NATSMessage(
        subject="s", data={}, reply="_INBOX.1", headers=headers, _msg=raw
    )

    bus = IntentBus.__new__(IntentBus)
    bus._nats_bus = _FakeNats(overhead + 100)

    assert bus._reply_budget(msg) == 100


# ── the shape that must not regress ───────────────────────────────


@pytest.mark.asyncio
async def test_a_normal_result_still_replies_normally() -> None:
    """The decline branch is one arm of an if/else; the other must be intact."""
    from probos.types import IntentResult

    nats = _FakeNats(1024 * 1024)
    bus = IntentBus.__new__(IntentBus)
    bus._nats_bus = nats

    async def _handler(intent: IntentMessage):
        return IntentResult(
            intent_id=intent.id,
            agent_id="agent-ezri",
            success=True,
            result="fifteen",
            confidence=0.9,
            timestamp=datetime.now(timezone.utc),
            metadata={},
        )

    await IntentBus._nats_subscribe_agent(bus, "agent-ezri", _handler)
    raw = _RawMsg(1024 * 1024)
    intent = IntentMessage(intent="direct_message", params={})
    await nats.callbacks[0](
        NATSMessage(
            subject="s",
            data=json.loads(json.dumps(IntentBus._serialize_intent(intent))),
            reply="_INBOX.1",
            _msg=raw,
        )
    )

    assert raw.payloads
    assert json.loads(raw.payloads[0].decode())["result"] == "fifteen"


@pytest.mark.asyncio
async def test_a_decline_with_no_reply_subject_sends_nothing() -> None:
    """A fire-and-forget dispatch has nothing to decline to."""
    nats = _FakeNats(1024 * 1024)
    bus = IntentBus.__new__(IntentBus)
    bus._nats_bus = nats

    async def _handler(intent: IntentMessage):
        return None

    await IntentBus._nats_subscribe_agent(bus, "agent-ezri", _handler)
    raw = _RawMsg(1024 * 1024)
    intent = IntentMessage(intent="direct_message", params={})
    await nats.callbacks[0](
        NATSMessage(
            subject="s",
            data=json.loads(json.dumps(IntentBus._serialize_intent(intent))),
            reply="",
            _msg=raw,
        )
    )
    assert raw.payloads == []
