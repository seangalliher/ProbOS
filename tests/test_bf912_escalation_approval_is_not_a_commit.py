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
