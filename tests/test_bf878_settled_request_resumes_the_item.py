"""BF-878: a work item whose capability request settled before the item was parked on it.

``CapabilityGapDriver.on_capability_event`` acts on a request's FULFILLED or
DECIDED(denied) event only while the linked item is ``blocked``. The grant fast
path and the file-time build rung fulfil a request inside ``triage_and_file``,
before ``block_on_request`` parks the item, so the event reached the handler
while the item was still ``in_progress`` and was dropped. Nothing else ever came
for it: the item stayed ``blocked`` on a request that was already done (#1439).
``continue_or_ask`` also parks after filing, so a decision landing in that window
was lost the same way.

The fix resolves a settled request at the one parking point. Both resolving
actors (the event handler and the post-park check) compare-and-set on the item
still being parked on THEIR request, so exactly one of them acts, and neither
acts on an item since parked on another request (A-1). Parking writes the
status and the request id in one write, so no event sees one without the other.

On AD-1204's continue path the post-park check gives the item what the event
handler would have: the same board move and the same router call. Whether that
call continues the turn is #1163's question, not this file's: AD-1165's promoted
items carry no dispatchable tag.

Every chain test runs the real stores, the real driver and AD-1211's event-bus
double (synchronous hook; a coroutine listener spawned as a task, as
``runtime._emit_event_local`` does). Each one asserts the re-dispatch, because
the router is the consumer that has to accept the resumed item. Checking only
the status would miss that.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.continue_or_ask import file_continue_request
from probos.cognitive.turn_promotion import PROMOTION_SOURCE, PROMOTION_TAG
from probos.events import EventType
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission
from probos.workforce import WorkItemStore, WorkTypeDefinition, WorkTypeTransition
from tests.test_ad1211_approval_fulfils_every_kind import (
    _EventBus,
    _RecordingRouter,
    _Runtime,
    _SelfMod,
    _ToolRegistry,
    _registration,
)

_DRIVER_LOG = "probos.cognitive.capability_gap_driver"
_PREMISE_TIMEOUT_S = 5.0


class _Rig(SimpleNamespace):
    """The AD-855 loop wired the way startup wires it, with one ``in_progress`` item."""


class _EventsBeforeParking(WorkItemStore):
    """Delivers every event already emitted before an item is parked ``blocked``.

    That is the ordering that stranded items on HEAD. It is fixed here rather
    than left to the scheduler, so a test cannot pass by a lucky interleaving
    in which the handler already sees the item ``blocked``.
    """

    before_parking: Callable[[], Awaitable[None]] | None = None

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system", **kwargs: Any,
    ) -> Any:
        if new_status == "blocked" and self.before_parking is not None:
            await self.before_parking()
        return await super().transition_work_item(work_item_id, new_status, source, **kwargs)


class _GatedWorkItems(WorkItemStore):
    """Holds every armed move to ``gated`` until ``expected`` callers are waiting.

    A race that is only hoped for proves nothing if the scheduler happens to
    serialise it, so this one is forced.
    """

    def __init__(self, *args: Any, gated: str, expected: int = 2, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._gated = gated
        self._expected = expected
        self.armed = False
        self.arrived = 0
        self.first = asyncio.Event()
        self.release = asyncio.Event()

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system", **kwargs: Any,
    ) -> Any:
        if self.armed and new_status == self._gated:
            self.arrived += 1
            self.first.set()
            if self.arrived >= self._expected:
                self.release.set()
            await self.release.wait()
        return await super().transition_work_item(work_item_id, new_status, source, **kwargs)


class _AfterBlocking(WorkItemStore):
    """Runs a one-shot hook the moment a move to ``blocked`` returns, before its caller goes on."""

    hook: Callable[[], Awaitable[None]] | None = None

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system", **kwargs: Any,
    ) -> Any:
        moved = await super().transition_work_item(work_item_id, new_status, source, **kwargs)
        if self.hook is not None and new_status == "blocked" and moved is not None:
            hook, self.hook = self.hook, None
            await hook()
        return moved


class _DecidedOnFiling(CapabilityRequestStore):
    """A Captain who approves the ask, and sees it fulfilled, before its filer parks the item."""

    async def file_request(self, **kwargs: Any) -> Any:
        filed = await super().file_request(**kwargs)
        await self.decide(filed.id, True, reason="", decided_by="captain")
        return await self.mark_fulfilled(filed.id)


class _HeldGets(CapabilityRequestStore):
    """Holds the first read of ``hold_id`` until released; every later read passes.

    That read is the post-park check's, so the check is held before it acts,
    which is how the review forced the race.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.hold_id: str | None = None
        self.held = asyncio.Event()
        self.release = asyncio.Event()
        self._spent = False

    async def get(self, request_id: str) -> Any:
        if request_id == self.hold_id and not self._spent:
            self._spent = True
            self.held.set()
            await self.release.wait()
        return await super().get(request_id)


