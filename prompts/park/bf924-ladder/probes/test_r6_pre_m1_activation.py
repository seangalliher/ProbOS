import os,sys
from pathlib import Path
TREE=Path(os.environ['PYTHONPATH'].split(';')[0]).parent
sys.path[:0]=[str(TREE/'src'),str(TREE)]
import probos
print('SOURCE',probos.__file__,flush=True)
assert Path(probos.__file__).resolve()==(TREE/'src/probos/__init__.py').resolve()
import importlib.util,json
from unittest.mock import AsyncMock,patch
import pytest
# Only the test fixture definitions are loaded externally; all probos classes are the guarded tree's.
name='tests.test_bf924_compilation_trust'
spec=importlib.util.spec_from_file_location(name,TREE/'tests'/'test_bf924_compilation_trust.py')
module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
from probos.cognitive.cognitive_agent import _DECISION_CACHES
from probos.cognitive.engineering_officer import EngineeringAgent
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.consensus.trust import TrustNetwork
from probos.types import AgentState,IntentMessage,LLMResponse,Priority

@pytest.mark.asyncio
async def test_the_pre_m1_serial_path_never_activates_validated_or_autonomous_replay(tmp_path):
    _DECISION_CACHES.clear()
    r=await module._store_rig(tmp_path,0.5,2)
    client=OpenAICompatibleClient(base_url='http://127.0.0.1:9/v1')
    agent=EngineeringAgent(llm_client=client,runtime=r.runtime);agent.state=AgentState.ACTIVE
    net=TrustNetwork();net.create_with_prior(agent.id,alpha=5,beta=5);r.runtime.trust_network=net
    calls=[];rows=[]
    async def complete(q,*,priority=Priority.NORMAL):calls.append(q.max_tokens);return LLMResponse(content='the guided answer')
    try:
        with patch.object(client,'complete',new=complete),patch.object(agent,'_recall_relevant_memories',new=AsyncMock(side_effect=lambda i,o:o)),patch.object(agent,'_store_action_episode',new=AsyncMock()):
            for _ in range(6):
                result=await agent.handle_intent(IntentMessage(intent='direct_message',params={'message':'perform the learned operation'},target_agent_id=agent.id))
                assert result is not None and result.success
                cursor=await r.store._db.execute("SELECT compilation_level,COALESCE(json_extract(content_snapshot,'$.compilation_level'),1),consecutive_successes FROM procedure_records WHERE id=?",(r.proc.id,))
                rows.append(tuple(await cursor.fetchone()))
        print('PRE_M1_ACTIVATION_CONTROL',json.dumps({'rows':rows,'LLM_limits':calls}),flush=True)
        assert rows==[(2,2,1),(2,2,2),(3,2,0),(3,2,1),(3,2,2),(3,2,0)]
        assert calls==[2048]*6
    finally:await client.close();await r.store.stop();_DECISION_CACHES.clear()