"""BF-722: an approval is durably recorded, or it did not happen.

Two defects that share one concern — the system reported success for a decision
whose consequences had not landed.

**Part A (the store).** ``get()`` returns the cached object ITSELF, not a copy,
and ``CapabilityRequest`` / ``SkillRequest`` are plain (non-frozen) dataclasses.
``decide()`` and ``mark_fulfilled()` therefore mutated the cached instance
BEFORE the UPDATE + COMMIT, and the trailing ``self._cache[req.id] = req`` that
reads like a publish step was a no-op on the same object. A lock timeout or a
commit failure left memory decided and the durable row ``pending``: the request
dropped out of ``list_pending()``, the card disappeared, and a restart brought
it back. Worse, DECIDED/FULFILLED were emitted and trust was moved for a
decision that never persisted — and FULFILLED is what resumes a blocked work
item.

**Part B (the route).** ``_maybe_fulfil_on_approval`` honest-degrades to
``False`` when fulfilment fails, and the route discarded that return value: HTTP
200, card removed, work item still blocked. The blanket already-decided guard
then refused the second attempt, so the failure consumed the only retry.

The load-bearing test is
``TestRetryFulfilsTheWorkItem::test_a_second_approval_fulfils_and_unblocks_the_item``.
It spans route -> store -> event -> work item, because a suite where each half
passes and nothing crosses the seam is exactly how this defect class survives.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.events import EventType
# ``_CONTINUE_KIND`` is the kind the route fulfils by approval alone, imported
# from production rather than re-typed so a change to it reaches this suite
# instead of silently bypassing it. It was ``next(iter(_FULFIL_ON_APPROVAL_KINDS))``
# until AD-1211 replaced that frozenset with a kind -> fulfiller map; the intent
# is unchanged, but the map now holds four kinds, so the self-fulfilling one has
# to be named rather than picked out of a one-element set.
from probos.routers.capability_requests import (
    _CONTINUE_KIND,
    decide_capability_request,
)
from probos.skill_request import SkillRequestStore
from probos.workforce import WorkItemStore


# ── Test doubles ───────────────────────────────────────────────────────────


class _Recorder:
    """Captures ``(event_type, data)`` pairs off the store's emit hook."""

    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, dict(data or {})))

    def types(self) -> list[str]:
        return [str(getattr(t, "value", t)) for t, _ in self.events]


class _Trust:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record_outcome(
        self, agent_id: str, success: bool, **kwargs: Any
    ) -> None:
        self.calls.append({"agent_id": agent_id, "success": success, **kwargs})


class _FailingConnection:
    """A real-shaped aiosqlite handle that fails at one named step.

    ``start()`` must succeed (schema, migration, cache load) or the store never
    reaches the method under test, so the failure is armed afterwards via
    :meth:`arm`.
    """

    def __init__(self, inner: Any, fail_on: str) -> None:
        self._inner = inner
        self._fail_on = fail_on
        self._armed = False
        self.commits = 0

    def arm(self) -> None:
        self._armed = True

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        if self._armed and self._fail_on == "execute":
            raise RuntimeError("BF-722: simulated UPDATE failure")
        return self._inner.execute(*args, **kwargs)

    async def commit(self) -> None:
        if self._armed and self._fail_on == "commit":
            raise RuntimeError("BF-722: simulated commit failure")
        self.commits += 1
        await self._inner.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _FailingFactory:
    """ConnectionFactory whose ``connect`` wraps the real handle."""

    def __init__(self, fail_on: str) -> None:
        self._fail_on = fail_on
        self.handle: _FailingConnection | None = None

    async def connect(self, path: str) -> Any:
        from probos.storage.sqlite_factory import default_factory

        inner = await default_factory.connect(path)
        self.handle = _FailingConnection(inner, self._fail_on)
        return self.handle


class _RecordingRouter:
    def __init__(self) -> None:
        self.dispatched: list[dict[str, Any]] = []

    async def on_work_item_created(self, event: dict[str, Any]) -> None:
        self.dispatched.append(event)


