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
from typing import Any

import pytest

from probos.cognitive.promoted_report_delivery import (
    PromotedReportDeliveryService,
)
from probos.threads import ChatThreadStore
from probos.workforce import WorkItemStore


_LEGACY_OUTBOX_SCHEMA = """
CREATE TABLE promoted_report_outbox (
    message_id TEXT PRIMARY KEY, work_item_id TEXT NOT NULL,
    thread_id TEXT NOT NULL, agent_id TEXT NOT NULL, body TEXT NOT NULL,
    created_at REAL NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
    queued_at REAL NOT NULL, delivered_at REAL
)
"""


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


async def test_no_ref_report_preserves_legacy_enqueue_signature(monkeypatch) -> None:
    import probos.cognitive.turn_promotion as tp

    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (0.0,))
    queued = []

    class _Busy:
        def append_message_once(self, thread_id: str, **kwargs: Any) -> Any:
            assert kwargs["metadata"] == {"work_item_id": "legacy-work", "source": tp.PROMOTION_SOURCE}
            raise OSError("owned legacy append unavailable")

    class _LegacyOutbox:
        async def enqueue_promoted_report(
            self, *, message_id: str, work_item_id: str, thread_id: str,
            agent_id: str, body: str, created_at: float,
        ) -> bool:
            queued.append((message_id, work_item_id, thread_id, agent_id, body, created_at))
            return True

    delivered = await tp._post_report(
        runtime=SimpleNamespace(chat_thread_store=_Busy(), work_item_store=_LegacyOutbox()),
        agent_id="agent", thread_id="thread", work_item_id="legacy-work", body="legacy body",
    )
    assert delivered.queued and not delivered.delivered
    assert len(queued) == 1
    assert queued[0][0] == delivered.message_id
    assert queued[0][1:5] == ("legacy-work", "thread", "agent", "legacy body")


@pytest.mark.parametrize("legacy", [False, True])
async def test_trace_migration_is_nullable_trailing_and_restart_idempotent(tmp_path, legacy) -> None:
    from probos.workforce import PromotedReportOutboxEntry

    path = tmp_path / "workforce.db"
    if legacy:
        with sqlite3.connect(path) as connection:
            connection.execute(_LEGACY_OUTBOX_SCHEMA)
            connection.execute(
                "INSERT INTO promoted_report_outbox VALUES "
                "('old', 'work', 'thread', 'agent', 'legacy body', 10.0, 0, 11.0, NULL)",
            )
    work = WorkItemStore(db_path=str(path), tick_interval=1000.0)
    try:
        await work.start()
        await work.start()
        with sqlite3.connect(path) as connection:
            columns = connection.execute("PRAGMA table_info(promoted_report_outbox)").fetchall()
            assert [column[1] for column in columns] == [
                "message_id", "work_item_id", "thread_id", "agent_id", "body",
                "created_at", "delivered", "queued_at", "delivered_at", "tool_trace_ref",
            ]
            assert columns[-1][2:6] == ("TEXT", 0, None, 0)
            connection.execute(
                "INSERT INTO promoted_report_outbox "
                "(message_id, work_item_id, thread_id, agent_id, body, created_at, "
                "delivered, queued_at, delivered_at) VALUES "
                "('legacy-writer', 'work', 'thread', 'agent', 'body', 12.0, 0, 13.0, NULL)",
            )
        before = await work.list_pending_promoted_reports(limit=10)
        assert all(entry.tool_trace_ref is None for entry in before)
        if legacy:
            assert before[0] == PromotedReportOutboxEntry(
                "old", "work", "thread", "agent", "legacy body", 10.0, False, 11.0, None,
            )
        await work.stop()
        await work.start()
        assert await work.list_pending_promoted_reports(limit=10) == before
        assert await work.enqueue_promoted_report(
            message_id="omitted", work_item_id="work", thread_id="thread",
            agent_id="agent", body="body", created_at=14.0,
        )
        assert (await work.list_pending_promoted_reports(limit=10))[-1].tool_trace_ref is None
    finally:
        await work.stop()


