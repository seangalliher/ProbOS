import os,sys
from pathlib import Path
TREE=Path(os.environ.get('BF924_SOURCE_TREE',str(Path(os.environ['PYTHONPATH'].split(';')[0]).parent)))
sys.path[:0]=[str(TREE/'src'),str(TREE)]
import probos
print('SOURCE',probos.__file__,flush=True)
assert Path(probos.__file__).resolve()==(TREE/'src/probos/__init__.py').resolve()
import asyncio,json,time
from contextlib import ExitStack
from contextvars import ContextVar
from unittest.mock import AsyncMock,patch
import pytest
from probos.cognitive.architect import ArchitectAgent
from probos.cognitive.cognitive_agent import _DECISION_CACHES
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.cognitive.engineering_officer import EngineeringAgent
from probos.cognitive.operations_officer import OperationsAgent
from probos.cognitive.security_officer import SecurityAgent
from probos.cognitive.training_officer import TrainingAgent
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.consensus.trust import TrustNetwork
from probos.types import AgentState,IntentMessage,LLMResponse,Priority
from r6_result_rig import Case,make_rig
from tests.test_bf924_compilation_trust import _handle_on_store

@pytest.fixture(autouse=True)
def caches():
    _DECISION_CACHES.clear()
    yield
    _DECISION_CACHES.clear()

async def snapshot(r):
    p=await r.store.get(r.proc.id);m=await r.store.get_quality_metrics(r.proc.id)
    return (p.compilation_level,m['consecutive_successes'])

@pytest.mark.asyncio
async def test_a_return_to_the_same_level_accepts_successes_from_its_earlier_epoch(tmp_path):
    r=await make_rig(tmp_path,Case('same-level-epoch',1,level=2))
    clients=[r.client]+[OpenAICompatibleClient(base_url='http://127.0.0.1:9/v1') for _ in range(3)]
    agents=[c(llm_client=q,runtime=r.runtime) for c,q in zip((EngineeringAgent,OperationsAgent,SecurityAgent,TrainingAgent),clients)]
    held=[asyncio.Event() for _ in range(3)];release=[asyncio.Event() for _ in range(3)]
    actor=ContextVar('actor',default=-1)
    phase={'wave':False,'peer_no':False}
    calls=[];decisions=[];rows=[];tasks=[]
    r.proc.intent_types=['direct_message'];await r.store.save(r.proc)
    net=TrustNetwork()
    def message(a):return IntentMessage(intent='direct_message',params={'message':'perform the learned operation'},target_agent_id=a.id,ttl_seconds=30)
    async def send(i):
        token=actor.set(i)
        try:return await r.bus.send(message(agents[i]))
        finally:actor.reset(token)
    try:
        with ExitStack() as stack:
            for i,(a,client) in enumerate(zip(agents,clients)):
                a.state=AgentState.ACTIVE;net.create_with_prior(a.id,alpha=5,beta=5)
                a.set_concurrency_manager(ConcurrencyManager(agent_id=a.id,max_concurrent=1))
                await r.registry.register(a);r.bus.subscribe(a.id,a.handle_intent,intent_names=['direct_message'])
                async def complete(q,*,priority=Priority.NORMAL,_i=i):
                    assert actor.get()==_i
                    calls.append((_i,q.max_tokens))
                    return LLMResponse(content=('NO' if phase['peer_no'] and _i==3 else 'YES') if q.max_tokens in (50,100) else 'the guided answer')
                stack.enter_context(patch.object(client,'complete',new=complete))
                stack.enter_context(patch.object(a,'_recall_relevant_memories',new=AsyncMock(side_effect=lambda i,o:o)))
                stack.enter_context(patch.object(a,'_store_action_episode',new=AsyncMock()))
                decide0=a.decide
                async def decide(o,_i=i,_original=decide0):
                    d=await _original(o);decisions.append((_i,d.get('compilation_level'),bool(d.get('cached'))));return d
                stack.enter_context(patch.object(a,'decide',new=decide))
            r.runtime.trust_network=net
            warm=[]
            for _ in range(5):
                result=await send(3);assert result is not None and result.success;warm.append(await snapshot(r))
            assert warm==[(2,1),(2,2),(3,0),(3,1),(3,2)]
            complete0=r.store.record_completion
            async def completion(pid):
                await complete0(pid)
                who=actor.get()
                if phase['wave'] and 0<=who<3:
                    held[who].set();await asyncio.wait_for(release[who].wait(),10)
            stack.enter_context(patch.object(r.store,'record_completion',new=completion))
            calls.clear();decisions.clear();phase['wave']=True
            tasks=[asyncio.create_task(send(i)) for i in range(3)]
            await asyncio.wait_for(asyncio.gather(*(e.wait() for e in held)),10)
            assert sorted(decisions)==[(0,3,True),(1,3,True),(2,3,True)]
            assert sorted(calls)==[(0,100),(1,100),(2,100)]
            assert (await snapshot(r))==(3,2)
            phase['peer_no']=True
            no=await send(3);assert no is not None and no.success
            demoted=await snapshot(r);assert demoted==(2,0)
            phase['peer_no']=False
            guided=[]
            for _ in range(3):
                result=await send(3);assert result is not None and result.success;guided.append(await snapshot(r))
            assert guided==[(2,1),(2,2),(3,0)]
            after_repromotion=len(calls)
            for i,t in enumerate(tasks):
                release[i].set();result=await asyncio.wait_for(t,10);assert result is not None and result.success
                rows.append(await snapshot(r))
            credited_calls=calls[after_repromotion:]
            before_next=len(calls);next_result=await send(3)
            assert next_result is not None and next_result.success
            next_calls=calls[before_next:]
        print('SAME_LEVEL_EPOCH_A6',json.dumps({'warm':warm,'already_validated_pending':[0,1,2],'demotion':demoted,'regained_with_guided':guided,'old_success_commits':rows,'new_validation_calls_after_regaining_3':credited_calls,'next_intent_calls':next_calls,'held_boundary':'real record_completion await after real act and validation; no action replaced'}),flush=True)
        assert rows==[(3,1),(3,2),(4,0)]
        assert credited_calls==[] and next_calls==[]
    finally:
        for e in release:e.set()
        for t in tasks:
            if not t.done():t.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        for a in agents:r.bus.unsubscribe(a.id)
        r.bus.unsubscribe(r.target.id)
        for c in clients:await c.close()
        await r.store.stop()