class _EventBus:
    """The runtime's local event dispatch, faithfully enough to prove the chain.

    ``EventEmitterMixin._emit`` calls its hook SYNCHRONOUSLY, and
    ``runtime._emit_event_local`` spawns a task for a coroutine listener and
    holds the reference (BF-639). Both are mirrored here, so the FULFILLED event
    really travels store -> listener -> driver rather than being hand-delivered.
    An async ``emit`` would silently never be awaited and every downstream
    assertion would pass vacuously.
    """

    def __init__(self) -> None:
        self._listeners: list[Any] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self.emitted: list[str] = []

    def add_event_listener(self, fn: Any) -> None:
        self._listeners.append(fn)

    def emit(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = str(getattr(event_type, "value", event_type))
        self.emitted.append(type_str)
        event = {
            "type": type_str,
            "data": dict(data or {}),
            "timestamp": time.time(),
        }
        for fn in self._listeners:
            task = asyncio.create_task(fn(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Await every listener task, including ones they spawn in turn."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks))


class _Runtime(SimpleNamespace):
    """Exactly the attributes the route and driver read off a runtime."""


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
async def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
async def trust() -> _Trust:
    return _Trust()


@pytest.fixture
async def store(tmp_path, recorder, trust):
    s = CapabilityRequestStore(
        db_path=str(tmp_path / "cap.db"),
        emit_event=recorder,
        trust_network=trust,
    )
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


@pytest.fixture
async def skill_store(tmp_path, recorder, trust):
    s = SkillRequestStore(
        db_path=str(tmp_path / "skill.db"),
        emit_event=recorder,
        trust_network=trust,
    )
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def _failing_store(tmp_path, recorder, trust, fail_on: str):
    """A started CapabilityRequestStore whose next write will fail."""
    factory = _FailingFactory(fail_on)
    s = CapabilityRequestStore(
        db_path=str(tmp_path / "cap.db"),
        connection_factory=factory,
        emit_event=recorder,
        trust_network=trust,
    )
    await s.start()
    return s, factory


async def _failing_skill_store(tmp_path, recorder, trust, fail_on: str):
    factory = _FailingFactory(fail_on)
    s = SkillRequestStore(
        db_path=str(tmp_path / "skill.db"),
        connection_factory=factory,
        emit_event=recorder,
        trust_network=trust,
    )
    await s.start()
    return s, factory


# ══ Part A ═════════════════════════════════════════════════════════════════
# ── 1/2. A write that did not land leaves nothing decided ──────────────────


class TestDecideIsAtomicWithItsWrite:
    @pytest.mark.parametrize("fail_on", ["execute", "commit"])
    @pytest.mark.asyncio
    async def test_a_failed_write_leaves_the_request_pending(
        self, tmp_path, recorder, trust, fail_on
    ):
        """The headline: memory must not outrun the durable row."""
        # Arrange
        store, factory = await _failing_store(tmp_path, recorder, trust, fail_on)
        try:
            req = await store.file_request(
                agent_id="agent-1", kind="install", target="numpy"
            )
            recorder.events.clear()
            assert factory.handle is not None
            factory.handle.arm()

            # Act — the store does not swallow; the caller degrades.
            with pytest.raises(RuntimeError):
                await store.decide(req.id, True)

            # Assert — cache still holds the PENDING original.
            cached = await store.get(req.id)
            assert cached is not None
            assert cached.status == "pending"
            assert cached.decided_at is None
            assert cached.decided_by == ""
            assert [r.id for r in await store.list_pending()] == [req.id]
            # ...and nothing downstream was told a decision happened.
            assert recorder.types() == []
            assert trust.calls == []
        finally:
            await store.stop()

    @pytest.mark.parametrize("fail_on", ["execute", "commit"])
    @pytest.mark.asyncio
    async def test_a_failed_write_does_not_survive_a_reopen(
        self, tmp_path, recorder, trust, fail_on
    ):
        """Real DB, real reload: the row on disk is still ``pending``.

        The cache assertion above cannot see the durable row. This one can.
        """
        # Arrange
        store, factory = await _failing_store(tmp_path, recorder, trust, fail_on)
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="numpy"
        )
        assert factory.handle is not None
        factory.handle.arm()
        with pytest.raises(RuntimeError):
            await store.decide(req.id, True)
        await store.stop()

        # Act — reopen over the same file with a healthy connection.
        reopened = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"))
        await reopened.start()
        try:
            # Assert
            reloaded = await reopened.get(req.id)
            assert reloaded is not None
            assert reloaded.status == "pending"
            assert reloaded.decided_by == ""
            assert len(await reopened.list_pending()) == 1
        finally:
            await reopened.stop()


class TestMarkFulfilledIsAtomicWithItsWrite:
    @pytest.mark.parametrize("fail_on", ["execute", "commit"])
    @pytest.mark.asyncio
    async def test_a_failed_write_leaves_the_request_approved(
        self, tmp_path, recorder, trust, fail_on
    ):
        """FULFILLED resumes a blocked item, so it must never precede the commit."""
        # Arrange
        store, factory = await _failing_store(tmp_path, recorder, trust, fail_on)
        try:
            req = await store.file_request(
                agent_id="agent-1", kind=_CONTINUE_KIND, target="continue"
            )
            await store.decide(req.id, True)
            recorder.events.clear()
            assert factory.handle is not None
            factory.handle.arm()

            # Act
            with pytest.raises(RuntimeError):
                await store.mark_fulfilled(req.id)

            # Assert
            cached = await store.get(req.id)
            assert cached is not None
            assert cached.status == "approved"
            assert recorder.types() == []
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_failed_fulfilment_does_not_survive_a_reopen(
        self, tmp_path, recorder, trust
    ):
        # Arrange
        store, factory = await _failing_store(tmp_path, recorder, trust, "commit")
        req = await store.file_request(
            agent_id="agent-1", kind=_CONTINUE_KIND, target="continue"
        )
        await store.decide(req.id, True)
        assert factory.handle is not None
        factory.handle.arm()
        with pytest.raises(RuntimeError):
            await store.mark_fulfilled(req.id)
        await store.stop()

        # Act
        reopened = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"))
        await reopened.start()
        try:
            # Assert
            reloaded = await reopened.get(req.id)
            assert reloaded is not None
            assert reloaded.status == "approved"
        finally:
            await reopened.stop()


class TestSkillDecideIsAtomicWithItsWrite:
    @pytest.mark.parametrize("fail_on", ["execute", "commit"])
    @pytest.mark.asyncio
    async def test_a_failed_write_leaves_the_request_requested(
        self, tmp_path, recorder, trust, fail_on
    ):
        """The ``skill_request`` mirror of the same defect."""
        # Arrange
        store, factory = await _failing_skill_store(
            tmp_path, recorder, trust, fail_on
        )
        try:
            req = await store.file_request("agent-9", "forecasting")
            recorder.events.clear()
            assert factory.handle is not None
            factory.handle.arm()

            # Act
            with pytest.raises(RuntimeError):
                await store.decide(req.id, True)

            # Assert
            cached = await store.get(req.id)
            assert cached is not None
            assert cached.status == "requested"
            assert cached.decided_at is None
            assert [r.id for r in await store.list_pending()] == [req.id]
            assert recorder.types() == []
            assert trust.calls == []
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_failed_write_does_not_survive_a_reopen(
        self, tmp_path, recorder, trust
    ):
        # Arrange
        store, factory = await _failing_skill_store(
            tmp_path, recorder, trust, "commit"
        )
        req = await store.file_request("agent-9", "forecasting")
        assert factory.handle is not None
        factory.handle.arm()
        with pytest.raises(RuntimeError):
            await store.decide(req.id, True)
        await store.stop()

        # Act
        reopened = SkillRequestStore(db_path=str(tmp_path / "skill.db"))
        await reopened.start()
        try:
            # Assert
            reloaded = await reopened.get(req.id)
            assert reloaded is not None
            assert reloaded.status == "requested"
        finally:
            await reopened.stop()


# ── 3. The success path is unchanged ───────────────────────────────────────


class TestTheSuccessPathIsUnchanged:
    @pytest.mark.asyncio
    async def test_decide_still_updates_state_event_and_trust(
        self, store, recorder, trust
    ):
        # Arrange
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="numpy"
        )
        recorder.events.clear()

        # Act
        updated = await store.decide(req.id, True, reason="ok")

        # Assert — returned object, cache and event all agree.
        assert updated is not None
        assert updated.status == "approved"
        assert updated.decided_by == "captain"
        assert updated.decision_reason == "ok"
        assert updated.decided_at is not None
        assert (await store.get(req.id)) is updated
        assert await store.list_pending() == []
        assert recorder.types() == [EventType.CAPABILITY_REQUEST_DECIDED.value]
        assert recorder.events[0][1]["status"] == "approved"
        assert recorder.events[0][1]["decision_reason"] == "ok"
        assert len(trust.calls) == 1
        assert trust.calls[0]["agent_id"] == "agent-1"
        assert trust.calls[0]["success"] is True

    @pytest.mark.asyncio
    async def test_decide_preserves_every_untouched_field(self, store):
        """``replace`` must copy the record, not rebuild a partial one."""
        # Arrange
        req = await store.file_request(
            agent_id="agent-1",
            kind="install",
            target="numpy",
            rationale="need arrays",
            work_item_id="wi-1",
        )

        # Act
        updated = await store.decide(req.id, True)

        # Assert
        assert updated is not None
        assert updated.id == req.id
        assert updated.agent_id == req.agent_id
        assert updated.kind == req.kind
        assert updated.target == req.target
        assert updated.rationale == req.rationale
        assert updated.work_item_id == req.work_item_id
        assert updated.created_at == req.created_at
        assert updated.payload == req.payload

    @pytest.mark.asyncio
    async def test_mark_fulfilled_still_updates_state_and_event(
        self, store, recorder
    ):
        # Arrange
        req = await store.file_request(
            agent_id="agent-1", kind=_CONTINUE_KIND, target="continue"
        )
        await store.decide(req.id, True)
        recorder.events.clear()

        # Act
        updated = await store.mark_fulfilled(req.id)

        # Assert
        assert updated is not None
        assert updated.status == "fulfilled"
        assert updated.decided_by == "captain"  # the decision survives
        assert (await store.get(req.id)) is updated
        assert recorder.types() == [EventType.CAPABILITY_REQUEST_FULFILLED.value]

    @pytest.mark.asyncio
    async def test_unknown_ids_are_still_a_quiet_none(self, store, recorder):
        # Act / Assert
        assert await store.decide("nope", True) is None
        assert await store.mark_fulfilled("nope") is None
        assert recorder.types() == []

    @pytest.mark.asyncio
    async def test_skill_decide_still_updates_state_event_and_trust(
        self, skill_store, recorder, trust
    ):
        # Arrange
        req = await skill_store.file_request("agent-9", "forecasting")
        recorder.events.clear()

        # Act
        updated = await skill_store.decide(req.id, False, reason="out of scope")

        # Assert
        assert updated is not None
        assert updated.status == "denied"
        assert updated.decision_reason == "out of scope"
        assert updated.skill_id == req.skill_id
        assert updated.created_at == req.created_at
        assert (await skill_store.get(req.id)) is updated
        assert await skill_store.list_pending() == []
        assert recorder.types() == [EventType.SKILL_REQUEST_DECIDED.value]
        assert len(trust.calls) == 1
        assert trust.calls[0]["success"] is False

    @pytest.mark.asyncio
    async def test_a_trust_failure_still_does_not_undo_the_decision(self, store):
        """Unchanged tiering: trust is non-critical, the decision is not."""
        # Arrange
        class _Broken:
            def record_outcome(self, *_a: Any, **_k: Any) -> None:
                raise RuntimeError("trust is down")

        store._trust_network = _Broken()
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="numpy"
        )

        # Act
        updated = await store.decide(req.id, True)

        # Assert
        assert updated is not None and updated.status == "approved"


