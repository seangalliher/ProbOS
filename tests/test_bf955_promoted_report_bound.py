"""BF-955 (#1757): a promoted report over the outbox's limit keeps its durable retry.

The promoted-report outbox refuses a body over 65,536 UTF-8 bytes when it writes a row
(``WorkItemStore.enqueue_promoted_report``) and when the drain reads one; the thread store sets
no limit. ``_post_report`` bounds the composed text once, before the first attempt, so the first
delivery, every retry, the cancellation queue and the exhausted queue carry the same text, and a
replay posts what the first attempt posted.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from types import SimpleNamespace
from typing import Any

import pytest

import probos.cognitive.promoted_report_delivery as prd
import probos.cognitive.turn_promotion as tp
from probos.cognitive.dm.reply_value import DmReply, ToolFailures, call_signature, failure_key
from probos.cognitive.promoted_report_delivery import PromotedReportDeliveryService
from probos.threads import ChatThreadStore
from probos.workforce import WorkItemStore

#: The outbox's limit (``workforce._MAX_PROMOTED_REPORT_BODY_BYTES``), written out so T5 compares two sources.
_LIMIT = 65_536
_NOTE = "\n\n(The rest of this report, "
_LOGGER = "probos.cognitive.turn_promotion"
_ROOT = "aaaaaaaaaaaa"
_BUILT = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-955 M2 builds it")
_TEXTS = {
    "at_limit": "x" * _LIMIT,
    "over_by_one": "x" * (_LIMIT + 1),
    # 90,001 bytes. The leading byte moves the cut off a character boundary.
    "over_multibyte": "a" + "\u20ac" * 30_000,
}


def _api() -> tuple[Any, int]:
    bound = getattr(prd, "bound_promoted_report_body", None)
    limit = getattr(prd, "PROMOTED_REPORT_BODY_MAX_BYTES", None)
    assert bound is not None and limit is not None, "BF-955: the bound is not built"
    return bound, limit


def _failures(name: str = "web_search") -> ToolFailures:
    return ToolFailures.from_mapping({failure_key(_ROOT, _ROOT, call_signature(name, None)): name})


class _Busy(ChatThreadStore):
    """Every append fails as a held lock does, after recording what it was asked to post."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.attempts: list[dict[str, Any]] = []
        self.entered = threading.Event()

    def append_message_once(self, thread_id: str, **kwargs: Any) -> Any:
        self.attempts.append({"thread_id": thread_id, **kwargs})
        self.entered.set()
        raise sqlite3.OperationalError("database is locked")


async def _work_store(tmp_path) -> WorkItemStore:
    store = WorkItemStore(db_path=str(tmp_path / "workforce.db"), tick_interval=1000.0)
    await store.start()
    return store


async def _post(threads: Any, work: Any, thread_id: str, text: str, *, failures: Any = None) -> Any:
    return await tp._post_report(
        runtime=SimpleNamespace(chat_thread_store=threads, work_item_store=work),
        agent_id="agent-1", thread_id=thread_id, work_item_id="wi-1",
        body=text, tool_failures=failures,
    )


# ---------------------------------------------------------------- the seam


