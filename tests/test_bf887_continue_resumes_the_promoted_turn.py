"""BF-887 (#1163): an approved ``continue`` resumes the promoted turn it parked.

Measured on the reference vessel 2026-10-07: a promoted turn stopped at its step
limit, filed a ``continue`` ask linked to its work item and parked the item; the
Captain approved; the request reached ``fulfilled`` and AD-855 logged "resumed
and re-dispatched" -- and nothing ran for eleven minutes. AD-855 handed the item
to ``WorkItemRouter``, which drops an AD-1165 promoted item by design. Every link
was correct and the chain was dead, because the suite asserted the hand-off at a
stub router that accepted everything.

So the seam tests here run the chain on the real components: the
``CognitiveAgent`` turn (promotion, AD-1164's ask, AD-1204's park), the AD-857
decide route and AD-1211's fulfilment over the ``CapabilityRequestStore``, the
AD-855 driver, the ``WorkItemStore``, the ``WorkItemRouter`` and its
``DepartmentDispatcher`` (asserted never to be handed the item), the
``AgentRegistry``, AD-1165's reporter and the ``ChatThreadStore``, whose commit
callback is BF-720's live refresh. Stand-ins: the model (a scripted
``WorkItemAgenticExecutor``), the runtime (a namespace carrying those stores),
its local event emitter (``_Bus``: a held task per listener, as
``runtime._emit_event_local`` makes), and the activation dispatcher under the
router and the router's member list (``_Dispatcher`` records each TaskEvent).

Families: S the seam; A AD-855's report for an ordinary item; N a resume nothing
can take; C the continuation store and its contracts; L every way a turn ends
lets go of the next pass it kept; G the long-run grant and a drift guard; O a
segment ends its item only while the item is its own, and the hand-off reads the
item as it is now (A-3 and A-4, the second and third reviews).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from probos.activation.dispatcher import DispatchResult
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive import turn_promotion
from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.continue_or_ask import (
    _continuation_block,
    continuation_task_text,
    file_continue_request,
)
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.standing_interests import stranded_reason_code
from probos.cognitive.turn_cost import _COST_STOP_LEAD_WITH_WORK
from probos.cognitive.turn_promotion import (
    _ACK_TEMPLATE,
    _REPORT_ABANDON_UNCONFIRMED,
    _REPORT_ABANDONED,
    _REPORT_FAILED,
    _REPORT_RESUME_LOST,
    PROMOTION_SOURCE,
    PROMOTION_TAG,
    RESUME_MOVED_ON,
    RESUME_NO_AGENT,
    RESUME_NO_CONTINUATION,
    RESUME_START_FAILED,
    RESUME_STARTED,
    RESUME_UNIDENTIFIED,
    PromotedTurnContinuations,
    _create_promoted_work_item,
    is_promoted_turn,
    resume_promoted_turn,
    start_resumed_run,
)
from probos.config import DmAgenticConfig, ExecutionConfig, HybridDispatchConfig
from probos.dm_reply import ToolFailures
from probos.execution.long_runs import EXECUTION_LONG_RUN_GRANT_KEY
from probos.mesh.department_dispatcher import DepartmentDispatcher
from probos.mesh.work_item_router import WorkItemRouter
from probos.routers.capability_requests import decide_capability_request
from probos.routers.deps import get_runtime
from probos.routers.workforce import router as workforce_router
from probos.substrate.registry import AgentRegistry
from probos.threads import ChatThreadStore
from probos.workforce import WorkItemStore

AGENT = "counselor_counselor_0_67c601cb"
ASK = (
    "For each of the top 15 Python packages on PyPI, tell me the release date of "
    "its current version and its license."
)
ASSEMBLED = "[working memory] [recall] [session history]\n\n" + ASK
PARTIAL = "A few JSON blobs were too large to parse cleanly; pulling version, license and date."
PARTIAL_2 = "Eleven of fifteen done: requests, urllib3, certifi, idna, charset-normalizer."
FINAL = "| package | released | license |\n| requests | 2026-08-18 | Apache-2.0 |"
STOP_NOTICE = "I have stopped and need your approval"
_SETTLE_S = 10.0
_DRIVER_LOG = "probos.cognitive.capability_gap_driver"
_PROMOTION_LOG = "probos.cognitive.turn_promotion"


# -- doubles -------------------------------------------------------------------


class _Bus:
    """``runtime._emit_event_local`` for a coroutine listener: a held task per event."""

    def __init__(self) -> None:
        self.listeners: list[Any] = []
        self.tasks: set[asyncio.Task[Any]] = set()
        self.emitted: list[str] = []

    def emit(self, event_type: Any, data: dict[str, Any]) -> None:
        kind = str(getattr(event_type, "value", event_type))
        self.emitted.append(kind)
        event = {"type": kind, "data": dict(data or {}), "timestamp": time.time()}
        for fn in self.listeners:
            task = asyncio.create_task(fn(event))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)


class _Dispatcher:
    """The activation dispatcher under ``WorkItemRouter``: records every TaskEvent."""

    def __init__(self, accepted: int = 1) -> None:
        self.events: list[Any] = []
        self.accepted = accepted

    async def dispatch(self, event: Any) -> DispatchResult:
        self.events.append(event)
        return DispatchResult(
            event_id="e", target_count=1, accepted=self.accepted,
            rejected=1 - self.accepted, unroutable=0,
        )


class _Members:
    def all(self) -> list[Any]:
        return [SimpleNamespace(id=AGENT)]


class _PassRaised(RuntimeError):
    """A scripted pass that raises, as a model or tool outage makes one."""


class _Executor:
    """The model, scripted. One instance per turn, as the agent makes it.

    Each pass takes the next outcome, and a ``_PassRaised`` there is raised
    instead; ``gates`` holds a pass until the test releases it, which is how a
    turn is made to outlive its promotion budget, or its deadline.
    """

    script: list[WorkItemAgenticOutcome | _PassRaised] = []
    gates: dict[int, asyncio.Event] = {}
    calls: list[dict[str, Any]] = []

    def __init__(self, *, llm_client: Any) -> None:
        pass

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        index = len(_Executor.calls)
        _Executor.calls.append(kwargs)
        gate = _Executor.gates.get(index)
        if gate is not None:
            await asyncio.wait_for(gate.wait(), timeout=_SETTLE_S)
        outcome = _Executor.script[index]
        if isinstance(outcome, _PassRaised):
            raise outcome
        return outcome


class _Episodes:
    def __init__(self) -> None:
        self.stored: list[Any] = []

    async def store(self, episode: Any) -> None:
        self.stored.append(episode)


class _HeldFirstAgentPost(ChatThreadStore):
    """Holds the first agent message's commit, in its worker thread, until ``release``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.holding = threading.Event()
        self.release = threading.Event()
        self._held_once = False

    def append_message_once(self, thread_id: str, **kwargs: Any) -> Any:
        if kwargs.get("role") == "agent" and not self._held_once:
            self._held_once = True
            self.holding.set()
            assert self.release.wait(_SETTLE_S), "premise: the held post was released"
        return super().append_message_once(thread_id, **kwargs)


class _DecidedOnFiling(CapabilityRequestStore):
    """A decision that lands while the turn is still filing: approved and fulfilled at once."""

    async def file_request(self, **kwargs: Any) -> Any:
        filed = await super().file_request(**kwargs)
        await self.decide(filed.id, True, reason="", decided_by="captain")
        return await self.mark_fulfilled(filed.id)


def _outcome(text: str, stopped_reason: str) -> WorkItemAgenticOutcome:
    # As the real executor returns one: its failures are always correlated, so
    # merge-open (``correlate_tool_outcomes``); the dataclass default is not.
    return WorkItemAgenticOutcome(
        final_text=text, stopped_reason=stopped_reason,
        tool_failures=ToolFailures.from_mapping({}, merge_open=True),
        tool_defect_evaluated=True,
    )


def _cut(text: str) -> WorkItemAgenticOutcome:
    return _outcome(text, "max_iterations")


def _done(text: str) -> WorkItemAgenticOutcome:
    return _outcome(text, "complete")


# -- the rig -------------------------------------------------------------------


@pytest.fixture
def scripted(monkeypatch):
    _Executor.script = []
    _Executor.gates = {}
    _Executor.calls = []
    monkeypatch.setattr("probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", _Executor)
    yield _Executor
    for gate in _Executor.gates.values():
        gate.set()


