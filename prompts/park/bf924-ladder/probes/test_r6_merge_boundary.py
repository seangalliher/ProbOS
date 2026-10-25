import os,sys
from pathlib import Path
TREE=Path(os.environ.get('BF924_SOURCE_TREE',str(Path(os.environ['PYTHONPATH'].split(';')[0]).parent)))
sys.path[:0]=[str(TREE/'src'),str(TREE)]
import probos
print('SOURCE',probos.__file__,flush=True)
assert Path(probos.__file__).resolve()==(TREE/'src/probos/__init__.py').resolve()
import asyncio,json
from contextlib import ExitStack
from unittest.mock import AsyncMock,patch
import pytest
from probos.cognitive.architect import ArchitectAgent
from probos.cognitive.engineering_officer import EngineeringAgent
from probos.cognitive.cognitive_agent import _DECISION_CACHES
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.consensus.trust import TrustNetwork
from probos.routers.procedures import MergeRequest,merge_procedures as merge_route
from probos.types import AgentState,IntentMessage,LLMResponse,Priority
from tests.test_fallback_learning import _make_procedure
from r6_result_rig import Case,make_rig

@pytest.mark.asyncio
async def test_a_metadata_merge_preserves_the_current_level_and_its_success_provenance(tmp_path):
    _DECISION_CACHES.clear()
    r=await make_rig(tmp_path,Case('merge-level-provenance',1,level=2))
    engineering=EngineeringAgent(llm_client=r.client,runtime=r.runtime)
    other=OpenAICompatibleClient(base_url='http://127.0.0.1:9/v1')
    architect=ArchitectAgent(llm_client=other,runtime=r.runtime)
    network=TrustNetwork()
    for a in (engineering,architect):a.state=AgentState.ACTIVE;network.create_with_prior(a.id,alpha=5,beta=5)
    r.runtime.trust_network=network
    r.proc.intent_types=['direct_message','design_feature'];await r.store.save(r.proc)
    duplicate=_make_procedure(id='duplicate-for-metadata-merge',compilation_level=1)
    duplicate.tags=['merge-provenance'];await r.store.save(duplicate)
    selected,released=asyncio.Event(),asyncio.Event()
    owner={'task':None,'reads':0}
    calls=[];decisions=[];snapshots=[]
    phase={'value':'warm'}
    async def row():
        cur=await r.store._db.execute("SELECT compilation_level,COALESCE(json_extract(content_snapshot,'$.compilation_level'),1),consecutive_successes FROM procedure_records WHERE id=?",(r.proc.id,))
        return tuple(await cur.fetchone())
    async def complete(q,*,priority=Priority.NORMAL):
        calls.append((phase['value'],'engineering',q.max_tokens));return LLMResponse(content='YES' if q.max_tokens in (50,100) else 'the guided answer')
    async def architect_complete(q,*,priority=Priority.NORMAL):
        calls.append((phase['value'],'architect',q.max_tokens));return LLMResponse(content='YES' if q.max_tokens in (50,100) else 'No proposal is available')
    execute0=r.store._db.execute;merge0=r.store.merge_procedures
    async def merge(primary,duplicate):
        owner['task']=asyncio.current_task();return await merge0(primary,duplicate)
    async def execute(query,parameters=()):
        cursor=await execute0(query,parameters)
        if asyncio.current_task() is owner['task'] and query=='SELECT content_snapshot FROM procedure_records WHERE id = ?' and parameters==(r.proc.id,):
            owner['reads']+=1
            if owner['reads']==2:
                fetch0=cursor.fetchone
                async def fetchone():
                    value=await fetch0();data=json.loads(value[0]);snapshots.append(data['compilation_level'])
                    assert data['compilation_level']==3 and not r.store._write_lock.locked()
                    selected.set();await asyncio.wait_for(released.wait(),10);return value
                cursor.fetchone=fetchone
        return cursor
    async def send(a,intent='direct_message'):
        return await a.handle_intent(IntentMessage(intent=intent,params={'message':'perform the learned operation','feature':'perform the learned design operation'},target_agent_id=a.id))
    task=None
    try:
        with ExitStack() as stack:
            for a in (engineering,architect):
                stack.enter_context(patch.object(a,'_recall_relevant_memories',new=AsyncMock(side_effect=lambda i,o:o)))
                stack.enter_context(patch.object(a,'_store_action_episode',new=AsyncMock()))
                original=a.decide
                async def decide(obs,_original=original,_agent=a):
                    d=await _original(obs);decisions.append((phase['value'],_agent.agent_type,d.get('compilation_level'),bool(d.get('cached'))));return d
                stack.enter_context(patch.object(a,'decide',new=decide))
            stack.enter_context(patch.object(r.client,'complete',new=complete))
            stack.enter_context(patch.object(other,'complete',new=architect_complete))
            warm=[]
            for _ in range(3):
                result=await send(engineering);assert result is not None and result.success;warm.append(await row())
            assert warm==[(2,2,1),(2,2,2),(3,3,0)]
            stack.enter_context(patch.object(r.store,'merge_procedures',new=merge))
            stack.enter_context(patch.object(r.store._db,'execute',new=execute))
            task=asyncio.create_task(merge_route(MergeRequest(primary_id=r.proc.id,duplicate_id=duplicate.id),runtime=r.runtime))
            await asyncio.wait_for(selected.wait(),10)
            phase['value']='failed-validated-replay'
            failed=await send(architect,'design_feature')
            assert failed is not None and not failed.success and failed.error=='No ===PROPOSAL=== block found in LLM output'
            demoted=await row();assert demoted==(2,2,0)
            phase['value']='guided-after-failure';guided=[]
            for _ in range(2):
                result=await send(engineering);assert result is not None and result.success;guided.append(await row())
            assert guided==[(2,2,1),(2,2,2)]
            assert [q[2] for q in calls if q[0]=='guided-after-failure']==[2048,2048]
            released.set();reply=await asyncio.wait_for(task,10);assert reply['success'] is True
            after_merge=await row();assert (await r.store.get(duplicate.id)).is_active is False
            phase['value']='one-successful-validated-replay'
            result=await send(engineering);assert result is not None and result.success
            after_one=await row()
            phase['value']='next-intent';before=len(calls)
            result=await send(engineering);assert result is not None and result.success
            next_calls=calls[before:]
        print('MERGE_PROVENANCE_A6',json.dumps({'warm':warm,'merge_snapshot_read':snapshots,'after_real_architect_failure':demoted,'two_guided_successes':guided,'after_metadata_merge':after_merge,'after_one_successful_level_3_replay':after_one,'next_intent_calls':next_calls,'calls':calls,'decisions':decisions,'real_route_reply_success':reply['success'],'held_boundary':'real merge cursor.fetchone await outside the write lock; unmodified real acts and reports'}),flush=True)
        assert after_one[1]<=3, 'the merge relabelled two Guided successes as Level 3 successes and supplied Level 4 after only one successful validation'
    finally:
        released.set()
        if task is not None and not task.done():task.cancel()
        if task is not None:await asyncio.gather(task,return_exceptions=True)
        r.bus.unsubscribe(r.target.id);await r.client.close();await other.close();await r.store.stop();_DECISION_CACHES.clear()