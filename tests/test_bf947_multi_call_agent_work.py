"""BF-947 (#1724): an agent-work item that files several calls waits for each, admits each approved one once, and is
given the results of the calls it already made.

Through the rig of ``tests/test_ad1347_s3_execution.py``: the real runner, ``WorkItemStore``, ``CapabilityRequestStore``,
AD-855's ``CapabilityGapDriver``, the approval route's ``decide_capability_request`` and ``WorkItemAgenticExecutor``,
driven by a scripted model. On the base this file fails at import (``CarriedResults``, ``requests_for_work_item``).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.agent_work import AgentWorkCreated, AgentWorkOrigin
from probos.agent_work_runner import (
    BLOCKED_REASON,
    CARRIED_PARAMS_MAX_CHARS,
    CARRIED_RESULT_MAX_CHARS,
    CARRIED_RESULTS_MAX,
    RUN_SOURCE,
    AgentWorkRunner,
    CarriedResults,
    approval_payload,
    task_text,
)
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import requests_for_work_item
from probos.cognitive.agentic_dispatch import CONFINED_CALL_ANSWERED, WorkItemAgenticExecutor
from probos.config import AgentWorkConfig
from probos.routers.capability_requests import decide_capability_request
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest
from tests.test_ad1347_s1_agent_work import REASON, STOP_REASON
from tests.test_ad1347_s3_execution import (
    CALLSIGNS,
    _call,
    _final,
    _pump,
    _request,
    _rig,
    _seen,
    _system_posts,
    _thread_in,
)

DECK_1 = {"deck": "1"}
DECK_2 = {"deck": "2"}
SURVEYED = "Hull integrity 98 percent"
CARRIED = "Do not make them again"


def _shown(request: LLMRequest) -> str:
    """What one model request showed: its plain prompt and its structured messages."""
    return (request.prompt or "") + "".join(str(message.get("content", "")) for message in (request.messages or []))


async def _self_task(rig: Any, thread_id: str, title: str = "Survey the hull") -> str:
    created = await rig.service.create_self_task(
        "forge-1", title=title, description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=thread_id),
    )
    assert isinstance(created, AgentWorkCreated), created
    return created.work_item.id


async def _decide(rig: Any, request_id: str, *, approve: bool, reason: str = "") -> None:
    """A decision through the approval route, then the stores' events delivered."""
    captain = SimpleNamespace(capability_request_store=rig.requests)
    decided = await decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=approve, reason=reason), runtime=captain,
    )
    assert decided["fulfilled"] is approve
    await _pump(rig)


def _restarted(
    rig: Any, *, clock: Callable[[], float] = time.time, executor: WorkItemAgenticExecutor | None = None,
) -> AgentWorkRunner:
    """A new runner over the same stores, as the next start builds one: its kept results start empty. ``executor``
    defaults to a ``WorkItemAgenticExecutor`` over the rig's model."""
    runner = AgentWorkRunner(
        service=rig.service, store=rig.store, ward_room=rig.wr, tools=rig.tools, requests=rig.requests,
        parking=rig.driver,
        executor=executor if executor is not None else WorkItemAgenticExecutor(llm_client=rig.llm),
        runtime=rig.runtime,
        agents=rig.runtime.registry, callsign_of=lambda slot: CALLSIGNS.get(slot, slot),
        ttl_seconds=AgentWorkConfig(enabled=True).ttl_seconds, clock=clock,
    )
    rig.runtime.agent_work_runner = runner
    rig.runner = runner
    return runner


# MC1
async def test_two_approved_calls_finish_the_item_in_one_resume(tmp_path: Path) -> None:
    """Acceptance 1: one run files two calls; the item waits for both decisions without running in between, then one
    resumed run makes both, once each, and the item is done. No call is filed twice."""
    script = [
        _call("hull_survey", DECK_1, "c1"), _call("hull_survey", DECK_2, "c2"), _final("Waiting for the Captain."),
        _call("hull_survey", DECK_1, "c3"), _call("hull_survey", DECK_2, "c4"), _final("Surveyed both decks."),
    ]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        item_id = await _self_task(rig, origin.id)
        await _pump(rig)
        parked = await rig.store.get_work_item(item_id)
        first, second = requests_for_work_item(rig.requests, item_id)
        assert parked is not None and parked.status == "blocked" and parked.metadata["capability_request_id"] == first.id
        assert (first.status, second.status, rig.survey.calls) == ("pending", "pending", 0)
        await _decide(rig, first.id, approve=True)
        again = await rig.store.get_work_item(item_id)
        assert again is not None and again.status == "blocked" and again.metadata["capability_request_id"] == second.id
        assert len(rig.llm.requests) == 3, "the item waits for every call it filed; no run in between"
        await _decide(rig, second.id, approve=True)
        done = await rig.store.get_work_item(item_id)
        assert done is not None and done.status == "done" and rig.survey.calls == 2 and len(rig.llm.requests) == 6
        assert [request.id for request in requests_for_work_item(rig.requests, item_id)] == [first.id, second.id]
        assert rig.runner.carried.for_agent(item_id, "forge-1") == ()
        [report] = _system_posts(rig, origin.id)
        assert "Surveyed both decks." in report