# ── 4. Cache-only mode is byte-identical ───────────────────────────────────


class TestCacheOnlyModeIsUnchanged:
    @pytest.mark.asyncio
    async def test_decide_and_fulfil_work_without_a_db(self, recorder, trust):
        """``db_path=""`` has no commit to fail; the publish still happens."""
        # Arrange
        store = CapabilityRequestStore(
            db_path="", emit_event=recorder, trust_network=trust
        )
        await store.start()
        try:
            req = await store.file_request(
                agent_id="agent-1", kind=_CONTINUE_KIND, target="continue"
            )
            recorder.events.clear()

            # Act
            decided = await store.decide(req.id, True, reason="ok")
            fulfilled = await store.mark_fulfilled(req.id)

            # Assert
            assert decided is not None and decided.status == "approved"
            assert fulfilled is not None and fulfilled.status == "fulfilled"
            assert (await store.get(req.id)) is fulfilled
            assert await store.list_pending() == []
            assert recorder.types() == [
                EventType.CAPABILITY_REQUEST_DECIDED.value,
                EventType.CAPABILITY_REQUEST_FULFILLED.value,
            ]
            assert len(trust.calls) == 1
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_skill_decide_works_without_a_db(self, recorder, trust):
        # Arrange
        store = SkillRequestStore(
            db_path="", emit_event=recorder, trust_network=trust
        )
        await store.start()
        try:
            req = await store.file_request("agent-9", "forecasting")
            recorder.events.clear()

            # Act
            decided = await store.decide(req.id, True)

            # Assert
            assert decided is not None and decided.status == "approved"
            assert (await store.get(req.id)) is decided
            assert recorder.types() == [EventType.SKILL_REQUEST_DECIDED.value]
            assert len(trust.calls) == 1
        finally:
            await store.stop()


