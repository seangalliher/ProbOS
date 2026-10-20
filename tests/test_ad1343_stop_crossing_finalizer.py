"""AD-1343 S1 (#1595), amendment A3: a stop never reads as a demerit and never lets a stopped agent verify or synthesize, through the real finalizer (X7, X8, X9).

``tests/test_ad1343_agent_stop_verify.py`` and ``tests/test_ad1343_agent_stop_crew.py`` prove each part alone: the verifier raises ``AgentStopped``
for a stopped producer, never picks a stopped agent, and the synthesizer refuses a stopped facilitator. A chain can be dead with every link
correct: a finalizer that reads the raise as an ordinary defect, or as exhaustion, or never maps it, turns the Captain's stop into a trust
demerit or a wrong blocked reason. These tests cross the whole chain on real parts:

the Captain's order (a real ``AgentStopService`` over ``agent_stops.db``) -> the real ``SubtaskVerifier`` and ``CrewSynthesizer`` over a real
``WorkItemStore`` and a scripted model client -> the real ``CrewSessionFinalizer`` -> a real ``CrewSessionTrustRecorder`` over a real
``TrustNetwork`` and the store's trust outbox.

- X7: the producer of a refuted child is stopped before ``finalize``. The session is blocked ``child_producer_unavailable`` (as a producer
  that is not live is), with no trust effect, no outbox row, one judge call and ``{"agentic_run": 1}`` refused. The control (an order in no
  force) repeats the existing exhaustion test and is still charged.
- X8: a stopped verifier is never picked: a colleague verifies the child, then the final verification finds no candidate.
- X9: a stopped facilitator's synthesis is refused, before ``finalize`` and when the order lands during the synthesis.

Every store lives in ``tmp_path``; the live data directory is never read. Nothing here sleeps: the service's clock is injected and each
finalization is bounded with ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.agent_stop import AgentStopService
from probos.cognitive.crew_finalizer import CrewSessionFinalizer
from probos.cognitive.crew_trust import CrewSessionTrustRecorder
from probos.consensus.trust import TrustNetwork
from tests.test_ad1126_verified_finalization import (
    _ScriptedLLM,
    _StaticAgenticExecutor,
    _executing_case,
    _make_synthesizer,
    _make_verifier,
    _registry_for,
    _runtime,
    _text,
    _verdict,
)
from tests.test_ad1126_verified_finalization import stores as stores_fixture
from tests.test_ad1130_outcome_only_room_trust import _outbox_rows, stores, trust_network  # noqa: F401  (fixtures)
from tests.test_ad1343_agent_stop import PRIVATE_FRAGMENT, REASON, _Clock, _service
from tests.test_ad1343_agent_stop_crew import _BOUND, STOP_LOGGER, _loud

PRODUCER = "producer-1"
VERIFIER = "verifier-1"
FACILITATOR = "facilitator-1"

# What a producer that is not live ends as, and what a stopped producer must end as: nothing else differs.
BLOCKED_PRODUCER_SHAPE = ("blocked_needs_captain", "child_producer_unavailable", 0, 1, [])


@pytest.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A started stop service on ``tmp_path`` with no order in force."""
    async with _service(tmp_path / "stops", clock=_Clock()) as service:
        yield service


@pytest.fixture
async def second(tmp_path: Path, request: pytest.FixtureRequest) -> AsyncIterator[SimpleNamespace]:
    """A second work-item store and trust network in their own directory: the golden run (no order in force) and the not-live twin
    share nothing with the stopped run, whose finalizer would otherwise meet the first one's owned-steps owner."""
    base = tmp_path / "second"
    base.mkdir()
    generator = stores_fixture.__wrapped__(base, request)
    value = await generator.__anext__()
    network = TrustNetwork(db_path=str(base / "trust.db"))
    await network.start()
    try:
        yield SimpleNamespace(stores=value, trust=network, path=base)
    finally:
        await network.stop()
        await generator.aclose()


class _Rig(SimpleNamespace):
    """The parts of one finalization: ``parent``, ``results``, ``children``, ``service``, ``finalizer``, ``judge``, ``synth``, ``executor``, ``registry``."""


