"""AD-1356 S1.1 (#1722): under agent work, a call to a tool id the registry does not hold is refused before the gate.

Through the rig of ``tests/test_ad1347_s3_execution.py`` (the real runner, stores, executor and a scripted model) with a
cache-only ``FaultReportStore`` on the runtime, and the real ``DispatchToolExecutor`` over a real ``ToolRegistry``. On the
base this file fails at import (``UNREGISTERED_TOOL_REFUSAL``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from probos.agent_work import AgentWorkCreated, AgentWorkOrigin
from probos.capability_request import requests_for_work_item
from probos.cognitive import agentic_dispatch
from probos.cognitive.agentic_dispatch import (
    CONFINED_CALL_FILED,
    CONFINEMENT_FILED,
    UNREGISTERED_TOOL_REFUSAL,
    DispatchToolExecutor,
    ToolCallConfinement,
    classify_tool_fault_error,
)
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.swe_harness.tool_call import llm_function_name
from probos.fault_report import FaultReportStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from tests.test_ad1347_s1_agent_work import REASON
from tests.test_ad1347_s3_execution import _call, _final, _pump, _rig, _seen, _thread_in

UNKNOWN = "grep_app_placeholder_skip"


class _Probe:
    """A registered tool outside every read set, under a given id."""

    name = "Probe"
    tool_type = ToolType.INFRA_SERVICE
    description = "Answers once."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(output="probed")


# UT1
async def test_an_unregistered_tool_is_refused_not_filed_and_never_counts_toward_a_fault(tmp_path: Path) -> None:
    """Acceptance 3: the model is shown the refusal, which names search_capabilities; nothing is filed on the item; the
    item is done; and two refusals in one run leave the fault store empty with no FAULT_REPORTED."""
    script = [_call(UNKNOWN, {}, "c1"), _call(UNKNOWN, {}, "c2"), _final("No such tool; nothing to report.")]
    async with _rig(tmp_path, script) as rig:
        events: list[tuple[Any, dict[str, Any]]] = []
        faults = FaultReportStore(emit_event=lambda kind, data: events.append((kind, data)))
        rig.runtime.fault_report_store = faults
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Search the relay log", description="", reason=REASON,
            origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated), created
        await _pump(rig)
        item = await rig.store.get_work_item(created.work_item.id)
        assert item is not None and item.status == "done"
        assert requests_for_work_item(rig.requests, item.id) == []
        assert _seen(rig, UNREGISTERED_TOOL_REFUSAL)
        assert faults.list_open() == [] and events == []


# UT2
async def test_only_a_confined_call_to_an_unregistered_id_is_refused_before_the_gate() -> None:
    """Without a confinement the registry answers as before (#1214). Under one, an unregistered id is refused without
    asking the gate, and the refusal is a never-ran policy outcome; a registered tool outside the set, by its id or by
    its provider alias, is put to the gate."""
    registry = ToolRegistry()
    registry.register(_Probe("hull_survey"))
    registry.register(_Probe("ops:hull:survey"))
    executor = DispatchToolExecutor(registry=registry)
    unconfined = await executor.invoke("forge-1", UNKNOWN, {})
    assert unconfined.error == f"Tool '{UNKNOWN}' not found"
    asked: list[Any] = []

    async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
        asked.append(tool_id)
        return CONFINEMENT_FILED

    executor.confine_calls(ToolCallConfinement(frozenset({"event_log_query"}), gate))
    refused = await executor.invoke("forge-1", UNKNOWN, {})
    assert refused.error == UNREGISTERED_TOOL_REFUSAL and asked == []
    alias = llm_function_name("ops:hull:survey")
    for tool_id in ("hull_survey", alias):
        assert (await executor.invoke("forge-1", tool_id, {})).error == CONFINED_CALL_FILED
    assert asked == ["hull_survey", alias]
    assert UNREGISTERED_TOOL_REFUSAL in agentic_dispatch._NEVER_RAN_REFUSALS
    assert classify_tool_fault_error(UNREGISTERED_TOOL_REFUSAL) == "permission_denied"
    assert not is_capability_gap(UNREGISTERED_TOOL_REFUSAL) and "search_capabilities" in UNREGISTERED_TOOL_REFUSAL