class _FirstReadFails(CapabilityRequestStore):
    """A request store whose next read raises, once it is armed."""

    fail_next_read = False

    async def get(self, request_id: str) -> Any:
        if self.fail_next_read:
            self.fail_next_read = False
            raise RuntimeError(f"BF-878 test: request {request_id} could not be read")
        return await super().get(request_id)


@pytest.fixture
async def make_rig(tmp_path: Path) -> AsyncIterator[Callable[..., Awaitable[_Rig]]]:
    built: list[_Rig] = []

    async def make(
        *,
        tools: dict[str, Any] | None = None,
        self_mod: Any = None,
        fast_path: bool = False,
        work_items: WorkItemStore | None = None,
        requests_cls: type[CapabilityRequestStore] = CapabilityRequestStore,
        subscribe: bool = True,
    ) -> _Rig:
        tag = f"rig{len(built)}"
        if work_items is None:
            work_items = _EventsBeforeParking(
                db_path=str(tmp_path / f"{tag}_wis.db"), tick_interval=1000,
            )
        await work_items.start()
        perms = ToolPermissionStore(db_path=str(tmp_path / f"{tag}_perms.db"))
        await perms.start()
        bus = _EventBus()
        if isinstance(work_items, _EventsBeforeParking):
            work_items.before_parking = bus.drain
        requests_db = str(tmp_path / f"{tag}_cap.db")
        requests = requests_cls(db_path=requests_db, emit_event=bus.emit)
        await requests.start()
        router = _RecordingRouter()
        runtime = _Runtime(
            work_item_router=router,
            work_item_store=work_items,
            capability_request_store=requests,
            tool_permission_store=perms,
            trust_network=SimpleNamespace(get_score=lambda _agent_id: 0.99),
            ontology=SimpleNamespace(get_agent_department=lambda _agent_id: "science"),
            tool_registry=_ToolRegistry(tools or {}),
            self_mod_pipeline=self_mod,
            mcp_server_store=None,
            config=SimpleNamespace(capability_triage=SimpleNamespace(
                grant_fast_path_enabled=fast_path, grant_trust_floor=0.5,
            )),
        )
        driver = CapabilityGapDriver(
            runtime=runtime, work_item_store=work_items, capability_request_store=requests,
        )
        runtime.capability_gap_driver = driver
        if subscribe:
            bus.add_event_listener(driver.on_capability_event)
        item = await work_items.create_work_item(
            title="Work needing a capability", description="d", work_type="task",
            assigned_to="agent-1", created_by="captain",
        )
        assert await work_items.transition_work_item(item.id, "in_progress", source="agent-1")
        rig = _Rig(
            work_items=work_items, perms=perms, bus=bus, requests=requests, requests_db=requests_db,
            router=router, runtime=runtime, driver=driver, item=item,
        )
        built.append(rig)
        return rig

    try:
        yield make
    finally:
        for rig in built:
            await rig.bus.drain()
            await rig.requests.stop()
            await rig.perms.stop()
            await rig.work_items.stop()


async def _item(rig: _Rig) -> Any:
    item = await rig.work_items.get_work_item(rig.item.id)
    assert item is not None
    return item


async def _file(rig: _Rig, *, kind: str = "grant", work_item_id: str | None = None) -> Any:
    return await rig.requests.file_request(
        agent_id="agent-1", kind=kind, target="reader", rationale="gap",
        work_item_id=work_item_id or rig.item.id,
    )


def _fulfilled(request_id: str) -> dict[str, Any]:
    return {
        "type": EventType.CAPABILITY_REQUEST_FULFILLED.value,
        "data": {"id": request_id}, "timestamp": 0.0,
    }


async def _reached(event: asyncio.Event) -> bool:
    try:
        await asyncio.wait_for(event.wait(), timeout=_PREMISE_TIMEOUT_S)
    except asyncio.TimeoutError:
        return False
    return True


def _dispatched_ids(rig: _Rig) -> list[str]:
    return [event["data"]["work_item"]["id"] for event in rig.router.dispatched]


def _driver_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records
        if record.name == _DRIVER_LOG and record.levelno >= logging.WARNING
    ]


def _fulfilment_found_it_unparked(caplog: pytest.LogCaptureFixture, item_id: str) -> bool:
    """Premise: the FULFILLED event reached the handler while the item was still ``in_progress``."""
    needle = f"work item {item_id} is in_progress (not blocked); event capability_request_fulfilled"
    return any(needle in record.getMessage() for record in caplog.records)


async def _promoted_turn(rig: _Rig) -> Any:
    """A work item made the way AD-1165 records a promoted turn."""
    turn = await rig.work_items.create_work_item(
        title="summarise the logs", description="summarise the logs", work_type="task",
        assigned_to="agent-1", created_by="captain", tags=[PROMOTION_TAG],
        metadata={"source": PROMOTION_SOURCE, "thread_id": "thread-1", "agent_id": "agent-1"},
    )
    assert await rig.work_items.transition_work_item(turn.id, "in_progress", source="agent-1")
    return turn


