"""AD-1360 S2a (#1828): producers that store an episode inside or after a cognitive cycle record that cycle's id.

Each crossing case runs a real producer (a CognitiveAgent cycle, the Captain's 1:1 DM route, the shell session, the
Ward Room service, the proactive loop, the promoted-turn helpers, the MCP episode writer) into a real ChromaDB-backed
EpisodicMemory with a cycle-id registry bound, and reads the stored record back. security.memory.correlation_cutoff
stays at 0.0, so nothing here changes a recall.
"""

from __future__ import annotations

import functools
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from probos.cognitive import turn_promotion
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.episodic import EpisodicMemory
from probos.crew_profile import Rank
from probos.cycle_trace import (
    VERDICT_EMPTY,
    VERDICT_RESOLVED,
    CycleIdRegistry,
    bind_cycle,
    current_cycle_id,
    cycle_scope,
    result_cycle_id,
    unbind_cycle,
)
from probos.dm_reply import DmReply
from probos.experience.commands.session import SessionManager
from probos.types import IntentMessage, IntentResult
from probos.ward_room.service import WardRoomService
from probos.ward_room_pipeline import WardRoomPostPipeline
from probos.workforce import WorkItemStore
from tests import bf934_world
from tests.test_ad1156_plan_execute_mode import _chat_request, _route_runtime

_OBSERVATION = "The coolant loop on deck four reads within limits after the morning flush."
_REPLY = "Coolant pressure on deck four held steady through the evening watch handover."
_QUESTION = "What does the coolant loop read?"


class _Agent(CognitiveAgent):
    """A real CognitiveAgent whose model steps are stubbed (test_ad1360_s1_cycle_trace's pattern): the real perceive,
    lifecycle, cycle binding and AD-654a self-post run; ``answer`` is the whole reply."""

    agent_type = "science_officer"
    instructions = "AD-1360 S2a producer test agent."
    answer = _OBSERVATION

    async def _recall_relevant_memories(self, intent: Any, observation: dict) -> dict:
        return observation

    async def decide(self, observation: dict) -> dict:
        return {"llm_output": ""}

    async def act(self, decision: dict) -> dict:
        return {"success": True, "result": self.answer}

    async def report(self, result: dict) -> dict:
        return {"success": True, "result": self.answer}


def _records(memory: EpisodicMemory) -> dict[str, tuple[str, str]]:
    """Every stored episode, read back from ChromaDB: user_input -> (correlation_id, correlation_verdict)."""
    got = memory._collection.get(include=["metadatas", "documents"])
    episodes = [
        EpisodicMemory._metadata_to_episode(episode_id, document, metadata)
        for episode_id, document, metadata in zip(got["ids"], got["documents"], got["metadatas"])
    ]
    return {episode.user_input: (episode.correlation_id, episode.correlation_verdict) for episode in episodes}


def _only(records: dict[str, tuple[str, str]], prefix: str, author: str = "") -> tuple[str, str]:
    hits = [value for key, value in records.items() if key.startswith(prefix) and author in key]
    assert len(hits) == 1, (prefix, author, sorted(records))
    return hits[0]


def _ctx(**overrides: Any) -> DmReplyContext:
    return DmReplyContext(
        runtime=SimpleNamespace(), agent=None, agent_id="ad1360-agent", callsign=None, req_message="",
        reply=DmReply(body="noted"), has_image_attachment=False, per_attachment=[], sanity_gate=None, params={},
        message_text="", sampling_state=None, avatar_event_bus=None, **overrides,
    )