@pytest.mark.parametrize("column", [
    "tool_trace_ref INTEGER",
    "tool_trace_ref TEXT NOT NULL DEFAULT ''",
    "tool_trace_ref TEXT DEFAULT 'invented'",
    "tool_trace_ref TEXT, unexpected TEXT",
])
async def test_trace_migration_rejects_incompatible_column_and_closes_connection(tmp_path, column) -> None:
    from probos.storage.sqlite_factory import default_factory

    path = tmp_path / "workforce.db"
    with sqlite3.connect(path) as connection:
        connection.execute(_LEGACY_OUTBOX_SCHEMA.rstrip().removesuffix(")") + ", " + column + ")")

    class _Factory:
        connection = None

        async def connect(self, db_path: str) -> Any:
            self.connection = await default_factory.connect(db_path)
            return self.connection

    factory = _Factory()
    work = WorkItemStore(db_path=str(path), connection_factory=factory)
    with pytest.raises(ValueError, match="promoted_report_trace_column_incompatible"):
        await work.start()
    assert await work.list_pending_promoted_reports(limit=10) == ()
    with pytest.raises(ValueError, match="no active connection"):
        await factory.connection.execute("SELECT 1")
    await work.stop()


@pytest.mark.parametrize("default", ["NULL", "Null", "(NULL)"])
async def test_trace_migration_accepts_existing_sql_null_default(tmp_path, default) -> None:
    from contextlib import closing

    path = tmp_path / "workforce.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            _LEGACY_OUTBOX_SCHEMA.rstrip().removesuffix(")")
            + ", tool_trace_ref TEXT DEFAULT " + default + ")",
        )
    work = WorkItemStore(db_path=str(path))
    try:
        await work.start()
        assert await work.enqueue_promoted_report(
            message_id="legacy", work_item_id="work", thread_id="thread",
            agent_id="agent", body="body", created_at=1.0,
        )
        (pending,) = await work.list_pending_promoted_reports(limit=1)
        assert pending.tool_trace_ref is None
    finally:
        await work.stop()


@pytest.mark.parametrize("failure", [sqlite3.OperationalError("migration fixture failure"), asyncio.CancelledError()])
async def test_trace_migration_unexpected_failure_propagates_and_cleans_up(tmp_path, failure) -> None:
    from probos.storage.sqlite_factory import default_factory

    class _Connection:
        def __init__(self, connection: Any) -> None:
            self.connection = connection
            self.closed = False

        @property
        def row_factory(self) -> Any:
            return self.connection.row_factory

        @row_factory.setter
        def row_factory(self, value: Any) -> None:
            self.connection.row_factory = value

        async def execute(self, sql: str, parameters: Any = ()) -> Any:
            if sql == "PRAGMA table_info(promoted_report_outbox)":
                raise failure
            return await self.connection.execute(sql, parameters)

        async def executescript(self, sql: str) -> Any:
            return await self.connection.executescript(sql)

        async def commit(self) -> None:
            await self.connection.commit()

        async def close(self) -> None:
            self.closed = True
            await self.connection.close()

    class _Factory:
        connection = None

        async def connect(self, db_path: str) -> Any:
            self.connection = _Connection(await default_factory.connect(db_path))
            return self.connection

    factory = _Factory()
    work = WorkItemStore(db_path=str(tmp_path / "workforce.db"), connection_factory=factory)
    with pytest.raises(type(failure)):
        await work.start()
    assert factory.connection.closed
    assert await work.list_pending_promoted_reports(limit=10) == ()
    await work.stop()


@pytest.mark.parametrize("ref", ["", "A" * 64, "b" * 63, "b" * 65, 1, True, b"a" * 64])
async def test_enqueue_promoted_report_rejects_noncanonical_refs(tmp_path, ref) -> None:
    work = await _work_store(tmp_path)
    try:
        with pytest.raises(ValueError, match="promoted_report_outbox_invalid"):
            await work.enqueue_promoted_report(
                message_id="msg", work_item_id="work", thread_id="thread",
                agent_id="agent", body="body", created_at=1.0, tool_trace_ref=ref,
            )
        assert await work.list_pending_promoted_reports(limit=10) == ()
    finally:
        await work.stop()


