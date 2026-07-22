"""AD-860: adversarial verification + convergence gate for crew sub-tasks.

``SubtaskVerifier`` (semantic sibling of ``RedTeamAgent``) runs an *independent*
crew member as an LLM judge that tries to refute a :class:`SubtaskResult` against
its declared acceptance criterion (``expected_output``) or — when none was
declared — a free-text "find the flaw" critique. A refuted result is re-run
through the public AD-859a :class:`WorkItemAgenticExecutor` with the critique
appended, up to ``max_convergence_rounds`` (Safety Budget). A still-refuted
result is escalated as ``unverified`` — never silently accepted.

Fixtures use a REAL :class:`TrustNetwork` (no MagicMock at the trust boundary —
BF-287: MagicMock auto-creates phantom attributes and would mask a wrong API
name). The LLM judge, store, registry, and AD-859a executor are small ``_Fake*``
stubs with the exact public shapes the verifier calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_verifier import (
    ConvergenceOutcome,
    SubtaskVerifier,
    VerificationVerdict,
)
from probos.consensus.trust import TrustNetwork
from probos.types import Vote


# ------------------------------------------------------------------ fakes

class _FakeLLM:
    """Scripted LLM judge: ``complete`` pops the next response and records the
    request so prompt anchoring can be asserted."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kw: Any) -> Any:
        self.requests.append(request)
        content = self._responses.pop(0) if self._responses else "{}"
        return SimpleNamespace(content=content)


class _FakeRegistry:
    """Returns the configured agents from ``all()`` (BaseAgent uses ``.id``)."""

    def __init__(self, agent_ids: list[str]) -> None:
        self._agents = [SimpleNamespace(id=aid) for aid in agent_ids]

    def all(self) -> list[Any]:
        return list(self._agents)


class _FakeStore:
    """Returns a work item whose ``metadata`` may carry ``expected_output``."""

    def __init__(self, metadata: dict[str, Any] | None) -> None:
        self._metadata = metadata

    async def get_work_item(self, work_item_id: str) -> Any:
        if self._metadata is None:
            return None
        return SimpleNamespace(metadata=dict(self._metadata))


class _FakeExecutor:
    """AD-859a executor stub: records every ``run`` call and returns scripted
    outcomes (so convergence re-runs can be asserted)."""

    def __init__(self, outcomes: list[WorkItemAgenticOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def run(self, *, agent_id: str, instructions: str, task_text: str,
                  runtime: Any, department: str = "", rank: str = "ensign") -> WorkItemAgenticOutcome:
        self.calls.append({
            "agent_id": agent_id,
            "instructions": instructions,
            "task_text": task_text,
        })
        if self._outcomes:
            return self._outcomes.pop(0)
        return WorkItemAgenticOutcome(final_text="")


def _accept(conf: float = 0.9, critique: str = "looks correct") -> str:
    return '{"accepted": true, "confidence": %s, "critique": "%s"}' % (conf, critique)


def _refute(conf: float = 0.8, critique: str = "missing requirement X") -> str:
    return '{"accepted": false, "confidence": %s, "critique": "%s"}' % (conf, critique)


def _result(output: str = "the produced output", agent_id: str = "producer") -> SubtaskResult:
    return SubtaskResult(
        work_item_id="wi-1",
        spec_id="spec-1",
        agent_id=agent_id,
        output=output,
        status="done",
    )


def _make_verifier(
    *,
    responses: list[str],
    agent_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    outcomes: list[WorkItemAgenticOutcome] | None = None,
    trust: TrustNetwork | None = None,
    max_rounds: int = 2,
) -> tuple[SubtaskVerifier, _FakeLLM, _FakeExecutor, TrustNetwork]:
    llm = _FakeLLM(responses)
    executor = _FakeExecutor(outcomes or [])
    trust = trust or TrustNetwork()
    verifier = SubtaskVerifier(
        llm_client=llm,
        work_item_store=_FakeStore(metadata),
        agent_registry=_FakeRegistry(agent_ids if agent_ids is not None else ["producer", "verifier"]),
        trust_network=trust,
        agentic_executor=executor,
        runtime=SimpleNamespace(),
        max_convergence_rounds=max_rounds,
    )
    return verifier, llm, executor, trust


# ------------------------------------------------------------------ verify

@pytest.mark.asyncio
async def test_verify_accepted_records_positive_trust():
    verifier, _llm, _ex, trust = _make_verifier(responses=[_accept()])

    verdict = await verifier.verify(_result())

    assert verdict.accepted is True
    assert verdict.verifier_agent_id == "verifier"
    assert verdict.verifier_agent_id != "producer"
    # Real TrustNetwork: a success raises the verifier's score above the prior.
    assert trust.get_record("verifier") is not None
    assert trust.get_score("verifier") > 0.5


@pytest.mark.asyncio
async def test_verify_refuted_records_negative_trust():
    verifier, _llm, _ex, trust = _make_verifier(responses=[_refute()])

    verdict = await verifier.verify(_result())

    assert verdict.accepted is False
    assert verdict.critique == "missing requirement X"
    assert trust.get_record("verifier") is not None
    assert trust.get_score("verifier") < 0.5


@pytest.mark.asyncio
async def test_verify_busy_trust_preserves_completed_verdict():
    trust = TrustNetwork()
    trust.record_outcome = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("trust_write_in_progress"),
    )
    verifier, _llm, _ex, _trust = _make_verifier(
        responses=[_accept()],
        trust=trust,
    )

    verdict = await verifier.verify(_result())

    assert verdict.accepted is True
    assert verdict.verifier_agent_id == "verifier"


@pytest.mark.asyncio
async def test_verify_other_trust_runtime_error_propagates():
    trust = TrustNetwork()
    trust.record_outcome = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("trust store defect"),
    )
    verifier, _llm, _ex, _trust = _make_verifier(
        responses=[_accept()],
        trust=trust,
    )

    with pytest.raises(RuntimeError, match="^trust store defect$"):
        await verifier.verify(_result())


