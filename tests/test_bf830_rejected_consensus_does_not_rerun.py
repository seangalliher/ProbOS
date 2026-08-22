"""BF-830 (#1295): a REJECTED consensus vote re-ran the act twice more.

`submit_intent_with_consensus` broadcasts at step 1 — agents RUN — and evaluates
quorum at step 2 (`runtime.py:3959-3981`). A rejection then entered the Tier 1
escalation retry, which calls that same method again, up to `max_retries = 2`.

So one promoted `run_command` whose quorum rejected performed the command THREE
times: the original broadcast plus two retries. Measured through the real
`EscalationManager`: two re-executions inside the ladder, on top of the one that
put it there.

It was the ordinary path, not an edge case — the decomposer instructs the model
to promote every shell command::

    decomposer.py:123   6. All run_command intents MUST have "use_consensus": true.

Tier 1's premise ("try again, perhaps with a different agent") is sound for a
transport or agent failure and wrong for a GOVERNANCE outcome: the crew
considered the act and declined it. Retrying is not recovery, it is the act
happening again.

`write_file` was already safe and shows why — escalation routes it to
`submit_write_with_consensus`, which proposes and only commits after the vote,
so retrying a PROPOSAL costs nothing. Every other intent took the `else` branch.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.consensus.escalation import EscalationManager
from probos.consensus.quorum import ConsensusOutcome
from probos.types import EscalationTier

CONSENSUS = {"category": "consensus"}


class _Runtime:
    """Counts what actually executed, the way the broadcast does."""

    def __init__(self, outcome=ConsensusOutcome.REJECTED) -> None:
        self.executed: list[str] = []
        self.proposed: list[str] = []
        self._outcome = outcome

    async def submit_intent_with_consensus(self, *, intent, params, timeout=10.0):
        # Step 1 broadcasts (agents RUN); step 2 evaluates. Both, in order.
        self.executed.append(intent)
        return {
            "results": [],
            "consensus": SimpleNamespace(outcome=self._outcome),
        }

    async def submit_write_with_consensus(self, *, path, content, timeout=10.0):
        # Proposes; commits only after the vote. Nothing is executed on reject.
        self.proposed.append(path)
        return {
            "results": [],
            "consensus": SimpleNamespace(outcome=self._outcome),
        }

    async def submit_intent(self, *, intent, params, timeout=10.0):
        self.executed.append(intent)
        return []


def _node(intent: str = "run_command", *, use_consensus: bool = True):
    return SimpleNamespace(
        id="t1",
        intent=intent,
        params={"command": "rm -rf /important", "path": "/tmp/x", "content": "y"},
        use_consensus=use_consensus,
        depends_on=[],
    )


def _manager(runtime, **kw) -> EscalationManager:
    return EscalationManager(runtime=runtime, llm_client=None, **kw)


# ── the defect ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_rejected_command_is_not_run_again() -> None:
    """The headline. Before the fix this ladder executed it twice more."""
    runtime = _Runtime()
    result = await _manager(runtime).escalate(
        _node(), "consensus rejected", dict(CONSENSUS)
    )

    assert runtime.executed == [], (
        f"a rejected act was performed {len(runtime.executed)} more time(s)"
    )
    assert result.resolved is False


@pytest.mark.asyncio
async def test_the_skip_is_recorded_not_merely_absent() -> None:
    """Absence from `tiers_attempted` cannot say whether RETRY was skipped or
    tried and failed. An observer must be able to tell."""
    result = await _manager(_Runtime()).escalate(
        _node(), "consensus rejected", dict(CONSENSUS)
    )

    assert EscalationTier.RETRY not in result.tiers_attempted
    assert EscalationTier.RETRY.value in result.tiers_skipped
    assert "again" in result.tiers_skipped[EscalationTier.RETRY.value]
    # And it survives serialization, which is how the DAG records it.
    assert EscalationTier.RETRY.value in result.to_dict()["tiers_skipped"]


@pytest.mark.asyncio
async def test_the_cascade_still_reaches_the_later_tiers() -> None:
    """Skipping Tier 1 must not skip the escalation itself."""
    result = await _manager(_Runtime()).escalate(
        _node(), "consensus rejected", dict(CONSENSUS)
    )
    assert EscalationTier.USER in result.tiers_attempted


class _Arbiter:
    """A non-mock LLM whose arbiter returns a decision of our choosing."""

    def __init__(self, action: str) -> None:
        self._action = action
        self.calls = 0

    async def complete(self, request=None, **kw):  # noqa: ANN001
        import json
        from types import SimpleNamespace

        self.calls += 1
        # ``error`` is read before ``content`` (escalation.py:291). Omitting it
        # made an earlier version of this double raise, so the arbiter never
        # reached the ``modify`` branch and both tests passed vacuously.
        return SimpleNamespace(
            error=None,
            content=json.dumps(
                {
                    "action": self._action,
                    "reason": "the arbiter has opinions",
                    "params": {"command": "echo modified"},
                }
            ),
        )


@pytest.mark.asyncio
async def test_the_arbiter_cannot_re_run_a_declined_act_with_new_params() -> None:
    """Tier 2's `modify` branch RE-SUBMITS, so "Tier 2 does not execute" was
    false as originally written.

    Measured by review with a real arbiter: one extra execution of
    `run_command`, with `attempts` still reporting 0 — so the run was hidden
    as well as unauthorised. An arbiter deciding the act would be acceptable
    with different parameters is a PROPOSAL; only the Captain can authorise a
    declined act.

    The earlier version of this test passed `llm_client=None`, so Tier 2 never
    ran and it passed with the fix reverted.
    """
    runtime = _Runtime()
    arbiter = _Arbiter("modify")
    manager = EscalationManager(runtime=runtime, llm_client=arbiter)

    await manager.escalate(_node(), "consensus rejected", dict(CONSENSUS))

    assert arbiter.calls == 1, "the arbiter was never reached; this proves nothing"
    assert runtime.executed == [], (
        f"the arbiter re-ran a declined act: {runtime.executed}"
    )


@pytest.mark.asyncio
async def test_the_arbiter_may_still_modify_an_ORDINARY_failure() -> None:
    """The regression the fix above could cause. `modify` is Tier 2's whole
    point for a non-governance failure and must keep working.

    A non-consensus node, so Tier 1 exhausts (``submit_intent`` returns no
    successful result) and the cascade actually reaches the arbiter — with a
    promoted node Tier 1 succeeds and Tier 2 never runs, which is what an
    earlier version of this test measured instead.
    """
    runtime = _Runtime()
    arbiter = _Arbiter("modify")
    manager = EscalationManager(runtime=runtime, llm_client=arbiter)

    await manager.escalate(
        _node(use_consensus=False),
        "connection reset",
        {"intent": "run_command", "params": {}},
    )
    assert arbiter.calls >= 1, "the arbiter was never reached; this proves nothing"
    assert runtime.executed, "an ordinary failure must still reach the arbiter's retry"


@pytest.mark.asyncio
async def test_the_captain_is_told_which_tier_was_skipped() -> None:
    """The Captain is being asked to approve an act the crew declined. Why the
    retry was skipped is part of that decision, so it must reach the prompt and
    not only the returned result."""
    seen: dict = {}

    async def _callback(question: str, context: dict):
        seen.update(context)
        return False

    manager = _manager(_Runtime(), user_callback=_callback)
    await manager.escalate(_node(), "consensus rejected", dict(CONSENSUS))

    assert EscalationTier.RETRY.value in seen.get("tiers_skipped", {})


# ── the regression a careless fix causes ──────────────────────────


@pytest.mark.asyncio
async def test_an_ordinary_failure_still_gets_its_full_retry_ladder() -> None:
    """The thing that must NOT change. A transport or agent failure is exactly
    what Tier 1 is for, and suppressing it for everything would trade one
    defect for another."""
    runtime = _Runtime()
    manager = _manager(runtime, max_retries=2)

    result = await manager.escalate(
        _node(), "connection reset", {"intent": "run_command", "params": {}}
    )

    assert len(runtime.executed) == 2, runtime.executed
    assert EscalationTier.RETRY in result.tiers_attempted
    assert result.tiers_skipped == {}


@pytest.mark.asyncio
async def test_a_missing_category_keeps_the_old_behaviour() -> None:
    """Every caller that has not been taught the category is unchanged, so the
    fix cannot silently disarm a ladder somewhere else."""
    runtime = _Runtime()
    await _manager(runtime).escalate(_node(), "boom", {})
    assert len(runtime.executed) == 2


@pytest.mark.asyncio
async def test_an_approving_retry_still_resolves() -> None:
    """Tier 1 must still be able to succeed for a non-governance failure."""
    runtime = _Runtime(outcome=ConsensusOutcome.APPROVED)
    result = await _manager(runtime).escalate(
        _node(), "transient", {"intent": "run_command", "params": {}}
    )
    assert result.resolved is True
    assert result.tier is EscalationTier.RETRY


# ── write_file, the path that was already correct ─────────────────


@pytest.mark.asyncio
async def test_write_file_still_commits_nothing_on_a_rejection() -> None:
    """It proposes rather than executing, so it was never multiplying. It must
    stay on that path and must not start executing."""
    runtime = _Runtime()
    await _manager(runtime).escalate(
        _node("write_file"), "consensus rejected", dict(CONSENSUS)
    )

    assert runtime.executed == []
    assert runtime.proposed == [], "a rejection must not re-propose either"


@pytest.mark.asyncio
async def test_write_file_under_an_ordinary_failure_is_unchanged() -> None:
    """Retrying a PROPOSAL costs nothing, so that ladder keeps running."""
    runtime = _Runtime()
    await _manager(runtime).escalate(
        _node("write_file"), "disk hiccup", {"intent": "write_file", "params": {}}
    )
    assert len(runtime.proposed) == 2
    assert runtime.executed == []


# ── the seam: the decomposer must actually send the category ──────


def test_the_rejection_door_labels_the_failure() -> None:
    """The manager is TOLD the category, not asked to infer it.

    The prompt for this fix suggested `_handle_rejection` already carried
    `category` into the escalation context. It did not — it put that value on
    the ESCALATION_START event and passed only intent and params to
    `escalate()`. Without this the fix is inert, which is the half-chain
    failure this repository sees most.
    """
    import inspect

    from probos.cognitive.decomposer import DAGExecutor

    source = inspect.getsource(DAGExecutor._handle_rejection)
    assert '"category": "consensus"' in source
    escalate_call = source.split("escalation_manager.escalate(")[1]
    assert '"category": "consensus"' in escalate_call.split(")")[0], (
        "the category must reach escalate(), not only the event"
    )


@pytest.mark.asyncio
async def test_a_failing_listener_does_not_re_run_the_command() -> None:
    """Observing a node is not part of executing it.

    Both the event emission and the checkpoint write sit AFTER the act, inside
    the executor's broad `except`, which escalates — and escalation's Tier 1
    re-executes. Review measured a single consensus-rejected `run_command`
    becoming THREE executions because one event listener raised, since the
    fallback `escalate()` carried no category and took the retry ladder.
    """
    from probos.cognitive.decomposer import DAGExecutor
    from probos.types import TaskDAG, TaskNode

    runtime = _Runtime()
    executor = DAGExecutor.__new__(DAGExecutor)
    executor.runtime = runtime
    executor.escalation_manager = _manager(runtime)
    executor._checkpoint_dir = None
    executor.attention = None

    node = TaskNode(
        id="t1", intent="run_command",
        params={"command": "rm -rf /important"}, use_consensus=True,
    )
    dag = TaskDAG(nodes=[node], source_text="run it")

    async def _hostile(event, payload):
        # Only the POST-execution events. An earlier version raised on
        # NODE_START too, which aborts before the node ever runs -- zero
        # executions, so the assertion passed without exercising anything.
        if "start" not in str(event).lower():
            raise RuntimeError("the listener is broken")

    try:
        await executor._execute_node(node, dag, {}, on_event=_hostile)
    except Exception:
        pass

    assert runtime.executed, "premise: the node must actually have executed"
    assert len(runtime.executed) == 1, (
        f"a broken listener caused {len(runtime.executed)} executions"
    )


@pytest.mark.asyncio
async def test_a_listener_fault_is_not_escalated_at_all() -> None:
    """Belt and braces are two different guarantees, and both are asserted.

    The category on the fallback door stops a listener fault from RE-EXECUTING.
    The guard around the emission stops it from being escalated in the first
    place. With only the former, a broken listener would still turn a completed
    node into an escalation — the Captain consulted about a failure that did
    not happen.
    """
    from probos.cognitive.decomposer import DAGExecutor
    from probos.types import TaskDAG, TaskNode

    runtime = _Runtime(outcome=ConsensusOutcome.APPROVED)
    executor = DAGExecutor.__new__(DAGExecutor)
    executor.runtime = runtime
    executor.escalation_manager = _manager(runtime)
    executor._checkpoint_dir = None
    executor.attention = None

    node = TaskNode(
        id="t1", intent="run_command", params={"command": "echo ok"},
        use_consensus=True,
    )
    dag = TaskDAG(nodes=[node], source_text="run it")

    async def _hostile(event, payload):
        if "start" not in str(event).lower():
            raise RuntimeError("the listener is broken")

    await executor._execute_node(node, dag, {}, on_event=_hostile)

    assert node.status == "completed", node.status
    assert getattr(node, "escalation_result", None) is None, (
        "a broken listener escalated a node that succeeded"
    )
    assert len(runtime.executed) == 1, runtime.executed
