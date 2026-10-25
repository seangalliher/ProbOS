import os
import sys
from pathlib import Path
TREE=Path(os.environ.get('BF924_SOURCE_TREE',r'D:\ProbOS-worktrees\bf924-review1'))
sys.path[:0]=[str(TREE/'src'),str(TREE)]
import probos
print('SOURCE',probos.__file__,flush=True)
assert Path(probos.__file__).resolve()==(TREE/'src/probos/__init__.py').resolve()
import json
from unittest.mock import AsyncMock,patch
import pytest
from probos.cognitive.engineering_officer import EngineeringAgent
from probos.types import AgentState,IntentMessage,LLMResponse,Priority
from tests.test_bf924_compilation_trust import trust_network_at
from test_result_paths import Case,make_rig

@pytest.mark.asyncio
async def test_the_same_procedure_requires_a_real_level_3_validation_request(tmp_path):
    r=await make_rig(tmp_path,Case('validation-control',1,level=3))
    a=EngineeringAgent(llm_client=r.client,runtime=r.runtime)
    a.state=AgentState.ACTIVE
    r.runtime.trust_network=trust_network_at(a.id,0.5)
    calls=[]
    async def complete(q,*,priority=Priority.NORMAL):
        calls.append(q.max_tokens)
        return LLMResponse(content='YES')
    try:
        assert r.proc.postconditions and r.proc.steps[0].expected_output
        with patch.object(r.client,'complete',new=complete),patch.object(a,'_recall_relevant_memories',new=AsyncMock(side_effect=lambda i,o:o)),patch.object(a,'_store_action_episode',new=AsyncMock()):
            result=await a.handle_intent(IntentMessage(intent='direct_message',params={'message':'perform the learned operation'},target_agent_id=a.id))
        print('VALIDATION_OBLIGATION_CONTROL',json.dumps({'success':result.success,'real_validation_token_limits':calls}),flush=True)
        assert result.success is True and calls==[100]
    finally:
        r.bus.unsubscribe(r.target.id)
        await r.client.close()
        await r.store.stop()