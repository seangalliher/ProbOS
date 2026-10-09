"""AD-1324 amendment 4: terminal records carry their context; a failed call is a terminal; cause reaches the card."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, AgenticResult
from probos.cognitive.tier_audit import TierAuditSink
from probos.substrate.event_log import EventLog
from tests.test_ad1324_audit import _build
from tests.test_ad1324_loop_tier_choice import DIRECTIVE, Client, Tools, answer, read
from tests.test_ad1324_tier_choice_e2e import _drive, endpoint  # noqa: F401  (fixture)

_CAUSE_SENTENCES = {
    "ceiling": "the configured cost ceiling excludes every model at or above that tier",
    "exact_unavailable": "the tier chosen for the step could not serve the request",
}


async def _records(log: EventLog) -> list[dict[str, Any]]:
    rows = await log.query(category="cognitive", limit=200)
    return [r["data"] for r in rows if r["event"] == "ad1324_tier_decision"]


@pytest.fixture
async def event_log(tmp_path: Any):
    log = EventLog(tmp_path / "e.db")
    await log.start()
    try:
        yield log
    finally:
        await log.stop()


@pytest.fixture
async def store(tmp_path: Any):
    s = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"), emit_event=lambda *_a, **_k: None)
    await s.start()
    try:
        yield s
    finally:
        stop = getattr(s, "stop", None)
        if stop is not None:
            await stop()


@pytest.fixture
def admits(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    """(request id, refusal cause) of every admission the production loop asked for."""
    from probos.cognitive.swe_harness.loop_tier_steps import LoopTierSteps

    seen: list[tuple[Any, Any]] = []
    real = LoopTierSteps.admit

    def spy(self: Any, request: Any, decision: Any) -> Any:
        refusal = real(self, request, decision)
        seen.append((request.id, getattr(refusal, "cause", None)))
        return refusal

    monkeypatch.setattr(LoopTierSteps, "admit", spy)
    return seen


@pytest.mark.asyncio
async def test_floor_stop_terminal_records_carry_work_item_tiers_and_request_id(
    endpoint: Any, event_log: EventLog, store: CapabilityRequestStore, admits: list[tuple[Any, Any]],
) -> None:
    seen = admits
    outcome, *_ = await _drive(
        endpoint=endpoint, armed=True, stakes="severe", ceiling=20.0, event_log=event_log, store=store,
    )
    assert endpoint.bodies == [] and outcome.stopped_reason == "tier_floor_unavailable"
    records = [r for r in await _records(event_log) if r["outcome"] in ("refused", "asked")]
    assert sorted(r["outcome"] for r in records) == ["asked", "refused"], "premise: one refused and one asked"
    assert len(seen) == 1, "premise: exactly one admission was asked for"
    pending = await store.list_pending()
    assert len(pending) == 1
    for record in records:
        assert record["work_item_id"] == "wi-1"
        assert (record["requested_tier"], record["effective_tier"], record["floor"]) == ("fast", "deep", "deep")
        assert record["request_id"] == seen[0][0]
        assert record["error_kind"] == "tier_floor_unmet"
    asked = next(r for r in records if r["outcome"] == "asked")
    assert asked["ask_request_id"] == str(pending[0].id)


@pytest.mark.asyncio
async def test_terminal_cause_matches_what_the_live_router_returned(
    endpoint: Any, event_log: EventLog, store: CapabilityRequestStore, admits: list[tuple[Any, Any]],
) -> None:
    seen = admits
    await _drive(
        endpoint=endpoint, armed=True, stakes="severe", ceiling=20.0, event_log=event_log, store=store,
    )
    assert len(seen) == 1 and seen[0][1] is not None, "premise: the loop named a cause"
    records = [r for r in await _records(event_log) if r["outcome"] in ("refused", "asked")]
    assert len(records) == 2
    assert {r["cause"] for r in records} == {seen[0][1]}


@pytest.mark.asyncio
async def test_plan_refusal_without_a_decision_records_empty_tiers_but_known_work_item(
    event_log: EventLog, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.cognitive import tier_policy

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("fault")

    monkeypatch.setattr(tier_policy, "TierChoiceController", _boom)
    ctl = _build(event_log)
    client = Client([answer()])
    loop = AgenticLoop(llm_client=client, tool_executor=Tools(), tier="fast", max_iterations=3, tier_controller=ctl)
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"})
    await ctl.drain_audit()
    assert client.requests == []
    records = await _records(event_log)
    assert len(records) == 1
    assert (records[0]["requested_tier"], records[0]["effective_tier"]) == ("", "")
    assert result.tier_stop is not None and result.tier_stop.effective_tier == ""


class _RaisingClient(Client):
    def __init__(self, responses: list[Any], raise_on: int, exc: BaseException) -> None:
        super().__init__(responses)
        self._raise_on = raise_on
        self._exc = exc

    async def complete(self, req: Any, **kw: Any) -> Any:
        self.requests.append(req)
        if len(self.requests) == self._raise_on:
            raise self._exc
        return self._responses.pop(0)


async def _armed_run(event_log: EventLog, client: Any) -> tuple[AgenticResult, Any]:
    ctl = _build(event_log, stakes="high")
    assert ctl is not None, "premise: the armed runtime builds a controller"
    loop = AgenticLoop(llm_client=client, tool_executor=Tools(), tier="fast", max_iterations=5, tier_controller=ctl)
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"})
    await ctl.drain_audit()
    return result, ctl


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("redo", "raise_on", "responses", "cause"),
    [(True, 3, [read(DIRECTIVE), answer("quick guess")], "redo_call_failed"), (False, 1, [], "call_failed")],
    ids=["redo", "first"],
)
async def test_call_exception_emits_one_faulted_terminal(
    event_log: EventLog, redo: bool, raise_on: int, responses: list[Any], cause: str,
) -> None:
    client = _RaisingClient(responses, raise_on, RuntimeError("boom"))
    result, _ = await _armed_run(event_log, client)
    assert len(client.requests) == raise_on, "premise: the failing call was reached"
    assert result.stopped_reason == "error" and result.error == "boom"
    records = [r for r in await _records(event_log) if r["outcome"] in ("refused", "asked", "faulted")]
    assert len(records) == 1
    record = records[0]
    assert (record["outcome"], record["error_kind"], record["cause"]) == ("faulted", "llm_call_failed", cause)
    assert record["work_item_id"] == "wi-9" and record["effective_tier"] in ("fast", "standard", "deep")
    assert record["request_id"] == client.requests[-1].id
    assert "boom" not in str(record)
    if redo:
        assert record["effective_tier"] == "standard"


@pytest.mark.asyncio
async def test_cancelled_error_on_redo_still_propagates_and_writes_no_terminal(event_log: EventLog) -> None:
    client = _RaisingClient([read(DIRECTIVE), answer("quick guess")], 3, asyncio.CancelledError())
    ctl = _build(event_log, stakes="high")
    loop = AgenticLoop(llm_client=client, tool_executor=Tools(), tier="fast", max_iterations=5, tier_controller=ctl)
    with pytest.raises(asyncio.CancelledError):
        await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"})
    await ctl.drain_audit()
    assert [r for r in await _records(event_log) if r["outcome"] in ("refused", "asked", "faulted")] == []


@pytest.mark.asyncio
async def test_unarmed_exception_path_is_unchanged_and_writes_no_event(event_log: EventLog) -> None:
    client = _RaisingClient([], 1, RuntimeError("boom"))
    loop = AgenticLoop(llm_client=client, tool_executor=Tools(), tier="fast", max_iterations=3)
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"})
    assert (result.stopped_reason, result.error, result.final_text) == ("error", "boom", "")
    assert result.tier_stop is None
    assert await _records(event_log) == []


@pytest.mark.asyncio
async def test_emit_terminal_sanitises_new_fields(event_log: EventLog) -> None:
    sink = TierAuditSink(event_log, agent_id="a", thread_id="t")
    sink.emit_terminal(
        outcome="refused", step=1, floor="deep", request_id="r1", work_item_id="free text here",
        requested_tier="ultra", effective_tier="deep",
    )
    sink.emit_terminal(outcome="refused", step=1, floor="deep", request_id="r2", work_item_id="w" * 81)
    sink.emit_terminal(
        outcome="refused", step=1, floor="deep", request_id="r3", work_item_id="wi-1:a.b_c", requested_tier="fast",
    )
    await sink.drain()
    by_id = {r["request_id"]: r for r in await _records(event_log)}
    assert sorted(by_id) == ["r1", "r2", "r3"], "premise: all three records landed"
    first, second, third = by_id["r1"], by_id["r2"], by_id["r3"]
    assert (first["work_item_id"], first["requested_tier"], first["effective_tier"]) == (None, "", "deep")
    assert second["work_item_id"] is None
    assert (third["work_item_id"], third["requested_tier"]) == ("wi-1:a.b_c", "fast")
    assert len(first) == len(second) == len(third) == 17


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", list(_CAUSE_SENTENCES))
async def test_cause_sentence_reaches_the_filed_card_through_the_executor(
    endpoint: Any, event_log: EventLog, store: CapabilityRequestStore, monkeypatch: pytest.MonkeyPatch, cause: str,
) -> None:
    from probos.cognitive.llm_client import OpenAICompatibleClient

    real = OpenAICompatibleClient.complete

    async def forced(self: Any, req: Any, **kw: Any) -> Any:
        response = await real(self, req, **kw)
        response.error_kind = "tier_floor_unmet"
        response.refusal_cause = cause
        return response

    monkeypatch.setattr(OpenAICompatibleClient, "complete", forced)
    seen: list[tuple[Any, Any]] = []
    await _drive(
        endpoint=endpoint, armed=True, stakes="severe", ceiling=None, event_log=event_log, store=store, seen=seen,
    )
    assert seen and seen[0][1] == cause, "premise: the router-side response carried the forced cause"
    pending = await store.list_pending()
    assert len(pending) == 1
    assert f"Cause: {_CAUSE_SENTENCES[cause]}." in pending[0].rationale
    await _drive(
        endpoint=endpoint, armed=True, stakes="severe", ceiling=None, event_log=event_log, store=store,
    )
    assert len(await store.list_pending()) == 1
