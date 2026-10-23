# BF-912: an escalation's approval is not a commit, so a consensus-gated node that nothing committed fails with the reason instead of completing

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22

**Status:** Build-ready. One milestone (M1), one commit, then a docs-only commit for the validation of record. Closes #1615.

**Tier: HIGH (confirmed).** This is a governance and approval path: the Captain's decision is acknowledged and not carried out, and the plan's state contradicts what was written.

**No new AD or BF number.** Ceiling: AD-1346 (`scripts/ad_ceiling.py`), BF-918 (#1626).

**Base:** `origin/main` `80456da2`. Drafted on tree `f8aee548`, which is that base plus AD-1341 S1. `git diff --stat 80456da2 f8aee548` over every file this contract reads or edits is empty, so each SEARCH below matches identically on both. AD-1341 S1 and BF-916 merge first; section 8's tracker pairs anchor on text that their entries do not replace.

**Tests:** new `tests/test_bf912_escalation_approval_is_not_a_commit.py`: 13 functions, 20 cases. No existing test changes (Absence AV2).

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). This contract is LF. Match and write with each file's own endings; write the new file LF.

**Mechanical repairs by the orchestrator (2026-10-22), no decision changed:** (1) §6's "Run first" paragraph said T1, T2, T7, T8 and T9 must pass on the tree without §7.1, but the new file imports the helper at module level, so the whole file fails at collection there; the paragraph now says to neutralise that one import in a scratch copy first (run by the orchestrator: with the import neutralised 15 of 20 cases fail, namely T3, T4, T4b, T5, T6, T6b, T6c and the eight T10 cases, each of the seven for `completed` where `failed` is required, and the five others pass). (2) §13's third bullet named the standard library namespace class with its call parentheses in an inline code span, which `scripts/phantom-api-precheck.ps1` reads as a phantom symbol; the sentence is reworded and the precheck is Clean. (3) §13's last bullet is closed: section 8's tracker pairs apply with 0 failures on a tree that holds AD-1341 S1's and BF-916's tracker entries.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| A gated node's rejection calls `_handle_rejection`, and an approval there completes the node | present | `decomposer.py:956-964`, `:1171-1205` |
| Tier 3's yes resolves with the round's proposals (Strategy 1) or a re-broadcast with no vote (Strategy 2) | present | `escalation.py:453-465`, `:493-510`, `:512-538` |
| Tier 2's "approve" resolves with the rejected round's own dict | present | `escalation.py:303-310` |
| The gated write commits only on APPROVED; it reports `committed` | present | `runtime.py:4772-4801` |
| The gated MCP invoke commits only on APPROVED; it reports `committed` | present | `runtime.py:4839-4933` |
| BF-779's route (an intent that declares `propose_commit` with no gated path) also escalates through `_handle_rejection` | present | `decomposer.py:982-991` |
| The except path escalates a raised gated call, and an approval completes it | present | `decomposer.py:1066-1118` |
| A consensus rejection skips Tier 1 (BF-830) | present | `escalation.py:135-144` |
| Production wiring: one manager and one executor; the shell sets the Tier 3 callback | present | `runtime.py:1038-1049`; `experience/shell.py:146` |
| BF-911 is closed; its approved-but-not-committed branch stays | present | #1613 CLOSED; `decomposer.py:965-971` |

## 1. Problem

A consensus-gated plan node (`write_file`, `mcp_invoke`) proposes during the vote. It is performed only by the commit that follows an approving vote (`ProbOSRuntime.submit_write_with_consensus`, `runtime.py:4775-4783`).

When the vote rejects, `DAGExecutor._handle_rejection` escalates (`decomposer.py:960`):
- **Tier 2:** an arbiter's "approve" resolves with `resolution=node.result`, the rejected round's own dict (`escalation.py:303-310`).
- **Tier 3:** the Captain's yes calls `EscalationManager._reexecute_without_consensus` (`escalation.py:457`). Its Strategy 1 reuses that round's proposals and returns `success: True` (`:493-510`).

Either way, the executor normalises the result and sets `node.status = "completed"` (`decomposer.py:1176-1181`); a resolution of `None` completes the node as well (`:1198-1199`). The dependents run, on a file that was never written.

Two more routes give the same false completion:
- **BF-779's refusal** of a `propose_commit` intent with no gated path (`:982-991`). There, Tier 3 re-broadcasts the proposal with no vote (Strategy 2).
- **The except path** (`:1090-1118`), when the gated call itself raised.

