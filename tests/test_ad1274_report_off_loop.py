"""AD-1274 / BF-826 slice A: the promoted report leaves the loop, and says so.

Measured at HEAD before this change, against the REAL ``ChatThreadStore`` with
its write lock held past the busy timeout: the post took 7.39s on the event
loop, a 50ms heartbeat recorded a **7890ms** gap (63ms uncontended), the call
returned its body exactly as it does on success, and the database held only the
warm-up row. Two defects in one line -- a loop stall and a silent loss.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from probos.events import EventType
from probos.cognitive.turn_promotion import (
    _ABANDON_GRACE_SECONDS,
    _REPORT_ABANDON_UNCONFIRMED,
    _PromotedRunSupervisor,
    _post_report,
    ReportDelivery,
)
from probos.runtime import ProbOSRuntime
from probos.threads import ChatThreadStore


class _ImpatientStore(ChatThreadStore):
    """The real store, but it gives up on a held lock in 200ms not 5s.

    Every other byte of the write path is production code -- the same
    ``BEGIN IMMEDIATE``, the same exact-match check, the same commit callback.
    Only the busy timeout is shortened, so a test can reach the past-the-timeout
    branch in under a second instead of the ~20s the real 5s default needs on
    Windows (measured: a 7s hold did NOT defeat it; the post simply waited).
    """

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None, timeout=0.2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


class _EmitHarness:
    """The REAL runtime emit methods bound onto a minimal object.

    Constructing a whole ``ProbOSRuntime`` would drag in the entire boot; what
    these tests need is exactly the dispatch code under test, unmodified.
    """

    _emit_from_any_thread = ProbOSRuntime._emit_from_any_thread
    emit_event = ProbOSRuntime.emit_event
    _emit_event = ProbOSRuntime._emit_event
    _emit_event_local = ProbOSRuntime._emit_event_local

    def __init__(self, store=None, dispatch_loop=None) -> None:
        self._event_listeners: list = []
        self._live_event_listeners: list = []
        self._event_listener_tasks: set = set()
        self._dispatch_loop = dispatch_loop
        self.nats_bus = None
        self.chat_thread_store = store
        self.work_item_store = None

    def _check_night_order_escalation(self, *_a, **_k) -> None:
        return None


def _lock_holder(db_path, *, thread_id: str, release, holding, timeout: float):
    """Hold an EXCLUSIVE write lock, as a competing writer would.

    The caller controls the release through ``release`` rather than a fixed
    sleep, because SQLite's busy timeout is not the wall clock: measured on
    this tree, a 0.2s ``timeout=`` waits far longer, and a 7s hold did not
    defeat the 5s default at all. Racing a sleep against it makes the test
    decide by timing luck.

    ``holding`` is set once the lock is actually taken, so a test can assert
    its own premise instead of sleeping and hoping.
    """
    started_fail: list[BaseException] = []

    def _run():
        try:
            conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=60)
            conn.execute("BEGIN EXCLUSIVE")
            conn.execute(
                "INSERT INTO chat_thread_messages "
                "(id, thread_id, author_id, role, body, created_at, metadata) "
                "VALUES (?,?,?,?,?,?,?)",
                ("warmup", thread_id, "agent-1", "agent", "warm", 1.0, "{}"),
            )
        except BaseException as exc:  # pragma: no cover - premise failure
            started_fail.append(exc)
            holding.set()
            return
        holding.set()
        release.wait(timeout)
        conn.execute("COMMIT")
        conn.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t, started_fail


# ── 1. the headline: the loop keeps running, the report lands once ──────────


@pytest.mark.asyncio
async def test_the_loop_keeps_its_schedule_while_the_report_is_in_flight(
    tmp_path,
) -> None:
    """The issue's acceptance, against the real store under real contention.

    Both premises are asserted, because either one failing makes this pass
    trivially: the heartbeat must have actually ticked through the post, and
    the post must actually have been delayed by the lock. A post that returned
    instantly proves nothing about a stall it never met.
    """
    db = tmp_path / "chat_threads.db"
    store = ChatThreadStore(db_path=db)
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])

    gaps: list[float] = []
    stop = threading.Event()

    async def heartbeat() -> None:
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.05)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    hb = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.15)

    release = threading.Event()
    holding = threading.Event()
    holder, holder_failed = _lock_holder(
        db, thread_id=thread.id, release=release, holding=holding, timeout=30,
    )
    assert holding.wait(timeout=10), "the competing writer never took the lock"
    assert not holder_failed, f"the lock holder failed: {holder_failed!r}"

    # Released from a separate thread WHILE the post is in flight, so the post
    # genuinely waits on a held lock and then genuinely succeeds.
    threading.Timer(1.0, release.set).start()

    started = time.monotonic()
    outcome = await _post_report(
        runtime=SimpleNamespace(chat_thread_store=store),
        agent_id="agent-1",
        thread_id=thread.id,
        work_item_id="wi-1",
        body="THE REPORT BODY",
    )
    post_elapsed = time.monotonic() - started

    await asyncio.sleep(0.1)
    stop.set()
    hb.cancel()
    with pytest.raises(asyncio.CancelledError):
        await hb
    release.set()
    holder.join(timeout=30)

    # Premise 1: the post really was delayed by the lock. Without this, a post
    # that never contended would satisfy every assertion below.
    assert post_elapsed > 0.7, (
        f"the post finished in {post_elapsed:.2f}s, so it never met the lock "
        "and this test proves nothing about a stall"
    )
    # Premise 2: the heartbeat really ran, on both sides of the post.
    assert len(gaps) >= 12, f"the heartbeat only ticked {len(gaps)} times"

    assert max(gaps) < 0.35, (
        f"the loop stalled for {max(gaps) * 1000:.0f}ms while the report was "
        "in flight; the write is back on the event loop"
    )
    assert outcome.delivered is True
    bodies = [m.body for m in store.list_messages(thread.id, limit=50)]
    assert bodies.count("THE REPORT BODY") == 1


# ── 2. the AD-1133 emit survives the worker thread ─────────────────────────


@pytest.mark.asyncio
async def test_a_coroutine_listener_still_sees_an_append_made_off_the_loop(
    tmp_path,
) -> None:
    """The whole seam: post -> executor -> store commit -> emit -> listener.

    Measured before ``_emit_from_any_thread`` existed: from a worker thread a
    *sync* listener ran and a *coroutine* listener was lost to a swallowed
    ``RuntimeError: no running event loop``. The HXI live-refresh listener
    returns an awaitable, so it was in the lost set -- moving the write off the
    loop without this hop would have traded a stall for a dead transcript.
    """
    store = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])

    harness = _EmitHarness(store, dispatch_loop=asyncio.get_running_loop())
    store.set_message_committed_callback(
        lambda message: harness._emit_from_any_thread(
            EventType.CHAT_THREAD_MESSAGE_APPENDED,
            {"thread_id": message.thread_id, "message_id": message.id},
        )
    )

    seen: list[dict] = []
    threads_seen: list[str] = []
    loop_thread_name = threading.current_thread().name

    async def coroutine_listener(event: dict) -> None:
        threads_seen.append(threading.current_thread().name)
        seen.append(event)

    harness._event_listeners.append((coroutine_listener, None))

    outcome = await _post_report(
        runtime=harness,
        agent_id="agent-1",
        thread_id=thread.id,
        work_item_id="wi-1",
        body="live refresh me",
    )
    assert outcome.delivered is True

    for _ in range(50):
        if seen:
            break
        await asyncio.sleep(0.02)

    assert seen, (
        "the coroutine listener never ran; the commit callback fired on a "
        "worker thread and the emit was lost, which is the AD-1133 regression"
    )
    assert threads_seen == [loop_thread_name], (
        f"the listener ran on {threads_seen}, not the loop thread "
        f"{loop_thread_name!r}"
    )
    assert seen[0]["data"]["thread_id"] == thread.id


@pytest.mark.asyncio
async def test_the_control_a_sync_listener_was_never_the_one_at_risk(
    tmp_path,
) -> None:
    """The discriminating control for the test above.

    A *sync* listener survived the worker thread even before this change, so a
    test that only asserted "some listener ran" could not tell a repaired emit
    from the defect. This pins which half was broken.
    """
    store = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])
    harness = _EmitHarness(store, dispatch_loop=asyncio.get_running_loop())

    ran_on: list[str] = []
    harness._event_listeners.append((lambda event: ran_on.append(
        threading.current_thread().name), None))
    store.set_message_committed_callback(
        lambda message: harness._emit_from_any_thread(
            EventType.CHAT_THREAD_MESSAGE_APPENDED, {"thread_id": message.thread_id},
        )
    )

    await _post_report(
        runtime=harness, agent_id="agent-1", thread_id=thread.id,
        work_item_id="wi-1", body="sync",
    )
    for _ in range(50):
        if ran_on:
            break
        await asyncio.sleep(0.02)
    assert ran_on == [threading.current_thread().name]


# ── 3. no captured loop degrades, and does not raise ───────────────────────


@pytest.mark.asyncio
async def test_an_emit_with_no_dispatch_loop_warns_and_does_not_raise(
    tmp_path, caplog,
) -> None:
    """A notification that cannot be scheduled must not fail the store write."""
    store = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])

    harness = _EmitHarness(store, dispatch_loop=None)
    ran: list[str] = []
    harness._event_listeners.append((lambda event: ran.append("sync"), None))
    store.set_message_committed_callback(
        lambda message: harness._emit_from_any_thread(
            EventType.CHAT_THREAD_MESSAGE_APPENDED, {"thread_id": message.thread_id},
        )
    )

    with caplog.at_level(logging.WARNING, logger="probos.runtime"):
        outcome = await _post_report(
            runtime=harness, agent_id="agent-1", thread_id=thread.id,
            work_item_id="wi-1", body="no loop captured",
        )

    assert outcome.delivered is True, "the store write must still commit"
    assert [m.body for m in store.list_messages(thread.id)] == ["no loop captured"]
    assert any("no live dispatch loop" in r.getMessage() for r in caplog.records), (
        "the degradation must be visible; a silently dropped coroutine "
        "listener is the defect this hop exists to close"
    )
    # Degrades to inline dispatch rather than dropping the event: that is what
    # every caller did before the hop existed, so a synchronous listener on a
    # loopless thread keeps working.
    assert ran == ["sync"]


# ── 4. exactly-once across a retry ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_retry_after_a_committed_write_leaves_exactly_one_row(
    tmp_path, monkeypatch,
) -> None:
    """The hardest case, and the reason the id is minted once.

    Attempt 1 commits and *then* fails, so its acknowledgement is lost. A retry
    that minted a fresh id would post the Captain the same report twice.
    """
    import probos.cognitive.turn_promotion as tp

    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (0.01,))

    attempts: list[str] = []

    class _LosesTheAck(ChatThreadStore):
        def append_message_once(self, thread_id, **kwargs):
            attempts.append(kwargs["message_id"])
            result = super().append_message_once(thread_id, **kwargs)
            if len(attempts) == 1:
                raise sqlite3.OperationalError("database is locked")
            return result

    store = _LosesTheAck(db_path=tmp_path / "chat_threads.db")
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])

    outcome = await _post_report(
        runtime=SimpleNamespace(chat_thread_store=store),
        agent_id="agent-1", thread_id=thread.id, work_item_id="wi-1",
        body="exactly once please",
    )

    assert len(attempts) == 2, f"expected one retry, saw {len(attempts)} attempts"
    assert len(set(attempts)) == 1, (
        "the retry minted a NEW message_id; the exact-match check cannot "
        "recognise the row that already committed and the Captain sees it twice"
    )
    assert outcome.delivered is True
    bodies = [m.body for m in store.list_messages(thread.id, limit=50)]
    assert bodies.count("exactly once please") == 1


# ── 5. a rejection is not a retry ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_rejected_message_is_attempted_exactly_once(tmp_path) -> None:
    """``ValueError`` from the store's validation is a verdict, not congestion."""
    attempts: list[int] = []

    class _Counting(ChatThreadStore):
        def append_message_once(self, thread_id, **kwargs):
            attempts.append(1)
            return super().append_message_once(thread_id, **kwargs)

    store = _Counting(db_path=tmp_path / "chat_threads.db")
    store.create_thread(title="t", participants=["captain", "agent-1"])

    outcome = await _post_report(
        runtime=SimpleNamespace(chat_thread_store=store),
        agent_id="agent-1",
        thread_id="",  # fails the store's id validation
        work_item_id="wi-1",
        body="rejected",
    )
    assert len(attempts) == 1, (
        f"a rejection was retried {len(attempts)} times; the bound is spent on "
        "an answer that cannot change"
    )
    assert outcome.delivered is False
    assert outcome.reason == "rejected"


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_the_stated_number_of_times(
    tmp_path, monkeypatch,
) -> None:
    """The control for the test above: a transient failure DOES consume the bound.

    Without this, "attempted once" would also pass against code that never
    retried anything.
    """
    import probos.cognitive.turn_promotion as tp

    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (0.01,))
    attempts: list[int] = []

    class _AlwaysBusy(ChatThreadStore):
        def append_message_once(self, thread_id, **kwargs):
            attempts.append(1)
            raise sqlite3.OperationalError("database is locked")

    store = _AlwaysBusy(db_path=tmp_path / "chat_threads.db")
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])

    outcome = await _post_report(
        runtime=SimpleNamespace(chat_thread_store=store),
        agent_id="agent-1", thread_id=thread.id, work_item_id="wi-1",
        body="busy",
    )
    # The literal, not the constant. Asserting against
    # ``tp._REPORT_DELIVERY_ATTEMPTS`` would pass for ANY bound, including a
    # silent collapse to one attempt -- and the docstring states three.
    assert tp._REPORT_DELIVERY_ATTEMPTS == 3, (
        "the retry bound changed; _post_report's docstring states 3 attempts "
        "and roughly 16s, and both must move together"
    )
    assert len(attempts) == 3
    assert outcome.delivered is False
    assert outcome.reason == "exhausted"