# ── Real-DB round trip (repo convention for any store change) ──────────────


class TestRealDbRoundTrip:
    @pytest.mark.asyncio
    async def test_a_decision_reloads_from_disk_field_for_field(self, tmp_path):
        """Cache-only tests cannot see a column or publish-ordering error."""
        # Arrange
        path = str(tmp_path / "cap.db")
        store = CapabilityRequestStore(db_path=path)
        await store.start()
        req = await store.file_request(
            agent_id="agent-1",
            kind="install",
            target="numpy",
            rationale="need arrays",
            work_item_id="wi-1",
        )
        decided = await store.decide(req.id, True, reason="approved by hand")
        assert decided is not None
        await store.stop()

        # Act
        reopened = CapabilityRequestStore(db_path=path)
        await reopened.start()
        try:
            # Assert
            reloaded = await reopened.get(req.id)
            assert reloaded is not None
            assert reloaded.status == "approved"
            assert reloaded.decided_by == "captain"
            assert reloaded.decision_reason == "approved by hand"
            assert reloaded.decided_at == pytest.approx(decided.decided_at)
            assert reloaded.work_item_id == "wi-1"
            assert reloaded.rationale == "need arrays"
            assert await reopened.list_pending() == []
        finally:
            await reopened.stop()

    @pytest.mark.asyncio
    async def test_a_fulfilment_reloads_from_disk(self, tmp_path):
        # Arrange
        path = str(tmp_path / "cap.db")
        store = CapabilityRequestStore(db_path=path)
        await store.start()
        req = await store.file_request(
            agent_id="agent-1", kind=_CONTINUE_KIND, target="continue"
        )
        await store.decide(req.id, True, reason="go on")
        await store.mark_fulfilled(req.id)
        await store.stop()

        # Act
        reopened = CapabilityRequestStore(db_path=path)
        await reopened.start()
        try:
            # Assert — the fulfilment landed and did not clear the decision.
            reloaded = await reopened.get(req.id)
            assert reloaded is not None
            assert reloaded.status == "fulfilled"
            assert reloaded.decided_by == "captain"
            assert reloaded.decision_reason == "go on"
        finally:
            await reopened.stop()

    @pytest.mark.asyncio
    async def test_a_skill_decision_reloads_from_disk(self, tmp_path):
        # Arrange
        path = str(tmp_path / "skill.db")
        store = SkillRequestStore(db_path=path)
        await store.start()
        req = await store.file_request(
            "agent-9", "forecasting", skill_label="Forecasting", source="peer"
        )
        decided = await store.decide(req.id, True, reason="useful")
        assert decided is not None
        await store.stop()

        # Act
        reopened = SkillRequestStore(db_path=path)
        await reopened.start()
        try:
            # Assert
            reloaded = await reopened.get(req.id)
            assert reloaded is not None
            assert reloaded.status == "approved"
            assert reloaded.decided_by == "captain"
            assert reloaded.decision_reason == "useful"
            assert reloaded.decided_at == pytest.approx(decided.decided_at)
            assert reloaded.skill_label == "Forecasting"
            assert reloaded.source == "peer"
        finally:
            await reopened.stop()


