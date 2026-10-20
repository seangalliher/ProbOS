"""AD-1343 S1 (#1595), amendment A2: a stopped agent is not eligible for crew work and its refuted result is not re-run (T32, T33).

``prompts/ad-1343-a2-amendment.md`` (Sections 16 to 18) closes the crew side of the Captain's stop. A cross-family review found that a
crew subtask and a correction re-run for a stopped agent were still started, because the S1 sinks guard the agent's own turns and
tool calls but not the crew executor's admission or the verifier's correction rounds. A2 makes the stop part of the answer to
"may this agent do crew work": the unit tests of that amendment are here, over a real ``AgentStopService`` in ``tmp_path``.

* T32: ``CrewAssignmentResolver.check_eligibility`` answers ``CrewWorkerEligibility(None, "stopped")`` for a stopped agent before any
  lookup and without counting a refusal (asking about a candidate refuses no work); a new subtask goes to an eligible colleague.
* T33: ``SubtaskVerifier`` does not re-run a stopped producer for a correction. The legacy loop ends the refuted result
  ``unverified``; the session loop raises ``AgentStopped`` and records no outcome (A3, R2: an exhaustion record charged the stopped
  producer), the owned-steps port is never asked to admit the correction, and a stop that lands after the check, so that the
  executor's run entry refuses, is re-raised and never a fault. Finalization and trust: tests/test_ad1343_stop_crossing_finalizer.py.

Each test holds its own golden: with no order in force, the same call routes exactly as before and the stop module and the changed
module log nothing at INFO or above. The crossing of eligibility through a real crew executor is
``tests/test_ad1343_stop_crossing_crew.py`` (X6), which imports the helpers of this file.

Every store lives in ``tmp_path``; the live data directory is never read. Nothing here sleeps, waits on a timer or orders anything
by wall-clock time: the service's clock is injected, every wait on a run is bounded with ``asyncio.wait_for``, and the verifier's
collaborators are small test-local fakes. The real ``WorkItemAgenticExecutor`` is used wherever the run entry is the point, with a
model client that counts its calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos import agent_stop
from probos.agent_stop import AgentStopService
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor, WorkItemAgenticOutcome
from probos.cognitive.crew_assignment import CrewAssignmentResolver, CrewWorkerEligibility
from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_finalizer import CrewSessionFinalizer
from probos.cognitive.crew_verifier import ConvergenceOutcome, SessionConvergenceOutcome, SubtaskVerifier
from probos.consensus.trust import TrustNetwork
from probos.consultation.dispatch import WorkItemSpec
from probos.ontology import VesselOntologyService
from probos.tools.registry import ToolRegistry
from tests.test_ad1343_agent_stop import AGENT, LIFT_REASON, PRIVATE_FRAGMENT, REASON, _Clock, _service
from tests.test_ad864_crew_assignment import _capability_registry, _make_registry

_BOUND = 30.0  # seconds: a bound for a wedged run, far above what these fakes need
STOP_LOGGER = "probos.agent_stop"
ASSIGNMENT_LOGGER = "probos.cognitive.crew_assignment"
VERIFIER_LOGGER = "probos.cognitive.crew_verifier"

PARENT = "ad1343-parent-0001"
CHILD = "ad1343-child-0001"
THREAD = "ad1343-thread-0001"
SPEC_ID = "ad1343-spec-0001"
INSTRUCTIONS = "AD-1343: do the work and report only what you verified"
TASK = "AD-1343: produce the evidence for requirement X"
FIRST_DRAFT = "AD-1343 first draft: the producer's first answer"
CORRECTED = "AD-1343 correction: the producer's revised answer"
CRITIQUE = "AD-1343 critique: requirement X is missing"

_REFUTE = json.dumps({"accepted": False, "confidence": 0.8, "critique": CRITIQUE})
_ACCEPT = json.dumps({"accepted": True, "confidence": 0.9, "critique": "AD-1343 judge: the correction satisfies requirement X"})

SPEC_ANALYSIS = WorkItemSpec(spec_id="ad1343-spec-analysis", title="analysis", capability="analysis")
SPEC_ENGINEERING = WorkItemSpec(spec_id="ad1343-spec-engineering", title="engineering", department="engineering")


def _loud(caplog: pytest.LogCaptureFixture, *loggers: str) -> list[tuple[str, int, str]]:
    """Every record at INFO or above that the named loggers wrote."""
    return [(r.name, r.levelno, r.getMessage()) for r in caplog.records if r.name in loggers and r.levelno >= logging.INFO]


def _logged_as_a_fault(caplog: pytest.LogCaptureFixture) -> list[str]:
    """What the verifier logged at WARNING or above with a traceback: how it logs a failed re-run it then degrades from."""
    return [r.getMessage() for r in caplog.records if r.name == VERIFIER_LOGGER and r.levelno >= logging.WARNING and r.exc_info]


def _runtime(service: AgentStopService) -> SimpleNamespace:
    """What the verifier and the executors read of the ship: the stop service as ``agent_stops`` and a tool registry gated by it."""
    registry = ToolRegistry()
    registry.set_stop_gate(service)
    return SimpleNamespace(agent_stops=service, tool_registry=registry)


class _CountingLLM:
    """A model client that counts every call: a run that must not start makes none."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def complete(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(request)
        raise AssertionError("AD-1343: the model was called for a run that must not start")


