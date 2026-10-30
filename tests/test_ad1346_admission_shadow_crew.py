"""AD-1346 M3c3 (#1604): the shadow statements at delegation, the crew synthesis sites and agent-created work, on a real boot.

Four of the six sites AD-1346 M3c3 shadows are driven here: a delegation (``DelegateTaskTool.invoke``), the
facilitator's synthesis (``CrewSynthesizer.synthesize_for_session``), the owned resume of a synthesis
(``CrewSessionFinalizer._resume_synthesis``) and an agent's create of its own work (``AgentWorkService._requester_stop``).
The two correction loops (``SubtaskVerifier.converge`` and ``converge_for_session``) reach their check only after a
refuted verdict from a full judge pass, so the census tests 9b and 9c pin their statements (the contract's D87).

- G5 one boot: startup handed the boot's service to the crew session finalizer and to the agent-work service, and a
     session correction's projected tool registry is handed it. Each driven site passes that service the work its stop
     check judged and what the check did, once with no order and once under a Captain's stop on a certified crew agent.
     ``admission_shadow.db`` then holds an ``admit``/``admit``/``admitted`` row and a ``refuse``/``would_refuse``/
     ``agent_stopped`` row for each of the three (work kind, seam) pairs, the new ``agent_work`` kind among them, and no
     disagreement sample is keyed on that agent.
- G6 two boots, ``admission.shadow_enabled`` true and then false: the same calls answer the same, byte for byte once the
     order's id, its start time and the agent's id are replaced (#1604 property 12).

On every boot, G5 and G6 assert that the order is counted exactly once at the delegation and agent-work seams and at
least twice at the agentic-run seam, which the synthesis and the resume both reach and the ship's own runs can also reach.

Each boot loads ``config/system.yaml`` from this checkout, as ``tests/test_ad1346_admission_shadow_routing.py`` does,
with agent-created work switched on, ``MockLLMClient`` and a data directory under ``tmp_path``; the proactive loop's own
task is stopped before the calls. The delegation runs over a test runtime that holds the boot's stop service and shadow
service and resolves one callsign; with no order it ends at the tree-budget check, which refuses a budget of the wrong
type before any run. The synthesis runs on the boot's synthesizer with a drafting stub as its model, the resume on the
boot's finalizer with a stub in place of its durable claim, and the create on the boot's agent-work service, naming a
parent item that does not exist, so no work item is created.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

import probos.agent_work as agent_work_module
import probos.cognitive.crew_finalizer as finalizer_module
import probos.cognitive.crew_synth as synth_module
import probos.tools.delegate_task_tool as delegation_module
from probos.admission import AdmissionService
from probos.admission.report import open_read_only, run_query
from probos.admission.seam import shadow_at
from probos.admission.store import STORE_FILENAME
from probos.agent_work import AgentWorkOrigin
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.crew_verifier import _session_correction_runtime
from probos.cognitive.llm_client import MockLLMClient
from probos.config import load_config
from probos.crew_utils import is_crew_agent
from probos.runtime import ProbOSRuntime
from probos.tools.delegate_task_tool import DelegateTaskTool
from probos.tools.delegation_budget import DELEGATION_TREE_BUDGET_KEY

_SYSTEM_YAML = Path(__file__).resolve().parents[1] / "config" / "system.yaml"
_REASON = "AD-1346 M3c3 crossing"
_DELEGATOR = "ad1346-m3c3-delegator"
_PARENT = "ad1346-m3c3-parent"
_NO_PARENT = "ad1346-m3c3-no-such-item"
_DRAFT = "AD-1346 M3c3: the facilitator's draft"
#: (work kind, seam) of the driven statements: a delegation, the synthesis and the resume, an agent's create.
_PAIRS = (("delegated_task", "delegation"), ("agentic_run", "agentic_run"), ("agent_work", "agent_work"))
#: The modules whose ``shadow_at`` G5 spies on, by the site each holds.
_SPIED: dict[str, ModuleType] = {
    "delegation": delegation_module, "synthesis": synth_module, "resume": finalizer_module, "agent_work": agent_work_module,
}


class _Claimed(Exception):
    """Raised by the stub that stands in for the finalizer's durable synthesis claim."""


