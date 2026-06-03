"""AD-855: tests for the BLOCKED -> request -> approve -> resume gap driver."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.workforce import WorkItemStore


class _RecordingRouter:
    """Stub WorkItemRouter that records re-dispatch calls."""

    def __init__(self) -> None:
        self.dispatched: list[dict] = []

    async def on_work_item_created(self, event: dict) -> None:
        self.dispatched.append(event)


@pytest.fixture
async def work_item_store(tmp_path):
    s = WorkItemStore(db_path=str(tmp_path / "wis.db"), tick_interval=1000)
    await s.start()
    yield s
    await s.stop()


@pytest.fixture
async def request_store(tmp_path):
    s = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"))
    await s.start()
    yield s
    await s.stop()


def _make_runtime(router: _RecordingRouter | None) -> SimpleNamespace:
    # All registries None -> triage routes a gap to kind="build" pending.
    return SimpleNamespace(work_item_router=router, config=None)


def _make_driver(work_item_store, request_store, router) -> CapabilityGapDriver:
    return CapabilityGapDriver(
        runtime=_make_runtime(router),
        work_item_store=work_item_store,
        capability_request_store=request_store,
    )


async def _make_in_progress_item(store: WorkItemStore, **meta):
    return await store.create_work_item(
        title="do the thing",
        work_type="task",
        status="in_progress",
        assigned_to="agent-1",
        metadata=dict(meta),
    )


class TestOnCapabilityGap:
    @pytest.mark.asyncio
    async def test_on_capability_gap_blocks_item_and_files_request(
        self, work_item_store, request_store
    ):
        # Arrange
        router = _RecordingRouter()
        driver = _make_driver(work_item_store, request_store, router)
        item = await _make_in_progress_item(work_item_store, dispatchable=True)

        # Act
        req = await driver.on_capability_gap(
            work_item_id=item.id, gap_target="weather_api", agent_id="agent-1"
        )

        # Assert: request filed, carries the work item link
        assert req is not None
        assert req.work_item_id == item.id
        # Board updated: item is blocked
        refreshed = await work_item_store.get_work_item(item.id)
        assert refreshed is not None
        assert refreshed.status == "blocked"
        # Metadata merged: pre-existing key survives + new keys present
        assert refreshed.metadata.get("dispatchable") is True
        assert refreshed.metadata.get("blocked_reason") == "weather_api"
        assert refreshed.metadata.get("capability_request_id") == req.id

    @pytest.mark.asyncio
    async def test_on_capability_gap_absent_store_degrades_returns_none(
        self, request_store
    ):
        # Arrange: no work_item_store
        driver = CapabilityGapDriver(
            runtime=_make_runtime(None),
            work_item_store=None,
            capability_request_store=request_store,
        )

        # Act
        result = await driver.on_capability_gap(
            work_item_id="missing", gap_target="x", agent_id="a"
        )

        # Assert: log-and-degrade, no raise
        assert result is None


class TestOnCapabilityEvent:
    @pytest.mark.asyncio
    async def test_fulfilled_event_resumes_and_redispatches(
        self, work_item_store, request_store
    ):
        # Arrange: item already blocked via the gap path
        router = _RecordingRouter()
        driver = _make_driver(work_item_store, request_store, router)
        item = await _make_in_progress_item(work_item_store)
        req = await driver.on_capability_gap(
            work_item_id=item.id, gap_target="weather_api", agent_id="agent-1"
        )
        assert req is not None
        router.dispatched.clear()

        # Act: capability request fulfilled
        await driver.on_capability_event(
            {
                "type": "capability_request_fulfilled",
                "data": {"id": req.id, "status": "fulfilled"},
                "timestamp": time.time(),
            }
        )

        # Assert: item resumed and re-dispatched
        refreshed = await work_item_store.get_work_item(item.id)
        assert refreshed is not None
        assert refreshed.status == "in_progress"
        assert len(router.dispatched) == 1
        assert router.dispatched[0]["data"]["work_item"]["id"] == item.id

    @pytest.mark.asyncio
    async def test_decided_denied_event_cancels_with_reason(
        self, work_item_store, request_store
    ):
        # Arrange: blocked item, then deny its request
        router = _RecordingRouter()
        driver = _make_driver(work_item_store, request_store, router)
        item = await _make_in_progress_item(work_item_store)
        req = await driver.on_capability_gap(
            work_item_id=item.id, gap_target="weather_api", agent_id="agent-1"
        )
        assert req is not None
        decided = await request_store.decide(
            req.id, approve=False, reason="out of scope"
        )
        assert decided is not None and decided.status == "denied"

        # Act
        await driver.on_capability_event(
            {
                "type": "capability_request_decided",
                "data": {"id": req.id, "status": "denied"},
                "timestamp": time.time(),
            }
        )

        # Assert: cancelled with denial reason recorded
        refreshed = await work_item_store.get_work_item(item.id)
        assert refreshed is not None
        assert refreshed.status == "cancelled"
        assert refreshed.metadata.get("denial_reason") == "out of scope"

    @pytest.mark.asyncio
    async def test_decided_approved_on_blocked_item_is_noop(
        self, work_item_store, request_store
    ):
        # Arrange: blocked item; resume must wait for FULFILLED, not approval
        router = _RecordingRouter()
        driver = _make_driver(work_item_store, request_store, router)
        item = await _make_in_progress_item(work_item_store)
        req = await driver.on_capability_gap(
            work_item_id=item.id, gap_target="weather_api", agent_id="agent-1"
        )
        assert req is not None
        router.dispatched.clear()

        # Act: DECIDED(approved) arrives before any FULFILLED
        await driver.on_capability_event(
            {
                "type": "capability_request_decided",
                "data": {"id": req.id, "status": "approved"},
                "timestamp": time.time(),
            }
        )

        # Assert: still blocked, no re-dispatch
        refreshed = await work_item_store.get_work_item(item.id)
        assert refreshed is not None
        assert refreshed.status == "blocked"
        assert router.dispatched == []

    @pytest.mark.asyncio
    async def test_event_recovers_work_item_id_via_store_lookup(
        self, work_item_store, request_store
    ):
        # Arrange: event payload carries only the request id (no work_item_id);
        # the driver must recover the link via request_store.get().
        router = _RecordingRouter()
        driver = _make_driver(work_item_store, request_store, router)
        item = await _make_in_progress_item(work_item_store)
        req = await driver.on_capability_gap(
            work_item_id=item.id, gap_target="weather_api", agent_id="agent-1"
        )
        assert req is not None
        router.dispatched.clear()

        # Act: minimal envelope, no work_item_id field anywhere
        await driver.on_capability_event(
            {
                "type": "capability_request_fulfilled",
                "data": {"id": req.id, "status": "fulfilled"},
                "timestamp": time.time(),
            }
        )

        # Assert: recovered the link and resumed
        refreshed = await work_item_store.get_work_item(item.id)
        assert refreshed is not None
        assert refreshed.status == "in_progress"
        assert len(router.dispatched) == 1

    @pytest.mark.asyncio
    async def test_fulfilled_event_with_absent_store_degrades_no_raise(self):
        # Arrange: both stores absent
        driver = CapabilityGapDriver(
            runtime=_make_runtime(None),
            work_item_store=None,
            capability_request_store=None,
        )

        # Act / Assert: no raise
        await driver.on_capability_event(
            {
                "type": "capability_request_fulfilled",
                "data": {"id": "nonexistent", "status": "fulfilled"},
                "timestamp": time.time(),
            }
        )

    @pytest.mark.asyncio
    async def test_event_missing_request_id_is_ignored(
        self, work_item_store, request_store
    ):
        # Arrange
        driver = _make_driver(work_item_store, request_store, _RecordingRouter())

        # Act / Assert: malformed payload (no id) does not raise
        await driver.on_capability_event(
            {"type": "capability_request_fulfilled", "data": {}, "timestamp": 0.0}
        )
