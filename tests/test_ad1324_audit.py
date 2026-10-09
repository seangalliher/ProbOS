"""AD-1324 amendment 1 (finding 9): the production-built controller audits every decision.

The sink is NOT supplied by the test: ``WorkItemAgenticExecutor._build_tier_controller`` builds
it, and the record reaches the runtime's ``event_log`` (the existing public audit seam).
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive import agentic_dispatch
from probos.cognitive.model_registry import ModelRegistry
from probos.cognitive.model_router import ModelRouter
from probos.cognitive.tier_policy import split_directive

SECRET = "TOP-SECRET-PROMPT-TEXT"


class _EventLog:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def log(self, category: str, event: str, agent_id: str | None = None, *a: Any, **kw: Any) -> None:
        if self.fail:
            raise RuntimeError("event log down")
        self.calls.append({"category": category, "event": event, "agent_id": agent_id, **kw})


def _runtime(event_log: Any) -> Any:
    dm = SimpleNamespace(
        enabled=True,
        economic_judgment=SimpleNamespace(
            enabled=True, verification_tool_ids=[],
            tier_choice=SimpleNamespace(
                enabled=True, stakes_floor={"high": "standard", "severe": "deep"}, max_upward_moves_per_turn=2,
            ),
        ),
    )
    return SimpleNamespace(
        config=SimpleNamespace(dm_agentic=dm, model_routing=SimpleNamespace(enabled=True)),
        model_router=ModelRouter(registry=ModelRegistry()),
        event_log=event_log,
    )

def _build(event_log: Any, stakes: str = "severe") -> Any:
    hook = SimpleNamespace(costed_case=lambda: SimpleNamespace(stakes=stakes, signals=()))
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=SimpleNamespace())
    return executor._build_tier_controller(
        runtime=_runtime(event_log), registry=None, agent_id="ezri", tier="fast",
        inner_loop_hook=hook, extra_context={"_crew_work_item_id": "wi-9"}, work_item_id_provider=None,
        thread_id="thread-1",
    )


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def _valid(tier: str, reason: str) -> Any:
    return split_directive(SimpleNamespace(content=f'x\n@@next_tier {{"tier":"{tier}","reason":"{reason}"}}', content_blocks=[]))[1]


@pytest.mark.asyncio
async def test_production_built_controller_emits_record_with_evidence_model_reason_and_work_item() -> None:
    log = _EventLog()
    ctl = _build(log, stakes="low")
    assert ctl is not None, "premise: the armed runtime builds a controller"
    decision = ctl.next_request_tier()
    ctl.after_tools(tool_names=["x"], all_tier1=False, results_is_error=[True])
    assert ctl.observe(decision, _valid("standard", "prior_error"), prompt_tokens_estimate=10) == "agent_choice"
    await _settle()
    assert log.calls, "premise: the record reached the event log"
    assert {c["event"] for c in log.calls} == {"ad1324_tier_decision"}
    record = log.calls[-1]["data"]
    assert record["work_item_id"] == "wi-9" and record["agent_id"] == "ezri" and record["thread_id"] == "thread-1"
    assert record["evidence"] == "prior_error"
    assert record["model_reason"] == "prior_error"
    assert record["requested_tier"] == "standard" and record["effective_tier"] == "standard"
    assert record["outcome"] == "served" and record["exact"] is True and record["step"] == 1
    assert set(record) >= {
        "agent_id", "work_item_id", "thread_id", "step", "requested_tier", "effective_tier", "floor",
        "outcome", "evidence", "model_reason", "exact",
    }


@pytest.mark.asyncio
async def test_floor_raise_is_recorded_as_raised() -> None:
    log = _EventLog()
    ctl = _build(log, stakes="severe")
    ctl.next_request_tier()
    await _settle()
    assert log.calls[0]["data"]["outcome"] == "raised" and log.calls[0]["data"]["floor"] == "deep"


@pytest.mark.asyncio
async def test_audit_record_contains_no_prompt_or_response_text() -> None:
    log = _EventLog()
    ctl = _build(log, stakes="low")
    decision = ctl.next_request_tier()
    ctl.observe(decision, split_directive(SimpleNamespace(content=f"{SECRET}\n@@next_tier junk", content_blocks=[]))[1],
                prompt_tokens_estimate=1)
    await _settle()
    assert log.calls and SECRET not in repr(log.calls)


@pytest.mark.asyncio
async def test_audit_sink_exception_does_not_break_the_step(caplog: pytest.LogCaptureFixture) -> None:
    ctl = _build(_EventLog(fail=True), stakes="severe")
    with caplog.at_level(logging.WARNING):
        decision = ctl.next_request_tier()
        await _settle()
    assert decision.tier == "deep"


@pytest.mark.asyncio
async def test_log_line_has_evidence_reason_and_work_item(caplog: pytest.LogCaptureFixture) -> None:
    ctl = _build(None, stakes="low")  # no event log at all: the log line is the sink
    with caplog.at_level(logging.INFO):
        decision = ctl.next_request_tier()
        ctl.after_tools(tool_names=["x"], all_tier1=False, results_is_error=[True])
        ctl.observe(decision, _valid("standard", "prior_error"), prompt_tokens_estimate=1)
    text = "\n".join(r.getMessage() for r in caplog.records if "AD-1324" in r.getMessage())
    assert "wi-9" in text and "prior_error" in text and "evidence" in text
