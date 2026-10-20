"""AD-1343 S1 (#1595), amendment A3 (part V): a stopped agent is never picked to verify and never synthesizes (T35, P1 to P6, Y1).

``prompts/ad-1343-a3-amendment.md`` (Sections 25 and 26, decision D29) closes a hole a second cross-family review found: a stopped
crew member could still be picked as the verifier of a colleague's result, and a stopped facilitator still synthesized the
session's final answer. A3 makes the Captain's stop part of the answer to "who may judge" and "who may synthesize":

* P1 to P3: the legacy pick (``SubtaskVerifier._pick_independent_verifier``) passes over a stopped agent in each of its steps, the
  any-independent step (P1), the ontology's department peer (P2) and the producer's chief (P3).
* P4: the session pick (``_pick_live_session_verifier``) passes over a stopped colleague; with every candidate stopped the pass is
  ``unavailable`` / ``independent_verifier_unavailable`` and the judge is never called.
* P5, P6: a verifier stopped while its prompt is built (the legacy store lookup, the session trace section) judges nothing under its
  name: the legacy verdict is the "no independent verifier" defect, the session pass is ``unavailable``, and the model is not called.
* Y1: ``CrewSynthesizer.synthesize_for_session`` raises ``AgentStopped`` before its model call when the facilitator is stopped
  (counted once, at ``agentic_run``), after the inputs are validated.
* Y2 (A4, F1): ``admitted_synthesis=True`` runs the draft for a stopped facilitator with no refusal counted; any other value
  (a truthy ``1``) is refused as before.
* T35 (R5): a correction admitted over the owned-steps port and then refused at the run entry logs one WARNING ("admitted but not
  executed") and raises ``AgentStopped``; the correction is not recorded.

Asking whether a candidate is stopped refuses no work, so it is not counted (``refused_counts`` stays ``{}`` for P1 to P6); the
facilitator is refused work of its own and is counted once. Each test holds its own golden: with no order in force it returns
exactly what it did before, and the logger ``probos.agent_stop`` writes nothing at INFO or above.

Every store lives in ``tmp_path``; the live data directory is never read. Nothing here sleeps or waits on a timer: the service's
clock is injected, every wait on a run is bounded by the rigs of ``tests/test_ad1343_agent_stop_crew.py`` (imported, not copied),
and the verifier's collaborators are small test-local fakes or the rigs of ``tests/test_ad866_dept_verifier.py``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pydantic
import pytest

from probos.agent_stop import AgentStopped, AgentStopService
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_synth import CrewSynthesizer, SessionSynthesisDraft
from probos.cognitive.crew_verifier import SessionVerificationPass, SubtaskVerifier, VerificationVerdict
from probos.consensus.trust import TrustNetwork
from probos.ontology import VesselOntologyService
from probos.substrate.registry import AgentRegistry
from tests.test_ad1343_agent_stop import AGENT, PRIVATE_FRAGMENT, REASON, _Clock, _service
from tests.test_ad1343_agent_stop_crew import (  # the crew rigs, imported and not copied
    _BOUND,
    CHILD,
    CORRECTED,
    FIRST_DRAFT,
    INSTRUCTIONS,
    SPEC_ID,
    STOP_LOGGER,
    TASK,
    VERIFIER_LOGGER,
    _Agent,
    _converge_session,
    _CountingLLM,
    _Judge,
    _loud,
    _NoWorkItems,
    _owned_snapshot,
    _RecordingExecutor,
    _Registry,
    _runtime,
    _verifier,
)
from tests.test_ad866_dept_verifier import (  # noqa: F401  (the fixtures are used by name)
    _FakeExecutor,
    _FakeLLM,
    _FakeStore,
    _register,
    _result,
    data_dir,
    ontology,
    ontology_dir,
)

V1 = "ad1343_verifier_0_00000001"
V2 = "ad1343_verifier_0_00000002"
PERMIT = "ad1343-permit-0001"
FINAL_DRAFT = "AD-1343: the facilitator's synthesized final answer"


class _CountingJudge(_FakeLLM):
    """The AD-866 judge that accepts, recording every request so a judgment that must not happen shows as a call."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def complete(self, request: Any, **kwargs: Any) -> Any:
        self.calls.append(request)
        response = await super().complete(request, **kwargs)
        response.tokens_used = 3  # the session loop reads the tokens a pass used
        return response


