"""BF-708: the capability-request notifier must read the REAL event shape.

Every producer in this codebase hands ``add_event_listener`` consumers a *dict*
envelope — ``runtime._emit_event`` (runtime.py) and ``BaseEvent.to_dict``
(events.py) both build ``{"type", "data", "timestamp"}``. The notifier read that
envelope with ``getattr``, which on a dict returns ``None``, so ``agent_id``
resolved to ``""`` and every notice was dropped with the AD-857 warning. Live
evidence at the time of filing: 7 requests filed, 7 notices skipped, 0
delivered.

The pre-existing suite (``test_ad857_capability_request_notifier.py``) was green
throughout, because it constructs an *object* event whose ``.data`` is exactly
what the notifier read. That is the "test double more capable than production"
shape. So the load-bearing test here is
``test_real_emit_path_delivers_notice_end_to_end``: it drives the REAL store
through the REAL ``ProbOSRuntime`` emission methods into a listener registered by
the REAL ``_wire_capability_request_notifier``, and it pins the envelope shape
the runtime produces. If runtime event construction changes, it fails.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.capability_request_notifier import (
    event_payload,
    notify_captain_of_capability_request,
)
from probos.runtime import ProbOSRuntime
from probos.startup.finalize import _wire_capability_request_notifier

AGENT_ID = "agent-abcdef012345"


# ── fakes ──────────────────────────────────────────────────────────
class _FakeChannel:
    def __init__(self, channel_id: str, name: str, channel_type: str) -> None:
        self.id = channel_id
        self.name = name
        self.channel_type = channel_type


class _FakeWardRoom:
    def __init__(self) -> None:
        self._channels: list[_FakeChannel] = []
        self.created_threads: list[dict[str, Any]] = []

    async def list_channels(self) -> list[_FakeChannel]:
        return list(self._channels)

    async def create_channel(self, **kwargs: Any) -> _FakeChannel:
        ch = _FakeChannel("ch-new", kwargs["name"], kwargs["channel_type"])
        self._channels.append(ch)
        return ch

    async def create_thread(self, **kwargs: Any) -> None:
        self.created_threads.append(kwargs)


class _Runtime:
    def __init__(self, ward_room: Any) -> None:
        self.ward_room = ward_room
        self.registry = None
        self.callsign_registry = None


class _ObjectEvent:
    """Dataclass-shaped producer: domain fields hang off ``.data``."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


class _ObjectPayloadEvent:
    """Dataclass-shaped producer using the older ``.payload`` spelling."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload


def _domain_fields(agent_id: str = AGENT_ID) -> dict[str, Any]:
    return {
        "id": "req-123456789012",
        "agent_id": agent_id,
        "kind": "continue",
        "target": "continue: summarise the incident log",
        "work_item_id": None,
    }


# ── event_payload: the five shapes ─────────────────────────────────
def test_event_payload_dict_envelope_with_data_returns_inner_mapping() -> None:
    inner = _domain_fields()
    assert event_payload({"type": "x", "data": inner, "timestamp": 1.0}) is inner


def test_event_payload_dict_envelope_with_payload_returns_inner_mapping() -> None:
    inner = _domain_fields()
    assert event_payload({"type": "x", "payload": inner, "timestamp": 1.0}) is inner


def test_event_payload_object_with_data_returns_inner_mapping() -> None:
    inner = _domain_fields()
    assert event_payload(_ObjectEvent(inner)) is inner


def test_event_payload_object_with_payload_returns_inner_mapping() -> None:
    inner = _domain_fields()
    assert event_payload(_ObjectPayloadEvent(inner)) is inner


def test_event_payload_bare_dict_of_domain_fields_returns_itself() -> None:
    bare = _domain_fields()
    assert event_payload(bare) is bare


def test_event_payload_empty_envelope_returns_inner_not_envelope() -> None:
    """An envelope with no domain fields has none — do not surface type/timestamp."""
    assert event_payload({"type": "x", "data": {}, "timestamp": 1.0}) == {}


def test_event_payload_unrecognised_shape_returns_empty_dict() -> None:
    """Never raise: the caller's own missing-field diagnostic should fire."""
    assert event_payload(object()) == {}
    assert event_payload(None) == {}
    assert event_payload("capability_request_filed") == {}


def test_event_payload_non_mapping_envelope_key_falls_through_to_bare_dict() -> None:
    bare = {"agent_id": AGENT_ID, "data": "not-a-mapping"}
    assert event_payload(bare) is bare


# ── notifier: delivery across producer shapes ──────────────────────
@pytest.mark.parametrize(
    "make_event",
    [
        pytest.param(
            lambda f: {"type": "capability_request_filed", "data": f, "timestamp": 1.0},
            id="dict_envelope_data",
        ),
        pytest.param(
            lambda f: {"type": "capability_request_filed", "payload": f, "timestamp": 1.0},
            id="dict_envelope_payload",
        ),
        pytest.param(_ObjectEvent, id="object_data"),
        pytest.param(_ObjectPayloadEvent, id="object_payload"),
        pytest.param(lambda f: f, id="bare_dict"),
    ],
)
async def test_notifier_delivers_for_every_producer_shape(make_event: Any) -> None:
    ward = _FakeWardRoom()

    await notify_captain_of_capability_request(
        _Runtime(ward), make_event(_domain_fields())
    )

    assert len(ward.created_threads) == 1
    thread = ward.created_threads[0]
    assert "continue: summarise the incident log" in thread["body"]
    assert thread["author_id"] == AGENT_ID