# ══ Part B ═════════════════════════════════════════════════════════════════


class _Wired:
    """The AD-855 loop wired the way startup wires it, plus the route."""

    def __init__(self, runtime, driver, router, bus, work_items, requests):
        self.runtime = runtime
        self.driver = driver
        self.router = router
        self.bus = bus
        self.work_items = work_items
        self.requests = requests


@pytest.fixture
async def wired(tmp_path, trust):
    work_items = WorkItemStore(db_path=str(tmp_path / "wis.db"), tick_interval=1000)
    await work_items.start()
    bus = _EventBus()
    requests = CapabilityRequestStore(
        db_path=str(tmp_path / "cap.db"),
        emit_event=bus.emit,
        trust_network=trust,
    )
    await requests.start()
    router = _RecordingRouter()
    runtime = _Runtime(
        work_item_router=router,
        work_item_store=work_items,
        capability_request_store=requests,
        config=None,
    )
    driver = CapabilityGapDriver(
        runtime=runtime,
        work_item_store=work_items,
        capability_request_store=requests,
    )
    runtime.capability_gap_driver = driver
    bus.add_event_listener(driver.on_capability_event)
    try:
        yield _Wired(runtime, driver, router, bus, work_items, requests)
    finally:
        await requests.stop()
        await work_items.stop()


