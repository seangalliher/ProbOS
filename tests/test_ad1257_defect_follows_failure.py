"""AD-1257: defect detection follows the tool failure, not the step limit.

BF-793 is the case, and it is the repo's dominant defect shape — built, tested,
inert. ``detect_tool_defect`` (AD-1170) reads ``outcome.tool_calls`` and
``outcome.tool_results``. Its ONLY production caller passes a
``WorkItemAgenticOutcome``, which carries neither, because AD-1248 deliberately
kept the raw pairs out of the projection (AD-731: refs on the bus, bytes in the
store). So ``getattr(..., None) or []`` yielded ``[]``, the guard returned
``None``, and the detector returned ``None`` unconditionally — with both of its
gates wide open.

Measured before the fix::

    detect_tool_defect(<AgenticResult shape>)   -> ('web_search', 'HTTP 503', 2)
    detect_tool_defect(WorkItemAgenticOutcome)  -> None

Every AD-1170 test proved the function against an ``AgenticResult``-shaped fake.
None crossed the seam to the object production actually supplies. The headline
test below does exactly that, through the real arming site.

The fix is three moves: detect where the pairs live (the executor scope), carry
a BOUNDED value out (``ToolDefect``), and file where the turn lives (the
per-pass fold point) — on every pass, whatever the stop reason.
"""

from __future__ import annotations

import dataclasses
import inspect
from types import SimpleNamespace
from typing import Any, get_type_hints

import pytest

from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticExecutor,
    WorkItemAgenticOutcome,
    _tool_id_resolver,
)
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.continue_or_ask import resolve_exhausted_turn
from probos.cognitive.repair_verification import find_failing_arguments
from probos.config import DmAgenticConfig
from probos.crew_utils import CREW_EXECUTION_KEYS
from probos.dm_reply import ToolFailures
from probos.fault_report import (
    _ERROR_MAX,
    _SIGNATURE_RE,
    _TOOL_ID_MAX,
    FaultReportStore,
    ToolDefect,
    detect_tool_defect,
    error_signature,
    resolve_tool_defect,
)
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry

ERROR_TEXT = "unknown browser action: 'key_type'"
OTHER_ERROR = "Page.click: Timeout 30000ms exceeded."


# ── fakes ──────────────────────────────────────────────────────────


class _FakeReport:
    def __init__(self, fault_id: str) -> None:
        self.id = fault_id


class _RecordingFaultStore:
    """Records every ``file_fault`` call. Assertions live in the TESTS.

    ``file_fault_from_turn`` wraps its call in ``except Exception``, which
    swallows ``AssertionError`` — an assertion inside here would pass whatever
    happened.
    """

    def __init__(self, fault_id: str = "fault-1") -> None:
        self.records: list[dict[str, Any]] = []
        self._fault_id = fault_id

    async def file_fault(self, **kwargs: Any) -> _FakeReport:
        self.records.append(dict(kwargs))
        return _FakeReport(self._fault_id)


class _RaisingFaultStore:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def file_fault(self, **kwargs: Any) -> Any:
        self.records.append(dict(kwargs))
        raise RuntimeError("the fault store is on fire")