@pytest.mark.parametrize(
    "case",
    [
        "at_limit",
        pytest.param("over_by_one", marks=_BUILT),  # T1
        pytest.param("over_multibyte", marks=_BUILT),  # T1
    ],
)
async def test_an_exhausted_report_is_queued_and_replayed_as_the_first_attempt_posted_it(
    tmp_path, monkeypatch, case,
) -> None:
    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (0.0,))
    text = _TEXTS[case]
    db = tmp_path / "chat_threads.db"
    busy = _Busy(db_path=db)
    thread = busy.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        outcome = await _post(busy, work, thread.id, text)
        assert outcome.reason == "exhausted"
        assert outcome.queued is True, "the report lost its durable retry"
        assert len(busy.attempts) == 3
        first = busy.attempts[0]
        assert all(attempt == first for attempt in busy.attempts), "every attempt posts the same message"
        pending = await work.list_pending_promoted_reports(limit=10)
        assert len(pending) == 1
        row = pending[0]
        assert (row.message_id, row.created_at, row.agent_id, row.body) == (
            first["message_id"], first["created_at"], first["author_id"], first["body"],
        )
        assert len(row.body.encode("utf-8")) <= _LIMIT

        healthy = ChatThreadStore(db_path=db)
        service = PromotedReportDeliveryService(outbox=work, threads=healthy)
        assert await service.drain_pending() == 1
        assert await service.drain_pending() == 0
        (replayed,) = healthy.list_messages(thread.id, limit=50)
        assert (
            replayed.id, replayed.author_id, replayed.role, replayed.body,
            replayed.created_at, replayed.metadata,
        ) == (
            first["message_id"], first["author_id"], first["role"], first["body"],
            first["created_at"], first["metadata"],
        )

        # The free path: the same text, posted while the store is free, is the same message.
        other = healthy.create_thread(title="u", participants=["captain", "agent-1"])
        free = await _post(healthy, work, other.id, text)
        assert free.delivered is True
        (direct,) = healthy.list_messages(other.id, limit=50)
        assert (direct.body, direct.metadata) == (replayed.body, replayed.metadata)
        # D2: the caller keeps the full text on both paths.
        assert outcome.body == free.body == text
    finally:
        await work.stop()


# ---------------------------------------------------------------- the bound


@_BUILT  # T2
@pytest.mark.parametrize("case", ["at_limit", "over_by_one", "over_multibyte"])
def test_the_bound_keeps_a_text_at_the_limit_and_cuts_a_longer_one_on_a_character_boundary(case) -> None:
    bound, limit = _api()
    assert limit == _LIMIT
    text = _TEXTS[case]
    result = bound(text)
    if case == "at_limit":
        assert (result.text, result.cut_chars, result.cut_bytes) == (text, 0, 0)
        return
    assert len(result.text.encode("utf-8")) <= _LIMIT
    head, sep, rest = result.text.partition(_NOTE)
    assert sep, "the cut text says it was cut"
    assert text.startswith(head) and "\ufffd" not in head
    # At most 256 bytes are held for the note, and at most 3 bytes of a cut character are dropped.
    assert len(head.encode("utf-8")) >= _LIMIT - 256 - 3
    assert result.cut_chars == len(text) - len(head)
    assert result.cut_bytes == len(text.encode("utf-8")) - len(head.encode("utf-8"))
    assert rest.startswith(f"{result.cut_chars:,} characters")
    assert bound(text) == result, "the same text is bounded the same way"


@_BUILT  # T3
@pytest.mark.parametrize("path", ["delivered", "exhausted"])
async def test_the_disclosure_survives_the_cut_and_the_caller_keeps_the_full_text(
    tmp_path, monkeypatch, path,
) -> None:
    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (0.0,))
    failures = _failures()
    text = "x" * 70_000
    full = str(DmReply(body=text, tool_failures=failures).render())
    disclosure = str(DmReply(body="", tool_failures=failures).render())
    assert disclosure and "web_search" in disclosure and full == text + disclosure  # premise
    db = tmp_path / "chat_threads.db"
    threads = ChatThreadStore(db_path=db) if path == "delivered" else _Busy(db_path=db)
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        outcome = await _post(threads, work, thread.id, text, failures=failures)
        if path == "delivered":
            assert outcome.delivered is True
            messages = threads.list_messages(thread.id, limit=50)
            assert len(messages) == 1
            posted = messages[0].body
        else:
            assert outcome.queued is True
            pending = await work.list_pending_promoted_reports(limit=10)
            assert len(pending) == 1
            posted = pending[0].body
        assert len(posted.encode("utf-8")) <= _LIMIT
        assert posted.endswith(disclosure), "AD-1248: a cut keeps the tool-failure disclosure"
        assert _NOTE in posted
        # D2: the episode and the artifact get the full composed text ...
        assert outcome.body == full
        # ... whose first 500 characters (the AD-1166 episode response) are the posted text's.
        assert outcome.body[:500] == posted[:500]
    finally:
        await work.stop()


