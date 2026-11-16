"""Ward Room identity keys: an agent id finds its department; the cascade check meets episode owners in their own key.

#1792: resolve_author_department finds the department of an agent given its id ({type}_{pool}_{index}_{hash8}), not
only of a bare type, so a Ward Room episode an agent writes carries its department anchor.
#1793: the cascade check matches a post's author and its peers to episodes under both ids the Ward Room stores them
under (the slot id, and the certificate id the identity registry maps it to), from a pool large enough for every
peer that keeps every episode the old recall of three held; a reply episode stores the channel's id, as a thread
episode does.

The real WardRoomService runs on a temporary database with a real AgentIdentityRegistry and an episodic store double
that records what it is given and answers ``recall`` with the first ``k`` stored episodes (the real cap, no ranking).
Case mh uses a recall shaped like hybrid recall, which a wider ``k`` can make drop an episode; case mi uses one that
answers new Episode objects on every recall, as a real store does.
Synthetic fixtures only. A case marked ``until_built("#N")`` fails on the base at its own assert; the milestone that
builds #N adds it to ``_BUILT``. ``WARD_ROOM_IDENTITY_KEYS_RUNXFAIL=1`` runs every case plainly.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio

import probos.substrate.identity as substrate_identity
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.episodic import reciprocal_rank_fusion
from probos.cognitive.social_verification import SocialVerificationService
from probos.cognitive.thread_priority.scorer import ThreadPriorityScorer
from probos.cognitive.thread_priority.service import ThreadPriorityService
from probos.config import OrientationConfig, SocialVerificationConfig, SystemConfig
from probos.events import EventType
from probos.identity import AgentIdentityRegistry
from probos.substrate.identity import generate_agent_id
from probos.types import AnchorFrame, Episode
from probos.ward_room import WardRoomService
from probos.ward_room._helpers import resolve_author_department

_BUILT: frozenset[str] = frozenset({"#1792", "#1793"})


def until_built(issue: str) -> Any:
    """Strict xfail at an assert until *issue*'s milestone adds it to ``_BUILT``."""
    if issue in _BUILT or os.environ.get("WARD_ROOM_IDENTITY_KEYS_RUNXFAIL") == "1":
        return lambda func: func
    return pytest.mark.xfail(raises=AssertionError, strict=True)


_SHIP = "wr-keys-ship"
_PROCEDURE_ID = "wr-keys-procedure"
_PROMOTION = {
    "eligible": True,
    "criticality": "low",
    "procedure_name": "wr-keys-procedure",
    "procedure_description": "A synthetic procedure.",
    "compilation_level": 4,
    "intent_types": ["synthetic_intent"],
    "quality_metrics": {"effective_rate": 0.9, "total_completions": 12},
}
#: (slot id, agent type, callsign); production-shaped ids from substrate/identity.generate_agent_id.
_BUILDER = (generate_agent_id("builder", "builder", 0), "builder", "Forge")
_SURGEON = (generate_agent_id("surgeon", "surgeon", 0), "surgeon", "Lance")
_PEERS = [
    (generate_agent_id("scout", "scout", 0), "scout", "Wren"),
    (generate_agent_id("architect", "architect", 0), "architect", "Quill"),
    (generate_agent_id("pathologist", "pathologist", 0), "pathologist", "Marrow"),
]
_ECHO = "I agree we should review the onboarding checklist together before the next watch begins"
_STATUS = "Routine status from the medical bay: supplies counted, rota posted"
#: The most rows one post's peer check returns: two queries of LIMIT 20 (ward_room/threads.py check_peer_similarity).
_MAX_PEERS = 40


class _Episodes:
    """The store the Ward Room writes to and the cascade check reads: what it is given, in order."""

    def __init__(self, first: list[Episode] | None = None) -> None:
        self.stored: list[Episode] = list(first or [])

    async def store(self, episode: Episode) -> None:
        self.stored.append(episode)

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        return self.stored[:k]


class _Copies(_Episodes):
    """As ``_Episodes``, but each recall answers new Episode objects, as a real store builds them per recall."""

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        return [dataclasses.replace(ep) for ep in self.stored[:k]]


