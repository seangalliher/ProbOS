"""AD-1165: a conversational turn that outgrows a reply becomes a task.

A Captain DM carries a 60s intent TTL. AD-1065's conversational agentic loop
routinely runs past it when asked to do real work, so the handler is cancelled
mid-flight and the Captain is told the agent did not respond — for a turn in
which it was working correctly. The fix is not a bigger TTL: work that does not
fit inside a reply stops being a reply and becomes a background task, and the
turn returns an acknowledgement inside the deadline.

These tests pin the four properties the design rests on:

* promotion is decided by ELAPSED EVIDENCE, so a fast turn is untouched;
* the in-flight run is NEVER cancelled or restarted — the same task continues,
  which is what stops already-performed browser clicks being replayed;
* every failure degrades to awaiting inline, never past today's behaviour;
* the promoted item is not dispatchable, so nothing executes it a second time.

The store-backed tests use the REAL ``WorkItemStore`` and the REAL
``ChatThreadStore`` on ``tmp_path``. That is deliberate and specific to this
wave: the defect family this AD sits in was a chain of mechanisms that passed
every test against a capable double and did nothing in production.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from probos.cognitive.cognitive_agent import (
    CognitiveAgent,
    _coerce_promotion_budget,
    _promotion_request_text,
)
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.turn_promotion import (
    PROMOTION_SOURCE,
    PROMOTION_TAG,
    _ACK_TEMPLATE,
    _REPORT_EMPTY,
    _REPORT_FAILED,
    run_with_promotion,
)
from probos.config import DmAgenticConfig, HybridDispatchConfig, SystemConfig
from probos.threads import ChatThreadStore
from probos.workforce import WorkItem, WorkItemStore


# ── harness ───────────────────────────────────────────────────────


class _FakeWorkItemStore:
    """Records the create/transition calls, backed by the REAL dataclass.

    Using ``WorkItem(**kwargs)`` rather than a permissive stub means a field
    name that does not exist on the real work item raises here instead of
    passing silently — the exact masking this AD's neighbours were bitten by.
    """

    def __init__(self) -> None:
        self.created: list[WorkItem] = []
        self.transitions: list[tuple[str, str, str]] = []
        self.create_error: Exception | None = None
        self.transition_error: Exception | None = None

    async def create_work_item(self, **kwargs):
        if self.create_error is not None:
            raise self.create_error
        item = WorkItem(status="open", **kwargs)
        self.created.append(item)
        return item

    async def transition_work_item(self, work_item_id, new_status, source="system"):
        if self.transition_error is not None:
            raise self.transition_error
        self.transitions.append((work_item_id, new_status, source))
        return None


class _FakeThreadStore:
    def __init__(self) -> None:
        self.appended: list[dict] = []
        self.error: Exception | None = None

    def append_message(self, thread_id, *, author_id, role, body, metadata=None):
        if self.error is not None:
            raise self.error
        self.appended.append({
            "thread_id": thread_id,
            "author_id": author_id,
            "role": role,
            "body": body,
            "metadata": metadata,
        })
        return None


def _runtime(*, work_items=None, threads=None):
    return SimpleNamespace(
        work_item_store=work_items,
        chat_thread_store=threads,
    )


async def _drain(hold: set) -> None:
    """Await every task the caller is holding, then let callbacks settle."""
    while hold:
        await asyncio.gather(*tuple(hold), return_exceptions=True)
        await asyncio.sleep(0)


async def _promote(
    work,
    *,
    runtime,
    thread_id="thread-1",
    request_text="type Hello World into my document",
    hold=None,
    promote_after=0.01,
):
    return await run_with_promotion(
        work,
        promote_after_seconds=promote_after,
        runtime=runtime,
        agent_id="agent-ezri",
        thread_id=thread_id,
        request_text=request_text,
        hold=hold if hold is not None else set(),
    )


# ── the budget is OFF ─────────────────────────────────────────────


async def test_zero_budget_awaits_inline_and_creates_no_task() -> None:
    """0 is the shipped default and must be byte-identical to AD-1164."""
    store = _FakeWorkItemStore()
    hold: set = set()

    async def _work() -> str:
        return "answered inline"

    text = await _promote(
        _work, runtime=_runtime(work_items=store), hold=hold, promote_after=0.0,
    )
    assert text == "answered inline"
    assert hold == set()
    assert store.created == []


async def test_zero_budget_propagates_the_run_exception() -> None:
    async def _work() -> str:
        raise RuntimeError("loop blew up")

    with pytest.raises(RuntimeError, match="loop blew up"):
        await _promote(
            _work, runtime=_runtime(work_items=_FakeWorkItemStore()), promote_after=0.0,
        )


# ── the turn fits inside a reply ──────────────────────────────────


async def test_fast_turn_returns_its_own_text_and_is_never_promoted() -> None:
    store = _FakeWorkItemStore()
    hold: set = set()

    async def _work() -> str:
        return "Done, Captain."

    text = await _promote(
        _work, runtime=_runtime(work_items=store), hold=hold, promote_after=30.0,
    )
    assert text == "Done, Captain."
    assert store.created == []
    await _drain(hold)
    assert hold == set()


async def test_fast_turn_re_raises_the_run_exception_into_the_caller() -> None:
    """The inline path keeps the caller's honest-degrade reachable."""
    async def _work() -> str:
        raise RuntimeError("loop blew up")

    with pytest.raises(RuntimeError, match="loop blew up"):
        await _promote(
            _work,
            runtime=_runtime(work_items=_FakeWorkItemStore()),
            promote_after=30.0,
        )


