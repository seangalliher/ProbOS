"""AD-1346 M3c1 (#1604): the four shadowed sinks on a real boot: one crossing test and the golden test.

- G1 one boot: at the intent sink, the tool sink and the agentic-run entry a call the site's check admits, and at those
     three and the consultation sink a call it refuses (a Captain's stop on a certified crew agent), each leave a
     parity row of today's outcome beside the shadow outcome in ``admission_shadow.db``; no disagreement sample is
     keyed on that agent, and the stop counts one refusal at each of the four seams.
- G2 two boots, ``admission.shadow_enabled`` true and then false: the same calls answer the same, byte for byte once
     the order's id, its start time and the agent's id are replaced, and count the same refusals under the order
     (#1604 property 12).

Each boot uses ``SystemConfig()`` with the naming ceremony, the proactive loop and QA turned off, as
``tests/test_ad1346_admission_service_boot.py`` does, and ``MockLLMClient``; every data directory is under ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from probos.admission import AdmissionService
from probos.admission.report import open_read_only, run_query
from probos.admission.store import STORE_FILENAME
from probos.agent_stop import AgentStopped
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.consultation import ConsultationRequest
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_utils import is_crew_agent
from probos.runtime import ProbOSRuntime
from probos.types import IntentMessage
from probos.work_item_steps import OwnedStepsError

_PROBE = "ad1346_m3c1_probe"  # an intent no agent handles: an admitted agent self-deselects before any model work
_NO_TOOL = "ad1346-m3c1-no-such-tool"
_REASON = "AD-1346 M3c1 crossing"
_ONE_EACH = {"agentic_run": 1, "consultation": 1, "intent": 1, "tool": 1}


def _config(*, shadow_enabled: bool) -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    config.admission.shadow_enabled = shadow_enabled
    return config


async def _boot(data_dir: Path, *, shadow_enabled: bool = True) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=_config(shadow_enabled=shadow_enabled), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


def _certified_crew(rt: ProbOSRuntime) -> CognitiveAgent:
    crew = next(
        (
            a for a in rt.registry.all()
            if isinstance(a, CognitiveAgent) and is_crew_agent(a, rt.ontology)
            and getattr(rt.identity_service.resolve(a.id), "did", "")
        ),
        None,
    )
    assert crew is not None, "premise: the boot has a certified crew agent"
    return crew


async def _run(runner: WorkItemAgenticExecutor, rt: ProbOSRuntime, agent_id: str) -> list[str]:
    """The run entry's answer: ``AgentStopped`` for a stopped agent; otherwise the owned-steps binding error that the
    deliberately incomplete binding raises right after the entry's check, before any run work."""
    try:
        await runner.run(agent_id=agent_id, instructions="i", task_text="t", runtime=rt, owned_steps_execution_port=object())
    except (AgentStopped, OwnedStepsError) as exc:
        return [type(exc).__name__, str(exc)]
    raise AssertionError("premise: the run entry answers before any run starts")


async def _drive(rt: ProbOSRuntime) -> tuple[dict[str, Any], str, str]:
    """Three sinks with no order, then all four under a Captain's stop: the answers, their normalised text and the agent."""
    crew = _certified_crew(rt)
    runner = WorkItemAgenticExecutor(llm_client=rt.llm_client)
    answers: dict[str, Any] = {}
    answers["intent_admitted"] = await crew.handle_intent(IntentMessage(intent=_PROBE, target_agent_id=crew.id))
    answers["tool_admitted"] = (await rt.tool_registry.check_and_invoke(crew.id, _NO_TOOL, {})).error
    answers["run_admitted"] = await _run(runner, rt, crew.id)
    record = (await rt.agent_stops.issue_stop(crew.id, reason=_REASON)).record
    before = rt.agent_stops.refused_counts(record.stop_id)
    intent = await crew.handle_intent(IntentMessage(intent=_PROBE, target_agent_id=crew.id))
    consultation = await crew.handle_consultation_request(
        ConsultationRequest(requester_id="ad1346-m3c1", topic="t", question="q", target_agent_id=crew.id)
    )
    tool = await rt.tool_registry.check_and_invoke(crew.id, _NO_TOOL, {})
    run = await _run(runner, rt, crew.id)
    after = rt.agent_stops.refused_counts(record.stop_id)
    answers["intent_refused"] = [intent.success, intent.result, intent.error, intent.confidence, intent.metadata]
    answers["consultation_refused"] = [
        consultation.responder_id, consultation.answer, consultation.confidence, consultation.reasoning_summary,
    ]
    answers["tool_refused"] = [tool.error, tool.metadata]
    answers["run_refused"] = run
    answers["refusals_counted"] = {seam: after.get(seam, 0) - before.get(seam, 0) for seam in sorted(set(after) | set(before))}
    text = json.dumps(answers, sort_keys=True, default=repr)
    for value, mark in ((record.stop_id, "<stop>"), (record.sender_detail()["since"], "<since>"), (crew.id, "<agent>")):
        text = text.replace(value, mark)
    return answers, text, crew.id


async def test_each_shadowed_sink_records_todays_outcome_beside_the_shadow_verdict(tmp_path: Path) -> None:
    """G1 (kills GT-1 to GT-6)."""
    data_dir = tmp_path / "data"
    rt = await _boot(data_dir)
    try:
        assert isinstance(rt.admission_service, AdmissionService), "premise: the default boot builds the service"
        assert vars(rt.tool_registry)["_admission"] is rt.admission_service, "the runtime hands the tool sink its service"
        answers, _, agent_id = await _drive(rt)
        assert answers["refusals_counted"] == _ONE_EACH
    finally:
        await rt.stop()
    db = await open_read_only(data_dir / STORE_FILENAME)
    try:
        parity = await run_query(db, "parity_by_work_kind", ("0000-00-00",))
        disagreements = await run_query(db, "disagreement_samples", (1_000,))
    finally:
        await db.close()
    counted = {row[:5]: row[5] for row in parity}
    for work_kind, seam in (("intent", "intent"), ("tool_call", "tool"), ("agentic_run", "agentic_run")):
        assert counted.get((work_kind, seam, "admit", "admit", "admitted"), 0) >= 1, (work_kind, sorted(counted))
    for work_kind, seam in (("intent", "intent"), ("consultation", "consultation"), ("tool_call", "tool"), ("agentic_run", "agentic_run")):
        assert counted.get((work_kind, seam, "refuse", "would_refuse", "agent_stopped"), 0) >= 1, (work_kind, sorted(counted))
    assert [row for row in disagreements if json.loads(row[-1])["key"] == agent_id] == []


async def test_with_shadow_off_the_shadowed_sinks_answer_byte_identically(tmp_path: Path) -> None:
    """G2: #1604 property 12, the golden test (D63)."""
    texts: dict[bool, str] = {}
    for enabled in (True, False):
        rt = await _boot(tmp_path / ("on" if enabled else "off"), shadow_enabled=enabled)
        try:
            assert isinstance(rt.admission_service, AdmissionService) is enabled, "premise: the switch decides the service"
            answers, texts[enabled], _ = await _drive(rt)
            assert answers["refusals_counted"] == _ONE_EACH
            if enabled:
                seams = {seam for seam, _, _ in rt.admission_service.tally()}
                assert seams >= {"intent", "consultation", "tool", "agentic_run"}, "premise: the shadow statements ran"
        finally:
            await rt.stop()
    assert texts[True] == texts[False]