async def _blocked_on_a_continue_request(wired) -> tuple[Any, Any]:
    """A work item parked ``blocked`` on a linked ``continue`` request."""
    item = await wired.work_items.create_work_item(
        title="Type Hello World into the document",
        description="Type Hello World into the document",
        work_type="task",
        assigned_to="counselor_0",
        created_by="captain",
    )
    await wired.work_items.transition_work_item(
        item.id, "in_progress", source="counselor_0"
    )
    req = await wired.requests.file_request(
        agent_id="counselor_0",
        kind=_CONTINUE_KIND,
        target="continue",
        rationale="reached the step limit",
        work_item_id=item.id,
    )
    parked = await wired.driver.block_on_request(
        work_item_id=item.id, request_id=req.id, reason="needs another pass"
    )
    assert parked is True
    refreshed = await wired.work_items.get_work_item(item.id)
    assert refreshed is not None and refreshed.status == "blocked"
    return item, req


class _FulfilmentBreaker:
    """Wraps a real store and fails ``mark_fulfilled`` until released.

    A subclass rather than a monkeypatch on the instance so the route reaches
    the REAL ``decide``, ``get`` and ``list_pending`` throughout.
    """

    def __init__(self, inner: CapabilityRequestStore) -> None:
        self._inner = inner
        self.broken = True
        self.fulfil_attempts = 0

    async def mark_fulfilled(self, request_id: str) -> Any:
        self.fulfil_attempts += 1
        if self.broken:
            raise RuntimeError("BF-722: simulated fulfilment failure")
        return await self._inner.mark_fulfilled(request_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ── 5. A failed fulfilment is reported, not hidden ─────────────────────────


class TestAFailedFulfilmentIsReported:
    @pytest.mark.asyncio
    async def test_the_route_returns_200_and_says_it_did_not_fulfil(self, wired):
        """200 is correct — the approval IS recorded. The body must say the rest."""
        # Arrange
        item, req = await _blocked_on_a_continue_request(wired)
        breaker = _FulfilmentBreaker(wired.requests)
        wired.runtime.capability_request_store = breaker

        # Act
        response = await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Assert — the route did not raise, and it did not claim success.
        assert response["fulfilled"] is False
        assert response["request"]["status"] == "approved"
        assert breaker.fulfil_attempts == 1
        # The approval is durable...
        stored = await wired.requests.get(req.id)
        assert stored is not None and stored.status == "approved"
        # ...and the work item is still waiting, which is the honest state.
        blocked = await wired.work_items.get_work_item(item.id)
        assert blocked is not None and blocked.status == "blocked"
        assert wired.router.dispatched == []
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value not in wired.bus.emitted

    @pytest.mark.asyncio
    async def test_the_request_stays_visible_as_approved_and_unfulfilled(
        self, wired
    ):
        """A card can only be retried while something still lists it."""
        # Arrange
        _item, req = await _blocked_on_a_continue_request(wired)
        breaker = _FulfilmentBreaker(wired.requests)
        wired.runtime.capability_request_store = breaker
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Act / Assert — the store still knows it, in a retryable state.
        stored = await wired.requests.get(req.id)
        assert stored is not None
        assert stored.status == "approved"
        assert stored.decided_by == "captain"


# ── 6. THE CHAIN TEST: route -> store -> event -> work item ────────────────


class TestRetryFulfilsTheWorkItem:
    @pytest.mark.asyncio
    async def test_a_second_approval_fulfils_and_unblocks_the_item(self, wired):
        """The whole seam in one test.

        The Captain approves, fulfilment fails, the item stays blocked. The
        Captain clicks again: the route admits the retry, ``mark_fulfilled``
        commits, FULFILLED travels the bus, ``CapabilityGapDriver`` resumes the
        item and re-dispatches it. Each half of this passed before BF-722; the
        chain did not.
        """
        # Arrange — first approval, fulfilment broken.
        item, req = await _blocked_on_a_continue_request(wired)
        breaker = _FulfilmentBreaker(wired.requests)
        wired.runtime.capability_request_store = breaker
        first = await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()
        assert first["fulfilled"] is False
        still_blocked = await wired.work_items.get_work_item(item.id)
        assert still_blocked is not None and still_blocked.status == "blocked"

        # Act — the retry, with fulfilment working again.
        breaker.broken = False
        second = await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Assert — route reported it...
        assert second["fulfilled"] is True
        assert second["request"]["status"] == "fulfilled"
        # ...store committed it...
        stored = await wired.requests.get(req.id)
        assert stored is not None and stored.status == "fulfilled"
        # ...the event fired...
        assert (
            wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_FULFILLED.value)
            == 1
        )
        # ...and the work item left ``blocked`` and was re-dispatched.
        resumed = await wired.work_items.get_work_item(item.id)
        assert resumed is not None
        assert resumed.status == "in_progress"
        assert len(wired.router.dispatched) == 1
        assert wired.router.dispatched[0]["data"]["work_item"]["id"] == item.id

    @pytest.mark.asyncio
    async def test_the_retry_does_not_re_decide_the_request(self, wired):
        """A retry must not overwrite the decision it is retrying."""
        # Arrange
        _item, req = await _blocked_on_a_continue_request(wired)
        breaker = _FulfilmentBreaker(wired.requests)
        wired.runtime.capability_request_store = breaker
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True, reason="first"),
            runtime=wired.runtime,
        )
        await wired.bus.drain()
        first_decided_at = (await wired.requests.get(req.id)).decided_at

        # Act
        breaker.broken = False
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True, reason="second"),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Assert — the original decision is intact.
        stored = await wired.requests.get(req.id)
        assert stored is not None
        assert stored.decision_reason == "first"
        assert stored.decided_at == first_decided_at
        # DECIDED fired exactly once across both POSTs.
        assert (
            wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_DECIDED.value) == 1
        )


