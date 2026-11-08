# BF-955 (#1757): a promoted report over 64 KiB keeps its durable retry

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06
**Status:** ready to build on `origin/main` after AD-1358 S1 (#1750), BF-957 (#1760) and BF-958 (#1761) merge.
**Base:** the anchors were taken on `D:\ProbOS-worktrees\ad1358-build` (`fa030cae`), whose text of every source file below equals `48ed13bf`. `turn_promotion.py` is blob `f9c3c8da`; `promoted_report_delivery.py` is blob `67f56ef6`.
**Dependencies:** none in code.
**Tier:** M1 STANDARD (tests only). M2 HIGH (data integrity: what the thread and the outbox store and replay). M3 STANDARD.
**Estimated tests:** one new file, `tests/test_bf955_promoted_report_bound.py`, with 9 functions and 18 cases. No existing test file is edited. Counted by reading, not by running.
**BF number:** BF-955, held by #1757. Nothing new is allocated.

**Which text describes the head.** Before building, run:
1. `git diff --stat 48ed13bf HEAD -- src/probos/cognitive/turn_promotion.py src/probos/cognitive/promoted_report_delivery.py src/probos/workforce.py src/probos/cognitive/dm/bypass_egress.py src/probos/threads/__init__.py src/probos/dm_reply.py`. It must be empty.
2. Check that `tests/test_bf955_promoted_report_bound.py` does not exist.

Then:
- Each SEARCH below must occur exactly once. Otherwise it is a hard stop, and the SEARCH goes back to the Architect.
- Working copies are CRLF, and SEARCH text here is LF.
- Where prose and a block differ, the block wins.
- Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **The outbox has a limit.** `_MAX_PROMOTED_REPORT_BODY_BYTES = 65_536` (`workforce.py:1644`). It is enforced when a row is written (`enqueue_promoted_report`, `:10500`, which raises `ValueError("promoted_report_outbox_invalid")` at `:10512`) and when the drain reads a row (`:2113`).
2. **The thread store has none.** `ChatThreadStore.append_message_once` checks only that `body` is a `str` (`threads/__init__.py:1410`).
3. **Nothing bounds the body.** It is `compose_bypass_reply(text) or _REPORT_EMPTY` (`turn_promotion.py:1855`), and `compose_bypass_reply` returns marker-free text unchanged (`bypass_egress.py:156-157`). `_post_report` (`:1090`) renders the disclosure (`:1142-1152`). The same `body` then goes to every attempt (`:1220`), to `_queue_on_cancel` (`:1198`) and to the exhausted queue (`:1302`).
4. **Effect.** For a body over the limit whose attempts all fail, `enqueue` raises inside `_queue_pending_report`. It catches the error, logs "survives only in this log" (`:1361-1367`) and returns `False`. A cancelled turn loses the report the same way (`:1204-1210`).

## 2. Solution

- **The helper.** `bound_promoted_report_body(text, *, keep_tail="")` and `PROMOTED_REPORT_BODY_MAX_BYTES` are added to `cognitive/promoted_report_delivery.py`.
- **One bound per call.** `_post_report` records the agent's text before the render (`prose`), takes as the disclosure whatever the render appended after it, and computes `posted` once, before `message_id` is minted. Every attempt and both queue paths pass `posted`.
- **What the caller gets.** `ReportDelivery.body` stays the full composed text.
- **Logging.** A cut is logged once at WARNING, with the work item, the size, and how much was cut.

## 3. Decisions

D0 to D6 are in the tables above this contract.

## 4. Milestones and gates

| M | Pairs | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-10, then N2-1 to N2-10 (removing the markers) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`.

- **M0.** On the head, record the collected count (`--collect-only -q`) of every existing file named in G2. The bridge allows no pytest, so I could not.
- **G1.** `PY -m pytest tests/test_bf955_promoted_report_bound.py -q -n 0 -p no:randomly`
  - Expected: **4 passed**, **14 xfailed**. The 4 passes are T1[at_limit], T4[at_limit], T6[at_limit] and T9.
  - The marker has `raises=AssertionError, strict=True`, so any other exception, or an XPASS, is a FAIL.
  - Any other count is a hard stop.
- **G2.**
  1. `PY -m pytest tests/test_bf955_promoted_report_bound.py tests/test_ad1274_report_outbox.py tests/test_ad1274_report_off_loop.py tests/test_ad1248_slice_a_gaps.py tests/test_ad1165_turn_promotion.py tests/test_bf732_promoted_run_slot.py tests/test_ad1226_recall_artifact.py tests/test_bf791_bf792_bypass_egress.py tests/test_ad1346_admission_store_census.py tests/test_ad1346_admission_effect_census.py tests/test_ad1343_seam_registry.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`
  2. `PY -P scripts/check_architecture_principles.py --check`
  - Expected: **18 passed** in the new file. Every other file has 0 failed, and its collected count equals M0. The architecture check is clean.
- **G3.**
  1. `PY -P scripts/gen_ad_ledger.py`
  2. `PY -P scripts/gen_ad_ledger.py --check`
  3. `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`
- **Harness rule.** No source change made to pass a test, no skip, and no loosened assertion. Any of these goes back to the Architect.
- The broad gate runs once, in the main session, with `--receipt`, after the review repairs.

## 5. Commit messages

- **M1:** `BF-955 M1: tests for bounding a promoted report to the outbox's limit before its first delivery, xfail until built`
- **M2:** `BF-955 M2: a promoted report over 64 KiB is cut once before its first attempt, so its durable retry carries the text the attempts posted`
- **M3:** `BF-955 M3: trackers and ledger`

## 6. Tests (`tests/test_bf955_promoted_report_bound.py`)

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T1 | `test_an_exhausted_report_is_queued_and_replayed_as_the_first_attempt_posted_it` | 3 | **Seam:** real stores; exhausted → queued → drained → equals the attempts and the free path; at the limit and over it behave alike | over ×2: M2 |
| T2 | `test_the_bound_keeps_a_text_at_the_limit_and_cuts_a_longer_one_on_a_character_boundary` | 3 | The bound itself; determinism | M2 |
| T3 | `test_the_disclosure_survives_the_cut_and_the_caller_keeps_the_full_text` | 2 | AD-1248 disclosure; D2 on the delivered and exhausted paths | M2 |
| T4 | `test_a_cancelled_turn_queues_the_text_its_attempt_posted` | 2 | D3 | over: M2 |
| T5 | `test_the_bound_is_the_limit_a_real_outbox_accepts` | 1 | The two copies of 65,536 are equal | M2 |
| T6 | `test_a_cut_is_logged_once_at_warning_with_the_work_item_and_what_was_cut` | 2 | Logging | over: M2 |
| T7 | `test_a_text_that_is_not_utf8_encodable_is_returned_unchanged` | 2 | Never raises | M2 |
| T8 | `test_a_tail_is_kept_only_when_it_ends_the_text_and_leaves_room` | 2 | Tail rules | M2 |
| T9 | `test_a_report_within_the_limit_is_posted_byte_identically_with_its_disclosure` | 1 | Guard: AD-1248 byte identity within the limit | none |

**How each xfail case fails on the base.** Each fails at an `AssertionError`:
- T2, T5, T7 and T8 fail at `_api()`'s assertion.
- T1, T3[exhausted] and T4 fail at the `queued` or `len(pending) == 1` assertion.
- T3[delivered] fails at `len(posted.encode()) <= _LIMIT`.
- T6 fails at `len(records) == 1`.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf955_promoted_report_bound.py`:

```python
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
```

### 7.2 M2

**P2-1.** `src/probos/cognitive/promoted_report_delivery.py`
SEARCH:
```
import re
from typing import Any
```
REPLACE:
```
import re
from dataclasses import dataclass
from typing import Any
```

**P2-2.** `src/probos/cognitive/promoted_report_delivery.py`
SEARCH:
```
PROMOTED_REPORT_SOURCE_KEY = "source"
```
REPLACE:
```
PROMOTED_REPORT_SOURCE_KEY = "source"

# BF-955: the largest body, in UTF-8 bytes, that the promoted-report outbox
# accepts. ``WorkItemStore`` holds its own copy (``workforce.py``) and applies it
# when a row is written and again when the drain reads one; the BF-955 suite
# pins the two equal through a real store.
PROMOTED_REPORT_BODY_MAX_BYTES = 65_536

# BF-955: bytes held back for the cut note, which is under 160 bytes for any
# count below 10**18.
_CUT_NOTE_RESERVE_BYTES = 256

_CUT_NOTE = (
    "\n\n(The rest of this report, {:,} characters, was cut here, because a "
    "report this long cannot be kept for redelivery.)"
)


@dataclass(frozen=True)
class BoundedReportBody:
    """BF-955: a promoted report's body as it is posted and queued.

    ``cut_chars`` and ``cut_bytes`` count what was cut from the text before its
    tool-failure disclosure; both are 0 when ``text`` is the input.
    """

    text: str
    cut_chars: int = 0
    cut_bytes: int = 0


def bound_promoted_report_body(text: str, *, keep_tail: str = "") -> BoundedReportBody:
    """BF-955: bound a report to what the outbox accepts, the same way every time.

    A text of at most ``PROMOTED_REPORT_BODY_MAX_BYTES`` UTF-8 bytes is returned
    unchanged. A longer one becomes its head, cut on a character boundary, then
    the cut note, then ``keep_tail`` when the text ends with it and it leaves
    room for a head (AD-1248: the tool-failure disclosure survives a cut). A
    text that is not encodable as UTF-8 is returned unchanged.

    Deterministic, so a replay of the same text posts the same message.
    """
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        return BoundedReportBody(text=text)
    if len(data) <= PROMOTED_REPORT_BODY_MAX_BYTES:
        return BoundedReportBody(text=text)
    tail = keep_tail if keep_tail and text.endswith(keep_tail) else ""
    tail_data = tail.encode("utf-8")
    if len(tail_data) + _CUT_NOTE_RESERVE_BYTES >= PROMOTED_REPORT_BODY_MAX_BYTES:
        tail, tail_data = "", b""
    prose_data = data[: len(data) - len(tail_data)]
    room = PROMOTED_REPORT_BODY_MAX_BYTES - _CUT_NOTE_RESERVE_BYTES - len(tail_data)
    head = prose_data[:room].decode("utf-8", "ignore")
    cut_chars = len(text) - len(tail) - len(head)
    cut_bytes = len(prose_data) - len(head.encode("utf-8"))
    return BoundedReportBody(
        text=head + _CUT_NOTE.format(cut_chars) + tail,
        cut_chars=cut_chars,
        cut_bytes=cut_bytes,
    )
```

**P2-3.** `src/probos/cognitive/turn_promotion.py`
SEARCH:
```
from probos.cognitive.dm.bypass_egress import compose_bypass_reply
from probos.cognitive.promoted_report_delivery import promoted_report_metadata
from probos.tools.executor import recording_identity, sample_recording_identity
```
REPLACE:
```
from probos.cognitive.dm.bypass_egress import compose_bypass_reply
from probos.cognitive.promoted_report_delivery import (
    PROMOTED_REPORT_BODY_MAX_BYTES,
    bound_promoted_report_body,
    promoted_report_metadata,
)
from probos.tools.executor import recording_identity, sample_recording_identity
```

**P2-4.** `src/probos/cognitive/turn_promotion.py`
SEARCH:
```
    ``body`` is the COMPOSED disclosure text and is populated on every path,
    delivered or not: AD-1248 renders once per route and reuses that text for
    the episode and the outcome artifact, which must not change because the
    thread post failed.
    """
```
REPLACE:
```
    ``body`` is the COMPOSED disclosure text and is populated on every path,
    delivered or not: AD-1248 renders once per route and reuses that text for
    the episode and the outcome artifact, which must not change because the
    thread post failed.

    BF-955: above ``PROMOTED_REPORT_BODY_MAX_BYTES`` the thread and the outbox
    carry ``bound_promoted_report_body``'s cut of this text; ``body`` stays the
    full text.
    """
```

**P2-5.** `src/probos/cognitive/turn_promotion.py`
SEARCH:
```
    how one of them ends up with a different story. Render once per route, reuse.
    """
    from probos.dm_reply import DmReply, ToolFailures
```
REPLACE:
```
    how one of them ends up with a different story. Render once per route, reuse.

    BF-955: the text every attempt posts and every queue path stores is bounded
    once, before the first attempt, to what the outbox accepts, so a replay
    posts what the first attempt posted. The returned ``body`` is the full
    composed text.
    """
    from probos.dm_reply import DmReply, ToolFailures
```

**P2-6.** `src/probos/cognitive/turn_promotion.py`
SEARCH:
```
        tool_failures = None
    try:
        body = str(DmReply(
```
REPLACE:
```
        tool_failures = None
    prose = body  # BF-955: the agent's text, before the render appends a tool-failure disclosure
    try:
        body = str(DmReply(
```

**P2-7.** `src/probos/cognitive/turn_promotion.py`
SEARCH:
```
        return ReportDelivery(body=body, delivered=False, reason="no_store")

    # Minted ONCE, reused by every attempt and by any outbox redelivery. This
```
REPLACE:
```
        return ReportDelivery(body=body, delivered=False, reason="no_store")

    # BF-955: the outbox refuses a body over PROMOTED_REPORT_BODY_MAX_BYTES when
    # it writes a row and when the drain reads one, and the thread store sets no
    # limit. So the text is bounded once, here, before the first attempt: every
    # attempt, the cancellation queue and the exhausted queue carry ``posted``,
    # and a replay posts what the first attempt posted. ``body`` stays the full
    # composed text, which the caller reuses for the episode and the artifact.
    tail = body[len(prose):] if body.startswith(prose) else ""
    bounded = bound_promoted_report_body(body, keep_tail=tail)
    posted = bounded.text
    if bounded.cut_chars:
        logger.warning(
            "BF-955: the report for work item %s is %d characters, over the "
            "%d-byte delivery limit in UTF-8. Before the first attempt, %d "
            "characters (%d bytes) were cut from the end of its text, ahead of "
            "any tool-failure disclosure; the thread, every retry and the "
            "outbox carry the same cut text",
            work_item_id, len(body), PROMOTED_REPORT_BODY_MAX_BYTES,
            bounded.cut_chars, bounded.cut_bytes,
        )

    # Minted ONCE, reused by every attempt and by any outbox redelivery. This
```

**P2-8.** `src/probos/cognitive/turn_promotion.py`
SEARCH:
```
                    agent_id=agent_id,
                    body=body,
                    created_at=created_at,
                    tool_trace_ref=tool_trace_ref,
                ),
                timeout=_REPORT_CANCEL_QUEUE_SECONDS,
```
REPLACE:
```
                    agent_id=agent_id,
                    body=posted,  # BF-955: the cancelled turn queues the text the attempts post
                    created_at=created_at,
                    tool_trace_ref=tool_trace_ref,
                ),
                timeout=_REPORT_CANCEL_QUEUE_SECONDS,
```

**P2-9.** `src/probos/cognitive/turn_promotion.py`
SEARCH:
```
                _append_report_message,
                store,
                thread_id=thread_id,
                message_id=message_id,
                agent_id=agent_id,
                body=body,
```
REPLACE:
```
                _append_report_message,
                store,
                thread_id=thread_id,
                message_id=message_id,
                agent_id=agent_id,
                body=posted,  # BF-955: every attempt posts the bounded text
```

**P2-10.** `src/probos/cognitive/turn_promotion.py`
SEARCH:
```
    queued = await _queue_pending_report(
        runtime=runtime,
        message_id=message_id,
        work_item_id=work_item_id,
        thread_id=thread_id,
        agent_id=agent_id,
        body=body,
```
REPLACE:
```
    queued = await _queue_pending_report(
        runtime=runtime,
        message_id=message_id,
        work_item_id=work_item_id,
        thread_id=thread_id,
        agent_id=agent_id,
        body=posted,  # BF-955: the outbox row carries the text the attempts posted
```

**N2-1.** `tests/test_bf955_promoted_report_bound.py`
SEARCH:
```
        pytest.param("over_by_one", marks=_BUILT),  # T1
```
REPLACE:
```
        "over_by_one",
```

**N2-2.** `tests/test_bf955_promoted_report_bound.py`
SEARCH:
```
        pytest.param("over_multibyte", marks=_BUILT),  # T1
```
REPLACE:
```
        "over_multibyte",
```

**N2-3.** `tests/test_bf955_promoted_report_bound.py`
SEARCH:
```
@_BUILT  # T2
@pytest.mark.parametrize("case", ["at_limit", "over_by_one", "over_multibyte"])
```
REPLACE:
```
@pytest.mark.parametrize("case", ["at_limit", "over_by_one", "over_multibyte"])
```

**N2-4.** `tests/test_bf955_promoted_report_bound.py`
SEARCH:
```
@_BUILT  # T3
@pytest.mark.parametrize("path", ["delivered", "exhausted"])
```
REPLACE:
```
@pytest.mark.parametrize("path", ["delivered", "exhausted"])
```

**N2-5.** `tests/test_bf955_promoted_report_bound.py`
SEARCH:
```
    ["at_limit", pytest.param("over_by_one", marks=_BUILT)],  # T4
```
REPLACE:
```
    ["at_limit", "over_by_one"],
```

**N2-6.** `tests/test_bf955_promoted_report_bound.py`
SEARCH:
```
@_BUILT  # T5
async def test_the_bound_is_the_limit_a_real_outbox_accepts(tmp_path) -> None:
```
REPLACE:
```
async def test_the_bound_is_the_limit_a_real_outbox_accepts(tmp_path) -> None:
```

**N2-7.** `tests/test_bf955_promoted_report_bound.py`
SEARCH:
```
    ["at_limit", pytest.param("over_by_one", marks=_BUILT)],  # T6
```
REPLACE:
```
    ["at_limit", "over_by_one"],
```

**N2-8.** `tests/test_bf955_promoted_report_bound.py`
SEARCH:
```
@_BUILT  # T7
@pytest.mark.parametrize("text", ["\ud800" + "x" * 10, "x" * 70_000 + "\ud800"], ids=["short", "long"])
```
REPLACE:
```
@pytest.mark.parametrize("text", ["\ud800" + "x" * 10, "x" * 70_000 + "\ud800"], ids=["short", "long"])
```

**N2-9.** `tests/test_bf955_promoted_report_bound.py`
SEARCH:
```
@_BUILT  # T8
@pytest.mark.parametrize("tail_case", ["too_large", "not_a_suffix"])
```
REPLACE:
```
@pytest.mark.parametrize("tail_case", ["too_large", "not_a_suffix"])
```

**N2-10.** `tests/test_bf955_promoted_report_bound.py`
SEARCH:
```
_ROOT = "aaaaaaaaaaaa"
_BUILT = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-955 M2 builds it")
```
REPLACE:
```
_ROOT = "aaaaaaaaaaaa"
```

After N2-10, `rg -n "_BUILT" tests/test_bf955_promoted_report_bound.py` must find 0 matches.

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-955 (DATE), #1757 -- a promoted report over 64 KiB keeps its durable retry.**
- **Base.** `_post_report` posted the composed report into its thread, which sets no size limit. After three failed attempts, or a cancellation, it queued the same text in the promoted-report outbox, which refuses a body over 65,536 UTF-8 bytes when it writes a row and when the drain reads one. A longer report whose attempts all failed was therefore logged (its first 400 characters) and not queued.
- **Fix.** `bound_promoted_report_body` (`cognitive/promoted_report_delivery.py`) bounds the composed text once, before the first attempt. A text within `PROMOTED_REPORT_BODY_MAX_BYTES` (65,536) is unchanged. A longer one keeps its head, cut on a character boundary, then a note saying how many characters were cut, then its tool-failure disclosure. Every attempt, the cancellation queue and the exhausted queue carry that text, so the drain replays what the first attempt posted. A cut is logged at WARNING with the work item and the sizes.
- **Changed.** A report over the limit is now cut on its first delivery too, when the thread store is free.
- **Not changed.** The episode and the outcome artifact get the full composed text, as before. The outbox's write and read checks, `workforce.py` and the thread store are not changed. The contract is `prompts/bf-955-promoted-report-bound.md`.

```

**P3-2.** `DECISIONS.md`. Append after BF-958's entry. Its last bullet must occur once; if it does not (BF-958 is not on the base), stop and return to the Architect.
SEARCH:
```
- *Reversal.* Revert the BF-958 commits.
```
REPLACE:
```
- *Reversal.* Revert the BF-958 commits.

### BF-955 -- A promoted report over 64 KiB keeps its durable retry (DATE, #1757)

- *Scope.* `cognitive/promoted_report_delivery.py` (`PROMOTED_REPORT_BODY_MAX_BYTES`, `BoundedReportBody`, `bound_promoted_report_body`), `cognitive/turn_promotion.py` (`_post_report`, the `ReportDelivery` docstring), tests. Contract `prompts/bf-955-promoted-report-bound.md`.
- *G1 (where).* Bounded once in `_post_report`, before the first attempt; every attempt and both queue paths carry the bounded text, so AD-1274's frozen message is identical across delivery and replay. Rejected: raising both outbox limits (the cliff moves; `workforce.py` changes), cutting only the queued copy, and a limit in the thread store.
- *G2 (how).* UTF-8 bytes, measured as the outbox measures; a text at the limit is unchanged; the head is cut on a code-point boundary, followed by a note giving the number of characters cut, followed by the tool-failure disclosure (AD-1248: the disclosure survives a budget). The note names no location: the only durable full copy is the outcome artifact, written only when `memory.recall_outcome_refs_enabled` is on.
- *G3 (evidence).* The episode and the outcome artifact keep the full composed text: a cut is a fact about the transcript, not about the work. AD-1248's byte identity between the transcript and the reused text holds within the limit.
- *G4 (one number, two copies).* `workforce.py` keeps its private 65,536; a test pins the two equal through a real store.
- *Not changed.* The outbox's write and read checks, the thread store, `compose_bypass_reply`, the log's 400 characters, the AD-1166 and AD-1226 episode response.
- *Residual.* Recorded limits L1 to L7 of the contract. Considered, deferred: a claim check (the full text of a cut report written to the attachment store and named in the note).
- *Reversal.* Revert the BF-955 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited: a Grep for `BF-95[0-9]` in `docs/development/roadmap.md` finds 0.

## 8. What this does NOT change

- `workforce.py`: the outbox, its write check at `:10500` and its read check at `:2113`. The AD-1346 rows are untouched.
- `ChatThreadStore`, `compose_bypass_reply`, `DmReply`, `PromotedReportDeliveryService`.
- What `_post_report` returns: `ReportDelivery.body` is the full composed text on every path.
- The log lines' 400 characters, the episode response (`:1540`), the artifact, and `plan_mode_response`.
- The `no_store` path, which neither posts nor queues.
- Every report within 65,536 bytes: T9, T1[at_limit] and the existing suites guard this.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/cognitive/promoted_report_delivery.py | `PROMOTED_REPORT_BODY_MAX_BYTES = 65_536` | `PROMOTED_REPORT_BODY_MAX_BYTES = 65_537` | T5, T2[over_by_one] |
| 2 | M2 | src/probos/cognitive/promoted_report_delivery.py | `if len(data) <= PROMOTED_REPORT_BODY_MAX_BYTES:` | `if len(data) < PROMOTED_REPORT_BODY_MAX_BYTES:` | T2[at_limit], T6[at_limit] |
| 3 | M2 | src/probos/cognitive/promoted_report_delivery.py | `tail = keep_tail if keep_tail and text.endswith(keep_tail) else ""` | `tail = ""` | T3 |
| 4 | M2 | src/probos/cognitive/promoted_report_delivery.py | `tail = keep_tail if keep_tail and text.endswith(keep_tail) else ""` | `tail = keep_tail` | T8[not_a_suffix] |
| 5 | M2 | src/probos/cognitive/promoted_report_delivery.py | `if len(tail_data) + _CUT_NOTE_RESERVE_BYTES >= PROMOTED_REPORT_BODY_MAX_BYTES:` | `if False:` | T8[too_large] |
| 6 | M2 | src/probos/cognitive/promoted_report_delivery.py | `head = prose_data[:room].decode("utf-8", "ignore")` | `head = prose_data[:room].decode("utf-8", "replace")` | T2[over_multibyte] |
| 7 | M2 | src/probos/cognitive/promoted_report_delivery.py | `cut_chars = len(text) - len(tail) - len(head)` | `cut_chars = 0` | T2, T6[over_by_one] |
| 8 | M2 | src/probos/cognitive/promoted_report_delivery.py | `except UnicodeEncodeError:` | `except KeyError:` | T7 |
| 9 | M2 | src/probos/cognitive/turn_promotion.py | `posted = bounded.text` | `posted = body` | T1[over_*], T3, T4[over_by_one] |
| 10 | M2 | src/probos/cognitive/turn_promotion.py | `posted = bounded.text` | `body = posted = bounded.text` | T1[over_*] (`outcome.body == text`), T3 |
| 11 | M2 | src/probos/cognitive/turn_promotion.py | `tail = body[len(prose):] if body.startswith(prose) else ""` | `tail = ""` | T3 |
| 12 | M2 | src/probos/cognitive/turn_promotion.py | `body=posted,  # BF-955: the cancelled turn queues the text the attempts post` | `body=body,` | T4[over_by_one] |
| 13 | M2 | src/probos/cognitive/turn_promotion.py | `body=posted,  # BF-955: every attempt posts the bounded text` | `body=body,` | T1[over_*], T3[delivered] |
| 14 | M2 | src/probos/cognitive/turn_promotion.py | `body=posted,  # BF-955: the outbox row carries the text the attempts posted` | `body=body,` | T1[over_*], T3[exhausted] |
| 15 | M2 | src/probos/cognitive/turn_promotion.py | `if bounded.cut_chars:` | `if False:` | T6[over_by_one] |

There is no campaign of record yet. The Builder runs these mutants on M2's head.

## 10. Recorded limits

- **L1.** A report over the limit is cut on its first delivery, even when the store is free (the base posted it whole). The cut part is kept durably only in the outcome artifact, and only when `memory.recall_outcome_refs_enabled` is on (default `False`).
- **L2.** The cut falls on a code-point boundary, not a grapheme cluster. This is the same limit `DmReply.render` documents (`dm_reply.py:830-831`).
- **L3.** A disclosure that leaves fewer than 257 bytes for the head is dropped, and the text is cut from its head alone. With the disclosure's 32-name and 64-entry bounds (`dm_reply.py:149-150`) this is not expected; it was not measured.
- **L4.** There are two copies of 65,536: the private one in `workforce.py` and the new public one. T5 is what keeps them equal.
- **L5.** A text that cannot be encoded as UTF-8 is not bounded. It goes down the delivery path exactly as on the base.
- **L6.** The bound runs on the event loop: one encode and one slice, linear in the text's size. Not measured.
- **L7.** The episode response equals the posted text's first characters only while the kept head is at least 500 characters. This holds for any disclosure under about 63,000 bytes.

## 11. Verified Against Codebase (2026-11-06, tree `fa030cae`, source equal to `48ed13bf`)

```
git diff --stat 48ed13bf HEAD -- turn_promotion.py workforce.py bypass_egress.py threads/__init__.py  -> empty
git diff --stat 48ed13bf HEAD -- promoted_report_delivery.py dm_reply.py dm/reply_value.py tests/test_ad1274_report_outbox.py tests/test_ad1248_slice_a_gaps.py -> empty
rg -n "_post_report|_queue_pending_report|_queue_on_cancel|compose_bypass_reply|_REPORT_DELIVERY_ATTEMPTS" turn_promotion.py
  76 import; 194 attempts=3; 1090 def _post_report; 1173 _queue_on_cancel; 1296 queued = await _queue_pending_report(; 1315 def; 1855 body = compose_bypass_reply(text) or _REPORT_EMPTY; 1885 report = await _post_report(; 2023 on_unconfirmed; 3031
Read turn_promotion.py:350-376 (ReportDelivery; AD-1248 rule :365-368), :1090-1373 (_post_report, _queue_pending_report), :1430-1563 (_store_promoted_episode; response :1540), :1842-1931, :2019-2030, :3029-3037
rg -n "_MAX_PROMOTED_REPORT_BODY_BYTES|def enqueue_promoted_report" workforce.py  -> 1644, 2113, 10474, 10500
rg -n "MAX_PROMOTED_REPORT_BODY" (repository)  -> workforce.py only (absence of any other copy)
rg -n "from probos.cognitive" workforce.py  -> 0 (workforce imports nothing from cognitive)
Read workforce.py:2077-2141 (PromotedReportOutboxEntry, read check), :10474-10533 (write check, INSERT OR IGNORE)
Read threads/__init__.py:1390-1464 (no body limit; agent bodies recomposed by compose_bypass_reply); :120 _CREW_SESSION_ID_RE; :189-196 ChatThreadMessage; :243 __init__(db_path); :275 create_thread(*, title, participants); :1560 list_messages
Read bypass_egress.py:77 (_MARKER_PROBE: [A2UI] | <intent emotion), :137-161 (byte-identical without a marker)
Read dm_reply.py:707 (_DISCLOSURE_PREFIX "\n\n"), :816-862 (render: body + tail; max_chars ladder), :869 with_body
Read promoted_report_delivery.py:1-205 (imports :22-27; PROMOTED_REPORT_SOURCE_KEY :35 once; drain replays entry.body :111)
rg -n "recall_outcome_refs_enabled" src/probos  -> config.py:1083 default False
Read tests/test_ad1274_report_outbox.py:1-104, :380-556 (harness)
Read tests/test_ad1248_slice_a_gaps.py:296-363 (byte identity :316; getsource of _finish_promoted_turn only :338)
rg -n "turn_promotion\.py|promoted_report_delivery\.py|dm_reply\.py" tests  -> ad1343_seam_registry.py:184-185 (resume_promoted_turn), ad1156 learning :951 / scope :1221, ad1248_slice_b :423, bf791 :344 (_OTHER_SINKS membership); none names _post_report or a line
rg -n "append_message_once|enqueue_promoted|cognitive/|_line|lineno" tests/fixtures/ad1346_effect_census.py  -> rows key (path, qualname) of launches/egress; lines found by AST (:259, :306, :351, :368, :428); no row in either edited file
rg -n "enqueue_promoted_report|_post_report|turn_promotion|promoted_report" tests/fixtures  -> ad1346_store_census.py:363-365 (workforce rows only)
rg -n "getsource|inspect\.|ast\.parse|read_text" tests/test_{ad1274*,ad1165_turn_promotion,bf732_promoted_run_slot}.py  -> bf732:207 (cognitive_agent only)
rg "\"\s*\*\s*(6[5-9]|[7-9][0-9]|[1-9][0-9]{2,})_?[0-9]{3}\b" tests/test_{ad1274,ad1165,ad1248,ad1226,bf733,bf825}*.py  -> 0 (no existing test posts a body this large)
rg -n "turn_promotion|promoted_report_delivery|probos\.workforce" docs/development/architecture-baseline.yaml  -> :1045 WorkItemStore only (srp debt; not touched)
Read scripts/check_architecture_principles.py:506-615 (srp is class-level; layer-import is cross-package; neither applies)
pyproject.toml:181 asyncio_mode = "auto"; :196 addopts "-n 16 --dist=loadfile"
Glob prompts/bf-95*.md -> 950, 952, 953; rg "BF-955|bf955" -> 0; rg "BF-95[0-9]" roadmap.md -> 0
rg "^- \*Reversal\.\* Revert the AD-1358 S1 commits\." DECISIONS.md -> :1490 (BF-957 appends after it and BF-958 after BF-957, per their contracts)
SEARCH uniqueness (rg -n, turn_promotion.py): :77, :365, :1128, :1130, :1143, :1160, :1162, :1202, :1215, :1296 each once; promoted_report_delivery.py: :27, :35 once
```

**Not measured.**
- The `--collect-only` counts: the bridge allows no pytest, so M0 records them.
- What the thread store does with a lone surrogate.

## 12. Prior Art and Blind Spots

- **Internal, adopted.** `DmReply.render(max_chars=…)` (`dm_reply.py:816-862`): the body is cut and the disclosure survives, on a code-point boundary. Its character budget is not used, because the outbox counts bytes; the docstring at `:822-824` gives the same reason in reverse.
- **Internal, adopted.** `promoted_report_metadata` ("identical metadata for a first append and durable replay") sets where the identical body is built.
- **External: Slack** ([chat.postMessage](https://api.slack.com/methods/chat.postMessage), [2018 changelog](https://api.Slack.Com/changelog/2018-04-truncating-really-long-messages)). It truncates text over 40,000 characters and reports `message_truncated` only to the sender. **Adapted:** the cut is announced in the message itself, for the Captain.
- **External: the claim-check pattern** ([Microsoft](https://learn.microsoft.com/azure/architecture/patterns/claim-check), [Symfony 8.2](https://symfony.com/blog/new-in-symfony-8-2-messenger-outbox-and-claim-check)). The large payload is stored elsewhere and a reference is sent, applied only above the limit. **Considered, deferred:** writing the cut report's full text to the attachment store regardless of AD-1226's flag would add a storage write on a failure path and override that flag's "OFF ⇒ byte-identical" rule.
- **`reference-projects.md`** (judged on 2026-11-06). No row concerns message delivery or outbox size, so no row was examined or updated. Overdue rows (AG-UI, never) are not relevant: considered, deferred.
- **Blind spots handled.**
  - A plain head cut would drop the disclosure, which `render` appends at the end.
  - The thread store re-composes agent bodies. The note carries no marker the probe matches, and the bound is deterministic, so the first delivery and the replay store the same text.
  - A lone surrogate would make the bound raise inside a reporter that must not raise; it is returned unchanged instead.
  - The cancellation arm receives the bounded text through the closure.
  - The free path changes too, and this is stated in PROGRESS.

## 13. Diff Reviewer: properties to verify

1. In `_post_report`, every `_append_report_message` call and both `_queue_pending_report` calls pass `posted`. `posted` is assigned once, before `message_id` is minted, and never reassigned.
2. Every `ReportDelivery` that `_post_report` returns carries `body`, the full composed text, as on the base.
3. `bound_promoted_report_body` never raises for any `str` input and any `keep_tail`. It is deterministic and returns its input unchanged at or under 65,536 UTF-8 bytes. For an encodable input over the limit, its result is at most 65,536 bytes, its head is a prefix of the input, and it ends with `keep_tail` exactly when the text ends with it and the tail leaves room.
4. `workforce.py`, `threads/__init__.py`, `bypass_egress.py` and `dm_reply.py` have no diff.
5. The note contains neither `[A2UI]` nor `<intent emotion`.
6. A cut is logged once at WARNING with the work item, the length, the limit, and the characters and bytes cut. Nothing is logged for a text within the limit.
7. The only new module-level import is `dataclasses` in `promoted_report_delivery.py`; `turn_promotion.py`'s import stays inside `probos.cognitive`.
8. At M1, each xfail case fails at an `AssertionError`. At M2, `_BUILT` is gone from the file.

## 14. Acceptance criteria

- G1, G2 and G3 as stated. The broad gate is green, with a receipt.
- T1 crosses the seam with real stores. A 65,537-byte report whose attempts are all exhausted is queued, and the drain replays it as the message the attempts posted, which equals the free-path message. A report at the limit behaves the same on both paths.
- The #1604 classification rows are unchanged, because `workforce.py` has no diff.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