class _UnwiredFaultStore:
    """Present, but hands back nothing usable — the honest-degrade shape."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def file_fault(self, **kwargs: Any) -> None:
        self.records.append(dict(kwargs))
        return None


def _outcome(
    *,
    stopped_reason: str = "complete",
    defect: ToolDefect | None = None,
    final_text: str = "Here is what I managed, Captain.",
) -> WorkItemAgenticOutcome:
    return WorkItemAgenticOutcome(
        final_text=final_text,
        stopped_reason=stopped_reason,
        # Production shape: ``correlate_tool_outcomes`` always returns a
        # merge-OPEN value, and the dataclass default is merge-closed. A closed
        # double raises inside ``_accumulate_pass_failures`` on pass two, which
        # would silently skip the very hook these tests exist to exercise.
        tool_failures=ToolFailures(merge_open=True),
        tool_defect=defect,
        # AD-1269 / D6: production shape again. ``run()`` sets this wherever it
        # reads the pairs, and ``resolve_tool_defect`` now discriminates on it
        # rather than on whether the class happens to declare pair fields. A
        # fixture that omitted it would be testing the unmarked path.
        tool_defect_evaluated=True,
    )


class _ScriptedExecutor:
    """Stand-in for ``WorkItemAgenticExecutor`` — returns scripted outcomes."""

    script: list[WorkItemAgenticOutcome] = []
    runs: int = 0

    def __init__(self, *, llm_client: Any) -> None:
        self.llm_client = llm_client

    async def run(self, **_kwargs: Any) -> WorkItemAgenticOutcome:
        _ScriptedExecutor.runs += 1
        if len(_ScriptedExecutor.script) > 1:
            return _ScriptedExecutor.script.pop(0)
        return _ScriptedExecutor.script[0]


def _arm(monkeypatch, *outcomes: WorkItemAgenticOutcome) -> type[_ScriptedExecutor]:
    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor",
        _ScriptedExecutor,
    )
    _ScriptedExecutor.script = list(outcomes)
    _ScriptedExecutor.runs = 0
    return _ScriptedExecutor


def _agent(runtime: Any) -> Any:
    agent = SimpleNamespace(
        _runtime=runtime,
        _llm_client=object(),
        id="counselor-ezri",
        department="counseling",
        rank="lieutenant",
    )
    agent._conversational_agentic_will_run = (
        lambda obs: CognitiveAgent._conversational_agentic_will_run(agent, obs)
    )
    return agent


def _runtime(
    *, fault_store: Any = None, approval_store: Any = None, **cfg: Any,
) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(dm_agentic=DmAgenticConfig(enabled=True, **cfg)),
        fault_report_store=fault_store,
        action_approval_store=approval_store,
        capability_request_store=None,
    )


async def _standing_rule(tmp_path: Any, name: str = "aa.db") -> Any:
    """A live AD-1154 rule, so a turn REALLY runs a second pass.

    Without one, ``resolve_exhausted_turn`` breaks before re-invoking and every
    "across two passes" assertion below would hold on a single pass — which is
    the vacuous shape this whole AD exists to correct.
    """
    from probos.cognitive.continue_or_ask import (
        CONTINUE_ACTION,
        CONTINUE_SCOPE_KEY,
        CONTINUE_TOOL_ID,
    )
    from probos.tools.action_approvals import ActionApprovalStore

    store = ActionApprovalStore(db_path=str(tmp_path / name))
    await store.start()
    await store.issue_approval(
        "counselor-ezri",
        CONTINUE_TOOL_ID,
        CONTINUE_ACTION,
        scope_key=CONTINUE_SCOPE_KEY,
        ttl_seconds=3600,
    )
    return store


async def _turn(agent: Any, user_message: str = "type Hello into the doc") -> Any:
    return await CognitiveAgent._maybe_run_conversational_agentic(
        agent,
        {"intent": "direct_message", "params": {}},
        system_prompt="You are Ezri.",
        user_message=user_message,
    )


# ── the seam test — the one that would have caught this ────────────


@pytest.mark.asyncio
async def test_a_completed_turn_with_a_repeated_tool_failure_files_a_fault(
    monkeypatch,
) -> None:
    """completed turn -> outcome -> hook -> store, end to end.

    A narrower test passes on the broken wiring: ``detect_tool_defect`` works
    fine in isolation, which is exactly why five green tests hid a function that
    had never run. This one spans the whole chain and fails if the per-pass hook
    is removed.
    """
    store = _RecordingFaultStore()
    _arm(
        monkeypatch,
        _outcome(
            stopped_reason="complete",
            defect=ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2),
        ),
    )
    agent = _agent(_runtime(fault_store=store))

    text = await _turn(agent)

    assert text == "Here is what I managed, Captain."
    assert len(store.records) == 1
    assert store.records[0]["tool_id"] == "browser"
    assert store.records[0]["error_text"] == ERROR_TEXT
    assert store.records[0]["agent_id"] == "counselor-ezri"


# ── Section A — the carrier ────────────────────────────────────────


class _FailingTool:
    """Real Tool-protocol implementation that always answers the same way."""

    def __init__(self, tool_id: str = "browser", error: str = ERROR_TEXT) -> None:
        self._tid = tool_id
        self._error = error
        self.invocations = 0

    @property
    def tool_id(self) -> str:
        return self._tid

    @property
    def name(self) -> str:
        return self._tid

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return f"Fake tool {self._tid}"

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict:
        return {"type": "object"}

    async def invoke(self, params: dict, context: dict | None = None) -> ToolResult:
        self.invocations += 1
        return ToolResult(output="", error=self._error)


class _FakeLLMResponse:
    def __init__(self, content_blocks: list, content: str = "", tokens: int = 1) -> None:
        self.content_blocks = content_blocks
        self.content = content
        self.tokens_used = tokens


class _ScriptedLLM:
    def __init__(self, responses: list[_FakeLLMResponse]) -> None:
        self._responses = list(responses)

    async def complete(self, req: Any, **_kwargs: Any) -> _FakeLLMResponse:
        if self._responses:
            return self._responses.pop(0)
        return _FakeLLMResponse(content_blocks=[], content="done")


def _tool_use_response(tool_id: str) -> _FakeLLMResponse:
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

    block = ToolUseBlock(tool_call=ToolCallRequest(name=tool_id, arguments={}))
    return _FakeLLMResponse(content_blocks=[block], content="", tokens=1)


def _text_response(text: str) -> _FakeLLMResponse:
    return _FakeLLMResponse(content_blocks=[], content=text, tokens=1)


def _exec_runtime(registry: Any, perm_store: Any) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=True)),
        tool_registry=registry,
        tool_permission_store=perm_store,
        capability_gap_driver=None,
        intent_bus=None,
        attachment_store=None,
        emit_event=None,
    )


async def _run_executor(
    *, tool: Any, responses: list[_FakeLLMResponse], max_iterations: int = 5,
) -> WorkItemAgenticOutcome:
    registry = ToolRegistry()
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    executor = WorkItemAgenticExecutor(llm_client=_ScriptedLLM(responses))
    return await executor.run(
        agent_id="counselor-ezri",
        instructions="Test instructions.",
        task_text="type Hello into the doc",
        runtime=_exec_runtime(registry, perm_store),
        department="counseling",
        rank="ensign",
        max_iterations=max_iterations,
    )


@pytest.mark.asyncio
async def test_the_outcome_carries_the_defect_the_loop_saw() -> None:
    """The BF-701 shape, through the real ``run()``."""
    outcome = await _run_executor(
        tool=_FailingTool(),
        responses=[
            _tool_use_response("browser"),
            _tool_use_response("browser"),
            _text_response("I could not get it typed, Captain."),
        ],
    )

    assert outcome.tool_defect is not None
    assert outcome.tool_defect.tool_id == "browser"
    assert outcome.tool_defect.count == 2
    assert ERROR_TEXT in outcome.tool_defect.error_text


@pytest.mark.asyncio
async def test_a_completed_run_still_carries_the_defect() -> None:
    """The whole point of this AD: no stop-reason condition."""
    outcome = await _run_executor(
        tool=_FailingTool(),
        responses=[
            _tool_use_response("browser"),
            _tool_use_response("browser"),
            _text_response("Done what I could."),
        ],
    )

    assert outcome.stopped_reason == "complete"
    assert outcome.tool_defect is not None


@pytest.mark.asyncio
async def test_a_single_failure_leaves_the_outcome_clean() -> None:
    """Once is a transient. Retrying is the correct response to that."""
    outcome = await _run_executor(
        tool=_FailingTool(),
        responses=[_tool_use_response("browser"), _text_response("moving on")],
    )

    assert outcome.tool_defect is None


@pytest.mark.asyncio
async def test_malformed_results_do_not_fail_the_run(monkeypatch) -> None:
    """A hostile result cannot fail a dispatch — the detector swallows it."""
    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.detect_tool_defect",
        # ``**_kw`` because AD-1269 added ``resolve_tool_id`` at the call site.
        lambda result, **_kw: detect_tool_defect(SimpleNamespace(
            tool_calls=["not a call"], tool_results=[object(), None],
        )),
    )
    outcome = await _run_executor(
        tool=_FailingTool(),
        responses=[_tool_use_response("browser"), _text_response("fine")],
    )

    assert outcome.tool_defect is None
    assert outcome.final_text == "fine"


def test_the_carried_error_text_is_bounded() -> None:
    """The pre-review shape carried an unbounded str; measured at 1,000,000."""
    defect = ToolDefect(
        tool_id="b" * 4_000, error_text="x" * 10_000, count=2,
    )

    assert len(defect.error_text) <= _ERROR_MAX
    assert len(defect.tool_id) <= _TOOL_ID_MAX


def test_an_empty_defect_is_constructible_and_bounded() -> None:
    """Edge: the all-defaults value is still a valid, bounded value."""
    defect = ToolDefect()

    assert defect.tool_id == ""
    assert defect.error_text == ""
    assert defect.count == 0


def test_a_non_string_error_is_coerced_rather_than_carried() -> None:
    """Edge: ``ToolResult.output`` is ``Any``; the row it becomes is TEXT."""
    defect = ToolDefect(tool_id=None, error_text={"boom": 1}, count=2)  # type: ignore[arg-type]

    assert defect.tool_id == ""
    assert isinstance(defect.error_text, str)
    assert "boom" in defect.error_text


# ── Section B — filing ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_clean_outcome_files_nothing(monkeypatch) -> None:
    store = _RecordingFaultStore()
    _arm(monkeypatch, _outcome(stopped_reason="complete", defect=None))
    agent = _agent(_runtime(fault_store=store))

    await _turn(agent)

    assert store.records == []


@pytest.mark.asyncio
async def test_a_missing_fault_store_does_not_break_the_turn(monkeypatch) -> None:
    _arm(
        monkeypatch,
        _outcome(defect=ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2)),
    )
    agent = _agent(_runtime(fault_store=None))

    assert await _turn(agent) == "Here is what I managed, Captain."


@pytest.mark.asyncio
async def test_a_raising_fault_store_does_not_break_the_turn(monkeypatch) -> None:
    store = _RaisingFaultStore()
    _arm(
        monkeypatch,
        _outcome(defect=ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2)),
    )
    agent = _agent(_runtime(fault_store=store))

    assert await _turn(agent) == "Here is what I managed, Captain."
    assert len(store.records) == 1


# ── Section C — dedup ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_passes_of_one_turn_file_one_occurrence(
    monkeypatch, tmp_path,
) -> None:
    """``occurrences`` is quoted back to the Captain. It must not double-count."""
    store = _RecordingFaultStore()
    defect = ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2)
    executor = _arm(
        monkeypatch,
        _outcome(stopped_reason="max_iterations", defect=defect),
        _outcome(stopped_reason="max_iterations", defect=defect),
    )
    approvals = await _standing_rule(tmp_path)
    try:
        agent = _agent(
            _runtime(
                fault_store=store,
                approval_store=approvals,
                continue_or_ask_enabled=True,
                continue_or_ask_max_passes=2,
            )
        )

        await _turn(agent)
    finally:
        await approvals.stop()

    # Two REAL passes, one filing. Without the second pass this assertion is
    # vacuous, which is why the standing rule above is wired.
    assert executor.runs == 2
    assert len(store.records) == 1


@pytest.mark.asyncio
async def test_two_distinct_defects_in_one_turn_both_file(
    monkeypatch, tmp_path,
) -> None:
    store = _RecordingFaultStore()
    executor = _arm(
        monkeypatch,
        _outcome(
            stopped_reason="max_iterations",
            defect=ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2),
        ),
        _outcome(
            stopped_reason="complete",
            defect=ToolDefect(tool_id="browser", error_text=OTHER_ERROR, count=3),
        ),
    )
    approvals = await _standing_rule(tmp_path)
    try:
        agent = _agent(
            _runtime(
                fault_store=store,
                approval_store=approvals,
                continue_or_ask_enabled=True,
                continue_or_ask_max_passes=2,
            )
        )

        await _turn(agent)
    finally:
        await approvals.stop()

    assert executor.runs == 2
    assert len(store.records) == 2
    assert {r["error_text"] for r in store.records} == {ERROR_TEXT, OTHER_ERROR}


@pytest.mark.asyncio
async def test_an_unwired_store_is_not_retried_next_pass(
    monkeypatch, tmp_path,
) -> None:
    """An empty fault id is still recorded — one attempt per turn, not per pass."""
    store = _UnwiredFaultStore()
    defect = ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2)
    executor = _arm(
        monkeypatch,
        _outcome(stopped_reason="max_iterations", defect=defect),
        _outcome(stopped_reason="max_iterations", defect=defect),
    )
    approvals = await _standing_rule(tmp_path)
    try:
        agent = _agent(
            _runtime(
                fault_store=store,
                approval_store=approvals,
                continue_or_ask_enabled=True,
                continue_or_ask_max_passes=2,
            )
        )

        await _turn(agent)
    finally:
        await approvals.stop()

    assert executor.runs == 2
    assert len(store.records) == 1


@pytest.mark.asyncio
async def test_the_exhaustion_path_reuses_the_id_the_pass_filed() -> None:
    """The Captain still reads the same fault id; the store is not touched twice.

    This drives an ``AgenticResult``-shaped double, which HAS the raw pairs.
    Kept as-is because that is the crew path's real shape and it must stay
    green -- but it is NOT the shape production hands this function on the DM
    route, and on its own it pins nothing about that route.

    RESOLVED, and the history is why this note stays. As first built, the
    residual measured 2026-08-25 was::

        detect_tool_defect(WorkItemAgenticOutcome(tool_defect=<a real defect>))
        -> None   # branch taken: CUT_OFF (step limit), file_fault calls: 0

    -- the SAME BF-793 shape in the half the first pass did not reach: filing
    happened at the per-pass hook regardless, so no fault was lost, but the
    Captain-facing ``_DEFECT_*`` sentence on an exhausted turn was unreachable.
    ``resolve_tool_defect`` closed it by answering from whichever form the
    object can carry, with raw pairs authoritative when present INCLUDING when
    they say ``None`` (a superseded carried verdict would otherwise fabricate a
    fault claim). The DM shape is pinned by
    ``test_an_exhausted_dm_turn_reaches_the_captain_facing_defect_text`` and its
    dedup twin; without those, swapping the call site back would go unnoticed.
    """
    store = _RecordingFaultStore(fault_id="fault-second")
    outcome = SimpleNamespace(
        final_text="partway there",
        stopped_reason="max_iterations",
        tool_calls=[SimpleNamespace(id="c1", name="browser"),
                    SimpleNamespace(id="c2", name="browser")],
        tool_results=[
            SimpleNamespace(id="c1", output=ERROR_TEXT, is_error=True),
            SimpleNamespace(id="c2", output=ERROR_TEXT, is_error=True),
        ],
    )
    signature = error_signature(tool_id="browser", error_text=ERROR_TEXT)

    text = await resolve_exhausted_turn(
        outcome,
        reinvoke=_no_reinvoke,
        runtime=SimpleNamespace(fault_report_store=store),
        agent_id="counselor-ezri",
        base_task_text="type Hello",
        already_filed={signature: "fault-first"},
        config=SimpleNamespace(
            continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        ),
    )

    assert store.records == []
    assert "fault-first" in text
    assert "fault-second" not in text


@pytest.mark.asyncio
async def test_resolve_exhausted_turn_without_already_filed_is_unchanged() -> None:
    """Guards the 30+ existing call sites that never pass the new keyword."""
    store = _RecordingFaultStore(fault_id="fault-fresh")
    outcome = SimpleNamespace(
        final_text="partway there",
        stopped_reason="max_iterations",
        tool_calls=[SimpleNamespace(id="c1", name="browser"),
                    SimpleNamespace(id="c2", name="browser")],
        tool_results=[
            SimpleNamespace(id="c1", output=ERROR_TEXT, is_error=True),
            SimpleNamespace(id="c2", output=ERROR_TEXT, is_error=True),
        ],
    )

    text = await resolve_exhausted_turn(
        outcome,
        reinvoke=_no_reinvoke,
        runtime=SimpleNamespace(fault_report_store=store),
        agent_id="counselor-ezri",
        base_task_text="type Hello",
        config=SimpleNamespace(
            continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        ),
    )

    assert len(store.records) == 1
    assert "fault-fresh" in text


@pytest.mark.asyncio
async def test_an_empty_already_filed_mapping_files_as_normal() -> None:
    """Edge: supplied but empty is 'this turn filed nothing', not 'skip'."""
    store = _RecordingFaultStore(fault_id="fault-fresh")
    outcome = SimpleNamespace(
        final_text="",
        stopped_reason="max_iterations",
        tool_calls=[SimpleNamespace(id="c1", name="browser"),
                    SimpleNamespace(id="c2", name="browser")],
        tool_results=[
            SimpleNamespace(id="c1", output=ERROR_TEXT, is_error=True),
            SimpleNamespace(id="c2", output=ERROR_TEXT, is_error=True),
        ],
    )

    await resolve_exhausted_turn(
        outcome,
        reinvoke=_no_reinvoke,
        runtime=SimpleNamespace(fault_report_store=store),
        agent_id="counselor-ezri",
        base_task_text="type Hello",
        already_filed={},
        config=SimpleNamespace(
            continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        ),
    )

    assert len(store.records) == 1


async def _no_reinvoke(_task_text: str) -> Any:
    raise AssertionError("max_passes=1 must not re-invoke")


@pytest.mark.asyncio
async def test_a_later_turn_files_again_and_increments(monkeypatch) -> None:
    """Cross-turn coalescing is unchanged and belongs to the store."""
    store = FaultReportStore()
    defect = ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2)
    _arm(monkeypatch, _outcome(stopped_reason="complete", defect=defect))
    agent = _agent(_runtime(fault_store=store))

    await _turn(agent)
    await _turn(agent)

    open_faults = store.list_open()
    assert len(open_faults) == 1
    assert open_faults[0].occurrences == 2


# ── Section D — structural ─────────────────────────────────────────


def test_the_outcome_still_does_not_carry_raw_call_pairs() -> None:
    """AD-731: refs on the bus, bytes in the store. Pins boundary 1."""
    names = {f.name for f in dataclasses.fields(WorkItemAgenticOutcome)}

    assert "tool_calls" not in names
    assert "tool_results" not in names
    assert "tool_defect" in names


def test_the_crew_execution_record_shape_is_unchanged() -> None:
    assert "tool_defect" not in CREW_EXECUTION_KEYS


def test_the_detector_is_one_definition() -> None:
    """The re-export is a namespace alias, NOT a second definition."""
    from probos.cognitive import continue_or_ask
    from probos import fault_report

    assert continue_or_ask.detect_tool_defect is fault_report.detect_tool_defect
    assert continue_or_ask.ToolDefect is fault_report.ToolDefect
    assert (
        continue_or_ask._DEFECT_MIN_OCCURRENCES
        is fault_report._DEFECT_MIN_OCCURRENCES
    )

# ── Section E — the exhaustion consumer reads BOTH shapes ─────────
#
# Sections 1-4 left `resolve_exhausted_turn` calling `detect_tool_defect`,
# which joins raw call pairs. `current` on the DM path is a
# `WorkItemAgenticOutcome`, which now CARRIES a verdict but still has no
# pairs -- so the Captain-facing "the same call kept coming back the same
# way" message stayed dead for exactly the BF-793 reason this AD exists to
# fix. Measured before this section:
#
#     detect_tool_defect(WorkItemAgenticOutcome(tool_defect=<real>)) -> None
#     branch taken: CUT_OFF    file_fault calls: 0
#
# `resolve_tool_defect` answers from whichever form the object can carry.


def _pairs(count: int, tool: str = "browser", error: str = ERROR_TEXT) -> Any:
    """An object shaped like the loop output: it HAS the raw pairs."""
    from probos.cognitive.swe_harness.agentic_loop import AgenticResult
    from probos.cognitive.swe_harness.tool_call import (
        ToolCallRequest,
        ToolCallResult,
    )

    result = AgenticResult()
    result.stopped_reason = "max_iterations"
    result.tool_calls = [
        ToolCallRequest(id=f"c{i}", name=tool, arguments={})
        for i in range(count)
    ]
    result.tool_results = [
        ToolCallResult(id=f"c{i}", output=error, is_error=True)
        for i in range(count)
    ]
    return result


def test_the_carried_verdict_is_found_on_the_projection() -> None:
    """The assertion the bug fails: this is the object production supplies."""
    defect = detect_tool_defect(_pairs(2))
    assert defect is not None
    outcome = WorkItemAgenticOutcome(
        stopped_reason="max_iterations", tool_defect=defect,
        tool_defect_evaluated=True,
    )

    assert detect_tool_defect(outcome) is None      # why it was dead
    assert resolve_tool_defect(outcome) == defect   # why it is not


def test_raw_pairs_answer_even_when_they_say_no_defect() -> None:
    """Precedence, and the reason for it.

    A carried value a later pass has superseded must never override live
    evidence: the consumer files a fault report and quotes the tool to the
    Captain, so a stale verdict is a fabricated claim, not a stale cache.
    """
    stale = ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2)
    one_failure = _pairs(1)
    object.__setattr__(one_failure, "tool_defect", stale)

    assert detect_tool_defect(one_failure) is None
    assert resolve_tool_defect(one_failure) is None


def test_raw_pairs_win_over_a_disagreeing_carried_verdict() -> None:
    both = _pairs(2, tool="browser", error=ERROR_TEXT)
    object.__setattr__(
        both, "tool_defect",
        ToolDefect(tool_id="wrong_tool", error_text=OTHER_ERROR, count=99),
    )

    resolved = resolve_tool_defect(both)
    assert resolved is not None
    assert resolved.tool_id == "browser"
    assert resolved.error_text == ERROR_TEXT


def test_a_projection_carrying_nothing_resolves_to_nothing() -> None:
    assert resolve_tool_defect(
        WorkItemAgenticOutcome(
            stopped_reason="max_iterations", tool_defect_evaluated=True,
        )
    ) is None


@pytest.mark.parametrize(
    "carried",
    [
        ("browser", ERROR_TEXT, 2),                            # a bare tuple
        {"tool_id": "browser", "error_text": ERROR_TEXT},       # a mapping
        "browser",                                             # a string
        123,                                                   # a number
    ],
)
def test_only_a_bounded_tooldefect_is_trusted_from_the_carrier(carried) -> None:
    """Anything else is unbounded by construction and must not be quoted."""
    outcome = WorkItemAgenticOutcome(
        stopped_reason="max_iterations", tool_defect_evaluated=True,
    )
    object.__setattr__(outcome, "tool_defect", carried)

    assert resolve_tool_defect(outcome) is None


def test_the_carried_path_applies_the_same_threshold_as_the_joined_one() -> None:
    """A producer must not be able to lower the bar by construction."""
    outcome = WorkItemAgenticOutcome(
        stopped_reason="max_iterations",
        tool_defect=ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=1),
        tool_defect_evaluated=True,
    )
    assert resolve_tool_defect(outcome) is None


def test_resolution_never_raises_on_a_hostile_object() -> None:
    class _Hostile:
        @property
        def tool_defect(self):  # noqa: ANN202
            raise RuntimeError("boom")

    assert resolve_tool_defect(_Hostile()) is None
    assert resolve_tool_defect(None) is None


@pytest.mark.asyncio
async def test_an_exhausted_dm_turn_reaches_the_captain_facing_defect_text() -> None:
    """The half AD-1257 did not reach, closed.

    Every other test of this branch drives an ``AgenticResult``-shaped double,
    which HAS the raw pairs -- the exact test shape this AD condemns. Production
    hands `resolve_exhausted_turn` a `WorkItemAgenticOutcome`, which has none.
    So nothing pinned the call site, and swapping `resolve_tool_defect` back to
    `detect_tool_defect` would have gone unnoticed while the Captain-facing
    sentence went dead again.
    """
    store = _RecordingFaultStore(fault_id="fault-dm")
    defect = detect_tool_defect(_pairs(2))
    assert defect is not None
    outcome = WorkItemAgenticOutcome(
        final_text="partway there",
        stopped_reason="max_iterations",
        tool_defect=defect,
        tool_defect_evaluated=True,
    )

    text = await resolve_exhausted_turn(
        outcome,
        reinvoke=_no_reinvoke,
        runtime=SimpleNamespace(fault_report_store=store),
        agent_id="counselor-ezri",
        base_task_text="type Hello",
        config=SimpleNamespace(
            continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        ),
    )

    assert "browser" in text
    assert "fault-dm" in text
    assert len(store.records) == 1


@pytest.mark.asyncio
async def test_an_exhausted_dm_turn_reuses_a_fault_the_pass_hook_already_filed() -> None:
    """Dedup must survive the dual-source read, not just the joined one."""
    store = _RecordingFaultStore(fault_id="fault-second")
    defect = detect_tool_defect(_pairs(2))
    assert defect is not None
    signature = error_signature(
        tool_id=defect.tool_id, error_text=defect.error_text,
    )
    outcome = WorkItemAgenticOutcome(
        final_text="partway there",
        stopped_reason="max_iterations",
        tool_defect=defect,
        tool_defect_evaluated=True,
    )

    text = await resolve_exhausted_turn(
        outcome,
        reinvoke=_no_reinvoke,
        runtime=SimpleNamespace(fault_report_store=store),
        agent_id="counselor-ezri",
        base_task_text="type Hello",
        already_filed={signature: "fault-first"},
        config=SimpleNamespace(
            continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        ),
    )

    assert store.records == []
    assert "fault-first" in text
    assert "fault-second" not in text


def test_an_unbounded_look_alike_is_not_trusted_from_the_carrier() -> None:
    """The type bar is what bounds the value; duck typing is not.

    Mutation caught this: disabling the ``isinstance`` bar left the
    tuple/dict/str cases above still green, because those blow up on attribute
    access and the broad ``except`` swallows it -- the bar was never what
    rejected them. A namespace with the right attribute NAMES passes every
    field check (``count`` is an int, ``tool_id`` a non-empty str) and nothing
    truncated its error text: ``ToolDefect.__post_init__`` is the only thing
    that does. Without the bar this megabyte would be quoted to the Captain and
    written into a fault report.
    """
    look_alike = SimpleNamespace(
        tool_id="browser", error_text="x" * 1_000_000, count=2,
    )
    outcome = WorkItemAgenticOutcome(
        stopped_reason="max_iterations", tool_defect_evaluated=True,
    )
    object.__setattr__(outcome, "tool_defect", look_alike)

    assert resolve_tool_defect(outcome) is None


# ── Section F — repairs from adversarial review ───────────────────
#
# Four findings, each measured against the live code before the fix.


def test_a_defect_derives_its_signature_before_truncation() -> None:
    """One detector identity must not become two durable fault rows.

    `normalise_error` collapses digit and hex runs and THEN truncates, so
    cutting the raw text first and normalising later is a DIFFERENT identity:
    the collapse frees room that the raw cut had already spent.

    The shape matters. My first version of this test used two
    whitespace-equivalent errors and would have passed WITHOUT the fix --
    whitespace collapses to the same thing either way. A digit run does not.
    Verified by search, `logs/probe_finding4.py`::

        digit run collapses:  full equal True,  truncated equal False
        whitespace:           full equal True,  truncated equal True

    So the second assertion below is the load-bearing one: it pins that the
    naive recomputation genuinely differs, and therefore that deriving the
    signature at construction is what holds the two identities together.
    """
    tail = "Z" * 3000  # NOT hex, or it would collapse and mask the effect
    long_a = "err " + ("1" * 100) + " " + tail
    long_b = "err " + ("1" * 200) + " " + tail
    a = ToolDefect(tool_id="browser", error_text=long_a, count=2)
    b = ToolDefect(tool_id="browser", error_text=long_b, count=2)

    # One detected defect -> one signature.
    assert a.signature == b.signature
    assert a.signature == error_signature(tool_id="browser", error_text=long_a)

    # ... and recomputing from the TRUNCATED text is what used to split it.
    assert error_signature(
        tool_id="browser", error_text=a.error_text,
    ) != error_signature(
        tool_id="browser", error_text=b.error_text,
    )


def test_a_defect_signature_survives_truncation_of_the_error_text() -> None:
    huge = "boom " + ("z" * (_ERROR_MAX * 3))
    defect = ToolDefect(tool_id="browser", error_text=huge, count=2)

    assert len(defect.error_text) <= _ERROR_MAX
    assert defect.signature == error_signature(
        tool_id="browser", error_text=huge,
    )


def test_a_defect_count_cannot_break_captain_facing_formatting() -> None:
    """An arbitrary-precision int crashed `%d` formatting with ValueError."""
    defect = ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=10 ** 5000)

    assert defect.count <= 1_000_000
    assert "%d" % defect.count  # would have raised before the bound


@pytest.mark.parametrize("bad", [True, False, "2", 2.5, None])
def test_a_defect_count_that_is_not_an_int_becomes_zero(bad) -> None:
    """`bool` is an `int` subclass and is never an honest repeat count."""
    defect = ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=bad)

    assert defect.count == 0
    assert type(defect.count) is int


def test_a_negative_count_cannot_pass_the_threshold() -> None:
    assert ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=-5).count == 0


@pytest.mark.asyncio
async def test_the_pass_hook_applies_the_same_bar_as_the_resolver() -> None:
    """The hook wrote durable rows the exhaustion path would have refused.

    Measured before the fix, all three filed a row: count below the threshold,
    an empty tool_id, and a duck-typed 1 MB look-alike.
    """
    from probos.cognitive.cognitive_agent import _file_pass_defect

    for carried in (
        ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=1),
        ToolDefect(tool_id="", error_text=ERROR_TEXT, count=2),
        SimpleNamespace(
            tool_id="browser", error_text="x" * 1_000_000, count=2,
            signature="deadbeef",
        ),
    ):
        store = _RecordingFaultStore(fault_id="fault-x")
        outcome = WorkItemAgenticOutcome(
            stopped_reason="complete", tool_defect_evaluated=True,
        )
        object.__setattr__(outcome, "tool_defect", carried)
        filed: dict[str, str] = {}

        await _file_pass_defect(
            outcome,
            runtime=SimpleNamespace(fault_report_store=store),
            agent_id="counselor-ezri",
            thread_id="t1",
            attempted="type Hello",
            filed=filed,
        )

        assert store.records == [], f"{carried!r} should not have filed"
        assert filed == {}


@pytest.mark.asyncio
async def test_a_filed_fault_carries_the_runs_tool_trace_ref() -> None:
    """Without the ref the AD-1171/1172 repair path returns 'inconclusive'.

    `FaultReportStore.file_fault` has always accepted one; nothing passed it,
    so every row this path wrote stored None while the outcome was holding the
    ref the whole time.
    """
    from probos.cognitive.cognitive_agent import _file_pass_defect

    ref = "sha256:" + ("a" * 57)
    store = _RecordingFaultStore(fault_id="fault-ref")
    outcome = WorkItemAgenticOutcome(
        stopped_reason="complete",
        tool_trace_ref=ref,
        tool_defect=ToolDefect(
            tool_id="browser", error_text=ERROR_TEXT, count=2,
        ),
        tool_defect_evaluated=True,
    )

    await _file_pass_defect(
        outcome,
        runtime=SimpleNamespace(fault_report_store=store),
        agent_id="counselor-ezri",
        thread_id="t1",
        attempted="type Hello",
        filed={},
    )

    assert len(store.records) == 1
    assert store.records[0]["tool_trace_ref"] == ref


# ── Section G — AD-1269: what the row durably MEANS ────────────────
#
# Three findings, one question: where does a fault row's identity come from?
#
#   1. ``tool_id`` was the PROVIDER ALIAS, not a registered id. Five consumers
#      need the canonical id -- the Captain-facing repair rationale, the repair
#      approval's ``scope_key``, ``get_by_tool``, ``idx_faults_tool`` and the
#      ``FAULT_REPORTED`` payload -- and exactly one, AD-1173's argument
#      recovery, needs the observed name, because the trace records
#      ``ToolCallRequest.name``. So the row carries both.
#   2. The store RECOMPUTED the signature from the already-truncated text, so
#      one defect could split across two rows and neither reach the repair
#      threshold.
#   3. Coalescing discarded a trace ref the first occurrence had lacked.
#
# The table was measured empty on the live vessel before this shipped, so every
# one of these is still a free choice and there is nothing to migrate.

MCP_TOOL_ID = "mcp:docs:search"

# The three-thousand-character tail is NOT hex: ``normalise_error`` collapses
# hex runs to ``<id>``, which would erase the length difference these two
# strings exist to create.
_LONG_TAIL = "Z" * 3000
LONG_ERROR_A = "HTTPError " + ("1" * 100) + " backend schema " + _LONG_TAIL
LONG_ERROR_B = "HTTPError " + ("1" * 200) + " backend schema " + _LONG_TAIL


def _mcp_alias() -> str:
    from probos.cognitive.swe_harness.tool_call import llm_function_name

    return llm_function_name(MCP_TOOL_ID)


class _TraceCapturingStore:
    """Records the AD-1151 blob the executor persists, as bytes."""

    def __init__(self) -> None:
        self.blobs: list[bytes] = []

    async def write(
        self, *, content_hash: str, blob: bytes, mime: str = "",
        origin: str = "",
    ) -> str:
        self.blobs.append(blob)
        return content_hash

    def entries(self) -> list[dict[str, Any]]:
        import json

        return json.loads(self.blobs[-1].decode("utf-8"))


def _registry_with(*tool_ids: str) -> Any:
    registry = ToolRegistry()
    for tid in tool_ids:
        registry.register(_FailingTool(tool_id=tid), provider="test")
    return registry


# ── the AD-1269 seam test — alias in, canonical row out, args back ─


@pytest.mark.asyncio
async def test_an_mcp_fault_is_filed_against_the_canonical_id_and_recovers_args(
    monkeypatch, tmp_path,
) -> None:
    """The whole chain: alias observed -> canonical row -> trace -> arguments.

    A test that stops at the row proves half a chain, which is the shape that
    let AD-1170 rot for months. This one starts at a tool whose id the
    provider's name regex REJECTS, drives the real executor so the alias is
    genuinely what the model names, files through the real arming site into a
    real store, and then asks AD-1173's recovery to find the failing call in
    the real persisted trace -- which records the alias, not the id.
    """
    alias = _mcp_alias()
    assert alias != MCP_TOOL_ID, "the premise: this id needs an alias"

    registry = _registry_with(MCP_TOOL_ID)
    trace = _TraceCapturingStore()
    runtime = _exec_runtime(registry, ToolPermissionStore())
    runtime.attachment_store = trace

    executor = WorkItemAgenticExecutor(
        llm_client=_ScriptedLLM([
            _tool_use_response(alias),
            _tool_use_response(alias),
            _text_response("I could not search the docs, Captain."),
        ]),
    )
    outcome = await executor.run(
        agent_id="counselor-ezri",
        instructions="Test instructions.",
        task_text="search the docs",
        runtime=runtime,
        department="counseling",
        rank="ensign",
        max_iterations=5,
    )

    # 1. the outcome separates identity from provenance
    assert outcome.tool_defect is not None
    assert outcome.tool_defect.tool_id == MCP_TOOL_ID
    assert outcome.tool_defect.observed_as == alias

    # 2. the durable row keeps that separation, through the real store
    store = FaultReportStore(db_path=str(tmp_path / "faults.db"))
    await store.start()
    try:
        _arm(monkeypatch, _outcome(
            stopped_reason="complete", defect=outcome.tool_defect,
        ))
        await _turn(_agent(_runtime(fault_store=store)))
        rows = store.list_open()
    finally:
        await store.stop()

    assert len(rows) == 1
    row = rows[0]
    assert row.tool_id == MCP_TOOL_ID
    assert row.observed_as == alias
    # The point of the canonical id: the Captain can look this up, and a
    # repair approval keyed on it grants something.
    assert registry.get(row.tool_id) is not None

    # 3. and the trace -- which records the ALIAS -- still yields the arguments
    entries = trace.entries()
    assert {e.get("name") for e in entries} == {alias}
    args = find_failing_arguments(
        entries,
        tool_id=row.tool_id,
        signature=row.signature,
        observed_as=row.observed_as,
    )
    assert args == {}, "the failing call's arguments, recovered by alias"
    # Without the provenance the row would be unmatchable against its own trace.
    assert find_failing_arguments(
        entries, tool_id=row.tool_id, signature=row.signature,
    ) is None


# ── canonicalisation, and its three degradations ───────────────────


def test_a_plain_tool_id_is_unchanged_by_canonicalisation() -> None:
    """Blast radius: aliasing only bites ids the provider's regex rejects."""
    registry = _registry_with("browser")

    defect = detect_tool_defect(
        _pairs(2, tool="browser"),
        resolve_tool_id=_tool_id_resolver(registry),
    )

    assert defect is not None
    assert defect.tool_id == "browser"
    assert defect.observed_as == ""


