import os
import sys
from pathlib import Path
TREE = Path(os.environ.get("BF924_SOURCE_TREE", r"D:\ProbOS-worktrees\bf924-review1"))
sys.path[:0] = [str(TREE / "src"), str(TREE)]
import probos
print("SOURCE", probos.__file__, flush=True)
assert Path(probos.__file__).resolve() == (TREE / "src/probos/__init__.py").resolve()
import asyncio
import json
import logging
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from probos.cognitive.cognitive_agent import _DECISION_CACHES
from probos.cognitive.llm_client import OpenAICompatibleClient, MockLLMClient
from probos.cognitive.procedures import ProcedureStep
from probos.events import EventType
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.substrate.registry import AgentRegistry
from probos.types import AgentState, IntentResult, LLMRequest, LLMResponse, Priority
from tests.test_bf924_compilation_trust import _store_rig, _handle_on_store
from tests.test_replay_dispatch import ReplayTestAgent

@pytest.fixture(autouse=True)
def clear_decision_caches():
    _DECISION_CACHES.clear()
    yield
    _DECISION_CACHES.clear()

@dataclass
class Case:
    name: str
    row: int
    level: int = 3
    compound: bool = False
    overall: str = "YES"
    step: str = "YES"
    reject_step: int = 1
    score: float = 0.5
    approved: bool = False
    fail_action: bool = False
    no_recovery: bool = False
    fail_recovery: bool = False
    missing: str = ""
    dispatch: str = ""
    formatting_error: bool = False
    accounting_error: str = ""
    no_checks: bool = False

CASES = [
    Case("guided-success-promotes", 1, level=2),
    Case("clamped-guided-success-capped", 1, level=4, score=0.3),
    Case("guided-failure-resets", 2, level=2, fail_action=True),
    Case("clamped-guided-failure-demotes", 2, level=4, score=0.3, fail_action=True),
]
for comp in (False, True):
    for answer in ("NO", "MAYBE", ""):
        CASES.append(Case(f"overall-{answer or chr(48)}-compound-{comp}", 3, compound=comp, overall=answer))
    for fault in ("raise", "timeout", "error-reply"):
        CASES.append(Case(f"overall-{fault}-compound-{comp}", 4, compound=comp, overall=fault))
CASES += [Case("single-yes", 5), Case("single-no-validation-context", 5, no_checks=True)]
for level in (3, 4, 5):
    for recovery in ("success", "none", "action-failure"):
        CASES.append(Case(f"single-cached-failure-L{level}-{recovery}", 6, level=level, score=0.7,
                          approved=(level == 5), fail_action=True, no_recovery=(recovery == "none"),
                          fail_recovery=(recovery == "action-failure")))
for missing in ("intent_bus", "registry", "unresolved"):
    CASES.append(Case(f"L3-degraded-{missing}", 7, compound=True, missing=missing))
for answer in ("NO", "MAYBE", ""):
    for recovery in ("success", "none", "action-failure"):
        for number in (1, 2):
            CASES.append(Case(f"step-{answer or chr(48)}-{number}-{recovery}", 8, compound=True, step=answer,
                              reject_step=number, no_recovery=(recovery == "none"), fail_recovery=(recovery == "action-failure")))
for dispatch in ("failed", "raise"):
    for answer in ("YES", "NO"):
        CASES.append(Case(f"L3-dispatch-{dispatch}-step-{answer}", 9, compound=True, dispatch=dispatch, step=answer))
for fault in ("raise", "timeout", "error-reply"):
    CASES.append(Case(f"step-call-{fault}", 10, compound=True, step=fault))
CASES.append(Case("compound-all-yes", 11, compound=True))
for level in (4, 5):
    CASES.append(Case(f"single-success-L{level}", 12, level=level, score=0.7, approved=True))
    for dispatch in ("", "failed", "raise"):
        CASES.append(Case(f"compound-L{level}-dispatch-{dispatch or chr(48)}", 13, level=level, compound=True,
                          score=0.7, approved=True, dispatch=dispatch))
    for missing in ("intent_bus", "registry", "unresolved"):
        CASES.append(Case(f"L{level}-degraded-{missing}", 14, level=level, compound=True,
                          score=0.7, approved=True, missing=missing))
    for comp in (False, True):
        CASES.append(Case(f"format-error-L{level}-compound-{comp}", 15, level=level, compound=comp,
                          score=0.7, approved=True, formatting_error=True))