# MC2
async def test_a_resumed_run_is_given_earlier_results_and_a_repeat_is_answered_not_filed(tmp_path: Path) -> None:
    """Acceptance 3: the second run makes the first approved call and files a new one; the third run is given the
    first call's result, its repeat of that call is answered and does not run, and the item is done with each call
    made once and filed once."""
    script = [
        _call("hull_survey", DECK_1, "c1"), _final("Waiting for the Captain."),
        _call("hull_survey", DECK_1, "c2"), _call("hull_survey", DECK_2, "c3"), _final("Waiting for the Captain."),
        _call("hull_survey", DECK_1, "c4"), _call("hull_survey", DECK_2, "c5"), _final("Surveyed both decks."),
    ]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        item_id = await _self_task(rig, origin.id)
        await _pump(rig)
        [first] = requests_for_work_item(rig.requests, item_id)
        await _decide(rig, first.id, approve=True)
        assert rig.survey.calls == 1
        _, second = requests_for_work_item(rig.requests, item_id)
        await _decide(rig, second.id, approve=True)
        done = await rig.store.get_work_item(item_id)
        assert done is not None and done.status == "done" and rig.survey.calls == 2 and len(rig.llm.requests) == 8
        assert [request.id for request in requests_for_work_item(rig.requests, item_id)] == [first.id, second.id]
        third_run = _shown(rig.llm.requests[5])
        assert '- hull_survey {"deck": "1"}: ' in third_run and SURVEYED in third_run and CARRIED in third_run
        assert CARRIED not in _shown(rig.llm.requests[2])
        assert _seen(rig, CONFINED_CALL_ANSWERED)


# MC3
async def test_a_denied_call_the_item_is_not_parked_on_cancels_it_at_its_next_run(tmp_path: Path) -> None:
    """Acceptance 2: a denial of the second filed call leaves the item parked on the first; deciding the first starts
    its next run, which cancels the item with that reason, runs nothing and reports the reason."""
    script = [_call("hull_survey", DECK_1, "c1"), _call("hull_survey", DECK_2, "c2"), _final("Waiting for the Captain.")]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        item_id = await _self_task(rig, origin.id)
        await _pump(rig)
        first, second = requests_for_work_item(rig.requests, item_id)
        await _decide(rig, second.id, approve=False, reason="not that deck")
        still = await rig.store.get_work_item(item_id)
        assert still is not None and still.status == "blocked" and still.metadata["capability_request_id"] == first.id
        await _decide(rig, first.id, approve=True)
        ended = await rig.store.get_work_item(item_id)
        assert ended is not None and ended.status == "cancelled" and ended.metadata["denial_reason"] == "not that deck"
        assert rig.survey.calls == 0 and len(rig.llm.requests) == 3
        [report] = _system_posts(rig, origin.id)
        assert "not that deck" in report


# MC4
async def test_an_item_parked_before_this_fix_waits_for_its_other_filed_call(tmp_path: Path) -> None:
    """Q1's compatibility path: the state the runner before BF-947 left, built by hand (parked on its first filed call,
    a second filed call pending); approving the first parks it on the second without a run; approving the second runs
    both calls once."""
    script = [_call("hull_survey", DECK_1, "c1"), _call("hull_survey", DECK_2, "c2"), _final("Surveyed both decks.")]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        item_id = await _self_task(rig, origin.id)
        rig.work_events.clear()  # no run of this runner made the state below
        assert await rig.store.transition_work_item(item_id, "in_progress", source=RUN_SOURCE, expected_status="open")
        first = await rig.requests.file_action_request(
            "forge-1", approval_payload("hull_survey", DECK_1, item_id), rationale="filed before BF-947", work_item_id=item_id,
        )
        second = await rig.requests.file_action_request(
            "forge-1", approval_payload("hull_survey", DECK_2, item_id), rationale="filed before BF-947", work_item_id=item_id,
        )
        assert await rig.driver.block_on_request(work_item_id=item_id, request_id=first.id, reason=BLOCKED_REASON)
        rig.work_events.clear()
        rig.request_events.clear()
        await _decide(rig, first.id, approve=True)
        waiting = await rig.store.get_work_item(item_id)
        assert waiting is not None and waiting.status == "blocked" and waiting.metadata["capability_request_id"] == second.id
        assert rig.llm.requests == []
        await _decide(rig, second.id, approve=True)
        done = await rig.store.get_work_item(item_id)
        assert done is not None and done.status == "done" and rig.survey.calls == 2


