import pytest
from probos.ward_room_pipeline import AgentResponse, merge_agent_responses

@pytest.mark.asyncio
async def test_merge_agent_responses_deduplication():
    responses = [
        AgentResponse("Here's the summary.", "ArchitectAgent", "summarize"),
        AgentResponse("Here's the summary.", "OutlookAgent", "summarize"),
        AgentResponse("Different insight.", "SkillAgent", "analyze"),
    ]
    merged = await merge_agent_responses(responses)
    assert "ArchitectAgent" in merged
    assert "SkillAgent" in merged
    assert merged.count("Here's the summary.") == 1
    assert merged.count("Different insight.") == 1

@pytest.mark.asyncio
async def test_merge_agent_responses_cites_agents():
    responses = [
        AgentResponse("Insight A.", "A", "intent1"),
        AgentResponse("Insight B.", "B", "intent2"),
    ]
    merged = await merge_agent_responses(responses)
    assert "[A] Insight A." in merged
    assert "[B] Insight B." in merged
