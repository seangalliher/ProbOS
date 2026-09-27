"""BF-874 (#1429) crossing test: the REAL think cycle never posts a DM body.

``ProactiveCognitiveLoop._think_for_agent`` runs for real -- its gates, the action extraction
(rank from a real ``TrustNetwork``), the DM step, the BF-203 catch-all, the BF-215 empty check,
and ``_post_to_ward_room`` into a real ``WardRoomService``. The model is the only double: a
thinker whose ``handle_intent`` returns the text a model wrote (the AD-1228 ``_thinker`` shape).
Each case asserts where its secret landed: never a department or ship thread or post; a DM
thread exactly when the block could be sent. The observation must still be posted, so a case
that posts nothing at all cannot pass by accident.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry, Rank
from probos.proactive import ProactiveCognitiveLoop
from probos.substrate.identity import generate_pool_ids
from probos.substrate.registry import AgentRegistry
from probos.types import IntentResult
from probos.ward_room.service import WardRoomService

CREW = (("security_officer", "Worf", "security"), ("architect", "Number One", "science"), ("counselor", "Troi", "medical"))
SECRET = "SECRET-E1"


def _agent(agent_type: str, callsign: str, reply: str | None = None) -> SimpleNamespace:
    aid = generate_pool_ids(agent_type, agent_type, 1)[0]
    agent = SimpleNamespace(id=aid, agent_type=agent_type, pool=agent_type, callsign=callsign, is_alive=True, capabilities=[])
    if reply is not None:
        async def handle_intent(intent: Any) -> IntentResult:
            return IntentResult(intent_id=intent.id, agent_id=aid, success=True, result=reply)
        agent.handle_intent = handle_intent
    return agent


def _bodies(node: Any) -> list[str]:
    if isinstance(node, dict):
        out = [node["body"]] if isinstance(node.get("body"), str) else []
        for value in node.values():
            if isinstance(value, (dict, list)):
                out.extend(_bodies(value))
        return out
    if isinstance(node, list):
        return [b for item in node for b in _bodies(item)]
    return []


@pytest.mark.parametrize(("reply", "dm_min_rank", "dm_title"), [
    ("Status nominal. [DM @Troi] {s} [/DM]", "ensign", "[DM to @Troi]"),
    ("Status nominal. [DM @Number One] {s} [/DM]", "ensign", "[DM to @Number One]"),
    ("Status nominal. [DM @Number One] {s}", "ensign", "[DM to @Number One]"),
    ("Status nominal. [DM@Troi] {s} [/DM]", "ensign", None),
    ("Status nominal. [DM @Number One {s}", "ensign", None),
    ("Status nominal. [DM to @Troi] {s} [/DM]", "ensign", None),
    ("Status nominal. [DM @Troi] {s} [/DM]", "commander", None),
], ids=["control-single-word", "issue-multiword", "unclosed-multiword", "no-space-after-DM",
        "no-closing-bracket", "title-shape", "below-dm-min-rank"])
async def test_think_cycle_never_posts_a_dm_body(tmp_path, reply: str, dm_min_rank: str, dm_title: str | None) -> None:
    ws = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await ws.start()
    try:
        registry = AgentRegistry()
        thinker = _agent("security_officer", "Worf", reply.replace("{s}", SECRET))
        for a in (thinker, *(_agent(t, cs) for t, cs, _ in CREW[1:])):
            await registry.register(a)
        callsigns = CallsignRegistry()
        for t, cs, _ in CREW:
            callsigns.set_callsign(t, cs)
        callsigns.bind_registry(registry)
        depts = {t: d for t, _, d in CREW}
        config = SystemConfig()
        config.communications.dm_min_rank = dm_min_rank
        rt = SimpleNamespace(
            ward_room=ws, registry=registry, callsign_registry=callsigns,
            ontology=SimpleNamespace(get_agent_department=lambda t: depts.get(t)),
            config=config, trust_network=TrustNetwork(), ward_room_router=None, episodic_memory=None,
            hebbian_router=None, dispatcher=None, _records_store=None, working_memory=None,
            dm_sanity_gate=DmSanityGate(), skill_service=None, boot_camp=None, emit_event=lambda *a, **k: None,
        )
        loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
        loop.set_runtime(rt)

        await loop._think_for_agent(thinker, Rank.LIEUTENANT, 0.6)

        public: list[str] = []
        observations: list[str] = []
        dm_titles: list[str] = []
        for ch in await ws.list_channels():
            for th in await ws.list_threads(ch.id, limit=500):
                texts = [th.title, th.body, *_bodies((await ws.get_thread(th.id) or {}).get("posts", []))]
                holds = any(SECRET in t for t in texts if t)
                if ch.channel_type in ("department", "ship"):
                    observations.append(th.title)
                    if holds:
                        public.append(th.title)
                elif ch.channel_type == "dm" and holds:
                    dm_titles.append(th.title)
        assert observations == ["[Observation] Status nominal."]  # premise: the think posted
        assert public == []
        assert dm_titles == ([dm_title] if dm_title else [])
    finally:
        await ws.stop()


async def _think(tmp_path: Any, reply: str, dm_min_rank: str) -> tuple[list[str], list[str], list[str], list[str]]:
    """Run the REAL think once; return (observation titles, public places holding SECRET,
    DM titles holding SECRET, every DM title)."""
    ws = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await ws.start()
    try:
        registry = AgentRegistry()
        thinker = _agent("security_officer", "Worf", reply.replace("{s}", SECRET))
        for a in (thinker, *(_agent(t, cs) for t, cs, _ in CREW[1:])):
            await registry.register(a)
        callsigns = CallsignRegistry()
        for t, cs, _ in CREW:
            callsigns.set_callsign(t, cs)
        callsigns.bind_registry(registry)
        depts = {t: d for t, _, d in CREW}
        config = SystemConfig()
        config.communications.dm_min_rank = dm_min_rank
        rt = SimpleNamespace(
            ward_room=ws, registry=registry, callsign_registry=callsigns,
            ontology=SimpleNamespace(get_agent_department=lambda t: depts.get(t)),
            config=config, trust_network=TrustNetwork(), ward_room_router=None, episodic_memory=None,
            hebbian_router=None, dispatcher=None, _records_store=None, working_memory=None,
            dm_sanity_gate=DmSanityGate(), skill_service=None, boot_camp=None, emit_event=lambda *a, **k: None,
        )
        loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
        loop.set_runtime(rt)

        await loop._think_for_agent(thinker, Rank.LIEUTENANT, 0.6)

        observations: list[str] = []
        public: list[str] = []
        secret_dms: list[str] = []
        all_dms: list[str] = []
        for ch in await ws.list_channels():
            for th in await ws.list_threads(ch.id, limit=500):
                texts = [th.title, th.body, *_bodies((await ws.get_thread(th.id) or {}).get("posts", []))]
                holds = any(SECRET in t for t in texts if t)
                if ch.channel_type in ("department", "ship"):
                    observations.append(" ".join(th.title.split()))
                    if holds:
                        public.append(th.title)
                elif ch.channel_type == "dm":
                    all_dms.append(th.title)
                    if holds:
                        secret_dms.append(th.title)
        return observations, public, secret_dms, all_dms
    finally:
        await ws.stop()


# A-2 (review round 1, finding 1): a stray [/DM] ends a body the first closer did not, so the text
# before it is withheld. Every case must still post its observation, so posting nothing cannot pass.
@pytest.mark.parametrize(("reply", "dm_min_rank", "observation", "secret_dms", "all_dms"), [
    ("[DM @Troi] private-prefix [DM@Bad] private-nested [/DM] {s} [/DM] public-after", "ensign",
     "[Observation] public-after", [], ["[DM to @Troi]"]),
    ("Status nominal. [DM @Troi] private-prefix [DM@Bad] private-nested [/DM] {s} [/DM] public-after", "ensign",
     "[Observation] Status nominal. public-after", [], ["[DM to @Troi]"]),
    ("Status nominal. [DM @Troi] {s} [/DM][/DM]", "ensign",
     "[Observation] Status nominal.", ["[DM to @Troi]"], ["[DM to @Troi]"]),
    ("Status nominal. [DM @Troi] ok [/DM] {s} [/DM]", "ensign",
     "[Observation] Status nominal.", [], ["[DM to @Troi]"]),
    ("Status nominal. [DM @Troi] ok [/DM] [DM@Bad] no [/DM] {s} [/DM]", "ensign",
     "[Observation] Status nominal.", [], ["[DM to @Troi]"]),
    ("{s} [/DM] Status nominal.", "ensign",
     "[Observation] Status nominal.", [], []),
    ("Status nominal. [DM @Troi] ok [/DM] {s} [/DM]", "commander",
     "[Observation] Status nominal.", [], []),
], ids=["review-r1-input", "review-r1-input-with-lead", "doubled-closer", "closer-text-closer",
        "malformed-opener-after", "closer-without-opener", "below-dm-min-rank"])
async def test_think_cycle_never_posts_the_text_before_a_stray_closer(
    tmp_path, reply: str, dm_min_rank: str, observation: str, secret_dms: list[str], all_dms: list[str],
) -> None:
    observations, public, got_secret_dms, got_all_dms = await _think(tmp_path, reply, dm_min_rank)
    assert observations == [observation]  # premise: the think posted, and kept the public text
    assert public == []
    assert got_secret_dms == secret_dms
    assert got_all_dms == all_dms
