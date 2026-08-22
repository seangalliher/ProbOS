"""BF-805 (#1269): metadata must never take the answer down with it.

``IntentBus._serialize_result`` carries ``metadata`` on every NATS reply
(BF-742, so AD-1203's ``tool_trace_ref`` stops being dropped).
``NATSMessage.respond`` then calls plain ``json.dumps`` on the whole payload,
so ONE unserializable value anywhere in ``metadata`` raised, was caught by
``_nats_subscribe_agent``'s handler-error branch, and replaced the agent's
successful answer with a synthetic failure.

Measured through the real adapter before the fix::

    success=False, result=None,
    error="Object of type object is not JSON serializable"

The Captain lost the answer and was handed a serialization fault about their
request instead.

These tests drive the REAL ``_on_nats_intent`` callback registered by
``_nats_subscribe_agent`` and the REAL ``NATSMessage.respond``, then read the
bytes the caller would actually receive — asserting on ``_reply_payload``'s
return value alone would not prove the payload survives ``json.dumps``, which
is the entire question.
"""

from __future__ import annotations

import asyncio
import json
import logging
import textwrap
from datetime import datetime, timezone
from typing import Any

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    NATSMessage,
    encoded_header_size,
)
from probos.types import IntentMessage, IntentResult


class _RawMsg:
    """Stands in for ``nats.aio.msg.Msg``.

    Enforces the server's byte ceiling, because the real one does: a reply past
    ``max_payload`` is refused with ``nats: maximum payload exceeded``. A double
    that accepts any bytes cannot see that class of failure at all, which is how
    a size-blind probe passed a whole suite while failing against a live server.

    ``header_bytes`` models the second half of the same defect: ``Msg.respond``
    republishes the request's headers and the SERVER counts them alongside the
    body, even though nats-py's own guard checks the body alone.
    """

    def __init__(
        self, max_payload: int = 1024 * 1024, header_bytes: int = 0
    ) -> None:
        self.payloads: list[bytes] = []
        # ``nats.aio.msg.Msg`` defaults this to None, and the difference is a
        # whole 12-byte header block: None takes nats-py's PUB branch, an empty
        # dict still takes HPUB.
        self.headers: dict[str, str] | None = None
        self._max_payload = max_payload
        self._header_bytes = header_bytes

    async def respond(self, payload: bytes) -> None:
        if len(payload) + self._header_bytes > self._max_payload:
            raise RuntimeError("nats: maximum payload exceeded")
        self.payloads.append(payload)


class _FakeNats:
    def __init__(self, max_payload: int = 1024 * 1024) -> None:
        self.callbacks: list = []
        self.max_payload = max_payload

    async def subscribe(self, subject, cb):
        self.callbacks.append(cb)
        return object()


async def _reply_bytes(
    *,
    metadata=None,
    result_value=("the fifteen packages",),
    raises: BaseException | None = None,
    max_payload: int = 1024 * 1024,
    headers: dict[str, str] | None = None,
) -> dict | None:
    """Run the real NATS adapter and return the decoded reply, or None."""
    nats = _FakeNats(max_payload=max_payload)
    bus = IntentBus.__new__(IntentBus)
    bus._nats_bus = nats

    async def _handler(intent: IntentMessage):
        if raises is not None:
            raise raises
        return IntentResult(
            intent_id=intent.id,
            agent_id="agent-ezri",
            success=True,
            result=result_value,
            confidence=0.9,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata if metadata is not None else {},
        )

    await IntentBus._nats_subscribe_agent(bus, "agent-ezri", _handler)
    on_intent = nats.callbacks[0]

    raw = _RawMsg(max_payload=max_payload)
    if headers is not None:
        raw.headers = headers
        raw._header_bytes = encoded_header_size(headers)
    intent = IntentMessage(intent="direct_message", params={"text": "hello"})
    msg = NATSMessage(
        subject="intent.agent-ezri",
        data=json.loads(json.dumps(IntentBus._serialize_intent(intent))),
        reply="_INBOX.1",
        _msg=raw,
    )
    await on_intent(msg)
    if not raw.payloads:
        return None
    return json.loads(raw.payloads[-1].decode())


def _bus(max_payload: int = 1024 * 1024) -> IntentBus:
    bus = IntentBus.__new__(IntentBus)
    bus._nats_bus = _FakeNats(max_payload=max_payload)
    return bus