@pytest.mark.asyncio
async def test_decay_does_not_raise_a_procedure_after_a_real_replay_failure(tmp_path):
    r=await make_rig(tmp_path,Case('decay-failure-order',12,level=5,score=0.7,approved=True))
    architect=ArchitectAgent(llm_client=r.client,runtime=r.runtime);architect.state=AgentState.ACTIVE
    next_client=OpenAICompatibleClient(base_url='http://127.0.0.1:9/v1')
    next_agent=EngineeringAgent(llm_client=next_client,runtime=r.runtime);next_agent.state=AgentState.ACTIVE
    net=TrustNetwork()
    for a in (architect,next_agent):net.create_with_prior(a.id,alpha=7,beta=3)
    r.runtime.trust_network=net
    r.proc.intent_types=['design_feature','direct_message'];await r.store.save(r.proc)
    await r.store.approve_promotion(r.proc.id,'captain','review-approval')
    old_time=time.time()-40*86400
    with patch('probos.cognitive.procedure_store.time.time',return_value=old_time):
        for _ in range(3):
            await r.store.record_selection(r.proc.id);await r.store.record_applied(r.proc.id);await r.store.record_completion(r.proc.id)
    selected,released=asyncio.Event(),asyncio.Event()
    old_rows=[];calls=[];next_calls=[];decisions=[]
    execute0=r.store._db.execute
    async def execute(query,parameters=()):
        cursor=await execute0(query,parameters)
        if 'SELECT id, name, compilation_level, content_snapshot' in ' '.join(query.split()):
            fetch0=cursor.fetchall
            async def fetchall():
                rows=await fetch0();old_rows.extend(rows)
                assert len(rows)==1 and rows[0][2]==5 and not r.store._write_lock.locked()
                selected.set();await asyncio.wait_for(released.wait(),10);return rows
            cursor.fetchall=fetchall
        return cursor
    async def complete(q,*,priority=Priority.NORMAL):calls.append(q.max_tokens);return LLMResponse(content='No proposal is available')
    async def next_complete(q,*,priority=Priority.NORMAL):next_calls.append(q.max_tokens);return LLMResponse(content='YES')
    decide0=next_agent.decide
    async def decide(o):
        d=await decide0(o);decisions.append((d.get('compilation_level'),bool(d.get('cached'))));return d
    task=None
    try:
        with ExitStack() as stack:
            for a in (architect,next_agent):
                stack.enter_context(patch.object(a,'_recall_relevant_memories',new=AsyncMock(side_effect=lambda i,o:o)))
                stack.enter_context(patch.object(a,'_store_action_episode',new=AsyncMock()))
            stack.enter_context(patch.object(r.client,'complete',new=complete))
            stack.enter_context(patch.object(next_client,'complete',new=next_complete))
            stack.enter_context(patch.object(next_agent,'decide',new=decide))
            stack.enter_context(patch.object(r.store._db,'execute',new=execute))
            task=asyncio.create_task(r.store.decay_stale_procedures())
            await asyncio.wait_for(selected.wait(),10)
            failed=await architect.handle_intent(IntentMessage(intent='design_feature',params={'feature':'perform the learned design operation'},target_agent_id=architect.id))
            assert failed is not None and not failed.success
            assert failed.error=='No ===PROPOSAL=== block found in LLM output'
            demoted=await snapshot(r);assert demoted==(2,0)
            released.set();decayed=await asyncio.wait_for(task,10)
            after_decay=await snapshot(r)
            next_result=await next_agent.handle_intent(IntentMessage(intent='direct_message',params={'message':'perform the learned operation'},target_agent_id=next_agent.id))
            assert next_result is not None and next_result.success
        print('DECAY_FAILURE_A6',json.dumps({'selected_level':old_rows[0][2],'real_agent':'ArchitectAgent','failure':failed.error,'after_failure':demoted,'decay_receipt':decayed,'after_stale_decay':after_decay,'next_decision':decisions,'next_LLM_calls':next_calls,'failure_LLM_calls':calls,'held_boundary':'real decay cursor.fetchall await; real act and report unchanged'}),flush=True)
        assert after_decay[0]<=demoted[0], 'a stale decay raised a freshly demoted procedure back to autonomous replay'
    finally:
        released.set()
        if task is not None and not task.done():task.cancel()
        if task is not None:await asyncio.gather(task,return_exceptions=True)
        r.bus.unsubscribe(r.target.id);await r.client.close();await next_client.close();await r.store.stop()