def _finalizer(rig_stores: Any, service: Any, registry: Any, verifier: Any, synthesizer: Any, recorder: Any, stop_service: Any) -> Any:
    """Built as ``_make_finalizer`` builds it, directly, with the stop service when the constructor takes one (before A3 it does not)."""
    kwargs: dict[str, Any] = {
        "work_item_store": rig_stores.work,
        "crew_session_service": service,
        "chat_thread_store": rig_stores.chat,
        "artifact_store": rig_stores.artifacts,
        "attachment_store": rig_stores.attachments,
        "agent_registry": registry,
        "verifier": verifier,
        "synthesizer": synthesizer,
        "trust_recorder": recorder,
    }
    if "agent_stops" in inspect.signature(CrewSessionFinalizer.__init__).parameters:
        kwargs["agent_stops"] = stop_service
    return CrewSessionFinalizer(**kwargs)


async def _rig(
    rig_stores: Any,
    tmp_path: Path,
    stop_service: AgentStopService,
    trust: TrustNetwork,
    *,
    judge: list[Any],
    synth: list[Any],
    executor: _StaticAgenticExecutor | None = None,
    producer_alive: bool = True,
    child_prefix: str = "child",
) -> _Rig:
    parent, _thread, service, _contract, children, results = await _executing_case(rig_stores, child_prefix=child_prefix)
    registry = _registry_for(children)
    registry.get(PRODUCER).is_alive = producer_alive
    runtime = _runtime(rig_stores, tmp_path, service)
    runtime.agent_stops = stop_service
    runtime.tool_registry.set_stop_gate(stop_service)
    judge_llm = _ScriptedLLM(judge)
    synth_llm = _ScriptedLLM(synth)
    active_executor = executor or _StaticAgenticExecutor(final_text="Still incomplete")
    synthesizer = _make_synthesizer(llm=synth_llm, stores=rig_stores, runtime=runtime)
    finalizer = _finalizer(
        rig_stores,
        service,
        registry,
        _make_verifier(llm=judge_llm, stores=rig_stores, registry=registry, executor=active_executor, runtime=runtime),
        synthesizer,
        CrewSessionTrustRecorder(outbox=rig_stores.work, trust_network=trust),
        stop_service,
    )
    return _Rig(
        parent=parent, results=results, children=children, service=service, finalizer=finalizer, judge=judge_llm,
        synth=synth_llm, executor=active_executor, registry=registry, synthesizer=synthesizer,
    )


async def _finalize(rig: _Rig) -> Any:
    return await asyncio.wait_for(rig.finalizer.finalize(rig.parent.id, rig.results), timeout=_BOUND)


def _shape(result: Any, outbox: list[Any]) -> tuple[Any, ...]:
    return (result.state, result.reason, result.accepted_count, result.total_count, outbox)


