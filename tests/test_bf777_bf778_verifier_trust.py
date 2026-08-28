"""BF-777 / BF-778: the crew verification path must not reward the wrong thing.

Two defects that compounded, which is why they land together:

* **BF-777** -- ``_parse_verdict`` read ``accepted`` with ``bool(...)``, and
  ``bool("false")`` is ``True``. A judge that refused a result in string form
  was recorded as accepting it. LLMs emit string-typed booleans routinely.
* **BF-778** -- ``verify()`` then recorded the VERIFIER with
  ``success=verdict.accepted``, so accepting paid and refusing cost. Fixing the
  parser alone would have converted every newly-honest refusal into a trust
  penalty for the agent that caught it.

The parser's sibling ``_parse_session_verdict`` was already strict. Two parsers
in one class disagreeing about the same field is what made this findable.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_verifier import SubtaskVerifier
from probos.consensus.trust import TrustNetwork


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    async def complete(self, request: Any, **_kw: Any) -> Any:
        content = self._responses.pop(0) if self._responses else "{}"
        return SimpleNamespace(content=content)


class _FakeRegistry:
    def __init__(self, agent_ids: list[str]) -> None:
        self._agents = [SimpleNamespace(id=aid) for aid in agent_ids]

    def all(self) -> list[Any]:
        return list(self._agents)


class _FakeStore:
    async def get_work_item(self, work_item_id: str) -> Any:
        return None


class _FakeExecutor:
    def __init__(self, outcomes: list[WorkItemAgenticOutcome]) -> None:
        self._outcomes = list(outcomes)

    async def run(self, *, agent_id: str, instructions: str, task_text: str,
                  runtime: Any, department: str = "",
                  rank: str = "ensign") -> WorkItemAgenticOutcome:
        if self._outcomes:
            return self._outcomes.pop(0)
        return WorkItemAgenticOutcome(final_text="")


class _RecordingExecutor(_FakeExecutor):
    """Keeps every ``task_text`` so the critique fed to the producer is checkable."""

    def __init__(self, outcomes: list[WorkItemAgenticOutcome]) -> None:
        super().__init__(outcomes)
        self.tasks: list[str] = []

    async def run(self, *, task_text: str, **kw: Any) -> WorkItemAgenticOutcome:
        self.tasks.append(task_text)
        return await super().run(task_text=task_text, **kw)


def _accept(conf: float = 0.9, critique: str = "looks correct") -> str:
    return '{"accepted": true, "confidence": %s, "critique": "%s"}' % (conf, critique)


def _refute(conf: float = 0.8, critique: str = "missing requirement X") -> str:
    return '{"accepted": false, "confidence": %s, "critique": "%s"}' % (conf, critique)


def _result(output: str = "the produced output") -> SubtaskResult:
    return SubtaskResult(
        work_item_id="wi-1",
        spec_id="spec-1",
        agent_id="producer",
        output=output,
        status="done",
    )


def _make(responses, *, outcomes=None, trust=None, max_rounds=1):
    trust = trust or TrustNetwork()
    verifier = SubtaskVerifier(
        llm_client=_FakeLLM(responses),
        work_item_store=_FakeStore(),
        agent_registry=_FakeRegistry(["producer", "verifier"]),
        trust_network=trust,
        agentic_executor=_FakeExecutor(outcomes or []),
        runtime=SimpleNamespace(),
        max_convergence_rounds=max_rounds,
    )
    return verifier, trust


# ---------------------------------------------------------------- BF-777

@pytest.mark.parametrize(
    "raw_accepted",
    ["false", "False", "no", "0", "true", "True", [], {}, None, 0, 1, 1.0],
)
@pytest.mark.asyncio
async def test_non_bool_accepted_degrades_to_refuted(raw_accepted, caplog):
    """Every non-bool ``accepted`` refuses, in the conservative direction.

    ``"false"``/``"False"``/``"no"``/``"0"`` are the dangerous ones -- each was
    read as ACCEPTED before, because any non-empty string is truthy. The truthy
    cases (``"true"``, ``1``) are included deliberately: a permissive fix that
    only special-cased falsey strings would pass the dangerous half and still be
    wrong, since the contract is "not a bool means malformed", not "guess".
    """
    payload = json.dumps(
        {"accepted": raw_accepted, "confidence": 0.9, "critique": "why"}
    )
    verifier, _trust = _make([payload])

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.crew_verifier"):
        verdict = await verifier.verify(_result())

    assert verdict.accepted is False
    assert verdict.confidence == 0.0
    assert verdict.verification_defect is True
    # The critique is diagnostic only -- BF-777 stops it reaching the producer,
    # because a judge protocol error is not the producer's defect to fix.
    assert "Malformed judge verdict" in verdict.critique
    assert f"was {type(raw_accepted).__name__}" in verdict.critique
    assert "not bool" in verdict.critique
    # A silently-degraded judgement is the thing this bug was made of; the
    # degrade must be visible at WARNING, per the repo's logging standard.
    assert any(
        rec.levelno >= logging.WARNING and "BF-777" in rec.getMessage()
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_real_booleans_are_unchanged():
    verifier, _trust = _make([_accept()])
    assert (await verifier.verify(_result())).accepted is True

    verifier, _trust = _make([_refute()])
    refuted = await verifier.verify(_result())
    assert refuted.accepted is False
    assert refuted.critique == "missing requirement X"


@pytest.mark.asyncio
async def test_both_parsers_reject_a_string_typed_accepted():
    """Neither parser accepts a string-typed ``accepted`` (BF-777 #4).

    They REJECT IT DIFFERENTLY and that is fine -- the legacy parser
    honest-degrades to a refusal, the session parser raises. What is pinned
    here is only that neither one lets it through, so a future edit cannot
    widen the strict sibling to match the lenient one. This is deliberately
    NOT a claim that the two parsers agree in general; they differ on missing,
    extra and duplicate fields, on string confidence, and on empty critiques.
    """
    verifier, _trust = _make([])
    payload = json.dumps({"accepted": "false", "confidence": 0.9, "critique": "x"})

    lenient = verifier._parse_verdict(payload, "verifier")
    assert lenient.accepted is False
    assert lenient.verification_defect is True

    with pytest.raises(ValueError, match="session_verdict_invalid"):
        verifier._parse_session_verdict(payload, "verifier", 0)


# ---------------------------------------------------------------- BF-778

@pytest.mark.asyncio
async def test_refusal_writes_no_trust_at_judgement_time():
    verifier, trust = _make([_refute()])

    await verifier.verify(_result())

    assert trust.get_record("verifier") is None


@pytest.mark.asyncio
async def test_acceptance_writes_no_trust_at_judgement_time():
    verifier, trust = _make([_accept()])

    await verifier.verify(_result())

    assert trust.get_record("verifier") is None


@pytest.mark.asyncio
async def test_a_resolved_refusal_still_writes_no_trust():
    """Refuse, the producer changes the output, the judge accepts -- neutral.

    An earlier revision credited the refuser here, calling the sequence proof
    the refusal was "knowably correct". It is not: a whitespace-only edit
    satisfies it. Worse, the resulting gradient makes refusing weakly dominate
    accepting (accept pays 0; refuse pays p x credit), which is BF-778 mirrored
    rather than fixed. Real adjudication is BF-782's job; until it exists the
    ledger stays neutral.
    """
    verifier, trust = _make(
        [_refute(), _accept()],
        outcomes=[SimpleNamespace(final_text="corrected output")],
    )

    outcome = await verifier.converge(
        _result(), instructions="do it", task_text="task"
    )

    assert outcome.status == "converged"
    assert trust.get_record("verifier") is None


@pytest.mark.asyncio
async def test_a_whitespace_only_edit_earns_nothing():
    """The concrete farm the credit predicate was vulnerable to."""
    verifier, trust = _make(
        [_refute(), _accept()],
        outcomes=[SimpleNamespace(final_text="the produced output ")],
    )

    outcome = await verifier.converge(
        _result(output="the produced output"),
        instructions="do it",
        task_text="task",
    )

    assert outcome.status == "converged"
    assert trust.get_record("verifier") is None


@pytest.mark.asyncio
async def test_a_failed_rerun_writes_no_trust():
    """An executor exception is an infrastructure failure, not a bad refusal."""

    class _Boom:
        async def run(self, **_kw: Any) -> WorkItemAgenticOutcome:
            raise RuntimeError("executor exploded")

    trust = TrustNetwork()
    verifier = SubtaskVerifier(
        llm_client=_FakeLLM([_refute(), _accept()]),
        work_item_store=_FakeStore(),
        agent_registry=_FakeRegistry(["producer", "verifier"]),
        trust_network=trust,
        agentic_executor=_Boom(),
        runtime=SimpleNamespace(),
        max_convergence_rounds=1,
    )

    outcome = await verifier.converge(
        _result(), instructions="do it", task_text="task"
    )

    assert outcome.status == "converged"
    assert trust.get_record("verifier") is None


@pytest.mark.parametrize(
    "judge_reply, agents",
    [
        # non-bool `accepted`
        ('{"accepted": "false", "confidence": 0.9, "critique": "x"}', None),
        # `accepted` absent entirely -- previously defaulted to a plain refusal
        ('{"confidence": 0.9, "critique": "x"}', None),
        # unparseable
        ("not json at all", None),
        # no independent verifier: the producer is the only agent
        (None, ["producer"]),
    ],
    ids=["non-bool", "missing-field", "unparseable", "no-peer"],
)
@pytest.mark.asyncio
async def test_every_defect_source_terminates_without_rerunning(judge_reply, agents):
    """A VERIFIER failure must never be handed to the producer to fix.

    Parameterised across every path that constructs a defective verdict --
    a mutation flipping ``verification_defect=False`` on just ONE of them
    survived a test that only covered the non-bool branch.
    """
    executor = _RecordingExecutor([SimpleNamespace(final_text="new output")])
    trust = TrustNetwork()
    verifier = SubtaskVerifier(
        llm_client=_FakeLLM([judge_reply] if judge_reply else []),
        work_item_store=_FakeStore(),
        agent_registry=_FakeRegistry(agents or ["producer", "verifier"]),
        trust_network=trust,
        agentic_executor=executor,
        runtime=SimpleNamespace(),
        max_convergence_rounds=1,
    )

    outcome = await verifier.converge(
        _result(), instructions="do it", task_text="ORIGINAL TASK"
    )

    assert outcome.verdict.verification_defect is True
    assert outcome.status == "unverified"
    assert outcome.rounds == 0
    # The producer was never asked to fix the verifier's failure.
    assert executor.tasks == []
    assert trust.get_record("verifier") is None


@pytest.mark.asyncio
async def test_an_llm_judge_failure_is_a_defect():
    """The judge raising is a verifier failure, not a producer failure."""

    class _BoomLLM:
        async def complete(self, request: Any, **_kw: Any) -> Any:
            raise RuntimeError("judge exploded")

    executor = _RecordingExecutor([])
    trust = TrustNetwork()
    verifier = SubtaskVerifier(
        llm_client=_BoomLLM(),
        work_item_store=_FakeStore(),
        agent_registry=_FakeRegistry(["producer", "verifier"]),
        trust_network=trust,
        agentic_executor=executor,
        runtime=SimpleNamespace(),
        max_convergence_rounds=1,
    )

    outcome = await verifier.converge(
        _result(), instructions="do it", task_text="ORIGINAL TASK"
    )

    assert outcome.verdict.verification_defect is True
    assert outcome.status == "unverified"
    assert executor.tasks == []
    assert trust.get_record("verifier") is None


@pytest.mark.asyncio
async def test_a_rerun_that_reproduces_the_same_text_writes_nothing():
    """A non-empty re-run returning the ORIGINAL output resolves nothing."""
    verifier, trust = _make(
        [_refute(), _accept()],
        outcomes=[SimpleNamespace(final_text="the produced output")],
    )

    outcome = await verifier.converge(
        _result(output="the produced output"),
        instructions="do it",
        task_text="task",
    )

    assert outcome.status == "converged"
    assert trust.get_record("verifier") is None


@pytest.mark.parametrize(
    "second_reply",
    [
        '{"accepted": "false", "confidence": 0.9, "critique": "x"}',
        '{"confidence": 0.9, "critique": "x"}',
        "not json at all",
    ],
    ids=["non-bool", "missing-field", "unparseable"],
)
@pytest.mark.asyncio
async def test_a_defect_on_a_LATER_round_also_terminates(second_reply):
    """The defect guard must run after EVERY verify, not just the first.

    With the check only before the loop, a valid refusal followed by a defective
    second verdict re-ran the producer against
    ``"Unparseable judge response: not json"`` as though it were a critique --
    the exact thing the pre-loop guard exists to prevent, one round later.
    Observed before the fix: rounds=2, executor_task_count=2.
    """
    executor = _RecordingExecutor([SimpleNamespace(final_text="second output")])
    trust = TrustNetwork()
    verifier = SubtaskVerifier(
        llm_client=_FakeLLM([_refute(), second_reply]),
        work_item_store=_FakeStore(),
        agent_registry=_FakeRegistry(["producer", "verifier"]),
        trust_network=trust,
        agentic_executor=executor,
        runtime=SimpleNamespace(),
        max_convergence_rounds=3,
    )

    outcome = await verifier.converge(
        _result(), instructions="do it", task_text="ORIGINAL TASK"
    )

    assert outcome.verdict.verification_defect is True
    assert outcome.status == "unverified"
    assert outcome.rounds == 1
    # Exactly ONE producer re-run -- the one driven by the VALID refusal.
    assert len(executor.tasks) == 1
    assert "missing requirement X" in executor.tasks[0]
    assert trust.get_record("verifier") is None


@pytest.mark.asyncio
async def test_a_valid_verdict_is_not_marked_defective():
    """The flag must discriminate, not be always-on."""
    verifier, _trust = _make([_accept()])
    assert (await verifier.verify(_result())).verification_defect is False

    verifier, _trust = _make([_refute()])
    assert (await verifier.verify(_result())).verification_defect is False


@pytest.mark.asyncio
async def test_no_verifier_is_scored_anywhere_in_convergence():
    """Verifier A refuses, verifier B accepts -- neither is scored.

    A mutation scoring ``verdict.verifier_agent_id`` (the ACCEPTING judge)
    instead of the refuser passed every other test in an earlier revision.
    Neutrality kills both variants at once.
    """
    trust = TrustNetwork()
    verifier = SubtaskVerifier(
        llm_client=_FakeLLM([_refute(), _accept()]),
        work_item_store=_FakeStore(),
        agent_registry=_FakeRegistry(["producer", "verifier"]),
        trust_network=trust,
        agentic_executor=_FakeExecutor(
            [SimpleNamespace(final_text="corrected output")]
        ),
        runtime=SimpleNamespace(),
        max_convergence_rounds=1,
    )
    picks = iter(["verifier-a", "verifier-b"])
    verifier._pick_independent_verifier = lambda _producer: next(picks)

    outcome = await verifier.converge(
        _result(), instructions="do it", task_text="task"
    )

    assert outcome.status == "converged"
    assert trust.get_record("verifier-a") is None
    assert trust.get_record("verifier-b") is None


@pytest.mark.asyncio
async def test_unresolved_refusal_writes_no_trust():
    """Still refuted after the last round: neither upheld nor contradicted."""
    verifier, trust = _make(
        [_refute(), _refute()],
        outcomes=[SimpleNamespace(final_text="still wrong")],
    )

    outcome = await verifier.converge(
        _result(), instructions="do it", task_text="task"
    )

    assert outcome.status == "unverified"
    assert trust.get_record("verifier") is None


@pytest.mark.asyncio
async def test_immediate_acceptance_writes_no_trust():
    """rounds=0: nothing was refused, so nothing has resolved."""
    verifier, trust = _make([_accept()])

    outcome = await verifier.converge(
        _result(), instructions="do it", task_text="task"
    )

    assert outcome.rounds == 0
    assert trust.get_record("verifier") is None
