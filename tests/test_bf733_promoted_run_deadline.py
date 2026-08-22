"""BF-733 (#1191): a promoted run that never returns must still report.

Measured on the reference vessel 2026-08-08. Work item ``ccabc4818bd1`` was
promoted at 22:02:16, the LLM endpoint went empty-200 across all three text
tiers at 22:04:05 and recovered by 22:09:10 -- and at 22:17 the run had still
not returned, still not reported, and the row was still ``in_progress`` with an
``updated_at`` frozen at promotion. The Captain held an acknowledgement
promising a report that nothing would ever deliver.

The reporter awaited the run with a bare ``await task``. Which await inside the
run was the slow one is *not* what these tests pin, deliberately: the LLM
client's per-endpoint semaphore acquire is untimed on purpose (BF-654's
fail-open was removed so a saturated endpoint can never be exceeded), a tool can
wedge, and the next one can wedge somewhere new. Enumerating suspension points
is unbounded work. A deadline on the run as a whole is the property that holds
whichever await is at fault, so that is what is tested here.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.turn_promotion import (
    _ACK_TEMPLATE,
    _REPORT_ABANDON_UNCONFIRMED,
    _REPORT_ABANDONED,
    _REPORT_EMPTY,
    _REPORT_FAILED,
    run_with_promotion,
)
from probos.config import DmAgenticConfig
from probos.workforce import WorkItem


# ── harness ───────────────────────────────────────────────────────


class _FakeWorkItemStore:
    """Backed by the REAL ``WorkItem`` so a bad field name raises here."""

    def __init__(self) -> None:
        self.created: list[WorkItem] = []
        self.transitions: list[tuple[str, str, str]] = []

    async def create_work_item(self, **kwargs):
        item = WorkItem(status="open", **kwargs)
        self.created.append(item)
        return item

    async def transition_work_item(self, work_item_id, new_status, source="system"):
        self.transitions.append((work_item_id, new_status, source))
        return None


class _FakeThreadStore:
    def __init__(self) -> None:
        self.appended: list[dict] = []

    def append_message(self, thread_id, *, author_id, role, body, metadata=None):
        self.appended.append({"thread_id": thread_id, "role": role, "body": body})
        return None


class _Slot:
    """A BF-732 concurrency slot that records enter/exit."""

    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def __aenter__(self):
        self._log.append("enter")
        return self

    async def __aexit__(self, *exc):
        self._log.append("exit")
        return False


class _FakeEpisodicMemory:
    def __init__(self) -> None:
        self.stored: list = []

    async def store(self, episode):
        self.stored.append(episode)
        return None


class _BlockingSlot:
    """A BF-732 slot that does not admit until ``admit`` is set.

    ``ConcurrencyManager.acquire`` waits without a bound when its capacity is
    taken, which is the condition a herd of stalled runs produces.
    """

    def __init__(self, admit: asyncio.Event) -> None:
        self._admit = admit

    async def __aenter__(self):
        await self._admit.wait()
        return self

    async def __aexit__(self, *exc):
        return False


def _runtime(store, threads):
    return SimpleNamespace(work_item_store=store, chat_thread_store=threads)


async def _settle(hold: set, *, seconds: float) -> None:
    """Let the detached reporter run, then tear down whatever is left."""
    await asyncio.sleep(seconds)


async def _teardown(hold: set) -> None:
    for task in tuple(hold):
        task.cancel()
    if hold:
        await asyncio.gather(*tuple(hold), return_exceptions=True)


async def _promote(work, *, store, threads, deadline, hold, **kwargs):
    return await run_with_promotion(
        work,
        promote_after_seconds=0.01,
        runtime=_runtime(store, threads),
        agent_id="agent-ezri",
        thread_id="thread-1",
        request_text="for each of the top 15 python packages on pypi",
        hold=hold,
        deadline_seconds=deadline,
        **kwargs,
    )


async def _never() -> str:
    """A run suspended for good, like the live one."""
    await asyncio.Event().wait()
    return "unreachable"


# ── the defect ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stranded_promoted_run_reports_instead_of_hanging_forever() -> None:
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    try:
        ack = await _promote(
            _never, store=store, threads=threads, deadline=0.2, hold=hold
        )
        assert ack.startswith("I've started")
        await _settle(hold, seconds=0.6)

        bodies = [m["body"] for m in threads.appended]
        assert bodies == [_REPORT_ABANDONED]
        item_id = store.created[0].id
        assert (item_id, "failed", "agent-ezri") in store.transitions
    finally:
        await _teardown(hold)


@pytest.mark.asyncio
async def test_the_abandoned_report_is_distinguishable_from_the_other_three() -> None:
    """Which of the four report wordings ran is the discriminating fact.

    A test asserting only "something was posted" passes on the empty-report
    path too, and that path means the run RETURNED with no text -- the opposite
    of what this BF is about.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    try:
        await _promote(_never, store=store, threads=threads, deadline=0.2, hold=hold)
        await _settle(hold, seconds=0.6)
        body = threads.appended[0]["body"]
        assert body == _REPORT_ABANDONED
        assert body != _REPORT_FAILED
        assert body != _REPORT_EMPTY
        # It must not claim the work finished.
        assert "finished" not in body
    finally:
        await _teardown(hold)