@pytest.mark.asyncio
async def test_a_cancelled_turn_still_leaves_its_report_durably_pending(
    tmp_path, monkeypatch,
) -> None:
    """The one path that used to lose the report outright.

    A shutdown or recycle landing BETWEEN two attempts unwound through the
    cancellation arm, which re-raised immediately and never queued. Measured by
    review: zero pending rows. That is precisely the failure this AD exists to
    end, arriving through the only branch that skipped the durable queue.

    The control is the enqueue itself: if nothing were ever queued on ANY path
    the assertion below would also pass against a no-op outbox, so the test
    asserts the row's identity -- same work item, same body -- not merely that
    something was written.
    """
    import probos.cognitive.turn_promotion as tp

    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (5.0,))
    started = asyncio.Event()

    class _BusyThenCancelled(ChatThreadStore):
        def append_message_once(self, thread_id, **kwargs):
            started.set()
            raise sqlite3.OperationalError("database is locked")

    store = _BusyThenCancelled(db_path=tmp_path / "chat_threads.db")
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])

    queued: list[dict] = []

    class _Outbox:
        async def enqueue_promoted_report(self, **kwargs):
            queued.append(kwargs)

    runtime = SimpleNamespace(chat_thread_store=store, work_item_store=_Outbox())

    task = asyncio.create_task(_post_report(
        runtime=runtime, agent_id="agent-1", thread_id=thread.id,
        work_item_id="wi-cancelled", body="the report nobody waited for",
    ))
    await asyncio.wait_for(started.wait(), timeout=5.0)
    # Now inside the 5s backoff, which is where a shutdown lands.
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(queued) == 1, "a cancelled turn must not drop the report"
    assert queued[0]["work_item_id"] == "wi-cancelled"
    assert queued[0]["body"] == "the report nobody waited for"