class _Fused:
    """A recall shaped like hybrid recall (episodic.py ``_fuse_dense_sparse``): the dense top ``k`` and the sparse
    top ``3 * k``, fused by the production ``reciprocal_rank_fusion`` at its default ``k=60``, then cut to ``k``.
    Both rankings grow with ``k``, so a wider recall need not hold a narrower one's episodes."""

    def __init__(self, dense: list[Episode], sparse: list[Episode]) -> None:
        self._by_id = {ep.id: ep for ep in [*dense, *sparse]}
        self._dense = [ep.id for ep in dense]
        self._sparse = [ep.id for ep in sparse]

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        fused = reciprocal_rank_fusion([self._dense[:k], self._sparse[: k * 3]], k=60)
        return [self._by_id[eid] for eid, _score in fused[:k]]


@pytest_asyncio.fixture
async def registry(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    """A real identity registry, started and commissioned as tests/test_ad1196_did_key_binding.py does."""
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=_SHIP, vessel_name="Wr-keys-ship", version="1")
        yield reg
    finally:
        await reg.stop()


async def _certify(reg: AgentIdentityRegistry, agents: list[tuple[str, str, str]]) -> None:
    for slot, agent_type, callsign in agents:
        cert = await reg.issue_birth_certificate(
            agent_type=agent_type, callsign=callsign, instance_id=_SHIP, vessel_name="Wr-keys-ship",
            department="", post_id=f"post-{callsign}", baseline_version="v1", slot_id=slot,
        )
        assert reg.get_by_slot(slot) is cert and cert.agent_uuid != slot  # premise: the slot maps to a certificate id


@contextlib.asynccontextmanager
async def _room(directory: Path, episodes: _Episodes, registry: Any, verification: Any = None) -> AsyncIterator[WardRoomService]:
    directory.mkdir(parents=True, exist_ok=True)
    room = WardRoomService(db_path=str(directory / "ward_room.db"), episodic_memory=episodes, identity_registry=registry)
    await room.start()
    try:
        if verification is not None:
            room.set_social_verification(verification)
        yield room
    finally:
        await room.stop()


async def _all_hands(room: WardRoomService) -> Any:
    return next(channel for channel in await room.list_channels() if channel.name == "All Hands")


class _Builder(CognitiveAgent):
    """A real agent of a type with a department entry (builder -> engineering)."""

    agent_type = "builder"
    instructions = "Synthetic instructions."


async def _promote(room: WardRoomService) -> Any:
    """A real promotion request (CognitiveAgent._announce_promotion_request) by the builder; its All Hands thread."""
    runtime = SimpleNamespace(ward_room=room, ontology=None, trust_network=None, procedure_store=None)
    agent = _Builder(pool="builder", agent_id=_BUILDER[0], runtime=runtime)
    agent.callsign = _BUILDER[2]
    await agent._announce_promotion_request(_PROCEDURE_ID, _PROMOTION)
    channel = await _all_hands(room)
    posted = [t for t in await room.list_threads(channel.id) if t.title.startswith("[Promotion Request]")]
    assert [t.author_id for t in posted] == [_BUILDER[0]]  # premise: posted under the agent's id
    return posted[0]


def _episodes_of(episodes: _Episodes, thread_id: str, trigger_type: str) -> list[Episode]:
    return [
        ep for ep in episodes.stored
        if ep.anchors is not None and ep.anchors.thread_id == thread_id and ep.anchors.trigger_type == trigger_type
    ]


def _cascade_service(episodes: _Episodes) -> tuple[SocialVerificationService, list[str]]:
    """The service startup builds (default config), with an emitter recording each cascade event's risk."""
    risks: list[str] = []

    def emit(event_type: str, data: dict) -> None:
        if event_type == EventType.CASCADE_CONFABULATION_DETECTED.value:
            risks.append(data["risk_level"])

    return SocialVerificationService(episodes, SocialVerificationConfig(), emit_event_fn=emit), risks