@pytest.fixture
async def make_rig(tmp_path):
    built: list[SimpleNamespace] = []

    async def make(
        *,
        requests_cls: type[CapabilityRequestStore] = CapabilityRequestStore,
        threads_cls: type[ChatThreadStore] = ChatThreadStore,
        dm: DmAgenticConfig | None = None,
        execution: ExecutionConfig | None = None,
        with_agent: bool = True,
        accepted: int = 1,
        episodic: bool = False,
    ) -> SimpleNamespace:
        tag = f"r{len(built)}"
        bus = _Bus()
        work_items = WorkItemStore(db_path=str(tmp_path / f"{tag}_wis.db"), tick_interval=1000)
        await work_items.start()
        requests = requests_cls(db_path=str(tmp_path / f"{tag}_cap.db"), emit_event=bus.emit)
        await requests.start()
        threads = threads_cls(tmp_path / f"{tag}_threads.db")
        committed: list[Any] = []
        threads.set_message_committed_callback(committed.append)
        dispatcher = _Dispatcher(accepted)
        hybrid = HybridDispatchConfig()
        router = WorkItemRouter(
            dispatcher=dispatcher,
            department_dispatcher=DepartmentDispatcher(
                hebbian_router=None, ontology=None, config=hybrid,
            ),
            registry=_Members(), config=hybrid,
        )
        registry = AgentRegistry()
        config = SimpleNamespace(
            dm_agentic=dm or DmAgenticConfig(
                enabled=True, continue_or_ask_enabled=True,
                continue_or_ask_max_passes=1, promote_to_task_after_seconds=0.05,
            ),
        )
        if execution is not None:
            config.execution = execution
        runtime = SimpleNamespace(
            config=config,
            work_item_store=work_items,
            capability_request_store=requests,
            chat_thread_store=threads,
            work_item_router=router,
            registry=registry,
            event_log=None,
            episodic_memory=_Episodes() if episodic else None,
        )
        driver = CapabilityGapDriver(
            runtime=runtime, work_item_store=work_items, capability_request_store=requests,
        )
        runtime.capability_gap_driver = driver
        bus.listeners.append(driver.on_capability_event)
        agent = None
        if with_agent:
            agent = CognitiveAgent(agent_id=AGENT, instructions="You are Ezri.")
            agent._runtime = runtime
            agent._llm_client = object()
            agent.callsign = "Ezri"
            await registry.register(agent)
        thread = threads.get_or_create_default_for_agent(AGENT, "Ezri")
        rig = SimpleNamespace(
            bus=bus, work_items=work_items, requests=requests, threads=threads,
            committed=committed, dispatcher=dispatcher, router=router, registry=registry,
            runtime=runtime, driver=driver, agent=agent, thread=thread,
        )
        built.append(rig)
        return rig

    try:
        yield make
    finally:
        for rig in built:
            await _settle(rig)
            await rig.requests.stop()
            await rig.work_items.stop()


async def _settle(rig: SimpleNamespace) -> None:
    """Join every listener task and every task the agent holds, bounded; fail loudly if not."""
    deadline = time.monotonic() + _SETTLE_S
    while True:
        held = set(rig.bus.tasks)
        if rig.agent is not None:
            held |= {t for t in rig.agent._promoted_turn_tasks if not t.done()}
        if not held:
            return
        remaining = deadline - time.monotonic()
        assert remaining > 0, f"premise: the rig settles within {_SETTLE_S}s ({len(held)} left)"
        await asyncio.wait(held, timeout=remaining)
        for task in held:
            if task.done() and not task.cancelled() and task.exception() is not None:
                if isinstance(task.exception(), _PassRaised):
                    continue  # a pass the test scripted to raise; its reporter took it
                raise task.exception()


async def _turn(rig: SimpleNamespace) -> str:
    return await rig.agent._maybe_run_conversational_agentic(
        {"intent": "direct_message", "thread_id": rig.thread.id, "params": {"captain_message": ASK}},
        system_prompt="You are Ezri.",
        user_message=ASSEMBLED,
    )


async def _promote_and_stop(rig: SimpleNamespace, gate: asyncio.Event) -> tuple[Any, Any]:
    """Run the turn past its promotion budget, then let its first pass end."""
    ack = await _turn(rig)
    items = await rig.work_items.list_work_items(status="in_progress")
    assert len(items) == 1, "premise: the turn was promoted to one work item"
    assert ack == _ACK_TEMPLATE.format(work_item_id=items[0].id)
    gate.set()
    await _settle(rig)
    return items[0], await rig.requests.list_pending()


async def _approve(rig: SimpleNamespace, request_id: str) -> dict[str, Any]:
    result = await decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=True), runtime=rig.runtime,
    )
    await _settle(rig)
    return result


def _agent_bodies(rig: SimpleNamespace) -> list[str]:
    return [m.body for m in rig.threads.list_messages(rig.thread.id) if m.role == "agent"]


def _fulfilled_event(request_id: str) -> dict[str, Any]:
    return {"type": "capability_request_fulfilled", "data": {"id": request_id}, "timestamp": 0.0}


async def _parked_promoted(
    rig: SimpleNamespace,
    *,
    thread: bool = True,
    fulfil: bool = True,
    before_fulfil: Callable[[Any], Awaitable[None]] | None = None,
) -> tuple[Any, Any]:
    """A promoted turn's item, parked on its continue ask, the ask then approved and fulfilled."""
    if thread:
        item = await _create_promoted_work_item(
            runtime=rig.runtime, agent_id=AGENT, thread_id=rig.thread.id, request_text=ASK,
        )
    else:
        item = await rig.work_items.create_work_item(
            title=ASK, work_type="task", status="in_progress", assigned_to=AGENT,
            tags=[PROMOTION_TAG], metadata={"source": PROMOTION_SOURCE},
        )
    request_id = await file_continue_request(
        rig.runtime, agent_id=AGENT, thread_id=rig.thread.id, base_task_text=ASK,
        passes=1, work_item_id=item.id,
    )
    assert (await rig.work_items.get_work_item(item.id)).status == "blocked", "premise: parked"
    if before_fulfil is not None:
        await before_fulfil(item)
    if fulfil:
        await rig.requests.decide(request_id, True, reason="", decided_by="captain")
        await rig.requests.mark_fulfilled(request_id)
        await _settle(rig)
    return item, await rig.requests.get(request_id)


# -- S: the seam ---------------------------------------------------------------


async def test_s1_an_approved_continue_runs_the_turns_next_pass_and_posts_its_result(make_rig, scripted):
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done(FINAL)]
    scripted.gates = {0: gate}

    item, pending = await _promote_and_stop(rig, gate)

    # Premise: the defect's starting state, as the live run measured it.
    assert len(pending) == 1 and pending[0].kind == "continue" and pending[0].work_item_id == item.id
    parked = await rig.work_items.get_work_item(item.id)
    assert parked.status == "blocked" and parked.metadata["capability_request_id"] == pending[0].id
    assert _agent_bodies(rig)[-1].startswith(STOP_NOTICE)
    assert item.id in rig.agent._promoted_turn_continuations
    assert len(scripted.calls) == 1
    # Premise: this router and dispatcher do dispatch an item that is dispatchable.
    assert await rig.router.dispatch_work_item(parked.to_dict() | {"tags": ["consultation"]}) is True
    rig.dispatcher.events.clear()
    committed_before = len(rig.committed)

    result = await _approve(rig, pending[0].id)

    assert result["fulfilled"] is True
    assert len(scripted.calls) == 2, "the turn's next pass ran"
    assert scripted.calls[1]["task_text"] == continuation_task_text(ASSEMBLED, PARTIAL)
    assert PARTIAL in scripted.calls[1]["task_text"]
    assert scripted.calls[1]["thread_id"] == rig.thread.id
    assert _agent_bodies(rig)[-1] == FINAL
    assert [m.body for m in rig.committed[committed_before:]] == [FINAL]
    assert (await rig.work_items.get_work_item(item.id)).status == "done"
    assert rig.dispatcher.events == [], "the router was never handed the promoted turn"
    assert len(rig.agent._promoted_turn_continuations) == 0
    assert (await rig.requests.get(pending[0].id)).status == "fulfilled"


async def test_s2_a_resumed_pass_that_stops_again_parks_on_a_new_ask_and_resumes_again(make_rig, scripted):
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _cut(PARTIAL_2), _done(FINAL)]
    scripted.gates = {0: gate}

    item, pending = await _promote_and_stop(rig, gate)
    await _approve(rig, pending[0].id)

    second = await rig.requests.list_pending()
    assert len(second) == 1 and second[0].id != pending[0].id and second[0].work_item_id == item.id
    reparked = await rig.work_items.get_work_item(item.id)
    assert reparked.status == "blocked" and reparked.metadata["capability_request_id"] == second[0].id
    assert len(scripted.calls) == 2

    await _approve(rig, second[0].id)

    assert len(scripted.calls) == 3
    assert scripted.calls[2]["task_text"] == continuation_task_text(ASSEMBLED, PARTIAL_2)
    assert PARTIAL not in scripted.calls[2]["task_text"], "rebuilt from the base, never stacked"
    bodies = _agent_bodies(rig)
    assert bodies[-1] == FINAL
    assert sum(body.startswith(STOP_NOTICE) for body in bodies) == 2
    assert (await rig.work_items.get_work_item(item.id)).status == "done"
    assert rig.dispatcher.events == []


async def test_s3_a_raced_and_repeated_approval_runs_the_next_pass_once(make_rig, scripted):
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done(FINAL), _done("a second run that must not happen")]
    scripted.gates = {0: gate}
    item, pending = await _promote_and_stop(rig, gate)

    outcomes = await asyncio.gather(
        decide_capability_request(
            pending[0].id, CapabilityRequestDecideRequest(approve=True), runtime=rig.runtime,
        ),
        decide_capability_request(
            pending[0].id, CapabilityRequestDecideRequest(approve=True), runtime=rig.runtime,
        ),
        return_exceptions=True,
    )
    await _settle(rig)
    for _ in range(2):
        await rig.driver.on_capability_event(_fulfilled_event(pending[0].id))
    await _settle(rig)

    assert any(isinstance(outcome, dict) for outcome in outcomes), f"premise: {outcomes!r}"
    assert "capability_request_fulfilled" in rig.bus.emitted
    assert len(scripted.calls) == 2, "one approval, one next pass"
    assert _agent_bodies(rig).count(FINAL) == 1
    assert (await rig.work_items.get_work_item(item.id)).status == "done"