def _deep(depth: int):
    """A value nested ``depth`` levels deep."""
    value: Any = "leaf"
    for _ in range(depth):
        value = [value]
    return value


def _encodes(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError, RecursionError):
        return False
    return True


def _envelope_seam_depth() -> int:
    """The depth where a value encodes alone but not under ``metadata``.

    Measured at the CALLER's stack depth, never cached at import: the recursion
    limit is relative to how deep the stack already is, so a constant computed
    at module load is wrong by several levels inside a test frame.
    """
    for depth in range(3200, 2000, -1):
        if _encodes({"deep": _deep(depth)}) and not _encodes(
            {"metadata": {"deep": _deep(depth)}}
        ):
            return depth
    raise AssertionError("no depth separates the two envelope shapes")


# ── the defect ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unserializable_metadata_no_longer_destroys_the_answer() -> None:
    reply = await _reply_bytes(
        metadata={"dm_reply": {"bad": object()}},
        result_value="the fifteen packages",
    )
    assert reply is not None
    assert reply["success"] is True
    assert reply["result"] == "the fifteen packages"
    assert reply["error"] is None


@pytest.mark.asyncio
async def test_only_the_offending_key_is_dropped() -> None:
    """A bad ``dm_reply`` must not also cost the caller its trace ref.

    Dropping ``metadata`` wholesale would be simpler and would silently undo
    BF-742, which exists precisely because AD-1203's ref was being lost.
    """
    reply = await _reply_bytes(
        metadata={
            "tool_trace_ref": "sha256:abc123",
            "dm_reply": {"bad": object()},
            "turn": 4,
        },
    )
    assert reply is not None
    assert reply["metadata"] == {"tool_trace_ref": "sha256:abc123", "turn": 4}


@pytest.mark.asyncio
async def test_the_drop_is_recorded_in_the_log_by_name(caplog) -> None:
    """The receiver cannot tell, so the log is the only record there is."""
    with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
        await _reply_bytes(metadata={"dm_reply": {"bad": object()}})
    messages = [r.getMessage() for r in caplog.records]
    assert any("BF-805" in m and "dm_reply" in m for m in messages), messages


# ── what must not change ──────────────────────────────────────────


def test_the_separator_between_kept_keys_is_charged_exactly() -> None:
    """``json.dumps`` joins members with ``", "`` — two bytes, not one.

    A one-byte charge under-counts every key after the first, so at a limit
    one byte under the full envelope the pass keeps BOTH keys, the assembled
    check then rejects them, and the container is lost whole — taking the
    earlier key that would have fitted, and logging only ``<metadata>``.
    """
    metadata = {"tool_trace_ref": "sha256:abc123", "dm_reply": "y" * 40}
    result = IntentResult(
        intent_id="i-1",
        agent_id="agent-ezri",
        success=True,
        result="ok",
        confidence=0.9,
        timestamp=datetime.now(timezone.utc),
        metadata=metadata,
    )
    full = len(json.dumps(IntentBus._serialize_result(result)).encode())

    # One byte short of everything fitting: the FIRST key must survive.
    decoded = json.loads(_bus()._reply_bytes(result, full - 1).decode())
    assert decoded["result"] == "ok"
    assert decoded["metadata"] == {"tool_trace_ref": "sha256:abc123"}

    # And with room for everything, nothing is dropped.
    assert json.loads(_bus()._reply_bytes(result, full).decode())[
        "metadata"
    ] == metadata