class _StoppingStore(_NoWorkItems):
    """A work-item store holding nothing whose lookup is where the Captain's stop lands: it issues the order, then answers None."""

    def __init__(self, service: AgentStopService, stop_agent: str | None) -> None:
        self._service = service
        self._stop_agent = stop_agent

    async def get_work_item(self, work_item_id: str) -> None:
        if self._stop_agent is not None:
            await self._service.issue_stop(self._stop_agent, reason=REASON)
        return None


def _legacy_verifier(
    registry: Any, runtime: Any, judge: _CountingJudge, *, store: Any = None, ontology: VesselOntologyService | None = None,
) -> SubtaskVerifier:
    """A verifier over ``registry`` and ``runtime`` whose judge is ``judge``; the AD-866 store and executor stubs are not exercised."""
    kwargs: dict[str, Any] = {}
    if ontology is not None:
        kwargs["ontology"] = ontology
    return SubtaskVerifier(
        llm_client=judge,
        work_item_store=_FakeStore() if store is None else store,
        agent_registry=registry,
        trust_network=TrustNetwork(),
        agentic_executor=_FakeExecutor(),
        runtime=runtime,
        **kwargs,
    )


def _session_result() -> SubtaskResult:
    """A fresh, finished result of the producer ``AGENT`` for the session judgment."""
    return SubtaskResult(
        work_item_id=CHILD, spec_id=SPEC_ID, agent_id=AGENT, output=FIRST_DRAFT, status="done", stopped_reason="complete",
    )


def _legacy_result() -> SubtaskResult:
    return SubtaskResult(work_item_id=CHILD, spec_id=SPEC_ID, agent_id=AGENT, output=FIRST_DRAFT, status="done")


async def _session_pass(verifier: SubtaskVerifier) -> SessionVerificationPass:
    return await asyncio.wait_for(
        verifier.verify_for_session(_session_result(), expected_output=None, excluded_agent_ids=frozenset({AGENT})),
        timeout=_BOUND,
    )


async def _legacy_verdict(verifier: SubtaskVerifier, result: SubtaskResult | None = None) -> VerificationVerdict:
    return await asyncio.wait_for(verifier.verify(_legacy_result() if result is None else result), timeout=_BOUND)


def _not_in_the_log(caplog: pytest.LogCaptureFixture) -> None:
    """The golden's last word: the stop module wrote nothing at INFO or above."""
    assert _loud(caplog, STOP_LOGGER) == []