async def test_s4_a_reporter_still_posting_its_stop_notice_reads_only_its_own_segment(make_rig, scripted):
    rig = await make_rig(threads_cls=_HeldFirstAgentPost, episodic=True)
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done(FINAL)]
    scripted.gates = {0: gate}

    await _turn(rig)
    item = (await rig.work_items.list_work_items(status="in_progress"))[0]
    gate.set()
    assert await asyncio.to_thread(rig.threads.holding.wait, _SETTLE_S), (
        "premise: the first segment's reporter is posting its stop notice"
    )
    pending: list[Any] = []
    for _ in range(200):
        pending = await rig.requests.list_pending()
        if pending:
            break
        await asyncio.sleep(0.01)
    assert pending and (await rig.work_items.get_work_item(item.id)).status == "blocked"

    await decide_capability_request(
        pending[0].id, CapabilityRequestDecideRequest(approve=True), runtime=rig.runtime,
    )
    for _ in range(500):
        if FINAL in _agent_bodies(rig):
            break
        await asyncio.sleep(0.01)
    assert FINAL in _agent_bodies(rig), "premise: the next pass finished while the notice was held"
    rig.threads.release.set()
    await _settle(rig)

    completes = {
        episode.outcomes[0]["response"].startswith(STOP_NOTICE): episode.outcomes[0]["complete"]
        for episode in rig.runtime.episodic_memory.stored
    }
    assert completes == {True: False, False: True}, completes
    assert (await rig.work_items.get_work_item(item.id)).status == "done"


async def test_s5_an_ask_decided_before_its_item_parks_still_resumes_the_turn(make_rig, scripted):
    rig = await make_rig(requests_cls=_DecidedOnFiling)
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done(FINAL)]
    scripted.gates = {0: gate}

    item, pending = await _promote_and_stop(rig, gate)

    assert pending == [] and "capability_request_fulfilled" in rig.bus.emitted, (
        "premise: the ask was fulfilled as it was filed"
    )
    assert len(scripted.calls) == 2, "the turn's next pass ran"
    assert scripted.calls[1]["task_text"] == continuation_task_text(ASSEMBLED, PARTIAL)
    assert FINAL in _agent_bodies(rig)
    assert (await rig.work_items.get_work_item(item.id)).status == "done"
    assert rig.dispatcher.events == []


async def test_s6_a_next_pass_whose_continuation_will_not_compose_is_not_run(make_rig, scripted, monkeypatch):
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done("a pass that started the task over")]
    scripted.gates = {0: gate}
    item, pending = await _promote_and_stop(rig, gate)

    def _raise(**_kwargs: Any) -> str:
        raise RuntimeError("will not compose")

    monkeypatch.setattr("probos.cognitive.continue_or_ask._render_continuation", _raise)
    await _approve(rig, pending[0].id)

    assert len(scripted.calls) == 1, "the base prompt alone would start the task over"
    await _assert_closed(rig, item, RESUME_START_FAILED, notice=True)


async def test_s7_a_resumed_pass_that_reaches_the_turns_cost_ceiling_says_so(make_rig, scripted):
    rig = await make_rig(dm=DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        promote_to_task_after_seconds=0.05, token_budget=100_000,
    ))
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _outcome(PARTIAL_2, "token_budget")]
    scripted.gates = {0: gate}
    item, pending = await _promote_and_stop(rig, gate)

    await _approve(rig, pending[0].id)

    assert len(scripted.calls) == 2
    last = _agent_bodies(rig)[-1]
    assert last.startswith(_COST_STOP_LEAD_WITH_WORK) and PARTIAL_2 in last
    assert await rig.requests.list_pending() == [], "a cost stop files no ask"
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress"
    assert len(rig.agent._promoted_turn_continuations) == 0


# -- A: AD-855's report for an ordinary item -------------------------------------


async def _parked_generic(rig: SimpleNamespace, *, tags: list[str]) -> tuple[Any, Any]:
    item = await rig.work_items.create_work_item(
        title="do the thing", work_type="task", status="in_progress",
        assigned_to=AGENT, tags=tags, metadata={},
    )
    req = await rig.requests.file_request(
        agent_id=AGENT, kind="grant", target="reader", rationale="gap", work_item_id=item.id,
    )
    assert await rig.driver.block_on_request(work_item_id=item.id, request_id=req.id, reason="reader")
    await rig.requests.decide(req.id, True, reason="", decided_by="captain")
    await rig.requests.mark_fulfilled(req.id)
    await _settle(rig)
    return item, req


def _driver_records(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _DRIVER_LOG and r.levelno == level]


async def test_a1_an_item_the_router_admits_is_reported_re_dispatched(make_rig, caplog):
    rig = await make_rig(with_agent=False)
    caplog.set_level(logging.INFO, logger=_DRIVER_LOG)

    item, _req = await _parked_generic(rig, tags=["consultation"])

    assert len(rig.dispatcher.events) == 1
    assert f"AD-855: work item {item.id} resumed and re-dispatched" in _driver_records(caplog, logging.INFO)
    assert _driver_records(caplog, logging.WARNING) == []


async def test_a2_an_item_the_router_drops_is_reported_not_dispatchable(make_rig, caplog):
    rig = await make_rig(with_agent=False)
    caplog.set_level(logging.INFO, logger=_DRIVER_LOG)

    item, req = await _parked_generic(rig, tags=[])

    (warning,) = _driver_records(caplog, logging.WARNING)
    assert "not dispatchable" in warning and req.id[:12] in warning and "strand_timeout_seconds" in warning
    assert not any("resumed and re-dispatched" in m for m in _driver_records(caplog, logging.INFO))
    assert rig.dispatcher.events == []
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress"


async def test_a3_an_item_no_agent_admits_is_reported_not_admitted(make_rig, caplog):
    rig = await make_rig(with_agent=False, accepted=0)
    caplog.set_level(logging.INFO, logger=_DRIVER_LOG)

    item, _req = await _parked_generic(rig, tags=["consultation"])

    assert len(rig.dispatcher.events) == 1, "premise: the router did try"
    (warning,) = _driver_records(caplog, logging.WARNING)
    assert "no agent admitted" in warning and "stall_timeout_seconds" in warning
    assert not any("resumed and re-dispatched" in m for m in _driver_records(caplog, logging.INFO))
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress"


async def test_a4_a_router_that_raises_is_reported_and_the_item_stays_in_progress(make_rig, caplog):
    rig = await make_rig(with_agent=False)

    async def _boom(_wi: dict[str, Any]) -> bool:
        raise RuntimeError("dispatcher is down")

    rig.router.dispatch_work_item = _boom
    caplog.set_level(logging.INFO, logger=_DRIVER_LOG)

    item, _req = await _parked_generic(rig, tags=["consultation"])

    (warning,) = _driver_records(caplog, logging.WARNING)
    assert "raised" in warning and item.id in warning
    assert not any("resumed and re-dispatched" in m for m in _driver_records(caplog, logging.INFO))
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress"


async def test_a5_a_promoted_item_is_handed_to_its_agent_never_to_the_router(make_rig, caplog):
    rig = await make_rig(with_agent=False)
    resumed: list[str] = []
    await rig.registry.register(SimpleNamespace(
        id=AGENT, agent_type="counselor", pool="p",
        resume_promoted_turn=lambda wid, ask: resumed.append((wid, ask)) or RESUME_STARTED,
    ))
    caplog.set_level(logging.INFO, logger=_PROMOTION_LOG)

    item, req = await _parked_promoted(rig)

    # A-3 (F-R2-1): handed the ask that admitted the pass, as well as the item.
    assert resumed == [(item.id, req.id)]
    assert rig.dispatcher.events == []
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress"
    assert any(
        f"AD-855/BF-887: work item {item.id} resumed on capability request {req.id[:12]}" in r.getMessage()
        for r in caplog.records if r.levelno == logging.INFO
    )


# -- N: a resume nothing can take -------------------------------------------------


async def _assert_closed(rig: SimpleNamespace, item: Any, outcome: str, *, notice: bool) -> None:
    closed = await rig.work_items.get_work_item(item.id)
    assert closed.status == "failed"
    assert closed.metadata["stranded_reason"] == "continue_resume_" + outcome
    assert type(closed.metadata["stranded_at"]) is float
    # The consumer: the owner's AD-1228 "work item finished" notice names the code, not "other".
    assert stranded_reason_code(closed.metadata) == "continue_resume_" + outcome
    assert (_REPORT_RESUME_LOST in _agent_bodies(rig)) is notice


def _lost_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.levelno == logging.WARNING and "AD-855/BF-887" in r.getMessage()
    ]


@pytest.mark.parametrize("aboard", ["nobody", "an_agent_that_runs_no_turns"])
async def test_n1_no_agent_to_take_the_pass_closes_the_item_failed_and_tells_the_captain(
    make_rig, caplog, aboard,
):
    rig = await make_rig(with_agent=False)
    if aboard != "nobody":
        await rig.registry.register(SimpleNamespace(id=AGENT, agent_type="x", pool="p"))
    caplog.set_level(logging.INFO)

    item, req = await _parked_promoted(rig)

    await _assert_closed(rig, item, RESUME_NO_AGENT, notice=True)
    (warning,) = _lost_warnings(caplog)
    assert item.id in warning and req.id[:12] in warning and "not aboard" in warning
    assert "ask again" in warning and "continue_resume_no_agent" in warning
    assert rig.dispatcher.events == []