@pytest.mark.asyncio
async def test_verify_anchors_prompt_to_expected_output():
    verifier, llm, _ex, _trust = _make_verifier(
        responses=[_accept()],
        metadata={"expected_output": "MUST return a sorted list"},
    )

    await verifier.verify(_result())

    prompt = llm.requests[0].prompt
    assert "DECLARED ACCEPTANCE CRITERION" in prompt
    assert "MUST return a sorted list" in prompt


@pytest.mark.asyncio
async def test_verify_free_text_path_when_expected_absent():
    verifier, llm, _ex, _trust = _make_verifier(
        responses=[_accept()],
        metadata={"plan_version": 1},  # present item, no expected_output key
    )

    await verifier.verify(_result())

    prompt = llm.requests[0].prompt
    assert "DECLARED ACCEPTANCE CRITERION" not in prompt
    assert "No explicit acceptance criterion was declared" in prompt


@pytest.mark.asyncio
async def test_verify_no_independent_agent_degrades_unverified():
    # Registry holds ONLY the producer — an agent is never allowed to verify
    # itself, so the verdict honest-degrades with no trust write.
    verifier, _llm, _ex, trust = _make_verifier(
        responses=[_accept()], agent_ids=["producer"],
    )

    verdict = await verifier.verify(_result())

    assert verdict.accepted is False
    assert verdict.verifier_agent_id == ""
    # No trust recorded for anyone (degrade path skips record_outcome).
    assert trust.get_record("producer") is None


@pytest.mark.asyncio
async def test_verify_never_self_verifies():
    verifier, _llm, _ex, _trust = _make_verifier(
        responses=[_accept()], agent_ids=["producer", "reviewer-b"],
    )

    verdict = await verifier.verify(_result(agent_id="producer"))

    assert verdict.verifier_agent_id == "reviewer-b"


@pytest.mark.asyncio
async def test_verify_non_json_response_degrades_refuted():
    verifier, _llm, _ex, _trust = _make_verifier(responses=["the result is fine, trust me"])

    verdict = await verifier.verify(_result())

    assert verdict.accepted is False
    assert verdict.verifier_agent_id == "verifier"


# ------------------------------------------------------------------ converge

@pytest.mark.asyncio
async def test_converge_accepted_first_pass_no_rerun():
    verifier, _llm, executor, _trust = _make_verifier(responses=[_accept()])

    outcome = await verifier.converge(_result(), instructions="do X", task_text="task X")

    assert isinstance(outcome, ConvergenceOutcome)
    assert outcome.status == "converged"
    assert outcome.rounds == 0
    assert executor.calls == []  # no re-run when the first verdict accepts


@pytest.mark.asyncio
async def test_converge_refuted_then_accepted_reruns_with_critique():
    verifier, _llm, executor, _trust = _make_verifier(
        responses=[_refute(critique="needs error handling"), _accept()],
        outcomes=[WorkItemAgenticOutcome(final_text="revised output with error handling")],
    )
    result = _result(output="first draft")

    outcome = await verifier.converge(result, instructions="impl", task_text="build the thing")

    assert outcome.status == "converged"
    assert outcome.rounds == 1
    assert len(executor.calls) == 1
    # The critique must be threaded into the re-run task text.
    assert "needs error handling" in executor.calls[0]["task_text"]
    assert "build the thing" in executor.calls[0]["task_text"]
    # The re-run output replaces the prior draft.
    assert result.output == "revised output with error handling"


@pytest.mark.asyncio
async def test_converge_max_rounds_then_unverified_not_silently_accepted():
    verifier, _llm, executor, _trust = _make_verifier(
        responses=[_refute(), _refute(), _refute()],
        outcomes=[
            WorkItemAgenticOutcome(final_text="attempt 2"),
            WorkItemAgenticOutcome(final_text="attempt 3"),
        ],
        max_rounds=2,
    )

    outcome = await verifier.converge(_result(), instructions="i", task_text="t")

    assert outcome.status == "unverified"  # never silently accepted
    assert outcome.rounds == 2
    assert len(executor.calls) == 2


# ------------------------------------------------------------------ vote map

def test_verdict_to_vote_maps_real_vote_shape():
    verdict = VerificationVerdict(
        accepted=True, confidence=0.75, critique="ok", verifier_agent_id="v-7",
    )

    vote = SubtaskVerifier.verdict_to_vote(verdict)

    assert isinstance(vote, Vote)
    assert vote.agent_id == "v-7"
    assert vote.approved is True
    assert vote.confidence == 0.75
    assert vote.reason == "ok"