def test_an_ambiguous_name_is_filed_verbatim_and_warned(caplog) -> None:
    """BF-757's rule, applied to filing: two claimants, so refuse to pick.

    Which of them the model was actually shown depends on the order they were
    offered in, and that order is not recoverable here. Naming the wrong one in
    a durable record is worse than naming the alias.
    """
    alias = _mcp_alias()
    registry = _registry_with(MCP_TOOL_ID, alias)

    with caplog.at_level("WARNING"):
        defect = detect_tool_defect(
            _pairs(2, tool=alias),
            resolve_tool_id=_tool_id_resolver(registry),
        )

    assert defect is not None
    assert defect.tool_id == alias
    assert defect.observed_as == ""
    assert any("ambiguous" in r.message or "claimed by" in r.message
               for r in caplog.records)


def test_an_unregistered_name_is_filed_verbatim() -> None:
    """Zero claimants: the model named something nobody owns. Still a fault."""
    registry = _registry_with("browser")

    defect = detect_tool_defect(
        _pairs(2, tool="ghost_tool"),
        resolve_tool_id=_tool_id_resolver(registry),
    )

    assert defect is not None
    assert defect.tool_id == "ghost_tool"
    assert defect.observed_as == ""


def test_the_detector_needs_no_resolver() -> None:
    """Foundation stays pure: the resolver is injected, never imported."""
    without = detect_tool_defect(_pairs(2, tool=MCP_TOOL_ID))

    assert without is not None
    assert without.tool_id == MCP_TOOL_ID
    assert without.observed_as == ""