async def test_n2_an_agent_that_holds_no_next_pass_closes_it_the_same_way(make_rig, caplog):
    rig = await make_rig()  # a fresh agent: the vessel restarted since the turn stopped
    caplog.set_level(logging.INFO)

    item, _req = await _parked_promoted(rig)

    await _assert_closed(rig, item, RESUME_NO_CONTINUATION, notice=True)
    assert "holds no next pass" in _lost_warnings(caplog)[0]


async def test_n3_a_start_that_raises_closes_it_the_same_way(make_rig, caplog):
    rig = await make_rig()
    caplog.set_level(logging.INFO)

    def _raise(_ask: str) -> None:
        raise RuntimeError("the turn's state is gone")

    async def _hold_a_raising_pass(item: Any) -> None:
        rig.agent._promoted_turn_continuations = PromotedTurnContinuations(agent_id=AGENT)
        rig.agent._promoted_turn_continuations.hold(item.id, _raise)

    item, _req = await _parked_promoted(rig, before_fulfil=_hold_a_raising_pass)

    await _assert_closed(rig, item, RESUME_START_FAILED, notice=True)
    assert len(rig.agent._promoted_turn_continuations) == 0


async def test_n4_an_item_that_names_no_thread_is_closed_without_a_notice(make_rig, caplog):
    rig = await make_rig()
    caplog.set_level(logging.INFO)

    item, _req = await _parked_promoted(rig, thread=False)

    await _assert_closed(rig, item, RESUME_UNIDENTIFIED, notice=False)
    assert "assigned to no agent, or names no thread" in _lost_warnings(caplog)[0]
    # A-1 (F-R1-3): the WARNING promises no notice that will not be posted.
    assert "posting no notice" in _lost_warnings(caplog)[0]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], "no post was attempted"


async def test_n5_an_item_that_moved_on_is_left_as_it_is_and_nothing_is_posted(make_rig, caplog):
    rig = await make_rig(with_agent=False)
    caplog.set_level(logging.INFO)
    item, req = await _parked_promoted(rig, fulfil=False)
    assert await rig.work_items.transition_work_item(item.id, "cancelled", source="captain")

    outcome = await resume_promoted_turn(
        rig.runtime, await rig.work_items.get_work_item(item.id), req.id,
    )

    # A-3 (F-R2-2): the hand-off reads the item again and finds it moved on, so it
    # neither runs it nor closes it. This read RESUME_NO_AGENT and a refused close
    # while the hand-off trusted the item it was given; that refusal is N5b's now.
    assert outcome == RESUME_MOVED_ON
    assert (await rig.work_items.get_work_item(item.id)).status == "cancelled"
    assert _REPORT_RESUME_LOST not in _agent_bodies(rig)
    assert any(
        "left in_progress on capability request" in r.getMessage()
        for r in caplog.records if r.levelno == logging.INFO
    )
    assert _lost_warnings(caplog) == [], "nothing is closed, so no WARNING says it will be"


async def test_n5b_an_item_that_moves_on_under_the_close_is_left_as_it_is(make_rig, caplog):
    """The close's own compare-and-set: the item leaves in_progress on its ask
    after the hand-off read it and before the close lands."""
    rig = await make_rig(with_agent=False)
    caplog.set_level(logging.INFO)
    item, req = await _parked_promoted(rig, fulfil=False)
    resumed = await rig.work_items.transition_work_item(
        item.id, "in_progress", source="capability_gap_driver",
        expected_status="blocked", expected={"capability_request_id": req.id},
    )
    assert resumed is not None, "premise: AD-855's compare-and-set moved it"
    transition = rig.work_items.transition_work_item

    async def _cancelled_first(work_item_id: str, status: str, **kwargs: Any) -> Any:
        if status == "failed":
            cancelled = await transition(work_item_id, "cancelled", source="captain")
            assert cancelled is not None, "premise: the item moved on under the close"
        return await transition(work_item_id, status, **kwargs)

    rig.work_items.transition_work_item = _cancelled_first

    outcome = await resume_promoted_turn(rig.runtime, resumed, req.id)

    assert outcome == RESUME_NO_AGENT
    assert (await rig.work_items.get_work_item(item.id)).status == "cancelled"
    assert _REPORT_RESUME_LOST not in _agent_bodies(rig)
    assert any("was not closed" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_n6_the_notice_does_not_read_as_a_capability_gap() -> None:
    assert _CAPABILITY_GAP_RE.search(_REPORT_RESUME_LOST) is None


async def _patch_work_item(rig: SimpleNamespace, work_item_id: str, body: dict[str, Any]) -> Any:
    """The real ``PATCH /api/work-items/{id}`` route, in process."""
    app = FastAPI()
    app.include_router(workforce_router)
    app.dependency_overrides[get_runtime] = lambda: rig.runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://in-process.test", trust_env=False,
    ) as client:
        return await client.patch(f"/api/work-items/{work_item_id}", json=body)


@pytest.mark.parametrize(
    ("owner", "outcome"),
    [(None, RESUME_UNIDENTIFIED), ("science_science_0_5d2e8f10", RESUME_NO_AGENT)],
    ids=["cleared", "changed"],
)
async def test_n7_an_owner_cleared_or_changed_on_the_board_still_hears_back_in_the_turns_thread(
    make_rig, scripted, owner, outcome,
):
    """A-1 (F-R1-2): running the next pass needs the CURRENT owner; telling the
    Captain it did not run does not, so the notice comes from the agent that ran
    the turn, into its thread, as the record kept them at promotion."""
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done("a pass nobody now owns must not run")]
    scripted.gates = {0: gate}
    item, pending = await _promote_and_stop(rig, gate)

    response = await _patch_work_item(rig, item.id, {"assigned_to": owner})

    assert response.status_code == 200, f"premise: {response.text}"
    patched = await rig.work_items.get_work_item(item.id)
    assert (patched.assigned_to or None) == owner, "premise: the route changed the owner"
    assert patched.status == "blocked", "premise: and only the owner -- the item is still parked"
    assert patched.metadata["capability_request_id"] == pending[0].id, "premise: on its ask"
    assert (patched.metadata["agent_id"], patched.metadata["thread_id"]) == (AGENT, rig.thread.id), (
        "premise: the record still names the agent and the thread of the turn"
    )
    assert item.id in rig.agent._promoted_turn_continuations, "premise: the next pass is held"

    await _approve(rig, pending[0].id)

    assert len(scripted.calls) == 1, "no resume: running the next pass needs the current owner"
    await _assert_closed(rig, item, outcome, notice=True)
    lost = [m for m in rig.threads.list_messages(rig.thread.id) if m.body == _REPORT_RESUME_LOST]
    assert [m.author_id for m in lost] == [AGENT], "one notice, from the agent that ran the turn"
    assert rig.dispatcher.events == []


async def test_n8_the_warning_says_what_it_is_doing_when_the_close_is_cancelled(make_rig, caplog):
    """A-1 (F-R1-3): logged before the close and the notice, the WARNING says what
    is being done; a close cancelled under it leaves the item as it was, and the
    log must not have said otherwise."""
    rig = await make_rig()  # a fresh agent: it holds no next pass for the item
    caplog.set_level(logging.INFO)
    item, req = await _parked_promoted(rig, fulfil=False)
    resumed = await rig.work_items.transition_work_item(
        item.id, "in_progress", source="capability_gap_driver",
        expected_status="blocked", expected={"capability_request_id": req.id},
    )
    assert resumed is not None, "premise: AD-855's compare-and-set moved it"
    entered = asyncio.Event()
    transition = rig.work_items.transition_work_item

    async def _held_close(work_item_id: str, status: str, **kwargs: Any) -> Any:
        if status == "failed":
            entered.set()
            await asyncio.sleep(_SETTLE_S)  # the store is busy; the test cancels first
        return await transition(work_item_id, status, **kwargs)

    rig.work_items.transition_work_item = _held_close
    resume = asyncio.create_task(resume_promoted_turn(rig.runtime, resumed, req.id))
    await asyncio.wait_for(entered.wait(), timeout=_SETTLE_S)
    resume.cancel()

    with pytest.raises(asyncio.CancelledError):
        await resume
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress"
    assert _REPORT_RESUME_LOST not in _agent_bodies(rig)
    (warning,) = _lost_warnings(caplog)
    assert "holds no next pass" in warning and "closing it as failed" in warning
    assert "is closed failed" not in warning and "is told" not in warning


# -- C: the continuation store and its contracts ----------------------------------


def test_c1_a_held_pass_starts_once_and_a_second_resume_finds_nothing() -> None:
    started: list[str] = []
    held = PromotedTurnContinuations(agent_id=AGENT)
    held.hold("w1", started.append)

    assert held.resume("w1", "r1") == RESUME_STARTED
    assert held.resume("w1", "r1") == RESUME_NO_CONTINUATION
    # A-3 (F-R2-1): the pass is started with the ask whose approval admitted it.
    assert started == ["r1"]


def test_c2_holding_again_replaces_the_earlier_pass() -> None:
    started: list[str] = []
    held = PromotedTurnContinuations(agent_id=AGENT)
    held.hold("w1", lambda _ask: started.append("old"))
    held.hold("w1", lambda _ask: started.append("new"))

    assert len(held) == 1 and held.resume("w1", "r1") == RESUME_STARTED
    assert started == ["new"]


def test_c3_past_the_limit_the_oldest_is_released_with_a_warning(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_PROMOTION_LOG)
    held = PromotedTurnContinuations(agent_id=AGENT, limit=2)
    for key in ("w1", "w2", "w3"):
        held.hold(key, lambda _ask: None)

    assert "w1" not in held and "w2" in held and "w3" in held
    (warning,) = [r.getMessage() for r in caplog.records]
    assert "w1" in warning and "the most it keeps" in warning
    assert held.resume("w1", "r1") == RESUME_NO_CONTINUATION
    assert held.resume("w3", "r3") == RESUME_STARTED