async def _thread_echo(tmp_path: Path, registry: AgentIdentityRegistry, *, certify: str) -> list[str]:
    """Three peers post the promotion request's body as threads in All Hands; then the builder posts the request.

    certify: "before" issues every certificate before the first post; "after" between the peers' posts and the
    request (their episodes keep the slot id, as before BF-103's migration); "never" issues none."""
    async with _room(tmp_path / "scratch", _Episodes(), None) as scratch:
        body = (await _promote(scratch)).body
    episodes = _Episodes()
    service, risks = _cascade_service(episodes)
    everyone = [*_PEERS, _BUILDER]
    async with _room(tmp_path / "room", episodes, registry, service) as room:
        if certify == "before":
            await _certify(registry, everyone)
        channel = await _all_hands(room)
        for index, (slot, _agent_type, callsign) in enumerate(_PEERS):
            await room.create_thread(
                channel_id=channel.id, author_id=slot, title=f"Echo {index}", body=body, author_callsign=callsign,
            )
        if certify == "after":
            await _certify(registry, everyone)
        await _promote(room)
    return risks


async def _reply_echo(tmp_path: Path, registry: AgentIdentityRegistry) -> tuple[list[str], _Episodes, str, str]:
    """Certificated agents. The surgeon opens a status thread; a peer posts the echo as a thread; two peers and the
    builder post it as replies in the status thread. Returns the risks, the store, the channel id and the thread id."""
    episodes = _Episodes()
    service, risks = _cascade_service(episodes)
    async with _room(tmp_path / "room", episodes, registry, service) as room:
        await _certify(registry, [*_PEERS, _BUILDER, _SURGEON])
        channel = await _all_hands(room)
        status = await room.create_thread(
            channel_id=channel.id, author_id=_SURGEON[0], title="Watch status", body=_STATUS,
            author_callsign=_SURGEON[2],
        )
        first, *rest = _PEERS
        await room.create_thread(
            channel_id=channel.id, author_id=first[0], title="Echo", body=_ECHO, author_callsign=first[2],
        )
        for slot, _agent_type, callsign in [*rest, _BUILDER]:
            await room.create_post(thread_id=status.id, author_id=slot, body=_ECHO, author_callsign=callsign)
    return risks, episodes, channel.id, status.id


def _restored_id(agent_type: str, pool: str, index: int) -> str:
    """A production-shaped id built by hand, as one read back from storage: not from generate_agent_id."""
    digest = hashlib.sha256(f"{agent_type}:{pool}:{index}".encode()).hexdigest()[:8]
    return f"{agent_type}_{pool}_{index}_{digest}"


def _owned(owner: str, thread_id: str, department: str) -> Episode:
    return Episode(
        user_input=f"[Ward Room] All Hands: {thread_id}", timestamp=1000.0, agent_ids=[owner], source="direct",
        anchors=AnchorFrame(
            channel="ward_room", channel_id="all-hands-id", thread_id=thread_id, trigger_type="ward_room_post",
            department=department, source_origin_id=f"wr-thread:{thread_id}",
        ),
    )


# --- #1792 -----------------------------------------------------------------------------------------------------


@until_built("#1792")
def test_r1_a_production_id_resolves_to_its_types_department() -> None:
    assert resolve_author_department(_BUILDER[0]) == "engineering"
    assert resolve_author_department(_restored_id("code_reviewer", "code_reviewer", 3)) == "engineering"
    assert resolve_author_department(_restored_id("research_specialist", "science-pool", 1)) == "science"


@until_built("#1792")
def test_r3_r4_agent_type_of_names_a_type_only_for_a_verified_id() -> None:
    agent_type_of = getattr(substrate_identity, "agent_type_of", None)
    assert callable(agent_type_of)
    assert agent_type_of(_BUILDER[0]) == "builder"
    assert agent_type_of(_restored_id("code_reviewer", "code_reviewer", 3)) == "code_reviewer"
    assert agent_type_of("red_team_0_deadbeef") == ""  # its hash matches no split: the prefix is not a type
    assert agent_type_of("builder") == ""
    assert agent_type_of("") == ""
    assert agent_type_of(None) == ""  # type: ignore[arg-type]


def test_r2_r3_a_bare_type_a_key_and_an_unknown_value_behave_as_before() -> None:
    assert resolve_author_department("builder") == "engineering"
    assert resolve_author_department("surgeon") == "medical"
    for value in ("captain", "system", "", "red_team_0_deadbeef", "nobody_nobody_0_00000000", None):
        assert resolve_author_department(value) == ""  # type: ignore[arg-type]