# P1
async def test_legacy_pick_passes_over_a_stopped_agent_without_an_ontology(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    registry = AgentRegistry()
    await _register(registry, agent_id="v1", agent_type="reviewer")
    await _register(registry, agent_id="v2", agent_type="reviewer")
    await _register(registry, agent_id="builder-1", agent_type="builder")
    async with _service(tmp_path, clock=_Clock()) as service:
        judge = _CountingJudge()
        verifier = _legacy_verifier(registry, _runtime(service), judge)

        # Golden: with no order in force the first registered non-producer judges (the AD-860 any-independent pick).
        with caplog.at_level(logging.INFO):
            golden = await _legacy_verdict(verifier, _result("builder-1"))
        assert golden.verifier_agent_id == "v1" and golden.accepted is True
        assert len(judge.calls) == 1
        _not_in_the_log(caplog)

        record = (await service.issue_stop("v1", reason=REASON)).record
        assert service.stop_for("v1") == record  # premise: v1 is stopped and v2 is not
        assert service.stop_for("v2") is None

        verdict = await _legacy_verdict(verifier, _result("builder-1"))

        assert verdict.verifier_agent_id == "v2"  # the next independent agent judged; v1 was passed over
        assert verdict.accepted is True and verdict.verification_defect is False
        assert len(judge.calls) == 2  # one judgment more, and not under the stopped name
        assert service.refused_counts(record.stop_id) == {}  # asking about a candidate refuses no work: nothing is counted


# P2
@pytest.mark.parametrize("stand_in", ["next_peer", "chief"])
async def test_legacy_pick_passes_over_a_stopped_department_peer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, ontology: VesselOntologyService, stand_in: str,
) -> None:
    registry = AgentRegistry()
    await _register(registry, agent_id="builder-1", agent_type="builder")  # the producer (engineering)
    # The cross-department agent is registered first, so the any-independent step could not be what picks an engineering peer.
    await _register(registry, agent_id="scout-1", agent_type="scout")  # science
    await _register(registry, agent_id="eng-1", agent_type="engineering_officer")  # the engineering peer, to be stopped
    ontology.wire_agent("builder", "builder-1")
    ontology.wire_agent("scout", "scout-1")
    ontology.wire_agent("engineering_officer", "eng-1")
    if stand_in == "next_peer":
        await _register(registry, agent_id="eng-2", agent_type="builder")  # a second engineering peer
        expected = "eng-2"
    else:
        await _register(registry, agent_id="arch-1", agent_type="architect")  # the chief, after the science agent
        ontology.wire_agent("architect", "arch-1")
        expected = "arch-1"
    async with _service(tmp_path, clock=_Clock()) as service:
        judge = _CountingJudge()
        verifier = _legacy_verifier(registry, _runtime(service), judge, ontology=ontology)

        # Golden: with no order in force the department peer eng-1 is picked over the earlier-registered science agent.
        with caplog.at_level(logging.INFO):
            golden = await _legacy_verdict(verifier, _result("builder-1"))
        assert golden.verifier_agent_id == "eng-1"
        assert len(judge.calls) == 1
        _not_in_the_log(caplog)

        record = (await service.issue_stop("eng-1", reason=REASON)).record
        assert service.stop_for("eng-1") == record  # premise

        verdict = await _legacy_verdict(verifier, _result("builder-1"))

        assert verdict.verifier_agent_id != "eng-1"  # the stopped peer judged nothing
        assert verdict.verifier_agent_id == expected  # the next peer, or the chief: never the any-independent science agent
        assert verdict.verifier_agent_id != "scout-1"
        assert len(judge.calls) == 2
        assert service.refused_counts(record.stop_id) == {}


# P3
async def test_legacy_pick_passes_over_a_stopped_chief(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, ontology: VesselOntologyService,
) -> None:
    registry = AgentRegistry()
    # The producer fills the chief engineer post and is the only engineering agent, so there is no department peer.
    await _register(registry, agent_id="eng-chief-1", agent_type="engineering_officer")
    await _register(registry, agent_id="scout-1", agent_type="scout")  # science, registered before the chief
    await _register(registry, agent_id="arch-1", agent_type="architect")  # the producer's chief, to be stopped
    ontology.wire_agent("engineering_officer", "eng-chief-1")
    ontology.wire_agent("scout", "scout-1")
    ontology.wire_agent("architect", "arch-1")
    async with _service(tmp_path, clock=_Clock()) as service:
        judge = _CountingJudge()
        verifier = _legacy_verifier(registry, _runtime(service), judge, ontology=ontology)

        # Golden: with no order in force the chief is picked over the earlier-registered independent agent.
        with caplog.at_level(logging.INFO):
            golden = await _legacy_verdict(verifier, _result("eng-chief-1"))
        assert golden.verifier_agent_id == "arch-1"
        assert len(judge.calls) == 1
        _not_in_the_log(caplog)

        record = (await service.issue_stop("arch-1", reason=REASON)).record
        assert service.stop_for("arch-1") == record  # premise

        verdict = await _legacy_verdict(verifier, _result("eng-chief-1"))

        assert verdict.verifier_agent_id != "arch-1"  # the stopped chief judged nothing
        assert verdict.verifier_agent_id == "scout-1"  # the any-independent step stands in
        assert len(judge.calls) == 2
        assert service.refused_counts(record.stop_id) == {}