The orchestrator reproduced this on `main` `3dfb6f81` (#1615): "vote REJECTED, Captain APPROVES at Tier 3: write=completed after=completed dependents_dispatched=['read_file'] file_written=False".

## 2. Solution overview

The executor owns node state, so it is the one that refuses to complete a node an approval cannot perform. `escalation.py` does not change.

- A module helper, `_approval_did_not_commit(esc_result)`, is True when the escalation resolved, was not a decline, and its resolution does not itself report `committed` True.
- `_handle_rejection` takes `gated: bool = False`. Both gated doors pass `gated=True`:
  - the gate table's rejection at `:960`;
  - BF-779's `propose_commit` refusal at `:984`.
  - For a gated node whose approval did not commit, a new method `_fail_uncommitted_approval` fails the node with a reason naming BF-912 and the tier, emits `ESCALATION_EXHAUSTED` and `NODE_FAILED`, and returns. The dependents then wait ("Dependency deadlock").
- The except path does the same, using a local flag `gated_route`:
  - It starts as `node.use_consensus`, so a node counts as gated until the gate table answers (fail closed).
  - It becomes `gated is not None` once the table answers.
  - BF-779's route sets it to True.
- Unchanged:
  - the Captain's decline, a skipped prompt, an approving vote and BF-911's approved-but-not-committed branch;
  - ordinary retries;
  - execute-then-vote approvals (`run_command`), whose act already ran on the broadcast.

## 3. Decisions

**D1. What an approval of a gated node does.** Options, ranked:
1. **Chosen: fail it, with the reason.** No new authority path. It is the narrower change the issue offers, and it keeps BF-830's rule that only the Captain may let a declined act proceed: it removes a false report and adds no capability.
2. Commit on the Captain's Tier 3 yes only, through a new "commit after override" method on the runtime. That is a new path that commits with no approving vote, and a shared contract in `runtime.py`. It is the Captain's AD if he wants it (register RB5).
3. Commit on Tier 2 or Tier 3. Rejected: an LLM arbiter would overrule the crew's vote and perform the write, which weakens a consensus control.

**D2. Where the check lives.** Options, ranked:
1. **Chosen: `decomposer.py` only.** The executor knows the route and owns `node.status`. The escalation manager stays event-silent and does not know about the gate table, and its result still records truthfully that the approver said yes.
2. Return an unresolved result from `escalation.py` for gated nodes. It needs the gate table inside the manager and falsifies `resolved` and `user_approved`.
3. Both. Twice the surface for the same effect.

**D3. What proves a commit.** Options, ranked:
1. **Chosen: the resolution's own `committed is True`.** This is BF-911's evidence pattern (`decomposer.py:965`). No tier produces it today; a future override that really commits (D1 option 2) would satisfy it without touching this code.
2. Never complete a gated node after an escalation. Simpler, but it would have to be undone if an override ever commits.

**D4. Which routes.** Options, ranked:
1. **Chosen: all three:**
   - the gate table's rejection;
   - BF-779's `propose_commit` refusal;
   - the except path.

   It is the same false completion in each.
2. The rejection path only, as the issue names it. It leaves the other two routes reporting a commit that never happened.

**D5. Which events.** Options, ranked:
1. **Chosen: `ESCALATION_EXHAUSTED` with the reason, then `NODE_FAILED`.** The renderer maps both to "failed" (`renderer.py:538-545`). The escalation did not resolve the node.
2. `ESCALATION_RESOLVED` then `NODE_FAILED`. The renderer would show "completed" until the next event.

**D6. The except path before the gate table answers.** Options, ranked:
1. **Chosen: `gated_route = node.use_consensus` until the table answers (fail closed).** If the lookup itself raised, nothing knows whether the node is gated; an approval must not complete a consensus node it might not have committed.
2. Start at `False`. The approval would complete it, which is the defect.

## 4. Milestones

| Milestone | Sections | Commit |
|---|---|---|
| M1 | §7.1, §7.2, then §8 | One commit: "BF-912: an escalation's approval is not a commit, so a consensus-gated node that nothing committed fails with the reason (closes #1615)" |
| Docs only | §8's last paragraph | The validation of record, after the code commit |

## 5. Consumers of every value this changes

| Value | Consumer | Accepts the change because |
|---|---|---|
| `node.status = "failed"` | `DAGExecutor.execute`'s counts (`:822-823`); the deadlock pass (`:851-855`); `renderer.py:538-545`; the reflector | It is the existing failed state, which the "User rejected" branch already produces |
| `results[node.id] = {"error": ..., "committed": False}` | `_summarize_node_result` (a dict without `results` falls through to its other branches); dependents' `$dep` substitution (`:934-938`) | It has the same shape as the existing `{"error": "User rejected the operation"}`. Dependents never run on a failed node |
| `ESCALATION_EXHAUSTED` with an `error` key | `renderer.py:544`; `event_persistence.py:242` | The renderer reads only `node`. Persistence takes any payload |
| The new `gated` keyword on `_handle_rejection` | Its three call sites only (Absence AV3) | It defaults to False, so `:1004` is unchanged |

## 6. Tests

M1 opens at **§7.1**. The test file is §7.2, and §8's tracker pairs go in M1's commit.

New `tests/test_bf912_escalation_approval_is_not_a_commit.py`. It runs the production `DAGExecutor`, `EscalationManager`, gate table (`ProbOSRuntime.gated_commit_for` and both adapters), `ProbOSRuntime.submit_write_with_consensus`, `ProbOSRuntime.submit_mcp_invoke_with_consensus` and `FileWriterAgent.commit_write`. Only the vote's outcome, the arbiter's answer and the Captain's answer are chosen. Every test asserts its premise first.

| Test | What it proves |
|---|---|
| T1 | Control: an approving vote still writes the file, completes, runs the dependent; nobody is asked |
| T2 | The Captain declines: the node fails "User rejected the operation" as before; no file; the dependent waits |
| T3 | **The headline.** The Captain approves a rejected write: the node fails with the BF-912 reason. Checked: the events, the reason payload, the log line, no file, the dependent waits. The vote's record stays on the node |
| T4 | The same for the gate table's `mcp_invoke`: no bridge invoke |
| T4b | Tier 2: an arbiter's "approve" behaves as the Captain's does; Tier 3 is not reached |
| T5 | BF-779's `propose_commit` route fails on approval |
| T6 | The except path: a gated call that raised and was approved fails; `NODE_FAILED` comes from the new method |
| T6b | A listener that raised inside the rejection (BF-779's route) cannot complete the node on the re-escalation |
| T6c | A consensus node whose gate table raised fails on approval (D6) |
| T7 | A skipped prompt keeps the existing failure and the vote's record |
| T8 | Regression: an ordinary failure that Tier 1 retries still completes |
| T9 | Regression: an approved execute-then-vote `run_command` still completes with its output |
| T10 | The predicate's boundaries, 8 cases |

**Focused gate (Builder, `-n 0`)**, the changed slice and its immediate consumers:

```text
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf912_escalation_approval_is_not_a_commit.py tests/test_escalation.py tests/test_bf830_rejected_consensus_does_not_rerun.py tests/test_bf911_protected_config_write_refusal.py tests/test_ad1284_consensus_gate_reachability.py tests/test_decomposer.py tests/test_dag_proposal.py tests/test_checkpoint.py tests/test_layer_boundaries.py -q -n 0
```

**Run first:** the new file alone, on the tree **without** §7.1 applied. The module-level import of the new helper makes the whole file fail at collection there, so first neutralise that one import in a scratch copy of the test file (`try:` the import, `except ImportError:` bind the name to `None`). Then T3, T4, T4b, T5, T6, T6b and T6c must fail (they reproduce the defect: the node is `completed` where it must be `failed`), the eight T10 cases fail (the helper is absent), and T1, T2, T7, T8 and T9 must pass. Then apply §7.1 to the tree and use the committed file; all 20 cases must pass.

The broad gate runs once in the main session, after review.

## 7. The contract

### 7.1 `src/probos/cognitive/decomposer.py` (M1)

Nine pairs, in file order. Each SEARCH occurs once in the file (checked with `grep -n -F` on each distinctive line; §11).

**Pair 1: the annotation import.**

SEARCH:
```python
    from probos.consensus.escalation import EscalationManager
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)
```
REPLACE:
```python
    from probos.consensus.escalation import EscalationManager
    from probos.runtime import ProbOSRuntime
    from probos.types import EscalationResult  # BF-912: an annotation only

logger = logging.getLogger(__name__)
```

**Pair 2: the predicate.**

SEARCH:
```python
        "success": success and any(
            getattr(r, "success", False) for r in agent_results
        ),
        "result_count": len(agent_results),
    }


def _summarize_node_result(node_result: Any) -> str:
```
REPLACE:
```python
        "success": success and any(
            getattr(r, "success", False) for r in agent_results
        ),
        "result_count": len(agent_results),
    }


def _approval_did_not_commit(esc_result: EscalationResult) -> bool:
    """BF-912 (#1615): True when an escalation approved a node and nothing reports that its act was committed.

    A consensus-gated act (the gate table's ``write_file`` and ``mcp_invoke``, or an intent that declares
    ``propose_commit``) is performed only by the commit that follows an approving vote. Tier 2's "approve"
    resolves with the rejected round's own dict, and Tier 3's yes with that round's proposals or a
    re-broadcast of them, so neither commits. Only a resolution that itself reports ``committed`` True is a
    performed act; no tier produces one today. A declined or unresolved escalation is not an approval: the
    existing branches handle it.
    """
    if not esc_result.resolved or esc_result.user_approved is False:
        return False  # BF-912: not an approval; the existing branches decide
    approved_result = esc_result.resolution
    return not (isinstance(approved_result, dict) and approved_result.get("committed") is True)


def _summarize_node_result(node_result: Any) -> str:
```

**Pair 3: the route flag.** `tests/test_ad1284_consensus_gate_reachability.py:355-360` splits this method's source at its first `try:` and checks for quoted intent names up to the first `elif node.use_consensus`. The two new lines quote no name, and the first line contains no `try:`.

SEARCH:
```python
        logger.info(
            "Executing DAG node: id=%s intent=%s depends=%s consensus=%s",
            node.id, node.intent, node.depends_on, node.use_consensus,
        )

        try:
            # BF-779: table, not a name. A by-name check gated exactly one intent
            # and left mcp_invoke -- which HAS a gated runtime path -- proposing
            # into a void, committing nothing.
            _lookup = getattr(self.runtime, "gated_commit_for", None)
            gated = _lookup(node.intent) if (_lookup and node.use_consensus) else None
            if gated is not None:
```
REPLACE:
```python
        logger.info(
            "Executing DAG node: id=%s intent=%s depends=%s consensus=%s",
            node.id, node.intent, node.depends_on, node.use_consensus,
        )

        gated_route = node.use_consensus  # BF-912: until the gate table answers, a consensus node counts as gated
        try:
            # BF-779: table, not a name. A by-name check gated exactly one intent
            # and left mcp_invoke -- which HAS a gated runtime path -- proposing
            # into a void, committing nothing.
            _lookup = getattr(self.runtime, "gated_commit_for", None)
            gated = _lookup(node.intent) if (_lookup and node.use_consensus) else None
            gated_route = gated is not None  # BF-912: the except path below needs to know
            if gated is not None:
```

**Pair 4: the gate table's rejection door.**

SEARCH:
```python
                    await self._handle_rejection(
                        node, dag, results,
                        f"Consensus {consensus.outcome.value}",
                        on_event=on_event,
                    )
                elif not result.get("committed", True):
```
REPLACE:
```python
                    await self._handle_rejection(
                        node, dag, results,
                        f"Consensus {consensus.outcome.value}",
                        on_event=on_event, gated=True,  # BF-912: the gate table's commit is this node's only commit
                    )
                elif not result.get("committed", True):
```

**Pair 5: BF-779's door.**

SEARCH:
```python
                if _mode_of and _mode_of(node.intent) == "propose_commit":
                    await self._handle_rejection(
                        node, dag, results,
                        f"{node.intent} declares propose_commit but has no "
                        f"gated commit path registered; refusing to fall back "
                        f"to execute-then-vote",
                        on_event=on_event,
                    )
                    return
```
REPLACE:
```python
                if _mode_of and _mode_of(node.intent) == "propose_commit":
                    gated_route = True  # BF-912: declares propose_commit, and no gated path can commit it
                    await self._handle_rejection(
                        node, dag, results,
                        f"{node.intent} declares propose_commit but has no "
                        f"gated commit path registered; refusing to fall back "
                        f"to execute-then-vote",
                        on_event=on_event, gated=True,  # BF-912: an approval cannot commit a propose_commit intent
                    )
                    return
```

**Pair 6: the except path.**

SEARCH:
```python
                node.escalation_result = esc_result.to_dict()
                if esc_result.resolved:
                    if esc_result.resolution is not None:
                        node.result = esc_result.resolution
                        results[node.id] = esc_result.resolution
```
REPLACE:
```python
                node.escalation_result = esc_result.to_dict()
                if gated_route and _approval_did_not_commit(esc_result):
                    await self._fail_uncommitted_approval(node, results, esc_result, on_event)  # BF-912: a raised gated call
                elif esc_result.resolved:
                    if esc_result.resolution is not None:
                        node.result = esc_result.resolution
                        results[node.id] = esc_result.resolution
```

**Pair 7: the rejection handler's signature.** `tests/test_bf830_rejected_consensus_does_not_rerun.py:300-305` scans this method's source from its `escalation_manager.escalate(` call to the call's first `)`. The docstring below names neither, and the call is unchanged.

SEARCH:
```python
    async def _handle_rejection(
        self,
        node: TaskNode,
        dag: TaskDAG,
        results: dict[str, Any],
        error: str,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        """Handle a consensus-rejected node: escalate or mark failed."""
```
REPLACE:
```python
    async def _handle_rejection(
        self,
        node: TaskNode,
        dag: TaskDAG,
        results: dict[str, Any],
        error: str,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        gated: bool = False,
    ) -> None:
        """Handle a consensus-rejected node: escalate or mark failed.

        BF-912 (#1615): ``gated`` says the node's act is performed only by the commit that follows an
        approving vote (the gate table's paths, and an intent that declares ``propose_commit``). An
        approval at Tier 2 or Tier 3 cannot perform it, so the node fails with the reason instead of completing.
        """
```

**Pair 8: the rejection handler's check.**

SEARCH:
```python
            logger.info(
                "Escalation result for node %s: resolved=%s tier=%s "
                "user_approved=%s has_resolution=%s",
                node.id, esc_result.resolved, esc_result.tier,
                esc_result.user_approved, esc_result.resolution is not None,
            )
            node.escalation_result = esc_result.to_dict()
            if esc_result.resolved:
```
REPLACE:
```python
            logger.info(
                "Escalation result for node %s: resolved=%s tier=%s "
                "user_approved=%s has_resolution=%s",
                node.id, esc_result.resolved, esc_result.tier,
                esc_result.user_approved, esc_result.resolution is not None,
            )
            node.escalation_result = esc_result.to_dict()
            if gated and _approval_did_not_commit(esc_result):
                await self._fail_uncommitted_approval(node, results, esc_result, on_event)  # BF-912: the rejection door
                return  # BF-912: an approval of a gated node is not its commit
            if esc_result.resolved:
```

**Pair 9: the failing method** (the end of `_handle_rejection`, which is the end of the file).

SEARCH:
```python
        else:
            node.status = "failed"
            if on_event:
                await on_event(EventType.NODE_FAILED, {"node": node, "error": error})
```
REPLACE:
```python
        else:
            node.status = "failed"
            if on_event:
                await on_event(EventType.NODE_FAILED, {"node": node, "error": error})

    async def _fail_uncommitted_approval(
        self,
        node: TaskNode,
        results: dict[str, Any],
        esc_result: EscalationResult,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        """BF-912 (#1615): fail a consensus-gated node that an escalation approved and nothing committed.

        The approver's decision stays in ``node.escalation_result``, and whatever ``node.result`` held stays;
        ``results`` carries the reason, so the plan says why it stopped. Dependents then wait
        (``Dependency deadlock``), as they do for any failed node.
        """
        error = (
            f"BF-912: approved at escalation tier {esc_result.tier.value}, but the approval could not commit "
            f"{node.intent}: it commits only through an approving consensus vote, and no commit is reported"
        )
        logger.warning("BF-912: node %s (%s): %s", node.id, node.intent, error)
        node.status = "failed"  # BF-912: an approval is not a commit
        results[node.id] = {"error": error, "committed": False}
        if on_event:  # BF-912: the board shows the failure and its reason
            exhausted = {"node": node, "escalation": node.escalation_result, "error": error}
            await on_event(EventType.ESCALATION_EXHAUSTED, {**exhausted, "category": "consensus", "event": "escalation_exhausted"})
            await on_event(EventType.NODE_FAILED, {"node": node, "error": error, "committed": False})
```

### 7.2 New file: `tests/test_bf912_escalation_approval_is_not_a_commit.py` (M1)

```python
"""BF-912 (#1615): an escalation's approval never reports a consensus-gated act completed when nothing committed.

A gated ``write_file`` or ``mcp_invoke`` proposes during the vote and is performed only by the commit that
follows an approving vote (``ProbOSRuntime.submit_write_with_consensus``). When the vote rejected it, an
arbiter's "approve" (Tier 2) or the Captain's yes (Tier 3) resolved the escalation with the rejected round's
proposals, and the DAG executor marked the node completed and ran its dependents on a write that never
happened. These tests drive the production executor, escalation manager, gate table and commit chain; only
the vote, the arbiter's answer and the Captain's answer are chosen. Each asserts its premise first, so a test
that never reached the path cannot pass.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace as _NS
from typing import Any

import pytest

from probos.cognitive.decomposer import DAGExecutor, _approval_did_not_commit
from probos.consensus.escalation import EscalationManager
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.types import ConsensusOutcome, EscalationResult, EscalationTier, IntentResult, TaskDAG, TaskNode

_CONTENT = "the plan's text\n"


class _Log:
    """The event log the consensus commits write; records each event name."""

    def __init__(self) -> None:
        self.events: list[str] = []

    async def log(self, **kwargs: Any) -> str:
        self.events.append(kwargs["event"])
        return "row-1"


class _Bridge:
    """An MCP bridge that records every invoke; a rejected vote must make none."""

    def __init__(self) -> None:
        self.invocations: list[str] = []

    async def invoke(self, server_url: str, tool: str, arguments: dict, **kwargs: Any) -> dict:
        self.invocations.append(tool)
        return {"ok": True}


class _Vessel:
    """What the executor, the gate table and both consensus commits read from a runtime.

    The gate table, its two adapters and both consensus commits are the production methods. The vote's
    outcome is chosen; every broadcast without a vote is recorded and answers as a proposal would.
    """

    gated_commit_for = ProbOSRuntime.gated_commit_for
    _gated_commit_write = ProbOSRuntime._gated_commit_write
    _gated_commit_mcp_invoke = ProbOSRuntime._gated_commit_mcp_invoke
    submit_write_with_consensus = ProbOSRuntime.submit_write_with_consensus
    submit_mcp_invoke_with_consensus = ProbOSRuntime.submit_mcp_invoke_with_consensus

    def __init__(self, tmp_path: Any, outcome: ConsensusOutcome, *, mode: str = "execute_then_vote",
                 vote_raises: bool = False) -> None:
        self.config_path = str(tmp_path / "system.yaml")
        self.event_log = _Log()
        self.mcp_bridge = _Bridge()
        self.outcome = outcome
        self.mode = mode
        self.vote_raises = vote_raises
        self.votes: list[str] = []
        self.broadcasts: list[str] = []
        self.flaky_failed = False

    def consensus_mode_for(self, intent: str) -> str:
        return self.mode

    async def submit_intent_with_consensus(self, intent: str, params: Any = None, timeout: Any = None,
                                           **kwargs: Any) -> dict:
        self.votes.append(intent)
        if self.vote_raises:
            raise RuntimeError("the vote could not be taken")
        proposal = IntentResult(intent_id="i1", agent_id="proposer", success=True,
                                result={"proposed": intent}, confidence=0.9)
        return {"intent": None, "results": [proposal], "verifications": [],
                "consensus": _NS(outcome=self.outcome)}

    async def submit_intent(self, intent: str, params: Any = None, timeout: Any = None) -> list:
        self.broadcasts.append(intent)
        if intent == "flaky" and not self.flaky_failed:
            self.flaky_failed = True
            raise RuntimeError("transport reset")
        return [IntentResult(intent_id="i2", agent_id="worker", success=True,
                             result={"ran": intent}, confidence=0.9)]


class _UnreadableGateVessel(_Vessel):
    """A vessel whose gate table raises when it is read."""

    def gated_commit_for(self, intent: str) -> Any:
        raise RuntimeError("the gate table could not be read")


class _Arbiter:
    """A real (non-mock) LLM client whose arbiter answers "approve"."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: Any) -> Any:
        self.calls += 1
        return _NS(error=None, content=json.dumps({"action": "approve", "reason": "acceptable", "params": {}}))


async def _run(vessel: _Vessel, first: TaskNode, *, answer: bool | None = True, arbiter: Any = None,
               raise_once_on: Any = None) -> tuple[TaskDAG, dict, list, list]:
    """*first*, then a ``read_file`` that depends on it, through the production executor and escalation manager."""
    asked: list[str] = []
    events: list[tuple[Any, str, dict]] = []
    raised: list[Any] = []

    async def _captain(description: str, context: dict) -> bool | None:
        asked.append(description)
        return answer

    async def _on_event(event: Any, data: dict) -> None:
        if event == raise_once_on and not raised:
            raised.append(event)
            raise RuntimeError("a listener failed")
        events.append((event, data["node"].id, data))

    manager = EscalationManager(runtime=vessel, llm_client=arbiter, user_callback=_captain)
    dag = TaskDAG(nodes=[first, TaskNode(id="after", intent="read_file", depends_on=[first.id])])
    outcome = await DAGExecutor(vessel, escalation_manager=manager).execute(dag, on_event=_on_event)
    return dag, outcome, events, asked


def _kinds(events: list, node_id: str) -> list:
    return [event for event, nid, _ in events if nid == node_id]


def _write(tmp_path: Any) -> TaskNode:
    return TaskNode(id="write", intent="write_file", params={"path": str(tmp_path / "out.txt"), "content": _CONTENT},
                    use_consensus=True)


# --- T1, T2: the paths that must not change ------------------------------------------------------------------


async def test_t1_an_approving_vote_still_writes_and_completes(tmp_path: Any) -> None:
    """T1 (control): the vote approves, the commit writes, the node completes and its dependent runs."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.APPROVED)
    dag, outcome, events, asked = await _run(vessel, _write(tmp_path))
    write, after = dag.nodes
    assert vessel.event_log.events == ["write_committed"], "premise: the production commit ran"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == _CONTENT
    assert (write.status, after.status) == ("completed", "completed")
    assert vessel.broadcasts == ["read_file"] and asked == []


async def test_t2_the_captain_declines_and_the_node_fails_as_before(tmp_path: Any) -> None:
    """T2: the vote rejects and the Captain declines; nothing is written and the dependent waits."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.REJECTED)
    dag, outcome, events, asked = await _run(vessel, _write(tmp_path), answer=False)
    write, after = dag.nodes
    assert len(asked) == 1 and vessel.event_log.events == [], "premise: rejected, so no commit ran; the Captain was asked"
    assert write.status == "failed" and outcome["results"]["write"] == {"error": "User rejected the operation"}
    assert after.status == "failed" and "read_file" not in vessel.broadcasts
    assert not (tmp_path / "out.txt").exists()


# --- T3 to T5: an approval of a gated node ---------------------------------------------------------------------


async def test_t3_the_captain_approves_a_rejected_write_and_the_node_fails_saying_why(tmp_path: Any, caplog: Any) -> None:
    """T3: before the fix the node was completed and its dependent ran on a file that was never written."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.REJECTED)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.decomposer"):
        dag, outcome, events, asked = await _run(vessel, _write(tmp_path), answer=True)
    write, after = dag.nodes
    assert len(asked) == 1 and write.escalation_result["user_approved"] is True, "premise: the Captain approved at Tier 3"
    assert vessel.event_log.events == [] and not (tmp_path / "out.txt").exists(), "premise: nothing was committed"
    assert write.status == "failed", write.status
    error = outcome["results"]["write"]["error"]
    assert outcome["results"]["write"] == {"error": error, "committed": False}
    assert error.startswith("BF-912: approved at escalation tier user, but the approval could not commit write_file:")
    assert "it commits only through an approving consensus vote" in error
    assert write.result["committed"] is False, "the vote's own record stays on the node"
    kinds = _kinds(events, "write")
    assert EventType.ESCALATION_EXHAUSTED in kinds and EventType.NODE_FAILED in kinds
    assert EventType.NODE_COMPLETE not in kinds and EventType.ESCALATION_RESOLVED not in kinds
    exhausted = next(data for event, nid, data in events if event == EventType.ESCALATION_EXHAUSTED and nid == "write")
    assert exhausted["error"] == error and exhausted["escalation"]["user_approved"] is True
    assert after.status == "failed" and outcome["results"]["after"] == {"error": "Dependency deadlock"}
    assert "read_file" not in vessel.broadcasts, "the dependent ran on a write that never happened"
    assert any("BF-912: node write (write_file)" in r.getMessage() for r in caplog.records)


async def test_t4_the_same_holds_for_the_gate_tables_mcp_invoke(tmp_path: Any) -> None:
    """T4: the gate table's other path; the Captain's approval invokes nothing, so the node fails."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.REJECTED)
    node = TaskNode(id="invoke", intent="mcp_invoke", params={"server_url": "srv", "tool": "do_thing", "arguments": {}},
                    use_consensus=True)
    dag, outcome, events, asked = await _run(vessel, node, answer=True)
    invoke, after = dag.nodes
    assert len(asked) == 1 and vessel.votes == ["mcp_invoke"], "premise: the mcp path voted and the Captain approved"
    assert vessel.mcp_bridge.invocations == [] and invoke.status == "failed"
    assert outcome["results"]["invoke"]["committed"] is False and after.status == "failed"


async def test_t4b_an_arbiters_approve_behaves_as_the_captains_does(tmp_path: Any) -> None:
    """T4b: Tier 2's "approve" resolved with the rejected round's own dict; the Captain is never reached."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.REJECTED)
    arbiter = _Arbiter()
    dag, outcome, events, asked = await _run(vessel, _write(tmp_path), arbiter=arbiter)
    write, after = dag.nodes
    assert arbiter.calls == 1 and asked == [], "premise: Tier 2 approved and Tier 3 was not reached"
    assert write.escalation_result["tier"] == "arbitration" and write.escalation_result["resolved"] is True
    assert write.status == "failed" and not (tmp_path / "out.txt").exists()
    assert outcome["results"]["write"]["error"].startswith("BF-912: approved at escalation tier arbitration,")
    assert after.status == "failed" and "read_file" not in vessel.broadcasts


async def test_t5_a_propose_commit_intent_with_no_gated_path_fails_on_approval(tmp_path: Any) -> None:
    """T5: BF-779's refusal escalates; the Captain's approval re-broadcasts a proposal and commits nothing."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.REJECTED, mode="propose_commit")
    node = TaskNode(id="act", intent="device_actuate", params={"device_id": "lamp"}, use_consensus=True)
    dag, outcome, events, asked = await _run(vessel, node, answer=True)
    act, after = dag.nodes
    assert len(asked) == 1 and vessel.votes == [], "premise: no vote ran; BF-779's refusal escalated and was approved"
    assert act.status == "failed" and outcome["results"]["act"]["error"].startswith("BF-912:")
    assert after.status == "failed" and "read_file" not in vessel.broadcasts


# --- T6 to T6c: the except path -----------------------------------------------------------------------------


async def test_t6_a_gated_call_that_raised_and_was_approved_fails(tmp_path: Any) -> None:
    """T6: the gated call raised; the Captain's approval re-broadcast the proposal, which commits nothing."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.APPROVED, vote_raises=True)
    dag, outcome, events, asked = await _run(vessel, _write(tmp_path), answer=True)
    write, after = dag.nodes
    assert vessel.votes == ["write_file"] and len(asked) == 1, "premise: the gated call raised and the Captain approved"
    assert "write_file" in vessel.broadcasts, "premise: Tier 3 took its re-broadcast strategy"
    assert write.status == "failed" and not (tmp_path / "out.txt").exists()
    assert outcome["results"]["write"]["error"].startswith("BF-912:")
    kinds = _kinds(events, "write")
    assert EventType.NODE_FAILED in kinds and EventType.NODE_COMPLETE not in kinds
    assert after.status == "failed" and "read_file" not in vessel.broadcasts


async def test_t6b_a_listener_that_raised_inside_the_rejection_cannot_complete_the_node(tmp_path: Any) -> None:
    """T6b: the first escalation-start listener raises on BF-779's route; the except path escalates once, and fails it."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.REJECTED, mode="propose_commit")
    node = TaskNode(id="act", intent="device_actuate", params={"device_id": "lamp"}, use_consensus=True)
    dag, outcome, events, asked = await _run(vessel, node, answer=True, raise_once_on=EventType.ESCALATION_START)
    act, after = dag.nodes
    assert len(asked) == 1 and _kinds(events, "act").count(EventType.ESCALATION_START) == 1, (
        "premise: the first start raised inside the rejection, and the except path escalated once")
    assert act.status == "failed" and outcome["results"]["act"]["error"].startswith("BF-912:")
    assert after.status == "failed" and "read_file" not in vessel.broadcasts


async def test_t6c_a_consensus_node_whose_gate_table_raised_fails_on_approval(tmp_path: Any) -> None:
    """T6c: until the gate table answers, a consensus node counts as gated, so an approval cannot complete it."""
    vessel = _UnreadableGateVessel(tmp_path, ConsensusOutcome.REJECTED)
    dag, outcome, events, asked = await _run(vessel, _write(tmp_path), answer=True)
    write, after = dag.nodes
    assert vessel.votes == [] and len(asked) == 1, "premise: the lookup raised before any vote, and the Captain approved"
    assert write.status == "failed" and outcome["results"]["write"]["error"].startswith("BF-912:")
    assert after.status == "failed" and not (tmp_path / "out.txt").exists()


# --- T7 to T9: what must not change -------------------------------------------------------------------------


async def test_t7_a_skipped_prompt_keeps_the_existing_failure(tmp_path: Any) -> None:
    """T7: no answer resolves nothing; the node fails as before and keeps the vote's record as its result."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.REJECTED)
    dag, outcome, events, asked = await _run(vessel, _write(tmp_path), answer=None)
    write, after = dag.nodes
    assert len(asked) == 1 and write.escalation_result["resolved"] is False, "premise: the Captain skipped"
    assert write.status == "failed" and "consensus" in outcome["results"]["write"]
    assert "error" not in outcome["results"]["write"] and after.status == "failed"


async def test_t8_an_ordinary_failure_that_a_retry_resolves_still_completes(tmp_path: Any) -> None:
    """T8 (regression): a node with no consensus gate is untouched; Tier 1's retry resolves it as before."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.APPROVED)
    dag, outcome, events, asked = await _run(vessel, TaskNode(id="flaky", intent="flaky"))
    flaky, after = dag.nodes
    assert vessel.broadcasts[:2] == ["flaky", "flaky"] and flaky.escalation_result["tier"] == "retry", (
        "premise: the first broadcast raised and Tier 1's retry resolved it")
    assert (flaky.status, after.status) == ("completed", "completed") and asked == []


async def test_t9_an_approved_execute_then_vote_command_still_completes(tmp_path: Any) -> None:
    """T9 (regression): run_command executes on the broadcast, so the Captain's approval reuses that output."""
    vessel = _Vessel(tmp_path, ConsensusOutcome.REJECTED)
    node = TaskNode(id="cmd", intent="run_command", params={"command": "echo hi"}, use_consensus=True)
    dag, outcome, events, asked = await _run(vessel, node, answer=True)
    cmd, after = dag.nodes
    assert vessel.votes == ["run_command"] and len(asked) == 1, "premise: the vote rejected and the Captain approved"
    assert cmd.status == "completed" and outcome["results"]["cmd"]["success"] is True
    assert after.status == "completed" and "read_file" in vessel.broadcasts


# --- T10: the predicate -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("resolved", "user_approved", "resolution", "expected"),
    [
        (False, None, None, False),
        (True, False, None, False),
        (True, True, None, True),
        (True, None, {"results": [], "success": True}, True),
        (True, True, {"committed": False}, True),
        (True, None, {"committed": "yes"}, True),
        (True, True, ["not", "a", "dict"], True),
        (True, None, {"committed": True}, False),
    ],
)
def test_t10_only_a_resolution_that_reports_its_commit_is_a_performed_act(
    resolved: bool, user_approved: bool | None, resolution: Any, expected: bool
) -> None:
    """T10: the predicate's boundaries; a declined or unresolved escalation is not an approval."""
    result = EscalationResult(tier=EscalationTier.USER, resolved=resolved, user_approved=user_approved,
                              resolution=resolution)
    assert _approval_did_not_commit(result) is expected
```

## 8. Tracking (tracker pairs; in M1's commit)

Set the date to the commit date. Both pairs anchor on text that AD-1341 S1's and BF-916's entries leave in place:
- `PROGRESS.md`: its title line.
- `DECISIONS.md`: the heading and first bullet of the 2026-10-17 entry. S1's pair inserts before it, and so would BF-916's, so this entry lands after both.

If either batch moved one of these lines, re-anchor on text and say so in the commit body.

**`PROGRESS.md`** (one-line SEARCH, deliberately: any later line belongs to an entry that lands first):

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-912 (2026-10-22), closes #1615 -- an escalation's approval no longer reports a consensus-gated write or MCP invoke completed when nothing was committed.** A gated `write_file` or `mcp_invoke` is performed only by the commit that follows an approving vote. When the vote rejected it, an arbiter's "approve" (Tier 2) or the Captain's yes (Tier 3) resolved the escalation with the rejected round's proposals, and `DAGExecutor` marked the node completed and ran its dependents on a write that never happened. Such a node now fails with a reason naming BF-912 and the tier ("the approval could not commit ..."), with `ESCALATION_EXHAUSTED` and `NODE_FAILED`, and its dependents wait. The same holds on BF-779's route (an intent that declares `propose_commit` with no gated path) and on the except path when a gated call raised; until the gate table answers, a consensus node counts as gated. Only a resolution that itself reports `committed` True could complete such a node, and no tier produces one today. The Captain's decline, a skipped prompt, an approving vote, BF-911's approved-but-not-committed branch, ordinary retries and execute-then-vote approvals are unchanged; `escalation.py` is unchanged. New: `tests/test_bf912_escalation_approval_is_not_a_commit.py` (the production executor, escalation manager, gate table and commit chain). The contract is `prompts/bf-912-escalation-approval-is-not-a-commit.md`.
```

**`DECISIONS.md`:**

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)

- *Scope.* Standing-order text and its layout test only; nothing under `src/` changes. No AD or BF number, like the 2026-10-15 profile entries.
```
REPLACE:
```markdown
### BF-912 -- An escalation's approval is not a gated commit (2026-10-22, #1615)

- *Scope.* One milestone, one gate and one PR. `cognitive/decomposer.py` and a new test file. Contract: `prompts/bf-912-escalation-approval-is-not-a-commit.md`.
- *D1 (fail, not commit).* A consensus-gated node whose escalation approved it and whose resolution does not report `committed` True fails with the reason. Rejected: committing on the Captain's Tier 3 yes (a new path that commits with no approving vote; the Captain's AD if he wants it) and committing on Tier 2 (an LLM would overrule the crew's vote).
- *D2-D3 (where, and the evidence).* The executor decides, because it owns node state; `escalation.py` stays unchanged and still records that the approver said yes. A commit is proved only by the resolution's own `committed is True`, BF-911's evidence pattern.
- *D4-D6 (routes and events).* The gate table's rejection, BF-779's `propose_commit` refusal and the except path. Until the gate table answers, a consensus node counts as gated. Events: `ESCALATION_EXHAUSTED` with the reason, then `NODE_FAILED`.
- *Disclosed effects.* A rejected gated write or MCP invoke that the Captain approves at the shell prompt, or an arbiter approves, now fails and says why; to perform it, submit it again so a new vote can approve it. The prompt still asks for an approval it cannot carry out (register). Nothing persisted changes.
- *Register.* RB1 to RB6 in section 14 of the contract.
- *Reversal.* Revert the BF-912 commit. Nothing persisted changes; the approvals complete those nodes again.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)

- *Scope.* Standing-order text and its layout test only; nothing under `src/` changes. No AD or BF number, like the 2026-10-15 profile entries.
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` and commit its two outputs with M1. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`.

**`docs/development/roadmap.md`:** no row. Its table holds only bugs that are open and deliberately not fixed.

**Docs-only commit after the code commit:** add a *Validation of record* bullet before BF-912's *Reversal* line. It records:
- the mutation campaign of record and its base tree;
- the sha256 of `decomposer.py` and of the new test file;
- each row's first failing test.

Add the same as a closing section of this contract, then regenerate the ledger.

## 9. What this does NOT change

- `consensus/escalation.py`, all of it:
  - the tier order and BF-830's Tier 1 skip;
  - the arbiter's "modify" withholding;
  - Tier 3's two strategies and its prompt text;
  - the event-silent contract.
- The consensus policy and quorum evaluation.
- The gate table and both consensus commits (`runtime.py`).
- `FileWriterAgent.commit_write`, and the AD-1344 and BF-911 refusals.
- BF-911's approved-but-not-committed branch (`decomposer.py:965-971`).
- The execute-then-vote path and its approvals (`decomposer.py:1004`); ordinary nodes and their Tier 1 retries.
- No configuration field, no `EventType` member, no UI, renderer or HXI change. The shell callback is unchanged.

## 10. Mutation rows (29 rows; whole stripped lines, each occurring once in its file after §7)

**Tier HIGH:** every changed executable line in `src/probos/cognitive/decomposer.py` has a row. Comments, docstrings, the `TYPE_CHECKING` import (an annotation only, so no runtime mutant) and `def` lines have none.

**How to run:**
1. Run each row against `tests/test_bf912_escalation_approval_is_not_a_commit.py` on the tree with §7 applied, after an unmutated baseline run that passes.
2. Restore the file after each row.
3. Any row whose first failing test differs from the one named: run it alone against the named test.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| R1 | `src/probos/cognitive/decomposer.py` | `if not esc_result.resolved or esc_result.user_approved is False:` | `if esc_result.user_approved is False:` | T7 (an unresolved escalation takes BF-912's path); T10 case 1 |
| R2 | `src/probos/cognitive/decomposer.py` | `if not esc_result.resolved or esc_result.user_approved is False:` | `if not esc_result.resolved:` | T2 (a decline takes BF-912's path); T10 case 2 |
| R3 | `src/probos/cognitive/decomposer.py` | `return False  # BF-912: not an approval; the existing branches decide` | `return True` | T2, T7 |
| R4 | `src/probos/cognitive/decomposer.py` | `approved_result = esc_result.resolution` | `approved_result = {"committed": True}` | T3; T10 case 3 |
| R5 | `src/probos/cognitive/decomposer.py` | `return not (isinstance(approved_result, dict) and approved_result.get("committed") is True)` | `return not isinstance(approved_result, dict)` | T3; T10 case 4 |
| R6 | `src/probos/cognitive/decomposer.py` | `return not (isinstance(approved_result, dict) and approved_result.get("committed") is True)` | `return not (isinstance(approved_result, dict) and approved_result.get("committed"))` | T10 case 6 (`"yes"` is not True) |
| R7 | `src/probos/cognitive/decomposer.py` | `gated_route = node.use_consensus  # BF-912: until the gate table answers, a consensus node counts as gated` | `gated_route = False` | T6c |
| R8 | `src/probos/cognitive/decomposer.py` | `gated_route = gated is not None  # BF-912: the except path below needs to know` | `gated_route = False` | T6 |
| R9 | `src/probos/cognitive/decomposer.py` | `gated_route = gated is not None  # BF-912: the except path below needs to know` | `gated_route = True` | T8 (an ordinary retry would fail) |
| R10 | `src/probos/cognitive/decomposer.py` | `on_event=on_event, gated=True,  # BF-912: the gate table's commit is this node's only commit` | `on_event=on_event,` | T3, T4, T4b |
| R11 | `src/probos/cognitive/decomposer.py` | `gated_route = True  # BF-912: declares propose_commit, and no gated path can commit it` | `pass` | T6b |
| R12 | `src/probos/cognitive/decomposer.py` | `on_event=on_event, gated=True,  # BF-912: an approval cannot commit a propose_commit intent` | `on_event=on_event,` | T5 |
| R13 | `src/probos/cognitive/decomposer.py` | `gated: bool = False,` | `gated: bool = True,` | T9 |
| R14 | `src/probos/cognitive/decomposer.py` | `if gated and _approval_did_not_commit(esc_result):` | `if _approval_did_not_commit(esc_result):` | T9 |
| R15 | `src/probos/cognitive/decomposer.py` | `if gated and _approval_did_not_commit(esc_result):` | `if gated:` | T2 |
| R16 | `src/probos/cognitive/decomposer.py` | `await self._fail_uncommitted_approval(node, results, esc_result, on_event)  # BF-912: the rejection door` | `pass` | T3 (the node stays running) |
| R17 | `src/probos/cognitive/decomposer.py` | `return  # BF-912: an approval of a gated node is not its commit` | `pass` | T3 (the old completion runs) |
| R18 | `src/probos/cognitive/decomposer.py` | `if gated_route and _approval_did_not_commit(esc_result):` | `if False:` | T6 |
| R19 | `src/probos/cognitive/decomposer.py` | `await self._fail_uncommitted_approval(node, results, esc_result, on_event)  # BF-912: a raised gated call` | `pass` | T6 (the node stays running) |
| R20 | `src/probos/cognitive/decomposer.py` | `elif esc_result.resolved:` | `if esc_result.resolved:` | T6 (the completion runs after the failure) |
| R21 | `src/probos/cognitive/decomposer.py` | `f"BF-912: approved at escalation tier {esc_result.tier.value}, but the approval could not commit "` | `f"approved at escalation tier {esc_result.tier.value}, but the approval could not commit "` | T3 (`startswith`) |
| R22 | `src/probos/cognitive/decomposer.py` | `f"{node.intent}: it commits only through an approving consensus vote, and no commit is reported"` | `f"{node.intent}"` | T3 |
| R23 | `src/probos/cognitive/decomposer.py` | `logger.warning("BF-912: node %s (%s): %s", node.id, node.intent, error)` | `pass` | T3 (caplog) |
| R24 | `src/probos/cognitive/decomposer.py` | `node.status = "failed"  # BF-912: an approval is not a commit` | `pass` | T3 |
| R25 | `src/probos/cognitive/decomposer.py` | `results[node.id] = {"error": error, "committed": False}` | `pass` | T3 |
| R26 | `src/probos/cognitive/decomposer.py` | `if on_event:  # BF-912: the board shows the failure and its reason` | `if False:` | T3 (no `ESCALATION_EXHAUSTED`) |
| R27 | `src/probos/cognitive/decomposer.py` | `exhausted = {"node": node, "escalation": node.escalation_result, "error": error}` | `exhausted = {"node": node}` | T3 (the payload's `error`) |
| R28 | `src/probos/cognitive/decomposer.py` | `await on_event(EventType.ESCALATION_EXHAUSTED, {**exhausted, "category": "consensus", "event": "escalation_exhausted"})` | `pass` | T3 |
| R29 | `src/probos/cognitive/decomposer.py` | `await on_event(EventType.NODE_FAILED, {"node": node, "error": error, "committed": False})` | `pass` | T6. Not T3: on the gate table's door `_execute_node`'s own post-act emission (`elif on_event and node.status == "failed":`) emits `NODE_FAILED` again (RB1) |

## 11. Verified Against Codebase (2026-10-22, tree `f8aee548`; identical on `80456da2` for every file below)

```text
git diff --stat 80456da2 f8aee548 -- src/probos/cognitive/decomposer.py src/probos/consensus/escalation.py src/probos/runtime.py src/probos/types.py src/probos/agents/file_writer.py tests/test_escalation.py tests/test_bf830_rejected_consensus_does_not_rerun.py PROGRESS.md DECISIONS.md
  (empty: S1 touches none of them)

grep -n -F <each SEARCH's distinctive line> src/probos/cognitive/decomposer.py
  26:    from probos.runtime import ProbOSRuntime                       (pair 1)
  670:        "result_count": len(agent_results),                       (pair 2)
  941:            "Executing DAG node: id=%s intent=%s depends=%s consensus=%s",  (pair 3)
  965:                elif not result.get("committed", True):           (pair 4)
  983:                if _mode_of and _mode_of(node.intent) == "propose_commit":  (pair 5)
  1090:                node.escalation_result = esc_result.to_dict()     (pair 6, 16 spaces)
  1146:        """Handle a consensus-rejected node: escalate or mark failed."""  (pair 7)
  1170:            node.escalation_result = esc_result.to_dict()         (pair 8, 12 spaces)
  1213/1217: await on_event(EventType.NODE_FAILED, {"node": node, "error": error})  (pair 9: only 1214-1217
             has "        else:" / 12-space status / 12-space "if on_event:" before it)

decomposer.py:3      from __future__ import annotations
decomposer.py:18     from probos.types import ConsensusOutcome, IntentDescriptor, LLMRequest, TaskDAG, TaskNode, Episode, AttentionEntry
decomposer.py:20-26  if TYPE_CHECKING: ... EscalationManager ... ProbOSRuntime
decomposer.py:650-671 def _normalize_consensus_result(...)
decomposer.py:817-824 execute returns results, completed_count, failed_count
decomposer.py:848-855 deadlock: pending nodes -> {"error": "Dependency deadlock"}
decomposer.py:945-973 the gated branch; :960 _handle_rejection; :965-971 BF-911
decomposer.py:982-991 BF-779's propose_commit refusal -> _handle_rejection; return
decomposer.py:1043-1047 post-act NODE_COMPLETE / NODE_FAILED by status
decomposer.py:1066-1136 except path; :1083-1087 category consensus when use_consensus
decomposer.py:1138-1217 _handle_rejection; :1171-1205 resolved branches complete the node
escalation.py:135-144 BF-830 skips Tier 1 for category consensus
escalation.py:154-160 Tier 2 runs for a non-None, non-mock client
escalation.py:303-310 approve -> resolution=node.result
escalation.py:453-465 user_decision True -> _reexecute_without_consensus; user_approved=True
escalation.py:493-510 Strategy 1: reuse successful results, success True
escalation.py:512-538 Strategy 2: runtime.submit_intent with no consensus
types.py:380-395     EscalationResult(tier, resolved, ..., resolution, ..., user_approved: bool | None = None)
types.py:371-376     EscalationTier USER="user", ARBITRATION="arbitration", RETRY="retry"
types.py:423-434     TaskNode(id, intent, params, depends_on, use_consensus, ..., result, status, escalation_result)
types.py:78-86       IntentResult(intent_id, agent_id, success, result, error, confidence)
runtime.py:4753-4801 submit_write_with_consensus: commits only on APPROVED; result["committed"]
runtime.py:4803-4933 submit_mcp_invoke_with_consensus: invokes only on APPROVED; result["committed"]
runtime.py:5216-5241 gated_commit_for: {"write_file": ..., "mcp_invoke": ...}.get(intent)
runtime.py:5243-5269 _gated_commit_write, _gated_commit_mcp_invoke
runtime.py:1038-1049 EscalationManager(runtime=self, llm_client=..., max_retries=2); DAGExecutor(...)
experience/shell.py:146 escalation_manager.set_user_callback(
file_writer.py:146-171 commit_write: AD-1344 then BF-911 refusal, then write
security/file_access.py:316-370 protected_write_refusal reads runtime.config_path only
renderer.py:538-545  NODE_FAILED/ESCALATION_EXHAUSTED -> "failed"; ESCALATION_RESOLVED -> "completed"
pyproject.toml:181   asyncio_mode = "auto"
tests/test_ad1284_consensus_gate_reachability.py:355-360 splits _execute_node at "try:" .. "elif node.use_consensus"
tests/test_bf830_rejected_consensus_does_not_rerun.py:300-305 scans _handle_rejection's escalate( call
tests/test_bf911_protected_config_write_refusal.py:746-768 the gate-table vessel pattern this file reuses
scripts/phantom-api-precheck.ps1:217, :228 the CamelCase dotted-call and constructor-call patterns; :59-71 the stdlib names it skips
```

## 12. Absence Verified (2026-10-22)

```text
AV1 CLAIM: there is no "commit after an approval" path, so failing the node adds no authority (D1)
    RUN:   Grep "commit_write\(" src/probos
    FOUND: runtime.py:4782 (inside submit_write_with_consensus, on APPROVED); productivity_agents.py:125 and
           organizer_agents.py:65 (direct utility writes, not escalation); docstrings in file_writer.py and isolation.py
    HOLDS: yes. The MCP commit is only at runtime.py:4853, inside the APPROVED branch

AV2 CLAIM: no existing test pins a gated node completing after an approval
    RUN:   Grep "escalation_manager=" tests -> 13 files. test_escalation.py: every DAG test is either use_consensus=False
           or wraps the runtime in _ungated (gated_commit_for -> None), its 15:test file lines 483, 515, 562, 795, 929, 982;
           test_bf911's _run_plan escalate is an AsyncMock never awaited (asserted await_count == 0).
           The federation files (ad1123, ad1197 x2, ad1198 x2, ad447, ad722b, ad730, ad731a x2, federation_nats)
           were not opened; Grep "DAGExecutor\(" src -> runtime.py:1043 only
    RUN:   Grep "user_callback|resolved=True|escalation_manager=" in test_ad1284, test_dag_proposal, test_scaling,
           test_bf860 (one Grep per file) -> no matches
    HOLDS: yes for every file read; the federation files are in "Not verified"

AV3 CLAIM: _handle_rejection has exactly three callers
    RUN:   Grep "_handle_rejection\(" src/probos
    FOUND: decomposer.py:960, :984, :1004 and the def at :1138
    HOLDS: yes

AV4 CLAIM: the new names do not exist yet
    RUN:   grep -c -E "_approval_did_not_commit|_fail_uncommitted_approval|gated_route|gated: bool|approved_result|BF-912" src/probos/cognitive/decomposer.py -> 0
    RUN:   grep -c -E "elif esc_result.resolved|\"committed\": False|exhausted = |def _fail_|TYPE_CHECKING:" -> 1 (the TYPE_CHECKING: line)
    HOLDS: yes, so every §10 line is unique after §7

AV5 CLAIM: no source-scan test reads the lines this changes beyond the two shown
    RUN:   Grep "getsource\(DAGExecutor|getsource\(decomposer|decomposer\)\.read_text|_execute_node\)" tests
    FOUND: test_ad1284...:355 and test_bf830...:300 only; both are checked in §7.1 pairs 3 and 7
    HOLDS: yes
```

## 13. Not verified

- The 11 federation test files that pass `escalation_manager=` (AV2) were not opened. They run in the broad gate. If one fails, check first whether it routes a consensus node through a gated intent.
- None of these tests was run here (read-only consult). The orchestrator runs §6's "Run first" check before the Builder's focused gate.
- The phantom-API precheck was not run by the Architect on this contract. The test file avoids flagged shapes: no direct call of the standard library namespace class (it is imported under the alias `_NS`), no mock constructors, no capitalised placeholder calls.
- The shell's rendering of the new reason was not checked in a live session; the renderer only reads `node`.
- BF-916's tracker pairs are not in this tree. Section 8 assumes they also insert after `# ProbOS Progress` and before the 2026-10-17 `DECISIONS.md` heading.

## 14. For the register (follow-ups this change should not fix)

- **RB1:** on the gate table's rejection door and the execute-then-vote door, `_handle_rejection` emits `NODE_FAILED` (or `NODE_COMPLETE`), and then `_execute_node`'s post-act emission (`decomposer.py:1043-1047`) emits it again. This is pre-existing.
- **RB2:** Tier 3 asks the Captain to approve a gated act that his approval cannot perform. The prompt should say so, or Tier 3 should be skipped for gated nodes (`escalation.py`, UX).
- **RB3:** Tier 3's Strategy 2 re-broadcasts a gated intent with no vote (`escalation.py:512-518`). It has no effect today, because proposers only propose. It would matter if a `propose_commit` agent's act ever had an effect.
- **RB4:** a listener that raises inside `_handle_rejection` after `escalate()` returned sends the node to the except path, which escalates again, so the Captain is asked twice. BF-830 protected only post-act listeners. This is pre-existing; T6b covers only a raise before `escalate()`.
- **RB5:** a Tier 3 override that commits a write the crew rejected (D1 option 2) is the Captain's AD if he wants it. It is not filed.
- **RB6:** on the except path, a gated call that raised *after* its commit (for example, the event log failing after `commit_write`) is reported as "no commit is reported" while the file exists. That fails closed (the plan stops), but the text cannot tell the two cases apart.

## 15. Prior Art and Blind Spots

**Prior art:** none sought. This is a bug fix in ProbOS-specific escalation plumbing, which the drafting standard exempts from the external search; the reference-project review was not due for it.

**Internal precedent, adopted:**
- BF-911's `committed` evidence (`decomposer.py:965-971`), for D3.
- BF-830's rule that only the Captain may let a declined act proceed (`escalation.py:129-134`), for D1.
- BF-779's fail-instead-of-quietly-completing stance (`decomposer.py:975-981`), for D4 and D6.

**Blind spots found and absorbed:**
- BF-779's route and the except path take the same false completion (D4).
- A gate table that raises (D6, T6c).
- A listener raising inside the rejection (T6b).
- The duplicate `NODE_FAILED`, which would have let mutant R29 survive T3; it is killed by T6 instead.
- The two source-scan tests that pin this code (§7.1, pairs 3 and 7).

**Considered and deferred:** RB2 to RB5.

## 16. Diff Reviewer: properties to verify

- No path from an escalation leaves a consensus-gated node `completed` unless its resolution reports `committed` True.
- A decline, a skip, an approving vote, BF-911's branch, Tier 1 retries of ordinary nodes, and execute-then-vote approvals behave exactly as on `80456da2`.
- `escalation.py` and `runtime.py` are byte-identical to the base.
- `test_ad1284...:355-360` and `test_bf830...:300-305` still pass, unedited.
- Every §10 line occurs exactly once in `decomposer.py`.
- **Consumer that must accept this:** `DAGExecutor.execute`'s caller (`runtime.py:1043`) and the shell renderer, which read a failed node with a `{"error", "committed"}` result exactly as they read the existing "User rejected" result.

## 17. Acceptance Criteria

- [ ] The Captain approves at Tier 3, or an arbiter approves at Tier 2, a gated `write_file` or `mcp_invoke` that the vote rejected: the node fails with a BF-912 reason, nothing is written or invoked, and its dependents do not run (T3, T4, T4b).
- [ ] The same holds on BF-779's `propose_commit` route and on the except path (T5, T6, T6b, T6c).
- [ ] The Captain declines: the node fails, and no file exists (T2). The control run with an approving vote is unchanged (T1).
- [ ] Execute-then-vote approvals and ordinary retries are unchanged (T8, T9).
- [ ] All 29 mutation rows are killed and recorded as the campaign of record.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
