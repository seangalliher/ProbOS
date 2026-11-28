"""AD-1356 S1.2 (#1722): a tool's mark of its caller's bad input is not a fault, on either filing path.

Through the rig of ``tests/test_ad1347_s3_execution.py``: a self-task's run calls ``event_log_query`` (registered by its
production function); the real executor's fault observer files into a cache-only ``FaultReportStore``, and the DM path's
filer is ``cognitive_agent._file_pass_defect`` on the run's own outcome. On the base this file fails at import
(``is_caller_input_error``).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.agent_work import AgentWorkCreated, AgentWorkOrigin
from probos.cognitive.agentic_dispatch import classify_tool_fault_error
from probos.cognitive.cognitive_agent import _file_pass_defect
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolCallResult
from probos.config import AgentWorkConfig
from probos.events import EventType
from probos.fault_detection import collect_tool_fault_batch
from probos.fault_report import FaultReportStore
from probos.substrate.event_log import EventLog
from probos.tools.protocol import is_caller_input_error
from tests.test_ad1347_s1_agent_work import REASON
from tests.test_ad1347_s3_execution import WINDOW, _call, _final, _pump, _rig, _seen, _thread_in, _watch_runs

NO_FILTER = {"start_time": WINDOW["start_time"], "end_time": WINDOW["end_time"]}
MARKED = "event_log_query_invalid:filter_required"
SECTION = AgentWorkConfig(enabled=True, max_open_per_agent=10, max_created_per_agent_per_hour=10)


def _faults(rig: Any) -> tuple[FaultReportStore, list[tuple[Any, dict[str, Any]]]]:
    events: list[tuple[Any, dict[str, Any]]] = []
    store = FaultReportStore(emit_event=lambda kind, data: events.append((kind, data)))
    rig.runtime.fault_report_store = store
    return store, events


async def _run_self_task(rig: Any, title: str) -> str:
    origin = await _thread_in(rig, "engineering", "laforge-1")
    created = await rig.service.create_self_task(
        "forge-1", title=title, description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
    )
    assert isinstance(created, AgentWorkCreated), created
    await _pump(rig)
    item = await rig.store.get_work_item(created.work_item.id)
    assert item is not None and item.status == "done", item
    return item.id


# IE1
async def test_caller_input_errors_in_three_runs_file_no_fault_on_the_observer_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 4, the AD-1205 observer path: two marked errors in each of three runs leave the store empty with no
    FAULT_REPORTED, and each run's own verdict is None."""
    runs = _watch_runs(monkeypatch)
    script: list[Any] = []
    for n in range(3):
        script += [
            _call("event_log_query", NO_FILTER, f"a{n}"), _call("event_log_query", NO_FILTER, f"b{n}"),
            _final("No filter was given."),
        ]
    async with _rig(tmp_path, script, section=SECTION) as rig:
        faults, events = _faults(rig)
        for n in range(3):
            await _run_self_task(rig, f"Read the relay log {n}")
        assert _seen(rig, MARKED)
        assert faults.list_open() == [] and events == []
        assert [run["outcome"].tool_defect for run in runs] == [None, None, None]


# IE2
async def test_caller_input_errors_file_no_fault_on_the_dm_filing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 4, the DM path: with no observer on the runtime, the DM path's filer files nothing for a run's two
    marked errors."""
    runs = _watch_runs(monkeypatch)
    script = [_call("event_log_query", NO_FILTER, "a"), _call("event_log_query", NO_FILTER, "b"), _final("No filter.")]
    async with _rig(tmp_path, script) as rig:
        await _run_self_task(rig, "Read the relay log")
        events: list[tuple[Any, dict[str, Any]]] = []
        faults = FaultReportStore(emit_event=lambda kind, data: events.append((kind, data)))
        filed: dict[str, str] = {}
        await _file_pass_defect(
            runs[0]["outcome"], filed, runtime=SimpleNamespace(fault_report_store=faults),
            agent_id="forge-1", thread_id="", attempted="",
        )
        assert filed == {} and faults.list_open() == [] and events == []


# IE3
async def test_two_identical_genuine_tool_errors_still_file_a_fault_on_both_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 4's control: a failing reader makes event_log_query answer ``event_log_query_failed`` twice in a run.
    The observer path files one fault and emits FAULT_REPORTED once; the DM path's filer files one fault."""

    async def broken(self: Any, spec: Any) -> Any:
        raise RuntimeError("event store down")

    monkeypatch.setattr(EventLog, "query_governed", broken)
    runs = _watch_runs(monkeypatch)
    script = [
        _call("event_log_query", WINDOW, "a"), _call("event_log_query", WINDOW, "b"), _final("The log is down."),
        _call("event_log_query", WINDOW, "c"), _call("event_log_query", WINDOW, "d"), _final("The log is down."),
    ]
    async with _rig(tmp_path, script, section=SECTION) as rig:
        observed, events = _faults(rig)
        await _run_self_task(rig, "Read the relay log")
        [fault] = observed.list_open()
        assert (fault.tool_id, fault.error_text) == ("event_log_query", "event_log_query_failed")
        assert [kind for kind, _ in events] == [EventType.FAULT_REPORTED]
        rig.runtime.fault_report_store = None
        await _run_self_task(rig, "Read the relay log again")
        dm = FaultReportStore()
        await _file_pass_defect(
            runs[1]["outcome"], {}, runtime=SimpleNamespace(fault_report_store=dm),
            agent_id="forge-1", thread_id="", attempted="",
        )
        [dm_fault] = dm.list_open()
        assert dm_fault.tool_id == "event_log_query"


# IE4
@pytest.mark.parametrize(("tool_id", "error", "marked"), [
    ("event_log_query", "event_log_query_invalid:filter_required", True),
    ("mcp:docs:search", "mcp:docs:search_invalid:query", True),
    ("event_log_query", "event_log_query_invalid:", False),
    ("", "_invalid:window", False),
    ("event_log_query", "oracle_query_invalid:query", False),
    ("event_log_query", "Event_Log_Query_Invalid:window", False),
    ("event_log_query", "event_log_query_failed", False),
    ("publish_finding", "publish_finding_failed:write_failed", False),
    ("event_log_query", None, False),
    (None, "event_log_query_invalid:window", False),
])
def test_only_a_tools_own_mark_is_a_caller_input_error(tool_id: Any, error: Any, marked: bool) -> None:
    """The mark is the tool's own non-empty id, then ``_invalid:``, then at least one more character, case-sensitive;
    another tool's mark, an empty code and any non-str are not."""
    assert is_caller_input_error(tool_id, error) is marked


# IE5
def test_a_marked_error_is_neither_fault_nor_success_evidence_in_a_batch() -> None:
    """A marked error whose text the classifier does not call noise (``timeout``) is skipped by the batch, so the tool's
    one unmarked error is its defect and the tool is not reported as mixed."""
    calls = [ToolCallRequest(name="probe", arguments={}, id="c0"), ToolCallRequest(name="probe", arguments={}, id="c1")]
    results = [
        ToolCallResult(id="c0", output="probe_invalid:timeout", is_error=True),
        ToolCallResult(id="c1", output="probe_failed:timeout", is_error=True),
    ]
    batch = collect_tool_fault_batch(
        SimpleNamespace(tool_calls=calls, tool_results=results), classify_error=classify_tool_fault_error,
    )
    [evidence] = batch.tools
    assert evidence.defect is not None and evidence.defect.error_text == "probe_failed:timeout"
    assert evidence.mixed is False and evidence.succeeded is False