def _stubborn_run(release: asyncio.Event):
    """A run that swallows cancellation until ``release`` is set.

    ``Task.cancel()`` is a request, and this is the double for a run that never
    honours it -- wedged inside a shield, or blocked in an executor thread. It
    has to be releasable or the loop's own teardown (``_cancel_all_tasks``)
    inherits the wedge and hangs the whole session.
    """

    async def _run() -> str:
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                if release.is_set():
                    raise
                continue

    return _run


@pytest.mark.asyncio
async def test_a_run_that_ignores_cancellation_is_reported_as_unconfirmed() -> None:
    """``Task.cancel()`` is a request. The report does not wait on the answer.

    A run wedged inside a shield or a blocking executor call may never honour
    the cancellation; withholding the Captain's report until it does would
    reproduce the very defect this fixes. But the report must not claim "I
    stopped it" either -- the runtime has no evidence for that, and the run can
    still produce side effects.
    """
    import probos.cognitive.turn_promotion as tp

    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    release = asyncio.Event()
    original_grace = tp._ABANDON_GRACE_SECONDS
    tp._ABANDON_GRACE_SECONDS = 0.05
    try:
        await _promote(
            _stubborn_run(release),
            store=store,
            threads=threads,
            deadline=0.2,
            hold=hold,
        )
        await _settle(hold, seconds=0.8)

        assert [m["body"] for m in threads.appended] == [
            _REPORT_ABANDON_UNCONFIRMED
        ]
        assert _REPORT_ABANDON_UNCONFIRMED != _REPORT_ABANDONED
    finally:
        tp._ABANDON_GRACE_SECONDS = original_grace
        release.set()
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_run_that_may_still_be_executing_leaves_its_item_open() -> None:
    """Closing terminally here is both a false claim and a later write conflict.

    The AD-498 state machine refuses a transition out of a terminal status, so
    a run that eventually finishes would have its own ``done`` rejected -- and
    the board would have shown ``failed`` for work that completed.
    """
    import probos.cognitive.turn_promotion as tp

    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    release = asyncio.Event()
    original_grace = tp._ABANDON_GRACE_SECONDS
    tp._ABANDON_GRACE_SECONDS = 0.05
    try:
        await _promote(
            _stubborn_run(release),
            store=store,
            threads=threads,
            deadline=0.2,
            hold=hold,
        )
        await _settle(hold, seconds=0.8)
        assert [t[1] for t in store.transitions] == ["in_progress"]
    finally:
        tp._ABANDON_GRACE_SECONDS = original_grace
        release.set()
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_stubborn_run_logs_that_it_did_not_unwind(caplog) -> None:
    """The report is delivered, and the residual risk is said out loud.

    An abandoned run that never unwound may still hold LLM capacity and open
    sockets. Reporting silently would claim a cleanliness the runtime does not
    have.
    """
    import probos.cognitive.turn_promotion as tp

    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    release = asyncio.Event()
    original_grace = tp._ABANDON_GRACE_SECONDS
    tp._ABANDON_GRACE_SECONDS = 0.05
    try:
        with caplog.at_level(logging.ERROR, logger="probos.cognitive.turn_promotion"):
            await _promote(
                _stubborn_run(release),
                store=store,
                threads=threads,
                deadline=0.2,
                hold=hold,
            )
            await _settle(hold, seconds=0.8)
        messages = [r.getMessage() for r in caplog.records]
        assert any("did not unwind" in m for m in messages), messages
    finally:
        tp._ABANDON_GRACE_SECONDS = original_grace
        release.set()
        await _teardown(hold)