@pytest.mark.asyncio
async def test_a_cancellation_during_the_write_itself_also_queues(
    tmp_path,
) -> None:
    """The OTHER cancellable await, and it has its own handler.

    Mutation found this gap: disabling the queue call in the write arm left
    every test green, because the sibling test cancels during the BACKOFF. The
    two awaits fail independently -- a cancellation can land while the worker
    thread is still inside the store -- so each needs its own proof.

    `to_thread` does not cancel the worker; the await simply raises while the
    thread runs on. That is exactly the production shape during shutdown.
    """
    started = threading.Event()
    release = threading.Event()

    class _BlockingStore(ChatThreadStore):
        def append_message_once(self, thread_id, **kwargs):
            started.set()
            release.wait(timeout=10.0)
            raise sqlite3.OperationalError("database is locked")

    store = _BlockingStore(db_path=tmp_path / "chat_threads.db")
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])

    queued: list[dict] = []

    class _Outbox:
        async def enqueue_promoted_report(self, **kwargs):
            queued.append(kwargs)

    runtime = SimpleNamespace(chat_thread_store=store, work_item_store=_Outbox())

    task = asyncio.create_task(_post_report(
        runtime=runtime, agent_id="agent-1", thread_id=thread.id,
        work_item_id="wi-mid-write", body="cancelled mid-write",
    ))
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, started.wait, 5.0,
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()

    assert len(queued) == 1, (
        "a cancellation landing during the write must queue the report too"
    )
    assert queued[0]["work_item_id"] == "wi-mid-write"