# ── the turn outgrows a reply ─────────────────────────────────────


async def test_slow_turn_is_promoted_and_acknowledged_immediately() -> None:
    store = _FakeWorkItemStore()
    threads = _FakeThreadStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "Typed Hello World into the document."

    text = await _promote(
        _work, runtime=_runtime(work_items=store, threads=threads), hold=hold,
    )

    assert len(store.created) == 1
    item = store.created[0]
    assert text == _ACK_TEMPLATE.format(work_item_id=item.id)
    # The acknowledgement lands while the run is still going — that is the
    # entire point: the turn returns inside the chat TTL.
    assert threads.appended == []

    release.set()
    await _drain(hold)

    assert [m["body"] for m in threads.appended] == [
        "Typed Hello World into the document."
    ]
    assert threads.appended[0]["role"] == "agent"
    assert threads.appended[0]["author_id"] == "agent-ezri"
    assert threads.appended[0]["metadata"] == {
        "work_item_id": item.id, "source": PROMOTION_SOURCE,
    }
    assert store.transitions == [
        (item.id, "in_progress", "agent-ezri"),
        (item.id, "done", "agent-ezri"),
    ]


async def test_the_promoted_run_is_never_restarted() -> None:
    """Promotion stops WAITING for the run; it does not cancel or replay it.

    A design that re-dispatched would redo every click the agent had already
    performed, which is the specific hazard for the browser work this unblocks.
    """
    runs = 0
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        nonlocal runs
        runs += 1
        await release.wait()
        return "done"

    threads = _FakeThreadStore()
    await _promote(
        _work,
        runtime=_runtime(work_items=_FakeWorkItemStore(), threads=threads),
        hold=hold,
    )
    release.set()
    await _drain(hold)

    assert runs == 1
    assert [m["body"] for m in threads.appended] == ["done"]


async def test_promoted_work_item_carries_the_captains_request() -> None:
    store = _FakeWorkItemStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "ok"

    await _promote(
        _work,
        runtime=_runtime(work_items=store, threads=_FakeThreadStore()),
        hold=hold,
        request_text="type Hello World into my document",
    )
    item = store.created[0]
    assert item.title == "type Hello World into my document"
    assert item.description == "type Hello World into my document"
    assert item.work_type == "task"
    assert item.assigned_to == "agent-ezri"
    assert item.metadata["source"] == PROMOTION_SOURCE
    assert item.metadata["thread_id"] == "thread-1"

    release.set()
    await _drain(hold)


