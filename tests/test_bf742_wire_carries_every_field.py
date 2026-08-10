"""BF-742 (#1196): the NATS wire drops fields nobody declared it could drop.

BF-737 chased a `thread_id` that the router provably set and the agent provably
read, and which provably arrived `None`. Every statement in that chain was true.
The one thing never checked was whether the object the agent receives is the
object the router sent -- it is not. `send()` routes through `_nats_send` when
the bus is connected, and `_serialize_intent` emitted eight of `IntentMessage`'s
nine fields. `thread_id`, added by AD-791a, was the ninth.

A field the wire omits does not fail. It arrives as the dataclass default, so
producer and consumer can both be correct while the value never survives the
trip -- the exact half-chain shape this codebase keeps producing, with the
transport as the unbuilt link.

`IntentResult.metadata` had the same hole, and that one is newer: AD-1203 put
the per-turn tool-trace ref there hours before this was found, and every NATS
reply dropped it.

The round-trip tests below fix the two live cases. The drift guards are the
actual deliverable: they fail when a field is added to either dataclass and not
to its serializer, which is the only way this class of defect stops recurring.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from probos.mesh.intent import IntentBus
from probos.types import IntentMessage, IntentResult


# ── the drift guards ──────────────────────────────────────────────


def test_every_intent_field_crosses_the_wire() -> None:
    """Fails when a field is added to IntentMessage but not the serializer.

    Pinned by NAME against ``dataclasses.fields`` rather than by a hand-written
    list, because a hand-written list is the thing that went stale.
    """
    declared = {f.name for f in dataclasses.fields(IntentMessage)}
    on_the_wire = set(IntentBus._serialize_intent(IntentMessage(intent="x")))

    assert declared - on_the_wire == set(), (
        f"IntentMessage fields dropped by _serialize_intent: "
        f"{sorted(declared - on_the_wire)}. A dropped field arrives as the "
        f"dataclass default, so nothing raises and the value is simply gone."
    )
    assert on_the_wire - declared == set()


def test_every_result_field_crosses_the_wire() -> None:
    declared = {f.name for f in dataclasses.fields(IntentResult)}
    on_the_wire = set(IntentBus._serialize_result(
        IntentResult(intent_id="i", agent_id="a", success=True)
    ))

    assert declared - on_the_wire == set(), (
        f"IntentResult fields dropped by _serialize_result: "
        f"{sorted(declared - on_the_wire)}"
    )
    assert on_the_wire - declared == set()


# ── the two live cases ────────────────────────────────────────────


def test_thread_id_survives_the_round_trip() -> None:
    """BF-737's root cause. Live 2026-08-10 13:09:34: the Captain's message was
    appended to thread e879c64b78d2 at 13:09:31 (so the router's ``thread`` was
    not None), and three seconds later the agent logged
    ``observed thread_id=None type=NoneType present=True``.
    """
    sent = IntentMessage(
        intent="direct_message",
        params={"text": "Hello Ezri"},
        target_agent_id="counselor_counselor_0_67c601cb",
        thread_id="e879c64b78d24d6382e28555c9fec943",
    )

    received = IntentBus._deserialize_intent(IntentBus._serialize_intent(sent))

    assert received.thread_id == "e879c64b78d24d6382e28555c9fec943"


def test_result_metadata_survives_the_round_trip() -> None:
    """AD-1203's per-turn tool-trace ref. Shipped hours before this was found,
    with a green gate, dropped on every NATS reply.
    """
    sent = IntentResult(
        intent_id="i", agent_id="a", success=True, result="ok",
        metadata={"tool_trace_ref": "0aaf7ab7b54f"},
    )

    received = IntentBus._deserialize_result(IntentBus._serialize_result(sent))

    assert received.metadata == {"tool_trace_ref": "0aaf7ab7b54f"}


def test_every_intent_value_survives_the_round_trip() -> None:
    """Not just present on the wire -- equal after it. A field serialized under
    a matching key but reconstructed wrongly would pass the drift guard.
    """
    sent = IntentMessage(
        intent="direct_message",
        params={"text": "hi", "captain_message": "hi"},
        urgency=0.9,
        context="ctx",
        ttl_seconds=42.0,
        id="deadbeef",
        created_at=datetime(2026, 8, 10, 13, 9, 31, tzinfo=timezone.utc),
        target_agent_id="agent-1",
        thread_id="thread-1",
    )

    received = IntentBus._deserialize_intent(IntentBus._serialize_intent(sent))

    for f in dataclasses.fields(IntentMessage):
        assert getattr(received, f.name) == getattr(sent, f.name), f.name


def test_every_result_value_survives_the_round_trip() -> None:
    sent = IntentResult(
        intent_id="i",
        agent_id="a",
        success=True,
        result={"answer": 42},
        error=None,
        confidence=0.75,
        timestamp=datetime(2026, 8, 10, 13, 9, 37, tzinfo=timezone.utc),
        metadata={"tool_trace_ref": "abc123", "n": 3},
    )

    received = IntentBus._deserialize_result(IntentBus._serialize_result(sent))

    for f in dataclasses.fields(IntentResult):
        assert getattr(received, f.name) == getattr(sent, f.name), f.name


# ── a peer that predates the fix ──────────────────────────────────


def test_an_older_peer_omitting_the_new_keys_still_deserializes() -> None:
    """Absent means the pre-BF-742 value, not a hard failure. A node that has
    not been upgraded must still be able to talk to this one.
    """
    intent = IntentBus._deserialize_intent({
        "intent": "direct_message",
        "params": {"text": "hi"},
        "urgency": 0.5,
        "context": "",
        "ttl_seconds": 60.0,
        "id": "x",
        "created_at": "2026-08-10T13:09:31+00:00",
        "target_agent_id": "a",
    })
    assert intent.thread_id is None

    result = IntentBus._deserialize_result({
        "intent_id": "i",
        "agent_id": "a",
        "success": True,
        "result": "ok",
        "error": None,
        "confidence": 0.5,
        "timestamp": "2026-08-10T13:09:37+00:00",
    })
    assert result.metadata == {}


def test_a_hostile_metadata_type_does_not_reach_the_dataclass() -> None:
    """``metadata`` is typed ``dict`` and read with ``.get`` all over the
    codebase. A peer sending a list must not turn that into an AttributeError
    three layers away from the wire.
    """
    for bad in ([], "x", 3, None):
        result = IntentBus._deserialize_result({
            "intent_id": "i", "agent_id": "a", "success": True,
            "timestamp": "2026-08-10T13:09:37+00:00", "metadata": bad,
        })
        assert result.metadata == {}, bad