# MC5
async def test_after_a_restart_a_used_approval_is_not_admitted_again(tmp_path: Path) -> None:
    """Acceptance 4 and limit L1: a call made under its approval before a restart is filed again when the run after the
    restart repeats it (the new runner keeps no results), and is not run a second time."""
    script = [
        _call("hull_survey", DECK_1, "c1"), _final("Waiting for the Captain."),
        _call("hull_survey", DECK_1, "c2"), _call("hull_survey", DECK_2, "c3"), _final("Waiting for the Captain."),
        _call("hull_survey", DECK_1, "c4"), _call("hull_survey", DECK_2, "c5"), _final("Waiting for the Captain."),
    ]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        item_id = await _self_task(rig, origin.id)
        await _pump(rig)
        [first] = requests_for_work_item(rig.requests, item_id)
        await _decide(rig, first.id, approve=True)
        _, second = requests_for_work_item(rig.requests, item_id)
        runner = _restarted(rig)
        try:
            await _decide(rig, second.id, approve=True)
            assert rig.survey.calls == 2, "each approved call ran once"
            *_, third = requests_for_work_item(rig.requests, item_id)
            assert third.id not in (first.id, second.id) and third.status == "pending" and third.payload["params"] == DECK_1
            parked = await rig.store.get_work_item(item_id)
            assert parked is not None and parked.status == "blocked" and parked.metadata["capability_request_id"] == third.id
        finally:
            await runner.stop()


# MC6
async def test_the_task_text_states_the_current_utc_time(tmp_path: Path) -> None:
    """Acceptance 5: a run's task text carries the runner's clock as UTC; the function formats any epoch time."""
    async with _rig(tmp_path, [_final()]) as rig:
        runner = _restarted(rig, clock=lambda: 0.0)
        try:
            origin = await _thread_in(rig, "engineering", "laforge-1")
            item_id = await _self_task(rig, origin.id)
            await _pump(rig)
            assert _seen(rig, "Current UTC time: 1970-01-01T00:00:00Z.")
            item = await rig.store.get_work_item(item_id)
            assert item is not None and item.status == "done"
            assert "Current UTC time: 1971-01-01T00:00:00Z." in task_text(item, requester="Forge", now=31_536_000.0)
        finally:
            await runner.stop()


# MC7
async def test_another_claimant_is_not_given_the_first_claimants_results(tmp_path: Path) -> None:
    """A request's first claimant makes an approved call and files another; stopped, it loses the request at its next
    run; the next claimant's task text holds none of the first claimant's results, and its own call is filed."""
    script = [
        _call("hull_survey", DECK_1, "c1"), _final("Waiting for the Captain."),
        _call("hull_survey", DECK_1, "c2"), _call("hull_survey", DECK_2, "c3"), _final("Waiting for the Captain."),
        _call("hull_survey", DECK_1, "c4"), _final("Waiting for the Captain."),
    ]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        assert (await rig.runner.claim("forge-1", item_id))[0] == "claimed"
        await _pump(rig)
        [first] = requests_for_work_item(rig.requests, item_id)
        await _decide(rig, first.id, approve=True)
        assert rig.survey.calls == 1 and rig.runner.carried.for_agent(item_id, "forge-1") != ()
        _, second = requests_for_work_item(rig.requests, item_id)
        await rig.stops.issue_stop("forge-1", reason=STOP_REASON)
        await _decide(rig, second.id, approve=True)
        released = await rig.store.get_work_item(item_id)
        assert released is not None and (released.status, released.assigned_to) == ("open", None)
        assert (await rig.runner.claim("laforge-1", item_id))[0] == "claimed"
        await _pump(rig)
        shown = _shown(rig.llm.requests[5])
        assert SURVEYED not in shown and CARRIED not in shown
        *_, third = requests_for_work_item(rig.requests, item_id)
        assert (third.agent_id, third.status, rig.survey.calls) == ("laforge-1", "pending", 1)