@contextlib.asynccontextmanager
async def _native_workers(tmp_path: Path, service: AgentStopService | None) -> AsyncIterator[SimpleNamespace]:
    """The ``native_workers`` shape of tests/test_ad859_crew_executor.py, its resolver given the stop service.

    Three live agents on a real ontology: ``facilitator-1`` (architect) and the builders ``builder-1`` (highest trust) and
    ``builder-2``, the two of them the only agents with the ``analysis`` capability.
    """
    ontology_path = tmp_path / "worker-ontology"
    shutil.copytree(Path(__file__).resolve().parents[1] / "config" / "ontology", ontology_path)
    data_path = tmp_path / "worker-data"
    data_path.mkdir()
    ontology = VesselOntologyService(ontology_path, data_dir=data_path)
    await ontology.initialize()
    registry = await _make_registry([
        ("architect", "facilitator-1"),
        ("builder", "builder-1"),
        ("builder", "builder-2"),
    ])
    agents = registry.all()
    trust = TrustNetwork()
    for _ in range(3):
        trust.record_outcome("builder-1", True)
    capabilities = _capability_registry({"builder-1": ["analysis"], "builder-2": ["analysis"]})
    resolver = CrewAssignmentResolver(
        capability_registry=capabilities,
        ontology=ontology,
        trust_network=trust,
        agent_registry=registry,
        agent_stops=service,
    )
    try:
        for agent in agents:
            await agent.start()
            assert agent.is_alive
        yield SimpleNamespace(
            registry=registry, ontology=ontology, trust=trust,
            capabilities=capabilities, resolver=resolver, agents=agents,
        )
    finally:
        for agent in agents:
            await agent.stop()