async def test_enqueue_promoted_report_keeps_first_ref_and_all_identity_fields(tmp_path) -> None:
    work = await _work_store(tmp_path)
    try:
        arguments = dict(
            message_id="msg", work_item_id="work", thread_id="thread",
            agent_id="agent", body="first", created_at=1.0, tool_trace_ref="a" * 64,
        )
        assert await work.enqueue_promoted_report(**arguments)
        original = (await work.list_pending_promoted_reports(limit=10))[0]
        assert not await work.enqueue_promoted_report(
            **{**arguments, "body": "second", "created_at": 2.0, "tool_trace_ref": "b" * 64},
        )
        assert (await work.list_pending_promoted_reports(limit=10))[0] == original
        await work.stop()
        await work.start()
        assert (await work.list_pending_promoted_reports(limit=10))[0] == original
    finally:
        await work.stop()


@pytest.mark.parametrize("corrupt", ["", "A" * 64, "x" * 64, sqlite3.Binary(b"a" * 64)])
async def test_corrupt_persisted_trace_ref_fails_without_delivery_or_discard(tmp_path, corrupt) -> None:
    work = await _work_store(tmp_path)
    threads = ChatThreadStore(tmp_path / "threads.db")
    thread = threads.create_thread(title="owned", participants=["agent"])
    try:
        await work.enqueue_promoted_report(
            message_id="msg", work_item_id="work", thread_id=thread.id,
            agent_id="agent", body="body", created_at=1.0,
        )
        with sqlite3.connect(tmp_path / "workforce.db") as connection:
            connection.execute(
                "UPDATE promoted_report_outbox SET tool_trace_ref = ? WHERE message_id = 'msg'",
                (corrupt,),
            )
        service = PromotedReportDeliveryService(outbox=work, threads=threads)
        with pytest.raises(ValueError, match="promoted_report_outbox_corrupt"):
            await service.drain_pending()
        assert threads.list_messages(thread.id) == []
        with sqlite3.connect(tmp_path / "workforce.db") as connection:
            row = connection.execute(
                "SELECT delivered, tool_trace_ref FROM promoted_report_outbox WHERE message_id = 'msg'",
            ).fetchone()
        assert row[0] == 0
        assert row[1] == (bytes(corrupt) if isinstance(corrupt, memoryview) else corrupt)
    finally:
        await work.stop()


async def test_rollback_requires_quiescence_and_newer_drain_after_real_ack_loss(tmp_path) -> None:
    from contextlib import closing

    from probos.cognitive.promoted_report_delivery import promoted_report_metadata
    from tests.fixtures.consulted_evidence_bridge import ConsultedEvidenceFixture, REPLY_BODY

    fixture = ConsultedEvidenceFixture(tmp_path)
    try:
        await fixture.start()
        acknowledged = await fixture.start_turn(mode="lost_ack")
        completed = await fixture.release_turn(acknowledged["turn"])
        assert completed["llm_calls"] == 2 and completed["tool_calls"] == 1
        (pending,) = await fixture.work.list_pending_promoted_reports(limit=10)
        (report,) = [
            message for message in fixture.threads.list_messages(pending.thread_id)
            if message.body == REPLY_BODY
        ]
        assert report.id == pending.message_id
        assert report.metadata["tool_trace_ref"] == pending.tool_trace_ref
        fixture.threads.fault_mode = ""
        # An older drainer replays only these two metadata keys. This must fail:
        # relaxing append equality would hide the lost provenance on downgrade.
        with pytest.raises(ValueError, match="chat_thread_message_conflict"):
            fixture.threads.append_message_once(
                pending.thread_id, message_id=pending.message_id, author_id=pending.agent_id,
                role="agent", body=pending.body, created_at=pending.created_at,
                metadata=promoted_report_metadata(pending.work_item_id),
            )
        assert await fixture.work.list_pending_promoted_reports(limit=10) == (pending,)
        # The producer is quiescent. Restart under the newer schema and resolve
        # trace-bearing pending reports before an older drainer can be deployed.
        recovered = await fixture.recover(acknowledged["turn"])
        assert recovered["pending"] == []
        assert len([message for message in recovered["messages"] if message["body"] == REPLY_BODY]) == 1
        with closing(sqlite3.connect(tmp_path / "workforce.db")) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM promoted_report_outbox "
                "WHERE delivered = 0 AND tool_trace_ref IS NOT NULL",
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT tool_trace_ref FROM promoted_report_outbox WHERE message_id = ?",
                (pending.message_id,),
            ).fetchone() == (pending.tool_trace_ref,)
            # Rollback retains the column. Old explicit-column SQL can still
            # enqueue a new legacy-null report without rewriting stored bodies.
            connection.execute(
                "INSERT INTO promoted_report_outbox "
                "(message_id, work_item_id, thread_id, agent_id, body, created_at, "
                "delivered, queued_at, delivered_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, NULL)",
                ("legacy-after-quiescence", "legacy-work", pending.thread_id, pending.agent_id,
                 "legacy body", 123.0, 124.0),
            )
            connection.commit()
        (legacy,) = await fixture.work.list_pending_promoted_reports(limit=10)
        assert legacy.tool_trace_ref is None
        replayed = fixture.threads.append_message_once(
            legacy.thread_id, message_id=legacy.message_id, author_id=legacy.agent_id,
            role="agent", body=legacy.body, created_at=legacy.created_at,
            metadata=promoted_report_metadata(legacy.work_item_id),
        )
        assert replayed.body == "legacy body"
        assert replayed.metadata == {"work_item_id": "legacy-work", "source": "dm_agentic_promotion"}
    finally:
        await fixture.stop()


