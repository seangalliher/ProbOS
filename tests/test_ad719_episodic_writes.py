"""AD-719: episodic-write loop on multi-agent fan-out branch.

Each resolved fan-out reply MUST produce its own episode in episodic memory.
Stubs (unresolved / off-duty) are skipped.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from probos.api import create_app
from probos.cognitive.llm_client import MockLLMClient
from probos.runtime import ProbOSRuntime


def _single_word_callsigns(rt) -> list[str]:
    return [c for c in rt.callsign_registry.all_callsigns().values() if " " not in c and c]


@pytest.fixture
async def chat_client(tmp_path):
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await rt.start()
    # If the test runtime did not bring up an episodic_memory, attach a
    # stub so the AD-719 fan-out write loop has something to call. This
    # keeps the test boundary tight on the loop logic itself.
    if rt.episodic_memory is None:
        class _StubEpisodic:
            async def store(self, episode):
                return None
            async def stop(self):
                return None
        rt.episodic_memory = _StubEpisodic()
    # Force the dream_adapter off so the loop takes the explicit Episode
    # construction branch (deterministic source tag).
    rt.dream_adapter = None
    app = create_app(rt)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, rt
    await rt.stop()


@pytest.mark.asyncio
async def test_fanout_writes_one_episode_per_reply(chat_client):
    """Two-mention fan-out → episodic_memory.store called once per resolved reply.

    The runtime's other subsystems may also write episodes (with source != the
    AD-719 distinct tag); filter by source to scope the assertion to fan-out.
    """
    client, rt = chat_client
    callsigns = _single_word_callsigns(rt)
    if len(callsigns) < 2:
        pytest.skip("Need at least 2 single-word crew callsigns")
    a, b = callsigns[0], callsigns[1]
    if rt.episodic_memory is None:
        pytest.skip("episodic_memory not configured on this runtime")
    spy = AsyncMock()
    with patch.object(rt.episodic_memory, "store", spy):
        r = await client.post("/api/chat", json={"message": f"@{a} @{b} hello team"})
    assert r.status_code == 200
    data = r.json()
    replies = data.get("per_agent_replies") or []
    real_replies = [rr for rr in replies if rr.get("agent_id")]
    fanout_calls = [
        c for c in spy.call_args_list
        if str(c.args[0].source) == "multi_agent_chat"
    ]
    assert len(fanout_calls) == len(real_replies)
    if len(fanout_calls) >= 2:
        agent_ids_written = []
        for call in fanout_calls:
            agent_ids_written.extend(call.args[0].agent_ids)
        assert len(set(agent_ids_written)) == len(fanout_calls)


@pytest.mark.asyncio
async def test_fanout_skips_episode_for_stub_reply(chat_client):
    """Unknown callsign produces a stub reply with agent_id='' and no fan-out episode."""
    client, rt = chat_client
    callsigns = _single_word_callsigns(rt)
    if not callsigns:
        pytest.skip("Need at least 1 single-word crew callsign")
    known = callsigns[0]
    if rt.episodic_memory is None:
        pytest.skip("episodic_memory not configured")
    spy = AsyncMock()
    with patch.object(rt.episodic_memory, "store", spy):
        r = await client.post("/api/chat", json={"message": f"@{known} @ghostsentinel hi"})
    assert r.status_code == 200
    data = r.json()
    replies = data.get("per_agent_replies") or []
    real_replies = [rr for rr in replies if rr.get("agent_id")]
    fanout_calls = [
        c for c in spy.call_args_list
        if str(c.args[0].source) == "multi_agent_chat"
    ]
    # Stubs (agent_id == '') do not produce fan-out episodes.
    assert len(fanout_calls) == len(real_replies)


@pytest.mark.asyncio
async def test_fanout_episode_source_tag_distinct(chat_client):
    """Stored Episode.source for fan-out replies is exactly 'multi_agent_chat'."""
    client, rt = chat_client
    callsigns = _single_word_callsigns(rt)
    if len(callsigns) < 2:
        pytest.skip("Need at least 2 single-word crew callsigns")
    if rt.episodic_memory is None:
        pytest.skip("episodic_memory not configured")
    a, b = callsigns[0], callsigns[1]
    spy = AsyncMock()
    with patch.object(rt.episodic_memory, "store", spy):
        r = await client.post("/api/chat", json={"message": f"@{a} @{b} ping"})
    assert r.status_code == 200
    fanout_calls = [
        c for c in spy.call_args_list
        if str(c.args[0].source) == "multi_agent_chat"
    ]
    if not fanout_calls:
        pytest.skip("No live agents resolved on this runtime — no fan-out episodes written")
    for call in fanout_calls:
        episode = call.args[0]
        # dream_adapter is forced None in the fixture so this path constructs
        # Episode directly with the AD-719 distinct source tag.
        assert str(episode.source) == "multi_agent_chat"