# P4
async def test_session_pick_passes_over_a_stopped_candidate_and_reports_unavailable_when_all_are(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    registry = _Registry(_Agent(AGENT), _Agent(V1, agent_type="reviewer"), _Agent(V2, agent_type="reviewer"))
    async with _service(tmp_path, clock=_Clock()) as service:
        judge = _CountingJudge()
        verifier = _legacy_verifier(registry, _runtime(service), judge)

        # Golden: with no order in force the first live colleague judges.
        with caplog.at_level(logging.INFO):
            golden = await _session_pass(verifier)
        assert (golden.status, golden.verifier_agent_id, golden.accepted) == ("accepted", V1, True)
        assert len(judge.calls) == 1
        _not_in_the_log(caplog)

        first = (await service.issue_stop(V1, reason=REASON)).record
        assert service.stop_for(V1) == first and service.stop_for(V2) is None  # premise

        second_pass = await _session_pass(verifier)

        assert (second_pass.status, second_pass.verifier_agent_id) == ("accepted", V2)  # the first candidate was passed over
        assert len(judge.calls) == 2

        both = (await service.issue_stop(V2, reason=REASON)).record
        assert service.stop_for(V2) == both  # premise: every candidate is stopped

        none_left = await _session_pass(verifier)

        assert none_left.status == "unavailable"
        assert none_left.failure_code == "independent_verifier_unavailable"
        assert none_left.verifier_agent_id == "" and none_left.accepted is False and none_left.tokens_used == 0
        assert len(judge.calls) == 2  # no judge call was made for the last pass
        assert service.refused_counts(first.stop_id) == {} and service.refused_counts(both.stop_id) == {}


# P5
async def test_legacy_verify_judges_nothing_when_the_verifier_is_stopped_while_the_prompt_is_built(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    registry = _Registry(_Agent(V1, agent_type="reviewer"), _Agent(AGENT))
    async with _service(tmp_path, clock=_Clock()) as service:
        judge = _CountingJudge()

        # Golden: the same store without an order to issue lets the picked verifier judge.
        with caplog.at_level(logging.INFO):
            golden = await _legacy_verdict(_legacy_verifier(
                registry, _runtime(service), judge, store=_StoppingStore(service, None),
            ))
        assert (golden.verifier_agent_id, golden.accepted, golden.verification_defect) == (V1, True, False)
        assert len(judge.calls) == 1
        _not_in_the_log(caplog)

        verifier = _legacy_verifier(registry, _runtime(service), judge, store=_StoppingStore(service, V1))
        assert service.stop_for(V1) is None  # premise: V1 is not stopped when it is picked

        verdict = await _legacy_verdict(verifier)

        record = service.stop_for(V1)
        assert record is not None  # the order landed while the prompt was built
        assert verdict.verification_defect is True and verdict.accepted is False
        assert verdict.verifier_agent_id == ""  # nothing is judged under the stopped agent's name
        assert verdict.critique == "No independent verifier available; result unverified."
        assert len(judge.calls) == 1  # the golden's call only: the model was not called for the stopped verifier
        assert service.refused_counts(record.stop_id) == {}


# P6
async def test_session_pass_is_unavailable_when_the_verifier_is_stopped_while_the_prompt_is_built(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _Registry(_Agent(AGENT), _Agent(V1, agent_type="reviewer"))
    async with _service(tmp_path, clock=_Clock()) as service:
        judge = _CountingJudge()
        verifier = _legacy_verifier(registry, _runtime(service), judge)

        # Golden: with no order in force the picked verifier judges.
        with caplog.at_level(logging.INFO):
            golden = await _session_pass(verifier)
        assert (golden.status, golden.verifier_agent_id) == ("accepted", V1)
        assert len(judge.calls) == 1
        _not_in_the_log(caplog)

        async def stop_while_building(trace_ref: str | None) -> str:
            """Test-local: the Captain's stop lands while the judge prompt is built (the trace section is awaited there)."""
            await service.issue_stop(V1, reason=REASON)
            return ""

        monkeypatch.setattr(verifier, "_build_trace_section", stop_while_building)
        assert service.stop_for(V1) is None  # premise: V1 is not stopped when it is picked

        stopped_pass = await _session_pass(verifier)

        record = service.stop_for(V1)
        assert record is not None  # the order landed while the prompt was built
        assert stopped_pass.status == "unavailable"
        assert stopped_pass.failure_code == "independent_verifier_unavailable"
        assert stopped_pass.verifier_agent_id == "" and stopped_pass.accepted is False and stopped_pass.tokens_used == 0
        assert len(judge.calls) == 1  # the golden's call only
        assert service.refused_counts(record.stop_id) == {}


# Y1
async def test_synthesize_for_session_refuses_a_stopped_facilitator_before_its_model_call(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    class _Drafting:
        """A model client that counts its calls and answers a final draft."""

        def __init__(self) -> None:
            self.calls: list[Any] = []

        async def complete(self, request: Any, *args: Any, **kwargs: Any) -> Any:
            self.calls.append(request)
            return SimpleNamespace(content=FINAL_DRAFT, tokens_used=7)

    accepted = SimpleNamespace(
        accepted=True,
        status="converged",
        result=SubtaskResult(work_item_id=CHILD, spec_id=SPEC_ID, agent_id="ad1343_builder_0_00000003", output=CORRECTED, status="done"),
    )

    def call(synthesizer: CrewSynthesizer, *, criteria: tuple[str, ...] = ("requirement X is met",)) -> Any:
        return synthesizer.synthesize_for_session(
            parent_id="ad1343-parent-0001", producer_agent_id=AGENT, producer_instructions=INSTRUCTIONS, goal=TASK,
            success_criteria=criteria, expected_deliverable="the evidence for requirement X", outcomes=(accepted,),
        )

    async with _service(tmp_path, clock=_Clock()) as service:
        llm = _Drafting()
        synthesizer = CrewSynthesizer(
            llm_client=llm, work_item_store=_FakeStore(), trust_network=TrustNetwork(), episodic_memory=None,
            attachment_store=None, runtime=_runtime(service),
        )

        # Golden: with no order in force the facilitator's draft is made with one model call and returned.
        with caplog.at_level(logging.INFO):
            draft = await asyncio.wait_for(call(synthesizer), timeout=_BOUND)
        assert draft == SessionSynthesisDraft(producer_agent_id=AGENT, final_text=FINAL_DRAFT, tokens_used=7)
        assert len(llm.calls) == 1
        _not_in_the_log(caplog)

        record = (await service.issue_stop(AGENT, reason=REASON)).record
        assert service.stop_for(AGENT) == record  # premise

        with pytest.raises(AgentStopped) as raised:
            await asyncio.wait_for(call(synthesizer), timeout=_BOUND)

        assert raised.value.record == record  # it names the order, and not the Captain's reason
        assert record.stop_id in str(raised.value) and PRIVATE_FRAGMENT not in str(raised.value)
        assert len(llm.calls) == 1  # no second model call: the golden's only
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}  # counted once, at its seam

        # Invalid inputs fail first, as before, and are not counted as a refusal.
        with pytest.raises(ValueError, match="session_synthesis_input_invalid"):
            await asyncio.wait_for(call(synthesizer, criteria=()), timeout=_BOUND)
        assert len(llm.calls) == 1
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}


# Y2
async def test_synthesize_for_session_runs_an_admitted_synthesis_for_a_stopped_facilitator(tmp_path: Path) -> None:
    class _Drafting:
        """A model client that counts its calls and answers a final draft."""

        def __init__(self) -> None:
            self.calls: list[Any] = []

        async def complete(self, request: Any, *args: Any, **kwargs: Any) -> Any:
            self.calls.append(request)
            return SimpleNamespace(content=FINAL_DRAFT, tokens_used=7)

    accepted = SimpleNamespace(
        accepted=True,
        status="converged",
        result=SubtaskResult(work_item_id=CHILD, spec_id=SPEC_ID, agent_id="ad1343_builder_0_00000003", output=CORRECTED, status="done"),
    )

    def call(synthesizer: CrewSynthesizer, admitted: Any) -> Any:
        return synthesizer.synthesize_for_session(
            parent_id="ad1343-parent-0001", producer_agent_id=AGENT, producer_instructions=INSTRUCTIONS, goal=TASK,
            success_criteria=("requirement X is met",), expected_deliverable="the evidence for requirement X",
            outcomes=(accepted,), admitted_synthesis=admitted,
        )

    async with _service(tmp_path, clock=_Clock()) as service:
        llm = _Drafting()
        synthesizer = CrewSynthesizer(
            llm_client=llm, work_item_store=_FakeStore(), trust_network=TrustNetwork(), episodic_memory=None,
            attachment_store=None, runtime=_runtime(service),
        )
        record = (await service.issue_stop(AGENT, reason=REASON)).record
        assert service.stop_for(AGENT) == record  # premise

        draft = await asyncio.wait_for(call(synthesizer, True), timeout=_BOUND)
        assert draft == SessionSynthesisDraft(producer_agent_id=AGENT, final_text=FINAL_DRAFT, tokens_used=7)
        assert len(llm.calls) == 1
        assert service.refused_counts(record.stop_id) == {}  # admitted work is not a refusal

        with pytest.raises(AgentStopped):
            await asyncio.wait_for(call(synthesizer, 1), timeout=_BOUND)  # fail closed: truthy is not True
        assert len(llm.calls) == 1
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}


# T35
async def test_a_correction_admitted_then_refused_at_the_run_entry_logs_one_warning_and_keeps_its_permit(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    class _AdmittingPort:
        """A spy owned-steps port. ``admit_correction`` issues the order (when given a service), then admits with a permit."""

        def __init__(self, service: AgentStopService | None) -> None:
            self._service = service
            self.admitted: list[str] = []
            self.recorded: list[Any] = []

        async def admit_correction(self, verifier: Any, snapshot: Any, work_item_id: str, **_kwargs: Any) -> Any:
            self.admitted.append(work_item_id)
            if self._service is not None:
                await self._service.issue_stop(AGENT, reason=REASON)
            return SimpleNamespace(permit=PERMIT, disposition="new")

        def correction_execution_lease(self, snapshot: Any) -> Any:
            return SimpleNamespace(snapshot=snapshot)

        async def record_correction(self, verifier: Any, snapshot: Any, correction: Any) -> None:
            self.recorded.append(correction)
            raise AssertionError("AD-1343 A3: a correction that was refused at the run entry must not be recorded")

    async with _service(tmp_path, clock=_Clock()) as service:
        # Golden: with no order in force the admitted correction IS executed under its permit. The spy's string permit is
        # not a real one, so the run ends where the correction is turned into the record the port would store.
        golden_port, golden_executor = _AdmittingPort(None), _RecordingExecutor()
        golden = _verifier(_runtime(service), _Judge(), golden_executor)
        golden.bind_owned_steps_correction_port(golden_port)
        with caplog.at_level(logging.INFO), pytest.raises(pydantic.ValidationError):
            await _converge_session(golden, snapshot=_owned_snapshot())
        assert golden_port.admitted == [CHILD]
        assert len(golden_executor.calls) == 1 and golden_executor.calls[0]["owned_steps_execution_permit"] == PERMIT
        assert golden_port.recorded == []
        assert [r.getMessage() for r in caplog.records if "admitted but not executed" in r.getMessage()] == []
        _not_in_the_log(caplog)
        caplog.clear()

        llm = _CountingLLM()
        port = _AdmittingPort(service)
        verifier = _verifier(_runtime(service), _Judge(), WorkItemAgenticExecutor(llm_client=llm))
        verifier.bind_owned_steps_correction_port(port)
        assert service.stop_for(AGENT) is None  # premise: the producer is not stopped when the correction is admitted

        with caplog.at_level(logging.INFO), pytest.raises(AgentStopped) as raised:
            await _converge_session(verifier, snapshot=_owned_snapshot())

        record = service.stop_for(AGENT)
        assert record is not None and raised.value.record == record  # the order landed during the admission
        assert record.stop_id in str(raised.value) and PRIVATE_FRAGMENT not in str(raised.value)
        assert port.admitted == [CHILD]  # exactly one admission
        assert port.recorded == []  # the correction was not recorded
        assert llm.calls == []  # the model was not called
        warnings = [r for r in caplog.records if r.name == VERIFIER_LOGGER and r.levelno >= logging.WARNING]
        assert len(warnings) == 1  # exactly one WARNING
        assert "admitted but not executed" in warnings[0].getMessage()
        assert CHILD in warnings[0].getMessage() and AGENT in warnings[0].getMessage()
        assert PRIVATE_FRAGMENT not in warnings[0].getMessage()
        assert warnings[0].exc_info is None  # said once, as a statement and not as a fault with a traceback
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}