def _cycle_runtime(memory: EpisodicMemory, registry: CycleIdRegistry, **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(episodic_memory=memory, ontology=None, cycle_registry=registry, **extra)


def _recording(agent: CognitiveAgent, results: list[IntentResult]) -> Any:
    """The intent bus's ``send`` as a real cycle of ``agent``; each result is kept."""

    async def _send(intent: IntentMessage, **_kwargs: Any) -> IntentResult:
        results.append(await agent._run_cycle_bound_lifecycle(intent))
        return results[-1]

    return _send


async def _science_channel(w: Any) -> Any:
    """The channel ``_post_to_ward_room`` picks for a science officer: its department's, else the ship-wide one."""
    channels = await w.ws.list_channels()
    department = next((c for c in channels if c.channel_type == "department" and c.department == "science"), None)
    return department or next(c for c in channels if c.channel_type == "ship")


async def _thinker(w: Any, answer: str = _OBSERVATION) -> tuple[_Agent, list[IntentResult]]:
    """Kira as a real CognitiveAgent on the world's runtime: the real handle_intent runs, and its results are kept."""
    agent = _Agent(agent_id=w.ids["science_officer"], runtime=w.rt)
    agent.callsign = "Kira"
    agent.answer = answer
    await w.registry.register(agent)
    results: list[IntentResult] = []
    real = agent.handle_intent

    async def _handle(intent: IntentMessage) -> IntentResult | None:
        results.append(await real(intent))
        return results[-1]

    agent.handle_intent = _handle  # type: ignore[method-assign]
    return agent, results


@pytest.fixture
async def memory(tmp_path: Path) -> Any:
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"), relevance_threshold=0.0)
    await em.start()
    try:
        yield em
    finally:
        await em.stop()


@pytest.fixture
def registry(memory: EpisodicMemory) -> CycleIdRegistry:
    bound = CycleIdRegistry()
    memory.set_cycle_registry(bound)
    return bound


# -- N1 to N3: the scope, the result's id, the reply steps ------------------------------------------------------------


def test_cycle_scope_binds_an_id_keeps_the_outer_one_otherwise_and_always_puts_it_back() -> None:
    outer = bind_cycle("0123456789ab")
    try:
        with cycle_scope("feedfacecafe") as bound:
            assert bound == current_cycle_id() == "feedfacecafe"
            bind_cycle("aaaaaaaaaaaa")  # bound inside the scope and never reset: the scope's exit undoes it
        assert current_cycle_id() == "0123456789ab"
        for kept in ("", "   ", None, 7):
            with cycle_scope(kept) as bound:  # type: ignore[arg-type]
                assert bound == current_cycle_id() == "0123456789ab"
        with pytest.raises(RuntimeError, match="ad1360"):
            with cycle_scope("feedfacecafe"):
                raise RuntimeError("ad1360: the block failed")
        assert current_cycle_id() == "0123456789ab"
    finally:
        unbind_cycle(outer)
    assert current_cycle_id() == ""


def test_result_cycle_id_reads_only_a_non_empty_string() -> None:
    def result(metadata: dict) -> IntentResult:
        return IntentResult(intent_id="ad1360-intent", agent_id="ad1360-agent", success=True, metadata=metadata)

    assert result_cycle_id(result({"correlation_id": "abcdefabcdef"})) == "abcdefabcdef"
    for metadata in ({}, {"correlation_id": ""}, {"correlation_id": "   "}, {"correlation_id": 7}):
        assert result_cycle_id(result(metadata)) == ""
    for other in (None, MagicMock(), SimpleNamespace(metadata="abcdefabcdef")):
        assert result_cycle_id(other) == ""


async def test_the_reply_steps_run_with_the_cycle_bound_and_the_outer_id_comes_back() -> None:
    seen: list[str] = []

    async def probe() -> None:
        seen.append(current_cycle_id())

    async def fails() -> None:
        seen.append(current_cycle_id())
        raise RuntimeError("ad1360: a step failed")

    assert _ctx().cycle_id == ""  # every construction site that does not set it
    outer = bind_cycle("0123456789ab")
    try:
        await DmReplyPipeline(_ctx(cycle_id="feedfacecafe"))._run_steps((probe, fails, probe))
        assert current_cycle_id() == "0123456789ab"
        await DmReplyPipeline(_ctx())._run_steps((probe,))
    finally:
        unbind_cycle(outer)
    assert seen == ["feedfacecafe", "feedfacecafe", "feedfacecafe", "0123456789ab"]


# -- N4 to N8: crossing, from a real cycle (or inside one) to the stored record -------------------------------------


async def test_the_captains_dm_route_stores_the_turn_with_the_agents_cycle_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    from probos.routers.agents import agent_chat

    agent = _Agent()
    agent._runtime = _cycle_runtime(memory, registry)
    results: list[IntentResult] = []
    rt = _route_runtime(tmp_path, modes=False)
    rt.registry.get.return_value.sovereign_id = "ad1360-dm-agent"
    rt.episodic_memory = memory
    rt.intent_bus.send = AsyncMock(side_effect=_recording(agent, results))
    with patch("probos.routers.agents.is_crew_agent", return_value=True):
        await agent_chat("test-agent", _chat_request(_QUESTION), rt)
    chain_id = result_cycle_id(results[0])
    assert len(results) == 1 and registry.kind_of(chain_id) == "cognitive_cycle" and current_cycle_id() == ""
    assert _only(_records(memory), "[1:1 with") == (chain_id, VERDICT_RESOLVED)


async def test_a_shell_session_turn_stores_its_episode_with_the_agents_cycle_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    agent = _Agent()
    agent._runtime = _cycle_runtime(memory, registry)
    results: list[IntentResult] = []
    session = SessionManager()
    session.callsign, session.agent_id, session.agent_type, session.department = "Kira", agent.id, agent.agent_type, "science"
    session._sovereign_id = agent.id
    runtime = SimpleNamespace(
        intent_bus=SimpleNamespace(send=_recording(agent, results)), episodic_memory=memory, chat_thread_store=None,
    )
    await session.handle_message(_QUESTION, runtime, Console(file=io.StringIO()))
    chain_id = result_cycle_id(results[0])
    assert registry.kind_of(chain_id) == "cognitive_cycle"
    assert _only(_records(memory), "[1:1 with Kira]") == (chain_id, VERDICT_RESOLVED)


async def test_a_ward_room_reply_an_agent_posts_in_its_cycle_records_the_cycles_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    ws = WardRoomService(db_path=str(tmp_path / "wr.db"), episodic_memory=memory)
    await ws.start()
    try:
        channel = (await ws.list_channels())[0]
        thread = await ws.create_thread(
            channel.id, "captain", "Deck four", "What is on deck four today?", author_callsign="Captain",
        )
        await ws.create_post(thread.id, "ad1360-peer", _REPLY, author_callsign="Peer")  # outside any cycle
        agent = _Agent()
        agent.answer = _REPLY  # the peer's words, so AD-506b also writes the agent a peer-echo episode
        agent._runtime = _cycle_runtime(
            memory, registry, ward_room=ws,
            ward_room_post_pipeline=WardRoomPostPipeline(
                ward_room=ws, ward_room_router=None, proactive_loop=None, trust_network=None,
                callsign_registry=None, config=None,
            ),
        )
        intent = IntentMessage(
            intent="ward_room_notification", target_agent_id=agent.id,
            params={"thread_id": thread.id, "event_type": "ward_room_thread_created", "was_mentioned": True},
        )
        result = await agent._run_cycle_bound_lifecycle(intent)
    finally:
        await ws.stop()
    chain_id = result_cycle_id(result)
    records = _records(memory)
    assert registry.kind_of(chain_id) == "cognitive_cycle"
    assert _only(records, "[Ward Room reply]", "science_officer:") == (chain_id, VERDICT_RESOLVED)
    assert _only(records, "[Peer echo]") == (chain_id, VERDICT_RESOLVED)
    assert _only(records, "[Ward Room reply]", "Peer:") == ("", VERDICT_EMPTY)  # outside a cycle: S2b's
    assert _only(records, "[Ward Room]", "Captain:") == ("", VERDICT_EMPTY)


async def test_an_mcp_invoke_episode_stored_inside_a_cycle_records_that_cycles_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    from probos.runtime import ProbOSRuntime

    host = SimpleNamespace(episodic_memory=memory, identity_registry=None)
    token = bind_cycle(registry.issue(kind="cognitive_cycle"))
    try:
        chain_id = current_cycle_id()
        await ProbOSRuntime._store_mcp_invoke_episode(
            host, server_url="mcp.ad1360", tool="status", tier="open", success=True, agent_id="ad1360-agent",
        )
    finally:
        unbind_cycle(token)
    await ProbOSRuntime._store_mcp_invoke_episode(
        host, server_url="mcp.ad1360", tool="survey", tier="open", success=True, agent_id="ad1360-agent",
    )
    records = _records(memory)
    assert records["[mcp_invoke] status on mcp.ad1360"] == (chain_id, VERDICT_RESOLVED)
    assert records["[mcp_invoke] survey on mcp.ad1360"] == ("", VERDICT_EMPTY)  # outside a cycle: S2b's


# -- N9, N10: crossing, a real proactive think to the Ward Room's records --------------------------------------------


async def test_a_proactive_observation_thread_records_the_thinks_cycle_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bf934_world, "WardRoomService", functools.partial(WardRoomService, episodic_memory=memory))
    async with bf934_world.world(tmp_path) as w:
        w.rt.cycle_registry = registry
        channel = await _science_channel(w)
        await w.ws.create_thread(channel.id, "ad1360-peer", "[Observation] coolant", _OBSERVATION, author_callsign="Peer")
        agent, results = await _thinker(w)
        await bf934_world.think(w, agent)
    chain_id = result_cycle_id(results[0])
    records = _records(memory)
    assert len(results) == 1 and registry.kind_of(chain_id) == "cognitive_cycle"
    assert _only(records, "[Ward Room]", "Kira:") == (chain_id, VERDICT_RESOLVED)
    assert _only(records, "[Peer echo]") == (chain_id, VERDICT_RESOLVED)
    assert _only(records, "[Ward Room]", "Peer:") == ("", VERDICT_EMPTY)