@pytest.mark.parametrize(
    "resolver",
    [
        lambda name: (_ for _ in ()).throw(RuntimeError("registry on fire")),
        lambda name: None,
        lambda name: "",
        lambda name: 42,
    ],
)
def test_a_broken_resolver_degrades_to_the_observed_name(resolver) -> None:
    """Edge: a fault filed under the observed name is still a true record."""
    defect = detect_tool_defect(_pairs(2, tool="browser"), resolve_tool_id=resolver)

    assert defect is not None
    assert defect.tool_id == "browser"


def test_there_is_no_resolver_without_a_registry() -> None:
    """Edge: honest-degrade, byte-identical to the pre-AD-1269 detector."""
    assert _tool_id_resolver(None) is None
    assert _tool_id_resolver(SimpleNamespace()) is None


@pytest.mark.asyncio
async def test_the_row_tool_id_is_a_registered_tool_id() -> None:
    """Structural: every row this path files names something lookupable.

    This is what D1 buys. ``repair_dispatch`` puts ``brief.tool_id`` into both
    the sentence the Captain reads and the approval's ``scope_key``, so a row
    naming ``mcp_docs_search_38c53abe80026e47`` asks them to approve a repair to
    a tool they cannot find, under a grant that matches nothing.
    """
    registry = _registry_with("browser", MCP_TOOL_ID)
    resolver = _tool_id_resolver(registry)
    store = FaultReportStore()

    for observed in ("browser", _mcp_alias()):
        defect = detect_tool_defect(
            _pairs(2, tool=observed, error=f"boom from {observed}"),
            resolve_tool_id=resolver,
        )
        assert defect is not None
        await store.file_fault(
            tool_id=defect.tool_id,
            error_text=defect.error_text,
            defect=defect,
        )

    rows = store.list_open()
    assert len(rows) == 2
    for row in rows:
        assert registry.get(row.tool_id) is not None, row.tool_id