class _Drafting:
    """The synthesizer's model: one fixed draft for every request."""

    async def complete(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(content=_DRAFT, tokens_used=7)


async def _claim(session: Any) -> None:
    raise _Claimed("the durable claim is not made here")


async def _boot(data_dir: Path, *, shadow_enabled: bool = True) -> ProbOSRuntime:
    config = load_config(_SYSTEM_YAML)
    config.admission.shadow_enabled = shadow_enabled
    config.agent_work.enabled = True  # AD-1347 ships it off; the create site needs the service
    runtime = ProbOSRuntime(config=config, data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


def _certified_crew(rt: ProbOSRuntime) -> CognitiveAgent:
    """The first live crew ``CognitiveAgent`` whose identity the facade resolves with a DID and that agent work knows."""
    crew = next(
        (
            a for a in rt.registry.all()
            if isinstance(a, CognitiveAgent) and a.is_alive and is_crew_agent(a, rt.ontology)
            and getattr(rt.identity_service.resolve(a.id), "did", "") and rt.agent_work.crew_member(a.id) is not None
        ),
        None,
    )
    assert crew is not None, "premise: a live, certified crew agent that the agent-work service knows"
    return crew


def _spy(monkeypatch: pytest.MonkeyPatch, module: ModuleType, calls: list[tuple[object, dict[str, Any]]]) -> None:
    """Record each call ``module``'s statement makes, then make it."""

    def _recording(service: object, **kwargs: Any) -> None:
        calls.append((service, kwargs))
        return shadow_at(service, **kwargs)

    monkeypatch.setattr(module, "shadow_at", _recording)


def _expected(agent_id: str) -> dict[str, dict[str, str]]:
    """What each spied statement passes besides the service and ``refused`` (the contract's D82)."""
    return {
        "delegation": {
            "presented_id": agent_id, "work_kind": "delegated_task", "seam": "delegation", "origin": "agent",
            "origin_id": _DELEGATOR,
        },
        "synthesis": {
            "presented_id": agent_id, "work_kind": "agentic_run", "seam": "agentic_run", "origin": "system",
            "origin_id": _PARENT,
        },
        "resume": {
            "presented_id": agent_id, "work_kind": "agentic_run", "seam": "agentic_run", "origin": "system",
            "origin_id": _PARENT,
        },
        "agent_work": {
            "presented_id": agent_id, "work_kind": "agent_work", "seam": "agent_work", "origin": "agent",
            "origin_id": agent_id,
        },
    }


async def _delegate(rt: ProbOSRuntime, crew: CognitiveAgent) -> list[Any]:
    """One delegation to ``crew`` over a test runtime that holds the boot's stop service and shadow service and resolves
    one callsign to it. Its context carries a tree budget of the wrong type, so a delegation its stop check admits ends
    at the budget check, before any run: the result's output, error and evidence status."""
    runtime = SimpleNamespace(
        agent_stops=rt.agent_stops, admission_service=rt.admission_service,
        callsign_registry=SimpleNamespace(resolve=lambda to: {"agent_type": crew.agent_type, "agent_id": crew.id}),
        registry=SimpleNamespace(get_by_pool=lambda agent_type: [crew]),
    )
    tool = DelegateTaskTool(runtime=runtime, llm_client=None, max_depth=1, max_iterations=1, tier="standard")
    result = await tool.invoke(
        {"task": "AD-1346 M3c3: report in.", "to": "crew"},
        {"agent_id": _DELEGATOR, DELEGATION_TREE_BUDGET_KEY: "not-a-budget"},
    )
    return [result.output, result.error, result.evidence.status]


async def _synthesize(synthesizer: Any, agent_id: str) -> list[Any]:
    """The facilitator's synthesis of one accepted child: the draft's fields, or the exception's type and text."""
    outcome = SimpleNamespace(
        accepted=True, status="converged",
        result=SimpleNamespace(work_item_id="ad1346-m3c3-child", agent_id=agent_id, output="the child's evidence"),
    )
    try:
        draft = await synthesizer.synthesize_for_session(
            parent_id=_PARENT, producer_agent_id=agent_id, producer_instructions="Facilitate the session.",
            goal="AD-1346 M3c3", success_criteria=("the goal is met",), expected_deliverable="a summary",
            outcomes=(outcome,),
        )
    except Exception as exc:  # a stopped facilitator's AgentStopped is the answer
        return [type(exc).__name__, str(exc)]
    return [draft.producer_agent_id, draft.final_text, draft.tokens_used]


async def _resume(finalizer: Any, agent_id: str) -> list[Any]:
    """The owned resume of an unclaimed synthesis by ``agent_id``: the exception's type and text."""
    try:
        await finalizer._resume_synthesis(
            session=SimpleNamespace(task_id=_PARENT, facilitator_id=agent_id), recovery=SimpleNamespace(synthesis_ref=None),
            publications=[], convergence_refs=[],
        )
    except Exception as exc:  # the stub's _Claimed, or the order's transient error
        return [type(exc).__name__, str(exc)]
    return ["returned"]


async def _create(rt: ProbOSRuntime, agent_id: str) -> list[Any]:
    """A self-task by ``agent_id`` naming a parent item that does not exist: the answer's type, code and detail."""
    answer = await rt.agent_work.create_self_task(
        agent_id, title="AD-1346 M3c3", description="", reason=_REASON, origin=AgentWorkOrigin("dm"),
        spawned_from=_NO_PARENT,
    )
    return [type(answer).__name__, getattr(answer, "code", ""), getattr(answer, "detail", "")]


async def _drive(rt: ProbOSRuntime, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, int], str, str]:
    """Each driven site with no order, then under a Captain's stop: the answers, the refusals the order counted at each
    driven seam, the normalised text and the agent."""
    assert rt.crew_orchestrator is not None and rt.agent_work is not None, "premise: the crew orchestrator and agent work are on"
    if rt.proactive_loop is not None:
        await rt.proactive_loop.stop()  # the loop's own cycles would start work of their own
    crew = _certified_crew(rt)
    finalizer = vars(rt.crew_orchestrator)["_crew_session_finalizer"]
    synthesizer = vars(finalizer)["_synthesizer"]
    monkeypatch.setattr(synthesizer, "_llm", _Drafting())
    monkeypatch.setattr(finalizer, "_claim_owned_synthesis", _claim)
    answers: dict[str, Any] = {
        "delegation_admitted": await _delegate(rt, crew),
        "synthesis_admitted": await _synthesize(synthesizer, crew.id),
        "resume_admitted": await _resume(finalizer, crew.id),
        "agent_work_admitted": await _create(rt, crew.id),
    }
    record = (await rt.agent_stops.issue_stop(crew.id, reason=_REASON)).record
    before = rt.agent_stops.refused_counts(record.stop_id)
    answers["delegation_refused"] = await _delegate(rt, crew)
    answers["synthesis_refused"] = await _synthesize(synthesizer, crew.id)
    answers["resume_refused"] = await _resume(finalizer, crew.id)
    answers["agent_work_refused"] = await _create(rt, crew.id)
    after = rt.agent_stops.refused_counts(record.stop_id)
    counted = {seam: after.get(seam, 0) - before.get(seam, 0) for _, seam in _PAIRS}
    text = json.dumps(answers, sort_keys=True, default=repr)
    for value, mark in ((record.stop_id, "<stop>"), (record.sender_detail()["since"], "<since>"), (crew.id, "<agent>")):
        text = text.replace(value, mark)
    return answers, counted, text, crew.id


def _assert_counted(counted: dict[str, int]) -> None:
    assert (counted["delegation"], counted["agent_work"]) == (1, 1), counted
    assert counted["agentic_run"] >= 2, counted


async def test_each_crew_site_hands_the_boots_service_todays_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G5 (kills XG-1 to XG-4 and XW-1 to XW-6)."""
    data_dir = tmp_path / "data"
    rt = await _boot(data_dir)
    try:
        assert isinstance(rt.admission_service, AdmissionService), "premise: the shadow-on boot builds the service"
        assert rt.crew_orchestrator is not None and rt.agent_work is not None, "premise: the crew orchestrator and agent work are on"
        finalizer = vars(rt.crew_orchestrator)["_crew_session_finalizer"]
        assert vars(finalizer).get("_admission_service") is rt.admission_service, "startup hands the finalizer its service"
        assert vars(rt.agent_work).get("_admission_service") is rt.admission_service, "startup hands agent work its service"
        projection = _session_correction_runtime(rt, agent_id="ad1346-m3c3-producer", department="science", rank="ensign")
        assert vars(projection.tool_registry).get("_admission") is rt.admission_service, "a correction's registry is handed it"
        spied: dict[str, list[tuple[object, dict[str, Any]]]] = {name: [] for name in _SPIED}
        for name, module in _SPIED.items():
            _spy(monkeypatch, module, spied[name])
        answers, counted, _, agent_id = await _drive(rt, monkeypatch)
        _assert_counted(counted)
        assert answers["agent_work_refused"][1] == "agent_stopped", answers["agent_work_refused"]
        for name, fields in _expected(agent_id).items():
            mine = [(service, kwargs) for service, kwargs in spied[name] if all(kwargs.get(k) == v for k, v in fields.items())]
            assert [service is rt.admission_service for service, _ in mine] == [True, True], (name, spied[name])
            assert [kwargs["refused"] for _, kwargs in mine] == [False, True], (name, mine)
    finally:
        await rt.stop()
    db = await open_read_only(data_dir / STORE_FILENAME)
    try:
        parity = await run_query(db, "parity_by_work_kind", ("0000-00-00",))
        disagreements = await run_query(db, "disagreement_samples", (1_000,))
    finally:
        await db.close()
    rows = {row[:5]: row[5] for row in parity}
    for work_kind, seam in _PAIRS:
        assert rows.get((work_kind, seam, "admit", "admit", "admitted"), 0) >= 1, (work_kind, seam, sorted(rows))
        assert rows.get((work_kind, seam, "refuse", "would_refuse", "agent_stopped"), 0) >= 1, (work_kind, seam, sorted(rows))
    assert [row for row in disagreements if json.loads(row[-1])["key"] == agent_id] == []


async def test_with_shadow_off_the_crew_sites_answer_byte_identically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G6: #1604 property 12, the golden test for the four driven sites (D87)."""
    texts: dict[bool, str] = {}
    for enabled in (True, False):
        rt = await _boot(tmp_path / ("on" if enabled else "off"), shadow_enabled=enabled)
        try:
            assert isinstance(rt.admission_service, AdmissionService) is enabled, "premise: the switch decides the service"
            _, counted, texts[enabled], _ = await _drive(rt, monkeypatch)
            _assert_counted(counted)
            if enabled:
                pairs = {(kind, seam) for seam, kind, _ in rt.admission_service.tally()}
                assert pairs >= set(_PAIRS), "premise: the driven shadow statements ran"
        finally:
            await rt.stop()
    assert texts[True] == texts[False]