for comp in (False, True):
    for fault in ("record_consecutive_success", "promote_compilation_level"):
        CASES.append(Case(f"accounting-{fault}-compound-{comp}", 16, compound=comp, accounting_error=fault))
CASES += [
    Case("accounting-demotion-overall-NO", 16, overall="NO", accounting_error="demote_compilation_level"),
    Case("accounting-demotion-cached-failure", 16, fail_action=True, accounting_error="demote_compilation_level"),
    Case("accounting-reset-guided-failure", 16, level=2, fail_action=True, accounting_error="reset_consecutive_successes"),
]

async def make_rig(tmp_path, case):
    r = await _store_rig(tmp_path, case.score, case.level)
    r.client = OpenAICompatibleClient(base_url="http://127.0.0.1:9/v1")
    r.agent._llm_client = r.client
    r.bus = IntentBus(SignalManager())
    r.registry = AgentRegistry()
    r.runtime.intent_bus, r.runtime.registry = r.bus, r.registry
    r.target = ReplayTestAgent(llm_client=MockLLMClient(), runtime=r.runtime, pool="review4-worker")
    r.target.state = AgentState.ACTIVE
    await r.registry.register(r.target)
    await r.registry.register(r.agent)
    r.bus.subscribe(r.target.id, r.target.handle_intent, intent_names=["compound_step_replay"])
    r.proc.postconditions = [] if case.no_checks else ["the expected result exists"]
    r.proc.steps = [ProcedureStep(step_number=n, action=f"perform operation {n}",
                                expected_output="" if case.no_checks else f"operation {n} complete",
                                agent_role="review4-worker" if case.compound else "",
                                resolved_agent_type="review4-worker" if case.compound else "")
                    for n in ((1, 2) if case.compound else (1,))]
    if case.missing == "unresolved":
        for step in r.proc.steps:
            step.agent_role, step.resolved_agent_type = "missing-worker", "missing-worker"
    await r.store.save(r.proc)
    if case.approved:
        await r.store.approve_promotion(r.proc.id, "captain", "review4-directive")
    for _ in range(2):
        await r.store.record_consecutive_success(r.proc.id)
    if case.missing in ("intent_bus", "registry"):
        delattr(r.runtime, case.missing)
    r.requests, r.deliveries, r.decisions, r.acts, r.outcomes, r.sql = [], [], [], [], [], []
    r.counts = Counter()
    await r.store._db.set_trace_callback(r.sql.append)
    return r

async def reply(answer):
    if answer == "raise":
        raise RuntimeError("selected validation call failed")
    if answer == "timeout":
        await asyncio.sleep(1)
    if answer == "error-reply":
        return LLMResponse(content="", error="selected provider error")
    return LLMResponse(content=answer)