# ── D4 — the signature is computed once, at detection ──────────────


def test_two_long_errors_share_one_identity_but_not_a_truncated_one() -> None:
    """The premise the coalescing test below rests on, asserted directly."""
    assert error_signature(
        tool_id="browser", error_text=LONG_ERROR_A,
    ) == error_signature(tool_id="browser", error_text=LONG_ERROR_B)
    assert error_signature(
        tool_id="browser", error_text=LONG_ERROR_A[:_ERROR_MAX],
    ) != error_signature(tool_id="browser", error_text=LONG_ERROR_B[:_ERROR_MAX])


@pytest.mark.asyncio
async def test_a_long_digit_run_error_coalesces_across_turns(
    monkeypatch, tmp_path,
) -> None:
    """One fault, two turns, one row -- across a real close and reopen.

    ``normalise_error`` collapses digit runs and THEN truncates, so the collapse
    frees room the raw cut already spent. Before this, the store recomputed the
    signature from ``ToolDefect.error_text`` -- already truncated -- and the two
    turns below landed on two different rows with ``occurrences`` [1, 1].
    Neither reaches ``propose_after_occurrences``, so no repair is ever
    proposed for a fault that has now happened four times.
    """
    db = str(tmp_path / "faults.db")

    for error in (LONG_ERROR_A, LONG_ERROR_B):
        store = FaultReportStore(db_path=db)
        await store.start()
        try:
            _arm(monkeypatch, _outcome(
                stopped_reason="complete",
                defect=ToolDefect(
                    tool_id="browser", error_text=error, count=2,
                ),
            ))
            await _turn(_agent(_runtime(fault_store=store)))
        finally:
            await store.stop()

    reopened = FaultReportStore(db_path=db)
    await reopened.start()
    try:
        rows = reopened.list_open()
    finally:
        await reopened.stop()

    assert len(rows) == 1
    assert rows[0].occurrences == 2


@pytest.mark.asyncio
async def test_file_fault_without_a_signature_is_unchanged() -> None:
    """Guards the fourteen call sites that pass nothing."""
    store = FaultReportStore()

    report = await store.file_fault(tool_id="browser", error_text=ERROR_TEXT)

    assert report.signature == error_signature(
        tool_id="browser", error_text=ERROR_TEXT,
    )
    assert report.observed_as == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "nonsense",
        "a" * 63,
        "a" * 65,
        "A" * 64,                       # uppercase is not what we emit
        "z" * 64,                       # right length, not hex
        "a" * 64 + "\n",                # BF-757: ``$`` matches before a newline
        "",
    ],
)
async def test_file_fault_rejects_a_malformed_supplied_signature(bad) -> None:
    """A row keyed on a value we cannot reproduce can never coalesce.

    These seven cases used to be passed as a bare ``signature=`` string, which
    is the parameter review then measured filing one tool's occurrence onto
    another tool's row. Round 2 replaced that with a plant onto a constructed
    carrier -- ``object.__setattr__(carrier, "signature", bad)`` -- and pinned
    the store's shape check rejecting it.

    ``signature`` is now a derived read-only property, so the PLANT is what
    fails, which is strictly stronger: a shape check can only reject a bad
    value after something has built one, and there is now no way to build one.
    Both original assertions are kept below on the same carrier and the same
    seven values; only the step that used to succeed has become a raise.
    """
    store = FaultReportStore()
    carrier = ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2)

    with pytest.raises(AttributeError):
        object.__setattr__(carrier, "signature", bad)

    report = await store.file_fault(
        tool_id="browser", error_text=ERROR_TEXT, defect=carrier,
    )

    assert report.signature == error_signature(
        tool_id="browser", error_text=ERROR_TEXT,
    )


