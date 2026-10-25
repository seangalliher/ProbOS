import os
import sys
from pathlib import Path
TREE=Path(os.environ.get('BF924_SOURCE_TREE',r'D:\ProbOS-worktrees\bf924-review1'))
sys.path[:0]=[str(TREE/'src'),str(TREE)]
import probos
print('SOURCE',probos.__file__,flush=True)
assert Path(probos.__file__).resolve()==(TREE/'src/probos/__init__.py').resolve()
import asyncio
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock,patch
import pytest
from probos.cognitive.cognitive_agent import _DECISION_CACHES
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.cognitive.engineering_officer import EngineeringAgent
from probos.cognitive.operations_officer import OperationsAgent
from probos.cognitive.security_officer import SecurityAgent
from probos.cognitive.training_officer import TrainingAgent
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.consensus.trust import TrustNetwork
from probos.types import AgentState,IntentMessage,LLMResponse,Priority
from test_result_paths import Case,make_rig

@pytest.mark.asyncio
async def test_only_outcomes_from_level_3_supply_the_level_4_threshold(tmp_path):
    _DECISION_CACHES.clear()
    r=await make_rig(tmp_path,Case('validation-epoch',1,level=2))
    clients=[r.client]+[OpenAICompatibleClient(base_url='http://127.0.0.1:9/v1') for _ in range(3)]
    agents=[c(llm_client=client,runtime=r.runtime) for c,client in zip((EngineeringAgent,OperationsAgent,SecurityAgent,TrainingAgent),clients)]
    assert r.proc.postconditions and r.proc.steps[0].expected_output, 'the same procedure must require Level 3 validation'
    r.proc.intent_types=['direct_message']
    await r.store.save(r.proc)
    ready=[asyncio.Event() for _ in agents]
    release=[asyncio.Event() for _ in agents]
    guided_entries,decisions,calls,tasks,rows=[],[],[],[],[]
    state={'warming':True}
    network=TrustNetwork()
    def message(a):
        return IntentMessage(intent='direct_message',params={'message':'perform the learned operation'},target_agent_id=a.id,ttl_seconds=30)
    try:
        with ExitStack() as patches:
            for i,(a,client) in enumerate(zip(agents,clients)):
                a.state=AgentState.ACTIVE
                await r.registry.register(a)
                network.create_with_prior(a.id,alpha=5,beta=5)
                a.set_concurrency_manager(ConcurrencyManager(agent_id=a.id,max_concurrent=1))
                r.bus.subscribe(a.id,a.handle_intent,intent_names=['direct_message'])
                async def complete(q,*,priority=Priority.NORMAL,_i=i):
                    calls.append({'agent':_i,'max_tokens':q.max_tokens})
                    if q.max_tokens in (50,100):
                        return LLMResponse(content='YES')
                    if not state['warming']:
                        ready[_i].set()
                        await asyncio.wait_for(release[_i].wait(),10)
                    return LLMResponse(content='the guided answer')
                patches.enter_context(patch.object(client,'complete',new=complete))
                patches.enter_context(patch.object(a,'_recall_relevant_memories',new=AsyncMock(side_effect=lambda i,o:o)))
                patches.enter_context(patch.object(a,'_store_action_episode',new=AsyncMock()))
                original_guide=a._build_guided_decision
                async def guide(proc,obs,score,_i=i,_original=original_guide):
                    guided_entries.append({'agent':_i,'read_snapshot_level':proc.compilation_level})
                    return await _original(proc,obs,score)
                patches.enter_context(patch.object(a,'_build_guided_decision',new=guide))
                original_decide=a.decide
                async def decide(obs,_i=i,_original=original_decide):
                    d=await _original(obs)
                    decisions.append({'agent':_i,'guided':d.get('guided_by_procedure'),'effective_level':d.get('compilation_level'),'cached':d.get('cached')})
                    return d
                patches.enter_context(patch.object(a,'decide',new=decide))
            r.runtime.trust_network=network
            # Establish the count with ordinary completed turns, not a direct counter write.
            for _ in range(2):
                warm=await r.bus.send(message(agents[0]))
                assert warm is not None and warm.success
            warm_metrics=await r.store.get_quality_metrics(r.proc.id)
            assert warm_metrics['consecutive_successes']==2
            assert (await r.store.get(r.proc.id)).compilation_level==2
            guided_entries.clear();decisions.clear();calls.clear()
            state['warming']=False
            tasks=[asyncio.create_task(r.bus.send(message(a))) for a in agents]
            await asyncio.wait_for(asyncio.gather(*(e.wait() for e in ready)),10)
            assert len(guided_entries)==4 and all(e['read_snapshot_level']==2 for e in guided_entries)
            assert len(decisions)==0,'the pending LLM calls must not already have completed'
            assert len(calls)==4 and all(q['max_tokens'] not in (50,100) for q in calls)
            pending_entries=list(guided_entries)
            for i,t in enumerate(tasks):
                release[i].set()
                result=await asyncio.wait_for(t,10)
                assert result is not None and result.success
                p=await r.store.get(r.proc.id)
                m=await r.store.get_quality_metrics(r.proc.id)
                rows.append({'finished':i,'snapshot_level':p.compilation_level,'count':m['consecutive_successes']})
            assert len(decisions)==4 and all(d['guided'] is True and d['effective_level']==2 for d in decisions)
            wave_decisions=list(decisions)
            wave_calls=list(calls)
            before=len(calls)
            next_result=await r.bus.send(message(agents[0]))
            assert next_result is not None and next_result.success
            next_calls=calls[before:]
        final=(await r.store.get(r.proc.id)).compilation_level
        print('VALIDATION_EPOCH',json.dumps({'agent_types':[a.agent_type for a in agents],'warm_count':warm_metrics['consecutive_successes'],'all_four_pending_guided_LLM_calls':pending_entries,'completed_decisions':wave_decisions,'committed':rows,'validation_calls':[q for q in wave_calls if q['max_tokens'] in (50,100)],'next_intent_calls':next_calls,'final_snapshot_level':final,'held_boundary':'real LLM complete await; acts are unmodified'}),flush=True)
        assert final<=3,'Guided outcomes were credited at Level 3 and committed zero-validation Level 4'
    finally:
        for e in release:e.set()
        for t in tasks:
            if not t.done():t.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        for a in agents:r.bus.unsubscribe(a.id)
        r.bus.unsubscribe(r.target.id)
        for client in clients:await client.close()
        await r.store.stop()
        _DECISION_CACHES.clear()