async def test_promoted_item_is_not_dispatchable() -> None:
    """Nothing may execute the promoted run a second time.

    The run already has an owner. ``WorkItemRouter.is_dispatchable`` reads
    ``metadata["dispatchable"]`` and ``hybrid_dispatch.dispatchable_tags``; a
    promoted item must trip neither.
    """
    store = _FakeWorkItemStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "ok"

    await _promote(
        _work,
        runtime=_runtime(work_items=store, threads=_FakeThreadStore()),
        hold=hold,
    )
    item = store.created[0]
    assert "dispatchable" not in item.metadata
    assert PROMOTION_TAG in item.tags
    assert not set(item.tags) & set(HybridDispatchConfig().dispatchable_tags)

    release.set()
    await _drain(hold)


async def test_a_long_request_is_shortened_for_the_title_only() -> None:
    store = _FakeWorkItemStore()
    release = asyncio.Event()
    hold: set = set()
    request = "please " + ("x" * 500)

    async def _work() -> str:
        await release.wait()
        return "ok"

    await _promote(
        _work,
        runtime=_runtime(work_items=store, threads=_FakeThreadStore()),
        hold=hold,
        request_text=request,
    )
    item = store.created[0]
    assert len(item.title) == 120
    assert item.title.endswith("\u2026")
    assert item.description == request

    release.set()
    await _drain(hold)


# ── the promoted run does not end well ────────────────────────────


async def test_a_failed_promoted_run_reports_and_marks_the_item_failed() -> None:
    store = _FakeWorkItemStore()
    threads = _FakeThreadStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        raise RuntimeError("the browser went away")

    await _promote(
        _work, runtime=_runtime(work_items=store, threads=threads), hold=hold,
    )
    release.set()
    await _drain(hold)

    item = store.created[0]
    assert [m["body"] for m in threads.appended] == [_REPORT_FAILED]
    assert store.transitions[-1] == (item.id, "failed", "agent-ezri")


async def test_a_silent_promoted_run_still_reports() -> None:
    """The Captain was told a report would arrive; silence is not an option."""
    store = _FakeWorkItemStore()
    threads = _FakeThreadStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "   "

    await _promote(
        _work, runtime=_runtime(work_items=store, threads=threads), hold=hold,
    )
    release.set()
    await _drain(hold)

    assert [m["body"] for m in threads.appended] == [_REPORT_EMPTY]
    assert store.transitions[-1][1] == "done"


# ── BF-702: the intent self-tag must not reach the Captain ────────


async def test_the_intent_self_tag_is_stripped_from_a_report() -> None:
    """THE BF-702 regression, taken verbatim from the live transcript.

    A promoted run returns the agentic loop's text directly and never passes
    through ``DmReplyPipeline.step_7_divergence_check``, the step that parses
    and strips this tag precisely so it "never leaks to the Captain". The
    reference vessel's chat showed one.
    """
    store = _FakeWorkItemStore()
    threads = _FakeThreadStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return (
            'Done — "Hello from Ezri" has been typed into the document. '
            "I can see the text has been entered.\n\n<intent emotion=warm>"
        )

    await _promote(
        _work, runtime=_runtime(work_items=store, threads=threads), hold=hold,
    )
    release.set()
    await _drain(hold)

    body = threads.appended[0]["body"]
    assert "<intent" not in body
    assert "emotion=warm" not in body
    assert body.startswith('Done — "Hello from Ezri" has been typed')
    assert body.endswith("the text has been entered.")


async def test_a_report_that_is_only_a_tag_reads_as_empty() -> None:
    """Stripping must not post a blank message.

    If the tag was the whole reply, the result is silence -- and the Captain
    was promised a report, so it takes the empty-report wording instead.
    """
    store = _FakeWorkItemStore()
    threads = _FakeThreadStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "<intent emotion=warm>"

    await _promote(
        _work, runtime=_runtime(work_items=store, threads=threads), hold=hold,
    )
    release.set()
    await _drain(hold)

    assert [m["body"] for m in threads.appended] == [_REPORT_EMPTY]
    assert store.transitions[-1][1] == "done"