@pytest.mark.asyncio
async def test_a_cancelled_turn_survives_an_outbox_that_will_not_answer(
    tmp_path, monkeypatch,
) -> None:
    """The remedy must not become a hang.

    The cancel-path enqueue is bounded, so an outbox that never returns costs
    the bound and then gives up -- it does not hold a shutting-down vessel
    open. The report is lost in that case, and the log is the only record; that
    is worse than pending and better than a hang, and it is stated as such.
    """
    import probos.cognitive.turn_promotion as tp

    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (5.0,))
    monkeypatch.setattr(tp, "_REPORT_CANCEL_QUEUE_SECONDS", 0.05)
    started = asyncio.Event()

    class _Busy(ChatThreadStore):
        def append_message_once(self, thread_id, **kwargs):
            started.set()
            raise sqlite3.OperationalError("database is locked")

    class _WedgedOutbox:
        async def enqueue_promoted_report(self, **kwargs):
            await asyncio.sleep(30)

    store = _Busy(db_path=tmp_path / "chat_threads.db")
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])
    runtime = SimpleNamespace(
        chat_thread_store=store, work_item_store=_WedgedOutbox(),
    )

    task = asyncio.create_task(_post_report(
        runtime=runtime, agent_id="agent-1", thread_id=thread.id,
        work_item_id="wi-1", body="b",
    ))
    await asyncio.wait_for(started.wait(), timeout=5.0)
    await asyncio.sleep(0.05)
    task.cancel()
    started_at = time.monotonic()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert time.monotonic() - started_at < 5.0, (
        "the cancel-path enqueue must be bounded, or a wedged outbox turns a "
        "cancellation into a hang"
    )