def test_c3b_holding_a_turn_again_makes_it_the_newest() -> None:
    held = PromotedTurnContinuations(agent_id=AGENT, limit=2)
    held.hold("w1", lambda _ask: None)
    held.hold("w2", lambda _ask: None)
    held.hold("w1", lambda _ask: None)  # w1's next segment, kept again when it starts
    held.hold("w3", lambda _ask: None)

    assert "w1" in held and "w3" in held and "w2" not in held


def test_c4_release_forgets_and_an_unknown_release_is_a_no_op() -> None:
    held = PromotedTurnContinuations(agent_id=AGENT)
    held.hold("w1", lambda _ask: None)
    held.release("w1")
    held.release("never-held")

    assert len(held) == 0 and held.resume("w1", "r1") == RESUME_NO_CONTINUATION
    floor = PromotedTurnContinuations(agent_id=AGENT, limit=0)
    floor.hold("a", lambda _ask: None)
    floor.hold("b", lambda _ask: None)
    assert len(floor) == 1 and "b" in floor


def test_c10_a_segment_releases_only_the_pass_it_kept() -> None:
    """A-1 (F-R1-1): by the time an older segment of a turn ends, a newer one may
    hold the turn's next pass; the older one's release must leave it held."""
    held = PromotedTurnContinuations(agent_id=AGENT)

    def older(_ask: str) -> None: ...

    def newer(_ask: str) -> None: ...

    held.hold("w1", older)
    held.hold("w1", newer)

    held.release("w1", older)
    assert "w1" in held, "the newer segment's pass outlives the older segment's release"
    held.release("w1", newer)
    assert "w1" not in held


async def test_c5_a_promoted_turn_that_finishes_holds_nothing(make_rig, scripted):
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.script = [_done(FINAL)]
    scripted.gates = {0: gate}

    item, pending = await _promote_and_stop(rig, gate)

    assert pending == []
    assert len(rig.agent._promoted_turn_continuations) == 0
    assert (await rig.work_items.get_work_item(item.id)).status == "done"


async def test_c6_a_promoted_turn_that_stops_without_an_ask_holds_nothing(make_rig, scripted):
    rig = await make_rig(dm=DmAgenticConfig(enabled=True, promote_to_task_after_seconds=0.05))
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL)]
    scripted.gates = {0: gate}

    item, pending = await _promote_and_stop(rig, gate)

    assert pending == []
    assert len(rig.agent._promoted_turn_continuations) == 0
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress"


def test_c7_either_marker_makes_a_promoted_turn() -> None:
    assert is_promoted_turn(SimpleNamespace(metadata={"source": PROMOTION_SOURCE}, tags=[]))
    assert is_promoted_turn(SimpleNamespace(metadata={}, tags=[PROMOTION_TAG]))
    assert is_promoted_turn(SimpleNamespace(metadata=None, tags=[PROMOTION_TAG]))
    assert not is_promoted_turn(SimpleNamespace(metadata={"source": "captain"}, tags=["consultation"]))
    assert not is_promoted_turn(SimpleNamespace())


async def test_c8_parked_is_recorded_only_when_the_item_was_parked(make_rig) -> None:
    rig = await make_rig(with_agent=False)
    item = await _create_promoted_work_item(
        runtime=rig.runtime, agent_id=AGENT, thread_id=rig.thread.id, request_text=ASK,
    )
    parked: dict[str, str] = {}
    request_id = await file_continue_request(
        rig.runtime, agent_id=AGENT, thread_id=rig.thread.id, base_task_text=ASK,
        passes=1, work_item_id=item.id, parked=parked,
    )
    assert request_id and parked == {"request_id": request_id}

    unparked: dict[str, str] = {}
    other = await file_continue_request(
        SimpleNamespace(capability_request_store=rig.requests),
        agent_id=AGENT, thread_id=rig.thread.id, base_task_text=ASK,
        passes=1, work_item_id=item.id, parked=unparked,
    )
    assert other and unparked == {}, "filed, but with no driver nothing was parked"


def test_c9_the_resumed_text_is_the_standing_rule_text_and_empty_when_it_will_not_compose(
    monkeypatch,
) -> None:
    assert continuation_task_text(ASSEMBLED, PARTIAL) == ASSEMBLED + _continuation_block(PARTIAL)
    assert PARTIAL in continuation_task_text(ASSEMBLED, PARTIAL)

    def _raise(**_kwargs: Any) -> str:
        raise RuntimeError("will not compose")

    monkeypatch.setattr("probos.cognitive.continue_or_ask._render_continuation", _raise)
    assert continuation_task_text(ASSEMBLED, PARTIAL) == ""


# -- L: every way a turn ends lets go of the next pass it kept -------------------


def _held_turns(rig: SimpleNamespace) -> int:
    return len(rig.agent._promoted_turn_continuations)


def _watchdog_config() -> DmAgenticConfig:
    """A BF-733 deadline short enough to reach: the real watchdog stops the run."""
    return DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        promote_to_task_after_seconds=0.05, promoted_run_deadline_seconds=1.0,
    )


async def test_l1_a_promoted_turn_whose_run_raises_holds_nothing(make_rig, scripted):
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.script = [_PassRaised("the model endpoint went away")]
    scripted.gates = {0: gate}

    item, pending = await _promote_and_stop(rig, gate)

    assert pending == [] and (await rig.work_items.get_work_item(item.id)).status == "failed", (
        "premise: the run raised and its reporter closed the item"
    )
    assert _held_turns(rig) == 0


async def test_l2_a_resumed_pass_that_raises_holds_nothing(make_rig, scripted):
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _PassRaised("the model endpoint went away")]
    scripted.gates = {0: gate}
    item, pending = await _promote_and_stop(rig, gate)

    await _approve(rig, pending[0].id)

    assert len(scripted.calls) == 2, "premise: the next pass ran"
    assert (await rig.work_items.get_work_item(item.id)).status == "failed", "premise: and raised"
    assert _held_turns(rig) == 0


async def test_l3_a_promoted_run_the_watchdog_stops_holds_nothing(make_rig, scripted):
    rig = await make_rig(dm=_watchdog_config())
    scripted.script = [_cut(PARTIAL)]
    scripted.gates = {0: asyncio.Event()}  # never released: the run outlives its deadline

    await _turn(rig)
    (item,) = await rig.work_items.list_work_items(status="in_progress")
    assert item.id in rig.agent._promoted_turn_continuations, "premise: held from promotion"
    await _settle(rig)

    assert (await rig.work_items.get_work_item(item.id)).status == "failed", (
        "premise: BF-733's watchdog stopped the run and its reporter closed the item"
    )
    assert _held_turns(rig) == 0


async def test_l4_a_resumed_pass_the_watchdog_stops_holds_nothing(make_rig, scripted):
    rig = await make_rig(dm=_watchdog_config())
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done("never returned")]
    scripted.gates = {0: gate, 1: asyncio.Event()}  # the next pass outlives its deadline
    item, pending = await _promote_and_stop(rig, gate)

    await _approve(rig, pending[0].id)

    assert len(scripted.calls) == 2, "premise: the next pass started"
    assert (await rig.work_items.get_work_item(item.id)).status == "failed", (
        "premise: BF-733's watchdog stopped it and its reporter closed the item"
    )
    assert _held_turns(rig) == 0


async def test_l5_a_turn_that_finished_while_its_item_was_written_holds_nothing(make_rig, scripted):
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.script = [_done(FINAL)]
    scripted.gates = {0: gate}
    writing, written = asyncio.Event(), asyncio.Event()
    create = rig.work_items.create_work_item

    async def _slow_create(**kwargs: Any) -> Any:
        writing.set()
        await asyncio.wait_for(written.wait(), timeout=_SETTLE_S)
        return await create(**kwargs)

    rig.work_items.create_work_item = _slow_create
    turn = asyncio.create_task(_turn(rig))
    await asyncio.wait_for(writing.wait(), timeout=_SETTLE_S)
    (run,) = rig.agent._promoted_turn_tasks
    gate.set()
    await asyncio.wait({run}, timeout=_SETTLE_S)
    assert run.done() and run.result() == FINAL, "premise: the run finished before its item existed"
    written.set()
    ack = await asyncio.wait_for(turn, timeout=_SETTLE_S)
    await _settle(rig)

    (item,) = await rig.work_items.list_work_items(status="done")
    assert ack == _ACK_TEMPLATE.format(work_item_id=item.id), "premise: the turn was promoted"
    assert _agent_bodies(rig)[-1] == FINAL, "premise: and its result reported"
    assert _held_turns(rig) == 0


async def test_l6_turns_that_failed_do_not_crowd_out_one_still_waiting_on_the_captain(
    make_rig, scripted,
):
    """The review's measurement: one turn stopped to ask, then as many others as
    an agent holds (sixteen) were promoted and failed. Approving the ask must
    still run the waiting turn's next pass."""
    rig = await make_rig()
    failing = turn_promotion._MAX_HELD_CONTINUATIONS
    scripted.script = [
        _cut(PARTIAL),
        *[_PassRaised(f"outage {n}") for n in range(failing)],
        _done(FINAL),
    ]
    scripted.gates = {index: asyncio.Event() for index in range(failing + 1)}
    waiting, pending = await _promote_and_stop(rig, scripted.gates[0])
    for index in range(1, failing + 1):
        await _turn(rig)
        scripted.gates[index].set()
        await _settle(rig)
    failed = await rig.work_items.list_work_items(status="failed")
    assert len(failed) == failing, "premise: every other turn was promoted and failed"
    assert len(pending) == 1 and (await rig.work_items.get_work_item(waiting.id)).status == "blocked", (
        "premise: the first turn is still parked on its ask"
    )

    await _approve(rig, pending[0].id)

    assert len(scripted.calls) == failing + 2, "the waiting turn's next pass ran"
    assert _agent_bodies(rig)[-1] == FINAL
    assert (await rig.work_items.get_work_item(waiting.id)).status == "done"


