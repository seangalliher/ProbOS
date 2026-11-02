# BF-947 (#1724): an agent-work item waits for each call it filed, admits each approved one once, and is given the results of calls it already made

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-01
**Status:** ready to build. **Base:** `d5f105985440c69b256c2074a5283eef204ebdb1` (origin/main at PR #1733). **Dependencies:** none. **Tier:** M1 HIGH, M2 HIGH, M3 STANDARD. **Estimated tests:** 2 new files (11 tests), 2 edited tests, 1 edited vitest case.
**BF number:** BF-947, held by the title of #1724.

**Which text describes the head.** §1 to §3 describe the base `d5f10598`; their line numbers are the base's. The head is what the pairs and new-file blocks of §7 and §8 produce, applied in order. Where any prose here differs from a REPLACE or new-file block, the block wins. Head text means every docstring, comment, log message, error string, agent-facing string and test docstring in those blocks, plus the tracker entries (§8) and the commit messages (§5).

## 1. Problem

Each item below is on the base:

1. A run files every out-of-set call into `filed` and parks only on `filed[0]` (`agent_work_runner.py:488-489`).
2. A resume admits one call: `_approved_admission` (`:177-187`) reads the single `capability_request_id`, and the gate admits that key once (`:540-545`). Fulfilled approvals of the other filed calls are never admitted.
3. `task_text` (`:133-145`) carries no earlier results. A resumed run that makes its earlier calls again finds their approvals used, so it files them again. AD-1154 folds a repeat only into a *pending* request (`capability_request.py:849`).
4. A denial cancels only on the parked request. AD-855's `_cancel` compare-and-sets on `capability_request_id` (`capability_gap_driver.py:395-399`), `_moved_on` leaves other denials (`:433-443`), and the runner's `_denial_reason` reads only the parked id (`:190-202`).
5. `task_text` has no clock.

## 2. Solution

- **M1 (`agentic_dispatch.py`):**
  - a verdict `CONFINEMENT_ANSWERED` and its refusal `CONFINED_CALL_ANSWERED`, which joins `_NEVER_RAN_REFUSALS` and the `permission_denied` class;
  - an optional `ToolCallConfinement.record`, which `_invoke_reserved_body` hands each admitted call's result once the tool has returned.
- **M2 (`capability_request.py`, `agent_work_runner.py`):**
  - a module function `requests_for_work_item(store, work_item_id)`, the requests in the store's cache linked to the item, oldest first. It is a function, not a method: the store has 15 direct methods, the srp-size limit;
  - before a run, `_cancel_or_park` reads the assignee's agent-work requests on the item. A denied one cancels the item, a pending or approved-unfulfilled one parks it again, and otherwise every fulfilled one is admissible once;
  - `CarriedResults` keeps admitted results in memory. The task text lists them with the current UTC time, and the gate answers a repeat;
  - `_denial_reason` also reads the assignee's requests.
- **M3:** the approval card's copy, the trackers and the ledger.

## 3. Decisions

- **Park:** one key, parked on each request in turn (option A).
- **Admission:** fulfilled, this item, this slot, once per request.
- **Results:** runner memory, newest 8 per item, 1,500 characters each, parameters 200, never an error result.
- **Denial:** cancels the item at its next run.
- **Clock:** `now` comes from the runner's `self._clock()`.
- **Config:** no config field. No new method on `AgentWorkRunner` or `CapabilityRequestStore`; both are at 15 direct methods and neither is baselined.

## 4. Milestones and gates

| M | Tier | Pairs | Gate |
|---|---|---|---|
| M1 | HIGH | P1-1 to P1-6, N1-1 | G1 |
| M2 | HIGH | P2-1 to P2-14, N2-1 | G2 |
| M3 | STANDARD | P3-1 to P3-5, the ledger | G3 |

**G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf947_confinement_answer.py tests/test_ad1156_plan_execute_mode.py tests/test_ad1347_s3_execution.py tests/test_ad1154_approval_inbox.py tests/test_ad1152_agentic_correlation.py -q -n 0`

**G2:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf947_multi_call_agent_work.py tests/test_bf947_confinement_answer.py tests/test_ad1347_s3_execution.py tests/test_ad1347_s3_wiring.py tests/test_ad1347_s2_chain_tags.py tests/test_ad855_block_resume.py tests/test_bf878_settled_request_resumes_the_item.py tests/test_ad1213_delegated_approvals.py tests/test_ad1346_admission_service.py -q -n 0`, then:
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_dormant_classes.py --check`

**G3:**
- `cd ui && npx vitest run src/components/capability/__tests__/CapabilityRequestCard.ad1347.test.tsx src/components/capability/__tests__/ApprovalWave.test.tsx`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`

## 5. Commit messages

- M1: `BF-947 M1: the agent-work confinement answers a repeat of an admitted call and hands admitted results to a record`
- M2: `BF-947 M2: an agent-work item waits for each call it filed, admits each approved one once, and is given the results of calls it made`
- M3: `BF-947 M3: the approval card says when the item runs again; trackers and ledger`

## 6. Tests

| Id | File | Test | Covers |
|---|---|---|---|
| MC1 | multi_call | `test_two_approved_calls_finish_the_item_in_one_resume` | Acceptance 1; M2, M4 |
| MC2 | multi_call | `test_a_resumed_run_is_given_earlier_results_and_a_repeat_is_answered_not_filed` | Acceptance 3; M3 |
| MC3 | multi_call | `test_a_denied_call_the_item_is_not_parked_on_cancels_it_at_its_next_run` | Acceptance 2 |
| MC4 | multi_call | `test_an_item_parked_before_this_fix_waits_for_its_other_filed_call` | Q1 compatibility |
| MC5 | multi_call | `test_after_a_restart_a_used_approval_is_not_admitted_again` | Acceptance 4; L1 |
| MC6 | multi_call | `test_the_task_text_states_the_current_utc_time` | Acceptance 5 |
| MC7 | multi_call | `test_another_claimant_is_not_given_the_first_claimants_results` | across agents |
| MC8 | multi_call | `test_a_denial_on_another_item_of_the_same_agent_leaves_this_one_alone` | across items |
| MC9 | multi_call | `test_the_runner_keeps_the_newest_results_without_an_error_each_cut` | M3's bounds |
| MC10 | confinement_answer | `test_an_answered_call_never_runs_and_its_refusal_is_a_never_ran_policy_outcome` | M1 |
| MC11 | confinement_answer | `test_an_admitted_result_is_handed_to_record_and_a_record_that_raises_is_logged` | M1 |

Edited:
- X2 (`test_a_call_outside_the_read_set_parks_the_item_and_an_approval_runs_it_exactly_once`) pinned "a repeat is filed". It now pins "a repeat is answered", and its denial step uses a new call. The docstring records why.
- `test_the_plan_mode_refusal_is_a_policy_outcome` gains the new member of `_NEVER_RAN_REFUSALS`.
- The vitest case of the agent-work card.

## 7. The contract

### 7.1 M1

**P1-1** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
CONFINED_CALL_NOT_FILED: str = (
    "That call needs the Captain's approval before it runs, and it could not be filed for review, so it did "
    "not run. Finish what the read-only tools allow and report what remains open."
)
CONFINEMENT_ADMIT = "admit"
CONFINEMENT_FILED = "filed"
CONFINEMENT_REFUSED = "refused"

# AD-1189 / AD-1156: refusals of calls that never ran. They say nothing about
# the tool, so they are never defect evidence.
_NEVER_RAN_REFUSALS: frozenset[str] = frozenset(
    {_DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL, CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED}
)
```
REPLACE:
```python
CONFINED_CALL_NOT_FILED: str = (
    "That call needs the Captain's approval before it runs, and it could not be filed for review, so it did "
    "not run. Finish what the read-only tools allow and report what remains open."
)
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

**P1-2** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
class ToolCallConfinement:
    """AD-1347 S3: the calls a run makes directly (``tool_ids``) and the gate every other call is put to.

    ``gate(agent_id, tool_id, params)`` answers ``CONFINEMENT_ADMIT`` (run it), ``CONFINEMENT_FILED`` (filed for the
    Captain's approval) or anything else (not filed). Enforced first in the executor's invoke, before plan mode and the
    AD-1154 browser inbox, so the decision is made at the tool call, never by reading the plan.
    """

    tool_ids: frozenset[str]
    gate: Callable[[str, Any, Any], Awaitable[str]]

    def __post_init__(self) -> None:
        if (
            type(self.tool_ids) is not frozenset or not self.tool_ids
            or any(type(tool_id) is not str or not tool_id for tool_id in self.tool_ids)
            or not callable(self.gate)
        ):
            raise ValueError("tool_call_confinement_invalid")

    async def refuse_or_admit(self, agent_id: str, tool_id: Any, params: Any) -> ToolResult | None:
        """None admits the call; otherwise the refusal it gets. Fails closed: a gate that raises refuses."""
        try:
            verdict = await self.gate(agent_id, tool_id, params)
        except Exception:
            logger.warning(
                "AD-1347: the confinement gate raised for a call from agent %s; the call is refused and did not run",
                agent_id[:12], exc_info=True,
            )
            verdict = CONFINEMENT_REFUSED
        if verdict == CONFINEMENT_ADMIT:
            return None
        return ToolResult(error=CONFINED_CALL_FILED if verdict == CONFINEMENT_FILED else CONFINED_CALL_NOT_FILED)
```
REPLACE:
```python
class ToolCallConfinement:
    """AD-1347 S3: the calls a run makes directly (``tool_ids``) and the gate every other call is put to.

    ``gate(agent_id, tool_id, params)`` answers ``CONFINEMENT_ADMIT`` (run it), ``CONFINEMENT_FILED`` (filed for the
    Captain's approval), ``CONFINEMENT_ANSWERED`` (BF-947: refused with ``CONFINED_CALL_ANSWERED``) or anything else
    (not filed). Enforced first in the executor's invoke, before plan mode and the AD-1154 browser inbox, so the
    decision is made at the tool call, never by reading the plan. BF-947: ``record``, when set, is handed the result of
    each admitted call that returns from the tool (``record_admitted``).
    """

    tool_ids: frozenset[str]
    gate: Callable[[str, Any, Any], Awaitable[str]]
    record: Callable[[str, Any, Any, ToolResult], None] | None = None

    def __post_init__(self) -> None:
        if (
            type(self.tool_ids) is not frozenset or not self.tool_ids
            or any(type(tool_id) is not str or not tool_id for tool_id in self.tool_ids)
            or not callable(self.gate)
            or (self.record is not None and not callable(self.record))
        ):
            raise ValueError("tool_call_confinement_invalid")

    async def refuse_or_admit(self, agent_id: str, tool_id: Any, params: Any) -> ToolResult | None:
        """None admits the call; otherwise the refusal it gets. Fails closed: a gate that raises refuses."""
        try:
            verdict = await self.gate(agent_id, tool_id, params)
        except Exception:
            logger.warning(
                "AD-1347: the confinement gate raised for a call from agent %s; the call is refused and did not run",
                agent_id[:12], exc_info=True,
            )
            verdict = CONFINEMENT_REFUSED
        if verdict == CONFINEMENT_ADMIT:
            return None
        if verdict == CONFINEMENT_ANSWERED:
            return ToolResult(error=CONFINED_CALL_ANSWERED)
        return ToolResult(error=CONFINED_CALL_FILED if verdict == CONFINEMENT_FILED else CONFINED_CALL_NOT_FILED)

    def record_admitted(self, agent_id: str, tool_id: Any, params: Any, result: ToolResult) -> None:
        """BF-947: hand an admitted call's result to ``record`` when one is set; a ``record`` that raises is logged."""
        if self.record is None:
            return
        try:
            self.record(agent_id, tool_id, params, result)
        except Exception:
            logger.warning(
                "BF-947: the result of an admitted call from agent %s was not kept for a later run", agent_id[:12],
                exc_info=True,
            )
```

**P1-3** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
        confinement = self._confinement
        confined_admission = False
        if confinement is not None and tool_id not in confinement.tool_ids:
            refusal = await confinement.refuse_or_admit(agent_id, tool_id, params)
```
REPLACE:
```python
        confinement = self._confinement
        confined_admission = False
        admitted_params = params  # BF-947: what the gate was asked, for record_admitted
        if confinement is not None and tool_id not in confinement.tool_ids:
            refusal = await confinement.refuse_or_admit(agent_id, tool_id, params)
```

**P1-4** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
        if restricted and result.error is None:
            result = replace(result, output=_bound_browser_output(result.output))
        if dispositions and result.error is None:
            return replace(
                result,
                output=_with_disposition(result.output, " ".join(dispositions)),
            )
        return result
```
REPLACE:
```python
        if restricted and result.error is None:
            result = replace(result, output=_bound_browser_output(result.output))
        if dispositions and result.error is None:
            result = replace(
                result,
                output=_with_disposition(result.output, " ".join(dispositions)),
            )
        if confined_admission and confinement is not None:
            confinement.record_admitted(agent_id, tool_id, admitted_params, result)
        return result
```

**P1-5** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
            _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL,
            CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED,  # AD-1347 S3
            "consensus_blocked", "requires_confirmation",
```
REPLACE:
```python
            _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL,
            CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED, CONFINED_CALL_ANSWERED,  # AD-1347 S3, BF-947
            "consensus_blocked", "requires_confirmation",
```

**P1-6** `tests/test_ad1156_plan_execute_mode.py`

SEARCH:
```python
    # AD-1347 S3: a confined call that was filed or refused never ran either.
    assert never_ran == {
        _REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL,
        agentic_dispatch.CONFINED_CALL_FILED, agentic_dispatch.CONFINED_CALL_NOT_FILED,
    }
```
REPLACE:
```python
    # AD-1347 S3: a confined call that was filed or refused never ran either; BF-947: nor one the gate answered.
    assert never_ran == {
        _REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL,
        agentic_dispatch.CONFINED_CALL_FILED, agentic_dispatch.CONFINED_CALL_NOT_FILED,
        agentic_dispatch.CONFINED_CALL_ANSWERED,
    }
```

**N1-1** New file `tests/test_bf947_confinement_answer.py`:
```python
"""BF-947 (#1724) M1: the confinement's answered verdict and its record of admitted results.

The real ``ToolCallConfinement``; the gates and the records are plain functions. On the base this file fails at import
(``CONFINED_CALL_ANSWERED``).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from probos.cognitive import agentic_dispatch
from probos.cognitive.agentic_dispatch import (
    CONFINED_CALL_ANSWERED,
    CONFINEMENT_ADMIT,
    CONFINEMENT_ANSWERED,
    ToolCallConfinement,
    classify_tool_fault_error,
)
from probos.cognitive.decomposer import is_capability_gap
from probos.tools.protocol import ToolResult

READ_SET = frozenset({"event_log_query"})


async def _answered(agent_id: str, tool_id: Any, params: Any) -> str:
    return CONFINEMENT_ANSWERED


async def _admit(agent_id: str, tool_id: Any, params: Any) -> str:
    return CONFINEMENT_ADMIT


# MC10
async def test_an_answered_call_never_runs_and_its_refusal_is_a_never_ran_policy_outcome() -> None:
    result = await ToolCallConfinement(READ_SET, _answered).refuse_or_admit("forge-1", "hull_survey", {})
    assert result is not None and result.error == CONFINED_CALL_ANSWERED
    assert CONFINED_CALL_ANSWERED in agentic_dispatch._NEVER_RAN_REFUSALS
    assert not is_capability_gap(CONFINED_CALL_ANSWERED)
    assert classify_tool_fault_error(CONFINED_CALL_ANSWERED) == "permission_denied"
    assert await ToolCallConfinement(READ_SET, _admit).refuse_or_admit("forge-1", "hull_survey", {}) is None


# MC11
def test_an_admitted_result_is_handed_to_record_and_a_record_that_raises_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[tuple[Any, ...]] = []
    result = ToolResult(output="Hull integrity 98 percent; survey record written.")
    ToolCallConfinement(READ_SET, _admit, record=lambda *call: seen.append(call)).record_admitted(
        "forge-1", "hull_survey", {"deck": "1"}, result,
    )
    assert seen == [("forge-1", "hull_survey", {"deck": "1"}, result)]
    ToolCallConfinement(READ_SET, _admit).record_admitted("forge-1", "hull_survey", {}, result)  # no record set

    def broken(*call: Any) -> None:
        raise RuntimeError("store down")

    with caplog.at_level(logging.WARNING):
        ToolCallConfinement(READ_SET, _admit, record=broken).record_admitted("forge-1", "hull_survey", {}, result)
    assert "was not kept for a later run" in caplog.text
    with pytest.raises(ValueError, match="tool_call_confinement_invalid"):
        ToolCallConfinement(READ_SET, _admit, record="not callable")  # type: ignore[arg-type]
```

### 7.2 M2

**P2-1** `src/probos/capability_request.py` (end of file)

SEARCH:
```python
            db = await self._connection_factory.connect(self.db_path)
            try:
                cursor = await db.execute(f"{_SELECT_REQUESTS} WHERE id = ?", (request_id,))
                row = await cursor.fetchone()
                return _row_to_request(row) if row is not None else None
            finally:
                await db.close()
        return self._cache.get(request_id)
```
REPLACE:
```python
            db = await self._connection_factory.connect(self.db_path)
            try:
                cursor = await db.execute(f"{_SELECT_REQUESTS} WHERE id = ?", (request_id,))
                row = await cursor.fetchone()
                return _row_to_request(row) if row is not None else None
            finally:
                await db.close()
        return self._cache.get(request_id)


def requests_for_work_item(store: CapabilityRequestStore, work_item_id: str) -> list[CapabilityRequest]:
    """BF-947: the requests in ``store``'s cache linked to ``work_item_id``, in any status, oldest first. No I/O."""
    return sorted(
        (req for req in store._cache.values() if req.work_item_id == work_item_id),
        key=_created_at_sort_key,
    )
```

**P2-2** `src/probos/agent_work_runner.py`

SEARCH:
```python
Every run is confined (``ToolCallConfinement``): the tools in ``AGENT_WORK_READ_TOOL_IDS`` run as usual and a call to
any other tool is filed as an AD-1154 ``action`` request instead of running. After such a run the item parks
``blocked`` on that request through AD-855's ``block_on_request``; the Captain's approval fulfils it, AD-855 resumes the
item through ``resume_agent_work``, and the next run makes that one call (its approval is consumed on a claim-once row).
A denial cancels the item (AD-855) and the report names the Captain's reason.
```
REPLACE:
```python
Every run is confined (``ToolCallConfinement``): the tools in ``AGENT_WORK_READ_TOOL_IDS`` run as usual and a call to
any other tool is put to the run's gate, which files it as an AD-1154 ``action`` request instead of running it. After
such a run the item parks ``blocked`` on the first request its gate returned, through AD-855's ``block_on_request``;
its approval fulfils it and AD-855 resumes the item through ``resume_agent_work``, and its denial cancels the item
(AD-855). BF-947: before a run, the agent-work requests the item's assignee filed on it are read, oldest first. A
denied one cancels the item; else a pending one, or an approved one not yet fulfilled, parks the item on it again; else
the gate admits each call a fulfilled request covers, once per request (a claim-once row). The run is given the results
this runner keeps of calls admitted on the item for the same agent, and the gate answers a repeat of one of those calls
without running it. The report reads a denial's reason from the request.
```

**P2-3** `src/probos/agent_work_runner.py`

SEARCH:
```python
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Final
```
REPLACE:
```python
import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
```

**P2-4** `src/probos/agent_work_runner.py`

SEARCH:
```python
from probos.capability_request import (
    AGENT_WORK_CALL_ACTION,
    AGENT_WORK_SCOPE_PREFIX,
    action_dedup_key,
    agent_work_call,
    validate_action_payload,
)
```
REPLACE:
```python
from probos.capability_request import (
    AGENT_WORK_CALL_ACTION,
    AGENT_WORK_SCOPE_PREFIX,
    action_dedup_key,
    agent_work_call,
    requests_for_work_item,
    validate_action_payload,
)
```

**P2-5** `src/probos/agent_work_runner.py`

SEARCH:
```python
#: The claim tool renders its receipt through the invocation's presentation; the runner reads the board, not the text.
_PRESENTATION: Final = ToolResultPresentation(render_complete=repr)


def agent_work_approval(request: Any) -> dict[str, Any] | None:
```
REPLACE:
```python
#: The claim tool renders its receipt through the invocation's presentation; the runner reads the board, not the text.
_PRESENTATION: Final = ToolResultPresentation(render_complete=repr)
#: BF-947: an agent-work request in these statuses is waited for (an approved one is not yet fulfilled).
_UNDECIDED: Final[frozenset[str]] = frozenset({"pending", "approved"})
#: BF-947 (M3): how many results of admitted calls the runner keeps per item, and how much of each it keeps.
CARRIED_RESULTS_MAX: Final = 8
CARRIED_RESULT_MAX_CHARS: Final = 1_500
CARRIED_PARAMS_MAX_CHARS: Final = 200


@dataclass(frozen=True)
class CarriedResult:
    """BF-947 (M3): the result of one call admitted in a run of an item, by the agent that made it."""

    agent_id: str
    key: str  # the call's ``action_dedup_key``
    tool_id: str
    params: str  # its recorded parameters as JSON, cut at ``CARRIED_PARAMS_MAX_CHARS``
    output: str  # its output as text, cut at ``CARRIED_RESULT_MAX_CHARS``


class CarriedResults:
    """BF-947 (M3): per item, the results of admitted calls that returned no error, in this process only: the newest
    ``CARRIED_RESULTS_MAX`` per item, oldest first; an entry replaces one with the same call key."""

    def __init__(self) -> None:
        self._by_item: dict[str, tuple[CarriedResult, ...]] = {}

    def for_agent(self, work_item_id: str, agent_id: str) -> tuple[CarriedResult, ...]:
        """The results kept on this item for ``agent_id``, oldest first."""
        return tuple(entry for entry in self._by_item.get(work_item_id, ()) if entry.agent_id == agent_id)

    def recorder(self, work_item_id: str) -> Callable[[str, Any, Any, Any], None]:
        """The ``ToolCallConfinement.record`` of one run of this item."""

        def record(agent_id: str, tool_id: Any, params: Any, result: Any) -> None:
            payload = approval_payload(tool_id, params, work_item_id)
            if payload is None or getattr(result, "error", None) is not None:
                return
            entry = CarriedResult(
                agent_id=agent_id,
                key=action_dedup_key(agent_id=agent_id, payload=payload, work_item_id=work_item_id),
                tool_id=payload["tool_id"],
                params=json.dumps(payload["params"], sort_keys=True, default=str)[:CARRIED_PARAMS_MAX_CHARS],
                output=str(getattr(result, "output", ""))[:CARRIED_RESULT_MAX_CHARS],
            )
            kept = tuple(old for old in self._by_item.get(work_item_id, ()) if old.key != entry.key)
            self._by_item[work_item_id] = (*kept, entry)[-CARRIED_RESULTS_MAX:]

        return record

    def forget(self, work_item_id: str) -> None:
        """Drop the results kept on an item."""
        self._by_item.pop(work_item_id, None)


def agent_work_approval(request: Any) -> dict[str, Any] | None:
```

**P2-6** `src/probos/agent_work_runner.py`

SEARCH:
```python
def task_text(item: WorkItem, *, requester: str) -> str:
    """What the run is asked: the colleague's request, its reason and its tool, and the confinement in plain words."""
    provenance = _provenance(item)
    reason = provenance.get("reason") if type(provenance.get("reason")) is str else ""
    tool = provenance.get("tool_id") if type(provenance.get("tool_id")) is str else "the read-only tools you hold"
    details = f"{item.description}\n\n" if item.description and item.description != item.title else ""
    return (
        f"Agent work {item.id}: {item.title}\n\n{details}"
        f"Asked by {requester}. Reason: {reason}. Tool named: {tool}.\n\n"
        "Read-only tools run directly. A call to any other tool is filed for the Captain's approval and does not run "
        "now; this work resumes after the Captain decides. Do the reading, then answer with what you found and the "
        "tool results you relied on. Your answer is posted where the work was asked for."
    )
```
REPLACE:
```python
def task_text(item: WorkItem, *, requester: str, now: float, carried: tuple[CarriedResult, ...] = ()) -> str:
    """What the run is asked: the colleague's request, its reason and its tool, ``now`` (an epoch time) as UTC, the
    ``carried`` results (BF-947), and the confinement in plain words."""
    provenance = _provenance(item)
    reason = provenance.get("reason") if type(provenance.get("reason")) is str else ""
    tool = provenance.get("tool_id") if type(provenance.get("tool_id")) is str else "the read-only tools you hold"
    details = f"{item.description}\n\n" if item.description and item.description != item.title else ""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    earlier = "".join(f"- {entry.tool_id} {entry.params}: {entry.output}\n" for entry in carried)
    if earlier:
        earlier = (
            "Calls of this work that were approved and already ran, with their results (each cut at "
            f"{CARRIED_RESULT_MAX_CHARS:,} characters). Do not make them again:\n{earlier}\n"
        )
    return (
        f"Agent work {item.id}: {item.title}\n\n{details}"
        f"Asked by {requester}. Reason: {reason}. Tool named: {tool}.\n\n"
        f"Current UTC time: {stamp}.\n\n"
        f"{earlier}"
        "Read-only tools run directly. A call to any other tool is filed for approval and does not run now; this work "
        "continues when no call it filed awaits a decision or its fulfilment, and ends if one of them is denied. Do "
        "the reading, then answer with what you found and the tool results you relied on. Your answer is posted where "
        "the work was asked for."
    )
```

**P2-7** `src/probos/agent_work_runner.py`

SEARCH:
```python
async def _approved_admission(requests: Any, item: WorkItem, slot_id: str) -> tuple[str, str] | None:
    """(request id, call key) of the approval this item was parked on and resumed by, or None."""
    metadata = item.metadata if type(item.metadata) is dict else {}
    request_id = metadata.get("capability_request_id")
    if type(request_id) is not str or not request_id:
        return None
    request = await requests.get(request_id)
    payload = agent_work_approval(request) if request is not None else None
    if payload is None or request.status != "fulfilled" or request.agent_id != slot_id or request.work_item_id != item.id:
        return None
    return request_id, action_dedup_key(agent_id=slot_id, payload=payload, work_item_id=item.id)


async def _denial_reason(requests: Any, item: WorkItem) -> str:
    """The Captain's reason when the request this item was parked on was denied, else "".

    Read from the request, not the item: AD-855 writes ``denial_reason`` only after the cancel this notice follows.
    """
    metadata = item.metadata if type(item.metadata) is dict else {}
    request_id = metadata.get("capability_request_id")
    if type(request_id) is not str or not request_id:
        return ""
    request = await requests.get(request_id)
    if request is None or request.status != "denied" or agent_work_approval(request) is None:
        return ""
    return str(request.decision_reason or "no reason recorded")[:MAX_REASON_CHARS]
```
REPLACE:
```python
def _linked_calls(requests: Any, work_item_id: str, slot_id: str) -> list[Any]:
    """BF-947: the agent-work call requests ``slot_id`` filed on this item, oldest first."""
    return [
        request for request in requests_for_work_item(requests, work_item_id)
        if request.agent_id == slot_id and agent_work_approval(request) is not None
    ]


def _admissions(linked: list[Any], slot_id: str, work_item_id: str) -> dict[str, list[str]]:
    """BF-947 (M2): call key -> the ids of the fulfilled requests in ``linked`` that cover it, oldest first."""
    keys: dict[str, list[str]] = {}
    for request in linked:
        payload = agent_work_approval(request)
        if request.status == "fulfilled" and payload is not None:
            key = action_dedup_key(agent_id=slot_id, payload=payload, work_item_id=work_item_id)
            keys.setdefault(key, []).append(request.id)
    return keys


async def _cancel_or_park(store: Any, parking: Any, work_item_id: str, linked: list[Any]) -> bool:
    """BF-947 (M4): True when the item is not run now. The oldest denied request in ``linked`` moves it from
    in_progress to cancelled, with that request's decision reason as ``denial_reason``; else the oldest request in
    ``linked`` that is pending, or approved and not yet fulfilled, parks it on that request through
    ``block_on_request``."""
    denied = next((request for request in linked if request.status == "denied"), None)
    if denied is not None:
        moved = await store.transition_work_item(
            work_item_id, "cancelled", source=RUN_SOURCE, expected_status="in_progress",
            metadata_patch={"denial_reason": str(denied.decision_reason or "")},
        )
        if moved is not None:
            await _close_bookings(store, work_item_id, completed=False)
        return True
    waiting = next((request for request in linked if request.status in _UNDECIDED), None)
    if waiting is None:
        return False
    await parking.block_on_request(work_item_id=work_item_id, request_id=waiting.id, reason=BLOCKED_REASON)
    return True


async def _denial_reason(requests: Any, item: WorkItem) -> str:
    """The reason recorded with a denied agent-work request of this item, else "": first the request the item was
    parked on, then (BF-947) the requests its assignee filed on it, oldest first.

    Read from the request, not the item: AD-855 writes ``denial_reason`` only after the cancel this notice follows.
    """
    metadata = item.metadata if type(item.metadata) is dict else {}
    request_id = metadata.get("capability_request_id")
    candidates: list[Any] = []
    if type(request_id) is str and request_id:
        candidates.append(await requests.get(request_id))
    if type(item.assigned_to) is str and item.assigned_to:
        candidates.extend(_linked_calls(requests, item.id, item.assigned_to))
    for request in candidates:
        if request is not None and request.status == "denied" and agent_work_approval(request) is not None:
            return str(request.decision_reason or "no reason recorded")[:MAX_REASON_CHARS]
    return ""
```

**P2-8** `src/probos/agent_work_runner.py`

SEARCH:
```python
        self._restart: set[str] = set()  # A1 (F2): starts that arrived while the item ran; made when that run ends
```
REPLACE:
```python
        self._restart: set[str] = set()  # A1 (F2): starts that arrived while the item ran; made when that run ends
        self.carried = CarriedResults()  # BF-947 (M3)
```

**P2-9** `src/probos/agent_work_runner.py`

SEARCH:
```python
            if kind == EventType.WORK_ITEM_STATUS_CHANGED.value:
                if item.status in TERMINAL_STATUSES:
                    await _close_bookings(self._store, item.id, completed=item.status == "done")
                    await self.deliver_due_notices()
```
REPLACE:
```python
            if kind == EventType.WORK_ITEM_STATUS_CHANGED.value:
                if item.status in TERMINAL_STATUSES:
                    self.carried.forget(item.id)  # BF-947
                    await _close_bookings(self._store, item.id, completed=item.status == "done")
                    await self.deliver_due_notices()
```

**P2-10** `src/probos/agent_work_runner.py`

SEARCH:
```python
        A1 (review round 1): a request's eligibility is asked again first (F5); a run that filed a call parks on it and
        one the executor parked itself stays parked (F3); only a completed run with an answer is done (F4,
        ``_record_outcome``); a start that arrived during this run is made when it ends (F2).
        """
```
REPLACE:
```python
        A1 (review round 1): a request's eligibility is asked again first (F5); a run that filed a call parks on it and
        one the executor parked itself stays parked (F3); only a completed run with an answer is done (F4,
        ``_record_outcome``); a start that arrived during this run is made when it ends (F2). BF-947: before the agent
        runs, ``_cancel_or_park`` cancels the item on a denied call or parks it on an undecided one.
        """
```

**P2-11** `src/probos/agent_work_runner.py`

SEARCH:
```python
            if not await self._begin(item):
                return
            from probos.cognitive.agentic_dispatch import ToolCallConfinement

            agent = self._agents.get(slot)
            filed: list[str] = []
            confinement = ToolCallConfinement(
                AGENT_WORK_READ_TOOL_IDS,
                self._gate_for(item.id, await _approved_admission(self._requests, item, slot), filed),
            )
            try:
                outcome = await self._executor.run(
                    agent_id=slot, instructions=str(getattr(agent, "instructions", "") or ""),
                    task_text=task_text(item, requester=self._callsign_of(record.requester)),
                    runtime=self._runtime, failure_scope=item.id,
                    work_item_id_provider=lambda: item.id, confinement=confinement,
                )
            except AgentStopped:
                if record.kind == KIND_REQUEST:
                    await self._store.unassign_work_item(item.id, reason="the claimant was stopped by the Captain")
                return
            # A1 (F5): first, so a claimant stopped (or that lost the tool) after it filed a call is released, never
            # parked; a call it filed stays on the Captain's queue, inert: AD-855 and the admission act only on an item
            # parked on that request.
```
REPLACE:
```python
            if not await self._begin(item):
                return
            linked = _linked_calls(self._requests, item.id, slot)
            if await _cancel_or_park(self._store, self._parking, item.id, linked):
                return
            from probos.cognitive.agentic_dispatch import ToolCallConfinement

            agent = self._agents.get(slot)
            filed: list[str] = []
            confinement = ToolCallConfinement(
                AGENT_WORK_READ_TOOL_IDS, self._gate_for(item.id, _admissions(linked, slot, item.id), filed),
                record=self.carried.recorder(item.id),
            )
            try:
                outcome = await self._executor.run(
                    agent_id=slot, instructions=str(getattr(agent, "instructions", "") or ""),
                    task_text=task_text(
                        item, requester=self._callsign_of(record.requester), now=self._clock(),
                        carried=self.carried.for_agent(item.id, slot),
                    ),
                    runtime=self._runtime, failure_scope=item.id,
                    work_item_id_provider=lambda: item.id, confinement=confinement,
                )
            except AgentStopped:
                if record.kind == KIND_REQUEST:
                    await self._store.unassign_work_item(item.id, reason="the claimant was stopped by the Captain")
                return
            # A1 (F5): first, so a claimant stopped (or that lost the tool) after it filed a call is released, never
            # parked; a call it filed stays on the Captain's queue: AD-855 acts only on an item parked on that request,
            # and a run admits only calls its own assignee filed (BF-947).
```

**P2-12** `src/probos/agent_work_runner.py`

SEARCH:
```python
    def _gate_for(
        self, work_item_id: str, admission: tuple[str, str] | None, filed: list[str],
    ) -> Callable[[str, Any, Any], Awaitable[str]]:
        """The run's confinement gate: admit the one call an approval on record covers, else file the call for the
        Captain's approval. Fails toward refusal: a call that cannot be recorded is not run."""
        from probos.cognitive.agentic_dispatch import CONFINEMENT_ADMIT, CONFINEMENT_FILED, CONFINEMENT_REFUSED

        async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
            payload = approval_payload(tool_id, params, work_item_id)
            if payload is None:
                return CONFINEMENT_REFUSED
            key = action_dedup_key(agent_id=agent_id, payload=payload, work_item_id=work_item_id)
            if admission is not None and key == admission[1] and await self._store.claim_work_notice(
                work_item_id, agent_id, APPROVAL_USE_PREFIX + admission[0], self._clock(),
            ):
                return CONFINEMENT_ADMIT
            if self._requests.count_pending_sync(agent_id) >= self._max_pending:
                return CONFINEMENT_REFUSED
```
REPLACE:
```python
    def _gate_for(
        self, work_item_id: str, admissions: dict[str, list[str]], filed: list[str],
    ) -> Callable[[str, Any, Any], Awaitable[str]]:
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
            key = action_dedup_key(agent_id=agent_id, payload=payload, work_item_id=work_item_id)
            if any(entry.key == key for entry in self.carried.for_agent(work_item_id, agent_id)):
                return CONFINEMENT_ANSWERED
            for request_id in admissions.get(key, ()):
                if await self._store.claim_work_notice(
                    work_item_id, agent_id, APPROVAL_USE_PREFIX + request_id, self._clock(),
                ):
                    return CONFINEMENT_ADMIT
            if self._requests.count_pending_sync(agent_id) >= self._max_pending:
                return CONFINEMENT_REFUSED
```

**P2-13** `tests/test_ad1347_s3_execution.py`

SEARCH:
```python
from probos.cognitive.agentic_dispatch import (
    CONFINED_CALL_FILED,
    CONFINED_CALL_NOT_FILED,
    ToolCallConfinement,
```
REPLACE:
```python
from probos.cognitive.agentic_dispatch import (
    CONFINED_CALL_ANSWERED,
    CONFINED_CALL_FILED,
    CONFINED_CALL_NOT_FILED,
    ToolCallConfinement,
```

**P2-14a** `tests/test_ad1347_s3_execution.py`

SEARCH:
```python
    """Acceptance 4: filed, nothing run; approved, the item resumes and the call runs once; a repeat is filed; denied,
    the item ends and the Captain's reason reaches the origin thread."""
    script = [
        _call("hull_survey", {}), _final("Waiting for the Captain."),
        _call("hull_survey", {}, "c1"), _call("hull_survey", {}, "c2"), _final("Surveyed once."),
    ]
```
REPLACE:
```python
    """Acceptance 4: filed, nothing run; approved, the item resumes and the call runs once; BF-947: a repeat in that run
    is answered and does not run (before BF-947 it was filed), and a new call is filed; denied, the item ends and the
    Captain's reason reaches the origin thread."""
    script = [
        _call("hull_survey", {}), _final("Waiting for the Captain."),
        _call("hull_survey", {}, "c1"), _call("hull_survey", {}, "c2"), _call("hull_survey", {"deck": "2"}, "c3"),
        _final("Surveyed once."),
    ]
```

**P2-14b** `tests/test_ad1347_s3_execution.py`

SEARCH:
```python
        assert approved["fulfilled"] is True
        await _pump(rig)
        again = await rig.store.get_work_item(item_id)
        assert rig.survey.calls == 1, "the approval admits the call it was asked for, once"
        assert again is not None and again.status == "blocked"
        second_id = again.metadata["capability_request_id"]
        assert second_id != first_id and (await rig.requests.get(second_id)).status == "pending"
```
REPLACE:
```python
        assert approved["fulfilled"] is True
        await _pump(rig)
        again = await rig.store.get_work_item(item_id)
        assert rig.survey.calls == 1, "the approval admits the call it was asked for, once"
        assert _seen(rig, CONFINED_CALL_ANSWERED), "BF-947: the repeat is answered, not filed"
        assert again is not None and again.status == "blocked"
        second_id = again.metadata["capability_request_id"]
        second = await rig.requests.get(second_id)
        assert second_id != first_id and second.status == "pending" and second.payload["params"] == {"deck": "2"}
```

**N2-1** New file `tests/test_bf947_multi_call_agent_work.py`:
```python
"""BF-947 (#1724): an agent-work item that files several calls waits for each, admits each approved one once, and is
given the results of the calls it already made.

Through the rig of ``tests/test_ad1347_s3_execution.py``: the real runner, ``WorkItemStore``, ``CapabilityRequestStore``,
AD-855's ``CapabilityGapDriver``, the approval route's ``decide_capability_request`` and ``WorkItemAgenticExecutor``,
driven by a scripted model. On the base this file fails at import (``CarriedResults``, ``requests_for_work_item``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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


def _restarted(rig: Any, *, clock: Callable[[], float] = time.time) -> AgentWorkRunner:
    """A new runner over the same stores, as the next start builds one: its kept results start empty."""
    runner = AgentWorkRunner(
        service=rig.service, store=rig.store, ward_room=rig.wr, tools=rig.tools, requests=rig.requests,
        parking=rig.driver, executor=WorkItemAgenticExecutor(llm_client=rig.llm), runtime=rig.runtime,
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
```

### 7.3 M3 (the HXI)

**P3-1** `ui/src/components/capability/CapabilityRequestCard.tsx`. This is a one-line SEARCH: Grep finds `resumes its item` once in this file.

SEARCH:
```tsx
  // AD-1347 S3 A2 (F18): approving a validated agent-work call resumes its item, so it is not "decision only".
```
REPLACE:
```tsx
  // AD-1347 S3 A2 (F18), BF-947: approving a validated agent-work call counts toward its item's next run, so it is not "decision only".
```

**P3-2** `ui/src/components/capability/CapabilityRequestCard.tsx`

SEARCH:
```tsx
      {agentWork && <p>Approval resumes work item {approvalDisplayText(expected.work_item_id ?? '')}. If its run makes this
        call again, with this tool and exactly these parameters, that call is admitted once, subject to the remaining
        guards; nothing runs from here.</p>}
```
REPLACE:
```tsx
      {agentWork && <p>Work item {approvalDisplayText(expected.work_item_id ?? '')} runs again when no other call its
        assignee filed for it awaits a decision or its fulfilment; if one was denied, it ends instead. If its run makes
        this call again, with this tool and exactly these parameters, that call is admitted once, subject to the
        remaining guards; nothing runs from here.</p>}
```

**P3-3** `ui/src/components/capability/__tests__/CapabilityRequestCard.ad1347.test.tsx`

SEARCH:
```tsx
  it('says an agent-work approval resumes its item and offers no standing approval; an ordinary action keeps both', () => {
    render(<CapabilityRequestCard requestId={AGENT_WORK.id} request={AGENT_WORK} />);
    expect(screen.queryByText(/does not replay the original action/)).toBeNull();
    expect(screen.getByText(/Approval resumes work item wi-agent-work-1\./)).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: 'Grant standing approval' })).toBeNull();
    cleanup();
    render(<CapabilityRequestCard requestId={ORDINARY.id} request={ORDINARY} />);
    expect(screen.getByText(/does not replay the original action/)).toBeTruthy();
    expect(screen.queryByText(/Approval resumes work item/)).toBeNull();
```
REPLACE:
```tsx
  it('says when an agent-work item runs again and offers no standing approval; an ordinary action keeps both', () => {
    render(<CapabilityRequestCard requestId={AGENT_WORK.id} request={AGENT_WORK} />);
    expect(screen.queryByText(/does not replay the original action/)).toBeNull();
    expect(screen.getByText(/Work item wi-agent-work-1 runs again when no other call its assignee filed for it awaits a decision or its fulfilment; if one was denied, it ends instead\./)).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: 'Grant standing approval' })).toBeNull();
    cleanup();
    render(<CapabilityRequestCard requestId={ORDINARY.id} request={ORDINARY} />);
    expect(screen.getByText(/does not replay the original action/)).toBeTruthy();
    expect(screen.queryByText(/runs again when no other call/)).toBeNull();
```

## 8. Tracking (M3's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` in its first 120 characters.

**Date rule:** both heads carry 2026-11-01. If M3 is committed on a later date (`git log -1 --format=%cs`), the Builder puts that date in both heads.

**P3-4** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-947 (2026-11-01), #1724 -- an agent-work item waits for each call it filed, and each approval admits its call once.** A run filed every call outside the read set and parked on the first; a resume admitted only that call and started the run from scratch, so a resumed run that made those calls again could run only one of them and filed the rest again, and a denial of any call but the parked one changed nothing. Before a run, the runner now reads the agent-work requests the item's assignee filed on it, oldest first: a denied one cancels the item, a pending one or an approved one not yet fulfilled parks it on that request again, and otherwise each fulfilled one admits its call once. The runner keeps, in its own memory, the result of each admitted call that returned no error (the newest 8 per item, each cut at 1,500 characters). The next run of the item by the same agent lists them in its task text, and the confinement answers a repeat of one with `CONFINED_CALL_ANSWERED`, a never-ran refusal, instead of filing it. A restart forgets them. The task text states the current UTC time, and the approval card says when the item runs again. `capability_request_id` keeps its one-request shape, and `capability_gap_driver.py` is unchanged. The contract is `prompts/bf-947-multi-call-agent-work.md`.

```

**P3-5** `DECISIONS.md`

SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### BF-947 -- An agent-work item waits for each call it filed, and each approval admits its call once (2026-11-01, #1724)

- *Scope.* `capability_request.py` (`requests_for_work_item`), `cognitive/agentic_dispatch.py` (`ToolCallConfinement`: `CONFINEMENT_ANSWERED`, `record`), `agent_work_runner.py`, the approval card's copy, tests. Contract `prompts/bf-947-multi-call-agent-work.md`.
- *Park.* The item stays parked on one request (`capability_request_id`). Before a run, the runner reads the agent-work requests its assignee filed on the item, oldest first: a denied one cancels the item, and a pending one, or an approved one not yet fulfilled, parks it on that request again.
- *Admission.* Each fulfilled one of those requests admits its call once (the claim-once row `approval_use:<request id>`).
- *Results.* The runner keeps, in memory, the result of each admitted call that returned no error: the newest 8 per item, 1,500 characters of output and 200 of parameters each, by agent. The next run's task text lists them, and the gate answers a repeat with `CONFINED_CALL_ANSWERED`, a never-ran refusal. The task text states the current UTC time.
- *Rejected.* A list of request ids under a new key with a changed AD-855 driver, which every parked kind shares; one request for all of a run's calls; results in the item's metadata, which the store's `WORK_ITEM_UPDATED` event carries; results by reference in the AttachmentStore (considered, deferred); telling the agent of a denial and continuing.
- *Residual.* A restart forgets the kept results. A denial of a request the item is not parked on acts at the item's next run. Recorded limits L1 to L11 of the contract.
- *Reversal.* Revert the three commits. The requests filed stay in the inbox, and AD-855 acts on the parked one as before.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them.

**Not updated:**
- `docs/development/roadmap.md`: its Bug Tracker is for BFs filed and not fixed.
- No D numbers: the BF entries carry none (BF-941, `DECISIONS.md:904`).

**Merge note:** the unmerged AD-1346 M3e4c3c branch inserts at the same two anchors. Resolve mechanically, keeping both entries.

## 9. What this does NOT change

- The behaviour of `capability_gap_driver.py`: it is not edited.
- Every reader of `capability_request_id` (§10).
- AD-1154's dedup, `file_action_request`, `decide`, the approval route, and the HXI payload decoder.
- The read set `AGENT_WORK_READ_TOOL_IDS`.
- The behaviour of every executor that has no confinement. P1-4 replaces `return replace(...)` with an assignment followed by `return result`, which is behaviour-equal.
- `SystemConfig`, `EventType`, the persisted schema and request kinds.
- The AD-1356 S1 code paths (§13).

## 10. Mutation rows (one campaign of record on M2's head, plus BM-21 by hand on M3's)

Line cells hold the source line without its leading indentation.

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| BM-1 | `src/probos/agent_work_runner.py` | `if request.status == "fulfilled" and payload is not None:` | `if request.status == "fulfilled" and payload is not None and not keys:` | `test_two_approved_calls_finish_the_item_in_one_resume` |
| BM-2 | `src/probos/agent_work_runner.py` | `if any(entry.key == key for entry in self.carried.for_agent(work_item_id, agent_id)):` | `if False:` | `test_a_resumed_run_is_given_earlier_results_and_a_repeat_is_answered_not_filed` |
| BM-3 | `src/probos/agent_work_runner.py` | `f"{earlier}"` | `""` | `test_a_resumed_run_is_given_earlier_results_and_a_repeat_is_answered_not_filed` |
| BM-4 | `src/probos/agent_work_runner.py` | `denied = next((request for request in linked if request.status == "denied"), None)` | `denied = None` | `test_a_denied_call_the_item_is_not_parked_on_cancels_it_at_its_next_run` |
| BM-5 | `src/probos/agent_work_runner.py` | `waiting = next((request for request in linked if request.status in _UNDECIDED), None)` | `waiting = None` | `test_two_approved_calls_finish_the_item_in_one_resume` |
| BM-6 | `src/probos/agent_work_runner.py` | `work_item_id, agent_id, APPROVAL_USE_PREFIX + request_id, self._clock(),` | `work_item_id, agent_id, APPROVAL_USE_PREFIX + request_id + str(self._clock()), self._clock(),` | `test_after_a_restart_a_used_approval_is_not_admitted_again` |
| BM-7 | `src/probos/agent_work_runner.py` | `return tuple(entry for entry in self._by_item.get(work_item_id, ()) if entry.agent_id == agent_id)` | `return tuple(self._by_item.get(work_item_id, ()))` | `test_the_runner_keeps_the_newest_results_without_an_error_each_cut` |
| BM-8 | `src/probos/agent_work_runner.py` | `self._by_item.pop(work_item_id, None)` | `self._by_item.get(work_item_id)` | `test_the_runner_keeps_the_newest_results_without_an_error_each_cut` |
| BM-9 | `src/probos/cognitive/agentic_dispatch.py` | `confinement.record_admitted(agent_id, tool_id, admitted_params, result)` | `pass` | `test_a_resumed_run_is_given_earlier_results_and_a_repeat_is_answered_not_filed` |
| BM-10 | `src/probos/cognitive/agentic_dispatch.py` | `return ToolResult(error=CONFINED_CALL_ANSWERED)` | `return None` | `test_an_answered_call_never_runs_and_its_refusal_is_a_never_ran_policy_outcome` |
| BM-11 | `src/probos/cognitive/agentic_dispatch.py` | `if self.record is None:` | `if self.record is not None:` | `test_an_admitted_result_is_handed_to_record_and_a_record_that_raises_is_logged` |
| BM-12 | `src/probos/agent_work_runner.py` | `f"Current UTC time: {stamp}.\n\n"` | `""` | `test_the_task_text_states_the_current_utc_time` |
| BM-13 | `src/probos/agent_work_runner.py` | `candidates.extend(_linked_calls(requests, item.id, item.assigned_to))` | `candidates.extend(())` | `test_a_denied_call_the_item_is_not_parked_on_cancels_it_at_its_next_run` |
| BM-14 | `src/probos/capability_request.py` | `(req for req in store._cache.values() if req.work_item_id == work_item_id),` | `(req for req in store._cache.values() if req.work_item_id is not None),` | `test_a_denial_on_another_item_of_the_same_agent_leaves_this_one_alone` |
| BM-15 | `src/probos/cognitive/agentic_dispatch.py` | `CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED, CONFINED_CALL_ANSWERED,  # AD-1347 S3, BF-947` | `CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED,  # AD-1347 S3, BF-947` | `test_an_answered_call_never_runs_and_its_refusal_is_a_never_ran_policy_outcome` |
| BM-16 | `src/probos/cognitive/agentic_dispatch.py` | `CONFINED_CALL_ANSWERED,` | `CONFINED_CALL_NOT_FILED,` | `test_the_plan_mode_refusal_is_a_policy_outcome` |
| BM-17 | `src/probos/agent_work_runner.py` | `work_item_id, "cancelled", source=RUN_SOURCE, expected_status="in_progress",` | `work_item_id, "failed", source=RUN_SOURCE, expected_status="in_progress",` | `test_a_denied_call_the_item_is_not_parked_on_cancels_it_at_its_next_run` |
| BM-18 | `src/probos/agent_work_runner.py` | `if payload is None or getattr(result, "error", None) is not None:` | `if payload is None:` | `test_the_runner_keeps_the_newest_results_without_an_error_each_cut` |
| BM-19 | `src/probos/agent_work_runner.py` | `self._by_item[work_item_id] = (*kept, entry)[-CARRIED_RESULTS_MAX:]` | `self._by_item[work_item_id] = (*kept, entry)` | `test_the_runner_keeps_the_newest_results_without_an_error_each_cut` |
| BM-20 | `src/probos/agent_work_runner.py` | `output=str(getattr(result, "output", ""))[:CARRIED_RESULT_MAX_CHARS],` | `output=str(getattr(result, "output", "")),` | `test_the_runner_keeps_the_newest_results_without_an_error_each_cut` |
| BM-21 | `ui/src/components/capability/CapabilityRequestCard.tsx` | `{agentWork && <p>Work item {approvalDisplayText(expected.work_item_id ?? '')} runs again when no other call its` | `{agentWork && <p>Approval resumes work item {approvalDisplayText(expected.work_item_id ?? '')}. no other call its` | `says when an agent-work item runs again and offers no standing approval; an ordinary action keeps both` (vitest) |

Campaign of record: after an unmutated baseline of N1-1, N2-1, `tests/test_ad1347_s3_execution.py` and `tests/test_ad1156_plan_execute_mode.py`, run each row against the file that holds its killer. Record the base tree and the sha256 of the three mutated `src` files.

## 11. Recorded limits

- **L1.** A restart forgets the kept results. A repeat of a call made before it goes to the gate's filing step again, because its approval is used (MC5).
- **L2.** A denial of a request the item is not parked on acts at the item's next run. That run starts when the parked request is decided (AD-855 compare-and-sets on that request).
- **L3.** A cancelled item's other pending requests stay in the inbox. Deciding them changes nothing: AD-855 acts on `blocked` items, and runs do not start for terminal ones.
- **L4.** An approval whose call key never matches again (the model changes a parameter) stays `fulfilled` and unused.
- **L5.** A run that dies between filing and parking: a raise marks the item failed, and its filed requests stay in the inbox. A process exit leaves it `in_progress`, and `recover()` starts it, so `_cancel_or_park` parks it on the oldest undecided request.
- **L6.** An admitted call that returns an error, raises, or is refused after the gate admitted it (AD-1189's withheld schemas, AD-1154's credential refusal) is not kept. Its approval is used.
- **L7.** Only the newest 8 results per item are kept, each cut at 1,500 characters. A dropped one is no longer answered.
- **L8.** Two items of one agent share AD-1154's pending cap (`count_pending_sync` is per agent). Keys, admissions and kept results are per item (MC8).
- **L9.** The model may ignore the stated time and still call a tool for it; that call is filed.
- **L10.** An approved `read_file` of an earlier run's AD-1240 workspace result runs in a later run, and the tool decides whether that run may read it (AD-1356 S1.3).
- **L11.** Requests a previous claimant filed are neither admitted for, nor cancel, nor park the next claimant (MC7).

## 12. Verified Against Codebase (2026-11-01, on `d5f10598`)

```
Read src/probos/agent_work_runner.py (whole, 638 lines)
  13-17 module docstring; 27-31, 44-50 imports; 95-96 _PRESENTATION; 133-145 task_text; 177-187 _approved_admission;
  190-202 _denial_reason; 273 clock: Callable[[], float] = time.time; 289 self._clock; 292 self._restart;
  315-318 terminal branch; 441-448 _run docstring; 461-489 run, F5 comment, park on filed[0]; 530-558 _gate_for
  direct methods: :258 :297 :301 :329 :352 :377 :381 :393 :416 :424 :441 :514 :530 :560 :595 (15)
Read src/probos/cognitive/agentic_dispatch.py :295-356, :767-888, :1472-1493, :2102-2118, :2129-2151, :2160-2389
  304-321 CONFINED_CALL_* , CONFINEMENT_*, _NEVER_RAN_REFUSALS; 324-356 ToolCallConfinement
  768 _DispatchGuardMixin._invoke_reserved_body; 806-815 confinement; 834-837 browser session bound into params
  865-888 result tail; 2109 classify tuple; 2147 never-ran read; 105 logger; 27-28 dataclass, Callable imports
grep -n "_bound_browser_output(result.output)\|output=_with_disposition(result.output" agentic_dispatch.py -> 882, 886 (once each)
Read src/probos/cognitive/capability_gap_driver.py :135-443
  177 metadata_patch={"blocked_reason": reason, "capability_request_id": request_id}; 187 _resolve_if_settled
  273 only blocked items; 307-311 _resume CAS; 328 resume_agent_work; 395-399 _cancel CAS; 412 denial_reason; 433 _moved_on
Read src/probos/capability_request.py :150-181, :193-258, :484-543, :677-736, :807-981, :1140-1170
  37 from __future__ import annotations; 73 _ACTION_PAYLOAD_MAX_CHARS = 4000; 110 statuses; 155-175 agent_work_call
  484-510 action_dedup_key; 513 _created_at_sort_key; 849 dedup on a pending request only; 1154-1170 get (end of file, 1170 lines)
Read src/probos/workforce.py :181-197 (task transitions incl. in_progress->cancelled, in_progress->blocked),
  :1712-1731, :3281-3290 (projection = item.to_dict()), :10753-10851 (same-status metadata write), :11235-11248 claim_work_notice
Read src/probos/tools/protocol.py :81-85 (ToolResult output, error)
grep TOOL_INVOKED src/probos/tools -> executor.py:1186 "Neither sink receives raw errors, results or parameters."
Read src/probos/cognitive/decomposer.py :51-69 (_CAPABILITY_GAP_RE)
Read src/probos/startup/finalize.py :3499-3546 (runner built without clock; listener event types)
grep -n "SRP_MAX" scripts/check_architecture_principles.py -> 187 SRP_MAX_BODY_LINES = 500; 188 SRP_MAX_DIRECT_METHODS = 15
Read scripts/check_dormant_classes.py :8-29 (a use from a live top-level definition counts)
Read scripts/gen_ad_ledger.py :126-139 (status keywords, head window 120)
Read tests/test_ad1347_s3_execution.py :1-412, :540-819
Read tests/test_ad1156_plan_execute_mode.py :522-543
Read ui/src/components/capability/CapabilityRequestCard.tsx :134-139; __tests__/CapabilityRequestCard.ad1347.test.tsx (whole)
Read PROGRESS.md :1-3; DECISIONS.md :656-672, :1240-1247; grep -n "^### BF-94" DECISIONS.md -> 904
Read prompts/bf-941-cold-start-detector-and-session-flag.md :1287-1322, :1456-1501
grep capability_request_id src (20 hits, listed in the answer's Q1); ui (5 hits); tests (100 in 16 files)
BF ceiling: git log --all --format=%s | grep -o "BF-9[4-9][0-9]" -> BF-941 only; prompts/bf-9[4-9]*.md -> bf-941 only;
  roadmap.md BF-9[2-9][0-9] -> one AD-753 row naming BF-927 (no tracker row); gh issue view 1723 / 1724 -> BF-946 / BF-947 titles;
  gh issue list --state all --search "sort:created-desc" --limit 60 -> BF-945 #1720, BF-946 #1723, BF-947 #1724 highest
```

## Absence Verified (2026-11-01)

```
A1 CLAIM: outside agent_work_runner.py, no module under src or tests imports task_text or _approved_admission from it,
          and task_text has one call in src.
   RUN:   Grep "agent_work_runner|AgentWorkRunner\(|block_on_request|_approved_admission|_denial_reason|task_text\(" src;
          Grep "agent_work_runner import|_approved_admission|_denial_reason\(|task_text\(item|runner\._gate_for|_gate_for\(" tests
   FOUND: src imports: agent_work_tags.py:71 (AgentWorkRunner), capability_gap_driver.py:321 (resume_agent_work),
          runtime.py:170 (AgentWorkRunner), routers/capability_requests.py:17 (agent_work_approval), startup/finalize.py:3523
          (AgentWorkRunner); _approved_admission: agent_work_runner.py:177, :469; task_text: agent_work_runner.py:133 (def),
          :474 (call); other functions whose names end in task_text: continue_or_ask.py:353, :451, :530, :814;
          crew_executor.py:826, :1703, :1732, :2245, :2566; cognitive_agent.py:5301, :5568.
          tests: test_ad1347_s3_execution.py:35, :642, :846, :862, :928, :959; test_ad1347_s3_wiring.py:12;
          test_ad1156_plan_mode_containment.py and test_ad1156_plan_mode_side_effects.py define and call their own _gate_for.
   HOLDS: yes
A2 CLAIM: CapabilityRequestStore has no method that returns the requests of one work item in every status.
   RUN:   grep -n "    async def \|    def \|^class \|^def " src/probos/capability_request.py; Read :869-974, :976-981, :1142-1170
   FOUND: __init__ :686, start :709, stop :721, _refresh_cache :726, file_request :736, file_action_request :807,
          _find_pending_action :869 (pending, by key), find_action_requests_by_param :885 (by a params value),
          count_pending_sync :959 (a count), decide :976 (one id), mark_fulfilled :1065 (one id),
          require_build_consensus :1103 (one id), list_pending :1142 (pending), list_actionable :1146 (pending, or approved
          and fulfillable), get :1154 (one id)
   HOLDS: yes
A3 CLAIM: no .py file but agentic_dispatch.py, test_ad1156_plan_execute_mode.py and test_ad1347_s3_execution.py names
          _NEVER_RAN_REFUSALS.
   RUN:   Grep "_NEVER_RAN_REFUSALS" glob *.py over the worktree
   FOUND: agentic_dispatch.py:319, :2147; test_ad1156_plan_execute_mode.py:538; test_ad1347_s3_execution.py:566
   HOLDS: yes
A4 CLAIM: no file outside logs/ and prompts/ but CapabilityRequestCard.tsx and its test contains "Approval resumes work item"
          or "resumes its item".
   RUN:   Grep "Approval resumes work item|resumes its item" over the worktree, glob !{logs,prompts}/**
   FOUND: CapabilityRequestCard.tsx:56, :137; CapabilityRequestCard.ad1347.test.tsx:23, :26, :31
   HOLDS: yes
A5 CLAIM: no file outside logs/ but agent_work_runner.py and prompts/ad-1347-s2-s3-chain-wiring-execution-and-report-back.md
          contains "Read-only tools run directly", "this work resumes", "Tool named:" or "Asked by ".
   RUN:   Grep that alternation over the worktree, glob !logs/**
   FOUND: agent_work_runner.py:141, :142, :143; the AD-1347 prompt :1478, :1479, :1480
   HOLDS: yes
A6 CLAIM: no .py, .ts or .tsx file on the base contains CarriedResult, CARRIED_, requests_for_work_item, CONFINEMENT_ANSWERED,
          CONFINED_CALL_ANSWERED, record_admitted, _cancel_or_park, _linked_calls or the word _admissions.
   RUN:   Grep "CarriedResult|CARRIED_|requests_for_work_item|CONFINEMENT_ANSWERED|CONFINED_CALL_ANSWERED|record_admitted|_cancel_or_park|_linked_calls|_admissions\b" glob *.{py,ts,tsx}
   FOUND: none
   HOLDS: yes
A7 CLAIM: neither probos.agent_work_runner::AgentWorkRunner nor probos.capability_request::CapabilityRequestStore is a row
          of architecture-baseline.yaml, and each has 15 direct methods on the base.
   RUN:   grep -n "agent_work_runner\|agentic_dispatch\|capability_request\b\|capability_request.py\|capability_request::"
          docs/development/architecture-baseline.yaml; the method lists in §12 and A2
   FOUND: :350 probos.cognitive.agentic_dispatch::WorkItemAgenticExecutor only; 15 and 15
   HOLDS: yes
A8 CLAIM: _reject_reserved_metadata refuses SCAFFOLD_METADATA_FLAG and steps_control, and not denial_reason.
   RUN:   Read src/probos/workforce.py :1717-1735
   FOUND: :1728 SCAFFOLD_METADATA_FLAG, :1730 "steps_control"; the function ends at :1731
   HOLDS: yes
```

**Not verified (the orchestrator measures):**
- That `_Survey`'s output reaches `record_admitted` with "Hull integrity 98 percent" in it. The tests assert the substring only.
- That `laforge-1` can claim the released request (MC7).
- That `unassign_work_item` after an AD-855 resume returns the request to `("open", None)`.
- That vitest's whitespace normalisation lets P3-3's regex match across the JSX line break.
- That `if self.record is None:` is unique in the head file.
- That no other `src`-text scanner in the broad gate pins the edited text. Checked: `test_ad1346_admission_service.py:612-651`, `test_ad1320_agentic_budget_awareness.py:656-665`; the AD-1152 golden's blob list is never compared, at `:522-523`.

## 13. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:**
  - No method is added to `AgentWorkRunner` (stays 15) or `CapabilityRequestStore` (stays 15).
  - `CarriedResults` has 4 methods and `ToolCallConfinement` has 3.
  - `AgentWorkRunner`'s body stays under 500 lines.
  - No `create_task`, no database connect, and no new layer import: `agent_work_runner` already imports `capability_request`.
- **`check_dormant_classes.py --check`:**
  - `CarriedResults` is used in `AgentWorkRunner.__init__`. `AgentWorkRunner` is live (`startup/finalize.py:3535`), so the use counts.
  - `CarriedResult` is used in `CarriedResults.recorder`, which is live through that.
- **Config:** no field. F-553's grep and the AD-1152 golden do not move. Every AD-1152 observation runs with no confinement.
- **`gen_ad_ledger.py --check`:** passes once M3 regenerates the ledger. Both heads are free of the status keywords.
- **Collection:** two new files under `tests/`, plus the edited vitest file.

## 14. Prior Art and Blind Spots

- **Internal prior work:**
  - AD-855 and BF-878: the park is one compare-and-set key, and a request settled before the park is acted on at the park. Kept; the re-park relies on it.
  - AD-1154 DD-1 folds a repeat only into a pending request, which is why approved calls were filed again. Kept; the answered verdict covers the case.
  - AD-1347 D5: a denial cancels and the report reads the request. Extended to every filed call.
  - AD-1240's workspace: rejected for M3 (§3); see L10.
- **External:** skipped. This is ProbOS-specific approval plumbing, so `docs/research/reference-projects.md` was not examined.
- **Blind spots found:**
  1. Both classes sit at the srp-size method limit.
  2. The card's "Approval resumes work item" was already false for any filed call but the parked one.
  3. The task text's "this work resumes after the Captain decides" was loose: delegated deciders exist, and a denial ends the work.
  4. The F5 comment claimed the admission acts only on the parked request.
  5. A metadata copy of a result would be broadcast in every `WORK_ITEM_UPDATED` event.
  6. Limits L1 to L11.

## 15. Diff Reviewer: properties to verify (run both new files, then the greps)

1. `capability_request_id` is still written only by `block_on_request`, and every runner park passes one request id.
2. A call is admitted only after a successful `claim_work_notice(item, agent, "approval_use:" + id)` for a `fulfilled` request. That request must have this `work_item_id` (`requests_for_work_item`), this slot as `agent_id`, and a valid `agent_work_call` (`_linked_calls`).
3. The gate's order matches its docstring: refused when it cannot record the call; answered; admitted; refused at the pending cap; filed; refused when the filing returns no request.
4. `_cancel_or_park` runs after `_begin` and before the executor. A denied request cancels before any run; an undecided one re-parks before any run.
5. Kept results live only in `AgentWorkRunner.carried`. They are per item, read per agent, dropped on a terminal status event, and bounded at 8 entries, 1,500 characters and 200 characters.
6. `record_admitted` is called only after the tool returned, only for a confined admission, with the parameters the gate saw. A `record` that raises is logged and the result is returned unchanged.
7. With no confinement, `_invoke_reserved_body` returns what the base returned.
8. Every added or rewritten docstring, comment, refusal text, agent-facing text, card copy and test docstring is true of the head, in the code's branch order.
9. No config field, `EventType`, request kind or persisted key is added. The runner's cancel also writes AD-855's existing `denial_reason`.
10. MC4 builds the pre-fix state without the runner, and MC5 replaces the runner without reusing its memory.

## 16. Acceptance criteria

1. MC1: a two-call whole-path test with both calls approved and one resume; the item is `done` and no call is filed twice.
2. MC3: a denial of any filed call cancels the item at its next run, and the report names the reason.
3. MC2: a resumed run does not file again a call whose result it was given; the repeat is answered.
4. MC5, BM-6 killed: an approval admits its call at most once.
5. MC6: the task text contains the current UTC time.
6. Every §10 mutant is killed; G1 to G3 pass; the §13 checks pass; the broad gate's receipt is green.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 17. Corrections to this contract

**Amendment 1 (2026-11-02, the orchestrator, before the build).** Changed, against the contract as the Architect banked it:
- P2-6 (the task text): "continues when every call it filed is decided" is "continues when no call it filed awaits a decision or its fulfilment" (the runner also waits for an approved request that is not yet fulfilled, as the card's copy in P3-2 says).
- P2-7 (`_cancel_or_park`'s docstring): "the oldest pending request, or approved one not yet fulfilled" is "the oldest request in ``linked`` that is pending, or approved and not yet fulfilled" (the code takes the first of either status in the list's order).
Unchanged: every other SEARCH text and REPLACE text of §7 and §8; every count; and every record of §12 and entry of Absence Verified.
