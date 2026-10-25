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
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch
import pytest
from probos.cognitive.cognitive_agent import _DECISION_CACHES
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.consensus.trust import TrustNetwork
from probos.types import AgentState, IntentMessage, LLMResponse, Priority
from tests.test_replay_dispatch import ReplayTestAgent
from test_result_paths import Case, make_rig

@pytest.fixture(autouse=True)
def clear_caches():
    _DECISION_CACHES.clear()
    yield
    _DECISION_CACHES.clear()

@pytest.mark.asyncio
@pytest.mark.parametrize("compound", [False, True], ids=["single", "compound"])
async def test_a_later_validation_demotion_is_not_overwritten_by_stale_success_accounting(tmp_path, compound):
    r = await make_rig(tmp_path, Case("outcome-order", 3, level=2, compound=compound))
    r.agent.state = AgentState.ACTIVE
    peer_client = OpenAICompatibleClient(base_url="http://127.0.0.1:9/v1")
    peer = ReplayTestAgent(llm_client=peer_client, runtime=r.runtime)
    peer.state = AgentState.ACTIVE
    await r.registry.register(peer)
    trust = TrustNetwork()
    for agent in (r.agent, peer):
        trust.create_with_prior(agent.id, alpha=5.0, beta=5.0)
    r.runtime.trust_network = trust
    for agent in (r.agent, peer):
        agent.set_concurrency_manager(ConcurrencyManager(agent_id=agent.id, max_concurrent=1))
    r.bus.subscribe(r.agent.id, r.agent.handle_intent, intent_names=["test_intent"])
    r.bus.subscribe(peer.id, peer.handle_intent, intent_names=["test_intent"])
    snapshot_taken, demotion_done = asyncio.Event(), asyncio.Event()
    trace, first_requests, peer_requests = [], [], []
    state = {"success_task": None, "success_counted": False, "blocked": False}
    original_get = r.store.get
    original_count = r.store.record_consecutive_success
    original_demote = r.store.demote_compilation_level
    original_promote = r.store.promote_compilation_level
    original_outcome = r.agent._record_compilation_outcome
    async def outcome(procedure_id, success, **kwargs):
        if procedure_id and success:
            state["success_task"] = asyncio.current_task()
        return await original_outcome(procedure_id, success, **kwargs)
    async def count(procedure_id, **kwargs):
        value = await original_count(procedure_id, **kwargs)
        if asyncio.current_task() is state["success_task"]:
            state["success_counted"] = True
            trace.append({"event": "success_count_read", "count": value})
        return value
    async def get(procedure_id):
        value = await original_get(procedure_id)
        if asyncio.current_task() is state["success_task"] and state["success_counted"] and not state["blocked"]:
            state["blocked"] = True
            trace.append({"event": "success_level_read", "level": value.compilation_level})
            snapshot_taken.set()
            await asyncio.wait_for(demotion_done.wait(), 5)
        return value
    async def demote(procedure_id, level):
        await original_demote(procedure_id, level)
        loaded = await original_get(procedure_id)
        metrics = await r.store.get_quality_metrics(procedure_id)
        trace.append({"event": "NO_demotion_committed", "level": loaded.compilation_level, "count": metrics["consecutive_successes"]})
        demotion_done.set()
    async def promote(procedure_id, level, **kwargs):
        loaded = await original_get(procedure_id)
        metrics = await r.store.get_quality_metrics(procedure_id)
        trace.append({"event": "promotion_requested_after_demotion", "stored_level": loaded.compilation_level, "stored_count": metrics["consecutive_successes"], "requested_level": level, "kwargs": sorted(kwargs)})
        applied = await original_promote(procedure_id, level, **kwargs)
        trace.append({"event": "promotion_result", "applied": applied})
        return applied
    async def first_complete(request, *, priority=Priority.NORMAL):
        first_requests.append(request)
        return LLMResponse(content="YES" if request.max_tokens in (50, 100) else "the ordinary LLM answer")
    async def peer_complete(request, *, priority=Priority.NORMAL):
        peer_requests.append(request)
        return LLMResponse(content="NO" if request.max_tokens == 100 else "the ordinary LLM answer")
    def message(agent):
        return IntentMessage(intent="test_intent", params={"message": "perform the learned operation"}, target_agent_id=agent.id, ttl_seconds=20)
    running = None
    try:
        with ExitStack() as patches:
            for agent in (r.agent, peer):
                patches.enter_context(patch.object(agent, "_recall_relevant_memories", new=AsyncMock(side_effect=lambda i, obs: obs)))
                patches.enter_context(patch.object(agent, "_store_action_episode", new=AsyncMock()))
            patches.enter_context(patch.object(r.client, "complete", new=first_complete))
            patches.enter_context(patch.object(peer_client, "complete", new=peer_complete))
            await r.store.reset_consecutive_successes(r.proc.id)
            warm_levels = []
            for _ in range(5):
                warm = await r.bus.send(message(r.agent))
                assert warm is not None and warm.success
                warm_levels.append((await original_get(r.proc.id)).compilation_level)
            warm_metrics = await r.store.get_quality_metrics(r.proc.id)
            assert warm_levels == [2, 2, 3, 3, 3]
            assert (warm_metrics["total_completions"], warm_metrics["consecutive_successes"]) == (5, 2)
            first_requests.clear()
            patches.enter_context(patch.object(r.agent, "_record_compilation_outcome", new=outcome))
            for name, callback in (("get", get), ("record_consecutive_success", count), ("demote_compilation_level", demote), ("promote_compilation_level", promote)):
                patches.enter_context(patch.object(r.store, name, new=callback))
            running = asyncio.create_task(r.bus.send(message(r.agent)))
            await asyncio.wait_for(snapshot_taken.wait(), 5)
            peer_result = await r.bus.send(message(peer))
            success_result = await asyncio.wait_for(running, 5)
            loaded = await original_get(r.proc.id)
            metrics = await r.store.get_quality_metrics(r.proc.id)
            calls_before = len(peer_requests)
            next_result = await r.bus.send(message(peer))
            later_calls = [request.max_tokens for request in peer_requests[calls_before:]]
        print("SHARED_OUTCOME_ORDER", json.dumps({"compound": compound, "warm_levels": warm_levels, "warm_completions": warm_metrics["total_completions"], "trace": trace, "final_level": loaded.compilation_level,
            "final_count": metrics["consecutive_successes"], "first_success": success_result.success, "NO_intent_success": peer_result.success,
            "NO_requests": [request.max_tokens for request in peer_requests[:calls_before]], "next_intent_success": next_result.success,
            "next_intent_LLM_requests": later_calls, "next_result": next_result.result}, default=str), flush=True)
        assert success_result is not None and success_result.success and peer_result is not None and peer_result.success
        assert [item["event"] for item in trace[:4]] == ["success_count_read", "success_level_read", "NO_demotion_committed", "promotion_requested_after_demotion"]
        assert trace[2]["level"] == 2 and trace[2]["count"] == 0
        assert loaded.compilation_level == 2, "a success that read the old level/count overwrote the later NO demotion"
    finally:
        demotion_done.set()
        if running is not None and not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        for agent in (r.agent, peer, r.target):
            r.bus.unsubscribe(agent.id)
        await r.client.close()
        await peer_client.close()
        await r.store.stop()