# MC8
async def test_a_denial_on_another_item_of_the_same_agent_leaves_this_one_alone(tmp_path: Path) -> None:
    """Two items of one agent file the same call; denying one item's request cancels that item only, and the other's
    approval runs its call."""
    script = [
        _call("hull_survey", DECK_1, "c1"), _final("Waiting for the Captain."),
        _call("hull_survey", DECK_1, "c1"), _final("Waiting for the Captain."),
        _call("hull_survey", DECK_1, "c2"), _final("Surveyed deck one."),
    ]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        a_id = await _self_task(rig, origin.id, "Survey deck one")
        await _pump(rig)
        b_id = await _self_task(rig, origin.id, "Survey deck one for the log")
        await _pump(rig)
        [a_request] = requests_for_work_item(rig.requests, a_id)
        [b_request] = requests_for_work_item(rig.requests, b_id)
        await _decide(rig, a_request.id, approve=False, reason="once is enough")
        await _decide(rig, b_request.id, approve=True)
        a_item, b_item = await rig.store.get_work_item(a_id), await rig.store.get_work_item(b_id)
        assert a_item is not None and b_item is not None and (a_item.status, b_item.status) == ("cancelled", "done")
        assert rig.survey.calls == 1


# MC9
def test_the_runner_keeps_the_newest_results_without_an_error_each_cut() -> None:
    """M3's bounds: an error result is not kept; the newest ``CARRIED_RESULTS_MAX`` per item are, oldest first; an
    entry replaces one with the same call key; parameters and output are cut; items and agents are kept apart."""
    carried = CarriedResults()
    record = carried.recorder("wi-carried-1")
    record("forge-1", "hull_survey", {"deck": "x"}, ToolResult(error="the hull sensors did not answer"))
    assert carried.for_agent("wi-carried-1", "forge-1") == ()
    for deck in range(CARRIED_RESULTS_MAX + 2):
        record("forge-1", "hull_survey", {"deck": str(deck)}, ToolResult(output=f"deck {deck} sound"))
    kept = carried.for_agent("wi-carried-1", "forge-1")
    assert [entry.output for entry in kept] == [f"deck {deck} sound" for deck in range(2, CARRIED_RESULTS_MAX + 2)]
    record("forge-1", "hull_survey", {"deck": "2"}, ToolResult(output="deck 2 sound again"))
    again = carried.for_agent("wi-carried-1", "forge-1")
    assert len(again) == CARRIED_RESULTS_MAX and (again[-1].output, again[-1].params) == ("deck 2 sound again", '{"deck": "2"}')
    assert [entry.output for entry in again[:-1]] == [f"deck {deck} sound" for deck in range(3, CARRIED_RESULTS_MAX + 2)]
    assert carried.for_agent("wi-carried-1", "laforge-1") == () and carried.for_agent("wi-carried-2", "forge-1") == ()
    carried.recorder("wi-carried-2")("forge-1", "hull_survey", {"note": "n" * 300}, ToolResult(output="o" * 2_000))
    [cut] = carried.for_agent("wi-carried-2", "forge-1")
    assert (len(cut.params), len(cut.output)) == (CARRIED_PARAMS_MAX_CHARS, CARRIED_RESULT_MAX_CHARS)
    carried.forget("wi-carried-2")
    assert carried.for_agent("wi-carried-2", "forge-1") == ()


class _RaisesAfterRun(WorkItemAgenticExecutor):
    """The real executor, whose run then raises: a failure after the run's calls returned."""

    async def run(self, **kwargs: Any) -> Any:
        await super().run(**kwargs)
        raise RuntimeError("the run failed after its calls returned")