async def test_an_untagged_report_is_unchanged() -> None:
    """The strip is a no-op on ordinary text -- no truncation, no reflow."""
    store = _FakeWorkItemStore()
    threads = _FakeThreadStore()
    release = asyncio.Event()
    hold: set = set()
    original = "Filed the summary in the ship's records. Two sections, no gaps."

    async def _work() -> str:
        await release.wait()
        return original

    await _promote(
        _work, runtime=_runtime(work_items=store, threads=threads), hold=hold,
    )
    release.set()
    await _drain(hold)

    assert [m["body"] for m in threads.appended] == [original]


async def test_an_inline_tag_does_not_merge_adjacent_words() -> None:
    """BF-603's collapse-to-one-space behaviour must survive this path."""
    store = _FakeWorkItemStore()
    threads = _FakeThreadStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "Typed it in.<intent emotion=warm>Anything else?"

    await _promote(
        _work, runtime=_runtime(work_items=store, threads=threads), hold=hold,
    )
    release.set()
    await _drain(hold)

    body = threads.appended[0]["body"]
    assert "<intent" not in body
    assert "in.Anything" not in body, "words merged where the tag was removed"
    assert "Typed it in. Anything else?" == body


async def test_a_cancelled_promoted_run_leaves_the_item_in_progress() -> None:
    """Cancellation means unfinished, not finished. The board must say so."""
    store = _FakeWorkItemStore()
    threads = _FakeThreadStore()
    hold: set = set()

    async def _work() -> str:
        await asyncio.Event().wait()
        return "never"

    await _promote(
        _work, runtime=_runtime(work_items=store, threads=threads), hold=hold,
    )
    for task in tuple(hold):
        task.cancel()
    await _drain(hold)

    item = store.created[0]
    assert store.transitions == [(item.id, "in_progress", "agent-ezri")]
    assert threads.appended == []


# ── nowhere to promote TO: degrade to the inline wait ─────────────


async def test_no_thread_id_waits_inline_rather_than_promising_a_report() -> None:
    store = _FakeWorkItemStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "the real answer"

    async def _release_soon() -> None:
        await asyncio.sleep(0.02)
        release.set()

    releaser = asyncio.create_task(_release_soon())
    text = await _promote(
        _work,
        runtime=_runtime(work_items=store, threads=_FakeThreadStore()),
        hold=hold,
        thread_id="",
    )
    await releaser
    assert text == "the real answer"
    assert store.created == []


async def test_no_work_item_store_waits_inline() -> None:
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "the real answer"

    async def _release_soon() -> None:
        await asyncio.sleep(0.02)
        release.set()

    releaser = asyncio.create_task(_release_soon())
    text = await _promote(
        _work, runtime=_runtime(work_items=None, threads=_FakeThreadStore()), hold=hold,
    )
    await releaser
    assert text == "the real answer"


async def test_a_raising_work_item_store_waits_inline() -> None:
    store = _FakeWorkItemStore()
    store.create_error = RuntimeError("db is gone")
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "the real answer"

    async def _release_soon() -> None:
        await asyncio.sleep(0.02)
        release.set()

    releaser = asyncio.create_task(_release_soon())
    text = await _promote(
        _work, runtime=_runtime(work_items=store, threads=_FakeThreadStore()), hold=hold,
    )
    await releaser
    assert text == "the real answer"


async def test_a_failed_in_progress_transition_still_promotes_and_reports() -> None:
    """The board row being wrong must not cost the Captain the work."""
    store = _FakeWorkItemStore()
    store.transition_error = RuntimeError("state machine said no")
    threads = _FakeThreadStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "typed it"

    text = await _promote(
        _work, runtime=_runtime(work_items=store, threads=threads), hold=hold,
    )
    assert text == _ACK_TEMPLATE.format(work_item_id=store.created[0].id)

    release.set()
    await _drain(hold)
    assert [m["body"] for m in threads.appended] == ["typed it"]


async def test_a_raising_thread_store_still_closes_the_work_item(caplog) -> None:
    store = _FakeWorkItemStore()
    threads = _FakeThreadStore()
    threads.error = ValueError("chat_thread_message_invalid")
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "typed it"

    await _promote(
        _work, runtime=_runtime(work_items=store, threads=threads), hold=hold,
    )
    release.set()
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.turn_promotion"):
        await _drain(hold)

    assert store.transitions[-1][1] == "done"
    assert any("typed it" in r.getMessage() for r in caplog.records)