async def execute_case(r, case, *, verify=True):
    with ExitStack() as patches:
        async def complete(request: LLMRequest, *, priority=Priority.NORMAL):
            assert isinstance(request, LLMRequest)
            assert priority is Priority.NORMAL
            r.requests.append(request)
            if "Should this procedure be evolved?" in request.prompt:
                return LLMResponse(content="NO")
            if request.max_tokens == 100:
                return await reply(case.overall)
            if request.max_tokens == 50:
                index = sum(q.max_tokens == 50 for q in r.requests)
                return await reply(case.step if index == case.reject_step else "YES")
            return LLMResponse(content="the ordinary LLM answer")
        patches.enter_context(patch.object(r.client, "complete", new=complete))
        patches.enter_context(patch("probos.config.COMPILATION_VALIDATION_TIMEOUT_SECONDS", 0.025))
        real_decide, real_act = r.agent.decide, r.agent.act
        real_fallback, real_outcome = r.agent._run_llm_fallback, r.agent._record_compilation_outcome
        real_send = r.bus.send
        async def decide(observation):
            value = await real_decide(observation)
            r.decisions.append(dict(value))
            return value
        async def act(decision):
            r.acts.append({k: decision.get(k) for k in ("cached", "guided_by_procedure", "procedure_id", "llm_output")})
            if case.fail_action and (decision.get("cached") or decision.get("guided_by_procedure")):
                return {"success": False, "error": "the selected action failed"}
            if case.fail_recovery and not (decision.get("cached") or decision.get("guided_by_procedure")):
                return {"success": False, "error": "the recovery action failed"}
            return await real_act(decision)
        async def fallback(observation):
            r.counts["recovery"] += 1
            if case.no_recovery:
                return None
            return await real_fallback(observation)
        async def outcome(procedure_id, success, **kwargs):
            r.outcomes.append([procedure_id, success])
            return await real_outcome(procedure_id, success, **kwargs)
        async def send(intent, **kwargs):
            r.deliveries.append({"intent": intent.intent, "params": intent.params,
                                 "target_agent_id": intent.target_agent_id, "ttl_seconds": intent.ttl_seconds})
            if case.dispatch == "raise":
                raise RuntimeError("selected dispatch failure")
            return await real_send(intent, **kwargs)
        async def rejected_target(intent):
            r.counts["target_rejected"] += 1
            return IntentResult(intent_id=intent.id, agent_id=r.target.id, success=False,
                                error="the target reported failure")
        for name, callback in (("decide", decide), ("act", act), ("_run_llm_fallback", fallback),
                               ("_record_compilation_outcome", outcome)):
            patches.enter_context(patch.object(r.agent, name, new=callback))
        patches.enter_context(patch.object(r.bus, "send", new=send))
        if case.dispatch == "failed":
            patches.enter_context(patch.object(r.target, "_handle_compound_step_replay", new=rejected_target))
        if case.formatting_error:
            patches.enter_context(patch.object(r.agent, "_format_procedure_replay", side_effect=ValueError("selected format failure")))
        for name in ("record_selection", "record_applied", "record_completion", "record_fallback", "record_consecutive_success",
                     "promote_compilation_level", "demote_compilation_level", "reset_consecutive_successes"):
            original = getattr(r.store, name)
            async def counted(*args, _name=name, _original=original, **kwargs):
                r.counts[_name] += 1
                if _name == case.accounting_error:
                    raise RuntimeError(f"selected {_name} failure")
                return await _original(*args, **kwargs)
            patches.enter_context(patch.object(r.store, name, new=counted))
        result = await _handle_on_store(r.agent)
        if getattr(r, "settle", None) is not None:
            await r.settle()
    sql_count = len(r.sql)
    loaded = await r.store.get(r.proc.id)
    metrics = await r.store.get_quality_metrics(r.proc.id)
    events = [data for kind, data, *other in r.events if kind is EventType.TASK_EXECUTION_COMPLETE]
    learn = [data for kind, data, *other in r.events if kind is EventType.PROCEDURE_FALLBACK_LEARNING]
    row = {"name": case.name, "row": case.row, "result_success": result.success, "result": result.result,
           "error": result.error, "level": loaded.compilation_level, "consecutive": metrics["consecutive_successes"],
           "counts": dict(r.counts), "helper_calls": r.outcomes, "cached_decision": bool(r.decisions[-1].get("cached")),
           "guided_decision": bool(r.decisions[-1].get("guided_by_procedure")),
           "acts": [{"cached": bool(a["cached"]), "guided": bool(a["guided_by_procedure"]), "procedure_id": a["procedure_id"]} for a in r.acts],
           "validation_limits": [q.max_tokens for q in r.requests if q.max_tokens in (50, 100)],
           "ordinary_calls": sum(q.max_tokens not in (50, 100) for q in r.requests),
           "delivered": len(r.deliveries), "events": events, "learning": learn,
           "sql_statements": sql_count, "fallback_info": r.agent._last_fallback_info}
    print("RESULT_PATH", json.dumps(row, default=str), flush=True)
    if not verify:
        return row
    assert result is not None
    assert len(events) == 1, "the completion event is not emitted exactly once"
    assert len([p for p, success in r.outcomes if p]) <= 1, "one intent performed accounting twice"
    assert sum(r.counts[n] for n in ("record_consecutive_success", "demote_compilation_level", "reset_consecutive_successes")) <= 1
    assert r.counts["record_completion"] + r.counts["record_fallback"] <= 1
    assert all(q.tier == r.agent._resolve_tier() for q in r.requests if q.max_tokens in (50, 100))
    overall_rejected = case.overall not in ("YES", "raise", "timeout", "error-reply")
    step_rejected = (case.compound and not case.missing and case.level == 3 and
                     case.step not in ("YES", "raise", "timeout", "error-reply"))
    failed_replay = step_rejected or case.fail_action
    if overall_rejected:
        assert row["cached_decision"] is False and row["guided_decision"] is False
        assert result.success is True and result.result == "the ordinary LLM answer"
        assert events[0]["used_procedure"] is False and row["delivered"] == 0
        assert r.counts["record_completion"] == r.counts["record_fallback"] == 0
        assert [e["fallback_type"] for e in learn] == ["validation_failure"]
        assert len(r.outcomes) == 2 and r.outcomes[1][0] is None, "the tail must not carry the rejected procedure id"
        if not case.accounting_error:
            assert (row["level"], row["consecutive"]) == (2, 0)
    elif case.formatting_error:
        assert not row["cached_decision"] and len(learn) == 1 and learn[0]["fallback_type"] == "format_exception"
        assert result.success and not r.counts["record_consecutive_success"]
        assert (row["level"], row["consecutive"]) == (case.level, 2)
    elif failed_replay:
        assert r.counts["record_completion"] == 0 and r.counts["record_fallback"] == 1
        cached = bool(row["cached_decision"])
        assert r.counts["recovery"] == int(cached)
        assert events[0]["used_procedure"] is cached
        if step_rejected:
            assert not any(a["cached"] for a in row["acts"]), "act ran on an explicitly rejected cached replay"
            assert row["delivered"] == case.reject_step
        recovered = cached and not (case.no_recovery or case.fail_recovery)
        assert result.success is recovered
        assert len(learn) == int(recovered)
        if recovered:
            assert result.result == "the ordinary LLM answer" and learn[0]["fallback_type"] == "execution_failure"
            if step_rejected:
                assert learn[0]["rejection_reason"] == f"Compound step {case.reject_step} output failed Level 3 validation"
        elif step_rejected:
            assert result.error == f"Compound step {case.reject_step} output failed Level 3 validation"
        if not case.accounting_error:
            assert (row["level"], row["consecutive"]) == (2, 0)
    else:
        assert result.success and r.counts["record_completion"] == 1 and r.counts["record_fallback"] == 0
        assert r.counts["record_consecutive_success"] == 1
        assert events[0]["used_procedure"] is row["cached_decision"]
        if case.compound and not case.missing:
            assert not r.acts and row["delivered"] == 2
            assert events[0]["compound_dispatched"] is True and events[0]["steps_dispatched"] == 2
        if case.missing:
            assert len(r.acts) == 1 and r.acts[0]["cached"] and row["delivered"] == 0
        if not case.accounting_error:
            expected_level = case.level
            expected_count = 3
            if case.level == 2 and case.score >= 0.5:
                expected_level, expected_count = 3, 0
            elif case.level == 3:
                expected_level, expected_count = 4, 0
            elif case.level == 4 and case.approved and case.score >= 0.7:
                expected_level, expected_count = 5, 0
            elif case.level == 4 and case.score < 0.5:
                expected_count = 2  # A6 (D28): a clamped Guided run of a stored Level 4 procedure executed at Level 2: not counted
            assert (row["level"], row["consecutive"]) == (expected_level, expected_count)
    return row

@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_each_result_path_crosses_the_lifecycle_once(tmp_path, case, caplog):
    caplog.set_level(logging.WARNING, logger="probos.cognitive.cognitive_agent")
    r = await make_rig(tmp_path, case)
    try:
        row = await execute_case(r, case)
        failed_calls = sum(1 for q in r.requests if q.max_tokens == 100 and case.overall in ("raise", "timeout", "error-reply"))
        failed_calls += int(case.step in ("raise", "timeout", "error-reply") and any(q.max_tokens == 50 for q in r.requests))
        warnings = [record for record in caplog.records if "validation call failed" in record.getMessage()]
        assert len(warnings) == failed_calls, [record.getMessage() for record in caplog.records]
    finally:
        r.bus.unsubscribe(r.target.id)
        await r.client.close()
        await r.store.stop()