async def test_notifier_skips_and_warns_when_agent_id_genuinely_absent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The AD-857 warning is the diagnostic that surfaced BF-708 — keep it."""
    ward = _FakeWardRoom()
    fields = _domain_fields()
    del fields["agent_id"]

    with caplog.at_level(logging.WARNING, logger="probos.capability_request_notifier"):
        await notify_captain_of_capability_request(
            _Runtime(ward),
            {"type": "capability_request_filed", "data": fields, "timestamp": 1.0},
        )

    assert ward.created_threads == []
    assert any(
        "AD-857" in r.message and "missing agent_id" in r.message
        for r in caplog.records
    )


async def test_notifier_skips_and_warns_when_agent_id_is_empty_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ward = _FakeWardRoom()

    with caplog.at_level(logging.WARNING, logger="probos.capability_request_notifier"):
        await notify_captain_of_capability_request(
            _Runtime(ward),
            {"type": "capability_request_filed", "data": _domain_fields(""), "timestamp": 1.0},
        )

    assert ward.created_threads == []
    assert any("missing agent_id" in r.message for r in caplog.records)


async def test_notifier_skips_with_distinct_warning_when_ward_room_is_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.capability_request_notifier"):
        await notify_captain_of_capability_request(
            _Runtime(None),
            {"type": "capability_request_filed", "data": _domain_fields(), "timestamp": 1.0},
        )

    messages = [r.message for r in caplog.records]
    assert any("ward room unavailable" in m for m in messages)
    assert not any("missing agent_id" in m for m in messages)


# ── the load-bearing end-to-end test ───────────────────────────────
class _RealEmitHost:
    """A runtime stand-in that borrows the REAL emission methods verbatim.

    These are the unmodified ``ProbOSRuntime`` functions, so the envelope this
    host produces is byte-for-byte what production produces. Nothing here
    re-implements event construction — that is the whole point: a test that
    builds its own envelope cannot detect a mismatch between what the runtime
    emits and what a listener reads, which is precisely how BF-708 survived.
    """

    add_event_listener = ProbOSRuntime.add_event_listener
    _emit_event = ProbOSRuntime._emit_event
    _emit_event_local = ProbOSRuntime._emit_event_local
    _check_night_order_escalation = ProbOSRuntime._check_night_order_escalation

    def __init__(self, ward_room: Any) -> None:
        self.ward_room = ward_room
        self.registry = None
        self.callsign_registry = None
        self._event_listeners: list[Any] = []
        self._live_event_listeners: list[Any] = []
        self._event_listener_tasks: set[asyncio.Task] = set()
        self._nats_events_wired = False

    async def drain(self) -> None:
        """Await the listener tasks ``_emit_event_local`` spawned."""
        while self._event_listener_tasks:
            await asyncio.gather(*tuple(self._event_listener_tasks))


async def test_real_emit_path_delivers_notice_end_to_end() -> None:
    """file_request -> real _emit_event -> real wiring -> a delivered notice.

    This is the test that would have caught BF-708. Nothing in the chain is
    re-implemented: the store is the real ``CapabilityRequestStore``, emission
    is ``ProbOSRuntime._emit_event``/``_emit_event_local``, and the listener is
    registered by the real ``_wire_capability_request_notifier``.
    """
    ward = _FakeWardRoom()
    host = _RealEmitHost(ward)

    assert _wire_capability_request_notifier(runtime=host, config=None) is True

    store = CapabilityRequestStore(db_path="", emit_event=host._emit_event)
    request = await store.file_request(
        agent_id=AGENT_ID,
        kind="continue",
        target="continue: summarise the incident log",
        rationale="cut off after 3 passes",
    )
    await host.drain()

    assert len(ward.created_threads) == 1, (
        "the Captain received no notice for a filed request — the approval path "
        "is severed exactly as it was in BF-708"
    )
    thread = ward.created_threads[0]
    assert request.id[:12] in thread["body"]
    assert "continue: summarise the incident log" in thread["body"]


async def test_real_emit_path_envelope_shape_is_nested_under_data() -> None:
    """Pin the envelope the runtime actually produces (runtime.py _emit_event).

    The notifier's helper resolves ``data`` one level down. If runtime event
    construction ever flattens the envelope or renames the key, this fails here
    rather than silently reverting production to zero delivered notices.
    """
    host = _RealEmitHost(_FakeWardRoom())
    seen: list[Any] = []

    async def _record(event: Any) -> None:
        seen.append(event)

    host.add_event_listener(_record, event_types=["capability_request_filed"])

    store = CapabilityRequestStore(db_path="", emit_event=host._emit_event)
    await store.file_request(agent_id=AGENT_ID, kind="install", target="numpy")
    await host.drain()

    assert len(seen) == 1
    envelope = seen[0]
    assert isinstance(envelope, dict), "producers hand listeners a dict, not an object"
    assert set(envelope) == {"type", "data", "timestamp"}
    assert envelope["type"] == "capability_request_filed"
    assert envelope["data"]["agent_id"] == AGENT_ID
    assert event_payload(envelope) is envelope["data"]


async def test_real_emit_path_skips_when_ward_room_missing() -> None:
    """Honest-degrade survives the real path: no ward room, no raise."""
    host = _RealEmitHost(None)
    assert _wire_capability_request_notifier(runtime=host, config=None) is True

    store = CapabilityRequestStore(db_path="", emit_event=host._emit_event)
    await store.file_request(agent_id=AGENT_ID, kind="grant", target="fs.write")
    await host.drain()  # must not raise