async def test_no_thread_store_records_the_report_in_the_log(caplog) -> None:
    store = _FakeWorkItemStore()
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "typed it"

    await _promote(
        _work, runtime=_runtime(work_items=store, threads=None), hold=hold,
    )
    release.set()
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.turn_promotion"):
        await _drain(hold)

    assert any("typed it" in r.getMessage() for r in caplog.records)
    assert store.transitions[-1][1] == "done"


# ── against the REAL stores ───────────────────────────────────────


@pytest_asyncio.fixture
async def real_stores(tmp_path: Path):
    work_items = WorkItemStore(db_path=str(tmp_path / "wis.db"))
    await work_items.start()
    threads = ChatThreadStore(tmp_path / "threads.db")
    try:
        yield work_items, threads
    finally:
        await work_items.stop()


async def test_end_to_end_against_the_real_stores(real_stores) -> None:
    """The whole promotion round trip, with nothing faked.

    Proves the board row is really created, really moves open -> in_progress ->
    done through the AD-498 state machine, and that the report really commits
    to the thread the Captain is watching.
    """
    work_items, threads = real_stores
    thread = threads.create_thread(title="Ezri", participants=["agentezri"])
    runtime = _runtime(work_items=work_items, threads=threads)
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return "Hello World is in the document."

    text = await run_with_promotion(
        _work,
        promote_after_seconds=0.01,
        runtime=runtime,
        agent_id="agentezri",
        thread_id=thread.id,
        request_text="type Hello World into my document",
        hold=hold,
    )

    items = await work_items.list_work_items()
    promoted = [i for i in items if i.metadata.get("source") == PROMOTION_SOURCE]
    assert len(promoted) == 1
    assert text == _ACK_TEMPLATE.format(work_item_id=promoted[0].id)
    assert (await work_items.get_work_item(promoted[0].id)).status == "in_progress"

    release.set()
    await _drain(hold)

    assert (await work_items.get_work_item(promoted[0].id)).status == "done"
    bodies = [m.body for m in threads.list_messages(thread.id)]
    assert bodies == ["Hello World is in the document."]


# ── wording: the acknowledgement must not read as a capability gap ──


@pytest.mark.parametrize(
    "text",
    [
        _ACK_TEMPLATE.format(work_item_id="abc123"),
        _REPORT_EMPTY,
        _REPORT_FAILED,
    ],
)
def test_promotion_wording_is_not_read_as_a_capability_gap(text: str) -> None:
    """A match here would route a routine acknowledgement into self-modification."""
    assert _CAPABILITY_GAP_RE.search(text) is None


def test_the_promotion_tag_is_not_a_dispatchable_tag() -> None:
    """Drift guard: adding PROMOTION_TAG to dispatchable_tags = double execution."""
    assert PROMOTION_TAG not in HybridDispatchConfig().dispatchable_tags


# ── the arming site in cognitive_agent ────────────────────────────


def test_budget_defaults_to_off() -> None:
    assert SystemConfig().dm_agentic.promote_to_task_after_seconds == 0.0


def test_budget_is_bounded() -> None:
    assert DmAgenticConfig(promote_to_task_after_seconds=35).promote_to_task_after_seconds == 35.0
    with pytest.raises(Exception):
        DmAgenticConfig(promote_to_task_after_seconds=-1)
    with pytest.raises(Exception):
        DmAgenticConfig(promote_to_task_after_seconds=601)


@pytest.mark.parametrize(
    "raw",
    [None, "35", True, False, MagicMock(), float("nan"), float("inf"), 0, 0.0, -5.0],
)
def test_a_non_numeric_or_non_positive_budget_reads_as_off(raw) -> None:
    """A MagicMock config auto-creates the attribute as a truthy proxy.

    Comparing that proxy would make the arming decision on something that is not
    a number. Anything that is not a real finite positive float means OFF.
    """
    assert _coerce_promotion_budget(raw) == 0.0