@until_built("#1792")
@pytest.mark.asyncio
async def test_r1_thread_and_reply_episodes_carry_their_authors_departments(tmp_path: Path, registry) -> None:
    _risks, episodes, _channel_id, status_id = await _reply_echo(tmp_path, registry)
    threads = _episodes_of(episodes, status_id, "ward_room_post")
    replies = {ep.anchors.trigger_agent: ep.anchors.department for ep in _episodes_of(episodes, status_id, "ward_room_reply")}
    assert [ep.anchors.department for ep in threads] == ["medical"]
    assert replies == {"Quill": "science", "Marrow": "medical", "Forge": "engineering"}


@until_built("#1792")
@pytest.mark.asyncio
async def test_r1_a_promotion_request_episode_carries_its_agents_department(tmp_path: Path, registry) -> None:
    episodes = _Episodes()
    async with _room(tmp_path / "room", episodes, registry) as room:
        await _certify(registry, [_BUILDER])
        thread = await _promote(room)
    stored = _episodes_of(episodes, thread.id, "ward_room_post")
    assert len(stored) == 1  # premise
    assert stored[0].anchors.department == "engineering"


@until_built("#1792")
@pytest.mark.asyncio
async def test_r1_thread_priority_reads_the_departments_of_production_shaped_authors(tmp_path: Path, registry) -> None:
    async with _room(tmp_path / "room", _Episodes(), registry) as room:
        channel = await _all_hands(room)
        thread = await room.create_thread(
            channel_id=channel.id, author_id=_SURGEON[0], title="Priorities", body=_STATUS, author_callsign=_SURGEON[2],
        )
        for slot, _agent_type, callsign in (_BUILDER, _PEERS[1]):
            await room.create_post(thread_id=thread.id, author_id=slot, body=f"{callsign} acknowledges.", author_callsign=callsign)
        service = ThreadPriorityService(runtime=SimpleNamespace(ward_room=room), scorer=ThreadPriorityScorer())
        built = await service._build_input(thread.id)
    assert built is not None
    assert built.participant_departments == ["engineering", "science"]


@until_built("#1792")
def test_the_unread_orientation_flag_is_gone_and_a_config_that_sets_it_still_loads() -> None:
    assert "populate_ward_room_department" not in OrientationConfig.model_fields
    loaded = SystemConfig.model_validate({"orientation": {"populate_ward_room_department": False, "enabled": True}})
    assert loaded.orientation.enabled is True
    assert "populate_ward_room_department" not in loaded.orientation.model_dump()


# --- #1793 -----------------------------------------------------------------------------------------------------


@until_built("#1793")
@pytest.mark.asyncio
async def test_ma_md_me_an_echo_among_certificated_agents_is_reported(tmp_path: Path, registry) -> None:
    assert await _thread_echo(tmp_path, registry, certify="before") == ["medium", "high"]


@pytest.mark.asyncio
async def test_the_same_echo_among_agents_with_no_certificate_is_reported_as_before(tmp_path: Path, registry) -> None:
    assert await _thread_echo(tmp_path, registry, certify="never") == ["medium", "high"]


@pytest.mark.asyncio
async def test_mb_an_agent_certificated_after_its_posts_is_still_matched(tmp_path: Path, registry) -> None:
    assert await _thread_echo(tmp_path, registry, certify="after") == ["medium", "high"]


@until_built("#1793")
@pytest.mark.asyncio
async def test_me_mf_mg_an_echo_in_replies_among_certificated_agents_is_reported(tmp_path: Path, registry) -> None:
    risks, _episodes, _channel_id, _status_id = await _reply_echo(tmp_path, registry)
    assert risks == ["medium", "high"]


@until_built("#1793")
@pytest.mark.asyncio
async def test_mf_mg_reply_episodes_store_the_channel_id(tmp_path: Path, registry) -> None:
    _risks, episodes, channel_id, status_id = await _reply_echo(tmp_path, registry)
    stored = [*_episodes_of(episodes, status_id, "ward_room_reply"), *_episodes_of(episodes, status_id, "peer_repetition")]
    assert len(stored) == 6  # premise: three replies, each with a peer-echo episode
    assert {ep.anchors.channel_id for ep in stored} == {channel_id}