@pytest.mark.asyncio
async def test_a_completed_decay_read_after_the_failure_preserves_guided_dispatch(tmp_path):
    r=await make_rig(tmp_path,Case('decay-control',12,level=5,score=0.7,approved=True))
    architect=ArchitectAgent(llm_client=r.client,runtime=r.runtime)
    r.proc.intent_types=['design_feature','direct_message'];await r.store.save(r.proc)
    await r.store.approve_promotion(r.proc.id,'captain','control-approval')
    r.runtime.trust_network.create_with_prior(architect.id,alpha=7,beta=3)
    old_time=time.time()-40*86400
    with patch('probos.cognitive.procedure_store.time.time',return_value=old_time):
        for _ in range(3):
            await r.store.record_selection(r.proc.id);await r.store.record_applied(r.proc.id);await r.store.record_completion(r.proc.id)
    calls=[]
    async def complete(q,*,priority=Priority.NORMAL):calls.append(q.max_tokens);return LLMResponse(content='a guided answer')
    try:
        with patch.object(r.client,'complete',new=complete),patch.object(architect,'_recall_relevant_memories',new=AsyncMock(side_effect=lambda i,o:o)),patch.object(architect,'_store_action_episode',new=AsyncMock()):
            failed=await architect.handle_intent(IntentMessage(intent='design_feature',params={'feature':'perform the learned design operation'},target_agent_id=architect.id))
            assert failed is not None and not failed.success
            assert (await snapshot(r))==(2,0)
            decayed=await r.store.decay_stale_procedures()
            assert decayed==[] and (await snapshot(r))==(2,0)
            before=len(calls);result=await _handle_on_store(r.agent)
            assert result is not None and result.success
        assert calls[before:]==[2048]
        print('DECAY_CONTROL_A6',json.dumps({'after_failure':(2,0),'decay_receipt':decayed,'next_LLM_calls':calls[before:]}),flush=True)
    finally:
        r.bus.unsubscribe(r.target.id);await r.client.close();await r.store.stop()

@pytest.mark.asyncio
async def test_a_stale_failure_does_not_raise_a_restored_level_one_row(tmp_path):
    from tests.test_bf924_compilation_trust import _store_rig
    r=await _store_rig(tmp_path,0.5,3)
    held,released=asyncio.Event(),asyncio.Event();owner={'task':None};read=[]
    get0=r.store.get
    async def get(pid):
        p=await get0(pid)
        if asyncio.current_task() is owner['task'] and not held.is_set():
            read.append(p.compilation_level);held.set();await asyncio.wait_for(released.wait(),10)
        return p
    async def failed():
        owner['task']=asyncio.current_task()
        await r.agent._record_compilation_outcome(r.proc.id,False)
    task=None
    try:
        with patch.object(r.store,'get',new=get):
            task=asyncio.create_task(failed());await asyncio.wait_for(held.wait(),10)
            assert read==[3]
            archived=await get0(r.proc.id);archived.is_active=False;archived.is_archived=True;archived.compilation_level=1
            await r.store.save(archived)
            assert await r.store.restore_procedure(r.proc.id)
            restored=await snapshot(r);assert restored==(1,0)
            released.set();await asyncio.wait_for(task,10)
            after=await snapshot(r)
        print('STALE_FAILURE_RESTORE_A6',json.dumps({'failure_read':read,'after_restore':restored,'after_stale_failure':after,'injected_only_premise':'archived replacement saved while a failure held its earlier read'}),flush=True)
        assert after[0]<=restored[0], 'an unconditional stale demotion raised a restored Level 1 row to Level 2'
    finally:
        released.set()
        if task is not None and not task.done():task.cancel()
        if task is not None:await asyncio.gather(task,return_exceptions=True)
        await r.store.stop()