# -- G: the long-run grant, and a drift guard -------------------------------------


async def test_g1_the_next_pass_measures_its_long_run_grant_from_the_resume(make_rig, scripted):
    rig = await make_rig(
        dm=DmAgenticConfig(
            enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
            promote_to_task_after_seconds=0.05, promoted_run_deadline_seconds=1200.0,
        ),
        execution=ExecutionConfig(max_runtime_seconds=900.0),
    )
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done(FINAL)]
    scripted.gates = {0: gate}
    _item, pending = await _promote_and_stop(rig, gate)
    first = scripted.calls[0]["extra_context"][EXECUTION_LONG_RUN_GRANT_KEY]
    await asyncio.sleep(0.3)

    approved_at = time.monotonic()
    await _approve(rig, pending[0].id)

    resumed = scripted.calls[1]["extra_context"][EXECUTION_LONG_RUN_GRANT_KEY]
    assert resumed.deadline_monotonic - first.deadline_monotonic >= 0.25
    assert abs(resumed.deadline_monotonic - (approved_at + 1200.0 - 300.0)) < 1.0


async def test_g1b_a_resumed_pass_the_vessel_no_longer_lets_run_long_gets_no_grant(make_rig, scripted):
    rig = await make_rig(execution=ExecutionConfig(max_runtime_seconds=900.0))
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done(FINAL)]
    scripted.gates = {0: gate}
    _item, pending = await _promote_and_stop(rig, gate)
    assert EXECUTION_LONG_RUN_GRANT_KEY in scripted.calls[0]["extra_context"], "premise: armed"
    rig.runtime.config.execution = ExecutionConfig(max_runtime_seconds=0.0)

    await _approve(rig, pending[0].id)

    assert len(scripted.calls) == 2 and "extra_context" not in scripted.calls[1]


async def test_g4_start_resumed_run_holds_both_tasks_until_they_end() -> None:
    hold: set[asyncio.Task[Any]] = set()
    release = asyncio.Event()

    async def _work() -> str:
        await release.wait()
        return FINAL

    reporter = start_resumed_run(
        _work, runtime=SimpleNamespace(), agent_id=AGENT, thread_id="t",
        work_item_id="w1", request_text=ASK, hold=hold,
    )

    assert reporter in hold and len(hold) == 2
    release.set()
    await asyncio.wait_for(reporter, timeout=_SETTLE_S)
    assert hold == set()


def test_g2_start_resumed_run_takes_every_parameter_the_reporter_takes() -> None:
    reporter = set(inspect.signature(turn_promotion._report_holding_slot).parameters) - {"task"}
    resumed = set(inspect.signature(start_resumed_run).parameters)
    assert reporter <= resumed, reporter - resumed


def test_g3_the_agent_reports_and_bounds_the_resumed_run_exactly_as_the_first() -> None:
    """The two call sites pass the same reporter arguments, read the same way."""
    import ast

    from probos.cognitive import cognitive_agent

    tree = ast.parse(inspect.getsource(cognitive_agent))

    def call(name: str) -> tuple[dict[str, str], set[str]]:
        (found,) = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
        ]
        named = {kw.arg: ast.dump(kw.value) for kw in found.keywords if kw.arg is not None}
        spread = {ast.dump(kw.value) for kw in found.keywords if kw.arg is None}
        return named, spread

    (first, first_spread), (resumed, resumed_spread) = call("run_with_promotion"), call("start_resumed_run")
    for name in (
        "runtime", "agent_id", "thread_id", "request_text", "hold", "failures_probe",
        "background_slot", "deadline_seconds", "unconfirmed_grace_seconds", "strand_timeout_seconds",
    ):
        assert first[name] == resumed[name], name
    plan_mode = ast.dump(ast.Name(id="_plan_mode_promotion", ctx=ast.Load()))
    assert plan_mode in first_spread and plan_mode in resumed_spread


# -- O: a segment ends its item only while it is its own; the hand-off reads it now --

# The older segment's deadline, and how long before it the newer segment starts:
# the newer one's own deadline then falls a head start after the older one's.
_O_DEADLINE_S = 2.5
_O_HEAD_START_S = 1.0
SCIENCE = "science_science_0_5d2e8f10"


def _o_config() -> DmAgenticConfig:
    return DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        promote_to_task_after_seconds=0.05, promoted_run_deadline_seconds=_O_DEADLINE_S,
    )


async def _until(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + _SETTLE_S
    while not predicate():
        assert time.monotonic() < deadline, f"premise: reached within {_SETTLE_S}s"
        await asyncio.sleep(0.005)


def _hold_after(
    rig: SimpleNamespace, select: Callable[[str, dict[str, Any]], bool],
) -> SimpleNamespace:
    """Hold the first item write ``select`` picks, once it has committed, in the task
    that made it, until the test releases it: the window an approval can land in."""
    held = SimpleNamespace(entered=asyncio.Event(), release=asyncio.Event(), task=None)
    transition = rig.work_items.transition_work_item

    async def _held(work_item_id: str, status: str, *args: Any, **kwargs: Any) -> Any:
        moved = await transition(work_item_id, status, *args, **kwargs)
        if held.task is None and select(status, kwargs):
            held.task = asyncio.current_task()
            held.entered.set()
            await asyncio.wait_for(held.release.wait(), timeout=_SETTLE_S)
        return moved

    rig.work_items.transition_work_item = _held
    return held


def _approve_now(rig: SimpleNamespace, request_id: str) -> Awaitable[dict[str, Any]]:
    """The real decide route, without settling: a segment is still inside its park."""
    return decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=True), runtime=rig.runtime,
    )


@pytest.mark.parametrize("ending", ["finished", "watchdog"])
@pytest.mark.parametrize("older", ["first", "resumed"])
async def test_o1_an_older_segment_ending_under_a_newer_one_leaves_it_the_item(
    make_rig, scripted, caplog, older, ending,
):
    """A-3 (F-R2-1), the review's matrix: the approval of an older segment's ask
    starts the next segment while the older one is still inside its park; then the
    older one finishes, or the real BF-733 watchdog stops it. The newer segment
    owns the item: it stays in_progress under it, the newer pass parks it on its
    own ask, and approving that ask runs the turn to its end."""
    rig = await make_rig(dm=_o_config())
    caplog.set_level(logging.INFO)
    newer = 1 if older == "first" else 2  # the newer segment's pass, by index
    scripted.script = [
        *([] if older == "first" else [_cut(PARTIAL)]),
        _cut(PARTIAL_2),
        _cut("Twelve of fifteen done; stopping again."),
        _done(FINAL),
    ]
    scripted.gates = {index: asyncio.Event() for index in range(newer + 1)}
    parks: list[str] = []

    def _the_older_park(status: str, _kwargs: dict[str, Any]) -> bool:
        if status == "blocked":
            parks.append(status)
        return status == "blocked" and len(parks) == newer

    hold = _hold_after(rig, _the_older_park)
    await _turn(rig)
    (item,) = await rig.work_items.list_work_items(status="in_progress")
    scripted.gates[0].set()
    if older == "resumed":
        await _settle(rig)
        (first_ask,) = await rig.requests.list_pending()
        await _approve_now(rig, first_ask.id)
        scripted.gates[1].set()
    await asyncio.wait_for(hold.entered.wait(), timeout=_SETTLE_S)
    (older_ask,) = await rig.requests.list_pending()
    parked = await rig.work_items.get_work_item(item.id)
    assert parked.status == "blocked" and parked.metadata["capability_request_id"] == older_ask.id
    assert len(scripted.calls) == newer, "premise: the older segment parked and is inside its park"
    older_tasks = {t for t in rig.agent._promoted_turn_tasks if not t.done()}
    assert hold.task in older_tasks and len(older_tasks) == 2, "premise: the older run and reporter"
    await asyncio.sleep(_O_HEAD_START_S)

    await _approve_now(rig, older_ask.id)
    await _until(lambda: len(scripted.calls) == newer + 1)
    newer_tasks = {t for t in rig.agent._promoted_turn_tasks if not t.done()} - older_tasks
    assert len(newer_tasks) == 2, "premise: the approval started the newer run and its reporter"
    if ending == "finished":
        hold.release.set()
    await asyncio.wait(older_tasks, timeout=_SETTLE_S)
    assert all(t.done() for t in older_tasks), "premise: the older segment has ended"
    assert hold.task.cancelled() is (ending == "watchdog"), "premise: by the real watchdog, or not"
    assert not any(t.done() for t in newer_tasks), "premise: the newer segment is still running"

    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress", (
        "the newer segment owns the item, and the older one did not end it"
    )
    scripted.gates[newer].set()
    await _settle(rig)
    (next_ask,) = await rig.requests.list_pending()
    reparked = await rig.work_items.get_work_item(item.id)
    assert next_ask.work_item_id == item.id and reparked.status == "blocked"
    assert reparked.metadata["capability_request_id"] == next_ask.id

    await _approve(rig, next_ask.id)

    assert len(scripted.calls) == newer + 2, "approving the newer segment's ask ran its next pass"
    assert _agent_bodies(rig)[-1] == FINAL
    assert (await rig.work_items.get_work_item(item.id)).status == "done"
    assert rig.dispatcher.events == [] and _held_turns(rig) == 0
    if ending == "watchdog":
        assert _REPORT_ABANDONED not in _agent_bodies(rig), "no ending is posted for a running turn"
        (moved,) = [
            r.getMessage() for r in caplog.records
            if r.levelno == logging.WARNING and "after the item moved on" in r.getMessage()
        ]
        assert item.id in moved and "was stopped by its watchdog" in moved


