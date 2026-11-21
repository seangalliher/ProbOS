"""AD-1360 S2b (#1828): producers outside any cognitive cycle record an id their entry point issued.

Each case runs a real producer (the HXI Ward Room and recreation routes on a real WardRoomService, the Captain's 1:1 DM
route, the quartermaster, the ground-truth writer, the voice-approval route, the natural-language pipeline's episode
step, the FeedbackEngine, the camera route and the vision consumer, the device episode writers, a dispatched work item's
agentic run) into a real ChromaDB-backed EpisodicMemory with a cycle-id registry bound, and reads the stored record back.
security.memory.correlation_cutoff stays at 0.0, so nothing here changes a recall.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.agents.quartermaster import QuartermasterAgent
from probos.api_models import CreatePostRequest, CreateThreadRequest, SetVoiceProfileRequest
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.feedback import FeedbackEngine
from probos.cognitive.ground_truth import GroundTruthResult, VerificationEpisodeWriter
from probos.cycle_trace import (
    VERDICT_EMPTY,
    VERDICT_RESOLVED,
    CycleIdRegistry,
    bind_cycle,
    current_cycle_id,
    entry_scope,
    issue_entry_id,
    unbind_cycle,
)
from probos.dream_adapter import DreamAdapter
from probos.perception.consumer import VisionConsumer
from probos.routers.perception import _reset_state_for_tests, _write_anchor_episode
from probos.substrate.device_service import DeviceNodeService
from probos.types import Episode, IntentMessage, IntentResult, TaskDAG, TaskNode
from probos.ward_room.service import WardRoomService
from tests.test_ad1156_plan_execute_mode import _chat_request, _route_runtime

_REPLY = "Coolant pressure on deck four held steady through the evening watch handover."
_QUESTION = "What does the coolant loop read?"


class _Agent(CognitiveAgent):
    agent_type = "science_officer"
    instructions = "AD-1360 S2b entry-chain test agent."


def _episodes(memory: EpisodicMemory) -> list[Episode]:
    got = memory._collection.get(include=["metadatas", "documents"])
    return [
        EpisodicMemory._metadata_to_episode(episode_id, document, metadata)
        for episode_id, document, metadata in zip(got["ids"], got["documents"], got["metadatas"])
    ]


def _one(memory: EpisodicMemory, needle: str, agent: str = "") -> tuple[str, str]:
    """(correlation_id, correlation_verdict) of the one stored episode whose user_input or reflection holds needle."""
    episodes = _episodes(memory)
    hits = [
        ep for ep in episodes
        if (needle in ep.user_input or needle in (ep.reflection or "")) and (not agent or agent in ep.agent_ids)
    ]
    assert len(hits) == 1, (needle, agent, [(ep.user_input, ep.reflection) for ep in episodes])
    return hits[0].correlation_id, hits[0].correlation_verdict


def _chain(registry: CycleIdRegistry, record: tuple[str, str], kind: str) -> None:
    """The record resolved against an id the registry issued under ``kind``."""
    chain_id, verdict = record
    assert verdict == VERDICT_RESOLVED and registry.kind_of(chain_id) == kind, (record, registry.kind_of(chain_id))


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


def _quartermaster(memory: EpisodicMemory, registry: CycleIdRegistry | None, agent_id: str) -> QuartermasterAgent:
    return QuartermasterAgent(
        reconciler=MagicMock(), work_item_store=SimpleNamespace(list_work_items=AsyncMock(return_value=[])),
        work_item_router=MagicMock(), episodic=memory, agent_id=agent_id,
        runtime=SimpleNamespace(cycle_registry=registry) if registry is not None else None,
    )


def _nl_host(memory: EpisodicMemory, registry: CycleIdRegistry, adapter: Any) -> SimpleNamespace:
    results = {"t1": {"results": [{"agent_id": "ad1360-nl-agent"}]}}
    return SimpleNamespace(
        dag_executor=SimpleNamespace(execute=AsyncMock(return_value={"results": results})),
        working_memory=MagicMock(), episodic_memory=memory, dream_adapter=adapter, _last_shapley_values={},
        _knowledge_store=None, workflow_cache=None, cycle_registry=registry, _record_error=MagicMock(),
    )


# -- E1: the helpers ----------------------------------------------------------------------------------------------------


def test_an_entry_point_issues_its_own_id_unless_a_cycle_is_bound() -> None:
    registry = CycleIdRegistry()
    issued = issue_entry_id(registry, kind="hxi_post")
    assert registry.kind_of(issued) == "hxi_post" and current_cycle_id() == ""
    for stray in (None, MagicMock(), SimpleNamespace()):
        assert issue_entry_id(stray, kind="hxi_post") == ""
    for blank in ("", "   ", None):
        with pytest.raises(ValueError):
            issue_entry_id(None, kind=blank)  # type: ignore[arg-type]
    outer = bind_cycle("0123456789ab")
    try:
        held = len(registry)
        assert issue_entry_id(registry, kind="hxi_post") == "0123456789ab" and len(registry) == held
        with entry_scope(registry, kind="nl_request") as bound:
            assert bound == current_cycle_id() == "0123456789ab"
        assert current_cycle_id() == "0123456789ab"
    finally:
        unbind_cycle(outer)
    with entry_scope(registry, kind="nl_request") as bound:
        assert bound == current_cycle_id() and registry.kind_of(bound) == "nl_request"
    with pytest.raises(RuntimeError, match="ad1360"):
        with entry_scope(registry, kind="nl_request"):
            raise RuntimeError("ad1360: the block failed")
    with entry_scope(MagicMock(), kind="nl_request") as bound:
        assert bound == current_cycle_id() == ""
    assert current_cycle_id() == ""


# -- E2 to E7: entry points that M1 wires ---------------------------------------------------------------------------------


async def test_the_captains_ward_room_posts_from_the_hxi_record_the_requests_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    from probos.routers.recreation import make_move
    from probos.routers.wardroom import wardroom_create_post, wardroom_create_thread

    ws = WardRoomService(db_path=str(tmp_path / "wr.db"), episodic_memory=memory)
    await ws.start()
    try:
        channel = (await ws.list_channels())[0]
        runtime = SimpleNamespace(ward_room=ws, cycle_registry=registry, registry=MagicMock(), callsign_registry=None)
        thread = await wardroom_create_thread(channel.id, CreateThreadRequest(
            author_id="captain", title="Deck four survey", body="What is on deck four today?", author_callsign="Captain",
        ), runtime)
        await wardroom_create_post(
            thread["id"], CreatePostRequest(author_id="captain", body=_REPLY, author_callsign="Captain"), runtime,
        )
        game = MagicMock()
        game.make_move = AsyncMock(return_value={
            "thread_id": thread["id"], "state": {"status": "in_progress", "current_player": "Kira"}, "board_text": "X|O|X",
        })
        runtime.recreation_service = game
        await make_move({"game_id": "ad1360-game", "position": "5"}, runtime)
    finally:
        await ws.stop()
    _chain(registry, _one(memory, "Captain posted to"), "hxi_post")
    _chain(registry, _one(memory, _REPLY), "hxi_post")
    _chain(registry, _one(memory, "Captain played position 5."), "hxi_post")
    assert current_cycle_id() == ""


async def test_a_dm_whose_reply_carries_no_cycle_id_stores_the_routes_own_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    from probos.routers.agents import agent_chat

    rt = _route_runtime(tmp_path, modes=False)
    rt.registry.get.return_value.sovereign_id = "ad1360-dm-agent"
    rt.episodic_memory = memory
    rt.cycle_registry = registry
    rt.intent_bus.send = AsyncMock(return_value=IntentResult(
        intent_id="ad1360-intent", agent_id="ad1360-dm-agent", success=True, result=_REPLY,
    ))
    with patch("probos.routers.agents.is_crew_agent", return_value=True):
        await agent_chat("test-agent", _chat_request(_QUESTION), rt)
    _chain(registry, _one(memory, "[1:1 with"), "hxi_dm")


async def test_a_quartermaster_sweep_records_its_own_id(memory: EpisodicMemory, registry: CycleIdRegistry) -> None:
    await _quartermaster(memory, registry, "ad1360-quartermaster").reconcile()
    await _quartermaster(memory, None, "ad1360-bare-quartermaster").reconcile()
    _chain(registry, _one(memory, "quartermaster sweep", "ad1360-quartermaster"), "quartermaster_sweep")
    assert _one(memory, "quartermaster sweep", "ad1360-bare-quartermaster") == ("", VERDICT_EMPTY)


async def test_a_reactive_reclaim_records_its_own_id(memory: EpisodicMemory, registry: CycleIdRegistry) -> None:
    await _quartermaster(memory, registry, "ad1360-quartermaster").reconcile_for_agent("ad1360-departed")
    _chain(registry, _one(memory, "reactive reclaim for ad1360-departed"), "quartermaster_reclaim")


async def test_a_ground_truth_verification_records_its_own_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    writer = VerificationEpisodeWriter(runtime=SimpleNamespace(episodic_memory=memory, cycle_registry=registry))
    assert await writer.write(GroundTruthResult(
        verified=False, score=0.0, agent_id="ad1360-agent", claimed_summary="Surveyed the coolant loop on deck four.",
    ))
    _chain(registry, _one(memory, "Surveyed the coolant loop"), "ground_truth_verification")


async def test_the_captains_voice_approval_records_the_requests_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    from probos.routers.agents import set_agent_voice_profile

    agent = SimpleNamespace(
        id="ad1360-voice-agent", agent_type="science_officer", pool="science", sovereign_id="ad1360-voice-agent",
    )
    runtime = SimpleNamespace(
        registry=SimpleNamespace(get=lambda _agent_id: agent), episodic_memory=memory, cycle_registry=registry,
    )
    await set_agent_voice_profile(
        "ad1360-voice-agent", SetVoiceProfileRequest(proposal_rationale="A calmer voice for the night watch."), runtime,
    )
    _chain(registry, _one(memory, "[voice approval]"), "hxi_request")


# -- E8 to E13: entry points that M2 wires --------------------------------------------------------------------------------


async def test_the_natural_language_pipeline_stores_its_episode_with_the_requests_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    from probos.runtime import ProbOSRuntime

    adapter = DreamAdapter.__new__(DreamAdapter)
    adapter._trust_network, adapter._last_shapley_values, adapter._identity_registry = None, {}, None
    for host, text in (
        (_nl_host(memory, registry, adapter), "Survey the coolant loop on deck four"),
        (_nl_host(memory, registry, None), "Read the reactor log for the night watch"),
    ):
        dag = TaskDAG(nodes=[TaskNode(id="t1", intent="survey", status="completed")])
        await ProbOSRuntime._execute_dag(host, dag, text, time.monotonic())
        _chain(registry, _one(memory, text), "nl_request")
    assert current_cycle_id() == ""


async def test_captain_feedback_on_a_plan_records_its_own_id(memory: EpisodicMemory, registry: CycleIdRegistry) -> None:
    engine = FeedbackEngine(
        trust_network=MagicMock(), hebbian_router=MagicMock(), episodic_memory=memory, cycle_registry=registry,
    )
    assert (await engine.apply_execution_feedback(TaskDAG(nodes=[]), True, "Survey the coolant loop")).episode_stored
    bare = FeedbackEngine(trust_network=MagicMock(), hebbian_router=MagicMock(), episodic_memory=memory)
    assert (await bare.apply_execution_feedback(TaskDAG(nodes=[]), False, "Read the reactor log")).episode_stored
    _chain(registry, _one(memory, "Survey the coolant loop"), "captain_feedback")
    assert _one(memory, "Read the reactor log") == ("", VERDICT_EMPTY)


async def test_a_camera_frame_and_its_vision_description_record_their_own_ids(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    _reset_state_for_tests()
    try:
        await _write_anchor_episode(
            SimpleNamespace(episodic_memory=memory, cycle_registry=registry), "ad1360-session", "a" * 64, time.time(),
        )
    finally:
        _reset_state_for_tests()
    consumer = VisionConsumer.__new__(VisionConsumer)
    consumer._runtime = SimpleNamespace(episodic_memory=memory, cycle_registry=registry)
    await consumer._anchor_episode(
        "b" * 64, "the coolant gauge reads nominal", 0.9, "ad1360-session", agent_ids=["ad1360-observer"],
    )
    _chain(registry, _one(memory, "Camera stream began"), "hxi_request")
    _chain(registry, _one(memory, "Vision observation: the coolant gauge"), "vision_observation")


async def test_a_device_episode_records_the_cycle_that_actuated_it_and_none_outside_one(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    from probos.runtime import ProbOSRuntime

    service = DeviceNodeService(registry=MagicMock(), adapter=MagicMock(), episodic_provider=lambda: memory)
    token = bind_cycle(registry.issue(kind="cognitive_cycle"))
    try:
        chain_id = current_cycle_id()
        await service._store_episode(
            IntentMessage(intent="device.notify"), "dev-alpha", authorized=True, success=True, reason="",
        )
        await ProbOSRuntime._store_device_consensus_episode(
            SimpleNamespace(episodic_memory=memory), device_id="dev-bravo", intent_name="device.location",
            authorized=True, committed=True, reason="",
        )
    finally:
        unbind_cycle(token)
    await service._store_episode(
        IntentMessage(intent="device.notify"), "dev-charlie", authorized=False, success=False, reason="unpaired",
    )
    assert _one(memory, "-> dev-alpha") == (chain_id, VERDICT_RESOLVED)
    assert _one(memory, "-> dev-bravo") == (chain_id, VERDICT_RESOLVED)
    assert _one(memory, "-> dev-charlie") == ("", VERDICT_EMPTY)


async def test_a_dispatched_work_items_agentic_run_records_the_work_items_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    from probos.runtime import ProbOSRuntime

    host = SimpleNamespace(episodic_memory=memory, identity_registry=None)
    seen: list[str] = []

    def _run_for(tool: str) -> Any:
        async def _run(**_kwargs: Any) -> str:
            seen.append(current_cycle_id())
            await ProbOSRuntime._store_mcp_invoke_episode(
                host, server_url="mcp.ad1360", tool=tool, tier="open", success=True, agent_id=f"ad1360-{tool}",
            )
            return "Acknowledged; surveying the coolant loop."
        return _run

    for runtime, tool in (
        (SimpleNamespace(cycle_registry=registry, chat_thread_store=None, work_item_store=None), "status"),
        (SimpleNamespace(chat_thread_store=None, work_item_store=None), "survey"),
    ):
        agent = _Agent()
        agent._runtime = runtime
        agent._run_agentic_dispatch = _run_for(tool)  # type: ignore[method-assign]
        result = await agent._handle_work_item_dispatch(IntentMessage(
            intent="work_item_dispatched", params={"work_item_id": f"ad1360{tool}item", "title": "Survey"},
            target_agent_id=agent.id,
        ))
        assert result.success and current_cycle_id() == ""
    assert seen == ["ad1360statusitem", ""]
    assert registry.kind_of("ad1360statusitem") == "work_item" and not registry.resolves("ad1360surveyitem")
    assert _one(memory, "[mcp_invoke] status on mcp.ad1360") == ("ad1360statusitem", VERDICT_RESOLVED)
    assert _one(memory, "[mcp_invoke] survey on mcp.ad1360") == ("", VERDICT_EMPTY)


def test_startup_hands_the_feedback_engine_the_runtimes_registry() -> None:
    """A structural pin: the startup branch runs inside the boot sequence, which no focused test reaches."""
    path = Path(__file__).resolve().parents[1] / "src" / "probos" / "startup" / "cognitive_services.py"
    calls = [
        node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "FeedbackEngine"
    ]
    assert len(calls) == 1
    assert {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}.get("cycle_registry") == "cycle_registry"
