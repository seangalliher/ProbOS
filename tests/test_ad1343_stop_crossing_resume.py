"""AD-1343 S1 (#1595), amendment A3: the resume paths refuse a stopped facilitator and a stopped producer.

``CrewSessionFinalizer.resume`` rebuilds a durable CrewSession from its checkpoints. A3 makes it
treat an agent the Captain has stopped exactly as it treats one that is not live:

- X10  a stopped facilitator: ``CrewRecoveryTransientError("synthesis_producer_stopped")`` (N1) BEFORE the
       owned synthesis is claimed, so the synthesizer is not called and a resume after the lift is not read
       as an interrupted synthesis (``owned_steps_synthesis_interrupted``);
- X10b the race (A4, F1): the stop lands right after the durable claim. The claimed synthesis was
       admitted at the finalizer's check, so it runs to completion; no claim is left behind;
- X11  a stopped producer of a refuted child: ``CrewRecoveryTransientError("child_producer_stopped")``
       (N1), otherwise as for a producer with ``is_alive=False``, and no trust-outbox row;
- X10c (N1) a stop landing after the facilitator check of a synthesis that is not claimed (a session with
       no owned steps) is transient too; X10d (N1) a facilitator that is not live keeps ``ValueError``.

Every test crosses the whole chain: a real ``AgentStopService`` over ``agent_stops.db`` in ``tmp_path``
-> the real verifier, synthesizer and finalizer over real stores -> ``finalizer.resume``. Each has a
golden: with no order in force the resume returns exactly what it did before, and ``probos.agent_stop``
writes nothing at INFO or above.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from probos import work_item_steps as owned_steps
from probos.agent_stop import AgentStopped
from probos.cognitive.crew_finalizer import CrewSessionFinalizer
from probos.cognitive.crew_session import CrewRecoveryTransientError
from probos.cognitive.crew_trust import CrewSessionTrustRecorder
from probos.consensus.trust import TrustNetwork
from tests.test_ad1126_verified_finalization import (
    _ScriptedLLM,
    _StaticAgenticExecutor,
    _make_synthesizer,
    _make_verifier,
    _registry_for,
    _runtime,
    _text,
    _verdict,
)
from tests.test_ad1130_outcome_only_room_trust import (
    _outbox_rows,
    stores,  # noqa: F401  (a fixture: imported so pytest finds it here)
    trust_network,
)
from tests.test_ad1244_verdict_criteria import _executed_session
from tests.test_ad1343_agent_stop import LIFT_REASON, REASON, _service

STOP_LOGGER = "probos.agent_stop"
FACILITATOR = "facilitator-1"
FINAL_TEXT = "AD-1343 A3: the durable final report"


def _loud(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    """What the stop module wrote at INFO or above: nothing, when no order is in force."""
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == STOP_LOGGER and r.levelno >= logging.INFO]


class _Rig:
    """One owned session at the resume point, its real verifier, synthesizer and finalizer, and the scripted models."""

    def __init__(
        self, case: Any, tmp_path: Path, stops: Any, trust: TrustNetwork, *, judge: list[Any], synth: list[Any],
        correction: _StaticAgenticExecutor | None = None,
    ) -> None:
        self.case = case
        self.stops = stops
        self.trust = trust
        self.registry = _registry_for([case.child])
        self.judge = _ScriptedLLM(judge)
        self.synth = _ScriptedLLM(synth)
        self.correction = correction or _StaticAgenticExecutor(final_text="AD-1343 A3: a corrected answer", trace_ref=None)
        runtime = _runtime(case.stores, tmp_path, case.service)
        runtime.agent_stops = stops
        runtime.tool_registry.set_stop_gate(stops)
        verifier = _make_verifier(
            llm=self.judge, stores=case.stores, registry=self.registry, executor=self.correction,
            runtime=runtime, trust=trust,
        )
        synthesizer = _make_synthesizer(llm=self.synth, stores=case.stores, runtime=runtime, trust=trust)
        self.finalizer = CrewSessionFinalizer(
            work_item_store=case.stores.work, crew_session_service=case.service,
            chat_thread_store=case.stores.chat, artifact_store=case.stores.artifacts,
            attachment_store=case.stores.attachments, agent_registry=self.registry,
            verifier=verifier, synthesizer=synthesizer,
            trust_recorder=CrewSessionTrustRecorder(outbox=case.stores.work, trust_network=trust),
            agent_stops=stops,
        )

    @property
    def parent_id(self) -> str:
        return self.case.parent.id

    @property
    def producer_id(self) -> str:
        return str(self.case.results[0].agent_id)

    async def synthesis_claim(self) -> Any:
        return await self.case.stores.work.get_owned_synthesis_claim(self.parent_id)


# X10
async def test_resume_with_a_stopped_facilitator_is_refused_before_the_claim_and_resumes_after_the_lift(
    tmp_path: Path, trust_network: TrustNetwork,
) -> None:
    async with _executed_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, trust_network, judge=[_verdict(True), _verdict(True)], synth=[_text(FINAL_TEXT)])
        record = (await stops.issue_stop(FACILITATOR, reason=REASON)).record
        assert stops.stop_for(FACILITATOR) is not None  # premise: the order is in force
        assert await rig.synthesis_claim() is None  # premise: nothing is claimed yet

        with pytest.raises(CrewRecoveryTransientError) as refused:
            await rig.finalizer.resume(rig.parent_id)

        assert refused.value.code == "synthesis_producer_stopped"  # N1: transient, so the owner's recovery loop retries it
        assert len(rig.judge.requests) == 1  # premise: the child was verified, so the resume reached the synthesis step
        assert rig.synth.requests == []  # the synthesizer was not called
        assert await rig.synthesis_claim() is None  # refused BEFORE the owned synthesis was claimed
        assert stops.refused_counts(record.stop_id) == {"agentic_run": 1}  # the refusal, counted once at its seam
        session = await case.service.get_session(rig.parent_id)
        assert session is not None and session.state == "verifying"  # not terminal: the resume can be retried

        await stops.lift_stop(FACILITATOR, reason=LIFT_REASON)
        assert stops.stop_for(FACILITATOR) is None  # premise: the order is lifted
        try:
            completed = await rig.finalizer.resume(rig.parent_id)
        except owned_steps.OwnedStepsError as exc:  # what a claim made before the refusal would have left behind
            pytest.fail(f"the resume after the lift was read as an interrupted synthesis: {exc}")

        assert completed.completed is True and completed.state == "done"
        assert len(rig.synth.requests) == 1  # the one synthesis, after the lift
        assert len(rig.judge.requests) == 2  # the child was not judged again; only the final verification was added


# X10 (golden)
async def test_resume_with_no_order_in_force_completes_as_before(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, trust_network: TrustNetwork,
) -> None:
    async with _executed_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, trust_network, judge=[_verdict(True), _verdict(True)], synth=[_text(FINAL_TEXT)])
        assert stops.stop_for(FACILITATOR) is None  # premise: no order in force

        with caplog.at_level(logging.INFO):
            completed = await rig.finalizer.resume(rig.parent_id)

        assert completed.completed is True and completed.state == "done"
        assert (len(rig.judge.requests), len(rig.synth.requests)) == (2, 1)
        assert _loud(caplog) == []  # the stop module writes nothing when no order is in force


# X10b
async def test_resume_with_a_stop_landing_after_the_synthesis_claim_completes_the_admitted_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trust_network: TrustNetwork,
) -> None:
    # A4 (F1): round 3 showed this race refused after the claim and left a durable fence, so every resume after the lift
    # was read as an interrupted synthesis though nothing ran. The test asserted that leftover claim; it now asserts the
    # admitted synthesis completes and no stranded state remains.
    async with _executed_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, trust_network, judge=[_verdict(True), _verdict(True)], synth=[_text(FINAL_TEXT)])
        work = case.stores.work
        claimed = work.claim_owned_synthesis
        claims: list[str] = []

        async def claim_then_stop(*args: Any, **kwargs: Any) -> Any:
            # The reviewer's window: the real claim has succeeded, then the Captain's order lands before synthesis.
            admission = await claimed(*args, **kwargs)
            claims.append(admission.disposition)
            await stops.issue_stop(FACILITATOR, reason=REASON)
            return admission

        monkeypatch.setattr(work, "claim_owned_synthesis", claim_then_stop)
        assert stops.stop_for(FACILITATOR) is None  # premise: the finalizer's own check will pass

        try:
            completed = await rig.finalizer.resume(rig.parent_id)
        except (ValueError, owned_steps.OwnedStepsError) as exc:
            pytest.fail(f"a synthesis admitted before the order was refused after its claim: {exc!r}")

        assert claims == ["new"]  # premise: the claim was made, once, before the order
        record = stops.stop_for(FACILITATOR)
        assert record is not None  # premise: the order landed after the claim and is still in force
        assert completed.completed is True and completed.state == "done"  # the admitted synthesis ran to its end
        assert (len(rig.judge.requests), len(rig.synth.requests)) == (2, 1)  # one synthesis, one final verification
        assert await rig.synthesis_claim() is not None  # the claim records a synthesis that ran
        assert stops.refused_counts(record.stop_id) == {}  # admitted work is not a refusal

        lifted = await stops.lift_stop(FACILITATOR, reason=LIFT_REASON)
        assert lifted.refused == {}
        again = await rig.finalizer.resume(rig.parent_id)  # lift -> second resume: nothing is stranded or re-run
        assert again.state == "done" and len(rig.synth.requests) == 1


# X11
async def test_resume_with_a_stopped_producer_ends_as_with_a_producer_not_live(
    tmp_path: Path, trust_network: TrustNetwork,
) -> None:
    async def observe(rig: _Rig) -> dict[str, Any]:
        with pytest.raises((ValueError, CrewRecoveryTransientError)) as refused:
            await rig.finalizer.resume(rig.parent_id)
        child = await rig.case.stores.work.get_work_item(rig.case.child.id)
        session = await rig.case.service.get_session(rig.parent_id)
        recovery = await rig.case.service.get_recovery(rig.parent_id)
        assert child is not None and session is not None and recovery is not None
        return {
            "error": str(refused.value),
            "kind": type(refused.value).__name__,
            "state": session.state,
            "phase": recovery.phase,
            "child_verification": child.verification,
            "child_tokens": child.actual_tokens,
            "outbox": [tuple(row) for row in await _outbox_rows(rig.case.stores.work)],
            "trust": rig.trust.raw_scores(),
            "corrections": len(rig.correction.calls),
            "synthesis_claim": await rig.synthesis_claim(),
        }

    for name in ("not-live", "stopped"):
        (tmp_path / name).mkdir()
    async with _service(tmp_path / "stops") as stops:
        async with _executed_session(tmp_path / "not-live") as dead_case:
            dead = _Rig(
                dead_case, tmp_path / "not-live", stops, TrustNetwork(),
                judge=[_verdict(False, critique="incomplete")], synth=[],
            )
            dead.registry.get(dead.producer_id).is_alive = False
            assert stops.stop_for(dead.producer_id) is None  # premise: no order, the producer is simply not live
            not_live = await observe(dead)
        assert not_live["error"] == "child_producer_unavailable"  # premise: the established vocabulary for a producer not live
        assert not_live["kind"] == "ValueError"  # N1: a producer that is not live is still an integrity conflict
        assert not_live["outbox"] == [] and not_live["trust"] == {}

        async with _executed_session(tmp_path / "stopped") as case:
            rig = _Rig(
                case, tmp_path / "stopped", stops, trust_network,
                judge=[_verdict(False, critique="incomplete")], synth=[],
            )
            record = (await stops.issue_stop(rig.producer_id, reason=REASON)).record
            assert rig.registry.get(rig.producer_id).is_alive is True  # premise: only the order, not liveness, differs
            assert await _outbox_rows(case.stores.work) == []  # premise: no trust row before the resume

            stopped = await observe(rig)

            assert len(rig.judge.requests) == 1  # premise: round 0 was refuted, so a correction was due
            assert stopped["corrections"] == 0  # the stopped producer was not run again
            assert (stopped["kind"], stopped["error"]) == ("CrewRecoveryTransientError", "child_producer_stopped")  # N1
            assert stopped["outbox"] == []  # no trust-outbox row: neither a verdict nor an exhaustion was charged
            assert stopped["trust"] == {} and trust_network.raw_scores() == {}
            assert stopped["child_verification"] in (None, {}) and stopped["synthesis_claim"] is None
            # N1: ends as the same resume with the producer not live in every other respect (the judge was asked once
            # here, never there), except that the stop is transient
            assert {**stopped, "kind": None, "error": None} == {**not_live, "kind": None, "error": None}
            assert stops.refused_counts(record.stop_id) == {"agentic_run": 1}  # the refused correction, counted once at its seam


# X11 (golden)
async def test_resume_with_a_refuted_child_and_no_order_corrects_and_completes_as_before(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, trust_network: TrustNetwork,
) -> None:
    async with _executed_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(
            case, tmp_path, stops, trust_network,
            judge=[_verdict(False, critique="incomplete"), _verdict(True), _verdict(True)], synth=[_text(FINAL_TEXT)],
        )
        assert stops.stop_for(rig.producer_id) is None  # premise: no order in force

        with caplog.at_level(logging.INFO):
            completed = await rig.finalizer.resume(rig.parent_id)

        assert completed.completed is True and completed.state == "done"
        assert len(rig.correction.calls) == 1  # the producer is sent back once
        assert (len(rig.judge.requests), len(rig.synth.requests)) == (3, 1)
        assert await _outbox_rows(case.stores.work) != []  # the trust the session earned is recorded
        assert _loud(caplog) == []  # the stop module writes nothing when no order is in force


# X10c (N1, D43)
async def test_resume_of_an_unclaimed_synthesis_stopped_after_the_facilitator_check_is_transient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trust_network: TrustNetwork,
) -> None:
    async with _executed_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, trust_network, judge=[_verdict(True)], synth=[])

        async def claim_nothing_then_stop(session: Any) -> None:
            # A session with no owned steps claims nothing; the order lands before the synthesizer's own entry check.
            await stops.issue_stop(FACILITATOR, reason=REASON)
            return None

        monkeypatch.setattr(rig.finalizer, "_claim_owned_synthesis", claim_nothing_then_stop)
        assert stops.stop_for(FACILITATOR) is None  # premise: the finalizer's own check passes

        with pytest.raises(CrewRecoveryTransientError) as refused:
            await rig.finalizer.resume(rig.parent_id)

        assert refused.value.code == "synthesis_producer_stopped"
        assert isinstance(refused.value.__cause__, AgentStopped)  # refused at the synthesizer's entry, not by the finalizer
        assert rig.synth.requests == [] and await rig.synthesis_claim() is None


# X10d (N1)
async def test_resume_with_a_facilitator_that_is_not_live_is_still_an_integrity_conflict(
    tmp_path: Path, trust_network: TrustNetwork,
) -> None:
    async with _executed_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, trust_network, judge=[_verdict(True)], synth=[])
        rig.registry.get(FACILITATOR).is_alive = False
        assert stops.stop_for(FACILITATOR) is None  # premise: no order; the facilitator is simply not live

        with pytest.raises(ValueError) as refused:
            await rig.finalizer.resume(rig.parent_id)

        assert str(refused.value) == "synthesis_producer_unavailable"
        assert rig.synth.requests == []