async def test_a_reply_block_a_proactive_think_carries_out_records_the_thinks_cycle_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bf934_world, "WardRoomService", functools.partial(WardRoomService, episodic_memory=memory))
    async with bf934_world.world(tmp_path) as w:
        w.rt.cycle_registry = registry
        channel = await _science_channel(w)
        thread = await w.ws.create_thread(
            channel.id, "captain", "Deck four", "What is on deck four today?", author_callsign="Captain",
        )
        agent, results = await _thinker(w, f"[REPLY {thread.id}]\n{_REPLY}\n[/REPLY]")
        for _ in range(5):
            w.rt.trust_network.record_outcome(agent.id, success=True)
        assert Rank.from_trust(w.rt.trust_network.get_score(agent.id)) is not Rank.ENSIGN  # premise: replies allowed
        await bf934_world.think(w, agent)
    chain_id = result_cycle_id(results[0])
    records = _records(memory)
    assert registry.kind_of(chain_id) == "cognitive_cycle"
    assert _only(records, "[Ward Room reply]", "Kira:") == (chain_id, VERDICT_RESOLVED)
    assert _only(records, "[Ward Room]", "Captain:") == ("", VERDICT_EMPTY)


# -- N11, N12: a promoted run's work item, registered so its outcome episode resolves --------------------------------


