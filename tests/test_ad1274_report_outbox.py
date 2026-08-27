"""AD-1274 / BF-826 slice B: an undeliverable report is durably pending.

Slice A stops the loop stall and makes a failed post visible. It does not make
the report survive. For the BF-733 watchdog's interim notice that gap is the
unrecoverable one -- for a run that refuses its cancellation, the notice is the
only report the Captain will ever get, because the reporter is still waiting on
the run. A lost final report at least leaves a row on the board; a lost interim
notice leaves nothing.

The outbox lives in ``workforce.db``, NOT ``chat_threads.db``. An error path
must not fail the way the thing it reports on failed, and the AD-857 Captain-DM
notifier writes back into the same chat file -- same lock, so no fallback at
all.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from types import SimpleNamespace

import pytest

from probos.cognitive.promoted_report_delivery import (
    PromotedReportDeliveryService,
)
from probos.threads import ChatThreadStore
from probos.workforce import WorkItemStore


class _AlwaysBusy(ChatThreadStore):
    """A thread store whose write always fails, as a held lock does."""

    def append_message_once(self, thread_id, **kwargs):
        raise sqlite3.OperationalError("database is locked")


class _AlwaysRejects(ChatThreadStore):
    """A store that REFUSES the message outright -- permanent, not contention.

    ``append_message_once`` raises ``ValueError`` for a message it will never
    accept. Distinct from ``_AlwaysBusy`` on purpose: the two failures look
    alike from the drainer and must be handled oppositely, and a test that
    conflated them would not notice if one started behaving like the other.
    """

    def append_message_once(self, thread_id, **kwargs):
        raise ValueError("message rejected")


class _ThreadVanished(ChatThreadStore):
    """A store whose target thread no longer exists -- also permanent."""

    def append_message_once(self, thread_id, **kwargs):
        return None


async def _work_store(tmp_path) -> WorkItemStore:
    store = WorkItemStore(db_path=str(tmp_path / "workforce.db"), tick_interval=1000.0)
    await store.start()
    return store


# ── 9. the pending row is durable, and on a different resource ─────────────


@pytest.mark.asyncio
async def test_a_lost_report_becomes_a_pending_row_in_the_other_database(
    tmp_path, monkeypatch,
) -> None:
    import probos.cognitive.turn_promotion as tp

    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (0.01,))

    threads = _AlwaysBusy(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        outcome = await tp._post_report(
            runtime=SimpleNamespace(chat_thread_store=threads, work_item_store=work),
            agent_id="agent-1", thread_id=thread.id, work_item_id="wi-1",
            body="THE REPORT BODY",
        )
        assert outcome.delivered is False
        assert outcome.queued is True

        pending = await work.list_pending_promoted_reports(limit=10)
        assert len(pending) == 1
        assert pending[0].body == "THE REPORT BODY"
        assert pending[0].work_item_id == "wi-1"
        assert pending[0].thread_id == thread.id
        # The id is the one already minted for the failed attempt. If a new one
        # were minted per attempt, redelivery could not be recognised as the
        # same message and the Captain would see the report twice.
        assert pending[0].message_id == outcome.message_id
    finally:
        await work.stop()

    # Readable from a fresh connection to a DIFFERENT file, with the chat store
    # still broken. That separation is the whole point -- if the row lived in
    # chat_threads.db it would have been written through the lock that failed.
    conn = sqlite3.connect(str(tmp_path / "workforce.db"))
    try:
        rows = conn.execute(
            "SELECT message_id, body, delivered FROM promoted_report_outbox"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(outcome.message_id, "THE REPORT BODY", 0)]


@pytest.mark.asyncio
async def test_a_delivered_report_leaves_nothing_pending(
    tmp_path,
) -> None:
    """The control. Without it, "there is a pending row" could just mean every
    post queues one regardless of whether it landed."""
    import probos.cognitive.turn_promotion as tp

    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        outcome = await tp._post_report(
            runtime=SimpleNamespace(chat_thread_store=threads, work_item_store=work),
            agent_id="agent-1", thread_id=thread.id, work_item_id="wi-1",
            body="THE REPORT BODY",
        )
        assert outcome.delivered is True
        assert outcome.queued is False
        assert await work.list_pending_promoted_reports(limit=10) == ()
    finally:
        await work.stop()


# ── 10. the drain delivers it, exactly once ────────────────────────────────


@pytest.mark.asyncio
async def test_the_drain_delivers_a_pending_report_and_only_once(
    tmp_path, monkeypatch,
) -> None:
    """Drained twice on purpose. An at-least-once drain becomes exactly-once
    delivery because the replayed ``message_id`` is recognised by
    ``append_message_once``, which returns the existing row without inserting."""
    import probos.cognitive.turn_promotion as tp

    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (0.01,))

    db = tmp_path / "chat_threads.db"
    broken = _AlwaysBusy(db_path=db)
    thread = broken.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        outcome = await tp._post_report(
            runtime=SimpleNamespace(chat_thread_store=broken, work_item_store=work),
            agent_id="agent-1", thread_id=thread.id, work_item_id="wi-1",
            body="THE REPORT BODY",
        )
        assert outcome.queued is True

        # The store recovers: a healthy handle onto the same file.
        healthy = ChatThreadStore(db_path=db)
        service = PromotedReportDeliveryService(outbox=work, threads=healthy)

        assert await service.drain_pending() == 1
        assert await work.list_pending_promoted_reports(limit=10) == ()
        # Second pass: nothing left, and nothing posted twice.
        assert await service.drain_pending() == 0

        bodies = [m.body for m in healthy.list_messages(thread.id, limit=50)]
        assert bodies.count("THE REPORT BODY") == 1
        assert healthy.list_messages(thread.id, limit=50)[0].id == outcome.message_id
    finally:
        await work.stop()


@pytest.mark.asyncio
async def test_a_redelivery_whose_ack_is_lost_still_posts_only_once(
    tmp_path,
) -> None:
    """The ack is the one thing this drainer is allowed to lose.

    A row posted but not marked stays pending, so the next pass replays the
    same ``message_id``. That must be a no-op in the thread store, not a second
    report -- otherwise "leave it pending on failure" would be a duplication
    bug rather than a safety property.
    """
    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        created_at = time.time()
        queued = await work.enqueue_promoted_report(
            message_id="a" * 32, work_item_id="wi-1", thread_id=thread.id,
            agent_id="agent-1", body="THE REPORT BODY", created_at=created_at,
        )
        assert queued is True

        marks: list[str] = []
        original = work.mark_promoted_report_delivered

        async def _ack_is_lost(message_id):
            marks.append(message_id)
            if len(marks) == 1:
                raise sqlite3.OperationalError("database is locked")
            return await original(message_id)

        work.mark_promoted_report_delivered = _ack_is_lost
        service = PromotedReportDeliveryService(outbox=work, threads=threads)

        assert await service.drain_pending() == 0, "the lost ack is not a delivery"
        assert len(await work.list_pending_promoted_reports(limit=10)) == 1, (
            "a row whose ack was lost must stay pending"
        )
        assert await service.drain_pending() == 1

        bodies = [m.body for m in threads.list_messages(thread.id, limit=50)]
        assert bodies.count("THE REPORT BODY") == 1, (
            "the replay posted a second copy; the minted message_id is not "
            "reaching append_message_once"
        )
        assert await work.list_pending_promoted_reports(limit=10) == ()
    finally:
        await work.stop()


@pytest.mark.asyncio
async def test_a_row_the_thread_store_still_refuses_stays_pending(
    tmp_path,
) -> None:
    """A failed redelivery must not be recorded as a delivery."""
    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        await work.enqueue_promoted_report(
            message_id="b" * 32, work_item_id="wi-1", thread_id=thread.id,
            agent_id="agent-1", body="still broken", created_at=time.time(),
        )
        broken = _AlwaysBusy(db_path=tmp_path / "chat_threads.db")
        service = PromotedReportDeliveryService(outbox=work, threads=broken)

        assert await service.drain_pending() == 0
        pending = await work.list_pending_promoted_reports(limit=10)
        assert len(pending) == 1 and pending[0].delivered is False
    finally:
        await work.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "store_cls", [_AlwaysRejects, _ThreadVanished], ids=["rejected", "thread_gone"],
)
async def test_a_permanently_undeliverable_row_is_retired_not_left_pending(
    tmp_path, store_cls,
) -> None:
    """Asking again cannot change either answer, so the row must not sit there.

    Both of these were originally left pending, which was honest but wrong:
    the queue is oldest-first and bounded, so rows that can never succeed hold
    the front of it forever. Retired means "out of the pending set", NOT
    "delivered" -- the Captain never received it and the row must not claim
    otherwise.
    """
    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        await work.enqueue_promoted_report(
            message_id="c" * 32, work_item_id="wi-1", thread_id=thread.id,
            agent_id="agent-1", body="never lands", created_at=time.time(),
        )
        broken = store_cls(db_path=tmp_path / "chat_threads.db")
        service = PromotedReportDeliveryService(outbox=work, threads=broken)

        assert await service.drain_pending() == 0
        assert len(await work.list_pending_promoted_reports(limit=10)) == 0

        # ...and it is NOT recorded as delivered. 2 is the third state.
        with sqlite3.connect(str(tmp_path / "workforce.db")) as db:
            state = db.execute(
                "SELECT delivered FROM promoted_report_outbox WHERE message_id = ?",
                ("c" * 32,),
            ).fetchone()
        assert state[0] == 2, "a retired row must never read as delivered"
    finally:
        await work.stop()


@pytest.mark.asyncio
async def test_poison_rows_do_not_starve_a_deliverable_report(tmp_path) -> None:
    """The failure the retirement exists to prevent.

    Three permanently-undeliverable rows queued AHEAD of one good report, with
    a drain limit of 2. Left pending they occupy every bounded pass and the
    good report is never posted -- measured by review as three drains, zero
    delivered. The control is the good row: if it never arrives even after the
    poison is retired, the test is measuring the wrong thing.
    """
    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        now = time.time()
        for i in range(3):
            await work.enqueue_promoted_report(
                message_id=f"{i}" * 32, work_item_id=f"poison-{i}",
                thread_id="thread-that-does-not-exist", agent_id="agent-1",
                body=f"poison {i}", created_at=now + i,
            )
        await work.enqueue_promoted_report(
            message_id="d" * 32, work_item_id="wi-good", thread_id=thread.id,
            agent_id="agent-1", body="the one that matters", created_at=now + 10,
        )

        service = PromotedReportDeliveryService(
            outbox=work, threads=threads, drain_limit=2,
        )
        for _ in range(3):
            await service.drain_pending()

        bodies = [m.body for m in threads.list_messages(thread.id)]
        assert "the one that matters" in bodies, (
            "a deliverable report must not be starved by rows ahead of it that "
            "can never be delivered"
        )
        assert len(await work.list_pending_promoted_reports(limit=10)) == 0
    finally:
        await work.stop()


@pytest.mark.asyncio
async def test_a_delivered_row_is_never_rewritten_as_undeliverable(
    tmp_path,
) -> None:
    """Retirement must not be able to erase a real delivery.

    The Captain received it. Recording it afterwards as undeliverable would
    invert the one fact the outbox exists to keep straight.
    """
    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        await work.enqueue_promoted_report(
            message_id="e" * 32, work_item_id="wi-1", thread_id=thread.id,
            agent_id="agent-1", body="landed", created_at=time.time(),
        )
        assert await work.mark_promoted_report_delivered("e" * 32) is True
        assert await work.mark_promoted_report_undeliverable("e" * 32) is False

        with sqlite3.connect(str(tmp_path / "workforce.db")) as db:
            state = db.execute(
                "SELECT delivered FROM promoted_report_outbox WHERE message_id = ?",
                ("e" * 32,),
            ).fetchone()
        assert state[0] == 1, "a delivered row must stay delivered"
    finally:
        await work.stop()


@pytest.mark.asyncio
async def test_retiring_a_retired_row_reports_success_not_failure(
    tmp_path,
) -> None:
    """Retirement is idempotent, because the drainer can see a row twice.

    A pass that retires a row and then crashes before committing anything else
    will meet the same row again. Returning False there would read as "could
    not retire" and put the row back in the warn-and-retry path forever, which
    is the starvation this retirement exists to end, reintroduced through the
    repeat case.
    """
    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        await work.enqueue_promoted_report(
            message_id="f" * 32, work_item_id="wi-1", thread_id=thread.id,
            agent_id="agent-1", body="doomed", created_at=time.time(),
        )
        assert await work.mark_promoted_report_undeliverable("f" * 32) is True
        assert await work.mark_promoted_report_undeliverable("f" * 32) is True
    finally:
        await work.stop()


@pytest.mark.asyncio
async def test_the_drain_is_bounded_and_says_so_when_the_backlog_is_larger(
    tmp_path, caplog,
) -> None:
    import logging

    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        for i in range(4):
            await work.enqueue_promoted_report(
                message_id=f"{i:032d}", work_item_id="wi-1", thread_id=thread.id,
                agent_id="agent-1", body=f"report {i}", created_at=time.time() + i,
            )
        service = PromotedReportDeliveryService(
            outbox=work, threads=threads, drain_limit=2,
        )
        with caplog.at_level(
            logging.WARNING, logger="probos.cognitive.promoted_report_delivery",
        ):
            delivered = await service.drain_pending()

        assert delivered == 2, "the bound must be honoured"
        assert len(await work.list_pending_promoted_reports(limit=10)) == 2, (
            "the remainder must stay pending, not be dropped"
        )
        assert any("backlog exceeds" in r.getMessage() for r in caplog.records)

        # A second pass clears the rest, so the bound defers work rather than
        # discarding it.
        assert await service.drain_pending() == 2
        assert await work.list_pending_promoted_reports(limit=10) == ()
    finally:
        await work.stop()


@pytest.mark.asyncio
async def test_enqueueing_the_same_report_twice_keeps_one_row(tmp_path) -> None:
    work = await _work_store(tmp_path)
    try:
        kwargs = dict(
            message_id="c" * 32, work_item_id="wi-1", thread_id="t-1",
            agent_id="agent-1", body="once", created_at=1.0,
        )
        assert await work.enqueue_promoted_report(**kwargs) is True
        assert await work.enqueue_promoted_report(**kwargs) is False
        assert len(await work.list_pending_promoted_reports(limit=10)) == 1
    finally:
        await work.stop()


@pytest.mark.asyncio
async def test_the_outbox_refuses_an_invalid_row(tmp_path) -> None:
    work = await _work_store(tmp_path)
    try:
        with pytest.raises(ValueError, match="promoted_report_outbox_invalid"):
            await work.enqueue_promoted_report(
                message_id="", work_item_id="wi-1", thread_id="t-1",
                agent_id="agent-1", body="x", created_at=1.0,
            )
        with pytest.raises(ValueError, match="promoted_report_outbox_limit_invalid"):
            await work.list_pending_promoted_reports(limit=0)
        assert await work.mark_promoted_report_delivered("d" * 32) is False
    finally:
        await work.stop()


# ── startup wiring ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_startup_wires_the_drainer_and_clears_the_backlog(tmp_path) -> None:
    """Without this the pending row is a durable grave: preserved, never retried."""
    from probos.startup.finalize import _wire_promoted_report_delivery

    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        await work.enqueue_promoted_report(
            message_id="e" * 32, work_item_id="wi-1", thread_id=thread.id,
            agent_id="agent-1", body="left over from last boot",
            created_at=time.time(),
        )
        runtime = SimpleNamespace(work_item_store=work, chat_thread_store=threads)
        await _wire_promoted_report_delivery(runtime)

        assert isinstance(
            runtime.promoted_report_delivery_service, PromotedReportDeliveryService
        )
        assert await work.list_pending_promoted_reports(limit=10) == ()
        bodies = [m.body for m in threads.list_messages(thread.id, limit=50)]
        assert bodies == ["left over from last boot"]
    finally:
        await work.stop()


@pytest.mark.asyncio
async def test_startup_wiring_degrades_when_there_is_no_work_store() -> None:
    """A vessel must boot even when nothing can be redelivered."""
    from probos.startup.finalize import _wire_promoted_report_delivery

    runtime = SimpleNamespace(work_item_store=None, chat_thread_store=None)
    await _wire_promoted_report_delivery(runtime)
    assert not hasattr(runtime, "promoted_report_delivery_service")