def _redispatch_shape(event: dict[str, Any], item_id: str, request_id: str) -> dict[str, Any]:
    """A router call with what differs between two rigs taken out: ids and clocks."""
    item = dict(event["data"]["work_item"])
    assert item.pop("id") == item_id
    metadata = dict(item.pop("metadata"))
    assert metadata.pop("capability_request_id") == request_id
    item.pop("created_at")
    item.pop("updated_at")
    return {"type": event["type"], "item": item, "metadata": metadata}


# -- Seam: the request is fulfilled at filing time ---------------------------


async def test_a_grant_fulfilled_at_filing_resumes_and_redispatches_the_item(make_rig, caplog):
    rig = await make_rig(tools={"reader": _registration({"ensign": "read"})}, fast_path=True)
    await rig.perms.issue_grant(
        "peer-1", "reader", ToolPermission.READ, reason="peer", issued_by="captain",
    )
    caplog.set_level(logging.DEBUG, logger=_DRIVER_LOG)

    req = await rig.driver.on_capability_gap(
        work_item_id=rig.item.id, gap_target="reader", agent_id="agent-1",
    )
    await rig.bus.drain()

    # Premise: the fast path fulfilled the request while filing it, and its event
    # reached the handler before the item was parked. That ordering stranded it.
    assert req is not None and req.kind == "grant" and req.status == "fulfilled"
    assert _fulfilment_found_it_unparked(caplog, rig.item.id)
    item = await _item(rig)
    assert item.status == "in_progress"
    assert _dispatched_ids(rig) == [rig.item.id]
    assert item.metadata["capability_request_id"] == req.id
    assert item.metadata["blocked_reason"] == "reader"


async def test_a_build_fulfilled_at_filing_resumes_the_item(make_rig, caplog):
    rig = await make_rig(self_mod=_SelfMod(SimpleNamespace(status="active")), fast_path=True)
    caplog.set_level(logging.DEBUG, logger=_DRIVER_LOG)

    req = await rig.driver.on_capability_gap(
        work_item_id=rig.item.id, gap_target="summarise", agent_id="agent-1",
    )
    await rig.bus.drain()

    assert req is not None and req.kind == "build" and req.status == "fulfilled"
    assert rig.runtime.self_mod_pipeline.calls, "premise: the agent was built while filing"
    assert _fulfilment_found_it_unparked(caplog, rig.item.id)
    assert (await _item(rig)).status == "in_progress"
    assert _dispatched_ids(rig) == [rig.item.id]


async def test_a_continue_ask_decided_before_parking_gets_what_its_event_would_have_given(
    make_rig, caplog,
):
    """The post-park check gives a turn's item what its FULFILLED event gives one parked first.

    Both items are made the way AD-1165 records a promoted turn. They end with the same board
    move and the same router call, and that is all this asserts: whether the call continues the
    turn is #1163's question, and AD-1165's items carry no dispatchable tag.
    """
    decided_first = await make_rig(requests_cls=_DecidedOnFiling)
    parked_first = await make_rig()
    caplog.set_level(logging.DEBUG, logger=_DRIVER_LOG)

    shapes: list[dict[str, Any]] = []
    for rig in (decided_first, parked_first):
        turn = await _promoted_turn(rig)
        request_id = await file_continue_request(
            rig.runtime, agent_id="agent-1", thread_id="thread-1",
            base_task_text="summarise the logs", passes=3, work_item_id=turn.id,
        )
        await rig.bus.drain()
        if rig is decided_first:
            assert _fulfilment_found_it_unparked(caplog, turn.id), "premise: decided before parking"
        else:
            parked = await rig.work_items.get_work_item(turn.id)
            assert parked is not None and parked.status == "blocked", "premise: parked, then decided"
            assert rig.router.dispatched == []
            await rig.requests.decide(request_id, True, reason="", decided_by="captain")
            await rig.requests.mark_fulfilled(request_id)
            await rig.bus.drain()
        stored = await rig.requests.get(request_id)
        assert stored is not None and stored.status == "fulfilled" and stored.work_item_id == turn.id
        resumed = await rig.work_items.get_work_item(turn.id)
        assert resumed is not None and resumed.status == "in_progress"
        assert len(rig.router.dispatched) == 1
        shapes.append(_redispatch_shape(rig.router.dispatched[0], turn.id, request_id))

    assert shapes[0] == shapes[1]
    assert shapes[0]["item"]["status"] == "in_progress"


# -- Boundaries ---------------------------------------------------------------


async def test_a_request_denied_before_parking_cancels_the_item(make_rig):
    rig = await make_rig()
    req = await _file(rig)
    await rig.requests.decide(req.id, False, reason="not needed", decided_by="captain")
    await rig.bus.drain()
    assert (await _item(rig)).status == "in_progress", "premise: the denial found the item unparked"

    parked = await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=req.id, reason="reader",
    )
    await rig.bus.drain()

    item = await _item(rig)
    assert parked is True
    assert item.status == "cancelled"
    assert item.metadata["denial_reason"] == "not needed"
    assert rig.router.dispatched == []