@pytest.mark.parametrize("cancel_at", ["write", "backoff"])
async def test_cancelled_real_report_queues_same_frozen_ref_for_recovery(
    tmp_path, monkeypatch, cancel_at,
) -> None:
    import threading

    import probos.cognitive.turn_promotion as tp
    from tests.fixtures.consulted_evidence_bridge import ConsultedEvidenceFixture, REPLY_BODY

    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (30.0,))
    entered = threading.Event()
    release_write = threading.Event()
    committed = threading.Event()
    attempts = []
    fixture = ConsultedEvidenceFixture(tmp_path)
    finishing = None

    class _Gate:
        def append_message_once(self, thread_id: str, **kwargs: Any) -> Any:
            attempts.append({"thread_id": thread_id, **kwargs})
            entered.set()
            if cancel_at == "backoff":
                raise OSError("owned fixture append retry")
            if not release_write.wait(timeout=5):
                raise TimeoutError("owned fixture write gate timed out")
            message = fixture.threads.append_message_once(thread_id, **kwargs)
            committed.set()
            return message

    try:
        await fixture.start()
        acknowledged = await fixture.start_turn(mode="promoted")
        fixture.runtime.chat_thread_store = _Gate()
        finishing = asyncio.create_task(fixture.release_turn(acknowledged["turn"]))
        assert await asyncio.to_thread(entered.wait, 5)
        await fixture.agents["yeo"].cancel_reports()
        await asyncio.gather(finishing, return_exceptions=True)
        (pending,) = await fixture.work.list_pending_promoted_reports(limit=10)
        assert pending.tool_trace_ref is not None
        assert pending.tool_trace_ref == attempts[0]["metadata"]["tool_trace_ref"]
        assert pending.message_id == attempts[0]["message_id"]
        assert pending.created_at == attempts[0]["created_at"]
        assert pending.body == attempts[0]["body"] == REPLY_BODY
        assert len(attempts) == 1
        if cancel_at == "write":
            release_write.set()
            assert await asyncio.to_thread(committed.wait, 5)
        fixture.runtime.chat_thread_store = fixture.threads
        recovered = await fixture.recover(acknowledged["turn"])
        assert recovered["llm_calls"] == 2 and recovered["tool_calls"] == 1
        assert recovered["pending"] == []
        (report,) = [message for message in recovered["messages"] if message["body"] == REPLY_BODY]
        assert report["id"] == pending.message_id
        assert report["metadata"] == attempts[0]["metadata"]
    finally:
        release_write.set()
        if finishing is not None and not finishing.done():
            finishing.cancel()
            await asyncio.gather(finishing, return_exceptions=True)
        await fixture.stop()


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
