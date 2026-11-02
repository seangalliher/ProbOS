# AD-1356 S1 (#1722): agent work stops filing what a rule can decide

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-01
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-02 (S1.4 taken out on the live board's evidence, §3; built after BF-947's merge)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-02 (A4: re-anchored on main `e9140fcb` after BF-947's merge; P1-8 deleted, P3-6 added, RR3 takes RX-14)
**Status:** ready to build; built on main `e9140fcb` (BF-947, #1724, merged by #1734). S1 is built, reviewed and gated on its own, not batched with BF-947. **Base:** built on main `e9140fcb`; drafted on `378a6a301b5b9ec2ed05735f87f7052fa16d39d5` (origin/main `d5f10598` plus BF-947 as built, before its review) and re-anchored on `e9140fcb` by A4. **Dependencies:** BF-947 (#1724), merged. **Tier:** M1 HIGH, M2 STANDARD, M3 HIGH, M4 STANDARD (trackers and ledger only). **Estimated tests:** 3 new files (10 test functions as written), 3 edited test files.
**AD number:** AD-1356, held by the title of #1722 (`scripts/ad_ceiling.py`: ceiling AD-1356 from issue titles; `gh issue list --search "AD-1356 in:title"`: #1722 only).

**Which text describes the head.** §1 to §3 describe the drafting base `378a6a30`; their line numbers are that commit's. The head is what the pairs and new-file blocks of §7 and §8 produce, applied in order on main `e9140fcb`. Every SEARCH quotes `e9140fcb`. P1-1 to P1-4, P1-6, P1-7, P3-2 to P3-5 and P4-9 quote text BF-947 wrote; P1-1, P1-3 and P1-7 quote it as BF-947's review rounds rewrote it (A4). A SEARCH that no longer matches goes back to the Architect and is not rebased by hand. Where any prose here differs from a REPLACE or new-file block, the block wins. Head text means every docstring, comment, log message, error string, agent-facing string and test docstring in those blocks, plus the tracker entries (§8) and the commit messages (§5).

## 1. Problem

On the base:

1. Under a confinement, a call to a tool id no registry holds goes to the gate and is filed (`agentic_dispatch.py:834-841`). The registry's not-found answer (`registry.py:415-416`) is reached only by calls that are not confined.
2. `detect_tool_defect` counts every error result (`fault_report.py:388-401`). Its verdict feeds the AD-1205 same-run lane (`fault_detection.py:266`, `:541-542`) and the DM path's filer (`cognitive_agent.py:197`, `continue_or_ask.py:782`). The cross-turn lane drops `invalid_params` as noise (`fault_detection.py:32-35`, `:313`), but the same-run lane has no such filter. Three tools mark caller errors as `<tool_id>_invalid:<code>` (`event_log_query_tool.py:565`, `oracle_query_tool.py:377`, `publish_finding_tool.py:876`). `publish_finding` also uses the mark for a records-write failure (`:706`) and an unresolved author (`:424`), and neither is the caller's input.
3. The gate files a `read_file` of the agent's own AD-1240 result (`agent_work_runner.py:655-677`).
4. `_commit` dedups only open requests on an exact key (`agent_work.py:557-567`). On the live board (read-only copy, 2026-11-02) no two of the 43 agent-work items share requester, kind, department, tool, assignee and normalised title; the three `unread_counts` items have three titles and two requesters. S1 does not change `_commit` (§3).

## 2. Solution

- **M1:** `UNREGISTERED_TOOL_REFUSAL`. Under a confinement, a str tool id that resolves to no registered tool is refused before the confinement's set and gate. The refusal is a never-ran outcome in the `permission_denied` class.
- **M2:** `CALLER_INPUT_ERROR_MARK` and `is_caller_input_error` in `tools/protocol.py`. `detect_tool_defect` and `collect_tool_fault_batch` skip a marked result. `publish_finding`'s two non-input outcomes move to `publish_finding_failed:`.
- **M3:** `_recovery_read`, first in the gate, admits without filing. The runner does not keep a `WorkspaceSliceToolResult`.
- **M4:** trackers and ledger. No `src` or `tests` file.

## 3. Decisions

- **Unknown tool:** confined calls only; resolved through `_resolve_tool_id` then `registry.get`; reason code `confinement_refused`.
- **Input errors:** one predicate in `tools/protocol.py`, applied at the two places a result becomes defect evidence. `FaultReportStore.file_fault` and repair dispatch are unchanged.
- **Recovery reads:** keyed on the tool id and the path only. Lexical: absolute, no `..`, a result-directory part, under `workspace_exempt_roots`. No approval is used and nothing is filed or kept.
- **Duplicates (S1.4): not in S1.** On the live board no two of 43 items share the drafted key. The duplicates #1722 cites are reworded and from two requesters. The finding is recorded on #1722 as unresolved; an exact same-requester group on a live board would reopen it.
- **Config:** none. No new method on `AgentWorkService` (15 direct methods), `AgentWorkRunner` (15) or `PublishFindingTool`.

## 4. Milestones and gates

| M | Tier | Pairs | Gate |
|---|---|---|---|
| M1 | HIGH | P1-1 to P1-7, P1-9, N1-1 | G1 |
| M2 | STANDARD | P2-1 to P2-12, N2-1 | G2 |
| M3 | HIGH | P3-1 to P3-6, N3-1 | G3 |
| M4 | STANDARD | P4-8, P4-9, the ledger | G4 |

**G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1356_s1_unknown_tools.py tests/test_ad1156_plan_execute_mode.py tests/test_bf947_confinement_answer.py tests/test_bf947_multi_call_agent_work.py tests/test_ad1347_s3_execution.py tests/test_ad1154_approval_inbox.py tests/test_ad1152_agentic_correlation.py -q -n 0`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`

**G2:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1356_s1_input_errors.py tests/test_ad1169_fault_reports.py tests/test_ad1205_fault_observer.py tests/test_ad1205_fault_paths.py tests/test_ad1257_defect_follows_failure.py tests/test_ad1172_repair_dispatch.py tests/test_ad1140_publish_finding.py tests/test_ad1191_delegation_wire.py tests/test_ad1179_parameter_vocabulary_guards.py tests/test_ad1129_eventlog_query_tool.py tests/test_ad1139_oracle_query_tool.py -q -n 0`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`

**G3:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1356_s1_recovery_reads.py tests/test_bf947_multi_call_agent_work.py tests/test_ad1347_s3_execution.py tests/test_ad1240_tool_result_delivery.py -q -n 0`, then:
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_dormant_classes.py --check`

**G4:**
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`

## 5. Commit messages

- M1: `AD-1356 S1 M1: under agent work, a call to an unregistered tool is refused before the gate`
- M2: `AD-1356 S1 M2: a tool's mark of its caller's bad input is not a fault`
- M3: `AD-1356 S1 M3: the agent-work gate admits a read of a workspace-result path under the workspace root`
- M4: `AD-1356 S1 M4: trackers and ledger`

## 6. Tests

| Id | File | Test | Covers |
|---|---|---|---|
| UT1 | unknown_tools | `test_an_unregistered_tool_is_refused_not_filed_and_never_counts_toward_a_fault` | Acceptance 3, whole path |
| UT2 | unknown_tools | `test_only_a_confined_call_to_an_unregistered_id_is_refused_before_the_gate` | Q2 boundaries |
| IE1 | input_errors | `test_caller_input_errors_in_three_runs_file_no_fault_on_the_observer_path` | Acceptance 4, observer path |
| IE2 | input_errors | `test_caller_input_errors_file_no_fault_on_the_dm_filing_path` | Acceptance 4, DM path |
| IE3 | input_errors | `test_two_identical_genuine_tool_errors_still_file_a_fault_on_both_paths` | Acceptance 4, control |
| IE4 | input_errors | `test_only_a_tools_own_mark_is_a_caller_input_error` | predicate edges |
| IE5 | input_errors | `test_a_marked_error_is_neither_fault_nor_success_evidence_in_a_batch` | batch lane |
| RR1 | recovery_reads | `test_a_read_of_the_agents_own_workspace_result_runs_without_approval_and_another_agents_is_refused_by_the_tool` | Acceptance 5, whole path |
| RR2 | recovery_reads | `test_only_an_absolute_result_path_under_a_workspace_root_is_a_recovery_read` | predicate edges |
| RR3 | recovery_reads | `test_a_read_that_climbs_out_of_the_result_directory_is_filed_not_run` | filed, whole path; a recovery read is not kept on a parked item |

Edited:
- `test_the_plan_mode_refusal_is_a_policy_outcome` gains the new member of `_NEVER_RAN_REFUSALS`.
- Five asserts in `test_ad1140_publish_finding.py` and one in `test_ad1191_delegation_wire.py` take the `publish_finding_failed:` codes.

## 7. The contract

### 7.1 M1

**P1-1** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
# AD-1347 S3 (#1627): agent-created work runs confined. Its calls to the tools in the run's set run as usual; a call to
# any other tool is put to the run's gate, which admits it, files it for the Captain's approval (an AD-1154
# ``action``), answers it (BF-947) or refuses it. Error-shaped and final, in the AD-1154 voice; never defect evidence.
```
REPLACE:
```python
# AD-1347 S3 (#1627): agent-created work runs confined. AD-1356 S1.1: a call whose tool id the executor's registry does
# not hold is refused before the run's set is consulted. Its other calls to the tools in the run's set run as usual; a
# call to any other tool is put to the run's gate, which admits it, files it for the Captain's approval (an AD-1154
# ``action``), answers it (BF-947) or refuses it. Error-shaped and final, in the AD-1154 voice; never defect evidence.
```

**P1-2** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
# BF-947: the refusal for ``CONFINEMENT_ANSWERED``.
CONFINED_CALL_ANSWERED: str = (
    "That call already ran in this work under its approval, so it did not run again. Its result is in your task "
    "text or earlier in this run."
)
CONFINEMENT_ADMIT = "admit"
CONFINEMENT_FILED = "filed"
CONFINEMENT_REFUSED = "refused"
CONFINEMENT_ANSWERED = "answered"  # BF-947

# AD-1189 / AD-1156: refusals of calls that never ran. They say nothing about
# the tool, so they are never defect evidence.
_NEVER_RAN_REFUSALS: frozenset[str] = frozenset({
    _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL, CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED,
    CONFINED_CALL_ANSWERED,
})
```
REPLACE:
```python
# BF-947: the refusal for ``CONFINEMENT_ANSWERED``.
CONFINED_CALL_ANSWERED: str = (
    "That call already ran in this work under its approval, so it did not run again. Its result is in your task "
    "text or earlier in this run."
)
# AD-1356 S1.1: the refusal, under a confinement, of a call whose tool id the executor's registry does not hold.
UNREGISTERED_TOOL_REFUSAL: str = (
    "That call names no registered tool, so it did not run and was not filed for approval. Use "
    "search_capabilities to find a registered tool for this step."
)
CONFINEMENT_ADMIT = "admit"
CONFINEMENT_FILED = "filed"
CONFINEMENT_REFUSED = "refused"
CONFINEMENT_ANSWERED = "answered"  # BF-947

# AD-1189 / AD-1156: refusals of calls that never ran. They say nothing about
# the tool, so they are never defect evidence.
_NEVER_RAN_REFUSALS: frozenset[str] = frozenset({
    _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL, CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED,
    CONFINED_CALL_ANSWERED, UNREGISTERED_TOOL_REFUSAL,
})
```

**P1-3** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
    """AD-1347 S3: the calls a run makes directly (``tool_ids``) and the gate every other call is put to.

    ``gate(agent_id, tool_id, params)`` answers ``CONFINEMENT_ADMIT`` (run it), ``CONFINEMENT_FILED`` (filed for the
    Captain's approval), ``CONFINEMENT_ANSWERED`` (BF-947: refused with ``CONFINED_CALL_ANSWERED``) or anything else
    (not filed). Enforced first in the executor's invoke, before plan mode and the AD-1154 browser inbox, so the
    decision is made at the tool call, never by reading the plan. BF-947: ``record``, when set, is handed results of
    admitted calls (``record_admitted``).
    """
```
REPLACE:
```python
    """AD-1347 S3: the calls a run makes directly (``tool_ids``) and the gate for the run's other calls.

    ``gate(agent_id, tool_id, params)`` answers ``CONFINEMENT_ADMIT`` (run it), ``CONFINEMENT_FILED`` (filed for the
    Captain's approval), ``CONFINEMENT_ANSWERED`` (BF-947: refused with ``CONFINED_CALL_ANSWERED``) or anything else
    (not filed). Enforced in the executor's invoke after AD-1356 S1.1's refusal of a tool id the registry does not
    hold, and before plan mode and the AD-1154 browser inbox, so the decision is made at the tool call, never by
    reading the plan. BF-947: ``record``, when set, is handed results of admitted calls (``record_admitted``).
    """
```

**P1-4** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
        confinement = self._confinement
        confined_admission = False
        admitted_params = params  # BF-947: what the gate was asked, for record_admitted
        if confinement is not None and tool_id not in confinement.tool_ids:
            refusal = await confinement.refuse_or_admit(agent_id, tool_id, params)
```
REPLACE:
```python
        confinement = self._confinement
        confined_admission = False
        admitted_params = params  # BF-947: what the gate was asked, for record_admitted
        # AD-1356 S1.1: under a confinement, when the executor has a registry, a str tool id that resolves to no
        # registered tool is refused here, before the confinement's set and gate, so it is never filed. An ambiguous
        # name (``_resolve_tool_id`` answers None) goes on to the gate.
        if confinement is not None and self._registry is not None and type(tool_id) is str:
            resolved = self._resolve_tool_id(tool_id)
            if resolved is not None and self._registry.get(resolved) is None:
                strict_log("confinement", "confinement_refused")
                return refuse(ToolResult(error=UNREGISTERED_TOOL_REFUSAL), "confinement_refused")
        if confinement is not None and tool_id not in confinement.tool_ids:
            refusal = await confinement.refuse_or_admit(agent_id, tool_id, params)
```

**P1-5** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
    def confine_calls(self, confinement: ToolCallConfinement) -> None:
        """AD-1347 S3: put every call to a tool outside ``confinement.tool_ids`` to its gate, first in :meth:`invoke`."""
        self._confinement = confinement
```
REPLACE:
```python
    def confine_calls(self, confinement: ToolCallConfinement) -> None:
        """AD-1347 S3: put every call to a tool outside ``confinement.tool_ids`` to its gate in :meth:`invoke`, after
        AD-1356 S1.1 refuses a call whose tool id the registry does not hold."""
        self._confinement = confinement
```

**P1-6** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
            _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL,
            CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED, CONFINED_CALL_ANSWERED,  # AD-1347 S3, BF-947
            "consensus_blocked", "requires_confirmation",
```
REPLACE:
```python
            _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL,
            CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED, CONFINED_CALL_ANSWERED,  # AD-1347 S3, BF-947
            UNREGISTERED_TOOL_REFUSAL,  # AD-1356 S1.1
            "consensus_blocked", "requires_confirmation",
```

**P1-7** `src/probos/agent_work_runner.py`

SEARCH:
```python
Every run is confined (``ToolCallConfinement``): the tools in ``AGENT_WORK_READ_TOOL_IDS`` run as usual and a call to
any other tool is put to the run's gate (``_gate_for``, whose docstring gives its order), which may file it as an
AD-1154 ``action`` request. A run that filed a call can park the item ``blocked`` on the first request its gate
returned, through AD-855's ``block_on_request``; its approval fulfils it and AD-855 resumes the item through
```
REPLACE:
```python
Every run is confined (``ToolCallConfinement``): the executor refuses a call whose tool id its registry does not hold
(AD-1356 S1.1); the tools in ``AGENT_WORK_READ_TOOL_IDS`` run as usual; and a call to any other tool is put to the
run's gate (``_gate_for``, whose docstring gives its order), which may file it as an AD-1154 ``action`` request. A run
that filed a call can park the item ``blocked`` on the first request its gate returned, through AD-855's
``block_on_request``; its approval fulfils it and AD-855 resumes the item through
```

P1-8 is not in S1 (A4): main's task text already says what its REPLACE said (BF-947's F1 repair). Its id is not reused.

**P1-9** `tests/test_ad1156_plan_execute_mode.py`

SEARCH:
```python
    # AD-1347 S3: a confined call that was filed or refused never ran either; BF-947: nor one the gate answered.
    assert never_ran == {
        _REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL,
        agentic_dispatch.CONFINED_CALL_FILED, agentic_dispatch.CONFINED_CALL_NOT_FILED,
        agentic_dispatch.CONFINED_CALL_ANSWERED,
    }
```
REPLACE:
```python
    # AD-1347 S3: a confined call that was filed or refused never ran either; BF-947: nor one the gate answered;
    # AD-1356 S1.1: nor one refused because its tool id is not registered.
    assert never_ran == {
        _REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL,
        agentic_dispatch.CONFINED_CALL_FILED, agentic_dispatch.CONFINED_CALL_NOT_FILED,
        agentic_dispatch.CONFINED_CALL_ANSWERED, agentic_dispatch.UNREGISTERED_TOOL_REFUSAL,
    }
```

**N1-1** `tests/test_ad1356_s1_unknown_tools.py` (new)
```python
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
```

### 7.2 M2

**P2-1** `src/probos/tools/protocol.py`

SEARCH:
```python
@dataclass(frozen=True)
class ToolResult:
    """Result of a tool invocation."""

    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.error is None
```
REPLACE:
```python
@dataclass(frozen=True)
class ToolResult:
    """Result of a tool invocation."""

    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.error is None


#: AD-1356 S1.2: how a tool marks a caller error. A ``ToolResult.error`` that starts with the tool's own id and this
#: mark (``event_log_query_invalid:window``) says the call's input was wrong. ``fault_report.detect_tool_defect`` and
#: ``fault_detection.collect_tool_fault_batch`` skip such a result.
CALLER_INPUT_ERROR_MARK: str = "_invalid:"


def is_caller_input_error(tool_id: object, error: object) -> bool:
    """AD-1356 S1.2: whether ``error`` is ``tool_id``'s mark of a caller error: both are str, ``tool_id`` is not empty,
    and ``error`` starts with ``tool_id + CALLER_INPUT_ERROR_MARK`` (case-sensitive) and is longer than that prefix."""
    if type(tool_id) is not str or not tool_id or type(error) is not str:
        return False
    prefix = tool_id + CALLER_INPUT_ERROR_MARK
    return len(error) > len(prefix) and error.startswith(prefix)
```

**P2-2** `src/probos/fault_report.py`

SEARCH:
```python
from probos.fault_issue_filings import (
    ISSUE_FILING_SCHEMA, FaultIssueFilings, fault_transaction,
)
```
REPLACE:
```python
from probos.fault_issue_filings import (
    ISSUE_FILING_SCHEMA, FaultIssueFilings, fault_transaction,
)
from probos.tools.protocol import is_caller_input_error
```

**P2-3** `src/probos/fault_report.py`

SEARCH:
```python
    The resolver is INJECTED rather than imported. This module is foundation and
    stdlib-only; the authority that can answer the question
```
REPLACE:
```python
    The resolver is INJECTED rather than imported. This module is foundation; the
    authority that can answer the question
```

**P2-4** `src/probos/fault_report.py`

SEARCH:
```python
    answered with a count of 2. The same split can also hand the win to a
    less-frequent competing defect. Each distinct name is resolved once per
    call; the ``max()`` and the threshold are otherwise unchanged.

    Never raises: a malformed outcome yields ``None`` and the caller takes the
```
REPLACE:
```python
    answered with a count of 2. The same split can also hand the win to a
    less-frequent competing defect. Each distinct name is resolved once per
    call; the ``max()`` and the threshold are otherwise unchanged.

    AD-1356 S1.2: a result whose output ``is_caller_input_error`` marks for its
    canonical tool is not counted.

    Never raises: a malformed outcome yields ``None`` and the caller takes the
```

**P2-5** `src/probos/fault_report.py`

SEARCH:
```python
            raw = getattr(result, "output", "")
            raw_text = raw if type(raw) is str else str(raw)
            key = (_canonical(observed), normalise_error(raw_text))
```
REPLACE:
```python
            raw = getattr(result, "output", "")
            raw_text = raw if type(raw) is str else str(raw)
            tool = _canonical(observed)
            if is_caller_input_error(tool, raw_text):  # AD-1356 S1.2: the call's input was wrong, not the tool
                continue
            key = (tool, normalise_error(raw_text))
```

**P2-6** `src/probos/fault_detection.py`

SEARCH:
```python
from probos.tools.protocol import ToolResult
```
REPLACE:
```python
from probos.tools.protocol import ToolResult, is_caller_input_error
```

**P2-7** `src/probos/fault_detection.py`

SEARCH:
```python
        defect = None
        if failed:
            if type(raw) is not str:
                logger.warning(
                    "AD-1205: non-text tool error skipped; no error identity "
                    "can be established, so it contributes no diagnostic vote"
                )
                continue
            defect = ToolDefect(
```
REPLACE:
```python
        defect = None
        if failed:
            if type(raw) is not str:
                logger.warning(
                    "AD-1205: non-text tool error skipped; no error identity "
                    "can be established, so it contributes no diagnostic vote"
                )
                continue
            if is_caller_input_error(canonical, raw):
                continue  # AD-1356 S1.2: the call's input was wrong; neither fault nor success evidence
            defect = ToolDefect(
```

**P2-8** `src/probos/tools/publish_finding_tool.py`

SEARCH:
```python
        identity = self._resolve_identity(ctx)
        if identity is None:
            return self._invalid("author", started)
        callsign, department = identity
```
REPLACE:
```python
        identity = self._resolve_identity(ctx)
        if identity is None:
            return ToolResult(  # AD-1356 S1.2: not the caller's input, so not the _invalid: mark
                error="publish_finding_failed:author", duration_ms=(time.monotonic() - started) * 1000.0,
            )
        callsign, department = identity
```

**P2-9** `src/probos/tools/publish_finding_tool.py`

SEARCH:
```python
                "recorded and the agent is told the publication did not land",
                callsign, claim_id[:8], exc_info=True,
            )
            return self._invalid("write_failed", started)
```
REPLACE:
```python
                "recorded and the agent is told the publication did not land",
                callsign, claim_id[:8], exc_info=True,
            )
            return ToolResult(  # AD-1356 S1.2: not the caller's input, so not the _invalid: mark
                error="publish_finding_failed:write_failed", duration_ms=(time.monotonic() - started) * 1000.0,
            )
```

**P2-10** `tests/test_ad1140_publish_finding.py` (two pairs)

SEARCH:
```python
    result = await tool.invoke(_params(), _ctx())

    assert result.error == "publish_finding_invalid:author"
    assert _notebook_files(records) == []
    assert _CALLSIGN_RE.fullmatch(callsign) is None
```
REPLACE:
```python
    result = await tool.invoke(_params(), _ctx())

    assert result.error == "publish_finding_failed:author"  # AD-1356 S1.2: not the caller's input
    assert _notebook_files(records) == []
    assert _CALLSIGN_RE.fullmatch(callsign) is None
```

SEARCH:
```python
    assert (await tool.invoke(_params(), {})).error == (
        "publish_finding_invalid:author"
    )
    assert (await tool.invoke(_params(), None)).error == (
        "publish_finding_invalid:author"
    )
```
REPLACE:
```python
    assert (await tool.invoke(_params(), {})).error == (
        "publish_finding_failed:author"  # AD-1356 S1.2: not the caller's input
    )
    assert (await tool.invoke(_params(), None)).error == (
        "publish_finding_failed:author"
    )
```

**P2-11** `tests/test_ad1140_publish_finding.py` (two pairs)

SEARCH:
```python
    assert result.error == "publish_finding_invalid:author"
    assert _notebook_files(records) == []
    assert any("AD-1140" in r.message for r in caplog.records)
```
REPLACE:
```python
    assert result.error == "publish_finding_failed:author"  # AD-1356 S1.2: not the caller's input
    assert _notebook_files(records) == []
    assert any("AD-1140" in r.message for r in caplog.records)
```

SEARCH:
```python
    result = await _tool(records).invoke(_params(), _ctx())

    assert result.error == "publish_finding_invalid:write_failed"
```
REPLACE:
```python
    result = await _tool(records).invoke(_params(), _ctx())

    assert result.error == "publish_finding_failed:write_failed"  # AD-1356 S1.2: not the caller's input
```

**P2-12** `tests/test_ad1191_delegation_wire.py`

SEARCH:
```python
    if refusal == "write_failed":
        assert native.error == "publish_finding_invalid:write_failed"
        assert native.output is None and native.metadata == {}
```
REPLACE:
```python
    if refusal == "write_failed":
        assert native.error == "publish_finding_failed:write_failed"  # AD-1356 S1.2: not the caller's input
        assert native.output is None and native.metadata == {}
```

**N2-1** `tests/test_ad1356_s1_input_errors.py` (new)
```python
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
```

### 7.3 M3

**P3-1** `src/probos/agent_work_runner.py`

SEARCH:
```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
```
REPLACE:
```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
```

**P3-2** `src/probos/agent_work_runner.py`

SEARCH:
```python
    """BF-947 (M3): per item, the results of admitted calls that returned no error, in this process only: the newest
    ``CARRIED_RESULTS_MAX`` per item, oldest first; an entry replaces one with the same call key."""
```
REPLACE:
```python
    """BF-947 (M3): per item, the results of admitted calls that returned no error, in this process only: the newest
    ``CARRIED_RESULTS_MAX`` per item, oldest first; an entry replaces one with the same call key. AD-1356 S1.3: a
    ``WorkspaceSliceToolResult`` is not kept."""
```

**P3-3** `src/probos/agent_work_runner.py`

SEARCH:
```python
        def record(agent_id: str, tool_id: Any, params: Any, result: Any) -> None:
            payload = approval_payload(tool_id, params, work_item_id)
            if payload is None or getattr(result, "error", None) is not None:
                return
```
REPLACE:
```python
        def record(agent_id: str, tool_id: Any, params: Any, result: Any) -> None:
            payload = approval_payload(tool_id, params, work_item_id)
            if payload is None or getattr(result, "error", None) is not None:
                return
            from probos.cognitive.swe_harness.tools import WorkspaceSliceToolResult

            if isinstance(result, WorkspaceSliceToolResult):  # AD-1356 S1.3: a read of a workspace result is not kept
                return
```

**P3-4** `src/probos/agent_work_runner.py`

SEARCH:
```python
    return validate_action_payload({
        "tool_id": tool_id, "action": APPROVAL_ACTION, "params": recorded,
        "scope_key": APPROVAL_SCOPE_PREFIX + work_item_id, "session_id": None, "thread_id": "",
    })


def _provenance(item: WorkItem) -> dict[str, Any]:
```
REPLACE:
```python
    return validate_action_payload({
        "tool_id": tool_id, "action": APPROVAL_ACTION, "params": recorded,
        "scope_key": APPROVAL_SCOPE_PREFIX + work_item_id, "session_id": None, "thread_id": "",
    })


def _recovery_read(tool_id: Any, params: Any, roots: list[Path]) -> bool:
    """AD-1356 S1.3: a ``read_file`` call whose ``path`` is absolute, has no ``..`` part, has a part that
    ``is_workspace_result_path`` recognises, and lies under one of ``roots``."""
    raw = params.get("path") if tool_id == "read_file" and type(params) is dict else None
    if type(raw) is not str:
        return False
    from probos.execution.workspace_results import is_workspace_result_path

    path = Path(raw)
    return (
        path.is_absolute() and ".." not in path.parts and is_workspace_result_path(path)
        and any(path.is_relative_to(root) for root in roots)
    )


def _provenance(item: WorkItem) -> dict[str, Any]:
```

**P3-5** `src/probos/agent_work_runner.py`

SEARCH:
```python
        """The run's confinement gate, in this order. A call that cannot be recorded is refused. A call whose result
        this runner keeps on the item for the agent is answered and does not run (BF-947). A call a fulfilled request
        in ``admissions`` covers is admitted, once per request; with each such request used, it goes on as any other
        call. Any other call is refused when the agent has ``max_pending`` or more pending requests, else filed for
        approval (refused when the filing returns no request)."""
        from probos.cognitive.agentic_dispatch import (
            CONFINEMENT_ADMIT,
            CONFINEMENT_ANSWERED,
            CONFINEMENT_FILED,
            CONFINEMENT_REFUSED,
        )

        async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
            payload = approval_payload(tool_id, params, work_item_id)
            if payload is None:
                return CONFINEMENT_REFUSED
```
REPLACE:
```python
        """The run's confinement gate, in this order. A call ``_recovery_read`` accepts over ``workspace_exempt_roots``
        is admitted; it uses no approval, is not filed, and ``read_file`` decides whether the agent may read the path
        (AD-1356 S1.3). A call that cannot be recorded is refused. A call whose result this runner keeps on the item
        for the agent is answered and does not run (BF-947). A call a fulfilled request in ``admissions`` covers is
        admitted, once per request; with each such request used, it goes on as any other call. Any other call is
        refused when the agent has ``max_pending`` or more pending requests, else filed for approval (refused when the
        filing returns no request)."""
        from probos.cognitive.agentic_dispatch import (
            CONFINEMENT_ADMIT,
            CONFINEMENT_ANSWERED,
            CONFINEMENT_FILED,
            CONFINEMENT_REFUSED,
        )
        from probos.security.file_access import workspace_exempt_roots

        roots = workspace_exempt_roots(self._runtime)

        async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
            if _recovery_read(tool_id, params, roots):
                logger.info(
                    "AD-1356: agent work %s admitted a read of a workspace-result path; nothing was filed", work_item_id[:8],
                )
                return CONFINEMENT_ADMIT
            payload = approval_payload(tool_id, params, work_item_id)
            if payload is None:
                return CONFINEMENT_REFUSED
```

**P3-6** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
            # AD-1347 S3 A1 (F3): the Captain approved exactly this call, once; AD-1154's inbox below does not park it
            # again (credential entry there stays refused).
            confined_admission = True
```
REPLACE:
```python
            # AD-1347 S3 A1 (F3): the gate admitted this call, under the Captain's approval of exactly this call, once,
            # or as a read of a workspace-result path, which needs none (AD-1356 S1.3). AD-1154's inbox below does not
            # park an admitted call (credential entry there stays refused).
            confined_admission = True
```

**N3-1** `tests/test_ad1356_s1_recovery_reads.py` (new)
```python
"""AD-1356 S1.3 (#1722): the agent-work gate admits a read of a workspace-result path under the workspace root, and the
tool decides whose result it is.

Through the rig of ``tests/test_ad1347_s3_execution.py`` with a real AD-1240 ``WorkspaceResultStore`` (as
``tests/test_ad1240_workspace_results.py`` builds it) as the runtime's workspace and the native tools registered by
``register_native_swe_tools``. On the base this file fails at import (``_recovery_read``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.agent_work import AgentWorkCreated, AgentWorkOrigin
from probos.agent_work_runner import _recovery_read
from probos.capability_request import requests_for_work_item
from probos.cognitive.swe_harness.tools import register_native_swe_tools
from tests.test_ad1240_workspace_results import _capture, make_store
from tests.test_ad1347_s1_agent_work import REASON
from tests.test_ad1347_s3_execution import _call, _final, _pump, _rig, _seen, _thread_in

OWN_TEXT = "Relay drift log: two events, at 00:12 and at 00:47."
FOREIGN_TEXT = "Security sweep notes for deck four."


async def _workspace(rig: Any, tmp_path: Path) -> Any:
    """A started AD-1240 store under ``tmp_path`` as the runtime's workspace root and owner, with the native tools."""
    store = make_store(tmp_path / "workspaces").store
    execution = rig.runtime.config.execution.model_copy(update={"workspace_root": str(store.root)})
    rig.runtime.config = rig.runtime.config.model_copy(update={"execution": execution})
    rig.runtime.workspace_results = store
    assert register_native_swe_tools(rig.tools, rig.runtime) == 12
    await store.start()
    return store


async def _self_task(rig: Any, title: str) -> str:
    origin = await _thread_in(rig, "engineering", "laforge-1")
    created = await rig.service.create_self_task(
        "forge-1", title=title, description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
    )
    assert isinstance(created, AgentWorkCreated), created
    await _pump(rig)
    return created.work_item.id


# RR1
async def test_a_read_of_the_agents_own_workspace_result_runs_without_approval_and_another_agents_is_refused_by_the_tool(
    tmp_path: Path,
) -> None:
    """Acceptance 5: forge-1's read of its own stored result runs under agent work, the item is done and nothing is
    filed. Its read of worf-1's stored result is not filed either; the item ends done or failed (AD-1240 may end the
    run on the tool's refusal), and worf-1's text never reaches the model."""
    paths: dict[str, str] = {}

    async def read_own(request: Any) -> Any:
        return _call("read_file", {"path": paths["own"]}, "c1")

    async def read_foreign(request: Any) -> Any:
        return _call("read_file", {"path": paths["foreign"]}, "c2")

    script = [read_own, _final("Read my own result."), read_foreign, _final("Read the other result.")]
    async with _rig(tmp_path, script) as rig:
        store = await _workspace(rig, tmp_path)
        try:
            own = await store.store_tool_result(store.bind_agent("forge-1", rig.agents["forge-1"]), _capture(OWN_TEXT))
            foreign = await store.store_tool_result(store.bind_agent("worf-1", rig.agents["worf-1"]), _capture(FOREIGN_TEXT))
            paths.update(own=own.path, foreign=foreign.path)
            own_item = await _self_task(rig, "Read my stored result")
            done = await rig.store.get_work_item(own_item)
            assert done is not None and done.status == "done"
            assert requests_for_work_item(rig.requests, own_item) == []
            assert _seen(rig, OWN_TEXT)
            foreign_item = await _self_task(rig, "Read the security sweep")
            ended = await rig.store.get_work_item(foreign_item)
            assert ended is not None and ended.status in ("done", "failed")
            assert requests_for_work_item(rig.requests, foreign_item) == []
            assert not _seen(rig, FOREIGN_TEXT)
        finally:
            await store.stop()


# RR2
@pytest.mark.parametrize(("tool_id", "path", "accepted"), [
    ("read_file", "{root}/forge/.tool-results/20261011T07Z/abc/payload.jsonl", True),
    ("read_file", "{root}/forge/.TOOL-RESULTS/payload.jsonl", True),
    ("read_file", "{root}/forge/.tool-results/../notes.txt", False),
    ("read_file", "{elsewhere}/.tool-results/payload.jsonl", False),
    ("read_file", ".tool-results/payload.jsonl", False),
    ("read_file", "{root}/forge/notes.txt", False),
    ("list_files", "{root}/forge/.tool-results/payload.jsonl", False),
    ("read_file", "", False),
])
def test_only_an_absolute_result_path_under_a_workspace_root_is_a_recovery_read(
    tmp_path: Path, tool_id: str, path: str, accepted: bool,
) -> None:
    """The tool id is read_file; the path is absolute, has no ``..`` part, has a result-directory part in any case, and
    lies under a root. A non-str path or non-dict parameters are never accepted."""
    root = tmp_path / "workspaces"
    raw = path.format(root=root, elsewhere=tmp_path / "elsewhere")
    assert _recovery_read(tool_id, {"path": raw}, [root]) is accepted
    assert _recovery_read("read_file", {"path": 7}, [root]) is False
    assert _recovery_read("read_file", ["not", "a", "dict"], [root]) is False


# RR3
async def test_a_read_that_climbs_out_of_the_result_directory_is_filed_not_run(tmp_path: Path) -> None:
    """A ``read_file`` whose path names the result directory and then ``..`` is not a recovery read: the gate files it
    and the item parks on the request. The recovery read the run made first is shown to the model and is not kept on
    the parked item (a parked item keeps its results; an ended one drops them)."""
    paths: dict[str, str] = {}

    async def read_own(request: Any) -> Any:
        return _call("read_file", {"path": paths["own"]}, "c1")

    async def climb(request: Any) -> Any:
        return _call("read_file", {"path": paths["climb"]}, "c2")

    async with _rig(tmp_path, [read_own, climb, _final("Waiting for the Captain.")]) as rig:
        store = await _workspace(rig, tmp_path)
        try:
            own = await store.store_tool_result(store.bind_agent("forge-1", rig.agents["forge-1"]), _capture(OWN_TEXT))
            paths.update(own=own.path, climb=str(store.root / "forge" / ".tool-results" / ".." / "notes.txt"))
            item_id = await _self_task(rig, "Read the notes")
            parked = await rig.store.get_work_item(item_id)
            assert parked is not None and parked.status == "blocked"
            assert _seen(rig, OWN_TEXT)
            assert rig.runner.carried.for_agent(item_id, "forge-1") == ()
            [request] = requests_for_work_item(rig.requests, item_id)
            assert (request.status, request.payload["tool_id"], request.payload["params"]) == (
                "pending", "read_file", {"path": paths["climb"]},
            )
        finally:
            await store.stop()
```

### 7.4 M4

M4 changes no `src` or `tests` file; its pairs are P4-8 and P4-9 (§8) and the ledger. P4-1 to P4-7 and N4-1 (S1.4) are not in S1 (§3); their ids are not reused.

## 8. Tracking (M4's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` in its first 120 characters.

**Date rule:** both heads carry 2026-11-02. If M4 is committed on a later date (`git log -1 --format=%cs`), the Builder puts that date in both heads.

**P4-8** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1356 S1 (2026-11-02), #1722 -- agent work stops filing calls and faults a rule can decide.** Under a confinement the executor now refuses a call whose tool id its registry does not hold before the confinement's set and gate, with `UNREGISTERED_TOOL_REFUSAL`, a never-ran refusal that names `search_capabilities`. A tool error that starts with the tool's own id and `_invalid:` (`tools.protocol.is_caller_input_error`) is skipped by `detect_tool_defect` and `collect_tool_fault_batch`; `publish_finding`'s records-write failure and unresolved author now answer `publish_finding_failed:` codes. The agent-work gate admits, without an approval or a filing, a `read_file` of an absolute path with no `..` part that names the AD-1240 result directory and lies under the workspace root; `read_file` decides whose result it is, and the runner does not keep that result. S1 adds no dedup rule and `AgentWorkService._commit` is unchanged: on a read-only copy of the live board (2026-11-02) no two of 43 agent-work items share requester, kind, department, tool, assignee and normalised title, and the three `unread_counts` items have three titles from two requesters. No config field. The contract is `prompts/ad-1356-s1-stop-filing-what-a-rule-decides.md`.

```

**P4-9** `DECISIONS.md`

SEARCH:
```
### BF-947 -- An agent-work item waits for each call it filed, and each approval admits its call once (2026-11-02, #1724)
```
REPLACE:
```
### AD-1356 S1 -- Agent work stops filing what a rule can decide (2026-11-02, #1722)

- *Scope.* `cognitive/agentic_dispatch.py` (`UNREGISTERED_TOOL_REFUSAL`), `tools/protocol.py` (`CALLER_INPUT_ERROR_MARK`, `is_caller_input_error`), `fault_report.py`, `fault_detection.py`, `tools/publish_finding_tool.py`, `agent_work_runner.py` (`_recovery_read`), tests. Contract `prompts/ad-1356-s1-stop-filing-what-a-rule-decides.md`.
- *Unknown tools.* Under a confinement, a call whose resolved tool id the executor's registry does not hold is refused before the confinement's set and gate, a never-ran refusal. A call with no confinement keeps the registry's not-found result.
- *Input errors.* A `ToolResult.error` that starts with the tool's id and `_invalid:` marks a caller error; `detect_tool_defect` and `collect_tool_fault_batch` skip it. `publish_finding`'s two outcomes that were not the caller's input moved to `publish_finding_failed:`.
- *Recovery reads.* The gate admits a call `_recovery_read` accepts without an approval or a filing; `read_file` decides whose result it is. The runner does not keep a `WorkspaceSliceToolResult`.
- *Duplicates.* No rule added; `_commit` is unchanged. The live board (2026-11-02) held no two of 43 items with the same requester, kind, department, tool, assignee and normalised title; the cited duplicates were reworded and from two requesters.
- *Rejected.* Refusing unregistered ids with no confinement; a docstring-only convention; a filter in `FaultReportStore.file_fault`; the raw-path recovery test; an exact same-work rule with no live case; title-similarity matching.
- *Residual.* Recorded limits L1 to L12 of the contract.
- *Reversal.* Revert the AD-1356 S1 commits.

### BF-947 -- An agent-work item waits for each call it filed, and each approval admits its call once (2026-11-02, #1724)
```

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them.

**Not updated:** `docs/development/roadmap.md` (its Bug Tracker is for BFs).

**Merge note:** the unmerged AD-1346 M3e4c3c branch inserts after `# ProbOS Progress` and above `### Explicit delegation models ...`. S1's DECISIONS anchor is BF-947's heading, and its PROGRESS anchor is the file header. Resolve either order mechanically, keeping every entry.

## 9. What this does NOT change

- The behaviour of an executor with no confinement (UT2 pins #1214's not-found answer).
- `FaultReportStore.file_fault`, `repair_dispatch.py`, `continue_or_ask.py` and `cognitive_agent.py`: not edited.
- `ReadFileTool`, the AD-1240 store, `result_offload.py` and `_delivery_stop`: not edited (BF-946's scope).
- `AGENT_WORK_READ_TOOL_IDS`, AD-1213 routing, `classify_capability_request` and AD-1154's dedup.
- BF-947's park, admission and carried results, except that a `WorkspaceSliceToolResult` is not kept (P3-3).
- `event_log_query_tool.py` and `oracle_query_tool.py`: not edited.
- `agent_work.py` and `agent_work_tags.py`: not edited. AD-1347 S1's open-request dedup is the only dedup rule (§3).
- `SystemConfig`, `EventType`, the persisted schema (`dedup_key` stays `None` for work that is not a request) and request kinds.

## 10. Mutation rows (one campaign of record on M3's head; M4 changes no `src` file)

The Line cells hold the source line without its leading indentation. Prefix `RX` (absent from `prompts/`).

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| RX-1 | `src/probos/cognitive/agentic_dispatch.py` | `if resolved is not None and self._registry.get(resolved) is None:` | `if False:` | `test_an_unregistered_tool_is_refused_not_filed_and_never_counts_toward_a_fault` |
| RX-2 | `src/probos/cognitive/agentic_dispatch.py` | `resolved = self._resolve_tool_id(tool_id)` | `resolved = tool_id` | `test_only_a_confined_call_to_an_unregistered_id_is_refused_before_the_gate` |
| RX-3 | `src/probos/cognitive/agentic_dispatch.py` | `CONFINED_CALL_ANSWERED, UNREGISTERED_TOOL_REFUSAL,` | `CONFINED_CALL_ANSWERED,` | `test_an_unregistered_tool_is_refused_not_filed_and_never_counts_toward_a_fault` |
| RX-4 | `src/probos/cognitive/agentic_dispatch.py` | `if confinement is not None and self._registry is not None and type(tool_id) is str:` | `if self._registry is not None and type(tool_id) is str:` | `test_only_a_confined_call_to_an_unregistered_id_is_refused_before_the_gate` |
| RX-5 | `src/probos/cognitive/agentic_dispatch.py` | `UNREGISTERED_TOOL_REFUSAL,  # AD-1356 S1.1` | `# AD-1356 S1.1` | `test_only_a_confined_call_to_an_unregistered_id_is_refused_before_the_gate` |
| RX-6 | `src/probos/fault_report.py` | `if is_caller_input_error(tool, raw_text):  # AD-1356 S1.2: the call's input was wrong, not the tool` | `if False:` | `test_caller_input_errors_in_three_runs_file_no_fault_on_the_observer_path` |
| RX-7 | `src/probos/fault_detection.py` | `if is_caller_input_error(canonical, raw):` | `if False:` | `test_a_marked_error_is_neither_fault_nor_success_evidence_in_a_batch` |
| RX-8 | `src/probos/tools/protocol.py` | `return len(error) > len(prefix) and error.startswith(prefix)` | `return error.startswith(prefix)` | `test_only_a_tools_own_mark_is_a_caller_input_error` |
| RX-9 | `src/probos/tools/protocol.py` | `if type(tool_id) is not str or not tool_id or type(error) is not str:` | `if type(tool_id) is not str or type(error) is not str:` | `test_only_a_tools_own_mark_is_a_caller_input_error` |
| RX-10 | `src/probos/tools/publish_finding_tool.py` | `error="publish_finding_failed:write_failed", duration_ms=(time.monotonic() - started) * 1000.0,` | `error="publish_finding_invalid:write_failed", duration_ms=(time.monotonic() - started) * 1000.0,` | `test_a_failed_records_write_is_reported_not_swallowed` |
| RX-11 | `src/probos/agent_work_runner.py` | `if _recovery_read(tool_id, params, roots):` | `if False:` | `test_a_read_of_the_agents_own_workspace_result_runs_without_approval_and_another_agents_is_refused_by_the_tool` |
| RX-12 | `src/probos/agent_work_runner.py` | `path.is_absolute() and ".." not in path.parts and is_workspace_result_path(path)` | `path.is_absolute() and is_workspace_result_path(path)` | `test_only_an_absolute_result_path_under_a_workspace_root_is_a_recovery_read` |
| RX-13 | `src/probos/agent_work_runner.py` | `and any(path.is_relative_to(root) for root in roots)` | `and True` | `test_only_an_absolute_result_path_under_a_workspace_root_is_a_recovery_read` |
| RX-14 | `src/probos/agent_work_runner.py` | `if isinstance(result, WorkspaceSliceToolResult):  # AD-1356 S1.3: a read of a workspace result is not kept` | `if False:` | `test_a_read_that_climbs_out_of_the_result_directory_is_filed_not_run` |
| RX-15 | `src/probos/agent_work_runner.py` | `raw = params.get("path") if tool_id == "read_file" and type(params) is dict else None` | `raw = params.get("path") if type(params) is dict else None` | `test_only_an_absolute_result_path_under_a_workspace_root_is_a_recovery_read` |

**Campaign of record.** After an unmutated baseline of N1-1 to N3-1 and the three edited test files, run each row against the file that holds its killer. Record the base tree and the sha256 of every mutated `src` file.

## 11. Recorded limits

- **L1.** A call with no confinement to an unregistered id keeps the registry's not-found result (#1214).
- **L2.** An executor with no registry refuses nothing as unregistered; the gate files as before.
- **L3.** A registered but disabled tool, or one not offered to the agent, is not unregistered; it goes to the gate.
- **L4.** An ambiguous name (two registered tools claim it) goes to the gate as before.
- **L5.** The refusal names `search_capabilities` whether or not the agent holds it.
- **L6.** A tool can mark its own errors, and so can whatever stands behind it: a remote MCP server (`str(exc)` of its error) or a crew agent behind a mesh intent. An error that starts with the tool's own id and `_invalid:` is skipped by fault detection. On the base, the three native tools of §1 return the mark.
- **L7.** A caller error that a tool reports without the mark (`read_file`'s "path is required") is still counted.
- **L8.** An error a tool raises reaches the detector as "Tool <name> failed: ...", which is never a mark.
- **L9.** A `read_file` path that is relative, has a `..` part, or lies outside the workspace root is filed even if it names a result directory.
- **L10.** The recovery check is lexical over `workspace_exempt_roots(runtime)`, which answers `[]` when the root does not resolve. Every read is then filed.
- **L11.** A recovery read the tool refuses returns the tool's refusal. What AD-1240 does with it in the run (its delivery stop) is unchanged.
- **L12.** Agent work that repeats or rewords another item is created as before; only an open request with the same `dedup_key` is returned (AD-1347 S1).

## 12. Verified Against Codebase (2026-11-01, on `378a6a30`; re-run on `e9140fcb`, 2026-11-02)

```
Read src/probos/cognitive/agentic_dispatch.py :280-380, :790-916, :975-994, :1495-1521, :1862-1892, :1990-2189,
  :2930-2971, :3660-3729, :4340-4407
  301-303 comment; 304-328 CONFINED_CALL_*, CONFINEMENT_*, _NEVER_RAN_REFUSALS; 331-369 ToolCallConfinement
  792-916 _invoke_reserved_body (831-841 confinement, 824-829 refuse, 813-822 strict_log); 987-989 confine_calls
  1500-1521 DispatchToolExecutor; 2130-2146 classify_tool_fault_error; 2157-2189 _without_deferred_schema_refusals
  2894-2899 registry, fault_observer_for; 4332 _defect_outcome; 4357 detect_tool_defect; 4396-4403 observe
grep -n "_resolve_tool_id" agentic_dispatch.py -> 2033 (docstring mention only)
Read src/probos/tools/executor.py :286-363, :490-606, :608-646, :788-909 (502-508 self._registry; 560-606 _resolve_tool_id)
Read src/probos/tools/registry.py :200-229, :362-491 (406-416 #1214 not found before permission)
Read src/probos/tools/protocol.py :1-110 (80-91 ToolResult; stdlib imports only)
Read src/probos/fault_report.py :1-99, :100-455, :568-983
  46-56 imports; 300-301 "stdlib-only"; 336-425 detect_tool_defect (388-401 tally); 598 publish=self.file_fault;
  706-807 file_fault; 962-983 _emit_fault
Read src/probos/fault_detection.py :1-80, :180-589 (18-24 imports; 32-35 _NOISE; 237-344 collect; 541-542 same_run)
Read src/probos/cognitive/continue_or_ask.py :215-265; src/probos/cognitive/cognitive_agent.py :150-215
Read src/probos/cognitive/repair_dispatch.py :95-154 (136-140 propose_after_occurrences)
Read src/probos/tools/event_log_query_tool.py :108-162, :520-669; oracle_query_tool.py :240-261, :340-380
Read src/probos/tools/publish_finding_tool.py :405-429, :685-709, :850-878; grep "^class \|    def " -> 21 defs
Read src/probos/cognitive/swe_harness/agentic_loop.py :1245-1261, :2140-2159, :2785-2854
Read src/probos/cognitive/swe_harness/tool_call.py :64-70, :678-734, :829-869 (863-868 error text = str(error))
Read src/probos/agent_work_runner.py :1-112, :112-291, :540-684
Read src/probos/cognitive/swe_harness/tools.py :245-327, :379-499, :1367-1415 (1380-1385 read_perms)
Read src/probos/execution/workspace_results.py :178-207, :264-292, :410-436 (27 RESULT_DIRECTORY; 428-430)
grep "def bind_agent" -A 30 src/probos/execution/workspace_result_store.py -> 953-978
Read src/probos/execution/workspace.py :91-103, :327-331, :349-360; src/probos/execution/__init__.py (whole)
Read src/probos/security/file_access.py :388-411; grep "^from \|^import " workspace_results.py, file_access.py (stdlib)
Read src/probos/cognitive/swe_harness/result_offload.py :60-99, :250-416
Read src/probos/agent_work.py :1-52, :62-71, :97-240, :277-618; src/probos/agent_work_tags.py :56-75, :390-478
Read src/probos/workforce.py :11240-11273; grep "async def list_agent_work" -A 28 -> 11181-11208
Read src/probos/ward_room_pipeline.py :280-360; src/probos/cognitive/decomposer.py :48-70
Read src/probos/execution/effect_broker.py :40-89; grep "query_governed" substrate/event_log.py -> 915
grep "fault_observer" src/probos/runtime.py -> none; grep "^    execution: " config.py -> 3925
Read scripts/check_architecture_principles.py :44-83; scripts/gen_ad_ledger.py :120-142
Read docs/development/architecture-baseline.yaml :978-991; grep agent_work -> 341 (AgentWorkingMemory) only
Read PROGRESS.md :1-4; grep "^### BF-947 -- |^### Explicit delegation models" DECISIONS.md -> 1244, 1254
Read tests: test_ad1347_s3_execution.py :1-419, :550-590, :715-746; test_bf947_multi_call_agent_work.py :1-70, :222-301;
  test_bf947_confinement_answer.py (whole); test_ad1156_plan_execute_mode.py :518-549;
  test_ad1347_s1_agent_work.py :100-229, :288-307, :472-496; test_ad1347_s2_chain_tags.py :205-244, :290-319;
  test_ad1240_workspace_results.py :60-118, :233-297; test_ad1240_tool_result_delivery.py :670-727, :870-909;
  test_ad1140_publish_finding.py :798-849; test_ad1191_delegation_wire.py :462-475;
  test_ad1346_admission_service.py :608-653; test_ad1320_agentic_budget_awareness.py :650-665
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py -> CEILING AD-1356 (issue titles), NEXT AD-1357
gh issue list --state all --search "AD-1356 in:title" -> #1722 only
```

```
Live board, 2026-11-02 (orchestrator; read-only copy of `%LOCALAPPDATA%\ProbOS\data\workforce.db` taken about 07:35 UTC;
  `logs/ad1356/live-board.txt`, `logs/ad1356/unread-rows.txt`, gitignored):
  43 agent-work rows, all kind=self and dedup_key=None; 26 with tool_id=None and 17 with a tool_id; 28 done, 15 cancelled
  139a7a66, 59d2f34b, ac0f2ca5: the unread_counts items; tool_id=None; three titles, requesters engineering_officer x2 and builder; all cancelled
  groups with the same (requester, kind, department, tool, normalised title, assignee): 0
```

```
Re-run on main `e9140fcb`, 2026-11-02 (A4):
  logs/ad1356s1/oracle-d-on-main.txt (orchestrator, gitignored): M1's 9 pairs, P1-1, P1-3, P1-7, P1-8 failed;
    M2 14 of 14, M3 5 of 5, P4-8 and P4-9 applied, each slice on the base alone
  logs/ad1356s1/main-vs-drafting-base-src.diff (orchestrator): 378a6a30 -> e9140fcb, seven hunks in agent_work_runner.py
    and agentic_dispatch.py; under src and tests BF-947's rounds otherwise changed test_bf947_multi_call_agent_work.py only
  Read agentic_dispatch.py :296-381 (301-303 comment; 333-340 ToolCallConfinement docstring; 371-381 record_admitted),
    :826-917 (839-841 admission comment; 914-915 record_admitted), :1195-1258 (1249-1253 confined admission);
    grep "^_APPROVAL_INBOX_TOOL_IDS" -> 230 frozenset({"browser"})
  Read agent_work_runner.py :1-40 (13-23 module docstring), :112-157 (CarriedResults), :425-440 (437 terminal forget),
    :562-708 (_run 562-651; 610-612, 639-640 _forget_if_ended; 641-647 stop branch; _gate_for 669-708)
  grep "^class |^    (async )?def " agent_work_runner.py -> AgentWorkRunner 374, 15 defs
  git show 378a6a30:src/probos/agent_work_runner.py | grep "carried.forget" -> 419 (the terminal forget, on the drafting base too)
  task text on e9140fcb (diff above): "A call to another tool may be filed for approval instead of running; ... no call you
    filed on it ..."
```

## Absence Verified (2026-11-01; A1 and A2 restated on `e9140fcb`, 2026-11-02)

```
A1 CLAIM: on the base, no src module builds a ToolResult error that starts with its tool id and "_invalid:" except
          event_log_query_tool.py, oracle_query_tool.py and publish_finding_tool.py.
   RUN:   Grep "_invalid:" over src (re-run on e9140fcb, 2026-11-02: 48 lines in 11 files)
   FOUND: ToolResult errors: event_log_query_tool.py:565, oracle_query_tool.py:377, publish_finding_tool.py:876;
          review_requests_tool.py:63 ("review_requests: context_invalid: ..."; it starts "review_requests: ", not
          the mark); not ToolResult errors: economic_calibration.py :446 :458 :549 :573 :617 :634 (ValueError),
          substrate/event_log.py (30 lines; the file names no ToolResult), startup/federation_telemetry.py:70,
          tools/delegation_budget.py:99, cognitive/verifier_independence.py:106 (ValueError); neither an error nor a
          raise: federation/envelope.py:539, :889, :992 (an attribute ``self._invalid``) and
          cognitive/crew_executor.py:2819, :2876 (a parameter ``dependency_input_invalid``)
   HOLDS: yes
A2 CLAIM: in src, ToolDefect is constructed only at fault_report.py:410 and fault_detection.py:296; FaultReportStore.file_fault
          is reached only from continue_or_ask.py:249 and the observer's publish (fault_report.py:598 -> fault_detection.py:569).
   RUN:   Grep "ToolDefect\(|FAULT_REPORTED|\.file_fault\b|\b_publish\(" over src (re-run on e9140fcb, 2026-11-02: 20 lines)
   FOUND: ToolDefect( fault_detection.py:296, fault_report.py:410; .file_fault continue_or_ask.py:249, fault_report.py:598;
          self._publish( fault_detection.py:569 (the other _publish hits are other classes: crew_finalizer.py:3034, :3650,
          publish_finding_tool.py:443, :635, economic_judgment_organ.py:767, :867, :901, crew_session_live.py:440);
          FAULT_REPORTED: fault_report.py:777, :801 (emits), :222 (a docstring), events.py:244, event_persistence.py:250,
          repair_dispatch.py:3, :100
   HOLDS: yes
A3 CLAIM: in src, detect_tool_defect is called only at fault_report.py:455, fault_detection.py:266 and agentic_dispatch.py:4357,
          and resolve_tool_defect only at cognitive_agent.py:197 and continue_or_ask.py:782.
   RUN:   Grep "detect_tool_defect\(|resolve_tool_defect\(" over src
   FOUND: those five, plus the definitions fault_report.py:336, :428
   HOLDS: yes
A5 CLAIM: no file outside logs/ and prompts/ but publish_finding_tool.py, test_ad1140_publish_finding.py and
          test_ad1191_delegation_wire.py contains publish_finding_invalid:author, publish_finding_invalid:write_failed,
          _invalid("author" or _invalid("write_failed".
   RUN:   Grep "publish_finding_invalid:(author|write_failed)|_invalid\(\"(author|write_failed)\"", glob !{logs,prompts}/**
   FOUND: publish_finding_tool.py:424, :706; test_ad1140_publish_finding.py:809, :819, :822, :835, :848;
          test_ad1191_delegation_wire.py:471
   HOLDS: yes
A6 CLAIM: no .py, .ts or .tsx file on the base defines or names UNREGISTERED_TOOL_REFUSAL, CALLER_INPUT_ERROR_MARK,
          is_caller_input_error, DEDUP_DONE_WINDOW_SECONDS or publish_finding_failed, or the identifiers _recovery_read or
          _same_work.
   RUN:   Grep "UNREGISTERED_TOOL_REFUSAL|CALLER_INPUT_ERROR_MARK|is_caller_input_error|_recovery_read|_same_work|
          DEDUP_DONE_WINDOW_SECONDS|publish_finding_failed", glob *.{py,ts,tsx}
   FOUND: agentic_dispatch.py:3675, :3712 (_recovery_reader_full, another identifier);
          test_ad1323_continue_extension_permits.py:71 (..._same_work_item_refused, another identifier)
   HOLDS: yes
A7 CLAIM: the confined-run tests of test_ad1347_s3_execution.py and test_bf947_multi_call_agent_work.py script calls
          only to event_log_query and hull_survey, both registered in the rig.
   RUN:   Grep "_call\(\"[a-z_]+\"" -o in those files and the two other s2/s3 files
   FOUND: event_log_query, hull_survey only; rig registers both (test_ad1347_s3_execution.py:190-191)
   HOLDS: yes
A8 CLAIM: neither AgentWorkService, AgentWorkRunner nor CarriedResults is a row of architecture-baseline.yaml;
          PublishFindingTool is a srp-size row whose payload is its triggers.
   RUN:   Grep "agent_work|...|fault_report|fault_detection" and "publish_finding_tool|PublishFindingTool" in the baseline
   FOUND: :341 probos.cognitive.agent_working_memory::AgentWorkingMemory; :984-991 PublishFindingTool (triggers lines, methods)
   HOLDS: yes
```

**Not verified (the orchestrator measures):**
- The RR fixture:
  - `model_copy` on `SystemConfig` and `ExecutionConfig`;
  - `ProbOSRuntime.workspace_results` accepting the store;
  - forge-1 holding READ on `read_file` in an agentic run (the executor's `required`);
  - the executor's context carrying `agent_id` for `_workspace_slice_result`.
- Whether RR1's foreign item ends `done` or `failed`.
- That a run goes on to its next scripted call after a recovery read that succeeded (RR1 and RR3 rely on it).
- That production builds the AD-1240 store on the same root that `workspace_exempt_roots(runtime)` returns, and that the pointer frame gives that absolute path. If either fails, S1.3 is inert and fails safe: the read is filed.
- That `ToolRegistry.register` accepts the id `ops:hull:survey`, and that `_park_or_admit` with no approval store returns `None` (UT2).
- Head-text rules (l) to (p) live in `request-ad1346-m3e4c3.md`, which is not in the worktree.

## 13. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:**
  - No method is added to `AgentWorkService` (stays 15), `AgentWorkRunner` (15), `CarriedResults`, `_DispatchGuardMixin` or `PublishFindingTool`. `PublishFindingTool`'s srp row freezes its triggers only.
  - `_recovery_read` and `is_caller_input_error` are module functions.
  - No layer finding: `fault_report` imports `tools.protocol`, and `agent_work_runner` imports `security.file_access` and `execution.workspace_results` lazily. None of these is a ranked package.
  - No `create_task` and no database connect.
- **`check_dormant_classes.py --check`:** no new class.
- **Config:** no field. F-553 and the AD-1152 golden do not move, because AD-1152's observations run with no confinement.
- **`gen_ad_ledger.py --check`:** passes once M4 regenerates the ledger. The head is free of status keywords in its first 120 characters.
- **Collection:** three new files under `tests/`.

## 14. Prior Art and Blind Spots

- **Internal prior work:**
  - #1214: existence is checked before permission. Kept; UT2 pins it for calls with no confinement.
  - BF-754/BF-757: alias resolution. Reused (`_resolve_tool_id`).
  - AD-1205 `_NOISE`: already drops `invalid_params` in the cross-turn lane. The leak was in the same-run lane and the DM verdict.
  - AD-1240: owner-checked slices. Reused; `ReadFileTool` decides.
  - AD-1347 S1's key dedup: unchanged, the only dedup rule (§3).
- **External:**
  - The MCP tool-error guidance separates a protocol error (unknown tool, refused) from a tool execution error the model can fix by changing its call. Absorbed as the S1.1/S1.2 split ([MCP bundles guide](https://www.mcpbundles.com/guides/tool-errors), [Apollo MCP error handling](https://www.apollographql.com/docs/apollo-mcp-server/error-handling), [ruby-sdk #284](https://github.com/modelcontextprotocol/ruby-sdk/issues/284)).
  - JSON-RPC 2.0 separates -32602 invalid params from -32603 internal error ([Dart json_rpc_2 error codes](https://dart.googlesource.com/tools/+/HEAD/pkgs/json_rpc_2/lib/error_code.dart)). Adapted as a string mark, not a numeric code.
  - `docs/research/reference-projects.md` was considered as of 2026-11-01. No listed project bears on these seams; deferred.
- **Blind spots found:**
  1. `publish_finding` used the mark for two outcomes that are not caller errors.
  2. The issue's raw-path recovery rule would admit `..` paths and out-of-root result directories as ordinary reads.
  3. A kept recovery result would evict approved results from BF-947's memory.
  4. The executor's comment on a confined admission said the Captain approved the call; a recovery read is admitted with no approval (P3-6).
  5. The cited duplicates were reworded and from two requesters (live board, 2026-11-02), so no exact key catches them. S1.4 is not in S1.
  6. AD-1240 may end a run on a refused recovery read (unchanged).
  7. Limits L1 to L12.
  8. Considered, not in scope: showing an agent the board's open work at create time (two agents asked for the open list on 11-01).

## 15. Diff Reviewer: properties to verify (run the three new files, then the greps)

1. Under a confinement, and only when the executor has a registry, `_invoke_reserved_body` returns `UNREGISTERED_TOOL_REFUSAL` before the set and gate exactly when `_resolve_tool_id` returns a str that `registry.get` does not hold. With no confinement nothing changes.
2. `UNREGISTERED_TOOL_REFUSAL` is in `_NEVER_RAN_REFUSALS` and in `classify_tool_fault_error`'s `permission_denied` tuple, is not a capability gap, and names `search_capabilities`.
3. `is_caller_input_error` is applied in `detect_tool_defect` before the tally key and in `collect_tool_fault_batch` before the `ToolDefect`. The skipped result is neither fault nor success evidence. No other fault path is edited.
4. Only `publish_finding`'s `author` and `write_failed` outcomes change code; every other `publish_finding_invalid:` code is unchanged.
5. `_recovery_read` is the gate's first rule. It returns ADMIT with no claim row and no filing, keyed on the tool id and the path as §3 states. The recorder skips a `WorkspaceSliceToolResult` only.
6. `agent_work.py`, `agent_work_tags.py` and `tests/test_ad1356_s1_duplicates.py` are not in the diff.
7. Every added or rewritten docstring, comment, refusal text, agent-facing text and test docstring is true of the head, in the code's branch order.
8. No config field, `EventType`, request kind or persisted key is added.
9. UT1, IE1 to IE3, RR1 and RR3 each start from a work item and end at the run, the filing or the store.

## 16. Acceptance criteria

1. UT1: an unregistered tool id is refused with no request filed, the model is shown a text naming `search_capabilities`, and two refusals file no fault.
2. IE1 to IE3: marked errors across runs produce no `FAULT_REPORTED` and no fault on either the observer path or the DM path; two identical genuine errors still file on both.
3. RR1: a `read_file` of the agent's own workspace result runs under agent work with nothing filed. Another agent's result path is refused by the tool's owner check, and its text never reaches the model.
4. `AgentWorkService._commit` and `agent_work_tags.py` are unchanged; the live-board finding for S1.4 is recorded on #1722 as unresolved (§3).
5. Every §10 mutant is killed; G1 to G4 pass; the §13 checks pass; the broad gate's receipt is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