async def test_a_promoted_work_item_is_registered_when_made_so_its_outcome_episode_resolves(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    items = WorkItemStore(db_path=":memory:")
    await items.start()
    try:
        runtime = SimpleNamespace(work_item_store=items, cycle_registry=registry, episodic_memory=memory, registry=None)
        item = await turn_promotion._create_promoted_work_item(
            runtime=runtime, agent_id="ad1360-agent", thread_id="ad1360-thread", request_text="Survey the coolant loop.",
        )
        assert item is not None and registry.kind_of(item.id) == "work_item"
        await turn_promotion._store_promoted_episode(
            runtime=runtime, agent_id="ad1360-agent", thread_id="ad1360-thread", work_item_id=item.id,
            request_text="Survey the coolant loop.", body=_OBSERVATION, complete=True, failed=False,
        )
    finally:
        await items.stop()
    assert _only(_records(memory), "[1:1 background task]") == (item.id, VERDICT_RESOLVED)
    stray = MagicMock()
    turn_promotion._register_promoted_work_item(SimpleNamespace(cycle_registry=stray), "ad1360-item")
    turn_promotion._register_promoted_work_item(SimpleNamespace(), "ad1360-item")
    turn_promotion._register_promoted_work_item(SimpleNamespace(cycle_registry=registry), "   ")
    stray.register.assert_not_called()
    assert not registry.resolves("ad1360-item") and not registry.resolves("   ")


async def test_a_resumed_work_item_is_registered_again_after_a_restart(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    # ``registry`` is the one a restart left: it never saw the item promoted before it.
    item = SimpleNamespace(id="ad1360workitem", assigned_to="", metadata={"thread_id": "ad1360-thread"})
    runtime = SimpleNamespace(cycle_registry=registry, episodic_memory=memory, work_item_store=None, registry=None)
    assert not registry.resolves(item.id)
    await turn_promotion.resume_promoted_turn(runtime, item, "ad1360-request")
    assert registry.kind_of(item.id) == "work_item"
    await turn_promotion._store_promoted_episode(
        runtime=runtime, agent_id="ad1360-agent", thread_id="ad1360-thread", work_item_id=item.id,
        request_text="Survey the coolant loop.", body=_OBSERVATION, complete=True, failed=False,
    )
    assert _only(_records(memory), "[1:1 background task]") == (item.id, VERDICT_RESOLVED)
