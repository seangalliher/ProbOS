"""AD-1324 amendment 2 (finding 2): an armed run whose controller cannot be built fails closed."""

from __future__ import annotations

from typing import Any

import pytest

from probos.cognitive import tier_policy
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.tier_policy import FailedTierController
from tests.test_ad1324_audit import _build, _EventLog
from tests.test_ad1324_loop_tier_choice import Client, Tools, answer


def _boom(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("controller construction fault")


def test_armed_construction_fault_yields_a_failed_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _build(_EventLog()) is not None, "premise: this runtime arms and builds a real controller"
    monkeypatch.setattr(tier_policy, "TierChoiceController", _boom)
    ctl = _build(_EventLog())
    assert isinstance(ctl, FailedTierController)
    with pytest.raises(tier_policy.TierControllerUnavailable):
        ctl.next_request_tier()


def test_unarmed_construction_fault_cannot_arise_and_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tier_policy, "TierChoiceController", _boom)
    monkeypatch.setattr(tier_policy, "tier_choice_armed", lambda _runtime: False)
    assert _build(_EventLog()) is None


@pytest.mark.asyncio
async def test_failed_controller_makes_zero_model_calls_and_records_a_faulted_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _EventLog()
    monkeypatch.setattr(tier_policy, "TierChoiceController", _boom)
    ctl = _build(log)
    client, tools = Client([answer()]), Tools()
    loop = AgenticLoop(llm_client=client, tool_executor=tools, tier="fast", max_iterations=3, tier_controller=ctl)
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"})
    await ctl.drain_audit()
    assert client.requests == []
    assert result.stopped_reason == "error" and result.error == "tier_controller_failed"
    records = [c["data"] for c in log.calls]
    assert [r["outcome"] for r in records] == ["faulted"]
    assert records[0]["error_kind"] == "tier_controller_failed"