async def test_a_request_fulfilled_after_parking_resumes_the_item_once(make_rig):
    rig = await make_rig()
    req = await _file(rig)
    assert await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=req.id, reason="reader",
    )
    assert (await _item(rig)).status == "blocked"

    await rig.requests.decide(req.id, True, reason="", decided_by="captain")
    await rig.requests.mark_fulfilled(req.id)
    await rig.bus.drain()

    assert (await _item(rig)).status == "in_progress"
    assert _dispatched_ids(rig) == [rig.item.id]


async def test_an_approval_not_yet_fulfilled_at_parking_waits_for_its_fulfilment(make_rig):
    rig = await make_rig()
    req = await _file(rig)
    await rig.requests.decide(req.id, True, reason="", decided_by="captain")
    await rig.bus.drain()

    assert await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=req.id, reason="reader",
    )
    assert (await _item(rig)).status == "blocked"
    assert rig.router.dispatched == []

    await rig.requests.mark_fulfilled(req.id)
    await rig.bus.drain()

    assert (await _item(rig)).status == "in_progress"
    assert _dispatched_ids(rig) == [rig.item.id]


async def test_a_grant_that_is_not_fast_pathed_leaves_the_item_blocked(make_rig):
    rig = await make_rig(tools={"reader": _registration({"ensign": "read"})}, fast_path=False)
    await rig.perms.issue_grant(
        "peer-1", "reader", ToolPermission.READ, reason="peer", issued_by="captain",
    )

    req = await rig.driver.on_capability_gap(
        work_item_id=rig.item.id, gap_target="reader", agent_id="agent-1",
    )
    await rig.bus.drain()

    assert req is not None and req.kind == "grant" and req.status == "pending"
    assert (await _item(rig)).status == "blocked"
    assert rig.router.dispatched == []


async def test_a_request_linked_to_another_item_is_left_to_its_own_event(make_rig):
    rig = await make_rig()
    other = await rig.work_items.create_work_item(
        title="Other work", description="d", work_type="task",
        assigned_to="agent-1", created_by="captain",
    )
    req = await _file(rig, work_item_id=other.id)
    await rig.requests.decide(req.id, True, reason="", decided_by="captain")
    await rig.requests.mark_fulfilled(req.id)
    await rig.bus.drain()

    assert await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=req.id, reason="reader",
    )
    await rig.bus.drain()

    assert (await _item(rig)).status == "blocked"
    assert rig.router.dispatched == []


async def test_a_fulfilment_committed_before_a_restart_still_resumes_the_item(make_rig):
    rig = await make_rig(subscribe=False)
    req = await _file(rig)
    await rig.requests.decide(req.id, True, reason="", decided_by="captain")
    await rig.requests.mark_fulfilled(req.id)
    await rig.requests.stop()
    reopened = CapabilityRequestStore(db_path=rig.requests_db, emit_event=rig.bus.emit)
    await reopened.start()
    rig.requests = reopened
    driver = CapabilityGapDriver(
        runtime=rig.runtime, work_item_store=rig.work_items, capability_request_store=reopened,
    )

    assert await driver.block_on_request(
        work_item_id=rig.item.id, request_id=req.id, reason="reader",
    )

    assert (await _item(rig)).status == "in_progress"
    assert _dispatched_ids(rig) == [rig.item.id]


async def test_a_failed_post_park_check_is_reported_and_a_later_event_still_resolves_the_item(
    make_rig, caplog,
):
    rig = await make_rig(requests_cls=_FirstReadFails, subscribe=False)
    req = await _file(rig)
    await rig.requests.decide(req.id, True, reason="", decided_by="captain")
    await rig.requests.mark_fulfilled(req.id)
    rig.requests.fail_next_read = True
    caplog.set_level(logging.WARNING, logger=_DRIVER_LOG)

    parked = await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=req.id, reason="reader",
    )

    assert parked is True
    assert (await _item(rig)).status == "blocked"
    warnings = [
        record for record in caplog.records
        if record.name == _DRIVER_LOG and record.levelno == logging.WARNING
        and "BF-878" in record.getMessage()
    ]
    assert len(warnings) == 1 and rig.item.id in warnings[0].getMessage()
    # Review finding 3: the warning once said no later event would resolve the item.
    assert "no later event" not in warnings[0].getMessage()

    await rig.driver.on_capability_event(_fulfilled(req.id))

    assert (await _item(rig)).status == "in_progress"
    assert _dispatched_ids(rig) == [rig.item.id]


# -- Exactly one actor acts ---------------------------------------------------


