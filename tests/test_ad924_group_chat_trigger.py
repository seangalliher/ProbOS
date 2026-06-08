"""AD-924: agent-facing group-chat trigger tests.

BF-287 discipline: the runtime container is a ``MagicMock(spec=ProbOSRuntime)``
shell -- it only has to satisfy the ``ward_room`` early-return guard and expose
``trust_network`` / ``config`` -- but every substrate the code under test
actually touches is REAL. A real ``AgentGroupChatService`` runs over a real
``ChatThreadStore`` on ``tmp_path``, the registry is a real-but-fake stub (NOT a
``MagicMock``), and the callsign path uses the real ``CallsignRegistry``. Every
room assertion is against the real store (``list_threads`` / ``get_thread``),
never a mock -- this avoids the MagicMock auto-attribute phantom trap (BF-287).

The AD-918 fixtures (``_FakeAgent`` / ``_NoCallsigns`` / ``_Clock``) are reused;
a local ``_FakeRegistry`` adds ``.all()`` since the parent
``_extract_and_execute_actions`` path is driven end-to-end here.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.threads import ChatThreadStore
from probos.threads.agent_group_chat import AgentGroupChatService
from probos.ward_room import WardRoomService

# Reuse the AD-918 BF-287 fixtures (real-but-fake stubs, injectable clock).
from tests.test_ad918_agent_initiated_group_chat import (
    _Clock,
    _FakeAgent,
)

from pathlib import Path

FEDERATION_ORDERS = Path("config/standing_orders/federation.md")
GROUP_CHAT_MANUAL = Path("config/manuals/group-chat.md")


# Trust thresholds: 0.85 senior, 0.7 commander, 0.5 lieutenant.
_TRUST_COMMANDER = 0.75
_TRUST_LIEUTENANT = 0.6
_TRUST_ENSIGN = 0.3


class _FakeRegistry:
    """Real-but-fake registry: ``.get`` / ``.get_by_pool`` / ``.all`` (no MagicMock)."""

    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)

    def get_by_pool(self, agent_type: str):
        return [a for a in self._a.values() if a.agent_type == agent_type]

    def all(self):
        return list(self._a.values())


class _StubCallsigns:
    """Callsign stub: ``resolve`` always misses (agent_id-only path), and
    ``get_callsign`` returns a placeholder. The driven parent path
    (``_extract_and_execute_actions``) calls ``get_callsign(agent_type)`` in its
    recreation/challenge block; with no ``[CHALLENGE]`` tags in these texts the
    value is computed-but-unused. The real ``CallsignRegistry`` is used for the
    callsign-resolution test."""

    def resolve(self, ref: str):
        return None

    def get_callsign(self, agent_type: str) -> str:
        return ""


def _build_loop(
    tmp_path,
    *,
    agents: dict[str, _FakeAgent],
    trust: float = _TRUST_COMMANDER,
    callsign_registry=None,
    clock: _Clock | None = None,
) -> tuple[ProactiveCognitiveLoop, ChatThreadStore, _FakeRegistry, AgentGroupChatService]:
    """Wire a real service + store behind a MagicMock(spec=ProbOSRuntime) shell."""
    cfg = SystemConfig()
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    registry = _FakeRegistry(agents)
    cs = callsign_registry or _StubCallsigns()
    svc = AgentGroupChatService(
        store=store,
        registry=registry,
        callsign_registry=cs,
        config=cfg.group_chat,
        ontology_provider=None,
        clock=clock or _Clock(),
    )
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.ward_room = MagicMock(spec=WardRoomService)   # truthy -> passes the early-return guard
    runtime.ward_room_router = None                        # neutralize the endorsement path
    runtime.is_cold_start = False
    runtime.trust_network = MagicMock(spec=TrustNetwork)
    runtime.trust_network.get_score.return_value = trust
    runtime.config = cfg
    runtime.agent_group_chat = svc                          # REAL service over REAL store
    runtime.registry = registry
    runtime.callsign_registry = cs
    loop = ProactiveCognitiveLoop(interval=60)
    loop.set_runtime(runtime)
    return loop, store, registry, svc


# ---------------- 1. Commander creates a room ----------------


@pytest.mark.asyncio
async def test_commander_creates_room_with_title_participants_and_creator(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
        "data-1": _FakeAgent("data-1", "data_analyst"),
    }
    loop, store, _, _ = _build_loop(tmp_path, agents=agents)
    agent = agents["forge-1"]
    text = '[GROUP_CHAT title="Sensor Review" @bones-1,@data-1]\nLet us sync.\n[/GROUP_CHAT]'

    cleaned, actions = await loop._extract_and_execute_actions(agent, text)

    threads = store.list_threads()
    assert len(threads) == 1
    persisted = store.get_thread(threads[0].id)
    assert persisted.title == "Sensor Review"
    assert set(persisted.participants) == {"forge-1", "bones-1", "data-1"}
    assert "forge-1" in persisted.participants  # creator auto-added
    gc_actions = [a for a in actions if a["type"] == "group_chat"]
    assert len(gc_actions) == 1
    assert gc_actions[0]["title"] == "Sensor Review"
    assert gc_actions[0]["thread_id"] == persisted.id


# ---------------- 2. tag stripped ----------------


@pytest.mark.asyncio
async def test_tag_stripped_from_posted_text(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
    }
    loop, _, _, _ = _build_loop(tmp_path, agents=agents)
    agent = agents["forge-1"]
    text = 'Before. [GROUP_CHAT title="Coord" @bones-1] Kick off. [/GROUP_CHAT] After.'

    cleaned, _ = await loop._extract_and_execute_actions(agent, text)

    assert "[GROUP_CHAT" not in cleaned
    assert "[/GROUP_CHAT]" not in cleaned


# ---------------- 3. Ensign gated out ----------------


@pytest.mark.asyncio
async def test_ensign_gated_out_no_room(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
    }
    loop, store, _, _ = _build_loop(tmp_path, agents=agents, trust=_TRUST_ENSIGN)
    agent = agents["forge-1"]
    text = '[GROUP_CHAT title="Coord" @bones-1] Hi. [/GROUP_CHAT]'

    _, actions = await loop._extract_and_execute_actions(agent, text)

    assert store.list_threads() == []
    assert not [a for a in actions if a["type"] == "group_chat"]


# ---------------- 4. Lieutenant gated out ----------------


@pytest.mark.asyncio
async def test_lieutenant_gated_out_no_room(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
    }
    loop, store, _, _ = _build_loop(tmp_path, agents=agents, trust=_TRUST_LIEUTENANT)
    agent = agents["forge-1"]
    text = '[GROUP_CHAT title="Coord" @bones-1] Hi. [/GROUP_CHAT]'

    _, actions = await loop._extract_and_execute_actions(agent, text)

    assert store.list_threads() == []
    assert not [a for a in actions if a["type"] == "group_chat"]


# ---------------- 5. participants resolved by callsign ----------------


@pytest.mark.asyncio
async def test_participants_resolved_by_callsign(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
    }
    registry = _FakeRegistry(agents)
    cs = CallsignRegistry()
    cs.load_from_profiles()
    cs.bind_registry(registry)
    # "Bones" -> agent_type diagnostician -> bones-1.
    loop, store, _, _ = _build_loop(tmp_path, agents=agents, callsign_registry=cs)
    agent = agents["forge-1"]
    text = '[GROUP_CHAT title="Sickbay" @Bones] Status? [/GROUP_CHAT]'

    _, _ = await loop._extract_and_execute_actions(agent, text)

    threads = store.list_threads()
    assert len(threads) == 1
    persisted = store.get_thread(threads[0].id)
    assert "bones-1" in persisted.participants
    assert "forge-1" in persisted.participants


# ---------------- 6. cooldown blocks rapid second create ----------------


@pytest.mark.asyncio
async def test_cooldown_blocks_rapid_second_create(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
    }
    clock = _Clock(1000.0)  # not advanced -> 2nd create is within the 60s cooldown
    loop, store, _, _ = _build_loop(tmp_path, agents=agents, clock=clock)
    agent = agents["forge-1"]
    text = (
        '[GROUP_CHAT title="First" @bones-1] one [/GROUP_CHAT]\n'
        '[GROUP_CHAT title="Second" @bones-1] two [/GROUP_CHAT]'
    )

    _, actions = await loop._extract_and_execute_actions(agent, text)

    assert len(store.list_threads()) == 1  # only the first room
    created = [a for a in actions if a["type"] == "group_chat"]
    suppressed = [a for a in actions if a["type"] == "group_chat_suppressed"]
    assert len(created) == 1
    assert len(suppressed) == 1
    assert suppressed[0]["reason"] == "rate_limited"


# ---------------- 7. malformed tag degrades cleanly ----------------


@pytest.mark.asyncio
async def test_malformed_tag_degrades_cleanly(tmp_path):
    agents = {"forge-1": _FakeAgent("forge-1", "builder")}
    loop, store, _, _ = _build_loop(tmp_path, agents=agents)
    agent = agents["forge-1"]
    text = "[GROUP_CHAT no title here] just a malformed marker"

    cleaned, actions = await loop._extract_and_execute_actions(agent, text)

    assert store.list_threads() == []
    # No valid tag matched -> the extractor produced no action at all and did
    # not raise (clean degradation). (An unrelated parent cleanup may strip the
    # stray marker from the text; that is out of scope for this assertion.)
    assert not [a for a in actions if a["type"].startswith("group_chat")]


# ---------------- 8. non-crew creator -> no room ----------------


@pytest.mark.asyncio
async def test_non_crew_creator_no_room(tmp_path):
    # Commander-level trust, but the creator's agent_type is NOT crew.
    agents = {
        "cap-1": _FakeAgent("cap-1", "captain"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
    }
    loop, store, _, _ = _build_loop(tmp_path, agents=agents)
    agent = agents["cap-1"]
    text = '[GROUP_CHAT title="Bridge" @bones-1] sync [/GROUP_CHAT]'

    _, actions = await loop._extract_and_execute_actions(agent, text)

    assert store.list_threads() == []
    assert not [a for a in actions if a["type"] == "group_chat"]
    suppressed = [a for a in actions if a["type"] == "group_chat_suppressed"]
    assert suppressed and suppressed[0]["reason"] == "not_crew"


# ---------------- 9. federation.md standing order ----------------


def test_federation_md_contains_group_chat_instruction():
    text = FEDERATION_ORDERS.read_text(encoding="utf-8")
    assert "### Group Chat" in text
    assert "[GROUP_CHAT" in text
    assert "[/GROUP_CHAT]" in text
    # Encoding Safety rule: the NEW section must stay ASCII-only (the rest of the
    # pre-existing file is out of scope for this AD).
    start = text.index("### Group Chat")
    section = text[start:text.index("### Notebook", start)]
    assert all(ord(c) < 128 for c in section)


# ---------------- 10. manual seeded ----------------


def test_group_chat_manual_seeded():
    assert GROUP_CHAT_MANUAL.exists()
    text = GROUP_CHAT_MANUAL.read_text(encoding="utf-8")
    assert "[GROUP_CHAT" in text
    assert "Meeting" in text  # covers the AD-920..923 meeting experience
    # Encoding Safety rule: ASCII-only (no chars > 0x7F).
    assert all(ord(c) < 128 for c in text)


# ---------------- 11. config default ----------------


def test_group_chat_min_rank_default_is_commander():
    assert SystemConfig().communications.group_chat_min_rank == "commander"