@pytest.mark.asyncio
async def test_file_fault_rejects_an_untyped_identity_carrier() -> None:
    """The type bar is what makes the identity checkable; duck typing is not.

    A look-alike carries a well-formed digest it did not derive, which is the
    whole hazard: the store cannot tell whether that digest belongs to the tool
    named beside it.
    """
    store = FaultReportStore()
    look_alike = SimpleNamespace(
        tool_id="run_python",
        error_text=ERROR_TEXT,
        signature=error_signature(tool_id="browser", error_text=ERROR_TEXT),
        observed_as="",
    )

    report = await store.file_fault(
        tool_id="run_python", error_text=ERROR_TEXT, defect=look_alike,
    )

    assert report.tool_id == "run_python"
    assert report.signature == error_signature(
        tool_id="run_python", error_text=ERROR_TEXT,
    )


@pytest.mark.asyncio
async def test_two_tools_cannot_share_a_row_through_a_borrowed_digest() -> None:
    """F3, executed: the defect the bare-string parameter admitted.

    Review supplied ``"0" * 64`` for ``browser`` and then for ``run_python``
    and got ONE durable browser row at ``occurrences == 2`` and no row for
    ``run_python`` at all -- a well-formed digest that belonged to neither.
    The identity now arrives on a typed carrier that derives its own, so the
    two tools cannot collide however the caller is written.
    """
    store = FaultReportStore()

    for tool in ("browser", "run_python"):
        defect = ToolDefect(tool_id=tool, error_text=ERROR_TEXT, count=2)
        await store.file_fault(
            tool_id=tool, error_text=ERROR_TEXT, defect=defect,
        )

    rows = store.list_open()
    assert {r.tool_id for r in rows} == {"browser", "run_python"}
    assert [r.occurrences for r in rows] == [1, 1]


@pytest.mark.asyncio
async def test_a_carrier_cannot_borrow_another_tools_valid_digest(
    tmp_path,
) -> None:
    """R1, executed: a VALID digest for the WRONG tool, on a reopened row.

    The round-2 gate checked ``isinstance`` and 64-hex shape and never asked
    whose digest it was. Planting ``browser``'s real signature onto a carrier
    naming ``run_python`` permanently incremented the BROWSER row and gave
    ``run_python`` no row at all -- measured against a reopened SQLite store as
    ``[('browser', 'df36654b938d', 2)]``.

    ``signature`` is now derived from the carrier's own ``tool_id`` on every
    read, so the plant raises and the borrowed digest cannot exist to be
    checked.
    """
    db = str(tmp_path / "faults.db")
    borrowed = ToolDefect(
        tool_id="browser", error_text=ERROR_TEXT, count=2,
    ).signature

    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        await store.file_fault(
            tool_id="browser", error_text=ERROR_TEXT,
            defect=ToolDefect(
                tool_id="browser", error_text=ERROR_TEXT, count=2,
            ),
        )
        impostor = ToolDefect(
            tool_id="run_python", error_text=ERROR_TEXT, count=2,
        )
        with pytest.raises(AttributeError):
            object.__setattr__(impostor, "signature", borrowed)
        assert _SIGNATURE_RE.fullmatch(borrowed), "the premise: a VALID digest"
        assert impostor.signature != borrowed
        await store.file_fault(
            tool_id="run_python", error_text=ERROR_TEXT, defect=impostor,
        )
    finally:
        await store.stop()

    rows = await _reopen_rows(db)

    assert {(r.tool_id, r.occurrences) for r in rows} == {
        ("browser", 1), ("run_python", 1),
    }
    assert {r.signature for r in rows} == {
        error_signature(tool_id="browser", error_text=ERROR_TEXT),
        error_signature(tool_id="run_python", error_text=ERROR_TEXT),
    }


def test_file_fault_takes_no_bare_identity_arguments() -> None:
    """F3, structurally: a digest with no owner cannot be handed in at all.

    Removing the parameter is what makes a well-formed digest for the wrong
    tool unconstructible; a validity check would only have made it unlikely,
    and ``"0" * 64`` passed every check the round-1 build had.
    """
    params = inspect.signature(FaultReportStore.file_fault).parameters

    assert "defect" in params
    assert "signature" not in params
    assert "observed_as" not in params


def test_the_typed_carrier_is_typed_on_both_filing_apis() -> None:
    """R3: the annotation is what makes the carrier checkable at all.

    ``file_fault`` declared ``ToolDefect | None`` while the wrapper every DM
    turn actually calls, ``file_fault_from_turn``, still declared ``Any`` --
    measured with ``typing.get_type_hints``. A bare ``Any`` on the outer API
    means nothing upstream of the store is told what it may hand in.
    """
    from probos.cognitive.continue_or_ask import file_fault_from_turn

    expected = ToolDefect | None

    assert get_type_hints(FaultReportStore.file_fault)["defect"] == expected
    assert get_type_hints(file_fault_from_turn)["defect"] == expected


@pytest.mark.asyncio
async def test_file_fault_honours_a_well_formed_supplied_signature() -> None:
    """The carrier's own signature, over the UNTRUNCATED text, keys the row."""
    carrier = ToolDefect(tool_id="browser", error_text=LONG_ERROR_A, count=2)
    supplied = error_signature(tool_id="browser", error_text=LONG_ERROR_A)
    assert carrier.signature == supplied
    store = FaultReportStore()

    report = await store.file_fault(
        tool_id="browser",
        error_text=LONG_ERROR_A[:_ERROR_MAX],
        defect=carrier,
    )

    assert report.signature == supplied


# ── D5 — coalescing upgrades a missing trace ref, never overwrites ─


@pytest.mark.asyncio
async def test_coalescing_adopts_a_trace_ref_the_first_occurrence_lacked(
    tmp_path,
) -> None:
    """Provenance may go absent -> present. Proven across a reopen."""
    db = str(tmp_path / "faults.db")
    ref = "sha256:" + ("b" * 57)

    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        await store.file_fault(tool_id="browser", error_text=ERROR_TEXT)
        second = await store.file_fault(
            tool_id="browser", error_text=ERROR_TEXT, tool_trace_ref=ref,
        )
        assert second.occurrences == 2
    finally:
        await store.stop()

    reopened = FaultReportStore(db_path=db)
    await reopened.start()
    try:
        rows = reopened.list_open()
    finally:
        await reopened.stop()

    assert len(rows) == 1
    assert rows[0].tool_trace_ref == ref


@pytest.mark.asyncio
async def test_coalescing_never_overwrites_an_existing_trace_ref(
    tmp_path,
) -> None:
    """... and never the reverse. A proven trace is not traded for a newer one."""
    db = str(tmp_path / "faults.db")
    first_ref = "sha256:" + ("c" * 57)

    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        await store.file_fault(
            tool_id="browser", error_text=ERROR_TEXT, tool_trace_ref=first_ref,
        )
        await store.file_fault(
            tool_id="browser", error_text=ERROR_TEXT,
            tool_trace_ref="sha256:" + ("d" * 57),
        )
        await store.file_fault(tool_id="browser", error_text=ERROR_TEXT)
    finally:
        await store.stop()

    reopened = FaultReportStore(db_path=db)
    await reopened.start()
    try:
        rows = reopened.list_open()
    finally:
        await reopened.stop()

    assert rows[0].tool_trace_ref == first_ref
    assert rows[0].occurrences == 3


# ── D3 — the migration, against a database that already exists ─────


_PRE_AD1269_SCHEMA = """
CREATE TABLE IF NOT EXISTS fault_reports (
    id TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    error_text TEXT NOT NULL DEFAULT '',
    attempted TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    thread_id TEXT NOT NULL DEFAULT '',
    work_item_id TEXT,
    tool_trace_ref TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    occurrences INTEGER NOT NULL DEFAULT 1,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    resolved_at REAL,
    resolution TEXT NOT NULL DEFAULT ''
);
"""


def _write_pre_ad1269_db(path: str, *, signature: str) -> None:
    """A database at the fifteen-column schema, with a row already in it."""
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        conn.executescript(_PRE_AD1269_SCHEMA)
        conn.execute(
            "INSERT INTO fault_reports (id, signature, tool_id, error_text, "
            "attempted, agent_id, thread_id, work_item_id, tool_trace_ref, "
            "status, occurrences, first_seen_at, last_seen_at, resolved_at, "
            "resolution) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "old1", signature, "browser", ERROR_TEXT, "type Hello",
                "counselor-ezri", "t1", None, None, "open", 1,
                1000.0, 1000.0, None, "",
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_an_existing_db_migrates_to_the_new_column(tmp_path) -> None:
    """``CREATE TABLE IF NOT EXISTS`` is a no-op, so this needs an ALTER.

    The live vessel's ``fault_reports.db`` already exists at the fifteen-column
    schema. Without the guarded migration, ``_load_cache``'s SELECT fails with
    ``no such column: observed_as`` on the next boot -- and because that failure
    is inside ``start()``, the store comes up with an EMPTY cache and every
    recurring fault files a fresh row.
    """
    db = str(tmp_path / "legacy.db")
    signature = error_signature(tool_id="browser", error_text=ERROR_TEXT)
    _write_pre_ad1269_db(db, signature=signature)

    store = FaultReportStore(db_path=db)
    await store.start()          # would raise ``no such column`` without it
    try:
        rows = store.list_open()
    finally:
        await store.stop()

    assert len(rows) == 1
    assert rows[0].id == "old1"
    assert rows[0].observed_as == ""


@pytest.mark.asyncio
async def test_migration_is_idempotent_across_restarts(tmp_path) -> None:
    """Restarting must not try to add a column that is already there."""
    import sqlite3

    db = str(tmp_path / "legacy.db")
    _write_pre_ad1269_db(
        db, signature=error_signature(tool_id="browser", error_text=ERROR_TEXT),
    )

    for _ in range(3):
        store = FaultReportStore(db_path=db)
        await store.start()
        await store.stop()

    conn = sqlite3.connect(db)
    try:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(fault_reports)")]
    finally:
        conn.close()

    assert columns.count("observed_as") == 1
    assert len(columns) == 16


@pytest.mark.asyncio
async def test_a_fresh_db_needs_no_migration(tmp_path) -> None:
    """Edge: the CREATE already names the column, so the guard short-circuits."""
    import sqlite3

    db = str(tmp_path / "fresh.db")
    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        await store.file_fault(
            tool_id=MCP_TOOL_ID,
            error_text=ERROR_TEXT,
            defect=ToolDefect(
                tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, count=2,
                observed_as=_mcp_alias(),
            ),
        )
    finally:
        await store.stop()

    reopened = FaultReportStore(db_path=db)
    await reopened.start()
    try:
        rows = reopened.list_open()
    finally:
        await reopened.stop()

    conn = sqlite3.connect(db)
    try:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(fault_reports)")]
    finally:
        conn.close()

    assert columns[-1] == "observed_as"
    assert rows[0].observed_as == _mcp_alias()


# ── D6 — the discriminator is provenance, not shape ────────────────


def test_an_empty_pair_projection_with_a_marked_verdict_uses_it() -> None:
    """The BF-793 recurrence guard.

    ``hasattr(outcome, "tool_calls")`` asks what CLASS this is. Add
    empty-default pair fields to the projection -- which is exactly what AD-1248
    nearly did -- and the old rule sends a real verdict down the join path,
    where it finds two empty lists and answers None. The whole bug, recreated by
    a field being added. Provenance does not have that failure mode.
    """
    defect = ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2)
    projection = SimpleNamespace(
        tool_calls=[], tool_results=[],
        tool_defect=defect, tool_defect_evaluated=True,
    )

    assert detect_tool_defect(projection) is None
    assert resolve_tool_defect(projection) == defect