# ── 7. Trust moves exactly once ────────────────────────────────────────────


class TestTrustIsRecordedExactlyOnce:
    @pytest.mark.asyncio
    async def test_an_approve_then_retry_moves_trust_once(self, wired, trust):
        """The reason the retry does not call ``decide()`` again.

        ``decide()`` records a trust outcome. A retry that re-decided would
        inflate the requesting agent's trust once per click — a defect worse
        than the one being fixed, and silent.
        """
        # Arrange
        _item, req = await _blocked_on_a_continue_request(wired)
        breaker = _FulfilmentBreaker(wired.requests)
        wired.runtime.capability_request_store = breaker
        assert trust.calls == []

        # Act — approve, fail, retry, succeed.
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        breaker.broken = False
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Assert
        assert len(trust.calls) == 1
        assert trust.calls[0]["agent_id"] == "counselor_0"
        assert trust.calls[0]["success"] is True

    @pytest.mark.asyncio
    async def test_three_retries_still_move_trust_once(self, wired, trust):
        """Bound the claim: the guard is not 'exactly two clicks'."""
        # Arrange
        _item, req = await _blocked_on_a_continue_request(wired)
        breaker = _FulfilmentBreaker(wired.requests)
        wired.runtime.capability_request_store = breaker

        # Act
        for _ in range(3):
            await decide_capability_request(
                req.id,
                CapabilityRequestDecideRequest(approve=True),
                runtime=wired.runtime,
            )
        await wired.bus.drain()

        # Assert
        assert breaker.fulfil_attempts == 3
        assert len(trust.calls) == 1


