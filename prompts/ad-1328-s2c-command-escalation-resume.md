# AD-1328 S2c -- Command escalation resume: a dispatched work item is parked on the escalated command it waits for, and the Captain's approval resumes it so the command runs exactly once

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Revised by:** the orchestrator, 2026-10-16, adding exactly the two statements the Architect dictated after S2b review round 2 (read-only consult, session `8cde36e8`): the F-111/F-113 sentence under "What This Does NOT Change" and the F-113 sentence under "Builder Watch". The S2b base tree is now `c3a649dcbfb914c4fa754959d8d6585da09a5cf0` (the reviewed tree `aae5cf56` plus a docstring and one decision-log bullet; the nine SEARCH blocks and the new file were re-checked with `install_conflict_blocks2.py --check`: 0 failures).

**Status:** Ready for build (slice S2c of AD-1328, #1530; the last slice). No new AD or BF number: AD-1328 is allocated by the issue title (ceiling AD-1341, `scripts/ad_ceiling.py`, GitHub issue titles).
**Base:** the built S2b candidate (S1 + S2a merged on `main` `2400b14c`, then S2b and its repair r1), git tree `aae5cf56d303688d58c4dec193d84f654afe71f1`. Before installing, confirm `git rev-parse HEAD^{tree}` or, if the S2b branch moved (S2b review round 2), that every SEARCH below still occurs exactly once.
**Dependencies:** S2b by public name only (`CommandEscalations`, `escalation_scope`, `command_approval_request`, `SqliteCommandApprovalStore.get`), AD-855 (`CapabilityGapDriver.block_on_request`, `on_capability_event`), AD-1154 (`CapabilityRequestStore.find_action_requests_by_param`).
**Rigor (Captain, 2026-10-16 17:59):** S2c is not the security boundary (the approval store and the exactly-once admission are, in S2b). Standard focused tests, one review round, the gate; seven mutation rows on the lines that touch the store, the service or the dispatch seam. A review finding of P2 or lower becomes a #1523 follow-up, except one that lets the policy allow a command it should forbid.
**Estimated tests:** about 16 test functions in two new files; no existing test changes.

One-line summary: a plain dispatched work item's run names the item in its tool context (`_dispatched_work_item_id`), so an escalated `run_command` is filed in the item's scope and linked to it; after the run the item is parked `blocked` on that request through AD-855; the Captain's approval fulfils it, AD-855 resumes and re-dispatches the item, and its next run issues the command again and runs it once under the approval. DM turns keep the thread scope; crew children are unchanged.

---

## Problem

S2b delivered: an escalated `run_command` is filed in the AD-1154 inbox carrying the rule and justification; after approval the agent's next identical call in the scope runs exactly once (reused within a work item); a denial sticks in its scope; the mesh keeps its refusal. #1530's acceptance also says "the approved command **then** runs exactly once". What happens to an agent whose turn ends after the escalation (the normal case: no human answers within a run):

1. **A plain dispatched work item (unattended): nothing ever runs the approved command.** Its run carries no thread and no item id: `CognitiveAgent._run_agentic_dispatch` calls `executor.run(...)` with no `thread_id` and no `extra_context` (`src/probos/cognitive/cognitive_agent.py:2347-2356`), the run sets `thread_id` to `""` (`agentic_dispatch.py:2591`, `:3830-3836`), and `escalation_scope` reads only `_crew_work_item_id` and `thread_id` (`src/probos/execution/command_escalation.py:123-130`). So the escalation is filed with scope `""` and `work_item_id=None` (`command_escalation.py:336-338`). The approval admits one run within an hour of the decision (`command_approvals.py:170-174`, `:332`) that no one will issue: the run has ended, the item is left `in_progress` (`cognitive_agent.py:2286-2289`), and AD-855 finds no linked item on FULFILLED ("nothing to resume", `capability_gap_driver.py:254-263`). Nothing parks an item on a command escalation (Absence Verified #1).
2. **A crew child:** filed in `work_item:<child>` scope and linked (S2b). Nothing parks it either, and the crew executor owns its terminal state (AD-1324 does not park crew children, `tier_floor_ask.py:151-153`). The approval is used when the child re-issues the call while it is open (a verifier or retry pass, `crew_verifier.py:1536`, `:2112`); after the child ends it grants nothing (`command_escalation.py:277-282`).
3. **A DM turn (promoted or not):** `thread:<id>` scope, one run within an hour of the decision. The Captain is both the approver and the person the agent is talking to, so the Captain's next message in the thread is the resume; this is the same resume AD-1164's unlinked `continue` ask has (a continue request for an unpromoted turn is filed with no work item, `continue_or_ask.py:543-566`, and nothing resumes it).

So the resume is part of "then runs exactly once" for path 1, and only path 1 needs new code.

## Solution

1. `escalation_scope` (S2b, one added branch): a context key `_dispatched_work_item_id`, distinct from `_crew_work_item_id`, gives the `work_item:<id>` scope (Section 1).
2. `agentic_dispatch._AGENTIC_EXTRA_CONTEXT_KEYS` admits that key (Section 2).
3. NEW `src/probos/cognitive/command_escalation_park.py`: after a dispatched run, find the command request the item waits for and park it through `CapabilityGapDriver.block_on_request` (Section 3).
4. `CognitiveAgent`: `_run_agentic_dispatch` passes the key only when the command approval route is wired; `_handle_work_item_dispatch` parks the item after its `in_progress` claim (Section 4).
5. Closure: `DECISIONS.md`, `PROGRESS.md` (Sections 5-6).

The chain after this slice, all existing code past step 3: run 1 escalates -> filed in `work_item:W`, linked to W -> run ends, item claimed `in_progress` -> parked `blocked` on R (`block_on_request`, BF-878 resolves an already settled R at once) -> Captain approves (`decide_capability_request` -> `fulfil_approval`: the scope is open because `blocked` is not an ended status, `command_approvals.py:63`; an `active` row; `mark_fulfilled`) -> FULFILLED -> `on_capability_event` -> `_resume` (compare-and-set `blocked -> in_progress` on R) -> `router.dispatch_work_item` -> run 2 issues the command -> `find(active)` -> `use` -> `approved_run`, recorded before the spawn -> runs once.

### Decisions (the orchestrator records the rankings on #1530)

**D1 -- The smallest S2c that meets "then runs exactly once".** Ranked:

| # | Option | Correctness | Safety | Compatibility | Fit | Reversibility | Validation cost |
|---|---|---|---|---|---|---|---|
| **1 (chosen)** | Plain dispatched items get the work-item scope, a post-run park and AD-855's resume; DM turns keep `thread:` (the Captain's next message resumes); crew children unchanged | Closes the one path nothing resumes; restart-safe (the park is a durable board status) | No new admission: runs still go through S2b's store; fail-closed (any fault leaves the item as today) | Byte-identical without a command policy (the key and the park are armed only by a real `CommandEscalations`) | Reuses AD-855 and BF-878, which already resume capability gaps and continue asks this way | Delete the park call and the key | Low: two files, one seam |
| 2 | O-S2b-1 as written: promoted DM turns parked too | Breaks promoted turns: `resume_promoted_turn` needs a held continuation (`turn_promotion.py:2690-2701`), held only until a segment ends without a `continue` park (`:2637-2638`); a command park finds none and closes the item `failed` (`:2955-2972`) | Same | Same | Needs a change to BF-887's continuation lifecycle in the DM path | Same | High: the DM path and BF-887 |
| 3 | Closure only (S2b as is) | Fails acceptance for plain items (Problem 1) | Same | Same | -- | -- | Lowest |
| 4 | Replay on approval | Rejected in S2b D3 (BF-830; a REST handler would run a shell) | Unsafe | -- | -- | -- | -- |

**D2 -- A denial of a parked item's command cancels the item** (AD-855 unchanged, `capability_gap_driver.py:281-284`, reason in `denial_reason`). Ranked: (a) cancel -- chosen: no code; run 1 already did the rest of its task and reported the command as waiting (`_FILED_IN_TASK_FRAME`, `command_escalation.py:58-64`), so what remains is the denied command, and "cancelled, with the Captain's reason" is the truthful board state; (b) resume on denial so the agent reports it -- rejected: a resume re-dispatches the whole task (`capability_gap_driver.py:342-381`), repeating finished work to learn one refusal, and needs a command-specific branch in AD-855; (c) leave it blocked -- rejected: strands the item.

**D3 -- Which request the item is parked on.** The oldest **pending** command request of this agent in `work_item:W` (whenever filed: a resumed run's repeat folds into it, `capability_request.py:818-828`); else, of those **filed during this run** (`created_at >= since`), the oldest fulfilled whose approval has admitted no run yet (`uses == 0`), then the oldest denied: BF-878 resumes or cancels at once (`capability_gap_driver.py:190-227`). A request settled before the run began is never parked on again, so a resumed run that does not re-issue its command ends as today instead of resuming itself in a loop. Several escalations in one run are taken one per park, oldest first.

**D4 -- DM-turn scope (O-S2b-3).** Confirmed: a DM turn, promoted or not, keeps `thread:<id>` (one run within an hour of the decision, no reuse). A turn identity would grant nothing: the turn that filed has ended before any human decides, and the next turn has a new identity, which is what the thread scope already spans. Reuse across calls inside the resumed turn would need S2b's store to admit more than one run outside a work item (`command_approvals.py:77-80`), a change at the boundary. The issue amendment's "the DM turn" reuse scope is therefore **not** delivered for DM turns (its added acceptance names only the work item, which S2b and S2c deliver); considered, deferred (#1523 follow-up). It is the stricter direction (more escalation, never less), so it is within the delegated envelope.

**D5 -- Crew children.** Unchanged: no park (their terminal state belongs to the crew executor and finalizer, the AD-1324 precedent). Considered, deferred (#1523 follow-up): a crew child that ends before its approval leaves the approval unused.

**D6 -- The denial-dominance question from S2b round 1.** Not touched: a live denial wins over a later approval of the same command for its time limit (7 days in a work item, 1 hour otherwise) and nothing undoes it (repair r1). Considered, deferred (F-112's closing note on #1523). With D2 a parked item whose command is denied is cancelled anyway.

**D7 -- The seam manifest (O-S2b-2).** S2c writes the crossing test for `TA-P0-003-approval-resume` (`docs/development/seams/p0-manifest.yaml:47-57`: approval -> fulfilment -> resumed turn -> Captain transcript; producer `CapabilityRequestStore.decide`, consumer `CapabilityGapDriver.on_capability_event`) and does **not** edit the manifest: the entry belongs to AD-1270b (slice 3 fills node ids), and `tests/test_ad1270f_impact_selector.py:718-728` pins that the live manifest contributes no crossing test today. The node id is recorded in `DECISIONS.md` for AD-1270b to adopt.

### What S2c changes in S1, S2a and S2b

One hook in S2b, by design, not a defect: `src/probos/execution/command_escalation.py`, the constant `DISPATCHED_WORK_ITEM_KEY` (after `:92`) and one branch in `escalation_scope` after the crew branch (`:125-127`). Nothing in S1 or S2a, the store, the router, the gate, the frames or the records changes. The S2b review need not reopen: the branch only adds a scope S2b's service already handles for crew children (`scope_work_item_id`, `_scope_open`, the 7-day TTL).

---

## Section 1: `src/probos/execution/command_escalation.py`

```
<<<<<<< SEARCH
_RATIONALE_CHARS: Final = 280


@dataclass(frozen=True)
class EscalationScope:
=======
_RATIONALE_CHARS: Final = 280
#: AD-1328 S2c: the tool-context key naming a plain dispatched work item
#: (``CognitiveAgent._run_agentic_dispatch``). Distinct from ``_crew_work_item_id``, which
#: means "crew child" to AD-1324 and to the crew tools.
DISPATCHED_WORK_ITEM_KEY: Final = "_dispatched_work_item_id"


@dataclass(frozen=True)
class EscalationScope:
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    """The asker and scope from the invocation context ``ToolRegistry.check_and_invoke``
    built: it sets ``agent_id`` over the caller's keys; a crew child's loop context
    carries ``_crew_work_item_id``, a conversation's ``thread_id``. None without an
    agent identity."""
=======
    """The asker and scope from the invocation context ``ToolRegistry.check_and_invoke``
    built: it sets ``agent_id`` over the caller's keys; a crew child's loop context
    carries ``_crew_work_item_id``, a plain dispatched work item's
    ``DISPATCHED_WORK_ITEM_KEY`` (S2c), a conversation's ``thread_id``. None without an
    agent identity."""
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    if type(crew_item) is str and scope_work_item_id(WORK_ITEM_SCOPE_PREFIX + crew_item) is not None:
        return EscalationScope(agent_id, WORK_ITEM_SCOPE_PREFIX + crew_item, crew_item, thread_id)
    if thread_id:
=======
    if type(crew_item) is str and scope_work_item_id(WORK_ITEM_SCOPE_PREFIX + crew_item) is not None:
        return EscalationScope(agent_id, WORK_ITEM_SCOPE_PREFIX + crew_item, crew_item, thread_id)
    dispatched = context.get(DISPATCHED_WORK_ITEM_KEY)
    if type(dispatched) is str and scope_work_item_id(WORK_ITEM_SCOPE_PREFIX + dispatched) is not None:
        return EscalationScope(agent_id, WORK_ITEM_SCOPE_PREFIX + dispatched, dispatched, thread_id)
    if thread_id:
>>>>>>> REPLACE
```

## Section 2: `src/probos/cognitive/agentic_dispatch.py`

The key must pass the run's context allowlist (`agentic_dispatch.py:2760-2772` raises `agentic_context_invalid` for any other key). A literal, not an import, so this module does not pull the command policy into its import chain; a drift guard (Tests, P2) keeps it equal to `DISPATCHED_WORK_ITEM_KEY`.

```
<<<<<<< SEARCH
        "_crew_session_id",
        "_crew_work_item_id",
        "_crew_outcome_id",
        "_parent_operation_id",
=======
        "_crew_session_id",
        "_crew_work_item_id",
        # AD-1328 S2c: probos.execution.command_escalation.DISPATCHED_WORK_ITEM_KEY
        "_dispatched_work_item_id",
        "_crew_outcome_id",
        "_parent_operation_id",
>>>>>>> REPLACE
```

## Section 3: `src/probos/cognitive/command_escalation_park.py` (new, whole file)

```python
"""AD-1328 S2c (#1530): park a dispatched work item on the command escalation it waits for.

A plain work item (``CognitiveAgent._handle_work_item_dispatch``) runs once and returns.
When its run escalated a ``run_command`` -- filed in the item's scope (``work_item:<id>``)
and linked to it by ``probos.execution.command_escalation`` -- nothing would run the
command once the Captain approves it: the agent's turn has ended. So after the run the
item is parked ``blocked`` on that request through AD-855's
``CapabilityGapDriver.block_on_request``, the one writer of the parking keys, and the
driver does the rest: FULFILLED (the approval recorded) resumes and re-dispatches the
item, whose next run issues the command again and runs it once under the approval; a
denial cancels the item. A request the Captain settled while the run was still going is
resolved as the item parks (BF-878).

Which request: the oldest still pending for this agent in this item's scope; else, of
those filed during this run, the oldest approved and fulfilled whose approval has admitted
no run yet, then the oldest denied. A request settled before this run began is never
parked on again, so a resumed run that does not re-issue its command ends as it would
have before this slice instead of resuming itself.

Never raises; a fault leaves the item as the run left it (``in_progress``). Inert unless
the command approval route is wired (``runtime.command_escalations``).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Final

from probos.execution.command_approvals import (
    COMMAND_APPROVAL_ACTION,
    COMMAND_APPROVAL_TOOL_ID,
    WORK_ITEM_SCOPE_PREFIX,
    command_approval_request,
)
from probos.execution.command_escalation import CommandEscalations

logger = logging.getLogger(__name__)

#: The ``call_site`` a tool-path escalation is filed under (``RunCommandTool`` judges with
#: ``site="run_command_tool"``); the mesh path files nothing.
TOOL_CALL_SITE: Final = "run_command_tool"
#: What the board shows while the item waits (``blocked_reason``).
COMMAND_ESCALATION_BLOCKED_REASON: Final = (
    "waiting for the Captain's decision on an escalated run_command"
)
_STATUSES: Final = ("pending", "fulfilled", "denied")


def _filed_since(req: Any, since: float) -> bool:
    created = getattr(req, "created_at", None)
    return type(created) in (int, float) and math.isfinite(created) and created >= since


async def awaited_command_request(
    runtime: Any, *, agent_id: str, work_item_id: str, since: float,
) -> str:
    """The command escalation a run of ``work_item_id`` leaves the item waiting on, or ``""``.

    Raises on a store fault; :func:`park_on_command_escalation` degrades.
    """
    requests = runtime.capability_request_store
    scope_key = WORK_ITEM_SCOPE_PREFIX + work_item_id
    fulfilled: list[str] = []
    denied: list[str] = []
    for req in requests.find_action_requests_by_param(
        "call_site", TOOL_CALL_SITE, statuses=_STATUSES,
        tool_id=COMMAND_APPROVAL_TOOL_ID, action=COMMAND_APPROVAL_ACTION,
    ):
        ask = command_approval_request(req)
        if ask is None or ask.agent_id != agent_id or ask.scope_key != scope_key:
            continue
        status = getattr(req, "status", None)
        if status == "pending":
            return ask.request_id  # oldest first: the lookup sorts by created_at
        if not _filed_since(req, since):
            continue
        if status == "fulfilled":
            fulfilled.append(ask.request_id)
        elif status == "denied":
            denied.append(ask.request_id)
    approvals = getattr(runtime, "command_approval_store", None)
    if approvals is not None:
        for request_id in fulfilled:
            row = await approvals.get(request_id)
            if row is not None and row.state == "active" and row.uses == 0:
                return request_id
    return denied[0] if denied else ""


async def park_on_command_escalation(
    runtime: Any, *, agent_id: str, work_item_id: str, since: float,
) -> str:
    """After a dispatched run, park ``work_item_id`` on the command escalation it waits for.

    ``since`` is when the run began. Returns the request id the item was parked on, or
    ``""``. Never raises.
    """
    if not isinstance(getattr(runtime, "command_escalations", None), CommandEscalations):
        return ""
    driver = getattr(runtime, "capability_gap_driver", None)
    if driver is None or getattr(runtime, "capability_request_store", None) is None:
        return ""
    if type(work_item_id) is not str or not work_item_id or type(agent_id) is not str or not agent_id:
        return ""
    try:
        request_id = await awaited_command_request(
            runtime, agent_id=agent_id, work_item_id=work_item_id, since=since,
        )
    except Exception:
        logger.warning(
            "AD-1328: could not read the command escalations of work item %s; it is not "
            "parked, so approving one will not resume it", work_item_id, exc_info=True,
        )
        return ""
    if not request_id:
        return ""
    try:
        parked = bool(await driver.block_on_request(
            work_item_id=work_item_id, request_id=request_id,
            reason=COMMAND_ESCALATION_BLOCKED_REASON,
        ))
    except Exception:
        logger.warning(
            "AD-1328: parking work item %s on command request %s raised; the request "
            "stands, but approving it will not resume the item",
            work_item_id, request_id[:12], exc_info=True,
        )
        return ""
    if not parked:
        logger.warning(
            "AD-1328: work item %s could not be parked on command request %s; the request "
            "stands, but approving it will not resume the item", work_item_id, request_id[:12],
        )
        return ""
    logger.info(
        "AD-1328: work item %s parked on command request %s; the Captain's approval resumes "
        "it and a denial cancels it", work_item_id, request_id[:12],
    )
    return request_id
```

## Section 4: `src/probos/cognitive/cognitive_agent.py`

Block A, `_run_agentic_dispatch` (`:2345-2356`). Keep the line `failure_scope=str(work_item_id or ""),` byte for byte (pinned, `tests/test_ad1248_slice_a_gaps.py:259`).

```
<<<<<<< SEARCH
        from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

        executor = WorkItemAgenticExecutor(llm_client=llm)
        outcome = await executor.run(
            agent_id=self.id,
            instructions=getattr(self, "instructions", "") or "",
            task_text=task_text,
            runtime=runtime,
            # AD-1248: a work item has no cognitive correlation id -- this path
            # never calls ``perceive()`` -- so the item's own id is the scope.
            failure_scope=str(work_item_id or ""),
        )
=======
        from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
        from probos.execution.command_escalation import (
            DISPATCHED_WORK_ITEM_KEY,
            CommandEscalations,
        )

        # AD-1328 S2c (#1530): with the command approval route wired, the tool context
        # names this work item, so an escalated run_command is filed in its scope and
        # linked to it, and ``_handle_work_item_dispatch`` can park the item on it.
        # Without the route the arguments are unchanged.
        _scope_kwargs: dict[str, Any] = {}
        if work_item_id and isinstance(
            getattr(runtime, "command_escalations", None), CommandEscalations
        ):
            _scope_kwargs["extra_context"] = {DISPATCHED_WORK_ITEM_KEY: str(work_item_id)}

        executor = WorkItemAgenticExecutor(llm_client=llm)
        outcome = await executor.run(
            agent_id=self.id,
            instructions=getattr(self, "instructions", "") or "",
            task_text=task_text,
            runtime=runtime,
            # AD-1248: a work item has no cognitive correlation id -- this path
            # never calls ``perceive()`` -- so the item's own id is the scope.
            failure_scope=str(work_item_id or ""),
            **_scope_kwargs,
        )
>>>>>>> REPLACE
```

Block B, `_handle_work_item_dispatch` (`:2218-2224`). Keep `failures_sink=_dispatch_failures,` (pinned, `test_ad1248_slice_a_gaps.py:246`).

```
<<<<<<< SEARCH
        _dispatch_failures: dict = {}
        reply_text = await self._run_agentic_dispatch(
=======
        _dispatch_failures: dict = {}
        # AD-1328 S2c (#1530): when this run began. A command escalation settled since then
        # still parks the item below (BF-878 resolves it); one settled before never does.
        _dispatch_started = time.time()
        reply_text = await self._run_agentic_dispatch(
>>>>>>> REPLACE
```

Block C, `_handle_work_item_dispatch` (`:2286-2295`), inside `if store is not None and work_item_id:`. After the claim, because the claim's transition has no expected status and `blocked -> in_progress` is legal (`workforce.py:195`), so a park before it would be undone.

```
<<<<<<< SEARCH
            try:
                await store.transition_work_item(
                    work_item_id, "in_progress", source=self.id,
                )
            except Exception:
                logger.warning(
                    "AD-839: failed to transition work_item %s to in_progress; "
                    "it remains in its prior status",
                    work_item_id, exc_info=True,
                )
=======
            try:
                await store.transition_work_item(
                    work_item_id, "in_progress", source=self.id,
                )
            except Exception:
                logger.warning(
                    "AD-839: failed to transition work_item %s to in_progress; "
                    "it remains in its prior status",
                    work_item_id, exc_info=True,
                )
            # AD-1328 S2c (#1530): park the item on the escalated command it waits for,
            # so the Captain's approval resumes it (AD-855). Never raises; inert without
            # a command policy.
            from probos.cognitive.command_escalation_park import (
                park_on_command_escalation,
            )

            await park_on_command_escalation(
                runtime, agent_id=self.id, work_item_id=str(work_item_id),
                since=_dispatch_started,
            )
>>>>>>> REPLACE
```

## Section 5: `DECISIONS.md`

```
<<<<<<< SEARCH
- *Next.* S2c resumes a parked work item on approval and closes #1530. Contract `prompts/ad-1328-s2b-command-policy-escalation.md`.
=======
- *Next.* S2c resumes a parked work item on approval and closes #1530. Contract `prompts/ad-1328-s2b-command-policy-escalation.md`.

### AD-1328 S2c -- Command escalation resume: a dispatched work item waits for the Captain's decision on an escalated command, and the approval resumes it (2026-10-16, #1530)

- *The gap.* After S2b a plain dispatched work item's run carried no thread and no item id, so its escalation was filed with no scope and no work-item link, and the approval admitted one run within an hour that nothing would issue: the run had ended and nothing re-dispatched the item.
- *Resume.* The run's tool context names the item (`_dispatched_work_item_id`, distinct from `_crew_work_item_id`, set only when the command approval route is wired), so the escalation is filed in the item's scope and linked to it. After the run and its `in_progress` claim the item is parked `blocked` on the command request it waits for through AD-855's `block_on_request`: the oldest pending, else one filed during the run that the Captain already approved and that admitted no run, then one he denied (BF-878 resolves those at once). The approval fulfils the request, AD-855 resumes and re-dispatches the item, and its next run issues the command again and runs it once (then reuses it within the item, as S2b). A request settled before a run began is never parked on again, so a resumed run does not resume itself. The re-dispatch is a fresh run of the task, as for every AD-855 resume.
- *Denial.* Cancels the parked item with the Captain's reason (AD-855 unchanged): the run that parked it had already done the rest of its task.
- *DM turns and crew children.* A DM turn, promoted or not, keeps the thread scope: the Captain's next message in the thread runs the approved command once within an hour. A promoted turn is not parked, because its resume needs a held continuation that a command park would not have. Reuse inside a DM turn is not delivered (it would need the store to admit more than one run outside a work item); crew children are not parked (the crew executor owns their end). Both considered and deferred to #1523, as is undoing a live denial (S2b repair r1).
- *Seam.* `tests/test_ad1328_s2c_resume_seam.py::test_seam_escalate_park_approve_resume_runs_once` crosses `TA-P0-003-approval-resume` (approval -> fulfilment -> resumed run -> Captain transcript); the manifest entry is left to AD-1270b slice 3.
- Contract `prompts/ad-1328-s2c-command-escalation-resume.md`.
>>>>>>> REPLACE
```

## Section 6: `PROGRESS.md`

```
<<<<<<< SEARCH
# ProbOS Progress

**AD-1328 slice S2b (2026-10-16), #1530
=======
# ProbOS Progress

**AD-1328 slice S2c (2026-10-16), #1530 -- an approved escalated command now runs: a dispatched work item waits for the Captain's decision and resumes on approval; no new AD or BF number.** A plain dispatched work item's run now names the item to `run_command`, so an escalated command is filed in the item's scope; after the run the item is parked `blocked` on that request, the Captain's approval resumes and re-dispatches it (AD-855), and its next run issues the command again and runs it exactly once under the approval; a denial cancels the item with the Captain's reason. DM turns keep the thread scope (the Captain's next message in the thread runs it once within an hour) and crew children are unchanged. With no command policy nothing changes. Closes #1530 with S2b. Contract `prompts/ad-1328-s2c-command-escalation-resume.md`.

**AD-1328 slice S2b (2026-10-16), #1530
>>>>>>> REPLACE
```

Roadmap: `docs/development/roadmap.md` has no AD-1328 or #1530 row (grep below), so nothing to update there. `docs/development/config-reference.md:539-550` is unchanged (no config field). `docs/development/open-ads-report.md` is generated; not edited.

---

## Tests

Tests only; the Builder writes them. OS-independent: every gate takes `platform="linux"` and a `which` that finds nothing; no shell starts (`asyncio.create_subprocess_shell` and `swe_tools.ProcessTree` replaced by S2b's recorder); the stores are real SQLite files in `tmp_path`. Copy helpers (tests do not import each other): from `tests/test_ad1328_s2b_seam_and_wiring.py` `_policy`, `_rule`, `_ASK_PUSH`, `_Which`, `_gate`, `_Process`, `_Tree`, `_Spawns`, `spawns`, `_RecordingRouter`, `_EventBus`, `_EventLog`, `_Runtime`, `wired`, `approvals`, `_approve`, `_status`; from `tests/test_ad856_agentic_dispatch.py` `_FakeLLMResponse`, `_ScriptedLLM`, `_text_response`, `_make_agent` (with a `run_command` tool-use response carrying `arguments={"command": "git push origin"}`).

### `tests/test_ad1328_s2c_park_and_scope.py` (new)

Requests are filed by the real filer: `CommandEscalations.resolve(gate.judge(PUSH, site="run_command_tool"), command=PUSH, context=...)` over the `wired` stores, with `build_command_escalations`.

- **P1 `test_dispatched_key_gives_the_work_item_scope`** -- table on `escalation_scope`: `{"agent_id": "a1", KEY: "W-1"}` -> `EscalationScope("a1", "work_item:W-1", "W-1", "")`; with `"thread_id": "t1"` the thread id is kept; with `_crew_work_item_id: "C1"` too, the crew item wins; bad ids (`""`, `"has space"`, `"-leading"`, `"a/b"`, 129 characters) and non-strings (`7`, `None`) fall through to `thread:t1` or `""`. Control: a crew-only context gives S2b's answer.
- **P2 `test_the_key_is_one_name_in_both_places`** -- `DISPATCHED_WORK_ITEM_KEY in agentic_dispatch._AGENTIC_EXTRA_CONTEXT_KEYS` and `!= "_crew_work_item_id"`.
- **P3 `test_run_agentic_dispatch_names_the_item_only_with_the_route`** -- parametrized; `WorkItemAgenticExecutor.run` replaced (monkeypatch on the class) by a recorder returning `WorkItemAgenticOutcome(final_text="ok")`; runtime as `test_ad856`'s `_make_runtime(enabled=True, ...)` plus `command_escalations`. A real `CommandEscalations` (built over `SimpleNamespace` stand-ins) -> `extra_context == {KEY: "wi-1"}`; `None` -> no `extra_context` keyword; a `MagicMock` -> no `extra_context` keyword. All: `failure_scope == "wi-1"`.
- **P4 `test_park_is_inert_without_the_route`** -- a pending in-scope request exists (premise); `runtime.command_escalations` `None`, then a `MagicMock`: returns `""`, the item stays `in_progress`. Control: the real route parks the same item.
- **P5 `test_park_on_the_oldest_pending_request`** -- two pending in-scope requests (two escalate rules, two commands): parks on the older; status `blocked`, metadata `capability_request_id` = it, `blocked_reason == COMMAND_ESCALATION_BLOCKED_REASON`; the router dispatched nothing.
- **P6 `test_park_ignores_other_agents_items_and_scopes`** -- pending: another agent in W; this agent in another item; this agent thread-scoped (`{"agent_id": ..., "thread_id": "t1"}`); a browser `action` request linked to W (`file_action_request` with a valid browser payload). Returns `""` (premise: each is pending). Control: one more in-scope request, and it parks on that one.
- **P7 `test_a_request_approved_during_the_run_resumes_at_once`** -- `since` before filing; `_approve` while the item is `in_progress` (premise: `fulfilled` true, the row `active`, `uses == 0`); then park: returns R; BF-878 resumed it: status `in_progress`, one re-dispatch of W.
- **P8 `test_an_approval_already_used_is_not_parked_on`** -- as P7, then `approvals.use(R, agent_id=..., scope_key=...)` once before the park: returns `""`, no re-dispatch.
- **P9 `test_a_request_settled_before_the_run_is_never_parked_on_again`** -- one approved-unused and one denied, then `since = time.time()` (premise: `since` > both `created_at`): `""`, no dispatch, status `in_progress`. Control: `since=0.0` parks on the approved one.
- **P10 `test_a_request_denied_during_the_run_cancels_the_item`** -- deny via `_approve(..., approve=False)` while `in_progress`, then park: status `cancelled`, `denial_reason` "not needed".
- **P11 `test_pending_wins_over_settled`** -- one approved-unused during the run and one pending: parks on the pending; no re-dispatch.
- **P12 `test_park_degrades_on_faults`** -- `find_action_requests_by_param` raising (patched on the instance): `""`, status `in_progress`, a WARNING naming the item. An item moved to `done` after filing (so `block_on_request` refuses): `""`.
- **P13 `test_call_site_is_the_tool_paths`** -- `command_approval_payload(...)["params"]["call_site"] == TOOL_CALL_SITE` for a verdict judged at `site="run_command_tool"`.

### `tests/test_ad1328_s2c_resume_seam.py` (new; P-S1 is the seam of record)

Real: `WorkItemStore`, `CapabilityRequestStore` (emitting through `_EventBus`), `SqliteCommandApprovalStore`, `CapabilityGapDriver` subscribed to the bus, `CommandPolicyGate` with `_ASK_PUSH`, `build_command_escalations`, `RunCommandTool` in a real `ToolRegistry` (all ranks `full`, so the premise is reached), `ToolPermissionStore`, `decide_capability_request`, a `CognitiveAgent` built as `test_ad856`'s `_make_agent`, and `_handle_work_item_dispatch` -> `_run_agentic_dispatch` -> the real `WorkItemAgenticExecutor`. Stand-ins, named: the LLM (scripted), the router (`_RecordingRouter`; the hop from router to agent is `IntentMessage(intent="work_item_dispatched", params=..., target_agent_id=agent.id)` with `work_item_id`, `title` and `description` taken from the recorded dict, as `mesh/work_item_router.py:111-117` builds them), the thread store (records `get_or_create_default_for_agent` / `append_message`), the shell (`spawns`). Runtime: the `wired` runtime plus `config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=True))`, `tool_registry`, `tool_permission_store`, `intent_bus=None`, `emit_event=None`, `chat_thread_store`, `command_approval_store`, `command_escalations`. If the dispatch run's AD-1224 hooks need more of `_EventLog` than `log`, add the methods they call (`tools/executor.py:1471-1494`); do not drop `event_log`.

- **P-S1 `test_seam_escalate_park_approve_resume_runs_once`** -- item `task`, `open`, assigned to the agent. Run 1 (LLM: `run_command`, then "Waiting for approval."): premise `run_command` was offered; exactly one pending request R, `kind == "action"`, `work_item_id == item.id`, payload `scope_key == f"work_item:{item.id}"`, `params["command"] == PUSH`; `spawns.calls == []`; status `blocked` on R with `COMMAND_ESCALATION_BLOCKED_REASON`. Approve (`_approve`): `fulfilled` true; row `active`, `uses == 0`; one re-dispatch of the item; status `in_progress`. Run 2 from the recorded dict (LLM: `run_command`, then "Pushed."): `spawns.commands == [PUSH]` (once); `list_uses(R)` kinds `["approved_run"]`; `uses == 1`; status `in_progress`, not `blocked`; still one re-dispatch after `bus.drain()` (no self-resume); the last agent message in the thread is "Pushed." with `metadata["work_item_id"] == item.id`. Kills MX-1, MX-2, MX-3, MX-6, MX-7.
- **P-S2 `test_seam_denial_cancels_the_parked_item`** -- run 1 as above; deny: status `cancelled` with `denial_reason`; no re-dispatch; no spawn; `approvals.get(R).state == "denied"`.
- **P-S3 `test_seam_without_a_route_nothing_parks`** -- controls, the same agent and script. (a) No policy (`CommandPolicyGate(CommandPolicyConfig())`, `command_escalations=None`): the command runs as before (one spawn), nothing is filed, status `in_progress`. (b) `_ASK_PUSH` with `command_escalations=None`: S2a's refusal (`verdict.refusal_message`), no spawn, nothing filed, status `in_progress`.

### Focused gate (Builder, per section; not the broad gate)

```
d:/ProbOS/.venv/Scripts/pytest.exe -n 0 -q tests/test_ad1328_s2c_park_and_scope.py tests/test_ad1328_s2c_resume_seam.py tests/test_ad1328_s2b_escalation_service.py tests/test_ad1328_s2b_seam_and_wiring.py tests/test_ad1328_s2b_tool_router_shell.py tests/test_ad856_agentic_dispatch.py tests/test_ad839_work_item_dispatch.py tests/test_ad859a_agentic_executor.py tests/test_ad1248_slice_a_gaps.py tests/test_bf773_failure_reaches_the_captain.py tests/test_ad1275_sink_side_composition.py tests/test_ad855_block_resume.py tests/test_ad1129_eventlog_query_tool.py tests/test_ad1246_long_run_promotion.py
```

The broad gate runs once for PR 2 (S2b + S2c), in the main session, with `--receipt`.

### Mutation rows (seven; the Builder runs each against the focused files above)

| ID | File | Line as built | Mutant | Killed by |
|---|---|---|---|---|
| MX-1 | `execution/command_escalation.py` | `return EscalationScope(agent_id, WORK_ITEM_SCOPE_PREFIX + dispatched, dispatched, thread_id)` | `pass` | P1, P-S1 |
| MX-2 | `cognitive/command_escalation_park.py` | `return ask.request_id  # oldest first` | `continue` | P5, P-S1 |
| MX-3 | same | `if not _filed_since(req, since):` | `if False:` | P9, P-S1 (self-resume) |
| MX-4 | same | `... and row.uses == 0:` | drop the clause | P8 |
| MX-5 | same | `... or ask.scope_key != scope_key:` | drop the clause | P6 |
| MX-6 | `cognitive/cognitive_agent.py` | `**_scope_kwargs,` | removed | P3, P-S1 |
| MX-7 | same | `await park_on_command_escalation(` call | removed | P-S1 |

### Hidden pins (grep run; none needs an edit)

- `tests/test_ad1248_slice_a_gaps.py:246-248`, `:259`, `:375`, `:379` -- source scans of `_handle_work_item_dispatch` / `_run_agentic_dispatch` (`failures_sink=_dispatch_failures`, `_body = str(_composed.render())`, `body=_body,`, `failure_scope=str(work_item_id or "")`, `and _body:`, `result=_body or reply_text or "[NO_RESPONSE]"`): every pinned line is kept verbatim.
- `tests/test_ad839_work_item_dispatch.py:96-101`, `tests/test_ad1275_sink_side_composition.py:584-585` -- `MagicMock` runtimes: `command_escalations` is a `MagicMock`, so the `isinstance` arming keeps both new paths inert; the `transitions` lists stay `[("wi-1", "in_progress", id)]`.
- `tests/test_ad856_agentic_dispatch.py:167-182`, `:351-394` -- `SimpleNamespace` runtimes without `command_escalations`; the fake `transition_work_item` takes no keywords, and S2c adds none to that call.
- `tests/test_bf773_failure_reaches_the_captain.py:141-148` -- the fake `_run_agentic_dispatch` takes `**_`.
- `tests/test_ad1328_s2b_escalation_service.py:358-408` (`test_escalation_scope`) -- no case carries the new key; the new branch follows the crew branch, so every existing answer stands.
- `tests/test_ad1129_eventlog_query_tool.py:1947-1954`, `tests/test_ad1246_long_run_promotion.py:796` -- an unknown key is still refused.
- `tests/test_ad1270f_impact_selector.py:718-728` -- the manifest is not edited (D7).

---

## What This Does NOT Change

- S2b's store, admission, frames, records, router fulfiller and denial dominance; S1 and S2a.
- AD-855's driver (resume on FULFILLED, cancel on denial), BF-878, AD-1204/BF-887 promoted-turn resume, AD-1324.
- DM turns (thread scope), crew children (no park), the mesh path (S2a refusal).
- `docs/development/seams/p0-manifest.yaml` (AD-1270b's).
- The pre-existing AD-856 defect found while drafting (below): out of scope.
- F-111 (admission after scope end; cancellation does not stop in-flight calls) and F-113 (retry of a stranded approved command escalation) stay #1523 follow-ups.

## Tracking

`DECISIONS.md` (Section 5), `PROGRESS.md` (Section 6). Roadmap: no row (checked). PR 2 (S2b + S2c) closes #1530; the closure is the orchestrator's.

## Acceptance Criteria

- An escalated `run_command` in a plain dispatched work item is filed in `work_item:<id>` and linked to the item; after the run the item is `blocked` on it; the Captain's approval re-dispatches it and the re-issued command runs exactly once, recorded as the `approved_run` before it starts (P-S1).
- A denial cancels the parked item; nothing runs (P-S2).
- No command policy, or no approval route: nothing new happens (P3, P4, P-S3).
- A resumed run that does not re-issue the command does not resume itself (P9, P-S1).
- Every existing test passes unchanged.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Builder Watch

- Block C must come **after** the `in_progress` claim; before it, the claim undoes the park.
- If the resume path ever goes through `fulfil_approval`'s None exits, or relies on a retry being offered, it must cite F-113 rather than assume the BF-722 retry is offered (S2b review round 2).
- The seam needs the real executor path to reach `RunCommandTool`; if a rank or grant filter hides `run_command`, fix the fixture (permissions, grants), never the production gate. The P-S1 premise catches it.
- Found while drafting, not for S2c: AD-856's own capability-gap park is undone the same way. `_run_agentic_dispatch` parks the item via `on_capability_gap` (`cognitive_agent.py:2360-2366`), then `_handle_work_item_dispatch` moves it `in_progress` with no expected status (`:2286-2289`; `blocked -> in_progress` is legal, `workforce.py:195`), so the gap's FULFILLED finds it not blocked (`capability_gap_driver.py:273-278`). Found by reading, not yet reproduced. For the orchestrator to file as its own BF.

---

## Prior Art and Blind Spots

Internal: AD-855 / BF-878 (park and resume through the board, the precedent reused whole); AD-1204 / BF-887 (promoted-turn resume, why D1 option 2 is rejected); AD-1324 (`tier_floor_ask.py:151-153`, crew children not parked); S2b D3 (no replay).

External (2026-10-16; two searches):

- **LangGraph `interrupt()`** ([docs](https://docs.langchain.com/oss/python/langgraph/interrupts), [reference](https://reference.langchain.com/python/langgraph/types/interrupt)): resuming re-runs the interrupted node from its start, so side effects before the interrupt repeat; the advice is to keep them idempotent or after the interrupt. **Adopted as a recorded property:** an AD-855 re-dispatch is a fresh run of the task, so the work run 1 did before the escalation runs again; S2c accepts it as every AD-855 resume does (the agent's tools stay governed). Continuing the same loop instead is option 2, rejected.
- **Goose** permission modes ([docs](https://goose-docs.ai/docs/guides/managing-tools/goose-permissions)): manual approval asks interactively before a tool runs; nothing for an unattended agent whose turn has ended. **Nothing new** (overdue row examined).

Blind spots: several escalations in one run are taken one park at a time (D3); a denial of one cancels the item while another may still be pending, and that one then grants nothing (logged by S2b); an approval that grants nothing (another policy digest, a live denial) leaves the item `blocked` until the Captain retries or acts on the board (#1523 follow-up); a wall clock stepping back between `since` and filing skips a settled request, which leaves today's behaviour; a restart while parked is safe (the board status is durable, unlike a promoted turn's continuation). Considered, deferred: SWE-agent, Aider, Cursor (overdue, not relevant to resume).

## Absence Verified (2026-10-16)

1. CLAIM: nothing parks a work item on a command escalation.
   RUN: `rg -n "block_on_request\(|_park_work_item\(|on_capability_gap\(" src/probos`
   FOUND: `capability_gap_driver.py:115` (gap), `continue_or_ask.py:567`, `:620` (continue ask), `tier_floor_ask.py:202` (tier floor), `cognitive_agent.py:2362` (denied tool). HOLDS: yes.
2. CLAIM: a plain dispatched work item's tool context has no item id.
   RUN: `rg -n "_crew_work_item_id" src/probos`
   FOUND: set only at `crew_executor.py:1930`, `crew_verifier.py:1536`, `:2112`; `_run_agentic_dispatch` passes no `extra_context` or `thread_id` (`cognitive_agent.py:2347-2356`). HOLDS: yes.
3. CLAIM: no test pins `_AGENTIC_EXTRA_CONTEXT_KEYS`' contents, and no S2b test passes the new key.
   RUN: `rg -n "_AGENTIC_EXTRA_CONTEXT_KEYS|agentic_context_invalid" tests`; `rg -n "escalation_scope|_dispatched_work_item_id" tests`
   FOUND: only refusal-of-an-unknown-key tests; `test_ad1328_s2b_escalation_service.py:402-408`. HOLDS: yes.
4. CLAIM: the board reconciler does not move `blocked` items.
   RUN: `rg -n '"blocked"' src/probos -g "*reconcil*.py"` FOUND: none. HOLDS: yes.

## Verified Against Codebase (2026-10-16)

```
git rev-parse HEAD^{tree}                          -> aae5cf56d303688d58c4dec193d84f654afe71f1
scripts/ad_ceiling.py                               -> CEILING AD-1341 (GitHub issue titles); no number allocated
grep -n "def escalation_scope" src/probos/execution/command_escalation.py
  113: def escalation_scope(context: object) -> EscalationScope | None:
  125-127: crew branch; 128-130: thread / "" scope
  92: _RATIONALE_CHARS: Final = 280
  277-282: fulfil_approval refuses an ended work item;  336-338: file_action_request(..., work_item_id=scope.work_item_id)
  58-64: _FILED_IN_TASK_FRAME
grep -n "ENDED_WORK_ITEM_STATUSES\|def approval_ttl_seconds\|def command_approval_request\|async def get\|async def use" src/probos/execution/command_approvals.py
  63, 170, 177, 417, 366;  332: expires_at = now + ttl (decision time)
grep -n "_AGENTIC_EXTRA_CONTEXT_KEYS" src/probos/cognitive/agentic_dispatch.py
  110-127 (literal set);  2760-2772 (validation);  3830-3837 (_context.update thread_id);  4053-4059 (loop.run(context=_context))
grep -n "_run_agentic_dispatch\|_handle_work_item_dispatch\|^import time\|^from typing" src/probos/cognitive/cognitive_agent.py
  14: import time;  21: from typing import TYPE_CHECKING, Any, ClassVar, cast
  2129, 2218-2224, 2286-2295, 2305, 2345-2356, 2360-2366, 7765-7768 (handle_intent -> _handle_work_item_dispatch)
grep -n "def block_on_request\|def _resolve_if_settled\|def on_capability_event\|def _resume\|def _redispatch\|def _cancel" src/probos/cognitive/capability_gap_driver.py
  135, 190, 229, 291, 342, 383;  254-263 (no linked item);  273-284 (blocked guard; FULFILLED resume; denied cancel)
grep -n "def find_action_requests_by_param\|def file_action_request\|created_at=time.time()" src/probos/capability_request.py
  857 (statuses, tool_id, action; oldest first), 779, 749
grep -n "command_escalations" src/probos/startup/finalize.py src/probos/routers/capability_requests.py
  finalize.py:1779-1794;  capability_requests.py:464-485 (approve -> fulfil_approval; deny -> record_denial)
grep -n "site=\"run_command_tool\"" src/probos/cognitive/swe_harness/tools.py   -> 1176
grep -n "\"call_site\": verdict.call_site" src/probos/execution/command_escalation.py   -> 168
grep -n "WorkTypeTransition(\"blocked\", \"in_progress\"" src/probos/workforce.py      -> 195, 223, 243, 264, 288 (requires_assignment)
grep -n "def hold\|def resume\|RESUME_NO_CONTINUATION" src/probos/cognitive/turn_promotion.py   -> 2658, 2690-2701, 2955-2972
grep -n "park=" src/probos/cognitive/tier_floor_ask.py   -> 145, 151-153
grep -n "TA-P0-003" docs/development/seams/p0-manifest.yaml   -> 47-57 (crossing_test: null)
grep -n "contributes_nothing_today" tests/test_ad1270f_impact_selector.py   -> 718-728
grep -n "def dispatch_work_item\|payload_out" src/probos/mesh/work_item_router.py   -> 68, 111-117
grep -n "AD-1328\|1530" docs/development/roadmap.md   -> no match
```