# ── 6. a failed post is distinguishable, and costs the episode nothing ─────


@pytest.mark.asyncio
async def test_a_lost_report_is_distinguishable_and_still_returns_its_body(
    tmp_path, monkeypatch,
) -> None:
    """Real store, real lock, held past a real busy timeout.

    The defect this closes: the old signature returned the composed body
    identically whether the append committed or raised, so nothing downstream
    -- and nobody reading the code -- could tell a delivered report from a lost
    one.
    """
    import probos.cognitive.turn_promotion as tp

    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (0.01,))

    db = tmp_path / "chat_threads.db"
    store = _ImpatientStore(db_path=db)
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])

    release = threading.Event()
    holding = threading.Event()
    holder, holder_failed = _lock_holder(
        db, thread_id=thread.id, release=release, holding=holding, timeout=60,
    )
    assert holding.wait(timeout=10), "the competing writer never took the lock"
    assert not holder_failed, f"the lock holder failed: {holder_failed!r}"

    outcome = await _post_report(
        runtime=SimpleNamespace(chat_thread_store=store),
        agent_id="agent-1", thread_id=thread.id, work_item_id="wi-1",
        body="THE REPORT BODY",
    )
    release.set()
    holder.join(timeout=30)

    assert isinstance(outcome, ReportDelivery)
    assert outcome.delivered is False
    assert outcome.reason == "exhausted"
    # Premise: the lock really did defeat the store, not some other failure.
    assert "THE REPORT BODY" not in [
        m.body for m in store.list_messages(thread.id, limit=50)
    ]
    # AD-1248 survives: the episode and the outcome artifact still receive the
    # composed text. A failed delivery is a fact about the transcript, not
    # about the work.
    assert outcome.body == "THE REPORT BODY"