@pytest.mark.parametrize(
    ("edit", "outcome"),
    [
        ({}, RESUME_STARTED),
        ({"assigned_to": None}, RESUME_UNIDENTIFIED),
        ({"assigned_to": SCIENCE}, RESUME_NO_CONTINUATION),
        ({"status": "cancelled"}, RESUME_MOVED_ON),
    ],
    ids=["unchanged", "owner_cleared", "owner_changed", "cancelled"],
)
async def test_o2_the_hand_off_acts_on_a_board_edit_made_after_the_resume(
    make_rig, scripted, caplog, edit, outcome,
):
    """A-3 (F-R2-2): AD-855's compare-and-set has committed and the store is still
    publishing its cache when the real PATCH route edits the item. The hand-off
    acts on the edit, not on the snapshot the compare-and-set returned: an owner
    cleared or changed gets the stranded path -- one notice, from the agent that
    ran the turn, into its thread -- and no pass; a cancelled item is left as it is."""
    rig = await make_rig()
    caplog.set_level(logging.INFO)
    science = CognitiveAgent(agent_id=SCIENCE, instructions="You are Science.")
    science._runtime = rig.runtime
    await rig.registry.register(science)
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done(FINAL)]
    scripted.gates = {0: gate}
    item, (ask,) = await _promote_and_stop(rig, gate)
    hold = _hold_after(
        rig, lambda status, kwargs: status == "in_progress" and kwargs.get("expected_status") == "blocked",
    )
    approval = asyncio.create_task(_approve_now(rig, ask.id))
    await asyncio.wait_for(hold.entered.wait(), timeout=_SETTLE_S)
    resumed = await rig.work_items.get_work_item(item.id)
    assert resumed.status == "in_progress" and resumed.assigned_to == AGENT
    assert len(scripted.calls) == 1, "premise: the resume committed and no next pass has started"
    if edit:
        response = await _patch_work_item(rig, item.id, edit)
        assert response.status_code == 200, f"premise: {response.text}"

    hold.release.set()
    await approval
    await _settle(rig)

    after = await rig.work_items.get_work_item(item.id)
    lost = [m.author_id for m in rig.threads.list_messages(rig.thread.id) if m.body == _REPORT_RESUME_LOST]
    assert rig.dispatcher.events == []
    if outcome == RESUME_STARTED:
        assert len(scripted.calls) == 2 and _agent_bodies(rig)[-1] == FINAL
        assert after.status == "done" and lost == []
        return
    assert len(scripted.calls) == 1, "no next pass runs after the edit"
    assert item.id in rig.agent._promoted_turn_continuations, "the agent that ran it still holds it"
    if outcome == RESUME_MOVED_ON:
        assert after.status == "cancelled" and lost == []
        assert any("left in_progress on capability request" in r.getMessage() for r in caplog.records)
    else:
        await _assert_closed(rig, item, outcome, notice=True)
        assert lost == [AGENT], "one notice, from the agent that ran the turn"


async def test_o3_a_hand_off_that_cannot_read_the_item_again_uses_the_resume_snapshot(
    make_rig, scripted, caplog,
):
    rig = await make_rig()
    caplog.set_level(logging.INFO)
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done(FINAL)]
    scripted.gates = {0: gate}
    item, (ask,) = await _promote_and_stop(rig, gate)
    resumed = await rig.work_items.transition_work_item(
        item.id, "in_progress", source="capability_gap_driver",
        expected_status="blocked", expected={"capability_request_id": ask.id},
    )
    assert resumed is not None, "premise: AD-855's compare-and-set moved it"
    read = rig.work_items.get_work_item
    refused: list[str] = []

    async def _unreadable_once(work_item_id: str) -> Any:
        if not refused:
            refused.append(work_item_id)
            raise RuntimeError("the store is busy")
        return await read(work_item_id)

    rig.work_items.get_work_item = _unreadable_once

    outcome = await resume_promoted_turn(rig.runtime, resumed, ask.id)
    await _settle(rig)

    assert outcome == RESUME_STARTED and refused == [item.id]
    assert len(scripted.calls) == 2 and _agent_bodies(rig)[-1] == FINAL
    assert (await read(item.id)).status == "done"
    assert any(
        "could not read promoted work item" in r.getMessage()
        for r in caplog.records if r.levelno == logging.WARNING
    )


async def _a_segment(rig: SimpleNamespace, item: Any, work: Any, **kwargs: Any) -> set[asyncio.Task[Any]]:
    """A segment of ``item``'s turn through the public entry, its run being ``work``."""
    hold: set[asyncio.Task[Any]] = set()
    reporter = start_resumed_run(
        work, runtime=rig.runtime, agent_id=AGENT, thread_id=rig.thread.id,
        work_item_id=item.id, request_text=ASK, hold=hold, **kwargs,
    )
    await asyncio.wait_for(reporter, timeout=_SETTLE_S)
    return hold


@pytest.mark.parametrize("taken_by", ["its_own_ask", "a_newer_segment"])
async def test_o4_a_segment_that_fails_after_its_item_moved_on_ends_nothing(
    make_rig, caplog, taken_by,
):
    """A-3 (F-R2-1), the failure half: the segment parked the item on its ask -- which
    still waits on the Captain, or whose approval started a newer segment -- then
    failed. The ask, or that segment, owns what happens next."""
    rig = await make_rig(with_agent=False, episodic=True)
    caplog.set_level(logging.INFO)
    item, req = await _parked_promoted(rig, fulfil=False)
    status = "blocked"
    if taken_by == "a_newer_segment":
        assert await rig.work_items.transition_work_item(
            item.id, "in_progress", source="capability_gap_driver",
            expected_status="blocked", expected={"capability_request_id": req.id},
        ), "premise: AD-855's compare-and-set admitted the newer segment"
        status = "in_progress"

    async def _fails() -> str:
        raise _PassRaised("after the park")

    await _a_segment(rig, item, _fails, settle_expected={"capability_request_id": None})

    after = await rig.work_items.get_work_item(item.id)
    assert after.status == status and after.metadata["capability_request_id"] == req.id
    assert _REPORT_FAILED not in _agent_bodies(rig)
    assert len(rig.runtime.episodic_memory.stored) == 1, "its episode is still stored"
    (moved,) = [r.getMessage() for r in caplog.records if "after the item moved on" in r.getMessage()]
    assert item.id in moved and " failed after" in moved


async def test_o5_a_segment_that_cannot_read_its_item_ends_it_as_before(make_rig, caplog):
    rig = await make_rig(with_agent=False)
    caplog.set_level(logging.INFO)
    item = await _create_promoted_work_item(
        runtime=rig.runtime, agent_id=AGENT, thread_id=rig.thread.id, request_text=ASK,
    )
    read = rig.work_items.get_work_item
    refused: list[str] = []

    async def _unreadable_once(work_item_id: str) -> Any:
        if not refused:
            refused.append(work_item_id)
            raise RuntimeError("the store is busy")
        return await read(work_item_id)

    rig.work_items.get_work_item = _unreadable_once

    async def _fails() -> str:
        raise _PassRaised("the model endpoint went away")

    await _a_segment(rig, item, _fails, settle_expected={"capability_request_id": None})

    assert refused == [item.id]
    assert (await read(item.id)).status == "failed" and _agent_bodies(rig)[-1] == _REPORT_FAILED
    assert any(
        "could not read promoted work item" in r.getMessage() and "ending it as before" in r.getMessage()
        for r in caplog.records if r.levelno == logging.WARNING
    )


async def test_o6_a_segment_that_never_answers_after_a_newer_one_took_its_item_ends_nothing(
    make_rig, caplog, monkeypatch,
):
    """A-3 (F-R2-1), BF-825's ending: the run refused its cancellation past its grace,
    and by then the approval of its ask had admitted a newer segment."""
    monkeypatch.setattr(turn_promotion, "_ABANDON_GRACE_SECONDS", 0.05)
    rig = await make_rig(with_agent=False, episodic=True)
    caplog.set_level(logging.INFO)
    item, req = await _parked_promoted(rig, fulfil=False)
    assert await rig.work_items.transition_work_item(
        item.id, "in_progress", source="capability_gap_driver",
        expected_status="blocked", expected={"capability_request_id": req.id},
    ), "premise: AD-855's compare-and-set admitted a newer segment"
    release = asyncio.Event()

    async def _refuses() -> str:
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                if release.is_set():
                    return FINAL

    hold = await _a_segment(
        rig, item, _refuses, deadline_seconds=0.2, unconfirmed_grace_seconds=0.3,
        settle_expected={"capability_request_id": None},
    )
    try:
        after = await rig.work_items.get_work_item(item.id)
        assert after.status == "in_progress" and after.metadata["capability_request_id"] == req.id
        assert "stranded_reason" not in after.metadata
        assert _agent_bodies(rig) == [_REPORT_ABANDON_UNCONFIRMED], "premise: the interim notice only"
        assert len(rig.runtime.episodic_memory.stored) == 1
        messages = [r.getMessage() for r in caplog.records]
        assert any("did not answer its cancellation within its grace after the item" in m for m in messages)
        # A-4 (F-R3-2): BF-825's WARNING now announces an attempted guarded ending, so
        # its absence is asserted in those words; and a segment whose item moved on
        # attempts neither write, so no refusal is logged either -- with both writes
        # now refused by the store, that is what still tells a skipped write apart.
        assert not any("attempting a guarded ending" in m for m in messages)
        assert not any("refused the record of why it ended" in m for m in messages)
        assert not any("refused its guarded close" in m for m in messages)
    finally:
        release.set()
        for run in tuple(hold):
            run.cancel()
        if hold:
            await asyncio.wait(tuple(hold), timeout=_SETTLE_S)


