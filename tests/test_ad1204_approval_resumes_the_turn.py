"""AD-1204: approving a ``continue`` must actually resume the work.

The measured defect (reference vessel, 2026-08-04): four approved ``continue``
requests, zero resumptions, two work items stranded ``in_progress`` forever. On
the last one the Captain approved eight seconds after filing and nothing moved.

Nothing here builds a resume path. ``CapabilityGapDriver`` has implemented
BLOCKED -> request -> approve -> resume since AD-855 and it works. This suite
proves the three links that were missing between AD-1164's ``continue`` ask and
that driver:

1. the request is LINKED to the promoted work item (``work_item_id`` was
   hard-coded ``None`` at ``continue_or_ask.py:491``),
2. the item is PARKED ``blocked`` (otherwise the driver's idempotency guard
   ``if item.status != "blocked": return`` makes even a linked event a no-op),
3. approval FULFILS the request (the driver resumes on FULFILLED only;
   DECIDED+approved is explicitly a no-op there, and nothing called
   ``mark_fulfilled`` for ``kind="continue"``).

The load-bearing test is
``TestApprovalResumes::test_approving_re_dispatches_the_item_not_just_relabels_it``.
A status flip without a dispatch is the same dead end with a nicer label, so the
router call is asserted, not the status.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.continue_or_ask import (
    _BLOCKED_REASON,
    CONTINUE_REQUEST_KIND,
    file_continue_request,
    resolve_exhausted_turn,
)
# The REAL regex, imported rather than re-typed: ``lack`` is a bare substring in
# it, so reasoning about a match is not evidence.
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.turn_promotion import run_with_promotion
from probos.config import DmAgenticConfig
from probos.routers.capability_requests import (
    _FULFIL_ON_APPROVAL_KINDS,
    _maybe_fulfil_on_approval,
    decide_capability_request,
)
from probos.workforce import WorkItemStore

_REPO_ROOT = Path(__file__).resolve().parent.parent

_TASK = "Type Hello World into the document I have open"


# ── Test doubles ───────────────────────────────────────────────────────────


class _RecordingRouter:
    """Stub WorkItemRouter that records re-dispatch calls (AD-855's shape)."""

    def __init__(self) -> None:
        self.dispatched: list[dict] = []

    async def on_work_item_created(self, event: dict) -> None:
        self.dispatched.append(event)


class _EventBus:
    """The runtime's local event dispatch, faithfully enough to prove the chain.

    ``runtime._emit_event_local`` spawns a task for a coroutine listener and
    holds the reference (BF-639). Mirrored here so the FULFILLED event really
    travels store -> listener -> driver rather than being hand-delivered, and
    :meth:`drain` gives the test a deterministic join point.
    """

    def __init__(self) -> None:
        self._listeners: list[Any] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self.emitted: list[str] = []

    def add_event_listener(self, fn: Any) -> None:
        self._listeners.append(fn)

    def emit_event(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = getattr(event_type, "value", event_type)
        self.emitted.append(str(type_str))
        event = {
            "type": str(type_str),
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
    """Exactly the attributes the paths under test read off a runtime."""


class _RaisingDriver:
    async def block_on_request(self, **_kwargs: Any) -> bool:
        raise RuntimeError("board is down")


class _RaisingFulfilStore:
    async def mark_fulfilled(self, _request_id: str) -> Any:
        raise RuntimeError("db is down")


class _NullFulfilStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def mark_fulfilled(self, request_id: str) -> Any:
        self.calls.append(request_id)
        return None


async def _never_reinvoked(task_text: str) -> Any:  # pragma: no cover - guard
    raise AssertionError(f"re-invocation must not happen; got {task_text!r}")


def _config() -> DmAgenticConfig:
    """The REAL Pydantic model, so field names and bounds are real."""
    return DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=1
    )


def _cut_off() -> WorkItemAgenticOutcome:
    return WorkItemAgenticOutcome(
        final_text="I have the page open and I am lining up the cursor.",
        stopped_reason="max_iterations",
    )


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
async def work_item_store(tmp_path):
    store = WorkItemStore(db_path=str(tmp_path / "wis.db"), tick_interval=1000)
    await store.start()
    yield store
    await store.stop()


@pytest.fixture
async def bus():
    return _EventBus()


@pytest.fixture
async def request_store(tmp_path, bus):
    store = CapabilityRequestStore(
        db_path=str(tmp_path / "cap.db"), emit_event=bus.emit_event
    )
    await store.start()
    yield store
    await store.stop()


@pytest.fixture
async def wired(work_item_store, request_store, bus):
    """A runtime with the whole AD-855 loop wired the way startup wires it."""
    router = _RecordingRouter()
    runtime = _Runtime(
        work_item_router=router,
        work_item_store=work_item_store,
        capability_request_store=request_store,
        config=None,
    )
    driver = CapabilityGapDriver(
        runtime=runtime,
        work_item_store=work_item_store,
        capability_request_store=request_store,
    )
    runtime.capability_gap_driver = driver
    bus.add_event_listener(driver.on_capability_event)
    return SimpleNamespace(
        runtime=runtime,
        driver=driver,
        router=router,
        bus=bus,
        work_item_store=work_item_store,
        request_store=request_store,
    )


async def _promoted_item(store: WorkItemStore, agent_id: str = "counselor_0"):
    """The AD-1165 shape: a ``task`` already running, owned by the agent."""
    item = await store.create_work_item(
        title=_TASK,
        description=_TASK,
        work_type="task",
        assigned_to=agent_id,
        created_by="captain",
        tags=["conversational-turn"],
        metadata={"source": "dm_agentic_promotion", "thread_id": "thread-1"},
    )
    await store.transition_work_item(item.id, "in_progress", source=agent_id)
    return item


async def _exhaust_a_promoted_turn(wired) -> tuple[Any, Any]:
    """Run the real resolver against a real cut-off outcome. Returns (item, req)."""
    item = await _promoted_item(wired.work_item_store)
    await resolve_exhausted_turn(
        _cut_off(),
        reinvoke=_never_reinvoked,
        runtime=wired.runtime,
        agent_id="counselor_0",
        base_task_text=_TASK,
        thread_id="thread-1",
        work_item_id=item.id,
        config=_config(),
    )
    pending = await wired.request_store.list_pending()
    assert len(pending) == 1
    return item, pending[0]


# ── 1. The request is linked to its work item ──────────────────────────────


class TestTheRequestIsLinked:
    @pytest.mark.asyncio
    async def test_a_promoted_exhausted_turn_files_a_request_linked_to_its_item(
        self, wired
    ):
        """The root cause: ``work_item_id=None`` was hard-coded at the file site."""
        # Arrange / Act
        item, req = await _exhaust_a_promoted_turn(wired)

        # Assert — the link the driver recovers via ``req.work_item_id``.
        assert req.kind == CONTINUE_REQUEST_KIND
        assert req.work_item_id == item.id

    @pytest.mark.asyncio
    async def test_file_continue_request_passes_the_id_straight_through(self, wired):
        """The narrower unit: the id reaches ``file_request`` unchanged."""
        # Arrange
        item = await _promoted_item(wired.work_item_store)

        # Act
        request_id = await file_continue_request(
            wired.runtime,
            agent_id="counselor_0",
            thread_id="thread-1",
            base_task_text=_TASK,
            passes=1,
            work_item_id=item.id,
        )

        # Assert
        assert request_id
        stored = await wired.request_store.get(request_id)
        assert stored is not None
        assert stored.work_item_id == item.id


# ── 2. The item is parked blocked, carrying the request id ─────────────────


class TestTheItemIsParked:
    @pytest.mark.asyncio
    async def test_filing_the_ask_transitions_the_item_to_blocked(self, wired):
        # Arrange / Act
        item, _req = await _exhaust_a_promoted_turn(wired)

        # Assert
        refreshed = await wired.work_item_store.get_work_item(item.id)
        assert refreshed is not None
        assert refreshed.status == "blocked"

    @pytest.mark.asyncio
    async def test_the_blocked_item_carries_the_request_id_and_reason(self, wired):
        """The AD-855 metadata contract, written by the one writer that owns it."""
        # Arrange / Act
        item, req = await _exhaust_a_promoted_turn(wired)

        # Assert
        refreshed = await wired.work_item_store.get_work_item(item.id)
        assert refreshed is not None
        assert refreshed.metadata.get("capability_request_id") == req.id
        assert refreshed.metadata.get("blocked_reason") == _BLOCKED_REASON
        # Read-merge-write: the AD-1165 promotion keys survive.
        assert refreshed.metadata.get("source") == "dm_agentic_promotion"
        assert refreshed.metadata.get("thread_id") == "thread-1"

    @pytest.mark.asyncio
    async def test_an_absent_driver_still_files_the_ask_and_returns_the_work(
        self, request_store, work_item_store
    ):
        """Fail-safe in one direction: losing the park never loses the turn."""
        # Arrange — a runtime with a request store but no gap driver.
        runtime = _Runtime(capability_request_store=request_store)
        item = await _promoted_item(work_item_store)

        # Act
        text = await resolve_exhausted_turn(
            _cut_off(),
            reinvoke=_never_reinvoked,
            runtime=runtime,
            agent_id="counselor_0",
            base_task_text=_TASK,
            work_item_id=item.id,
            config=_config(),
        )

        # Assert — partial work returned, ask filed, item simply not parked.
        # BF-717: the stop notice leads, the partial work follows it.
        assert text.index("I have the page open") > text.index("I have stopped")
        pending = await request_store.list_pending()
        assert len(pending) == 1
        refreshed = await work_item_store.get_work_item(item.id)
        assert refreshed is not None and refreshed.status == "in_progress"

    @pytest.mark.asyncio
    async def test_a_raising_driver_still_files_the_ask_and_returns_the_work(
        self, request_store, work_item_store
    ):
        # Arrange
        runtime = _Runtime(
            capability_request_store=request_store,
            capability_gap_driver=_RaisingDriver(),
        )
        item = await _promoted_item(work_item_store)

        # Act
        text = await resolve_exhausted_turn(
            _cut_off(),
            reinvoke=_never_reinvoked,
            runtime=runtime,
            agent_id="counselor_0",
            base_task_text=_TASK,
            work_item_id=item.id,
            config=_config(),
        )

        # Assert
        assert "step limit" in text
        assert len(await request_store.list_pending()) == 1

    @pytest.mark.asyncio
    async def test_block_on_request_returns_false_on_an_illegal_transition(
        self, wired
    ):
        """A terminal item cannot be parked; the caller must be told, not lied to."""
        # Arrange — ``done`` is terminal for a task.
        item = await _promoted_item(wired.work_item_store)
        await wired.work_item_store.transition_work_item(
            item.id, "done", source="counselor_0"
        )

        # Act
        parked = await wired.driver.block_on_request(
            work_item_id=item.id, request_id="req-1", reason="x"
        )

        # Assert
        assert parked is False
        refreshed = await wired.work_item_store.get_work_item(item.id)
        assert refreshed is not None and refreshed.status == "done"

    @pytest.mark.asyncio
    async def test_block_on_request_returns_false_without_a_work_item_store(
        self, request_store
    ):
        # Arrange
        driver = CapabilityGapDriver(
            runtime=_Runtime(),
            work_item_store=None,
            capability_request_store=request_store,
        )

        # Act / Assert
        assert (
            await driver.block_on_request(
                work_item_id="missing", request_id="req-1", reason="x"
            )
            is False
        )


# ── 3 + 4. Approval fulfils, resumes, and RE-DISPATCHES ────────────────────


class TestApprovalResumes:
    @pytest.mark.asyncio
    async def test_approving_marks_the_continue_request_fulfilled(self, wired):
        # Arrange
        _item, req = await _exhaust_a_promoted_turn(wired)

        # Act — the real REST decision handler.
        result = await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Assert
        assert result["request"]["status"] == "fulfilled"
        assert "capability_request_fulfilled" in wired.bus.emitted

    @pytest.mark.asyncio
    async def test_approving_returns_the_item_to_in_progress(self, wired):
        # Arrange
        item, req = await _exhaust_a_promoted_turn(wired)

        # Act
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Assert
        refreshed = await wired.work_item_store.get_work_item(item.id)
        assert refreshed is not None
        assert refreshed.status == "in_progress"

    @pytest.mark.asyncio
    async def test_approving_re_dispatches_the_item_not_just_relabels_it(self, wired):
        """THE regression that matters.

        A status flip without a dispatch is the same dead end with a nicer
        label: the row would read ``in_progress`` while nothing ran, which is
        precisely the state the two stranded live items were already in. So the
        assertion is on the ROUTER, not the status.
        """
        # Arrange — a genuinely exhausted, genuinely promoted, genuinely parked turn.
        item, req = await _exhaust_a_promoted_turn(wired)
        wired.router.dispatched.clear()

        # Act — the Captain approves, and nothing else happens.
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Assert — the work item was handed back to the router to run again.
        assert len(wired.router.dispatched) == 1
        dispatched = wired.router.dispatched[0]
        assert dispatched["type"] == "work_item_created"
        assert dispatched["data"]["work_item"]["id"] == item.id
        assert dispatched["data"]["work_item"]["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_nothing_resumes_without_an_approval(self, wired):
        """Captain-gated: filing the ask must never re-enter the turn by itself."""
        # Arrange / Act — file, and do not decide.
        item, _req = await _exhaust_a_promoted_turn(wired)

        # Assert
        assert wired.router.dispatched == []
        refreshed = await wired.work_item_store.get_work_item(item.id)
        assert refreshed is not None and refreshed.status == "blocked"


# ── 5. A denial cancels rather than stranding ──────────────────────────────


class TestDenialIsHonest:
    @pytest.mark.asyncio
    async def test_denying_cancels_the_item_rather_than_leaving_it_blocked(
        self, wired
    ):
        # Arrange
        item, req = await _exhaust_a_promoted_turn(wired)

        # Act
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=False, reason="not now"),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Assert — AD-855's ``_cancel`` was reached.
        refreshed = await wired.work_item_store.get_work_item(item.id)
        assert refreshed is not None
        assert refreshed.status == "cancelled"
        assert refreshed.metadata.get("denial_reason") == "not now"

    @pytest.mark.asyncio
    async def test_denying_never_fulfils_and_never_dispatches(self, wired):
        # Arrange
        _item, req = await _exhaust_a_promoted_turn(wired)
        wired.router.dispatched.clear()

        # Act
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=False, reason="not now"),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Assert
        assert "capability_request_fulfilled" not in wired.bus.emitted
        assert wired.router.dispatched == []


# ── 6. A turn that was NOT promoted is untouched ───────────────────────────


class TestUnpromotedTurnIsUnchanged:
    @pytest.mark.asyncio
    async def test_no_work_item_files_an_unlinked_ask_and_parks_nothing(self, wired):
        """Byte-identical to before this AD when the turn finished under budget."""
        # Act — no ``work_item_id`` argument at all.
        text = await resolve_exhausted_turn(
            _cut_off(),
            reinvoke=_never_reinvoked,
            runtime=wired.runtime,
            agent_id="counselor_0",
            base_task_text=_TASK,
            thread_id="thread-1",
            config=_config(),
        )

        # Assert
        pending = await wired.request_store.list_pending()
        assert len(pending) == 1
        assert pending[0].work_item_id is None
        # BF-717: the stop notice leads, the partial work follows it.
        assert text.index("I have the page open") > text.index("I have stopped")
        assert "step limit" in text
        assert wired.router.dispatched == []

    @pytest.mark.asyncio
    async def test_approving_an_unlinked_ask_resumes_nothing_and_does_not_raise(
        self, wired
    ):
        """``on_capability_event`` logs "nothing to resume" — the honest no-op."""
        # Arrange
        await resolve_exhausted_turn(
            _cut_off(),
            reinvoke=_never_reinvoked,
            runtime=wired.runtime,
            agent_id="counselor_0",
            base_task_text=_TASK,
            config=_config(),
        )
        req = (await wired.request_store.list_pending())[0]

        # Act
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()

        # Assert
        assert wired.router.dispatched == []


# ── 7. Idempotency ─────────────────────────────────────────────────────────


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_a_second_fulfilled_event_does_not_re_dispatch(self, wired):
        """The driver acts only while the item is ``blocked``; it now is not."""
        # Arrange — approve once.
        item, req = await _exhaust_a_promoted_turn(wired)
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()
        assert len(wired.router.dispatched) == 1

        # Act — replay the same FULFILLED event.
        await wired.driver.on_capability_event(
            {
                "type": "capability_request_fulfilled",
                "data": {"id": req.id, "status": "fulfilled"},
                "timestamp": time.time(),
            }
        )

        # Assert — still exactly one dispatch, item unchanged.
        assert len(wired.router.dispatched) == 1
        refreshed = await wired.work_item_store.get_work_item(item.id)
        assert refreshed is not None and refreshed.status == "in_progress"

    @pytest.mark.asyncio
    async def test_a_second_approval_is_refused_by_the_pending_guard(self, wired):
        """AD-857 owns the already-decided guard; a re-approve cannot re-resume."""
        from fastapi import HTTPException

        # Arrange
        _item, req = await _exhaust_a_promoted_turn(wired)
        await decide_capability_request(
            req.id,
            CapabilityRequestDecideRequest(approve=True),
            runtime=wired.runtime,
        )
        await wired.bus.drain()
        wired.router.dispatched.clear()

        # Act / Assert
        with pytest.raises(HTTPException) as excinfo:
            await decide_capability_request(
                req.id,
                CapabilityRequestDecideRequest(approve=True),
                runtime=wired.runtime,
            )
        assert excinfo.value.status_code == 400
        assert wired.router.dispatched == []


# ── The plumbing route: how the id reaches the file site ───────────────────


class TestPromotionPublishesTheWorkItemId:
    @pytest.mark.asyncio
    async def test_a_promoted_run_is_told_its_work_item_id(self, work_item_store):
        """The item is created LAZILY, mid-run, so a callback is the only route."""
        # Arrange
        seen: list[str] = []
        started = asyncio.Event()
        release = asyncio.Event()

        async def _work() -> str:
            started.set()
            await release.wait()
            # The run reads the cell at the END of its turn, by which time
            # promotion has already written it.
            return f"saw={seen[0] if seen else ''}"

        runtime = _Runtime(
            work_item_store=work_item_store, chat_thread_store=None, config=None
        )
        hold: set[asyncio.Task[Any]] = set()

        # Act
        ack = await run_with_promotion(
            _work,
            promote_after_seconds=0.01,
            runtime=runtime,
            agent_id="counselor_0",
            thread_id="thread-1",
            request_text=_TASK,
            hold=hold,
            on_promoted=seen.append,
        )
        release.set()
        while hold:
            await asyncio.gather(*tuple(hold), return_exceptions=True)

        # Assert — one publication, and it names the item the ack names.
        assert started.is_set()
        assert len(seen) == 1
        assert seen[0] in ack
        item = await work_item_store.get_work_item(seen[0])
        assert item is not None

    @pytest.mark.asyncio
    async def test_a_fast_turn_is_never_told_an_id(self, work_item_store):
        """No item means no link; the unpromoted path stays exactly as it was."""
        # Arrange
        seen: list[str] = []

        async def _work() -> str:
            return "done fast"

        # Act
        text = await run_with_promotion(
            _work,
            promote_after_seconds=5.0,
            runtime=_Runtime(work_item_store=work_item_store, config=None),
            agent_id="counselor_0",
            thread_id="thread-1",
            request_text=_TASK,
            hold=set(),
            on_promoted=seen.append,
        )

        # Assert
        assert text == "done fast"
        assert seen == []

    @pytest.mark.asyncio
    async def test_a_raising_callback_does_not_fail_the_promotion(
        self, work_item_store
    ):
        """The promotion already succeeded; a bad link must not undo it."""
        # Arrange
        release = asyncio.Event()

        async def _work() -> str:
            await release.wait()
            return "late"

        def _boom(_work_item_id: str) -> None:
            raise RuntimeError("cell is gone")

        hold: set[asyncio.Task[Any]] = set()

        # Act
        ack = await run_with_promotion(
            _work,
            promote_after_seconds=0.01,
            runtime=_Runtime(
                work_item_store=work_item_store, chat_thread_store=None, config=None
            ),
            agent_id="counselor_0",
            thread_id="thread-1",
            request_text=_TASK,
            hold=hold,
            on_promoted=_boom,
        )
        release.set()
        while hold:
            await asyncio.gather(*tuple(hold), return_exceptions=True)

        # Assert — the Captain still gets the acknowledgement.
        assert "task" in ack

    def test_the_conversational_seam_wires_the_cell_to_both_ends(self):
        """Name the real caller. This is it, asserted at the source."""
        # Act
        source = (
            _REPO_ROOT / "src" / "probos" / "cognitive" / "cognitive_agent.py"
        ).read_text(encoding="utf-8")

        # Assert — one cell, written by promotion, read at the file site.
        assert '_promoted: dict[str, str] = {"work_item_id": ""}' in source
        assert "def _record_promotion(work_item_id: str) -> None:" in source
        assert "on_promoted=_record_promotion," in source
        assert 'work_item_id=_promoted["work_item_id"] or None,' in source


# ── Approval-fulfils: the narrow contract and its boundaries ───────────────


class TestFulfilOnApproval:
    def test_the_router_allowlist_agrees_with_the_module_that_files_the_kind(self):
        """Drift guard: the literal here and the constant there are one kind."""
        # Assert
        assert _FULFIL_ON_APPROVAL_KINDS == frozenset({CONTINUE_REQUEST_KIND})

    @pytest.mark.asyncio
    async def test_a_denial_never_fulfils(self):
        # Arrange
        store = _NullFulfilStore()
        decided = SimpleNamespace(id="req-1", kind=CONTINUE_REQUEST_KIND)

        # Act / Assert
        assert await _maybe_fulfil_on_approval(store, decided, approve=False) is False
        assert store.calls == []

    @pytest.mark.asyncio
    async def test_another_kind_is_never_self_fulfilling(self):
        """A grant/install/build has a real fulfiller; approval is not it."""
        # Arrange
        store = _NullFulfilStore()

        # Act / Assert
        for kind in ("grant", "install", "build", "action"):
            decided = SimpleNamespace(id="req-1", kind=kind)
            assert (
                await _maybe_fulfil_on_approval(store, decided, approve=True) is False
            )
        assert store.calls == []

    @pytest.mark.asyncio
    async def test_a_raising_store_degrades_to_false(self):
        # Arrange
        decided = SimpleNamespace(id="req-1", kind=CONTINUE_REQUEST_KIND)

        # Act / Assert
        assert (
            await _maybe_fulfil_on_approval(
                _RaisingFulfilStore(), decided, approve=True
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_an_unknown_id_degrades_to_false(self):
        # Arrange
        store = _NullFulfilStore()
        decided = SimpleNamespace(id="req-1", kind=CONTINUE_REQUEST_KIND)

        # Act / Assert
        assert await _maybe_fulfil_on_approval(store, decided, approve=True) is False
        assert store.calls == ["req-1"]


# ── The blocked reason is agent-safe text ──────────────────────────────────


class TestBlockedReasonWording:
    def test_the_blocked_reason_does_not_read_as_a_capability_gap(self):
        """Checked against the REAL regex — ``lack`` is a bare substring in it."""
        # Act / Assert
        assert _CAPABILITY_GAP_RE.search(_BLOCKED_REASON) is None

    def test_the_blocked_reason_names_the_kind_and_the_cause(self):
        """A board reader must be able to tell WHY the row stopped moving."""
        # Act / Assert
        assert _BLOCKED_REASON.startswith(f"{CONTINUE_REQUEST_KIND}:")
        assert "step limit" in _BLOCKED_REASON