# ── 7. the watchdog path ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_watchdog_still_stops_the_run_when_its_notice_cannot_land(
    tmp_path, monkeypatch,
) -> None:
    """For a run that refuses its cancel this notice is the ONLY report.

    So the watchdog must attempt it, must survive its failure, and must still
    cancel the run. The positive premise -- that the notice was actually
    attempted -- is asserted, because a watchdog that skipped it entirely would
    otherwise satisfy every other claim here.
    """
    import probos.cognitive.turn_promotion as tp

    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (0.01,))
    monkeypatch.setattr(tp, "_ABANDON_GRACE_SECONDS", 0.05)

    attempted: list[str] = []

    class _AlwaysBusy(ChatThreadStore):
        def append_message_once(self, thread_id, **kwargs):
            attempted.append(kwargs["body"])
            raise sqlite3.OperationalError("database is locked")

    store = _AlwaysBusy(db_path=tmp_path / "chat_threads.db")
    thread = store.create_thread(title="t", participants=["captain", "agent-1"])
    runtime = SimpleNamespace(chat_thread_store=store, work_item_store=None)

    # Releasable on purpose: an unreleasable stubborn run wedges the loop's own
    # teardown and hangs the session, exactly as ``_stubborn_run`` in
    # test_bf733_promoted_run_deadline.py records. Measured here first.
    release = asyncio.Event()

    async def _refuses_to_stop() -> str:
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                if release.is_set():
                    raise
                continue

    run = asyncio.create_task(_refuses_to_stop())
    supervisor = _PromotedRunSupervisor(
        run,
        deadline_seconds=0.1,
        work_item_id="wi-1",
        on_unconfirmed=lambda: tp._post_report(
            runtime=runtime, agent_id="agent-1", thread_id=thread.id,
            work_item_id="wi-1", body=tp._REPORT_ABANDON_UNCONFIRMED,
        ),
    )
    # The release MUST be in a finally. A failing assertion that skips it
    # leaves a task nothing can cancel, and the loop's own teardown
    # (``_cancel_all_tasks``) then inherits the wedge and hangs the whole
    # session instead of reporting the assertion -- measured while writing
    # this test, and the reason ``_stubborn_run`` in
    # test_bf733_promoted_run_deadline.py carries the same warning.
    try:
        supervisor.arm()
        await asyncio.wait_for(supervisor._watch, timeout=10)

        assert attempted == [_REPORT_ABANDON_UNCONFIRMED] * tp._REPORT_DELIVERY_ATTEMPTS, (
            "the interim notice must be attempted, and every attempt must "
            "carry the unconfirmed wording; a watchdog that skips it leaves "
            "the Captain with no report at all for this run"
        )
        assert run.cancelling() > 0, (
            "the watchdog must still have asked the run to stop"
        )
        assert not run.done(), (
            "premise: the run must still be refusing, or this exercised the "
            "clean-unwind branch instead of the unconfirmed one"
        )
    finally:
        release.set()
        run.cancel()
        try:
            await run
        except asyncio.CancelledError:
            pass


# ── 8. the wording is scoped to when it was observed ───────────────────────


def test_the_unconfirmed_notice_is_scoped_to_when_it_was_observed() -> None:
    """Delivery can now lag the observation the notice describes.

    Retry costs up to the stated bound, and a durably pending report waits for
    a drain. An unscoped present-tense "it has yet to answer" would be a claim
    about *now* built from a reading taken some time ago.
    """
    text = _REPORT_ABANDON_UNCONFIRMED
    assert "has yet to answer" not in text, (
        "present tense: this asserts the run is STILL silent at read time, "
        "which the runtime has no evidence for once delivery can lag"
    )
    assert "by the time I checked" in text
    assert "may have landed since" in text
    # The opposite over-correction: hedging so hard the notice stops saying
    # what happened. BF-733's whole point is that it must NOT claim the run
    # was stopped, but it must still report the deadline.
    assert "ran past its time limit" in text
    assert "I stopped it" not in text