def test_real_pairs_beat_a_stale_carried_verdict() -> None:
    """The fabrication guard, kept.

    The consumer files a fault report and quotes the tool to the Captain, so a
    verdict a later pass superseded is a fabricated claim, not a stale cache.
    Marked or not, populated pairs are the live evidence and they answer.
    """
    live = _pairs(2, tool="browser", error=ERROR_TEXT)
    object.__setattr__(live, "tool_defect", ToolDefect(
        tool_id="wrong_tool", error_text=OTHER_ERROR, count=99,
    ))
    object.__setattr__(live, "tool_defect_evaluated", True)

    resolved = resolve_tool_defect(live)

    assert resolved is not None
    assert resolved.tool_id == "browser"


def test_an_unmarked_carried_verdict_is_not_evidence() -> None:
    """Edge: an unmarked field is indistinguishable from its default."""
    unmarked = SimpleNamespace(
        tool_defect=ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2),
    )

    assert resolve_tool_defect(unmarked) is None


@pytest.mark.parametrize("marker", [1, "true", "yes", [1]])
def test_a_truthy_non_bool_marker_does_not_arm_the_carried_path(marker) -> None:
    """``is True``, following ``is_continue_or_ask_armed``: a value that
    reached here by a route that skipped the dataclass must not arm it."""
    unmarked = SimpleNamespace(
        tool_defect=ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2),
        tool_defect_evaluated=marker,
    )

    assert resolve_tool_defect(unmarked) is None


def test_the_outcome_marks_where_the_pairs_were_read() -> None:
    """Structural: the marker exists, defaults off, and is appended last."""
    names = [f.name for f in dataclasses.fields(WorkItemAgenticOutcome)]

    assert names[-1] == "tool_defect_evaluated"
    assert WorkItemAgenticOutcome().tool_defect_evaluated is False
    assert "tool_defect_evaluated" not in CREW_EXECUTION_KEYS


@pytest.mark.asyncio
async def test_a_real_run_marks_the_outcome_even_with_no_defect() -> None:
    """"Evaluated, and the answer is no" must be distinguishable from silence."""
    outcome = await _run_executor(
        tool=_FailingTool(),
        responses=[_tool_use_response("browser"), _text_response("moving on")],
    )

    assert outcome.tool_defect is None
    assert outcome.tool_defect_evaluated is True


# ── C11 — the trace reader learns about the alias ──────────────────


def _trace_entry(name: str, error: str, args: dict) -> dict[str, Any]:
    return {
        "id": "c1", "name": name, "arguments": args,
        "output": error, "is_error": True,
    }


def test_find_failing_arguments_matches_the_observed_name() -> None:
    signature = error_signature(tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT)
    entries = [_trace_entry(_mcp_alias(), ERROR_TEXT, {"q": "probos"})]

    assert find_failing_arguments(
        entries, tool_id=MCP_TOOL_ID, signature=signature,
        observed_as=_mcp_alias(),
    ) == {"q": "probos"}


def test_find_failing_arguments_falls_back_to_the_tool_id() -> None:
    """Empty ``observed_as`` is the ordinary case and must be a no-op."""
    signature = error_signature(tool_id="browser", error_text=ERROR_TEXT)
    entries = [_trace_entry("browser", ERROR_TEXT, {"action": "key_type"})]

    assert find_failing_arguments(
        entries, tool_id="browser", signature=signature,
    ) == {"action": "key_type"}
    assert find_failing_arguments(
        entries, tool_id="browser", signature=signature, observed_as="",
    ) == {"action": "key_type"}


def test_find_failing_arguments_still_refuses_a_mismatched_name() -> None:
    """Edge: provenance widens WHICH name matches, never how many do."""
    signature = error_signature(tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT)
    entries = [_trace_entry("some_other_tool", ERROR_TEXT, {"q": "probos"})]

    assert find_failing_arguments(
        entries, tool_id=MCP_TOOL_ID, signature=signature,
        observed_as=_mcp_alias(),
    ) is None


# ── Section H — adversarial review, round 2 ────────────────────────
#
# Three findings, all reached by EXECUTION against the round-1 build.
#
#   F1. Coalescing adopted a later occurrence's trace ref but kept the
#       earlier occurrence's observed name, so the row held one occurrence's
#       trace and another's provenance and could not read its own evidence.
#   F2. Canonicalisation ran on the WINNER, after the tally, so one tool
#       invoked under two names failed twice and was counted once each.
#   F3. The identity arrived as a bare 64-hex string, which is a shape check
#       and not an identity check: a well-formed digest for the wrong tool
#       filed one tool's occurrence onto another tool's row.


async def _reopen_rows(db: str) -> list[Any]:
    """Every open row, read back through a fresh store. Proves persistence."""
    reopened = FaultReportStore(db_path=db)
    await reopened.start()
    try:
        return reopened.list_open()
    finally:
        await reopened.stop()


# ── F1 — a trace and the name that reads it move together ──────────


@pytest.mark.asyncio
async def test_an_adopted_trace_brings_its_observed_name_with_it(tmp_path) -> None:
    """canonical -> alias, executed. The round-1 row could not read its trace.

    Both occurrences are the same fault -- ``observed_as`` is provenance and is
    not signature material -- so they coalesce. Occurrence 1 saw the tool under
    its own id and had no trace; occurrence 2 saw it under the provider alias
    and HAS one. Round 1 adopted the ref and left the name, so
    ``find_failing_arguments`` scanned an alias-named trace for the canonical
    id and returned None.
    """
    db = str(tmp_path / "faults.db")
    alias = _mcp_alias()
    ref = "sha256:" + ("e" * 57)
    first = ToolDefect(tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, count=2)
    second = ToolDefect(
        tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, count=2, observed_as=alias,
    )
    assert first.signature == second.signature, "the premise: these coalesce"

    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        await store.file_fault(
            tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, defect=first,
        )
        await store.file_fault(
            tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, defect=second,
            tool_trace_ref=ref,
        )
    finally:
        await store.stop()

    rows = await _reopen_rows(db)

    assert len(rows) == 1
    row = rows[0]
    assert row.occurrences == 2
    assert row.tool_trace_ref == ref
    assert row.observed_as == alias
    # ... and the trace that ref points at names the ALIAS, which is the whole
    # reason the name had to move with it.
    assert find_failing_arguments(
        [_trace_entry(alias, ERROR_TEXT, {"q": "probos"})],
        tool_id=row.tool_id, signature=row.signature,
        observed_as=row.observed_as,
    ) == {"q": "probos"}


@pytest.mark.asyncio
async def test_an_adopted_trace_clears_a_stale_observed_name(tmp_path) -> None:
    """alias -> canonical, executed. The empty case is the one that regressed.

    "Only upgrade when the new value is non-empty" reads as the safe rule and
    is wrong here: an occurrence that saw the tool under its OWN id records
    that id in its trace, so keeping the earlier alias makes the adopted trace
    unreadable in exactly the same way, in the other direction.
    """
    db = str(tmp_path / "faults.db")
    alias = _mcp_alias()
    ref = "sha256:" + ("f" * 57)
    first = ToolDefect(
        tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, count=2, observed_as=alias,
    )
    second = ToolDefect(tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, count=2)

    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        await store.file_fault(
            tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, defect=first,
        )
        await store.file_fault(
            tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, defect=second,
            tool_trace_ref=ref,
        )
    finally:
        await store.stop()

    rows = await _reopen_rows(db)

    assert len(rows) == 1
    row = rows[0]
    assert row.tool_trace_ref == ref
    assert row.observed_as == ""
    assert find_failing_arguments(
        [_trace_entry(MCP_TOOL_ID, ERROR_TEXT, {"q": "probos"})],
        tool_id=row.tool_id, signature=row.signature,
        observed_as=row.observed_as,
    ) == {"q": "probos"}