async def test_o7_a_resumed_segment_closes_its_item_only_while_it_is_on_its_ask(make_rig, caplog):
    """A-3 (F-R2-1): the close of a segment an approved ask admitted is a
    compare-and-set on that ask."""
    rig = await make_rig(with_agent=False)
    caplog.set_level(logging.INFO)
    item, req = await _parked_promoted(rig, fulfil=False)
    resumed = await rig.work_items.transition_work_item(
        item.id, "in_progress", source="capability_gap_driver",
        expected_status="blocked", expected={"capability_request_id": req.id},
    )
    assert resumed is not None, "premise: in_progress on its ask"

    async def _finishes() -> str:
        return FINAL

    await _a_segment(rig, item, _finishes, settle_expected={"capability_request_id": "an-earlier-ask"})
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress", (
        "a segment an earlier ask admitted does not close an item on a later one"
    )

    await _a_segment(rig, item, _finishes, settle_expected={"capability_request_id": req.id})
    assert (await rig.work_items.get_work_item(item.id)).status == "done"


def _o8_config() -> DmAgenticConfig:
    """O1's deadline, and a BF-825 grace short enough to reach."""
    return DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        promote_to_task_after_seconds=0.05, promoted_run_deadline_seconds=_O_DEADLINE_S,
        promoted_run_unconfirmed_grace_seconds=0.15,
    )


class _HeldEpisodes(_Episodes):
    """The episodic store, its first ``store`` held until the test releases it: the
    wait a real store's sidecar write can take (the review measured 360 ms)."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def store(self, episode: Any) -> None:
        if not self.entered.is_set():
            self.entered.set()
            await asyncio.wait_for(self.release.wait(), timeout=_SETTLE_S)
        await super().store(episode)


@pytest.mark.parametrize("older", ["first", "resumed"])
async def test_o8_an_older_segment_whose_item_moves_on_while_its_episode_is_stored_ends_nothing(
    make_rig, scripted, caplog, monkeypatch, older,
):
    """A-4 (F-R3-1, F-R3-2), the review's seam. An older segment's run ignores the
    real BF-733 watchdog's stop past BF-825's grace; its reporter reads the item --
    still the older segment's -- and starts storing the episode. While that store
    waits, the run returns, files its ask and parks the item, and the real approval
    of that ask admits a newer, healthy segment. The store then refuses both of the
    older segment's closing writes, and each refusal is logged: the item stays
    in_progress under the newer segment with no reason recorded, and approving that
    segment's own ask runs the turn to done. ``first`` is the turn's own run (the
    review's regression); ``resumed`` is a segment an approved ask admitted."""
    monkeypatch.setattr(turn_promotion, "_ABANDON_GRACE_SECONDS", 0.05)
    rig = await make_rig(dm=_o8_config(), episodic=True)
    caplog.set_level(logging.INFO)
    older_pass = 0 if older == "first" else 1  # by index
    newer_pass = older_pass + 1
    scripted.script = [
        *([] if older == "first" else [_cut(PARTIAL)]),
        _cut(PARTIAL_2),
        _cut("Twelve of fifteen done; stopping again."),
        _done(FINAL),
    ]
    first_gate = asyncio.Event()
    scripted.gates = {0: first_gate, newer_pass: asyncio.Event()}
    release_older, ignored = asyncio.Event(), asyncio.Event()
    scripted_run = _Executor.run

    async def _ignores_its_stop(self: Any, **kwargs: Any) -> WorkItemAgenticOutcome:
        if len(_Executor.calls) != older_pass:
            return await scripted_run(self, **kwargs)
        _Executor.calls.append(kwargs)
        while not release_older.is_set():
            try:
                await release_older.wait()
            except asyncio.CancelledError:
                ignored.set()
        return _Executor.script[older_pass]

    monkeypatch.setattr(_Executor, "run", _ignores_its_stop)
    episodes = _HeldEpisodes()
    try:
        if older == "first":
            rig.runtime.episodic_memory = episodes
            await _turn(rig)
            (item,) = await rig.work_items.list_work_items(status="in_progress")
            admitted_on = None
        else:
            item, (first_ask,) = await _promote_and_stop(rig, first_gate)
            rig.runtime.episodic_memory = episodes
            await _approve_now(rig, first_ask.id)
            admitted_on = first_ask.id
        await _until(lambda: len(scripted.calls) == older_pass + 1)
        older_tasks = {t for t in rig.agent._promoted_turn_tasks if not t.done()}
        assert len(older_tasks) == 2, "premise: the older run and its reporter"
        await asyncio.wait_for(episodes.entered.wait(), timeout=_SETTLE_S)
        assert ignored.is_set(), "premise: the watchdog's stop reached the run, which ignored it"
        read = await rig.work_items.get_work_item(item.id)
        assert read.status == "in_progress" and read.metadata.get("capability_request_id") == admitted_on, (
            "premise: the reporter read the item while it was still the older segment's"
        )
        assert any(
            f"the promoted run for work item {item.id} did not land within" in r.getMessage()
            for r in caplog.records if r.levelno == logging.WARNING
        ), "premise: BF-825's ending began, after its read"
        assert episodes.stored == [] and all(not t.done() for t in older_tasks), (
            "premise: the reporter waits on the episode store, and the run is alive"
        )

        release_older.set()
        deadline = time.monotonic() + _SETTLE_S
        while True:
            pending = await rig.requests.list_pending()
            parked = await rig.work_items.get_work_item(item.id)
            if len(pending) == 1 and parked.status == "blocked" and (
                parked.metadata.get("capability_request_id") == pending[0].id
            ):
                break
            assert time.monotonic() < deadline, "premise: the older run filed its ask and parked the item"
            await asyncio.sleep(0.005)
        (older_ask,) = pending
        assert older_ask.kind == "continue" and older_ask.work_item_id == item.id
        await _approve_now(rig, older_ask.id)
        await _until(lambda: len(scripted.calls) == newer_pass + 1)
        newer_tasks = {t for t in rig.agent._promoted_turn_tasks if not t.done()} - older_tasks
        admitted = await rig.work_items.get_work_item(item.id)
        assert admitted.status == "in_progress" and admitted.metadata["capability_request_id"] == older_ask.id
        assert len(newer_tasks) == 2, "premise: the approval admitted the newer run and its reporter"

        episodes.release.set()
        await asyncio.wait(older_tasks, timeout=_SETTLE_S)
        assert all(t.done() for t in older_tasks), "premise: the older reporter ended its segment"
        assert not any(t.done() for t in newer_tasks), "premise: the newer segment is still running"
        assert len(episodes.stored) == 1, "premise: the older segment's episode was stored"

        after = await rig.work_items.get_work_item(item.id)
        assert after.status == "in_progress", "the newer segment owns the item, and the older one did not end it"
        assert after.metadata["capability_request_id"] == older_ask.id
        assert "stranded_reason" not in after.metadata, "no reason was recorded on the newer segment's item"
        messages = [r.getMessage() for r in caplog.records if item.id in r.getMessage()]
        assert any("attempting a guarded ending" in m for m in messages), "BF-825 announced only an attempt"
        assert any("refused the record of why it ended" in m for m in messages), "the refused reason is logged"
        assert any("refused its guarded close to failed" in m for m in messages), "the refused close is logged"

        scripted.gates[newer_pass].set()
        await _settle(rig)
        (next_ask,) = await rig.requests.list_pending()
        reparked = await rig.work_items.get_work_item(item.id)
        assert next_ask.work_item_id == item.id and reparked.status == "blocked"
        assert reparked.metadata["capability_request_id"] == next_ask.id

        await _approve(rig, next_ask.id)

        assert len(scripted.calls) == newer_pass + 2, "approving the newer segment's ask ran its next pass"
        assert _agent_bodies(rig)[-1] == FINAL
        assert (await rig.work_items.get_work_item(item.id)).status == "done"
        assert rig.dispatcher.events == [] and _held_turns(rig) == 0
    finally:
        release_older.set()
        episodes.release.set()


def test_o9_every_closing_write_of_a_segment_carries_its_compare_and_set() -> None:
    """A-4 (F-R3-1): the turn's own run closes under a compare-and-set as a resumed
    segment does -- on no ask being linked yet -- and only a caller that gives no
    ``settle_expected`` closes without one."""
    cas = turn_promotion._settle_cas

    assert cas({"capability_request_id": None}) == {"expected": {"capability_request_id": None}}
    assert cas({"capability_request_id": "r1"}) == {"expected": {"capability_request_id": "r1"}}
    assert cas(None) == {}