def _fragment_logged(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every record, of any logger, that carries the Captain's private reason."""
    return [r.getMessage() for r in caplog.records if PRIVATE_FRAGMENT in r.getMessage()]


def _stop_before_synthesis(rig: _Rig, stop_service: AgentStopService, agent_id: str) -> None:
    """Make the order land during the synthesis: the real synthesizer's entry, preceded by the stop (test-local subclass)."""
    base = type(rig.synthesizer)

    class _StopsThenSynthesizes(base):  # type: ignore[valid-type, misc]
        async def synthesize_for_session(self, *args: Any, **kwargs: Any) -> Any:
            await stop_service.issue_stop(agent_id, reason=REASON)
            return await super().synthesize_for_session(*args, **kwargs)

    rig.synthesizer.__class__ = _StopsThenSynthesizes


# X7
async def test_a_stopped_producer_of_a_refuted_child_blocks_the_session_without_a_demerit(
    stores: Any, tmp_path: Path, trust_network: TrustNetwork, stops: AgentStopService, second: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _control_exhaustion_is_charged(second, tmp_path, stops, caplog)  # the control: no order in force, as before
    caplog.clear()
    rig = await _rig(stores, tmp_path, stops, trust_network, judge=[_verdict(False, critique="incomplete")], synth=[])
    trust_before = trust_network.raw_scores()
    score_before = trust_network.get_score(PRODUCER)
    record = (await stops.issue_stop(PRODUCER, reason=REASON)).record
    assert stops.stop_for(PRODUCER) is not None  # the premise: the order is in force and the producer is live
    assert rig.registry.get(PRODUCER).is_alive is True
    assert await _outbox_rows(stores.work) == []

    with caplog.at_level(logging.INFO):
        result = await _finalize(rig)

    assert (result.state, result.reason) == ("blocked_needs_captain", "child_producer_unavailable")
    assert result.completed is False
    assert trust_network.get_score(PRODUCER) == score_before  # no 0.5 -> 0.4 demerit
    assert trust_network.raw_scores() == trust_before  # and no credit to the refuting verifier
    assert await _outbox_rows(stores.work) == []
    assert len(rig.judge.requests) == 1  # the first round only
    assert rig.executor.calls == []  # no correction ran
    assert rig.synth.requests == []
    assert stops.refused_counts(record.stop_id) == {"agentic_run": 1}
    child = await stores.work.get_work_item(rig.children[0].id)
    assert child is not None and child.verification == {}  # no ChildVerificationRecord
    session = await rig.service.get_session(rig.parent.id)
    assert session is not None and session.state == "blocked_needs_captain"
    assert session.result_artifact_id is None
    assert _fragment_logged(caplog) == []


# X7 parity
async def test_a_stopped_producer_ends_exactly_as_a_producer_that_is_not_live(
    stores: Any, tmp_path: Path, trust_network: TrustNetwork, stops: AgentStopService, second: SimpleNamespace,
) -> None:
    stopped = await _rig(stores, tmp_path, stops, trust_network, judge=[_verdict(False, critique="incomplete")], synth=[])
    not_live = await _rig(
        second.stores, second.path, stops, second.trust, judge=[_verdict(False, critique="incomplete")], synth=[],
        producer_alive=False,
    )
    await stops.issue_stop(PRODUCER, reason=REASON)  # in force for both rigs; the not-live one never reaches it
    assert not_live.registry.get(PRODUCER).is_alive is False and stopped.registry.get(PRODUCER).is_alive is True

    stopped_result = await _finalize(stopped)
    stopped_shape = _shape(stopped_result, await _outbox_rows(stores.work))
    not_live_result = await _finalize(not_live)
    not_live_shape = _shape(not_live_result, await _outbox_rows(second.stores.work))

    assert not_live_shape == BLOCKED_PRODUCER_SHAPE  # what a producer that is not live ends as
    assert stopped_shape == not_live_shape
    assert trust_network.raw_scores() == {} and second.trust.raw_scores() == {}


async def _control_exhaustion_is_charged(
    second: SimpleNamespace, tmp_path: Path, stops: AgentStopService, caplog: pytest.LogCaptureFixture,
) -> None:
    """X7 control: with no order in force an exhausted convergence is still charged (``test_ad1130:1107-1137``), and the stop logger is silent."""
    rig = await _rig(
        second.stores, second.path, stops, second.trust,
        judge=[_verdict(False, critique="incomplete"), _verdict(False, critique="still incomplete"), _verdict(False, critique="terminally incomplete")],
        synth=[],
    )
    assert stops.stop_for(PRODUCER) is None  # the premise: no order in force

    with caplog.at_level(logging.INFO):
        result = await _finalize(rig)

    assert result.reason == "convergence_exhausted"
    raw = second.trust.raw_scores()
    assert raw[PRODUCER]["alpha"] == 2.0 and raw[PRODUCER]["beta"] > 2.0
    assert raw[VERIFIER]["alpha"] > 2.0 and raw[VERIFIER]["beta"] == 2.0
    rows = await _outbox_rows(second.stores.work)
    assert len(rows) == 4 and all(row[1] == 1 for row in rows)
    assert len(rig.judge.requests) == 3 and len(rig.executor.calls) == 2
    assert _loud(caplog, STOP_LOGGER) == []


async def _golden_session_completes(
    second: SimpleNamespace, tmp_path: Path, stops: AgentStopService, caplog: pytest.LogCaptureFixture, agent_id: str,
) -> None:
    """The golden of X8 and X9: with no order in force the verifier judges the child and the final result, the facilitator
    synthesizes once, the session completes, and the stop logger is silent."""
    rig = await _rig(
        second.stores, second.path, stops, second.trust,
        judge=[_verdict(True, critique="child accepted"), _verdict(True, confidence=0.97, critique="final accepted")],
        synth=[_text("Final synthesized result")],
    )
    assert stops.stop_for(agent_id) is None  # the premise: no order in force

    with caplog.at_level(logging.INFO):
        result = await _finalize(rig)

    child = await second.stores.work.get_work_item(rig.children[0].id)
    assert child is not None
    assert child.verification["rounds"][0]["verdict"]["verifier_agent_id"] == VERIFIER
    assert result.completed is True and result.state == "done"
    assert result.final_output == "Final synthesized result"
    assert len(rig.judge.requests) == 2 and len(rig.synth.requests) == 1
    assert _loud(caplog, STOP_LOGGER) == []


# X8
async def test_a_stopped_verifier_never_verifies_and_the_final_verification_finds_none(
    stores: Any, tmp_path: Path, trust_network: TrustNetwork, stops: AgentStopService, second: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _golden_session_completes(second, tmp_path, stops, caplog, VERIFIER)  # golden: verifier-1 judges both, the session completes
    caplog.clear()
    rig = await _rig(
        stores, tmp_path, stops, trust_network,
        judge=[_verdict(True, critique="child accepted")], synth=[_text("Final synthesized result")],
    )
    record = (await stops.issue_stop(VERIFIER, reason=REASON)).record
    assert stops.stop_for(VERIFIER) is not None and rig.registry.get(VERIFIER).is_alive is True  # stopped, yet registered and live

    with caplog.at_level(logging.INFO):
        result = await _finalize(rig)

    child = await stores.work.get_work_item(rig.children[0].id)
    assert child is not None
    assert child.verification["rounds"][0]["verdict"]["verifier_agent_id"] == FACILITATOR  # a colleague verified the child
    assert (result.state, result.reason) == ("blocked_needs_captain", "independent_verifier_unavailable")
    assert len(rig.judge.requests) == 1 and len(rig.synth.requests) == 1
    assert VERIFIER not in json.dumps(child.verification)  # no verdict names the stopped verifier
    assert VERIFIER not in trust_network.raw_scores()
    assert stops.refused_counts(record.stop_id) == {}  # a verifier question is memory only and is not counted
    session = await rig.service.get_session(rig.parent.id)
    assert session is not None and session.state == "blocked_needs_captain"
    assert _fragment_logged(caplog) == []


# X9
async def test_a_stopped_facilitator_does_not_synthesize_and_blocks_the_session(
    stores: Any, tmp_path: Path, trust_network: TrustNetwork, stops: AgentStopService, second: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _golden_session_completes(second, tmp_path, stops, caplog, FACILITATOR)  # golden: the facilitator synthesizes, the session completes
    caplog.clear()
    rig = await _rig(
        stores, tmp_path, stops, trust_network,
        judge=[_verdict(True, critique="child accepted"), _verdict(True, confidence=0.97, critique="final accepted")],
        synth=[_text("Final synthesized result")],
    )
    record = (await stops.issue_stop(FACILITATOR, reason=REASON)).record
    assert stops.stop_for(FACILITATOR) is not None and rig.registry.get(FACILITATOR).is_alive is True

    with caplog.at_level(logging.INFO):
        result = await _finalize(rig)

    child = await stores.work.get_work_item(rig.children[0].id)
    assert child is not None
    assert child.verification["rounds"][0]["verdict"]["verifier_agent_id"] == VERIFIER  # accepted by verifier-1
    assert (result.state, result.reason) == ("blocked_needs_captain", "synthesis_producer_unavailable")
    assert result.completed is False
    assert rig.synth.requests == []  # nothing was synthesized
    assert len(rig.judge.requests) == 1  # and no final verification ran
    assert stops.refused_counts(record.stop_id) == {"agentic_run": 1}
    session = await rig.service.get_session(rig.parent.id)
    assert session is not None and session.state == "blocked_needs_captain"
    assert session.result_artifact_id is None
    assert _fragment_logged(caplog) == []


# X9 race
async def test_a_facilitator_stopped_during_the_synthesis_does_not_synthesize(
    stores: Any, tmp_path: Path, trust_network: TrustNetwork, stops: AgentStopService, second: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _golden_session_completes(second, tmp_path, stops, caplog, FACILITATOR)  # golden: the facilitator synthesizes, the session completes
    caplog.clear()
    rig = await _rig(
        stores, tmp_path, stops, trust_network,
        judge=[_verdict(True, critique="child accepted"), _verdict(True, confidence=0.97, critique="final accepted")],
        synth=[_text("Final synthesized result")],
    )
    assert stops.stop_for(FACILITATOR) is None  # the premise: the order lands only once the synthesis was entered
    _stop_before_synthesis(rig, stops, FACILITATOR)

    with caplog.at_level(logging.INFO):
        result = await _finalize(rig)

    record = stops.stop_for(FACILITATOR)
    assert record is not None  # the order landed during the synthesis
    assert (result.state, result.reason) == ("blocked_needs_captain", "synthesis_producer_unavailable")
    assert rig.synth.requests == []
    assert len(rig.judge.requests) == 1
    assert stops.refused_counts(record.stop_id) == {"agentic_run": 1}
    session = await rig.service.get_session(rig.parent.id)
    assert session is not None and session.state == "blocked_needs_captain"
    assert session.result_artifact_id is None
