"""AD-1357 (#1749): what a crew chat reply was given, recorded beside the reply.

A crew ``direct_message`` reply carries a context manifest under its stored
``metadata["context_manifest"]``: the prompt's sections by name, size and whether
the budget kept them; what recall fed (the agent's own episode ids and source
tags, the band); which lookups ran and what they returned (Ship's Records paths,
the transcript room id, counts); and the journal row the turn wrote.

Real fixtures where the chain matters: a real ``CognitiveAgent`` through
``_recall_relevant_memories`` and ``_decide_via_llm``, a real ``OracleService`` over
a real ``RecordsStore`` on ``tmp_path``, a real ``CognitiveJournal``, a real
``ChatThreadStore`` and the real AD-914 group fan-out over a real ``IntentBus``.
The runtime is a ``SimpleNamespace`` with a real ``SystemConfig``: a ``MagicMock``
config would make ``dm_agentic.enabled`` truthy and run the AgenticLoop. Names
the change adds are imported inside the tests, so the file collects on the base.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.attention import estimate_tokens
from probos.cognitive.cognitive_agent import CognitiveAgent, _build_result_metadata
from probos.cognitive.episodic import RecallConfidence
from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.oracle_service import OracleService, make_reader_identity_resolver
from probos.config import RecordsConfig, SystemConfig
from probos.knowledge.records_store import RecordsStore
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.agents import _build_reply_metadata
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import Episode, IntentMessage, IntentResult, LLMResponse
from tests.fixtures.ad1028_golden._capture_golden import dm_observation, make_dm_agent

_UNTIL_M2 = pytest.mark.xfail(strict=True, reason="AD-1357 M2: a DM reply carries no context manifest")
_UNTIL_M3 = pytest.mark.xfail(strict=True, reason="AD-1357 M3: recall and the lookups are not recorded")
_UNTIL_M4 = pytest.mark.xfail(strict=True, reason="AD-1357 M4: an agentic DM turn writes no journal row")

AGENT_ID = "ad1357-ezri"
GAME_RECORD = "recreation/games/tictactoe/game-58042e2b4637.md"
GAME_QUERY = "tictactoe Captain Ezri"
FROZEN_TEMPORAL = "Current time: 2026-11-05 12:00:00 UTC (Thursday)"
NO_LOOKUPS = {
    "cross_agent_recall": {"ran": False},
    "transcript_grounding": {"ran": False},
    "oracle": {"ran": False},
}


async def _empty_sensorium(path: object, observation: dict) -> dict[str, str]:
    del path, observation
    return {}


class _OneReply:
    """An ``llm_client`` that answers every request with one reply and keeps the requests."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            content=self.content, model="scripted", tier="standard",
            tokens_used=10, prompt_tokens=5, completion_tokens=5,
        )


class _Episodic:
    """What ``_recall_relevant_memories`` reads of episodic memory (the BASIC path: no ``recall_weighted``)."""

    def __init__(self, episodes: list[Episode], confidence: RecallConfidence | None = None) -> None:
        self._episodes = episodes
        self._confidence = confidence or RecallConfidence(
            band="strong", best_similarity=0.9, candidate_count=len(episodes), query="",
        )

    async def count_for_agent(self, _mem_id: str) -> int:
        return len(self._episodes)

    async def recall_for_agent(self, _mem_id: str, _query: str, k: int = 3) -> list[Episode]:
        return list(self._episodes)

    async def recent_for_agent(self, _mem_id: str, k: int = 3) -> list[Episode]:
        return []

    async def recall_for_agent_with_confidence(self, _mem_id: str, _query: str, k: int = 5) -> Any:
        return [], self._confidence


class _Recreation:
    """``RecreationService``'s three reads for the AD-572 active-game block."""

    def get_game_by_player(self, callsign: str) -> dict[str, Any] | None:
        if callsign != "Ezri":
            return None
        return {
            "game_id": "game-1", "game_type": "tictactoe", "challenger": "Captain",
            "opponent": "Ezri", "state": {"current_player": "Captain"}, "moves_count": 0,
        }

    def render_board(self, _game_id: str) -> str:
        return " | | \n-+-+-\n | | \n-+-+-\n | | "

    def get_valid_moves(self, _game_id: str) -> list[int]:
        return []


def _config(**memory: Any) -> SystemConfig:
    config = SystemConfig()
    for name, value in memory.items():
        setattr(config.memory, name, value)
    return config


def _runtime(**attributes: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "config": SystemConfig(),
        "cognitive_journal": None,
        "episodic_memory": None,
        "ontology": None,
        "trust_network": None,
        "recreation_service": None,
    }
    base.update(attributes)
    return SimpleNamespace(**base)