@pytest.mark.asyncio
async def test_a_rejected_trace_leaves_the_observed_name_alone(tmp_path) -> None:
    """The converse: the name moves WITH a trace, never on its own.

    A row that already has a proven trace keeps it, so the provenance that
    reads it must stay too -- otherwise the second occurrence's name would be
    written over a trace it never described.
    """
    db = str(tmp_path / "faults.db")
    alias = _mcp_alias()
    kept = "sha256:" + ("1" * 57)

    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        await store.file_fault(
            tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, tool_trace_ref=kept,
            defect=ToolDefect(
                tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, count=2,
                observed_as=alias,
            ),
        )
        await store.file_fault(
            tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT,
            tool_trace_ref="sha256:" + ("2" * 57),
            defect=ToolDefect(
                tool_id=MCP_TOOL_ID, error_text=ERROR_TEXT, count=2,
            ),
        )
    finally:
        await store.stop()

    rows = await _reopen_rows(db)

    assert rows[0].tool_trace_ref == kept
    assert rows[0].observed_as == alias


# ── F2 — canonicalisation runs before the tally, not after ─────────


def _mixed_pairs(names: list[str], errors: dict[str, str] | None = None) -> Any:
    """Loop output where each call may name a DIFFERENT tool."""
    from probos.cognitive.swe_harness.agentic_loop import AgenticResult
    from probos.cognitive.swe_harness.tool_call import (
        ToolCallRequest,
        ToolCallResult,
    )

    by_name = errors or {}
    result = AgenticResult()
    result.stopped_reason = "max_iterations"
    result.tool_calls = [
        ToolCallRequest(id=f"c{i}", name=name, arguments={})
        for i, name in enumerate(names)
    ]
    result.tool_results = [
        ToolCallResult(
            id=f"c{i}", output=by_name.get(name, ERROR_TEXT), is_error=True,
        )
        for i, name in enumerate(names)
    ]
    return result


def test_one_canonical_tool_failing_under_two_names_is_one_defect() -> None:
    """F2, executed. Round 1 tallied observed names and answered None here.

    ``mcp:docs:search`` invoked once as its alias and once as itself is the
    same registered tool failing the same way twice -- which is precisely the
    threshold. Round 1 counted 1 and 1 and returned None, while both same-name
    controls below returned a count of 2.
    """
    alias = _mcp_alias()
    resolver = _tool_id_resolver(_registry_with(MCP_TOOL_ID))

    defect = detect_tool_defect(
        _mixed_pairs([alias, MCP_TOOL_ID]), resolve_tool_id=resolver,
    )

    assert defect is not None
    assert defect.tool_id == MCP_TOOL_ID
    assert defect.count == 2
    # One observed name is retained for trace matching: the group's first,
    # so the value is deterministic rather than dependent on dict ordering.
    assert defect.observed_as == alias

    for control in ([alias, alias], [MCP_TOOL_ID, MCP_TOOL_ID]):
        same_name = detect_tool_defect(
            _mixed_pairs(control), resolve_tool_id=resolver,
        )
        assert same_name is not None, control
        assert same_name.count == 2, control
        assert same_name.tool_id == MCP_TOOL_ID, control


def test_the_retained_observed_name_is_empty_when_the_group_starts_canonical() -> None:
    """Edge: the other order. The retained name still names something traced."""
    alias = _mcp_alias()
    resolver = _tool_id_resolver(_registry_with(MCP_TOOL_ID))

    defect = detect_tool_defect(
        _mixed_pairs([MCP_TOOL_ID, alias]), resolve_tool_id=resolver,
    )

    assert defect is not None
    assert defect.count == 2
    assert defect.observed_as == ""


def test_an_alias_split_cannot_hand_the_win_to_a_lesser_defect() -> None:
    """The second half of F2: a split loses a contest it should have won.

    ``browser`` fails three times; the MCP tool fails four, split two and two
    across its alias and its own id. Tallying observed names sees 3 / 2 / 2 and
    files against ``browser``; grouping first sees 4 / 3 and files against the
    tool that actually failed most.
    """
    alias = _mcp_alias()
    resolver = _tool_id_resolver(_registry_with(MCP_TOOL_ID, "browser"))

    defect = detect_tool_defect(
        _mixed_pairs(
            ["browser"] * 3 + [alias] * 2 + [MCP_TOOL_ID] * 2,
            errors={"browser": OTHER_ERROR},
        ),
        resolve_tool_id=resolver,
    )

    assert defect is not None
    assert defect.tool_id == MCP_TOOL_ID
    assert defect.count == 4
    assert defect.error_text == ERROR_TEXT


def test_a_distinct_name_is_resolved_once_per_call() -> None:
    """The tally now asks per name rather than once, so it must not ask twice."""
    asked: list[str] = []

    def _resolver(name: str) -> str:
        asked.append(name)
        return name

    detect_tool_defect(
        _mixed_pairs(["browser"] * 3 + ["run_python"] * 2),
        resolve_tool_id=_resolver,
    )

    assert sorted(asked) == ["browser", "run_python"]


def test_two_genuinely_different_tools_still_tally_apart() -> None:
    """Grouping must merge aliases of ONE tool, never two distinct tools."""
    resolver = _tool_id_resolver(_registry_with("browser", "run_python"))

    defect = detect_tool_defect(
        _mixed_pairs(["browser", "run_python"]), resolve_tool_id=resolver,
    )

    assert defect is None


# ── F4 — the exhaustion path, asserted on the PERSISTED row ────────


@pytest.mark.asyncio
async def test_the_exhaustion_path_files_the_identity_the_detector_derived(
    tmp_path,
) -> None:
    """F4: the direct exhaustion test asserted only that ONE call happened.

    Dropping the identity from that call site would not have reddened it. This
    one drives the same branch into a REAL store and reads the row back, so a
    long error's signature and an alias both have to survive the whole way --
    through ``resolve_exhausted_turn``, ``file_fault_from_turn``, the store,
    and a close and reopen.
    """
    alias = _mcp_alias()
    db = str(tmp_path / "faults.db")
    defect = ToolDefect(
        tool_id=MCP_TOOL_ID, error_text=LONG_ERROR_A, count=2,
        observed_as=alias,
    )

    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        text = await resolve_exhausted_turn(
            WorkItemAgenticOutcome(
                final_text="partway there",
                stopped_reason="max_iterations",
                tool_defect=defect,
                tool_defect_evaluated=True,
            ),
            reinvoke=_no_reinvoke,
            runtime=SimpleNamespace(fault_report_store=store),
            agent_id="counselor-ezri",
            base_task_text="search the docs",
            config=SimpleNamespace(
                continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
            ),
        )
    finally:
        await store.stop()

    rows = await _reopen_rows(db)

    assert MCP_TOOL_ID in text
    assert len(rows) == 1
    row = rows[0]
    assert row.tool_id == MCP_TOOL_ID
    assert row.observed_as == alias
    # The identity the DETECTOR derived, over the UNTRUNCATED text -- not the
    # store's recompute over ``error_text``, which is cut at ``_ERROR_MAX``.
    assert row.signature == error_signature(
        tool_id=MCP_TOOL_ID, error_text=LONG_ERROR_A,
    )
    assert row.signature != error_signature(
        tool_id=MCP_TOOL_ID, error_text=LONG_ERROR_A[:_ERROR_MAX],
    )



@pytest.mark.asyncio
async def test_a_subclass_overriding_the_digest_cannot_take_another_tools_row(
    tmp_path,
) -> None:
    """R1 round 3: the property closed planting; `isinstance` still let a subclass in.

    Deriving `signature` stopped `object.__setattr__`, but a subclass that
    OVERRIDES the property passed the `isinstance` gate and returned another
    tool's valid digest. Measured against a reopened store as
    `[('browser', ..., 2)]` with no `run_python` row -- the same wrong durable
    row R1 reported, reached a different way. The gate is now `type(...) is`.
    """
    db = str(tmp_path / "faults.db")
    borrowed = ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2).signature

    class _Impostor(ToolDefect):
        @property
        def signature(self) -> str:
            return borrowed

    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        await store.file_fault(
            tool_id="browser", error_text=ERROR_TEXT,
            defect=ToolDefect(tool_id="browser", error_text=ERROR_TEXT, count=2),
        )
        impostor = _Impostor(tool_id="run_python", error_text=ERROR_TEXT, count=2)
        # The premise: it really is a valid digest, and really does belong to
        # the other tool -- so only the exact-type gate can be what rejects it.
        assert isinstance(impostor, ToolDefect)
        assert _SIGNATURE_RE.fullmatch(impostor.signature)
        assert impostor.signature == borrowed

        await store.file_fault(
            tool_id="run_python", error_text=ERROR_TEXT, defect=impostor,
        )
    finally:
        await store.stop()

    rows = await _reopen_rows(db)

    assert {(r.tool_id, r.occurrences) for r in rows} == {
        ("browser", 1), ("run_python", 1),
    }


@pytest.mark.asyncio
async def test_a_tampered_carrier_cannot_write_an_unbounded_row(
    tmp_path,
) -> None:
    """The bounds are re-checked at the durable boundary, not assumed from construction.

    `__post_init__` bounds a normally-built carrier, but `error_key` and
    `tool_id` are still fields, so `object.__setattr__` can grow them
    afterwards -- and `_ERROR_MAX` is what keeps a fault row from carrying an
    unbounded tool result.

    Mutation caught the first version of this test: it used a SUBCLASS, which
    the `type(...) is ToolDefect` gate rejects first, so the bound was never
    reached and removing it left the test green. Tampering with a genuine
    instance is the path that actually reaches the bounds check.
    """
    db = str(tmp_path / "faults.db")
    tampered = ToolDefect(tool_id="run_python", error_text=ERROR_TEXT, count=2)
    object.__setattr__(tampered, "error_key", "z" * (_ERROR_MAX + 1))

    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        await store.file_fault(
            tool_id="browser", error_text=ERROR_TEXT, defect=tampered,
        )
    finally:
        await store.stop()

    rows = await _reopen_rows(db)

    assert len(rows) == 1
    # Identity recomputed from the honest arguments, not taken from the carrier.
    assert rows[0].tool_id == "browser"
    assert rows[0].signature == error_signature(
        tool_id="browser", error_text=ERROR_TEXT,
    )