# MC12
@pytest.mark.parametrize("raises", [False, True], ids=["the_run_returns", "the_run_raises"])
async def test_a_call_that_returns_after_its_item_ended_leaves_no_result_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raises: bool,
) -> None:
    """A2 (F2): an admitted call still running when its item is cancelled returns after the terminal event dropped the
    item's results, and is recorded then. The run reads the item again after its executor returns, or in its failure
    handler when the executor raises, and keeps nothing for the ended item."""
    script = [
        _call("hull_survey", DECK_1, "c1"), _final("Waiting for the Captain."),
        _call("hull_survey", DECK_1, "c2"), _final("Surveyed deck one."),
    ]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        item_id = await _self_task(rig, origin.id)
        await _pump(rig)
        [request] = requests_for_work_item(rig.requests, item_id)
        if raises:
            _restarted(rig, executor=_RaisesAfterRun(llm_client=rig.llm))
        entered, released = asyncio.Event(), asyncio.Event()
        survey = rig.survey.invoke

        async def held(params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
            entered.set()
            await released.wait()
            return await survey(params, context)

        monkeypatch.setattr(rig.survey, "invoke", held)
        deciding = asyncio.create_task(_decide(rig, request.id, approve=True))
        try:
            await asyncio.wait_for(entered.wait(), 10)
            moved = await rig.store.transition_work_item(
                item_id, "cancelled", source="captain", expected_status="in_progress",
            )
            assert moved is not None
            events = list(rig.work_events)
            rig.work_events.clear()
            for kind, data in events:
                await rig.runner.on_store_event({"type": getattr(kind, "value", kind), "data": data})
            assert rig.runner.carried.for_agent(item_id, "forge-1") == (), "the terminal event dropped the results"
        finally:
            released.set()
            await asyncio.wait_for(deciding, 20)
        ended = await rig.store.get_work_item(item_id)
        assert ended is not None and ended.status == "cancelled" and rig.survey.calls == 1
        assert rig.runner.carried.for_agent(item_id, "forge-1") == (), "the late result is not kept on the ended item"


# MC13
@pytest.mark.parametrize("held_in", ["the_model", "the_failure_handler"])
async def test_a_run_stopped_after_a_late_result_leaves_no_result_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held_in: str,
) -> None:
    """A3 (F2): an admitted call returns after its item was cancelled and the terminal event dropped the item's
    results, and is recorded then. ``stop`` then cancels the run while it waits for the model, or while its failure
    handler marks the item failed, before that handler's ``_forget_if_ended``. The run's ``finally`` keeps nothing for
    the item on either exit."""
    reached, never = asyncio.Event(), asyncio.Event()

    async def held_model(request: LLMRequest) -> Any:
        reached.set()
        await never.wait()
        raise AssertionError("the model is never released")

    last: Any = held_model if held_in == "the_model" else _final("Surveyed deck one.")
    script = [
        _call("hull_survey", DECK_1, "c1"), _final("Waiting for the Captain."), _call("hull_survey", DECK_1, "c2"), last,
    ]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        item_id = await _self_task(rig, origin.id)
        await _pump(rig)
        [request] = requests_for_work_item(rig.requests, item_id)
        if held_in == "the_failure_handler":
            _restarted(rig, executor=_RaisesAfterRun(llm_client=rig.llm))
            transition = rig.store.transition_work_item

            async def held_failure(work_item_id: str, new_status: str, *args: Any, **kwargs: Any) -> Any:
                if new_status == "failed":
                    reached.set()
                    await never.wait()
                return await transition(work_item_id, new_status, *args, **kwargs)

            monkeypatch.setattr(rig.store, "transition_work_item", held_failure)
        entered, released = asyncio.Event(), asyncio.Event()
        survey = rig.survey.invoke

        async def held(params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
            entered.set()
            await released.wait()
            return await survey(params, context)

        monkeypatch.setattr(rig.survey, "invoke", held)
        deciding = asyncio.create_task(_decide(rig, request.id, approve=True))
        try:
            await asyncio.wait_for(entered.wait(), 10)
            moved = await rig.store.transition_work_item(
                item_id, "cancelled", source="captain", expected_status="in_progress",
            )
            assert moved is not None
            events = list(rig.work_events)
            rig.work_events.clear()
            for kind, data in events:
                await rig.runner.on_store_event({"type": getattr(kind, "value", kind), "data": data})
            assert rig.runner.carried.for_agent(item_id, "forge-1") == (), "the terminal event dropped the results"
            released.set()
            await asyncio.wait_for(reached.wait(), 10)
            assert len(rig.runner.carried.for_agent(item_id, "forge-1")) == 1, "the late result was recorded"
        finally:
            released.set()
            await rig.runner.stop()
            await asyncio.gather(deciding, return_exceptions=True)  # its wait for the run ends with the cancellation
        ended = await rig.store.get_work_item(item_id)
        assert ended is not None and ended.status == "cancelled" and rig.survey.calls == 1
        assert rig.runner.carried.for_agent(item_id, "forge-1") == (), "a stopped run keeps nothing for its item"