@pytest.mark.parametrize(
    "case",
    ["at_limit", pytest.param("over_by_one", marks=_BUILT)],  # T4
)
async def test_a_cancelled_turn_queues_the_text_its_attempt_posted(tmp_path, monkeypatch, case) -> None:
    monkeypatch.setattr(tp, "_REPORT_RETRY_BACKOFF_SECONDS", (30.0,))
    text = _TEXTS[case]
    busy = _Busy(db_path=tmp_path / "chat_threads.db")
    thread = busy.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        task = asyncio.create_task(_post(busy, work, thread.id, text))
        assert await asyncio.to_thread(busy.entered.wait, 5)
        # Lands in the write or in the 30 s backoff; both arms call _queue_on_cancel.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        pending = await work.list_pending_promoted_reports(limit=10)
        assert len(pending) == 1, "the cancelled turn lost its durable retry"
        assert pending[0].body == busy.attempts[0]["body"]
        assert pending[0].message_id == busy.attempts[0]["message_id"]
        assert len(pending[0].body.encode("utf-8")) <= _LIMIT
    finally:
        await work.stop()


@_BUILT  # T5
async def test_the_bound_is_the_limit_a_real_outbox_accepts(tmp_path) -> None:
    bound, limit = _api()
    work = await _work_store(tmp_path)
    try:
        ids = {"work_item_id": "wi-1", "thread_id": "thread-1", "agent_id": "agent-1", "created_at": 1.0}
        assert await work.enqueue_promoted_report(message_id="m-at", body="x" * limit, **ids) is True
        with pytest.raises(ValueError, match="promoted_report_outbox_invalid"):
            await work.enqueue_promoted_report(message_id="m-over", body="x" * (limit + 1), **ids)
        cut = bound("x" * (limit + 1)).text
        assert await work.enqueue_promoted_report(message_id="m-cut", body=cut, **ids) is True
    finally:
        await work.stop()


@pytest.mark.parametrize(
    "case",
    ["at_limit", pytest.param("over_by_one", marks=_BUILT)],  # T6
)
async def test_a_cut_is_logged_once_at_warning_with_the_work_item_and_what_was_cut(
    tmp_path, caplog, case,
) -> None:
    text = _TEXTS[case]
    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            outcome = await _post(threads, work, thread.id, text)
        assert outcome.delivered is True
        records = [r for r in caplog.records if r.name == _LOGGER and "BF-955" in r.getMessage()]
        if case == "at_limit":
            assert records == []
            return
        assert len(records) == 1 and records[0].levelno == logging.WARNING
        message = records[0].getMessage()
        (posted,) = threads.list_messages(thread.id, limit=50)
        head = posted.body.partition(_NOTE)[0]
        assert "wi-1" in message and f"is {len(text)} characters" in message
        assert f"{len(text) - len(head)} characters (" in message
    finally:
        await work.stop()


@_BUILT  # T7
@pytest.mark.parametrize("text", ["\ud800" + "x" * 10, "x" * 70_000 + "\ud800"], ids=["short", "long"])
def test_a_text_that_is_not_utf8_encodable_is_returned_unchanged(text) -> None:
    bound, _limit = _api()
    result = bound(text)
    assert result.text == text and result.cut_chars == 0


@_BUILT  # T8
@pytest.mark.parametrize("tail_case", ["too_large", "not_a_suffix"])
def test_a_tail_is_kept_only_when_it_ends_the_text_and_leaves_room(tail_case) -> None:
    bound, _limit = _api()
    if tail_case == "too_large":
        tail = "y" * 65_400
        text = "x" * 1_000 + tail
    else:
        tail = "\n\nTAIL"
        text = "x" * 70_000
    result = bound(text, keep_tail=tail)
    assert len(result.text.encode("utf-8")) <= _LIMIT
    assert _NOTE in result.text
    assert not result.text.endswith(tail)


async def test_a_report_within_the_limit_is_posted_byte_identically_with_its_disclosure(tmp_path) -> None:
    failures = _failures()
    text = "I finished the research."
    threads = ChatThreadStore(db_path=tmp_path / "chat_threads.db")
    thread = threads.create_thread(title="t", participants=["captain", "agent-1"])
    work = await _work_store(tmp_path)
    try:
        outcome = await _post(threads, work, thread.id, text, failures=failures)
        assert outcome.delivered is True
        (message,) = threads.list_messages(thread.id, limit=50)
        assert message.body == outcome.body == str(DmReply(body=text, tool_failures=failures).render())
    finally:
        await work.stop()
