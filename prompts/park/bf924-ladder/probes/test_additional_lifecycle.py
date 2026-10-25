import os
import sys
from pathlib import Path
TREE = Path(os.environ.get("BF924_SOURCE_TREE", r"D:\ProbOS-worktrees\bf924-review1"))
sys.path[:0] = [str(TREE / "src"), str(TREE)]
import probos
print("SOURCE", probos.__file__, flush=True)
assert Path(probos.__file__).resolve() == (TREE / "src/probos/__init__.py").resolve()
import json
from unittest.mock import AsyncMock, patch
import pytest
from probos.cognitive.cognitive_agent import _DECISION_CACHES
from probos.cognitive.counselor import CounselorAgent
from probos.events import EventType
from probos.types import AgentState, IntentMessage, LLMResponse, Priority
from tests.test_bf924_compilation_trust import trust_network_at
from test_result_paths import Case, make_rig, execute_case

@pytest.fixture(autouse=True)
def clear_caches():
    _DECISION_CACHES.clear()
    yield
    _DECISION_CACHES.clear()

@pytest.mark.asyncio
async def test_compound_ladder_crosses_guided_validated_and_autonomous_paths(tmp_path):
    case = Case("compound-ladder", 11, level=2, compound=True)
    r = await make_rig(tmp_path, case)
    await r.store.reset_consecutive_successes(r.proc.id)
    rows = []
    try:
        for n in range(9):
            for collection in (r.requests, r.deliveries, r.decisions, r.acts, r.outcomes, r.sql, r.events):
                collection.clear()
            r.counts.clear()
            row = await execute_case(r, case, verify=False)
            assert r.counts["record_completion"] == r.counts["record_consecutive_success"] == 1
            assert r.counts["record_fallback"] == 0 and len(r.outcomes) == 1
            assert row["result_success"] and len(row["events"]) == 1
            rows.append({key: row[key] for key in ("level", "consecutive", "delivered", "validation_limits", "ordinary_calls", "sql_statements")})
        assert [row["level"] for row in rows] == [2, 2, 3, 3, 3, 4, 4, 4, 4]
        assert [row["validation_limits"] for row in rows] == [[]] * 3 + [[100, 50, 50]] * 3 + [[]] * 3
        assert [row["delivered"] for row in rows] == [0] * 3 + [2] * 6
        assert [row["consecutive"] for row in rows] == [1, 2, 0, 1, 2, 0, 1, 2, 3]
        print("COMPOUND_LADDER", json.dumps(rows), flush=True)
    finally:
        r.bus.unsubscribe(r.target.id)
        await r.client.close()
        await r.store.stop()

@pytest.mark.asyncio
@pytest.mark.parametrize("recover", [True, False], ids=["healthy-provider", "no-recovery-decision"])
async def test_a_counselor_rejected_replay_preserves_its_error_and_can_recover(tmp_path, recover, bridge_fix=False):
    r = await make_rig(tmp_path, Case("real-counselor-rejection", 8, compound=True, step="NO"))
    agent = CounselorAgent(llm_client=r.client, runtime=r.runtime)
    agent.state = AgentState.ACTIVE
    await r.registry.register(agent)
    r.runtime.trust_network = trust_network_at(agent.id, 0.5)
    calls, acts, reports = [], [], []
    async def complete(request, *, priority=Priority.NORMAL):
        calls.append(request)
        return LLMResponse(content="YES" if request.max_tokens == 100 else "NO" if request.max_tokens == 50 else "the ordinary LLM answer")
    real_act, real_report = agent.act, agent.report
    async def act(decision):
        acts.append(dict(decision))
        return await real_act(decision)
    async def report(result):
        if bridge_fix and not recover and isinstance(result, dict) and result.get("success") is False:
            result = {**result, "result": None}
        value = await real_report(result)
        reports.append({"input": result, "output": value})
        return value
    intent = IntentMessage(intent="direct_message", params={"message": "perform the learned two-step operation"}, target_agent_id=agent.id)
    try:
        with patch.object(r.client, "complete", new=complete), patch.object(agent, "act", new=act), patch.object(agent, "report", new=report), patch.object(agent, "_recall_relevant_memories", new=AsyncMock(side_effect=lambda i, obs: obs)), patch.object(agent, "_store_action_episode", new=AsyncMock()):
            if recover:
                real_fallback = agent._run_llm_fallback
                async def fallback_with_intent(observation):
                    value = await real_fallback(observation)
                    if value is not None and bridge_fix:
                        value["intent"] = observation["intent"]
                    return value
                with patch.object(agent, "_run_llm_fallback", new=fallback_with_intent):
                    result = await agent.handle_intent(intent)
            else:
                with patch.object(agent, "_run_llm_fallback", new=AsyncMock(return_value=None)):
                    result = await agent.handle_intent(intent)
        metrics = await r.store.get_quality_metrics(r.proc.id)
        print("COUNSELOR_BOUNDARY", json.dumps({"recover": recover, "success": result.success, "result": result.result, "error": result.error,
              "requests": [q.max_tokens for q in calls], "acts": acts, "reports": reports,
              "level": (await r.store.get(r.proc.id)).compilation_level, "metrics": metrics,
              "events": [(kind.value, data) for kind, data, *other in r.events]}, default=str), flush=True)
        assert [q.max_tokens for q in calls][:2] == [100, 50], "the real Counselor never reached the step rejection"
        assert not any(a.get("cached") for a in acts), "the rejected cached replay was acted on"
        assert metrics["total_completions"] == 0 and metrics["total_fallbacks"] == 1
        if recover:
            assert len(calls) == 3 and len(acts) == 1, "the recovery provider and action were not reached"
            assert result.success and result.result == "the ordinary LLM answer", "the real Counselor cannot use the successful recovery decision"
        else:
            assert not result.success
            assert result.error == "Compound step 1 output failed Level 3 validation", "the real Counselor report lost the rejected step reason"
    finally:
        r.bus.unsubscribe(r.target.id)
        await r.client.close()
        await r.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("recover", [True, False], ids=["healthy-provider", "no-recovery-decision"])