async def test_the_post_park_check_and_a_late_event_resume_the_item_once(
    make_rig, tmp_path, caplog,
):
    work_items = _GatedWorkItems(
        db_path=str(tmp_path / "gated_resume.db"), tick_interval=1000, gated="in_progress",
    )
    rig = await make_rig(work_items=work_items, subscribe=False)
    req = await _file(rig, kind="continue")
    await rig.requests.decide(req.id, True, reason="", decided_by="captain")
    await rig.requests.mark_fulfilled(req.id)
    work_items.armed = True
    caplog.set_level(logging.DEBUG, logger=_DRIVER_LOG)

    park = asyncio.create_task(rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=req.id, reason="continue",
    ))
    late: asyncio.Task[None] | None = None
    try:
        if not await _reached(work_items.first):
            pytest.fail("premise: nothing tried to resume the item after it was parked")
        assert (await _item(rig)).status == "blocked"
        late = asyncio.create_task(rig.driver.on_capability_event(_fulfilled(req.id)))
        if not await _reached(work_items.release):
            pytest.fail("premise: the late FULFILLED event never tried to resume the item")
    finally:
        work_items.release.set()
        results = await asyncio.gather(park, *([late] if late else []))

    assert results[0] is True
    assert (await _item(rig)).status == "in_progress"
    assert _dispatched_ids(rig) == [rig.item.id]
    # The actor that lost the race says nothing: it did not fail to resume the item.
    assert not _driver_warnings(caplog)


async def test_the_post_park_check_and_a_late_denial_cancel_the_item_once(
    make_rig, tmp_path, caplog,
):
    work_items = _GatedWorkItems(
        db_path=str(tmp_path / "gated_cancel.db"), tick_interval=1000, gated="cancelled",
    )
    rig = await make_rig(work_items=work_items, subscribe=False)
    req = await _file(rig)
    await rig.requests.decide(req.id, False, reason="not needed", decided_by="captain")
    work_items.armed = True
    caplog.set_level(logging.INFO, logger=_DRIVER_LOG)

    park = asyncio.create_task(rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=req.id, reason="reader",
    ))
    late: asyncio.Task[None] | None = None
    try:
        if not await _reached(work_items.first):
            pytest.fail("premise: nothing tried to cancel the item after it was parked")
        assert (await _item(rig)).status == "blocked"
        late = asyncio.create_task(rig.driver.on_capability_event({
            "type": EventType.CAPABILITY_REQUEST_DECIDED.value,
            "data": {"id": req.id, "status": "denied"}, "timestamp": 0.0,
        }))
        if not await _reached(work_items.release):
            pytest.fail("premise: the late denial never tried to cancel the item")
    finally:
        work_items.release.set()
        await asyncio.gather(park, *([late] if late else []))

    item = await _item(rig)
    assert item.status == "cancelled"
    assert item.metadata["denial_reason"] == "not needed"
    cancels = [
        record for record in caplog.records
        if record.name == _DRIVER_LOG and "cancelled (capability request denied)" in record.getMessage()
    ]
    assert len(cancels) == 1
    assert not _driver_warnings(caplog)


# -- A-1: a resolution acts only on an item still parked on its own request -----


async def test_a_post_park_check_held_until_the_item_parks_again_leaves_the_new_wait(
    make_rig, caplog,
):
    rig = await make_rig(requests_cls=_HeldGets, subscribe=False)
    first = await _file(rig)
    await rig.requests.decide(first.id, True, reason="", decided_by="captain")
    await rig.requests.mark_fulfilled(first.id)
    rig.requests.hold_id = first.id
    caplog.set_level(logging.DEBUG, logger=_DRIVER_LOG)

    park = asyncio.create_task(rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=first.id, reason="reader",
    ))
    second: Any = None
    try:
        if not await _reached(rig.requests.held):
            pytest.fail("premise: the post-park check never read its request")
        # The first request's own event resumes the item while that check is held ...
        await rig.driver.on_capability_event(_fulfilled(first.id))
        assert (await _item(rig)).status == "in_progress", "premise: the event resumed the item"
        assert _dispatched_ids(rig) == [rig.item.id]
        # ... and the agent parks it again, on a request nobody has decided.
        second = await _file(rig)
        assert await rig.driver.block_on_request(
            work_item_id=rig.item.id, request_id=second.id, reason="reader",
        )
        assert (await _item(rig)).status == "blocked", "premise: parked again"
    finally:
        rig.requests.release.set()
        parked = await park

    assert parked is True
    item = await _item(rig)
    assert item.status == "blocked"
    assert item.metadata["capability_request_id"] == second.id
    assert _dispatched_ids(rig) == [rig.item.id]
    assert not _driver_warnings(caplog)