@pytest.mark.asyncio
async def test_an_answer_too_big_for_the_wire_is_refused_not_submitted() -> None:
    """nats-py checks the BODY; the server counts body + headers.

    Measured live: a body one byte over the header-adjusted budget passed
    nats-py's own guard, was queued as an HPUB, and the server then reset the
    responder connection asynchronously — the send never failed locally and the
    caller timed out holding nothing. Refusing here reaches the handler-error
    branch, which sends a short reply the wire will actually take.
    """
    with pytest.raises(ValueError, match="body budget"):
        _bus()._reply_bytes(
            IntentResult(
                intent_id="i-1",
                agent_id="agent-ezri",
                success=True,
                result="y" * 500,
                confidence=0.9,
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            200,
        )

    # And the caller gets the error reply rather than silence.
    reply = await _reply_bytes(result_value="y" * 4096, max_payload=1024)
    assert reply is not None
    assert reply["success"] is False
    assert "body budget" in (reply["error"] or "")


@pytest.mark.asyncio
async def test_when_even_the_error_will_not_fit_the_caller_still_hears_back(
    caplog,
) -> None:
    """The error path must not fail the same way the reply it reports on did.

    Measured live: a legal request whose echoed headers left a 111-byte budget
    could carry neither the 170-byte answer nor the 290-byte error about it.
    Both raised, the second escaped the callback, NATS logged it, and the
    requester timed out holding nothing — this BF's own failure, reached
    through its own error path.
    """
    headers = {f"X-Pad-{i:02d}": "p" * 40 for i in range(6)}
    overhead = encoded_header_size(headers)
    with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
        reply = await _reply_bytes(
            result_value="y" * 4096,
            max_payload=overhead + 60,
            headers=headers,
        )
    assert reply is not None, "the caller was left with silence"
    assert reply["success"] is False


def test_the_smallest_error_envelope_drops_one_thing_at_a_time() -> None:
    """Each candidate gives up one more field the far end can default.

    ``_deserialize_result`` reads every field through a defaulted ``.get()``,
    so ``{"success": false}`` is a complete IntentResult carrying the one fact
    that matters — and ``None`` only when eighteen bytes will not go.
    """
    full = IntentBus._smallest_error_bytes("i-1", "boom", 1024)
    assert json.loads(full.decode()) == {
        "intent_id": "i-1", "success": False, "error": "boom",
    }

    # No room for the message, but room for the id.
    assert json.loads(
        IntentBus._smallest_error_bytes("i-1", "b" * 200, 40).decode()
    ) == {"intent_id": "i-1", "success": False}

    # No room for the id either.
    assert json.loads(
        IntentBus._smallest_error_bytes("i" * 300, "boom", 25).decode()
    ) == {"success": False}

    # And an honest None rather than something the wire will refuse.
    assert IntentBus._smallest_error_bytes("i-1", "boom", 17) is None
    assert len(IntentBus._smallest_error_bytes("i-1", "boom", 18)) == 18

    # The last resort really does deserialize into a failed result.
    smallest = IntentBus._deserialize_result(
        json.loads(IntentBus._smallest_error_bytes("i-1", "boom", 18).decode())
    )
    assert smallest.success is False


def test_absent_headers_and_empty_headers_are_not_the_same_block() -> None:
    """``None`` takes nats-py's PUB branch; ``{}`` still frames a 12-byte HPUB.

    Conflating them under-charges an empty-dict reply by the whole header
    block, which is exactly the byte class BF-805 exists to account for.
    """
    assert encoded_header_size(None) == 0
    from nats.aio.client import NATS_HDR_LINE, _CRLF_

    assert encoded_header_size({}) == len(NATS_HDR_LINE) + 2 * len(_CRLF_) == 12
    # A dict of only-empty keys still costs the block: the library skips the
    # keys but has already committed to HPUB.
    assert encoded_header_size({"  ": "x"}) == 12


@pytest.mark.asyncio
async def test_the_bytes_checked_are_the_bytes_sent() -> None:
    """Encoding twice lets the check and the send see different artifacts.

    Measured: a mapping whose ``items()`` succeeds once and raises on the
    second call passed the check and then destroyed the answer at the
    transport — the original defect, reproduced by the fix for it.
    """

    class _OnceOnly(dict):
        def __init__(self, *a, **kw) -> None:
            super().__init__(*a, **kw)
            self.calls = 0

        def items(self):  # noqa: ANN201
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("metadata failed on consumer encode")
            return super().items()

    reply = await _reply_bytes(
        metadata=_OnceOnly({"tool_trace_ref": "sha256:abc"}),
        result_value="the answer",
    )
    assert reply is not None
    assert reply["success"] is True
    assert reply["result"] == "the answer"


def test_pruning_stays_linear_in_the_number_of_keys() -> None:
    """Re-encoding the growing envelope per key was quadratic.

    Measured at 0.85s for 5,001 keys, synchronously inside the NATS callback,
    delaying every task on that event loop. Counts *bytes* encoded, not calls:
    the quadratic shape makes the same number of ``dumps`` calls, each one
    larger than the last, so a call count cannot tell the two apart.
    """
    keys = 400
    metadata: dict = {f"k{i:04d}": "x" * 64 for i in range(keys)}
    metadata["bad"] = object()
    result = IntentResult(
        intent_id="i-1",
        agent_id="agent-ezri",
        success=True,
        result="ok",
        confidence=0.9,
        timestamp=datetime.now(timezone.utc),
        metadata=metadata,
    )

    encoded_bytes = 0
    real = json.dumps

    def _counting(*args, **kwargs):
        nonlocal encoded_bytes
        out = real(*args, **kwargs)
        encoded_bytes += len(out)
        return out

    json.dumps = _counting  # type: ignore[assignment]
    try:
        encoded = _bus()._reply_bytes(result)
    finally:
        json.dumps = real  # type: ignore[assignment]

    decoded = json.loads(encoded.decode())
    assert decoded["result"] == "ok"
    assert "bad" not in decoded["metadata"]
    assert len(decoded["metadata"]) == keys

    # Each key is encoded once on its own, plus a bounded number of whole
    # envelopes. Quadratic pruning encodes a growing prefix per key, which is
    # ~200x this budget at 400 keys.
    budget = 8 * len(encoded)
    assert encoded_bytes <= budget, f"{encoded_bytes} bytes encoded, budget {budget}"


@pytest.mark.asyncio
async def test_a_clean_reply_is_byte_identical_to_before() -> None:
    """The degrade path must not touch a reply that never needed it."""
    metadata = {"tool_trace_ref": "sha256:abc123", "turn": 4}
    result = IntentResult(
        intent_id="i-1",
        agent_id="agent-ezri",
        success=True,
        result={"answer": "fifteen"},
        confidence=0.9,
        timestamp=datetime.now(timezone.utc),
        metadata=metadata,
    )
    assert _bus()._reply_bytes(result) == json.dumps(
        IntentBus._serialize_result(result)
    ).encode()

    reply = await _reply_bytes(metadata=metadata, result_value={"answer": "fifteen"})
    assert reply is not None
    assert reply["metadata"] == metadata
    assert reply["result"] == {"answer": "fifteen"}


@pytest.mark.asyncio
async def test_an_unserializable_ANSWER_still_fails_the_reply() -> None:
    """Fail-fast is right where there is nothing left to deliver.

    Degrading here would hand the caller ``success=True`` with a hollowed-out
    result, which is worse than the honest error.
    """
    reply = await _reply_bytes(metadata={}, result_value={"blob": object()})
    assert reply is not None
    assert reply["success"] is False
    assert "not JSON serializable" in (reply["error"] or "")


@pytest.mark.asyncio
async def test_a_bad_answer_is_not_rescued_by_dropping_good_metadata() -> None:
    """The key-by-key pass must not mistake an unserializable answer for
    unserializable provenance, drop healthy metadata, and still fail."""
    reply = await _reply_bytes(
        metadata={"tool_trace_ref": "sha256:abc123"},
        result_value={"blob": object()},
    )
    assert reply is not None
    assert reply["success"] is False


@pytest.mark.asyncio
async def test_a_bad_answer_beside_bad_metadata_never_claims_delivery(
    caplog,
) -> None:
    """Both broken at once is the one case where the drop changes nothing.

    Dropping the bad key does not make the payload sendable, so the reply fails
    either way and the outcome is identical. What is NOT identical is the log:
    without the final check, BF-805 announces that "the answer itself is
    delivered intact" about a reply that was never sent. A false claim in an
    incident log is exactly what this BF is about, one level down.
    """
    with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
        reply = await _reply_bytes(
            metadata={"dm_reply": {"bad": object()}},
            result_value={"blob": object()},
        )
    assert reply is not None
    assert reply["success"] is False
    messages = [r.getMessage() for r in caplog.records]
    assert not any("BF-805" in m for m in messages), messages


@pytest.mark.asyncio
async def test_the_handler_error_reply_still_reaches_the_caller() -> None:
    reply = await _reply_bytes(raises=RuntimeError("handler exploded"))
    assert reply is not None
    assert reply["success"] is False
    assert reply["error"] == "handler exploded"


# ── the probe matches the consumer ────────────────────────────────


def test_the_serializability_probe_asks_exactly_what_respond_asks() -> None:
    """An "improved" probe answers a different question than the wire.

    ``NATSMessage.respond`` calls plain ``json.dumps(...).encode()``.
    ``float('nan')`` is accepted by that (as bare ``NaN``) and must therefore be
    accepted here, even though it is not valid JSON — the job is to predict the
    consumer, not to be more correct than it. This exercises ``_encoded``, the
    function ``_reply_bytes`` actually calls; a separate "is it safe" helper
    that no production path uses would prove nothing about the real reply.
    """
    assert IntentBus._encoded({"x": float("nan")}) == b'{"x": NaN}'
    assert IntentBus._encoded({"x": object()}) is None
    assert IntentBus._encoded({object(): 1}) is None
    # And depth: this raises RecursionError, not TypeError.
    assert IntentBus._encoded({"x": _deep(20_000)}) is None

# ── the transport's other two refusals ────────────────────────────


@pytest.mark.asyncio
async def test_metadata_past_the_payload_limit_does_not_cost_the_answer() -> None:
    """Measured against a live server: valid metadata, refused for size.

    ``nats: maximum payload exceeded`` replaced a good answer just as a
    ``TypeError`` did. A probe that only asks "does it encode?" cannot see it.
    """
    reply = await _reply_bytes(
        metadata={"tool_trace_ref": "sha256:abc", "bulk": "y" * 4000},
        result_value="the fifteen packages",
        max_payload=2048,
    )
    assert reply is not None
    assert reply["success"] is True
    assert reply["result"] == "the fifteen packages"
    assert reply["metadata"] == {"tool_trace_ref": "sha256:abc"}


@pytest.mark.asyncio
async def test_two_values_that_only_overflow_together_are_pruned() -> None:
    """Each fits alone; together they do not.

    Testing a key in isolation would keep both and the reply would still be
    refused. The keys have to be tried cumulatively, in the real envelope.
    """
    reply = await _reply_bytes(
        metadata={"a": "x" * 700, "b": "y" * 700},
        result_value="ok",
        max_payload=1200,
    )
    assert reply is not None
    assert reply["success"] is True
    assert reply["result"] == "ok"
    assert list(reply["metadata"]) == ["a"]


@pytest.mark.asyncio
async def test_deeply_nested_metadata_does_not_cost_the_answer() -> None:
    """Encodes alone at this depth, fails nested under the real envelope.

    The depth is chosen at the seam and the premise is asserted: a value that
    also fails standalone would be dropped by an isolated probe too, so such a
    fixture would leave this test green against the defect it names.
    """
    value = _deep(_envelope_seam_depth())
    assert _encodes({"deep": value}), "premise: the value encodes on its own"
    assert not _encodes({"metadata": {"deep": value}}), "premise: nested it does not"

    reply = await _reply_bytes(metadata={"deep": value}, result_value="the answer")
    assert reply is not None
    assert reply["success"] is True
    assert reply["result"] == "the answer"
    assert reply["metadata"] == {}


@pytest.mark.asyncio
async def test_a_json_safe_non_mapping_container_is_dropped_and_named(
    caplog,
) -> None:
    """A list encodes fine and then becomes ``{}`` at the far end.

    ``_deserialize_result`` keeps ``metadata`` only when it is a mapping, so a
    JSON-safe non-mapping crossed the wire and silently arrived as nothing,
    with no record that provenance had been lost.
    """
    with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
        reply = await _reply_bytes(
            metadata=["not", "a", "mapping"], result_value="the answer"
        )
    assert reply is not None
    assert reply["success"] is True
    assert reply["result"] == "the answer"
    assert reply["metadata"] == {}
    assert any("<metadata>" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_metadata_that_fights_back_still_delivers_the_answer() -> None:
    """Naming or iterating the keys can itself raise.

    ``str(key)`` and ``items()`` are called on caller-supplied data, outside
    ``json.dumps``, so a hostile mapping destroyed the answer through a route
    the serializability probe never sees.
    """

    class _BadKey:
        def __str__(self) -> str:
            raise RuntimeError("bad key string")

        def __hash__(self) -> int:
            return 0

    class _BadItems(dict):
        def items(self):  # noqa: ANN201 - matching dict's signature loosely
            raise RuntimeError("bad items")

    for metadata in ({_BadKey(): object()}, _BadItems({"a": object()})):
        reply = await _reply_bytes(metadata=metadata, result_value="the answer")
        assert reply is not None, metadata
        assert reply["success"] is True, metadata
        assert reply["result"] == "the answer", metadata
        assert reply["metadata"] == {}, metadata


# ── the headers ride along, and the server counts them ────────────


def test_the_header_size_mirrors_the_library_that_frames_them() -> None:
    """Not an estimate: the same loop and the same constants.

    ``Client._send_publish`` writes the header line, then ``key: value`` per
    entry, then a blank line, skipping empty keys and stripping values. If
    nats-py changes that framing, the constants move with it and this
    arithmetic follows.
    """
    from nats.aio.client import NATS_HDR_LINE, _CRLF_

    assert encoded_header_size(None) == 0
    assert encoded_header_size({}) == len(NATS_HDR_LINE) + 2 * len(_CRLF_)

    headers = {"Nats-Msg-Id": "abc", "X-Trace": "sha256:deadbeef"}
    expected = len(NATS_HDR_LINE) + len(_CRLF_)
    for key, value in headers.items():
        expected += len(key.encode()) + 2 + len(value.encode()) + len(_CRLF_)
    expected += len(_CRLF_)
    assert encoded_header_size(headers) == expected

    # Empty keys are skipped by the library, so they cost nothing here either.
    assert encoded_header_size({"  ": "x", **headers}) == expected


def test_the_header_size_uses_strip_not_str_for_str_subtypes() -> None:
    """nats-py calls ``k.strip()``; ``str(k)`` differs for its own Header enum.

    ``Header.DESCRIPTION`` renders as ``Header.DESCRIPTION`` under ``str()``
    but strips to the wire name, and the gap made the budget over-charge by
    seven bytes per header and drop metadata that would have fitted.
    """
    from nats.js.api import Header

    key = Header.DESCRIPTION
    assert str(key) != key.strip(), "premise: the two spellings differ"
    framed = encoded_header_size({key: "x"})
    plain = encoded_header_size({key.strip(): "x"})
    assert framed == plain


def test_the_reply_budget_subtracts_the_headers_that_ride_along() -> None:
    """``Msg.respond`` republishes the request's headers; the server counts them.

    Measured live: a 1,048,568-byte body plus 279 bytes of echoed headers was
    refused at a 1,048,576 limit while the body alone fit.
    """
    headers = {"Nats-Msg-Id": "abc", "X-Trace": "sha256:deadbeef"}
    raw = _RawMsg()
    raw.headers = headers
    msg = NATSMessage("s", {}, reply="_INBOX.1", headers=headers, _msg=raw)
    overhead = encoded_header_size(headers)
    assert overhead > 0
    assert msg.reply_body_budget(1000) == 1000 - overhead
    # Never negative: a header block bigger than the limit leaves nothing.
    assert msg.reply_body_budget(overhead - 1) == 0

    # No headers, no deduction.
    plain = NATSMessage("s", {}, reply="_INBOX.1", _msg=_RawMsg())
    assert plain.reply_body_budget(1000) == 1000


@pytest.mark.asyncio
async def test_metadata_that_only_overflows_once_headers_ride_along() -> None:
    """The body fits the raw limit; body plus echoed headers does not.

    This is the exact live failure, in the suite: a size check that measures
    only the body approves it, and the server refuses the message.
    """
    headers = {"Nats-Msg-Id": "x" * 200}
    overhead = encoded_header_size(headers)
    limit = 1200

    nats = _FakeNats(max_payload=limit)
    bus = IntentBus.__new__(IntentBus)
    bus._nats_bus = nats

    async def _handler(intent: IntentMessage):
        return IntentResult(
            intent_id=intent.id,
            agent_id="agent-ezri",
            success=True,
            result="the answer",
            confidence=0.9,
            timestamp=datetime.now(timezone.utc),
            metadata={"bulk": "y" * (limit - overhead - 150)},
        )

    await IntentBus._nats_subscribe_agent(bus, "agent-ezri", _handler)
    raw = _RawMsg(max_payload=limit, header_bytes=overhead)
    raw.headers = headers
    intent = IntentMessage(intent="direct_message", params={})
    msg = NATSMessage(
        subject="intent.agent-ezri",
        data=json.loads(json.dumps(IntentBus._serialize_intent(intent))),
        reply="_INBOX.1",
        headers=headers,
        _msg=raw,
    )
    await nats.callbacks[0](msg)

    assert raw.payloads, "the reply was refused by the transport"
    reply = json.loads(raw.payloads[-1].decode())
    assert reply["success"] is True
    assert reply["result"] == "the answer"
    assert reply["metadata"] == {}


@pytest.mark.asyncio
async def test_a_metadata_container_that_is_not_a_mapping_is_dropped_whole(
    caplog,
) -> None:
    """There are no keys to prune, and the answer still matters."""
    with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
        reply = await _reply_bytes(metadata=object(), result_value="the answer")
    assert reply is not None
    assert reply["success"] is True
    assert reply["result"] == "the answer"
    assert reply["metadata"] == {}
    assert any("<metadata>" in r.getMessage() for r in caplog.records)

@pytest.mark.asyncio
async def test_a_nan_metadata_value_is_kept_because_the_wire_takes_it() -> None:
    reply_raw = None
    nats = _FakeNats()
    bus = IntentBus.__new__(IntentBus)
    bus._nats_bus = nats

    async def _handler(intent: IntentMessage):
        return IntentResult(
            intent_id=intent.id,
            agent_id="agent-ezri",
            success=True,
            result="ok",
            confidence=0.9,
            timestamp=datetime.now(timezone.utc),
            metadata={"score": float("nan")},
        )

    await IntentBus._nats_subscribe_agent(bus, "agent-ezri", _handler)
    raw = _RawMsg()
    intent = IntentMessage(intent="direct_message", params={})
    msg = NATSMessage(
        subject="intent.agent-ezri",
        data=json.loads(json.dumps(IntentBus._serialize_intent(intent))),
        reply="_INBOX.1",
        _msg=raw,
    )
    await nats.callbacks[0](msg)
    reply_raw = raw.payloads[-1].decode()
    assert "NaN" in reply_raw
    assert '"success": true' in reply_raw


# ── the blast radius is what it says ──────────────────────────────


def test_the_bus_reports_the_servers_limit_not_a_guess() -> None:
    """The limit has to come from the transport, or it is a guess.

    A connected client carries the figure the server advertised at connect; an
    unconnected one falls back to the NATS default rather than to no bound at
    all.
    """
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._nc = None
    assert bus.max_payload == DEFAULT_MAX_PAYLOAD_BYTES

    class _Client:
        max_payload = 8_388_608

    bus._nc = _Client()
    assert bus.max_payload == 8_388_608

    # A client that reports nonsense must not disarm the bound.
    class _Broken:
        max_payload = 0

    bus._nc = _Broken()
    assert bus.max_payload == DEFAULT_MAX_PAYLOAD_BYTES


def test_the_jetstream_dispatch_path_has_no_reply_to_lose() -> None:
    """#1269 lists this as unverified. It is verified here, by enumeration.

    ``_js_subscribe_agent_dispatch`` is fire-and-forget: it enqueues and
    acks/terms. If a reply is ever added there it must go through
    ``_reply_bytes`` too, and this test will fail until it does.

    Scoped to ``IntentBus`` deliberately, and said so: the repository also has
    ``NATSMessage.respond_encoded`` itself, which is the low-level adapter these
    reply sites call rather than a further reply site.
    """
    import ast
    import inspect

    source = inspect.getsource(IntentBus._js_subscribe_agent_dispatch)
    assert ".respond(" not in source

    class_source = inspect.getsource(IntentBus)
    tree = ast.parse(textwrap.dedent(class_source))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("respond", "respond_encoded")
    ]
    # Exactly three reply sites on the bus, and BF-827 (#1291) closed the last
    # gap: ALL THREE now send pre-encoded bytes against a budget. This asserted
    # that the decline was a plain ``respond`` with a dict literal, because
    # that is what shipped -- correct as a record, wrong as a contract, since
    # keeping it would have required the one un-budgeted path to stay
    # un-budgeted. Updated rather than deleted, so the change is recorded where
    # the old shape was.
    assert len(calls) == 3, [ast.dump(c) for c in calls]
    assert [c.func.attr for c in calls] == ["respond_encoded"] * 3, (
        [ast.dump(c) for c in calls]
    )
    assert not [c for c in calls if c.args and isinstance(c.args[0], ast.Dict)], (
        "a reply built from a dict literal is not budgeted"
    )

    # And both IntentResult payloads are built by the degrading builder --
    # whether inline or via a local, which the error path needs so it can fall
    # back when even the error will not fit.
    builders = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("_reply_bytes", "_smallest_error_bytes")
    ]
    assert builders.count("_reply_bytes") == 2, builders
    assert builders.count("_smallest_error_bytes") == 1, builders