async def test_the_minimal_failure_context_is_accepted_by_real_counselor(tmp_path, recover):
    await test_a_counselor_rejected_replay_preserves_its_error_and_can_recover(tmp_path, recover, bridge_fix=True)

@pytest.mark.asyncio
async def test_a_real_counselor_reaches_the_rejected_replay_through_normal_promotions(tmp_path):
    r = await make_rig(tmp_path, Case("counselor-real-ladder", 8, level=2, compound=True))
    agent = CounselorAgent(llm_client=r.client, runtime=r.runtime)
    agent.state = AgentState.ACTIVE
    await r.registry.register(agent)
    r.runtime.trust_network = trust_network_at(agent.id, 0.5)
    r.proc.intent_types = ["direct_message"]
    await r.store.save(r.proc)
    await r.store.reset_consecutive_successes(r.proc.id)
    calls, rows = [], []
    async def complete(request, *, priority=Priority.NORMAL):
        calls.append(request)
        return LLMResponse(content="YES" if request.max_tokens == 100 else "NO" if request.max_tokens == 50 else "the ordinary LLM answer")
    try:
        with patch.object(r.client, "complete", new=complete), patch.object(agent, "_recall_relevant_memories", new=AsyncMock(side_effect=lambda i, obs: obs)), patch.object(agent, "_store_action_episode", new=AsyncMock()):
            for n in range(4):
                before = len(calls)
                intent = IntentMessage(intent="direct_message", params={"message": "perform the learned two-step operation"}, target_agent_id=agent.id)
                result = await agent.handle_intent(intent)
                metrics = await r.store.get_quality_metrics(r.proc.id)
                rows.append({"turn": n + 1, "success": result.success, "result": result.result, "error": result.error,
                    "level": (await r.store.get(r.proc.id)).compilation_level, "consecutive": metrics["consecutive_successes"],
                    "completions": metrics["total_completions"], "fallbacks": metrics["total_fallbacks"], "request_limits": [q.max_tokens for q in calls[before:]]})
        print("COUNSELOR_NORMAL_LADDER", json.dumps(rows), flush=True)
        assert [row["level"] for row in rows] == [2, 2, 3, 2], "the stored procedure did not reach and reject a validated replay"
        assert all(row["success"] and row["result"] == "the ordinary LLM answer" for row in rows[:3])
        assert rows[3]["request_limits"] == [100, 50, 2048], "the validator and healthy recovery provider were not both reached"
        assert rows[3]["success"] and rows[3]["result"] == "the ordinary LLM answer", "an ordinary promoted Counselor replay cannot recover despite a successful LLM answer"
    finally:
        r.bus.unsubscribe(r.target.id)
        await r.client.close()
        await r.store.stop()