@pytest.mark.asyncio
async def test_the_deadline_runs_while_the_reporter_queues_for_a_slot() -> None:
    """BF-732's slot acquire is itself an unbounded wait.

    Arming the deadline behind it would suspend the supervision inside the very
    queue a herd of stalled runs creates -- so the stranded promise would come
    straight back under slot starvation.

    This test originally asserted ``threads.appended == []`` while the slot was
    blocked, then a report only after admission. That pinned the defect as the
    contract: cancelling THIS run frees capacity somebody else is holding, so a
    stuck holder kept the report hostage indefinitely. Inverted rather than
    deleted, so the history stays visible.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    started = asyncio.Event()
    admit = asyncio.Event()

    async def _work() -> str:
        started.set()
        await asyncio.Event().wait()
        return "unreachable"

    try:
        await _promote(
            _work,
            store=store,
            threads=threads,
            deadline=0.2,
            hold=hold,
            background_slot=lambda: _BlockingSlot(admit),
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        run_task = next(t for t in hold if t.get_name().startswith("ad1165-turn"))

        # The slot never admits. The run is stopped and the report lands anyway.
        await _settle(hold, seconds=0.6)
        assert not admit.is_set()
        assert run_task.done() and run_task.cancelled()
        assert [m["body"] for m in threads.appended] == [_REPORT_ABANDONED]
        assert store.transitions[-1][1] == "failed"
    finally:
        admit.set()
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_reporter_cancelled_while_queued_for_a_slot_cancels_the_run()  -> None:
    """AD-1165's contract has to hold before the reporter reaches its own body.

    Cancelled in the slot queue, ``_finish_promoted_turn`` is never entered, so
    its cancellation branch cannot be the thing that propagates into the run.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    started = asyncio.Event()
    admit = asyncio.Event()

    async def _work() -> str:
        started.set()
        await asyncio.Event().wait()
        return "unreachable"

    try:
        await _promote(
            _work,
            store=store,
            threads=threads,
            deadline=60.0,
            hold=hold,
            background_slot=lambda: _BlockingSlot(admit),
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        run_task = next(t for t in hold if t.get_name().startswith("ad1165-turn"))
        reporter = next(t for t in hold if t.get_name().startswith("ad1165-report"))
        await asyncio.sleep(0.05)

        reporter.cancel()
        await asyncio.gather(reporter, return_exceptions=True)
        await asyncio.wait_for(
            asyncio.gather(run_task, return_exceptions=True), timeout=5.0
        )
        assert run_task.cancelled()
        assert threads.appended == []
        assert [t[1] for t in store.transitions] == ["in_progress"]
    finally:
        admit.set()
        await _teardown(hold)


@pytest.mark.asyncio
async def test_an_exception_raised_while_unwinding_is_retrieved(caplog) -> None:
    """``await task`` used to consume whatever the run raised; a bound does not.

    Left unretrieved it surfaces at garbage-collection time as "Task exception
    was never retrieved", naming a task nobody can trace to a work item.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()

    async def _explodes_on_cleanup() -> str:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("cleanup exploded") from None
        return "unreachable"

    try:
        with caplog.at_level(
            logging.WARNING, logger="probos.cognitive.turn_promotion"
        ):
            await _promote(
                _explodes_on_cleanup,
                store=store,
                threads=threads,
                deadline=0.2,
                hold=hold,
            )
            await _settle(hold, seconds=0.6)
        run_task = next(
            t for t in hold if t.get_name().startswith("ad1165-turn")
        ) if hold else None
        messages = [r.getMessage() for r in caplog.records]
        assert any("raised while unwinding" in m for m in messages), messages
        if run_task is not None:
            assert isinstance(run_task.exception(), RuntimeError)
        assert [m["body"] for m in threads.appended] == [_REPORT_ABANDONED]
    finally:
        await _teardown(hold)



@pytest.mark.asyncio
async def test_an_abandoned_run_releases_its_concurrency_slot() -> None:
    """BF-732's slot is held for the run's life; an unbounded life leaks it."""
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    slot_log: list[str] = []
    try:
        await _promote(
            _never,
            store=store,
            threads=threads,
            deadline=0.2,
            hold=hold,
            background_slot=lambda: _Slot(slot_log),
        )
        await _settle(hold, seconds=0.6)
        assert slot_log == ["enter", "exit"]
    finally:
        await _teardown(hold)


@pytest.mark.asyncio
async def test_the_abandoned_run_is_actually_stopped() -> None:
    """Reporting is half of it. A run left alive keeps burning what it holds.

    The BF-732 slot the reporter releases is only one of the resources: the run
    also holds an LLM lane, an endpoint permit and whatever sockets it opened,
    and none of those are the reporter's to give back.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    started = asyncio.Event()

    async def _work() -> str:
        started.set()
        await asyncio.Event().wait()
        return "unreachable"

    try:
        await _promote(_work, store=store, threads=threads, deadline=0.2, hold=hold)
        await asyncio.wait_for(started.wait(), timeout=2.0)
        run_task = next(t for t in hold if t.get_name().startswith("ad1165-turn"))
        await _settle(hold, seconds=0.6)
        assert run_task.done()
        assert run_task.cancelled()
    finally:
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_run_that_unwinds_cleanly_is_not_reported_as_stuck(caplog) -> None:
    """The counterpart to the stubborn case: no false alarm on the normal one.

    Without this, dropping the grace wait entirely would look identical -- every
    abandoned run would be logged as having refused to unwind.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    try:
        with caplog.at_level(logging.ERROR, logger="probos.cognitive.turn_promotion"):
            await _promote(
                _never, store=store, threads=threads, deadline=0.2, hold=hold
            )
            await _settle(hold, seconds=0.6)
        messages = [r.getMessage() for r in caplog.records]
        assert not any("did not unwind" in m for m in messages), messages
        assert [m["body"] for m in threads.appended] == [_REPORT_ABANDONED]
    finally:
        await _teardown(hold)


@pytest.mark.asyncio
async def test_the_episode_records_an_abandoned_run_as_unsuccessful() -> None:
    """AD-1166 exists so promoted turns feed trust, routing and dreaming.

    An abandoned run stored as a success would teach the opposite of what
    happened -- and promoted turns are, by construction, the hard ones.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    memory = _FakeEpisodicMemory()
    runtime = SimpleNamespace(
        work_item_store=store,
        chat_thread_store=threads,
        episodic_memory=memory,
    )
    try:
        await run_with_promotion(
            _never,
            promote_after_seconds=0.01,
            runtime=runtime,
            agent_id="agent-ezri",
            thread_id="thread-1",
            request_text="for each of the top 15 python packages on pypi",
            hold=hold,
            deadline_seconds=0.2,
        )
        await _settle(hold, seconds=0.6)
        assert len(memory.stored) == 1
        outcome = memory.stored[0].outcomes[0]
        assert outcome["success"] is False
        # AD-1166 renders ``complete`` separately from ``success``; a run that
        # was abandoned did not complete, and recording otherwise contradicts
        # the reflection stored beside it.
        assert outcome["complete"] is False
        assert "stopped before finishing" in memory.stored[0].reflection
    finally:
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_late_landing_run_still_delivers_its_result() -> None:
    """The unconfirmed notice is interim, not final.

    A run that refuses the cancel may still finish and still hold the answer
    the Captain asked for. Reporting "it has yet to answer" and then walking
    away would throw that away and leave the row open for good.
    """
    import probos.cognitive.turn_promotion as tp

    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    release = asyncio.Event()

    async def _lands_late() -> str:
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                if release.is_set():
                    return "fifteen packages, all resolved"
                continue

    original_grace = tp._ABANDON_GRACE_SECONDS
    tp._ABANDON_GRACE_SECONDS = 0.05
    try:
        await _promote(
            _lands_late, store=store, threads=threads, deadline=0.2, hold=hold
        )
        await _settle(hold, seconds=0.6)
        assert [m["body"] for m in threads.appended] == [
            _REPORT_ABANDON_UNCONFIRMED
        ]
        assert [t[1] for t in store.transitions] == ["in_progress"]

        # The run lands after the notice.
        release.set()
        run_task = next(t for t in hold if t.get_name().startswith("ad1165-turn"))
        run_task.cancel()
        await _settle(hold, seconds=0.6)

        assert [m["body"] for m in threads.appended] == [
            _REPORT_ABANDON_UNCONFIRMED,
            "fifteen packages, all resolved",
        ]
        assert store.transitions[-1][1] == "done"
    finally:
        tp._ABANDON_GRACE_SECONDS = original_grace
        release.set()
        await _teardown(hold)


# ── the real concurrency consumer ─────────────────────────────────


def _real_manager(*, max_concurrent: int, queue_max_size: int):
    from probos.cognitive.concurrency_manager import ConcurrencyManager

    return ConcurrencyManager(
        agent_id="agent-ezri",
        max_concurrent=max_concurrent,
        queue_max_size=queue_max_size,
    )


@pytest.mark.asyncio
async def test_a_refused_slot_does_not_cost_the_captain_the_report() -> None:
    """The real manager raises at ADMISSION, past the guard on construction.

    ``ConcurrencyManager.acquire`` raises ``ValueError`` when its queue is full
    — from inside ``__aenter__``. Guarding only the ``slot()`` call left that
    raise to kill the reporter outright.
    """
    manager = _real_manager(max_concurrent=1, queue_max_size=0)
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    blocker = asyncio.Event()

    async def _occupy() -> None:
        async with manager.slot("other", 5):
            await blocker.wait()

    occupier = asyncio.create_task(_occupy())
    await asyncio.sleep(0.05)
    assert manager.at_capacity

    try:
        await _promote(
            _never,
            store=store,
            threads=threads,
            deadline=0.2,
            hold=hold,
            background_slot=lambda: manager.slot("direct_message_promoted", 4),
        )
        await _settle(hold, seconds=0.8)
        assert [m["body"] for m in threads.appended] == [_REPORT_ABANDONED]
        assert store.transitions[-1][1] == "failed"
    finally:
        blocker.set()
        await asyncio.gather(occupier, return_exceptions=True)
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_report_is_not_held_behind_capacity_another_run_owns() -> None:
    """Queued capacity is somebody else's to release.

    Cancelling *this* run frees nothing, so a stuck holder would keep the
    Captain's report hostage even after the deadline had done its job.
    """
    manager = _real_manager(max_concurrent=1, queue_max_size=10)
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    blocker = asyncio.Event()

    async def _occupy() -> None:
        async with manager.slot("other", 5):
            await blocker.wait()

    occupier = asyncio.create_task(_occupy())
    await asyncio.sleep(0.05)
    assert manager.at_capacity

    try:
        await _promote(
            _never,
            store=store,
            threads=threads,
            deadline=0.2,
            hold=hold,
            background_slot=lambda: manager.slot("direct_message_promoted", 4),
        )
        # The unrelated holder is STILL holding. The report must land anyway.
        await _settle(hold, seconds=0.9)
        assert manager.at_capacity
        assert [m["body"] for m in threads.appended] == [_REPORT_ABANDONED]
        assert store.transitions[-1][1] == "failed"
    finally:
        blocker.set()
        await asyncio.gather(occupier, return_exceptions=True)
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_slot_is_still_held_while_the_run_is_alive() -> None:
    """BF-732's property, unchanged: a live run is accounted for.

    The escape above must not become "never bother acquiring".
    """
    manager = _real_manager(max_concurrent=2, queue_max_size=10)
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    started = asyncio.Event()
    finish = asyncio.Event()

    async def _work() -> str:
        started.set()
        await finish.wait()
        return "done at last"

    try:
        await _promote(
            _work,
            store=store,
            threads=threads,
            deadline=30.0,
            hold=hold,
            background_slot=lambda: manager.slot("direct_message_promoted", 4),
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        await asyncio.sleep(0.1)
        assert manager.active_count == 1

        finish.set()
        await _settle(hold, seconds=0.4)
        assert manager.active_count == 0
        assert [m["body"] for m in threads.appended] == ["done at last"]
    finally:
        finish.set()
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_reporter_cancelled_while_queued_retrieves_a_late_failure(
    caplog,
) -> None:
    """Cancelling is a request; the run's cleanup can still raise afterwards.

    With nobody left awaiting it, that exception surfaces as an untraceable
    "Task exception was never retrieved" at collection time.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    started = asyncio.Event()
    admit = asyncio.Event()

    async def _explodes_on_cleanup() -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("cleanup exploded") from None
        return "unreachable"

    try:
        with caplog.at_level(
            logging.WARNING, logger="probos.cognitive.turn_promotion"
        ):
            await _promote(
                _explodes_on_cleanup,
                store=store,
                threads=threads,
                deadline=60.0,
                hold=hold,
                background_slot=lambda: _BlockingSlot(admit),
            )
            await asyncio.wait_for(started.wait(), timeout=2.0)
            run_task = next(
                t for t in hold if t.get_name().startswith("ad1165-turn")
            )
            reporter = next(
                t for t in hold if t.get_name().startswith("ad1165-report")
            )
            await asyncio.sleep(0.05)
            reporter.cancel()
            await asyncio.gather(reporter, return_exceptions=True)
            await asyncio.wait_for(
                asyncio.gather(run_task, return_exceptions=True), timeout=5.0
            )
            await asyncio.sleep(0.05)

        assert isinstance(run_task.exception(), RuntimeError)
        messages = [r.getMessage() for r in caplog.records]
        assert any("raised while unwinding" in m for m in messages), messages
    finally:
        admit.set()
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_result_produced_during_the_grace_is_delivered() -> None:
    """A run can catch the cancel, wrap up, and return the real answer.

    Treating "it reached the done set" as "it was stopped" threw that answer
    away and marked the board ``failed`` for work that had succeeded. Also
    covers a natural completion racing the deadline by a hair.
    """
    import probos.cognitive.turn_promotion as tp

    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()

    async def _wraps_up_on_cancel() -> str:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            return "the fifteen packages, resolved"
        return "unreachable"

    original_grace = tp._ABANDON_GRACE_SECONDS
    tp._ABANDON_GRACE_SECONDS = 2.0
    try:
        await _promote(
            _wraps_up_on_cancel,
            store=store,
            threads=threads,
            deadline=0.2,
            hold=hold,
        )
        await _settle(hold, seconds=0.8)
        assert [m["body"] for m in threads.appended] == [
            "the fifteen packages, resolved"
        ]
        assert store.transitions[-1][1] == "done"
    finally:
        tp._ABANDON_GRACE_SECONDS = original_grace
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_failure_during_the_grace_is_still_an_abandonment() -> None:
    """The carve-out above is for SUCCESS only.

    A run that raises while unwinding produced no answer, so reporting it as a
    completion would be the same false claim in the other direction.
    """
    import probos.cognitive.turn_promotion as tp

    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()

    async def _raises_on_cancel() -> str:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise RuntimeError("cleanup exploded") from None
        return "unreachable"

    original_grace = tp._ABANDON_GRACE_SECONDS
    tp._ABANDON_GRACE_SECONDS = 2.0
    try:
        await _promote(
            _raises_on_cancel, store=store, threads=threads, deadline=0.2, hold=hold
        )
        await _settle(hold, seconds=0.8)
        assert [m["body"] for m in threads.appended] == [_REPORT_ABANDONED]
        assert store.transitions[-1][1] == "failed"
    finally:
        tp._ABANDON_GRACE_SECONDS = original_grace
        await _teardown(hold)


@pytest.mark.asyncio
async def test_a_cancelled_waiter_hands_back_a_slot_it_was_just_promoted_into(
) -> None:
    """``release`` promotes into ``_active`` and THEN resolves the waiter.

    A cancellation arriving in that window used to strand the slot: the
    promotion had landed, and the only handle that could give it back was the
    value the waiter's ``await`` never returned. BF-733 makes the reporter
    cancel a queued acquire routinely, so this stopped being theoretical.
    """
    manager = _real_manager(max_concurrent=1, queue_max_size=10)
    occupying = await manager.acquire("other", 5)

    waiter = asyncio.create_task(manager.acquire("direct_message_promoted", 4))
    await asyncio.sleep(0.05)
    assert manager.queue_depth == 1

    # Promote the waiter, then cancel it before it can resume and take
    # ownership of the thread id it was just handed.
    await manager.release(occupying)
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    await asyncio.sleep(0.05)

    assert waiter.cancelled()
    assert manager.active_count == 0, manager.snapshot()
    assert manager.queue_depth == 0

    # The ceiling is intact: a fresh caller can still take the slot.
    fresh = await asyncio.wait_for(manager.acquire("after", 5), timeout=2.0)
    assert manager.active_count == 1
    await manager.release(fresh)


@pytest.mark.asyncio
async def test_a_run_that_refuses_to_stop_stays_accounted_for() -> None:
    """A run that ignores its cancellation is still executing.

    Treating the watchdog's verdict as "the run settled" released the reporter
    from the capacity queue and let fresh work be admitted alongside a run that
    was still holding LLM capacity and sockets -- which is exactly what BF-732's
    slot exists to prevent.
    """
    import probos.cognitive.turn_promotion as tp

    manager = _real_manager(max_concurrent=1, queue_max_size=10)
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    release = asyncio.Event()

    original_grace = tp._ABANDON_GRACE_SECONDS
    tp._ABANDON_GRACE_SECONDS = 0.05
    try:
        await _promote(
            _stubborn_run(release),
            store=store,
            threads=threads,
            deadline=0.2,
            hold=hold,
            background_slot=lambda: manager.slot("direct_message_promoted", 4),
        )
        await _settle(hold, seconds=0.8)

        # The interim notice landed -- it is not gated on capacity.
        assert [m["body"] for m in threads.appended] == [
            _REPORT_ABANDON_UNCONFIRMED
        ]
        # ...and the still-running run is still counted.
        assert manager.active_count == 1, manager.snapshot()

        release.set()
        run_task = next(t for t in hold if t.get_name().startswith("ad1165-turn"))
        run_task.cancel()
        await _settle(hold, seconds=0.5)
        assert manager.active_count == 0, manager.snapshot()
    finally:
        tp._ABANDON_GRACE_SECONDS = original_grace
        release.set()
        await _teardown(hold)


@pytest.mark.asyncio
async def test_cancelled_waiters_do_not_fill_the_queue_against_live_callers() -> None:
    """A cancelled queued acquire left a tombstone counted against the cap.

    BF-733 makes the reporter cancel a queued acquire routinely, so a queue of
    tombstones would raise on an ordinary caller -- which the conversational
    path renders to the Captain as no response at all.
    """
    manager = _real_manager(max_concurrent=1, queue_max_size=2)
    occupying = await manager.acquire("other", 5)

    doomed = [
        asyncio.create_task(manager.acquire(f"promoted-{i}", 4)) for i in range(2)
    ]
    await asyncio.sleep(0.05)
    assert manager.queue_depth == 2

    for task in doomed:
        task.cancel()
    await asyncio.gather(*doomed, return_exceptions=True)
    await asyncio.sleep(0.05)

    # A live caller must be able to queue rather than be shed.
    live = asyncio.create_task(manager.acquire("ordinary", 5))
    await asyncio.sleep(0.05)
    assert not live.done() or live.exception() is None

    await manager.release(occupying)
    thread_id = await asyncio.wait_for(live, timeout=2.0)
    assert manager.active_count == 1
    await manager.release(thread_id)


@pytest.mark.asyncio
async def test_the_interim_notice_is_not_gated_on_capacity() -> None:
    """The notice comes from the watchdog, never from the queued reporter.

    A stubborn run's reporter waits for a slot for as long as that run lives
    (see the test above), so posting the notice from there would make the
    Captain's promise wait on capacity an unrelated run is holding -- the exact
    defect this BF exists to close, reintroduced one layer in.
    """
    import probos.cognitive.turn_promotion as tp

    manager = _real_manager(max_concurrent=1, queue_max_size=10)
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    release = asyncio.Event()
    blocker = asyncio.Event()

    async def _occupy() -> None:
        async with manager.slot("other", 5):
            await blocker.wait()

    occupier = asyncio.create_task(_occupy())
    await asyncio.sleep(0.05)
    assert manager.at_capacity

    original_grace = tp._ABANDON_GRACE_SECONDS
    tp._ABANDON_GRACE_SECONDS = 0.05
    try:
        await _promote(
            _stubborn_run(release),
            store=store,
            threads=threads,
            deadline=0.2,
            hold=hold,
            background_slot=lambda: manager.slot("direct_message_promoted", 4),
        )
        await _settle(hold, seconds=0.8)

        # Still no capacity, and the reporter is still queued for it.
        assert manager.at_capacity
        assert manager.queue_depth == 1
        # The Captain has been told anyway.
        assert [m["body"] for m in threads.appended] == [
            _REPORT_ABANDON_UNCONFIRMED
        ]

        # And when capacity frees, the reporter TAKES the slot -- the stubborn
        # run is still executing, so the accounting BF-732 exists for still
        # applies to it. Discharging on the watchdog's verdict instead would
        # have abandoned the queue and let fresh work in beside a live run.
        blocker.set()
        await asyncio.gather(occupier, return_exceptions=True)
        await asyncio.sleep(0.15)
        assert manager.active_count == 1, manager.snapshot()
        assert [m["body"] for m in threads.appended] == [
            _REPORT_ABANDON_UNCONFIRMED
        ]
    finally:
        tp._ABANDON_GRACE_SECONDS = original_grace
        release.set()
        blocker.set()
        await asyncio.gather(occupier, return_exceptions=True)
        await _teardown(hold)


# ── what must not change ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_run_finishing_inside_the_deadline_is_unchanged() -> None:
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()

    async def _work() -> str:
        await asyncio.sleep(0.05)
        return "fifteen packages, all resolved"

    try:
        await _promote(_work, store=store, threads=threads, deadline=5.0, hold=hold)
        await _settle(hold, seconds=0.4)
        assert [m["body"] for m in threads.appended] == [
            "fifteen packages, all resolved"
        ]
        assert store.transitions[-1][1] == "done"
    finally:
        await _teardown(hold)


@pytest.mark.asyncio
async def test_zero_deadline_restores_the_unbounded_wait() -> None:
    """The escape hatch, pinned. An operator turning this off gets the old wait.

    Asserting the ABSENCE of a report is the point: without this, a later change
    that made the deadline unconditional would silently remove the opt-out.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    try:
        await _promote(_never, store=store, threads=threads, deadline=0.0, hold=hold)
        await _settle(hold, seconds=0.4)
        assert threads.appended == []
        assert [t[1] for t in store.transitions] == ["in_progress"]
    finally:
        await _teardown(hold)


@pytest.mark.asyncio
async def test_the_probes_are_not_consulted_for_an_abandoned_run() -> None:
    """Both probes describe a run that RETURNED. An abandoned one did not.

    ``completed_probe`` reads the last pass's ``stopped_reason`` and would read
    a stale one here -- a value from a pass that finished minutes before the run
    stalled -- and a truthy answer would close the item ``done``.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    calls: list[str] = []

    def _completed() -> bool:
        calls.append("completed")
        return True

    def _failures():
        calls.append("failures")
        return None

    try:
        await _promote(
            _never,
            store=store,
            threads=threads,
            deadline=0.2,
            hold=hold,
            completed_probe=_completed,
            failures_probe=_failures,
        )
        await _settle(hold, seconds=0.6)
        assert calls == []
        assert store.transitions[-1][1] == "failed"
    finally:
        await _teardown(hold)


@pytest.mark.asyncio
async def test_cancelling_the_reporter_still_cancels_the_run() -> None:
    """``asyncio.wait`` does not propagate cancellation; ``await task`` did.

    AD-1165's cancellation branch is written against a run that dies with its
    reporter (agent recycled, loop shutting down) and leaves the row
    ``in_progress``. Bounding the wait must not quietly turn that into an
    orphaned run.
    """
    store, threads = _FakeWorkItemStore(), _FakeThreadStore()
    hold: set = set()
    started = asyncio.Event()

    async def _work() -> str:
        started.set()
        await asyncio.Event().wait()
        return "unreachable"

    await _promote(_work, store=store, threads=threads, deadline=30.0, hold=hold)
    await asyncio.wait_for(started.wait(), timeout=2.0)

    run_task = next(t for t in hold if t.get_name().startswith("ad1165-turn"))
    reporter = next(t for t in hold if t.get_name().startswith("ad1165-report"))
    # The reporter has been CREATED but not yet scheduled. Cancelling it here
    # would kill it before it ever entered the wait, which tests nothing about
    # the wait's cancellation semantics.
    for _ in range(50):
        if not reporter.done() and reporter.get_coro().cr_await is not None:
            break
        await asyncio.sleep(0.01)

    reporter.cancel()
    await asyncio.gather(reporter, return_exceptions=True)
    await asyncio.wait_for(
        asyncio.gather(run_task, return_exceptions=True), timeout=5.0
    )

    assert run_task.cancelled()
    assert threads.appended == []
    assert [t[1] for t in store.transitions] == ["in_progress"]


# ── wording and configuration ─────────────────────────────────────


def test_every_report_wording_is_clean_against_the_real_gap_regex() -> None:
    """A report tripping ``_CAPABILITY_GAP_RE`` routes into self-modification.

    Imports the real predicate rather than re-stating the pattern, so a change
    to the regex is caught here instead of in production.
    """
    for text in (
        _ACK_TEMPLATE.format(work_item_id="ccabc4818bd1"),
        _REPORT_EMPTY,
        _REPORT_FAILED,
        _REPORT_ABANDONED,
        _REPORT_ABANDON_UNCONFIRMED,
    ):
        assert not is_capability_gap(text), text


def test_the_deadline_is_a_real_config_field_and_is_armed_by_default() -> None:
    """``getattr`` with a default would hide a field that does not exist.

    Armed by default on purpose: the deadline only bites once promotion is
    already enabled, and a backstop nobody switches on is indistinguishable
    from one that was never built.
    """
    assert "promoted_run_deadline_seconds" in DmAgenticConfig.model_fields
    assert DmAgenticConfig().promoted_run_deadline_seconds > 0.0


def test_the_default_deadline_is_an_explicit_operator_cutoff() -> None:
    """Pinned as a value, not justified as a computed ceiling.

    ``max_iterations`` (up to 25) times the shipped standard-tier timeout
    (300s) already exceeds this before tool time is counted, so it cannot be
    claimed to leave room for every legitimate run. It is a cutoff the operator
    chooses, and the config description says so; this pins the shipped value so
    a silent change to it has to be deliberate.
    """
    assert DmAgenticConfig().promoted_run_deadline_seconds == 1800.0


def test_the_agent_passes_the_deadline_at_the_promotion_call_site() -> None:
    """Everything above is inert unless the one production caller supplies it.

    Read from the AST rather than by substring: a text scan cannot tell a live
    keyword from the same words inside a comment or a docstring, and reaching
    the real call site needs a full DM turn ~1,600 lines into the handler.
    """
    import ast
    import inspect

    from probos.cognitive import cognitive_agent

    tree = ast.parse(inspect.getsource(cognitive_agent))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_with_promotion"
    ]
    assert calls, "found no run_with_promotion call at all — rewrite this scan"

    for call in calls:
        keywords = {kw.arg: kw.value for kw in call.keywords}
        assert "deadline_seconds" in keywords, ast.dump(call)
        # The value has to come from the config field, not a literal: a
        # hard-coded number here would be a second place to leave misconfigured.
        names = {
            node.value
            for node in ast.walk(keywords["deadline_seconds"])
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert "promoted_run_deadline_seconds" in names, ast.dump(
            keywords["deadline_seconds"]
        )