# ── 8. The guard still has teeth ───────────────────────────────────────────


class TestTheAlreadyDecidedGuardStillRefuses:
    @pytest.mark.asyncio
    async def test_a_denied_request_is_still_400(self, wired):
        """A denial is not re-decidable here."""
        # Arrange
        _item, req = await _blocked_on_a_continue_request(wired)
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=False, reason="no"),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Act / Assert
        with pytest.raises(HTTPException) as excinfo:
            await decide_capability_request(
                req.id,
                CapabilityRequestDecideRequest(approve=True),
                runtime=wired.runtime,
            )
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_re_denying_an_approved_request_is_still_400(self, wired):
        """Revocation is a different operation, deliberately out of scope."""
        # Arrange
        _item, req = await _blocked_on_a_continue_request(wired)
        breaker = _FulfilmentBreaker(wired.requests)
        wired.runtime.capability_request_store = breaker
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Act / Assert
        with pytest.raises(HTTPException) as excinfo:
            await decide_capability_request(
                req.id,
                CapabilityRequestDecideRequest(approve=False, reason="undo"),
                runtime=wired.runtime,
            )
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_a_fulfilled_request_is_still_400(self, wired):
        """Nothing is left to retry once fulfilment landed."""
        # Arrange
        _item, req = await _blocked_on_a_continue_request(wired)
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()
        assert (await wired.requests.get(req.id)).status == "fulfilled"

        # Act / Assert
        with pytest.raises(HTTPException) as excinfo:
            await decide_capability_request(
                req.id,
                CapabilityRequestDecideRequest(approve=True),
                runtime=wired.runtime,
            )
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_an_unknown_id_is_still_404(self, wired):
        # Act / Assert
        with pytest.raises(HTTPException) as excinfo:
            await decide_capability_request(
                "does-not-exist",
                CapabilityRequestDecideRequest(approve=True),
                runtime=wired.runtime,
            )
        assert excinfo.value.status_code == 404