# T32
async def test_a_stopped_agent_is_not_eligible_for_crew_work(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    async with _service(tmp_path / "stops", clock=_Clock()) as service, _native_workers(tmp_path, service) as workers:
        resolver = workers.resolver
        ids = ("facilitator-1", "builder-1", "builder-2")
        assert sorted(agent.id for agent in workers.agents) == sorted(ids)  # premise: the roster the amendment's row names
        # the same collaborators, wired as before A2 (no stop service): the answers the unstopped path must equal
        baseline = CrewAssignmentResolver(
            capability_registry=workers.capabilities, ontology=workers.ontology,
            trust_network=workers.trust, agent_registry=workers.registry,
        )

        # Golden: with no order in force every agent is eligible and the highest-trust builder is assigned, exactly as the
        # resolver wired without the service answers, and neither the stop module nor the resolver logs at INFO or above.
        with caplog.at_level(logging.INFO):
            eligibility = [resolver.check_eligibility(agent_id) for agent_id in ids]
            by_capability = resolver.resolve(SPEC_ANALYSIS)
            by_department = resolver.resolve(SPEC_ENGINEERING)
        assert [answer.reason for answer in eligibility] == ["eligible"] * 3
        assert all(answer.identity is not None for answer in eligibility)
        assert eligibility == [baseline.check_eligibility(agent_id) for agent_id in ids]
        assert (by_capability.agent_id, by_department.agent_id) == ("builder-1", "builder-1")
        assert (by_capability, by_department) == (baseline.resolve(SPEC_ANALYSIS), baseline.resolve(SPEC_ENGINEERING))
        assert _loud(caplog, STOP_LOGGER, ASSIGNMENT_LOGGER) == []

        record = (await service.issue_stop("builder-1", reason=REASON)).record
        assert service.stop_for("builder-1") == record

        # the stopped agent is not eligible, and the answer carries no identity
        assert resolver.check_eligibility("builder-1") == CrewWorkerEligibility(None, "stopped")
        # the order names one agent
        assert resolver.check_eligibility("builder-2").reason == "eligible"
        assert resolver.check_eligibility("facilitator-1").reason == "eligible"
        # a new subtask goes to an eligible colleague, whichever hint resolves it
        assert resolver.resolve(SPEC_ANALYSIS).agent_id == "builder-2"
        assert resolver.resolve(SPEC_ENGINEERING).agent_id == "builder-2"
        # asking about a candidate refuses no work: nothing is counted
        assert service.refused_counts(record.stop_id) == {}
        # a resolver wired without the service does not see the order: the stop is the injected service's, nothing else's
        assert baseline.check_eligibility("builder-1").reason == "eligible"
        assert baseline.resolve(SPEC_ANALYSIS).agent_id == "builder-1"

        # the stop is answered before any lookup: an agent the registry does not hold is "stopped", not "missing"
        assert resolver.check_eligibility("ghost-1").reason == "missing"  # premise: what an unregistered, unstopped agent is
        await service.issue_stop("ghost-1", reason=REASON)
        assert resolver.check_eligibility("ghost-1") == CrewWorkerEligibility(None, "stopped")

        # the Captain's lift restores the agent to crew work
        await service.lift_stop("builder-1", reason=LIFT_REASON)
        assert resolver.check_eligibility("builder-1").reason == "eligible"
        assert resolver.resolve(SPEC_ANALYSIS).agent_id == "builder-1"


@dataclass
class _Agent:
    id: str
    agent_type: str = "builder"
    instructions: str = "AD-1343: do the work and report only what you verified"
    department: str = "engineering"
    rank: str = "ensign"
    is_alive: bool = True


class _Registry:
    """The two calls the verifier makes of an agent registry: ``all`` and ``get``."""

    def __init__(self, *agents: _Agent) -> None:
        self._agents = {agent.id: agent for agent in agents}

    def all(self) -> list[_Agent]:
        return list(self._agents.values())

    def get(self, agent_id: str | None) -> _Agent | None:
        return None if agent_id is None else self._agents.get(agent_id)


class _NoWorkItems:
    """A work-item store that holds nothing, so the legacy judge is anchored to no expected output."""

    async def get_work_item(self, work_item_id: str) -> None:
        return None


class _Judge:
    """A stateless LLM judge: it refutes the first draft, accepts the corrected answer and records every request.

    Judging by what it is shown rather than by the order of the calls keeps a verdict right whatever extra pass a defect makes.
    """

    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> Any:
        self.requests.append(request)
        return SimpleNamespace(content=_ACCEPT if CORRECTED in request.prompt else _REFUTE, tokens_used=3)


class _RecordingExecutor:
    """An AD-859a executor stub: records every run and answers a finished correction."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        self.calls.append(kwargs)
        return WorkItemAgenticOutcome(final_text=CORRECTED, stopped_reason="complete", total_tokens=5)


class _StopLandsBeforeTheRunEntry:
    """An executor behind which the Captain's stop lands after the verifier's check: it issues the order, then runs the real entry.

    The real ``WorkItemAgenticExecutor`` is what refuses; this records the run it was handed and what the entry raised.
    """

    def __init__(self, service: AgentStopService, real: WorkItemAgenticExecutor, agent_id: str) -> None:
        self._service = service
        self._real = real
        self._agent_id = agent_id
        self.reached = 0
        self.raised: Exception | None = None

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        self.reached += 1
        await self._service.issue_stop(self._agent_id, reason=REASON)
        try:
            return await self._real.run(**kwargs)
        except Exception as exc:  # recorded for the test, then raised again unchanged
            self.raised = exc
            raise


class _Admitted(AssertionError):
    """A correction was admitted through the spy owned-steps port."""


class _SpyOwnedPort:
    """An owned-steps port whose only job is to record that a correction was admitted through it."""

    def __init__(self) -> None:
        self.admitted: list[str] = []

    async def admit_correction(self, verifier: Any, snapshot: Any, work_item_id: str, **_kwargs: Any) -> Any:
        self.admitted.append(work_item_id)
        raise _Admitted(f"AD-1343: a correction of {work_item_id} was admitted")


def _owned_snapshot() -> SimpleNamespace:
    """The slice of an owned-steps snapshot the session loop reads before it admits a correction: one submitted row for the child."""
    row = SimpleNamespace(child=SimpleNamespace(child_id=CHILD), submission="ad1343-submission-0001", step_id="ad1343-step-0001")
    return SimpleNamespace(control=SimpleNamespace(parent_id=PARENT, incarnation=1, rows=[row]))


def _verifier(runtime: Any, judge: _Judge, executor: Any) -> SubtaskVerifier:
    """A verifier over fakes; the producer ``AGENT`` is judged by the neutral ``ad1343-verifier-0001``."""
    return SubtaskVerifier(
        llm_client=judge,
        work_item_store=_NoWorkItems(),
        agent_registry=_Registry(_Agent("ad1343-verifier-0001", agent_type="reviewer"), _Agent(AGENT)),
        trust_network=TrustNetwork(),
        agentic_executor=executor,
        runtime=runtime,
        max_convergence_rounds=2,
    )


async def _converge_legacy(verifier: SubtaskVerifier) -> ConvergenceOutcome:
    """The legacy loop (AD-860) over a fresh, refutable result of the producer ``AGENT``."""
    result = SubtaskResult(work_item_id=CHILD, spec_id=SPEC_ID, agent_id=AGENT, output=FIRST_DRAFT, status="done")
    return await asyncio.wait_for(verifier.converge(result, instructions=INSTRUCTIONS, task_text=TASK), timeout=_BOUND)


async def _converge_session(verifier: SubtaskVerifier, *, snapshot: Any = None) -> SessionConvergenceOutcome:
    """The session loop over a fresh, refutable result of the producer ``AGENT``."""
    result = SubtaskResult(
        work_item_id=CHILD, spec_id=SPEC_ID, agent_id=AGENT, output=FIRST_DRAFT, status="done", stopped_reason="complete",
    )
    return await asyncio.wait_for(
        verifier.converge_for_session(
            result, instructions=INSTRUCTIONS, task_text=TASK, expected_output=None,
            parent_id=PARENT, thread_id=THREAD, department="engineering", rank="ensign",
            owned_steps_snapshot=snapshot,
        ),
        timeout=_BOUND,
    )


def _finalizer_document(outcome: SessionConvergenceOutcome) -> dict[str, Any]:
    """The ``ChildVerificationRecord`` document the finalizer builds from ``outcome``; it raises when the record does not validate.

    This is the consumer of the session loop's answer: its ``rounds_used == len(rounds) - 1`` and ``unverified`` rules reject an
    outcome that counts a round that never ran.
    """
    return CrewSessionFinalizer._verification_document(
        parent_id=PARENT, thread_id=THREAD, producer_agent_id=AGENT, outcome=outcome,
    )



# T33
@pytest.mark.parametrize("loop", ["legacy", "session"])
async def test_a_stopped_producer_is_not_re_run_for_correction(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, loop: str,
) -> None:
    converge = _converge_legacy if loop == "legacy" else _converge_session
    async with _service(tmp_path, clock=_Clock()) as service:
        judge, executor = _Judge(), _RecordingExecutor()
        verifier = _verifier(_runtime(service), judge, executor)

        # Golden: with no order in force a refuted result IS sent back and corrected (the verdict is a refutation, the
        # producer runs once, the corrected answer is judged and accepted), and neither the stop module nor the verifier
        # logs anything at INFO or above on the way.
        with caplog.at_level(logging.INFO):
            corrected = await converge(verifier)
        assert corrected.status == "converged" and corrected.result.output == CORRECTED
        assert len(executor.calls) == 1 and executor.calls[0]["agent_id"] == AGENT
        assert len(judge.requests) == 2  # the refutation, then the verdict on the correction
        assert _loud(caplog, STOP_LOGGER, VERIFIER_LOGGER) == []
        if loop == "session":
            assert corrected.rounds_used == 1 and _finalizer_document(corrected)["rounds_used"] == 1
        else:
            assert corrected.rounds == 1

        record = (await service.issue_stop(AGENT, reason=REASON)).record
        if loop == "legacy":
            outcome = await converge(verifier)
            # the refuted result ends unverified; the answer was not changed by any correction
            assert outcome.status == "unverified"
            assert outcome.result.output == FIRST_DRAFT
            assert outcome.rounds == 0  # no round ran
            assert (outcome.verdict.accepted, outcome.verdict.critique) == (False, CRITIQUE)  # premise: a refutation, so a re-run was due
        else:
            # A3 (R2): no outcome is recorded for a stopped producer (an exhaustion record charged it in finalization); the loop
            # raises and the finalizer blocks the session (tests/test_ad1343_stop_crossing_finalizer.py, X7).
            with pytest.raises(agent_stop.AgentStopped) as raised:
                await converge(verifier)
            assert raised.value.record == record and PRIVATE_FRAGMENT not in str(raised.value)
        # the producer did not run again, and only the refutation was judged: no correction followed to be judged
        assert len(executor.calls) == 1
        assert len(judge.requests) == 3
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}  # the refused correction, counted once at its seam
        assert _logged_as_a_fault(caplog) == []  # the stop is not logged as a failed re-run


# T33 (owned variant)
async def test_a_stopped_producers_session_correction_is_not_admitted_to_the_owned_port(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    async with _service(tmp_path, clock=_Clock()) as service:
        judge, executor, port = _Judge(), _RecordingExecutor(), _SpyOwnedPort()
        verifier = _verifier(_runtime(service), judge, executor)
        verifier.bind_owned_steps_correction_port(port)

        # Golden: with no order in force the refuted child's correction IS admitted through the owned port (the spy stops
        # the run there), so the port and the snapshot of this test reach the admission.
        with caplog.at_level(logging.INFO), pytest.raises(_Admitted):
            await _converge_session(verifier, snapshot=_owned_snapshot())
        assert port.admitted == [CHILD] and executor.calls == []
        assert _loud(caplog, STOP_LOGGER, VERIFIER_LOGGER) == []

        record = (await service.issue_stop(AGENT, reason=REASON)).record
        with caplog.at_level(logging.WARNING), pytest.raises(agent_stop.AgentStopped):
            await _converge_session(verifier, snapshot=_owned_snapshot())  # A3 (R2): raised; no outcome is recorded

        assert port.admitted == [CHILD]  # the stopped producer's correction was not admitted: the port was not asked again
        assert executor.calls == []
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}
        assert not any("admitted but not executed" in r.getMessage() for r in caplog.records)  # A3 (R5): before admission


# T33 (race, legacy)
async def test_a_stopped_producer_race_ends_unverified_without_a_second_verify_legacy(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    llm = _CountingLLM()
    async with _service(tmp_path, clock=_Clock()) as service:
        judge = _Judge()
        entry = _StopLandsBeforeTheRunEntry(service, WorkItemAgenticExecutor(llm_client=llm), AGENT)
        verifier = _verifier(_runtime(service), judge, entry)
        assert service.stop_for(AGENT) is None  # premise: the producer is not stopped when the verifier checks

        outcome = await _converge_legacy(verifier)

        record = service.stop_for(AGENT)
        assert record is not None and entry.reached == 1  # the order landed after the check, inside the run
        # the real run entry refused with AgentStopped, naming the order and not the Captain's reason, before the model
        assert isinstance(entry.raised, agent_stop.AgentStopped) and entry.raised.record == record
        assert record.stop_id in str(entry.raised) and PRIVATE_FRAGMENT not in str(entry.raised)
        assert llm.calls == []
        # the verifier took it as the escalation, not as a failed re-run to re-verify
        assert outcome.status == "unverified"
        assert len(judge.requests) == 1
        assert outcome.result.output == FIRST_DRAFT
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}
        assert _logged_as_a_fault(caplog) == []


# T33 (race, session)
async def test_a_stopped_producer_race_is_re_raised_never_failed_session(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    llm = _CountingLLM()
    async with _service(tmp_path, clock=_Clock()) as service:
        judge = _Judge()
        entry = _StopLandsBeforeTheRunEntry(service, WorkItemAgenticExecutor(llm_client=llm), AGENT)
        verifier = _verifier(_runtime(service), judge, entry)
        assert service.stop_for(AGENT) is None  # premise: the producer is not stopped when the verifier checks

        with pytest.raises(agent_stop.AgentStopped) as raised:  # A3 (R2): re-raised, never a terminal outcome
            await _converge_session(verifier)

        record = service.stop_for(AGENT)
        assert record is not None and entry.reached == 1
        # the run entry reached through the projected correction runtime (which has no ``agent_stops``) refused all the same
        assert isinstance(entry.raised, agent_stop.AgentStopped) and entry.raised.record == record
        assert raised.value is entry.raised  # the verifier re-raised the entry's refusal unchanged
        assert record.stop_id in str(entry.raised) and PRIVATE_FRAGMENT not in str(entry.raised)
        assert llm.calls == []
        assert len(judge.requests) == 1
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}
        assert _logged_as_a_fault(caplog) == []  # never failed / correction_execution_defect