async def test_a_duplicate_fulfilment_after_the_item_parks_again_leaves_the_new_wait(
    make_rig, caplog,
):
    rig = await make_rig()
    first = await _file(rig)
    assert await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=first.id, reason="reader",
    )
    await rig.requests.decide(first.id, True, reason="", decided_by="captain")
    await rig.requests.mark_fulfilled(first.id)
    await rig.bus.drain()
    assert (await _item(rig)).status == "in_progress", "premise: the fulfilment resumed the item"
    second = await _file(rig)
    assert await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=second.id, reason="reader",
    )
    await rig.bus.drain()
    assert (await _item(rig)).status == "blocked", "premise: parked again"
    caplog.set_level(logging.DEBUG, logger=_DRIVER_LOG)

    # BF-606: an event can be delivered more than once.
    await rig.driver.on_capability_event(_fulfilled(first.id))

    item = await _item(rig)
    assert item.status == "blocked"
    assert item.metadata["capability_request_id"] == second.id
    assert _dispatched_ids(rig) == [rig.item.id]
    assert not _driver_warnings(caplog)


async def test_a_denial_of_a_request_the_item_no_longer_waits_on_does_not_cancel_it(
    make_rig, caplog,
):
    rig = await make_rig()
    first = await _file(rig)
    assert await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=first.id, reason="reader",
    )
    # The Captain moves the item on by hand, and the agent parks it again on a new request.
    assert await rig.work_items.transition_work_item(rig.item.id, "in_progress", source="captain")
    second = await _file(rig)
    assert await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=second.id, reason="reader",
    )
    assert (await _item(rig)).status == "blocked", "premise: parked again"
    caplog.set_level(logging.DEBUG, logger=_DRIVER_LOG)

    await rig.requests.decide(first.id, False, reason="stale card", decided_by="captain")
    await rig.bus.drain()

    item = await _item(rig)
    assert item.status == "blocked"
    assert item.metadata["capability_request_id"] == second.id
    assert "denial_reason" not in item.metadata
    assert not _driver_warnings(caplog)


async def test_a_duplicate_event_delivered_as_the_item_parks_again_sees_the_new_request(
    make_rig, tmp_path, caplog,
):
    work_items = _AfterBlocking(db_path=str(tmp_path / "after_blocking.db"), tick_interval=1000)
    rig = await make_rig(work_items=work_items, subscribe=False)
    first = await _file(rig)
    assert await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=first.id, reason="reader",
    )
    await rig.requests.decide(first.id, True, reason="", decided_by="captain")
    await rig.requests.mark_fulfilled(first.id)
    await rig.driver.on_capability_event(_fulfilled(first.id))
    assert (await _item(rig)).status == "in_progress", "premise: the fulfilment resumed the item"
    second = await _file(rig)
    seen: list[Any] = []

    async def deliver_the_first_again() -> None:
        seen.append(await _item(rig))
        await rig.driver.on_capability_event(_fulfilled(first.id))

    work_items.hook = deliver_the_first_again
    caplog.set_level(logging.DEBUG, logger=_DRIVER_LOG)

    assert await rig.driver.block_on_request(
        work_item_id=rig.item.id, request_id=second.id, reason="reader",
    )

    assert len(seen) == 1 and seen[0].status == "blocked", "premise: delivered with the item blocked"
    # One write: no reader sees the item blocked while it still names the first request.
    assert seen[0].metadata["capability_request_id"] == second.id
    item = await _item(rig)
    assert item.status == "blocked"
    assert item.metadata["capability_request_id"] == second.id
    assert _dispatched_ids(rig) == [rig.item.id]
    assert not _driver_warnings(caplog)


async def test_a_resume_its_work_type_refuses_is_still_reported(make_rig, caplog):
    rig = await make_rig()
    rig.work_items.work_type_registry.register(WorkTypeDefinition(
        type_id="bf878_one_way", display_name="One way", description="Parks but never resumes.",
        initial_status="open", terminal_statuses=frozenset({"done", "cancelled"}),
        valid_transitions=[
            WorkTypeTransition("open", "in_progress"),
            WorkTypeTransition("in_progress", "blocked"),
        ],
    ))
    one_way = await rig.work_items.create_work_item(
        title="One way", description="d", work_type="bf878_one_way",
        assigned_to="agent-1", created_by="captain",
    )
    assert await rig.work_items.transition_work_item(one_way.id, "in_progress", source="agent-1")
    req = await _file(rig, work_item_id=one_way.id)
    assert await rig.driver.block_on_request(
        work_item_id=one_way.id, request_id=req.id, reason="reader",
    )
    caplog.set_level(logging.DEBUG, logger=_DRIVER_LOG)

    await rig.requests.decide(req.id, True, reason="", decided_by="captain")
    await rig.requests.mark_fulfilled(req.id)
    await rig.bus.drain()

    parked = await rig.work_items.get_work_item(one_way.id)
    assert parked is not None and parked.status == "blocked"
    assert parked.metadata["capability_request_id"] == req.id, "premise: still parked on this request"
    warnings = _driver_warnings(caplog)
    assert len(warnings) == 1 and "could not resume work item" in warnings[0].getMessage()
    assert rig.router.dispatched == []