def test_a_real_budget_is_read() -> None:
    assert _coerce_promotion_budget(35) == 35.0
    assert _coerce_promotion_budget(0.5) == 0.5


def test_request_text_prefers_the_captains_raw_message() -> None:
    obs = {"params": {"captain_message": "type hello", "text": "[scene] type hello"}}
    assert _promotion_request_text(obs, "assembled prompt") == "type hello"


def test_request_text_falls_back_through_text_then_the_prompt() -> None:
    assert _promotion_request_text({"params": {"text": "type hello"}}, "x") == "type hello"
    assert _promotion_request_text({"params": {}}, "assembled") == "assembled"
    assert _promotion_request_text({}, "assembled") == "assembled"
    assert _promotion_request_text({"params": "not-a-dict"}, "assembled") == "assembled"


# ── the arming site, end to end through the agent method ──────────


class _SlowOutcome:
    final_text = "Typed Hello World into the document."


class _SlowExecutor:
    release: asyncio.Event

    def __init__(self, *, llm_client) -> None:
        pass

    async def run(self, **kwargs):
        await _SlowExecutor.release.wait()
        return _SlowOutcome()


class _FastExecutor:
    def __init__(self, *, llm_client) -> None:
        pass

    async def run(self, **kwargs):
        return _SlowOutcome()


def _agent(runtime):
    agent = SimpleNamespace(
        _runtime=runtime,
        _llm_client=object(),
        id="agentezri",
        callsign="Ezri",
        agent_type="counselor",
        department="science",
        rank="lieutenant",
        _promoted_turn_tasks=set(),
    )
    agent._conversational_agentic_will_run = (
        lambda obs: CognitiveAgent._conversational_agentic_will_run(agent, obs)
    )
    return agent


def _dm_runtime(*, budget, work_items, threads):
    return SimpleNamespace(
        config=SimpleNamespace(
            dm_agentic=DmAgenticConfig(
                enabled=True, promote_to_task_after_seconds=budget,
            ),
        ),
        work_item_store=work_items,
        chat_thread_store=threads,
    )


async def _turn(agent):
    return await CognitiveAgent._maybe_run_conversational_agentic(
        agent,
        {
            "intent": "direct_message",
            "thread_id": "threadone",
            "params": {"captain_message": "type Hello World into my document"},
        },
        system_prompt="You are Ezri.",
        user_message="a very long assembled prompt",
    )


async def test_the_turn_promotes_through_the_agent_method(monkeypatch) -> None:
    _SlowExecutor.release = asyncio.Event()
    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", _SlowExecutor,
    )
    store = _FakeWorkItemStore()
    threads = _FakeThreadStore()
    agent = _agent(_dm_runtime(budget=0.01, work_items=store, threads=threads))

    text = await _turn(agent)
    assert text == _ACK_TEMPLATE.format(work_item_id=store.created[0].id)
    # The board row records what the Captain asked, not the assembled prompt.
    assert store.created[0].description == "type Hello World into my document"

    _SlowExecutor.release.set()
    await _drain(agent._promoted_turn_tasks)
    assert [m["body"] for m in threads.appended] == [
        "Typed Hello World into the document."
    ]


async def test_a_fast_turn_through_the_agent_method_is_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", _FastExecutor,
    )
    store = _FakeWorkItemStore()
    agent = _agent(_dm_runtime(budget=30.0, work_items=store, threads=_FakeThreadStore()))

    assert await _turn(agent) == "Typed Hello World into the document."
    assert store.created == []
    assert agent._promoted_turn_tasks == set()


async def test_the_default_budget_never_touches_the_task_holder(monkeypatch) -> None:
    """Default-OFF byte identity: the promotion module is not even imported."""
    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", _FastExecutor,
    )
    store = _FakeWorkItemStore()
    agent = _agent(_dm_runtime(budget=0.0, work_items=store, threads=_FakeThreadStore()))
    del agent._promoted_turn_tasks  # would AttributeError if the branch ran

    assert await _turn(agent) == "Typed Hello World into the document."
    assert store.created == []