def _agent(runtime: Any, llm: Any, *, agent_type: str = "scout") -> CognitiveAgent:
    """A real agent (test_ad1038's construction); clock and sensorium pinned as AD-1028's golden pins them."""
    agent = CognitiveAgent(agent_id=AGENT_ID, instructions="You are Ezri.")
    agent.agent_type = agent_type
    agent.callsign = "Ezri"
    agent._runtime = runtime
    agent._llm_client = llm
    agent._build_temporal_context = lambda: FROZEN_TEMPORAL  # type: ignore[method-assign]
    agent._dispatch_sensorium_async = _empty_sensorium  # type: ignore[method-assign]
    return agent


def _observation(params: dict[str, Any], *, intent_id: str) -> dict[str, Any]:
    return {"intent": "direct_message", "intent_id": intent_id, "params": params}


async def _turn(agent: CognitiveAgent, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recall, then the decision, in ``_run_cognitive_lifecycle``'s order; returns (observation, decision)."""
    intent = IntentMessage(intent="direct_message", params=params)
    observation = await agent._recall_relevant_memories(intent, _observation(params, intent_id=intent.id))
    decision = await agent._decide_via_llm(observation)
    return observation, decision


def _manifest_of(observation: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """The manifest as ``IntentResult.metadata`` carries it, through the production construction."""
    return _build_result_metadata({}, decision, observation)["context_manifest"]


def _names(manifest: dict[str, Any]) -> list[str]:
    return [section["name"] for section in manifest["sections"]]


def _in_order(wanted: list[str], names: list[str]) -> bool:
    remaining = iter(names)
    return all(name in remaining for name in wanted)


def _seq_clock():
    count = {"t": 0}

    def _clock() -> float:
        count["t"] += 1
        return float(count["t"])

    return _clock


async def _records_oracle(tmp_path: Path) -> OracleService:
    """A real ``OracleService`` over a real ``RecordsStore`` holding one AD-526a-shaped game record.

    Each query word appears as a whole word, so the record matches under both the
    substring scorer on the base and BF-952's word-boundary scorer.
    """
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    await store.initialize()
    await store.write_entry(
        "captain", GAME_RECORD,
        "# tictactoe\n\ntictactoe game between Captain and Ezri. Result: Captain wins.\n",
        "AD-1357 fixture", classification="ship",
    )
    oracle = OracleService(records_store=store)
    oracle.attach_reader_identity_resolver(
        make_reader_identity_resolver(
            registry=SimpleNamespace(
                get=lambda aid: SimpleNamespace(agent_type="scout", callsign="Ezri", sovereign_id="")
                if aid == AGENT_ID else None,
                all=lambda: [],
            ),
            ontology=SimpleNamespace(get_agent_department=lambda _t: "science"),
        )
    )
    return oracle


def _thread_store(tmp_path: Path) -> ChatThreadStore:
    return ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())


# ── T1: the crossing ─────────────────────────────────────────────────


@_UNTIL_M3
async def test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three(tmp_path: Path) -> None:
    """#1749 acceptance 1 and 2, across every seam: recall, the prompt, the result's metadata, the reply's
    metadata, the stored row."""
    episodes = [
        Episode(id="ep-own-direct-0001", timestamp=1.0, user_input="The Captain and I ran the warp drill.", source="direct"),
        Episode(id="ep-own-reflection-02", timestamp=2.0, user_input="I keep thinking about our games.", source="reflection"),
    ]
    weak = RecallConfidence(band="weak", best_similarity=0.513, candidate_count=2, query=GAME_QUERY)
    runtime = _runtime(
        config=_config(recall_confidence_gating_enabled=True),
        episodic_memory=_Episodic(episodes, weak),
        trust_network=SimpleNamespace(get_score=lambda _agent_id: 0.95),  # SENIOR: the ORACLE recall tier
        _oracle_service=await _records_oracle(tmp_path),
        recreation_service=_Recreation(),
    )
    agent = _agent(runtime, _OneReply("Good game, Captain."))

    observation, decision = await _turn(agent, {"text": GAME_QUERY, "captain_message": GAME_QUERY})
    result = IntentResult(
        intent_id="intent-ad1357", agent_id=AGENT_ID, success=True, result=decision["llm_output"],
        metadata=_build_result_metadata({}, decision, observation),
    )
    store = _thread_store(tmp_path)
    thread = store.get_or_create_default_for_agent(AGENT_ID, "Ezri")
    store.append_message(
        thread.id, author_id=AGENT_ID, role="agent", body="Good game, Captain.",
        metadata=_build_reply_metadata("intent-ad1357", result, {}),
    )
    (row,) = [m for m in store.list_messages(thread.id, limit=10) if m.role == "agent"]
    manifest = row.metadata["context_manifest"]

    prompt = agent._llm_client.requests[0].prompt
    assert "--- Active Game ---" in prompt and "CROSS-TIER KNOWLEDGE" in prompt  # premise: all three reached it
    names = _names(manifest)
    assert _in_order(["episodic", "recall_confidence", "oracle", "active_game", "captain_message"], names), names
    assert all(section["kept"] for section in manifest["sections"])
    assert manifest["path"] == "single_pass"
    assert (manifest["recall"]["ran"], manifest["recall"]["query"]) == (True, GAME_QUERY)
    assert manifest["recall"]["episodes"] == [
        {"id": "ep-own-direct-0001", "source": "direct"},
        {"id": "ep-own-reflection-02", "source": "reflection"},
    ]
    assert manifest["recall"]["confidence"] == {"band": "weak", "best_similarity": 0.513, "recall_type": None}
    oracle = manifest["lookups"]["oracle"]
    assert (oracle["ran"], oracle["scope"], oracle["failed"]) == (True, "all", False)
    assert GAME_RECORD in oracle["record_paths"]
    assert oracle["by_tier"]["records"] == len(oracle["record_paths"])
    assert "Captain wins" not in json.dumps(manifest)


# ── T2: recall off says so ───────────────────────────────────────────


@_UNTIL_M2
@pytest.mark.parametrize(
    ("runtime_attributes", "agent_type", "params"),
    [
        pytest.param({}, "scout", {"text": "hello", "captain_message": "hello"}, id="no-episodic-memory"),
        pytest.param({"episodic_memory": _Episodic([])}, "tester", {"text": "hello", "captain_message": "hello"}, id="not-crew"),
        pytest.param({"episodic_memory": _Episodic([])}, "scout", {"text": "   ", "captain_message": "   "}, id="empty-query"),
    ],
)
async def test_a_dm_reply_with_recall_off_says_recall_did_not_run(
    runtime_attributes: dict[str, Any], agent_type: str, params: dict[str, Any],
) -> None:
    """#1749 acceptance 2: with recall off the manifest says so rather than omitting the key."""
    agent = _agent(_runtime(**runtime_attributes), _OneReply("Hello, Captain."), agent_type=agent_type)
    observation, decision = await _turn(agent, params)
    manifest = _manifest_of(observation, decision)
    assert manifest["recall"] == {"ran": False}
    assert manifest["lookups"] == NO_LOOKUPS
    assert "captain_message" in _names(manifest)


# ── T3: privacy ──────────────────────────────────────────────────────


@_UNTIL_M3
@pytest.mark.parametrize(
    "case", ["one-to-one-scene-and-peer", "group-turn", "group-turn-with-captain-message", "empty-captain-message"],
)
async def test_the_manifest_holds_no_other_agents_text_and_no_camera_scene(case: str) -> None:
    """#1749 acceptance 3: ids and counts only. A peer's recalled text, its episode id and callsign, another
    agent's room message and the camera scene the router prepends (AD-733a) all reach the prompt; none is in
    the manifest."""
    own = [Episode(id="ep-own-0001", timestamp=1.0, user_input="A chat with the Captain.", source="direct")]
    weak = RecallConfidence(band="weak", best_similarity=0.5, candidate_count=1, query="")
    peer = SimpleNamespace(id="peer-agent-1", agent_type="scout", sovereign_id="peer-agent-1")
    peer_recall = SimpleNamespace(
        episode=Episode(id="peer-episode-SECRET-0001", user_input="PEER-PRIVATE-TEXT about the Captain"),
        peer_callsign="Lyra",
    )
    runtime = _runtime(
        config=_config(cross_agent_recall_enabled=True, recall_confidence_gating_enabled=True),
        episodic_memory=_Episodic(own, weak),
        registry=SimpleNamespace(all=lambda: [peer], get_by_pool=lambda _pool: []),
        hebbian_router=SimpleNamespace(get_weight=lambda *_args: 0.5),
        _cross_agent_recall_service=SimpleNamespace(escalate_recall=AsyncMock(return_value=[peer_recall])),
    )
    agent = _agent(runtime, _OneReply("Hello, Captain."))
    scene = "Current Visual Context: SCENE-MARKER a red chair\n\nhello Ezri"
    params = {
        "one-to-one-scene-and-peer": {"text": scene, "captain_message": "hello Ezri"},
        "group-turn": {"text": "PEER-PRIVATE-TEXT from the room", "is_group_chat": True, "trigger_speaker": "Lyra"},
        "group-turn-with-captain-message": {
            "text": "PEER-PRIVATE-TEXT from the room", "is_group_chat": True, "trigger_speaker": "Lyra",
            "captain_message": "PEER-PRIVATE-TEXT from the room",
        },
        "empty-captain-message": {"text": scene, "captain_message": ""},
    }[case]

    observation, decision = await _turn(agent, params)
    manifest = _manifest_of(observation, decision)
    prompt = agent._llm_client.requests[0].prompt
    encoded = json.dumps(manifest)

    assert "PEER-PRIVATE-TEXT" in prompt  # premise: the prompt carried another agent's text
    for secret in ("PEER-PRIVATE-TEXT", "peer-episode-SECRET-0001", "Lyra", "SCENE-MARKER"):
        assert secret not in encoded, secret
    assert manifest["recall"]["episodes"] == [{"id": "ep-own-0001", "source": "direct"}]
    if case == "one-to-one-scene-and-peer":
        assert "SCENE-MARKER" in prompt  # premise
        assert manifest["recall"]["query"] == "hello Ezri"
        assert manifest["lookups"]["cross_agent_recall"] == {"ran": True, "failed": False, "count": 1}
    else:
        assert manifest["recall"]["query"] is None
        assert manifest["recall"]["query_chars"] > 0


# ── T4: bounds and storability ───────────────────────────────────────


def _encoded_size(manifest: dict[str, Any]) -> int:
    """Bytes as ``ChatThreadStore.append_message_once`` encodes metadata."""
    return len(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    )


@_UNTIL_M2
def test_the_manifest_fits_its_bound_at_every_cap() -> None:
    """The largest manifest the caps allow, in ASCII as production names and ids are (the query at its worst
    JSON escape), fits ``MAX_MANIFEST_BYTES``; one shaped like the 2026-11-04 turn is under 4 KiB."""
    from probos.cognitive import context_manifest as cm

    ledger = cm.ContextLedger()
    big = "y" * 1_000_000
    for index in range(cm.MAX_SECTIONS + 5):
        ledger.renderer(f"s{index:02d}".ljust(100, "x"), big)
    observation: dict[str, Any] = {}
    cm.start_recall(observation, query="\x01" * 500, captain_words=True)
    cm.note_episodes(observation, [SimpleNamespace(id="e" * 100, source="s" * 100) for _ in range(cm.MAX_EPISODES + 8)])
    cm.note_confidence(observation, SimpleNamespace(band="b" * 100, best_similarity=0.123456, recall_type="r" * 100))
    cm.note_cross_agent(observation, 3)
    cm.note_transcript(observation, hit=True, thread_ids=["t" * 100] * 10)
    cm.note_oracle(
        observation, "all",
        [(f"tier{i}".ljust(100, "z"), "p" * 500) for i in range(20)] + [("records", "p" * 500)] * 20,
    )
    worst = cm.build_manifest(
        ledger, observation[cm.RECALL_KEY], path="single_pass", system_prompt="x" * 50_000,
        user_message="u", response_text="r", journal_entry_id="j" * 100,
    )
    assert "unrecorded" not in worst
    assert (len(worst["sections"]), worst["sections_omitted"]) == (cm.MAX_SECTIONS, 5)
    assert worst["recall"]["episode_count"] == cm.MAX_EPISODES + 8
    assert len(worst["recall"]["episodes"]) == cm.MAX_EPISODES
    assert len(worst["lookups"]["oracle"]["record_paths"]) == cm.MAX_RECORD_PATHS
    assert len(worst["lookups"]["oracle"]["by_tier"]) == cm.MAX_TIERS
    assert len(worst["lookups"]["transcript_grounding"]["thread_ids"]) == cm.MAX_THREADS
    assert _encoded_size(worst) <= cm.MAX_MANIFEST_BYTES

    live = cm.ContextLedger()
    for name in ("temporal", "working_memory", "dm_sensorium", "episodic", "recall_confidence", "oracle",
                 "source_attribution", "session_history", "active_game", "captain_message"):
        live.renderer(name, "x" * 1500)
    turn: dict[str, Any] = {}
    cm.start_recall(turn, query="Hello Ezri", captain_words=True)
    cm.note_episodes(turn, [SimpleNamespace(id=f"{i:032x}", source="direct") for i in range(10)])
    cm.note_confidence(turn, SimpleNamespace(band="weak", best_similarity=0.513, recall_type=""))
    cm.note_oracle(turn, "all", [("records", GAME_RECORD)])
    shaped = cm.build_manifest(
        live, turn[cm.RECALL_KEY], path="agentic", system_prompt="s" * 8000,
        user_message="u" * 900, response_text="r", journal_entry_id="f" * 32,
    )
    assert _encoded_size(shaped) <= 4096


@_UNTIL_M2
@pytest.mark.parametrize(
    "similarity", [float("nan"), float("inf"), True, "0.5", 10**400],
    ids=["nan", "infinity", "a-bool", "text", "too-large-for-a-float"],
)
def test_a_similarity_that_is_not_a_finite_number_is_recorded_as_none_and_the_row_stores(
    tmp_path: Path, similarity: Any,
) -> None:
    from probos.cognitive import context_manifest as cm

    ledger = cm.ContextLedger()
    ledger.renderer("captain_message", "Captain says: hi")
    observation: dict[str, Any] = {}
    cm.start_recall(observation, query="hi", captain_words=True)
    cm.note_confidence(observation, SimpleNamespace(band="weak", best_similarity=similarity, recall_type=""))
    manifest = cm.build_manifest(
        ledger, observation[cm.RECALL_KEY], path="single_pass", system_prompt="",
        user_message="", response_text="", journal_entry_id="row-1",
    )
    assert manifest["recall"]["confidence"]["best_similarity"] is None
    store = _thread_store(tmp_path)
    thread = store.get_or_create_default_for_agent(AGENT_ID, "Ezri")
    saved = store.append_message(
        thread.id, author_id=AGENT_ID, role="agent", body="hi", metadata={"context_manifest": manifest},
    )
    assert saved is not None and saved.metadata["context_manifest"] == manifest


@_UNTIL_M2
@pytest.mark.parametrize(
    ("value", "reason"),
    [
        pytest.param(float("nan"), "unencodable", id="nan"),
        pytest.param("\ud800", "unencodable", id="lone-surrogate"),
        pytest.param("y" * 16_385, "oversize", id="oversize"),
    ],
)
def test_a_manifest_the_store_would_refuse_is_replaced_by_a_stub_that_says_so(
    tmp_path: Path, value: Any, reason: str,
) -> None:
    from probos.cognitive import context_manifest as cm

    stub = cm.storable({"x": value}, path="single_pass")
    assert stub == {"v": cm.MANIFEST_VERSION, "path": "single_pass", "unrecorded": reason}
    store = _thread_store(tmp_path)
    thread = store.get_or_create_default_for_agent(AGENT_ID, "Ezri")
    assert store.append_message(
        thread.id, author_id=AGENT_ID, role="agent", body="hi", metadata={"context_manifest": stub},
    ) is not None


# ── T5, T6: the journal row ──────────────────────────────────────────


@_UNTIL_M2
async def test_the_manifest_names_its_journal_row_on_the_single_pass_path(tmp_path: Path) -> None:
    """The single-pass row (``entry_id=request.id``) and the manifest carry the same id and hashes."""
    journal = CognitiveJournal(db_path=str(tmp_path / "cognitive_journal.db"))
    await journal.start()
    try:
        agent = _agent(_runtime(cognitive_journal=journal), _OneReply("R" * 700))
        words = "Tell me about the drill. " * 30  # over 600 characters, so the journal's 500-character cut matters
        observation, decision = await _turn(agent, {"text": words, "captain_message": words})
        manifest = _manifest_of(observation, decision)
        (row,) = await journal.get_reasoning_chain(agent.id, limit=10)
    finally:
        await journal.stop()
    assert len(agent._llm_client.requests[0].prompt) > 600  # premise
    assert manifest["path"] == "single_pass"
    assert row["intent"] == "direct_message"
    assert (row["id"], row["prompt_hash"], row["response_hash"]) == (
        manifest["journal_entry_id"], manifest["prompt_hash"], manifest["response_hash"],
    )


@_UNTIL_M4
async def test_an_agentic_dm_turn_writes_one_journal_row_that_the_manifest_names(tmp_path: Path) -> None:
    """#1749 acceptance 4: the journal has a row for the DM turn, beside the chain intents."""
    journal = CognitiveJournal(db_path=str(tmp_path / "cognitive_journal.db"))
    await journal.start()
    try:
        agent = _agent(_runtime(cognitive_journal=journal), _OneReply("unused"))
        agent._maybe_run_conversational_agentic = AsyncMock(return_value="Done, Captain.")  # type: ignore[method-assign]
        observation, decision = await _turn(agent, {"text": "Make me a doc.", "captain_message": "Make me a doc."})
        manifest = _manifest_of(observation, decision)
        rows = await journal.get_reasoning_chain(agent.id, limit=10)
    finally:
        await journal.stop()
    assert decision["tier_used"] == "agentic" and agent._llm_client.requests == []  # premise: the loop answered
    (row,) = rows
    assert manifest["path"] == "agentic"
    keys = ("id", "intent", "tier", "model", "dag_node_id", "cached", "token_source", "success",
            "response_length", "intent_id", "prompt_hash", "response_hash")
    assert {key: row[key] for key in keys} == {
        "id": manifest["journal_entry_id"], "intent": "direct_message", "tier": "agentic", "model": "unknown",
        "dag_node_id": "dm-turn", "cached": 0, "token_source": "", "success": 1,
        "response_length": len("Done, Captain."), "intent_id": observation["intent_id"],
        "prompt_hash": manifest["prompt_hash"], "response_hash": manifest["response_hash"],
    }


# ── T7 to T9: the sinks and the wire ─────────────────────────────────


@_UNTIL_M2
def test_the_reply_metadata_carries_the_manifest_the_agent_made() -> None:
    manifest = {"v": 1, "path": "single_pass", "sections": []}
    result = IntentResult(
        intent_id="i1", agent_id="a1", success=True,
        metadata={"tool_trace_ref": "a" * 64, "context_manifest": manifest},
    )
    assert _build_reply_metadata("intent-1", result, {"emotion": "warm"}) == {
        "intent_id": "intent-1", "tool_trace_ref": "a" * 64, "emotion": "warm", "context_manifest": manifest,
    }


@pytest.mark.parametrize(
    "result",
    [
        IntentResult(intent_id="i1", agent_id="a1", success=True),
        IntentResult(intent_id="i1", agent_id="a1", success=True, metadata={"context_manifest": "not a dict"}),
        IntentResult(intent_id="i1", agent_id="a1", success=True, metadata={"context_manifest": {}}),
        None,
    ],
    ids=["no-metadata", "manifest-not-a-dict", "empty-manifest", "no-result"],
)
def test_a_reply_without_a_manifest_keeps_its_metadata_unchanged(result: Any) -> None:
    assert _build_reply_metadata("intent-1", result, None) == {"intent_id": "intent-1"}


@_UNTIL_M2
async def test_a_group_reply_is_stored_with_its_manifest_and_one_without_stays_unchanged(tmp_path: Path) -> None:
    """The real AD-914 fan-out over a real ``IntentBus`` and store (test_ad914's harness, restated)."""
    store = _thread_store(tmp_path)
    bus = IntentBus(SignalManager(reap_interval=1.0))
    types = {"scout1": "scout", "counselor1": "counselor"}
    runtime = SimpleNamespace(
        chat_thread_store=store, intent_bus=bus, ontology=None, project_store=None,
        registry=SimpleNamespace(get=lambda aid: SimpleNamespace(agent_type=types[aid]) if aid in types else None),
        callsign_registry=SimpleNamespace(get_callsign=lambda t: {"scout": "Wesley", "counselor": "Ezri"}.get(t, "")),
    )
    manifest = {"v": 1, "path": "single_pass", "sections": [{"name": "captain_message", "chars": 10, "kept": True}]}

    def _handler(agent_id: str, metadata: dict[str, Any]):
        async def _handle(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id, agent_id=agent_id, success=True,
                result=f"reply::{agent_id}", metadata=metadata,
            )
        return _handle

    bus.subscribe("scout1", _handler("scout1", {"context_manifest": manifest}), intent_names=["direct_message"])
    bus.subscribe("counselor1", _handler("counselor1", {}), intent_names=["direct_message"])
    thread = store.create_thread(title="room", participants=["scout1", "counselor1"])
    captain = store.append_message(thread.id, author_id="captain", role="captain", body="status?")
    await group_chat_fanout(runtime, thread.id, captain_body="status?", captain_msg=captain)
    rows = {m.author_id: m.metadata for m in store.list_messages(thread.id, limit=100) if m.role == "agent"}
    assert rows["scout1"]["context_manifest"] == manifest
    assert "context_manifest" not in rows["counselor1"]
    assert rows["counselor1"]["fanout"] == "ad914"


@_UNTIL_M2
def test_the_manifest_is_the_last_reply_metadata_key_so_bf805_drops_it_first() -> None:
    from probos.cognitive import context_manifest as cm

    metadata = _build_result_metadata({}, {}, {"_tool_trace_ref": "a" * 64, cm.MANIFEST_KEY: {"v": 1}})
    assert list(metadata) == ["tool_trace_ref", "context_manifest"]
    # 100 bytes of room fit the trace ref's 84 and not the manifest's 30 more (by hand: IntentBus._prune_metadata)
    kept, dropped = IntentBus._prune_metadata(metadata, 0, 100)
    assert (list(kept), dropped) == (["tool_trace_ref"], ["context_manifest"])


# ── T10, T11: the ledger ─────────────────────────────────────────────


@_UNTIL_M2
def test_a_section_is_recorded_by_its_name_alone_and_kept_only_when_assembly_renders_it() -> None:
    from probos.cognitive import context_manifest as cm

    observation: dict[str, Any] = {cm.MANIFEST_KEY: {"v": 1, "path": "stale"}}
    ledger = cm.start_ledger(observation)
    assert observation[cm.LEDGER_KEY] is ledger and cm.MANIFEST_KEY not in observation
    assert cm.ledger_of(observation) is ledger
    text = "the head-to-head tally: Captain 2, Ezri 0"
    render = ledger.renderer("head_to_head_tally", text)  # a name no manifest code knows
    ledger.renderer("dropped_section", "never rendered")
    ledger.note_appended("nothing_appended", 0)
    ledger.note_appended("strategy_advice", 7)
    assert ledger.to_wire() == ([
        {"name": "head_to_head_tally", "chars": len(text), "kept": False},
        {"name": "dropped_section", "chars": 14, "kept": False},
        {"name": "strategy_advice", "chars": 7, "kept": True},
    ], 0)
    assert render() is text
    sections, _ = ledger.to_wire()
    assert (sections[0]["kept"], sections[1]["kept"]) == (True, False)


@_UNTIL_M2
async def test_a_section_the_attention_budget_drops_is_recorded_as_not_kept() -> None:
    from probos.cognitive import context_manifest as cm

    agent = make_dm_agent()
    observation = dm_observation()
    captain = "Captain says: " + observation["params"]["text"]
    agent._runtime = SimpleNamespace(config=SimpleNamespace(memory=SimpleNamespace(
        attention=SimpleNamespace(enabled=True, token_budget=estimate_tokens(captain)),
    )))
    prompt = await agent._build_user_message(observation)
    sections, _ = observation[cm.LEDGER_KEY].to_wire()
    kept = {section["name"]: section["kept"] for section in sections}
    assert prompt == captain
    assert [name for name, was_kept in kept.items() if was_kept] == ["captain_message"]
    assert {"temporal", "episodic", "oracle", "session_history"} <= set(kept)


# ── T13 to T18: the lookups ──────────────────────────────────────────


@_UNTIL_M3
async def test_the_oracle_reports_what_it_rendered_and_renders_the_same_text(tmp_path: Path) -> None:
    oracle = await _records_oracle(tmp_path)
    sources: list[tuple[str, str]] = []
    with_sink = await oracle.query_formatted(GAME_QUERY, agent_id=AGENT_ID, k_per_tier=3, max_chars=2000, sources_out=sources)
    without = await oracle.query_formatted(GAME_QUERY, agent_id=AGENT_ID, k_per_tier=3, max_chars=2000)
    assert with_sink == without
    assert ("records", GAME_RECORD) in sources
    for _tier, path in sources:
        assert path in with_sink


@_UNTIL_M3
@pytest.mark.parametrize("case", ["a-room-matches", "only-a-title-matches"])
def test_transcript_grounding_reports_the_room_its_excerpt_came_from(tmp_path: Path, case: str) -> None:
    from probos.cognitive.transcript_grounding import consult_transcript

    store = _thread_store(tmp_path)
    if case == "a-room-matches":
        thread = store.create_thread(title="sidebar", participants=[AGENT_ID, "captain"])
        store.append_message(thread.id, author_id="captain", role="captain", body="the condensed sidebar voice stream")
        query = "condensed sidebar voice"
    else:
        thread = store.create_thread(title="kingfisher anomaly", participants=[AGENT_ID, "captain"])
        store.append_message(thread.id, author_id="captain", role="captain", body="hello there")
        query = "kingfisher"
    rooms: list[str] = []
    excerpt = consult_transcript(store, {AGENT_ID}, query, sources_out=rooms)
    assert excerpt == consult_transcript(store, {AGENT_ID}, query)
    if case == "a-room-matches":
        assert excerpt is not None and rooms == [thread.id]
    else:
        assert excerpt is None and rooms == []


@_UNTIL_M2
def test_only_ship_records_results_are_identified_and_every_tier_is_counted() -> None:
    from probos.cognitive import context_manifest as cm

    observation: dict[str, Any] = {}
    cm.start_recall(observation, query="q", captain_words=True)
    cm.note_oracle(observation, "all", [
        ("records", "notebooks/Lyra/drill.md"), ("episodic", "peer-episode-9"),
        ("archive", "archive/peer.md"), ("records", ""),
    ])
    _, lookups = observation[cm.RECALL_KEY].to_wire()
    assert lookups["oracle"] == {
        "ran": True, "scope": "all", "failed": False, "results": 4,
        "by_tier": {"records": 2, "episodic": 1, "archive": 1}, "record_paths": ["notebooks/Lyra/drill.md"],
    }
    cm.note_oracle(observation, "graph", None)
    _, lookups = observation[cm.RECALL_KEY].to_wire()
    assert lookups["oracle"] == {
        "ran": True, "scope": "graph", "failed": True, "results": 0, "by_tier": {}, "record_paths": [],
    }


@_UNTIL_M2
@pytest.mark.parametrize("case", ["strategy-advice", "owned-steps-view", "room-inputs"])
async def test_text_appended_after_assembly_is_recorded_by_name_and_length(case: str) -> None:
    agent = _agent(_runtime(), _OneReply("Aye."))
    params: dict[str, Any] = {"text": "status?", "captain_message": "status?"}
    if case == "strategy-advice":
        agent._strategy_advisor = SimpleNamespace(
            query_strategies=lambda _intent, _type: [{"id": "s-1"}],
            format_for_context=lambda _strategies: "STRATEGY: answer briefly.",
        )
        name, chars = "strategy_advice", len("\n\n" + "STRATEGY: answer briefly.")
    elif case == "owned-steps-view":
        owner = SimpleNamespace(admit_owned_steps_presentation=AsyncMock())
        agent._resolve_owned_steps_model_context = AsyncMock(  # type: ignore[method-assign]
            return_value=("RAW-VIEW", owner, object(), object()),
        )
        name, chars = "owned_steps_view", len("\n\n<owned_steps_view>\nRAW-VIEW\n</owned_steps_view>")
    else:
        params = {"text": "status?", "is_group_chat": True, "room_input_hashes": ["deadbeef"]}
        name, chars = "room_inputs", len("\nRoom inputs unavailable; do not claim complete analysis.")
    observation, decision = await _turn(agent, params)
    manifest = _manifest_of(observation, decision)
    assert manifest["sections"][-1] == {"name": name, "chars": chars, "kept": True}


@_UNTIL_M3
async def test_recall_records_the_room_transcript_grounding_drew_on(tmp_path: Path) -> None:
    from probos.cognitive import context_manifest as cm

    store = _thread_store(tmp_path)
    thread = store.create_thread(title="sidebar", participants=[AGENT_ID, "captain"])
    store.append_message(thread.id, author_id="captain", role="captain", body="the condensed sidebar voice stream")
    runtime = _runtime(
        config=_config(transcript_grounded_recall_enabled=True),
        episodic_memory=_Episodic([]), chat_thread_store=store,
    )
    agent = _agent(runtime, _OneReply("unused"))
    params = {"text": "condensed sidebar voice", "captain_message": "condensed sidebar voice"}
    intent = IntentMessage(intent="direct_message", params=params)
    observation = await agent._recall_relevant_memories(intent, _observation(params, intent_id=intent.id))
    _, lookups = observation[cm.RECALL_KEY].to_wire()
    assert observation.get("_transcript_grounding")  # premise: grounding fed the prompt
    assert lookups["transcript_grounding"] == {"ran": True, "hit": True, "thread_ids": [thread.id]}


@_UNTIL_M3
async def test_a_graph_only_lookup_is_recorded_with_its_scope(tmp_path: Path) -> None:
    """No trust network: the agent's rank is None, so its tier is ENHANCED and BF-265's graph-only query runs."""
    from probos.cognitive import context_manifest as cm

    runtime = _runtime(
        episodic_memory=_Episodic([Episode(id="ep-1", timestamp=1.0, user_input="a chat", source="direct")]),
        _oracle_service=await _records_oracle(tmp_path),
    )
    agent = _agent(runtime, _OneReply("unused"))
    params = {"text": GAME_QUERY, "captain_message": GAME_QUERY}
    intent = IntentMessage(intent="direct_message", params=params)
    observation = await agent._recall_relevant_memories(intent, _observation(params, intent_id=intent.id))
    _, lookups = observation[cm.RECALL_KEY].to_wire()
    assert lookups["oracle"] == {
        "ran": True, "scope": "graph", "failed": False, "results": 0, "by_tier": {}, "record_paths": [],
    }