# -- The store's compare-and-set ------------------------------------------------


async def test_transition_work_item_expected_status_is_a_compare_and_set(tmp_path):
    store = WorkItemStore(db_path=str(tmp_path / "cas.db"), tick_interval=1000)
    await store.start()
    try:
        item = await store.create_work_item(
            title="t", description="d", work_type="task", assigned_to="agent-1", created_by="captain",
        )
        assert await store.transition_work_item(item.id, "in_progress", source="t") is not None

        # A mismatch is refused and changes nothing.
        assert await store.transition_work_item(
            item.id, "blocked", source="t", expected_status="open",
        ) is None
        assert (await store.get_work_item(item.id)).status == "in_progress"
        # Already at the target: BF-606 would return the item, but this caller did not move it.
        assert await store.transition_work_item(
            item.id, "in_progress", source="t", expected_status="blocked",
        ) is None
        # A match moves it.
        moved = await store.transition_work_item(
            item.id, "blocked", source="t", expected_status="in_progress",
        )
        assert moved is not None and moved.status == "blocked"
        # A match does not license an illegal move.
        assert await store.transition_work_item(
            item.id, "done", source="t", expected_status="blocked",
        ) is None
        assert (await store.get_work_item(item.id)).status == "blocked"
        assert await store.transition_work_item(
            "no-such-item", "in_progress", source="t", expected_status="blocked",
        ) is None
        # Without it, BF-606 is unchanged.
        same = await store.transition_work_item(item.id, "blocked", source="t")
        assert same is not None and same.status == "blocked"
    finally:
        await store.stop()