@until_built("#1793")
@pytest.mark.asyncio
async def test_mc_one_recall_holds_a_matching_episode_of_every_peer_at_the_production_bound() -> None:
    peers = [generate_agent_id("scout", "scout", index) for index in range(_MAX_PEERS)]
    readers = [_owned(generate_agent_id("counselor", "counselor", index), f"read-{index}", "bridge") for index in range(3)]
    owned = [
        _owned(peer, f"echo-{index}", "medical" if index == _MAX_PEERS - 1 else "science")
        for index, peer in enumerate(peers)
    ]
    service = SocialVerificationService(_Episodes([*readers, *owned]), SocialVerificationConfig())
    matches = [{"author_id": peer, "author_callsign": f"Peer{index}", "timestamp": 1000.0 + index} for index, peer in enumerate(peers)]
    result = await service.check_cascade_risk(
        generate_agent_id("builder", "builder", 7), "Forge", _ECHO, "all-hands-id", peer_matches=matches,
    )
    assert result is not None
    assert result.affected_departments == ["medical", "science"]
    assert result.risk_level == "high"


def _shared(eid: str, owner: str) -> Episode:
    """An episode of ``owner`` in the one thread every peer echoes: no pair of these is independent."""
    return Episode(
        id=eid, timestamp=1000.0, user_input=_ECHO, agent_ids=[owner],
        anchors=AnchorFrame(channel_id="all-hands-id", thread_id="shared"),
    )


@pytest.mark.asyncio
async def test_mh_the_wider_recall_does_not_drop_an_episode_the_recall_of_three_held() -> None:
    """Hybrid-shaped recall: the recall of 3 holds the second peer's episode; the recall of 3 per author id (four
    ids, so 12) ranks eleven boosted episodes and dense-00 above it. The check keeps it, as the base did."""
    dense = [_shared(f"dense-{i:02}", "peer-a" if i == 0 else "other") for i in range(15)]
    sparse = [_shared("visual-00", "peer-b"), *dense[3:11], dense[1], dense[2], *dense[11:]]
    store = _Fused(dense, sparse)
    narrow = [ep.id for ep in await store.recall(_ECHO, k=3)]
    wide = [ep.id for ep in await store.recall(_ECHO, k=12)]
    assert narrow == ["dense-00", "visual-00", "dense-01"]  # premise: the recall of 3 holds both peers' episodes
    assert "visual-00" not in wide and "dense-00" in wide  # premise: the recall of 12 drops one of them
    matches = [{"author_id": f"peer-{x}", "author_callsign": x.upper(), "timestamp": 1000.0 + i} for i, x in enumerate("abc")]
    result = await SocialVerificationService(store, SocialVerificationConfig()).check_cascade_risk(
        "author", "Author", _ECHO, "all-hands-id", peer_matches=matches,
    )
    assert result is not None
    assert result.risk_level == "high"


@pytest.mark.asyncio
async def test_mi_an_episode_both_recalls_hold_counts_once() -> None:
    """Two peers' episodes in different channels and threads: one independent pair, score 1.0. Both recalls answer
    both episodes as new objects; counted twice they would give 4 of 6 independent pairs."""
    first = Episode(
        id="echo-a", timestamp=1000.0, user_input=_ECHO, agent_ids=["peer-a"],
        anchors=AnchorFrame(channel_id="channel-a", thread_id="thread-a"),
    )
    second = Episode(
        id="echo-b", timestamp=1000.0, user_input=_ECHO, agent_ids=["peer-b"],
        anchors=AnchorFrame(channel_id="channel-b", thread_id="thread-b"),
    )
    matches = [{"author_id": f"peer-{x}", "author_callsign": x.upper(), "timestamp": 1000.0} for x in "ab"]
    result = await SocialVerificationService(_Copies([first, second]), SocialVerificationConfig()).check_cascade_risk(
        "author", "Author", _ECHO, "all-hands-id", peer_matches=matches,
    )
    assert result is not None
    assert result.anchor_independence_score == 1.0