def _event_types(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [event_type for event_type, _data in events]


async def test_transition_work_item_expected_metadata_is_a_compare_and_set(tmp_path):
    events: list[tuple[str, dict[str, Any]]] = []
    store = WorkItemStore(
        db_path=str(tmp_path / "cas_metadata.db"), tick_interval=1000,
        emit_event=lambda event_type, data: events.append(
            (str(getattr(event_type, "value", event_type)), data),
        ),
    )
    await store.start()
    try:
        item = await store.create_work_item(
            title="t", description="d", work_type="task", assigned_to="agent-1",
            created_by="captain", metadata={"capability_request_id": "r1", "flag": True},
        )
        assert await store.transition_work_item(item.id, "in_progress", source="t") is not None
        assert await store.transition_work_item(item.id, "blocked", source="t") is not None
        events.clear()

        # Another request's id, a value that is equal in Python but not the same JSON
        # (True == 1), and a missing key expected to hold a value: each is refused.
        for expected in (
            {"capability_request_id": "r2"},
            {"flag": 1},
            {"absent": "x"},
        ):
            assert await store.transition_work_item(
                item.id, "in_progress", source="t", expected_status="blocked", expected=expected,
            ) is None, expected
        assert (await store.get_work_item(item.id)).status == "blocked"
        assert events == []

        # A missing key matches None, as in merge_work_item_metadata.
        moved = await store.transition_work_item(
            item.id, "in_progress", source="t", expected_status="blocked",
            expected={"capability_request_id": "r1", "flag": True, "absent": None},
        )
        assert moved is not None and moved.status == "in_progress"
        assert _event_types(events) == ["work_item_status_changed"]

        with pytest.raises(ValueError, match="work_item_metadata_expected_invalid"):
            await store.transition_work_item(
                item.id, "blocked", source="t", expected=["capability_request_id"],
            )
        with pytest.raises(ValueError, match="work_item_metadata_expected_invalid"):
            await store.transition_work_item(item.id, "blocked", source="t", expected={1: "r1"})
        assert (await store.get_work_item(item.id)).status == "in_progress"
    finally:
        await store.stop()


async def test_transition_work_item_metadata_patch_lands_with_the_status(tmp_path):
    events: list[tuple[str, dict[str, Any]]] = []
    store = WorkItemStore(
        db_path=str(tmp_path / "patch.db"), tick_interval=1000,
        emit_event=lambda event_type, data: events.append(
            (str(getattr(event_type, "value", event_type)), data),
        ),
    )
    await store.start()
    try:
        item = await store.create_work_item(
            title="t", description="d", work_type="task", assigned_to="agent-1",
            created_by="captain", metadata={"kept": "yes"},
        )
        assert await store.transition_work_item(item.id, "in_progress", source="t") is not None
        events.clear()

        parked = await store.transition_work_item(
            item.id, "blocked", source="t",
            metadata_patch={"capability_request_id": "r1", "blocked_reason": "reader"},
        )
        assert parked is not None and parked.status == "blocked"
        assert parked.metadata == {"kept": "yes", "capability_request_id": "r1", "blocked_reason": "reader"}
        # The two events a park has always emitted, in their order, and both name the request.
        assert _event_types(events) == ["work_item_status_changed", "work_item_updated"]
        assert all(data["work_item"]["metadata"]["capability_request_id"] == "r1" for _t, data in events)

        # Parked again while blocked: the patch is written, and there is no status event.
        events.clear()
        again = await store.transition_work_item(
            item.id, "blocked", source="t", metadata_patch={"capability_request_id": "r2"},
        )
        assert again is not None and again.status == "blocked"
        assert again.metadata == {"kept": "yes", "capability_request_id": "r2", "blocked_reason": "reader"}
        assert _event_types(events) == ["work_item_updated"]

        # Nothing to change: BF-606's no-op, with no write and no event.
        events.clear()
        same = await store.transition_work_item(
            item.id, "blocked", source="t", metadata_patch={"capability_request_id": "r2"},
        )
        assert same is not None and same.updated_at == again.updated_at
        assert events == []

        # A refused move writes neither its status nor its patch.
        assert await store.transition_work_item(
            item.id, "done", source="t", metadata_patch={"capability_request_id": "r3"},
        ) is None
        assert (await store.get_work_item(item.id)).metadata["capability_request_id"] == "r2"
        assert events == []

        with pytest.raises(ValueError, match="ui_scaffold_write_reserved"):
            await store.transition_work_item(
                item.id, "in_progress", source="t", metadata_patch={"ui_scaffold": True},
            )
        with pytest.raises(ValueError, match="work_item_metadata_patch_invalid"):
            await store.transition_work_item(
                item.id, "in_progress", source="t", metadata_patch=[("kept", "no")],
            )
        current = await store.get_work_item(item.id)
        assert current.status == "blocked" and current.metadata["kept"] == "yes"

        # The move is validated against the metadata it would write, as a merge is.
        gated = await store.create_work_item(
            title="g", description="d", work_type="task", assigned_to="agent-1", created_by="captain",
        )
        assert await store.set_steps(gated.id, ["unconfirmed step"]) is not None
        assert await store.transition_work_item(gated.id, "in_progress", source="t") is not None
        assert await store.transition_work_item(
            gated.id, "done", source="t", metadata_patch={"steps_gate_completion": True},
        ) is None
        assert (await store.get_work_item(gated.id)).status == "in_progress"
        # Premise: without that metadata the same move is legal.
        assert await store.transition_work_item(gated.id, "done", source="t") is not None
    finally:
        await store.stop()


async def test_transition_work_item_without_the_new_arguments_does_not_read_the_metadata(tmp_path):
    """Every existing caller moves an item without ``expected`` or ``metadata_patch``. A row
    whose metadata is not a JSON object still moves, as it did before BF-878; an ordinary
    write can store one."""
    events: list[tuple[str, dict[str, Any]]] = []
    store = WorkItemStore(
        db_path=str(tmp_path / "plain.db"), tick_interval=1000,
        emit_event=lambda event_type, data: events.append(
            (str(getattr(event_type, "value", event_type)), data),
        ),
    )
    await store.start()
    try:
        for stored in ([1], "s", 5, True):
            item = await store.create_work_item(
                title="t", description="d", work_type="task", assigned_to="agent-1",
                created_by="captain",
            )
            assert await store.update_work_item(item.id, metadata=json.dumps(stored)) is not None
            assert (await store.get_work_item(item.id)).metadata == stored, "premise: stored as written"
            events.clear()

            moved = await store.transition_work_item(item.id, "in_progress", source="t")

            assert moved is not None and moved.status == "in_progress", stored
            assert moved.metadata == stored
            assert _event_types(events) == ["work_item_status_changed"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_a_metadata_patch_of_another_json_type_is_written(tmp_path):
    """Round-2 review: Python equality reads ``True == 1``, so a patch that changed only a
    value's JSON type was reported as a successful move and never written. The patch is
    compared with the store's exact JSON equality, so it is written and announced."""
    from probos.workforce import WorkItemStore

    announced: list[tuple[str, dict]] = []
    store = WorkItemStore(
        db_path=str(tmp_path / "wis_patch_type.db"), tick_interval=1000,
        emit_event=lambda kind, data: announced.append((str(getattr(kind, "value", kind)), data)),
    )
    await store.start()
    try:
        item = await store.create_work_item(
            title="t", description="d", work_type="task", assigned_to="agent-1",
            created_by="captain", metadata={"flag": 1},
        )
        await store.transition_work_item(item.id, "in_progress", source="test")
        before = await store.get_work_item(item.id)
        assert type(before.metadata["flag"]) is int, "premise: the stored value is an int"
        announced.clear()

        moved = await store.transition_work_item(
            item.id, "in_progress", source="test", metadata_patch={"flag": True},
        )

        assert moved is not None
        after = await store.get_work_item(item.id)
        assert type(after.metadata["flag"]) is bool and after.metadata["flag"] is True
        updates = [data for kind, data in announced if kind == "work_item_updated"]
        assert len(updates) >= 1
        assert updates[-1]["work_item"]["metadata"]["flag"] is True
    finally:
        await store.stop()
