"""AD-979d slice 2: live wiring of ``CrossAgentRecallService`` into the sovereign
recall path (``CognitiveAgent._maybe_cross_agent_recall`` + the flag-gated
call-site block inside ``_recall_relevant_memories``).

BF-287 discipline: REAL collaborators at every substrate boundary — a real
``EpisodicMemory`` on ``tmp_path`` (real ONNX MiniLM embeddings), a real
``HebbianRouter``, a real ``TrustNetwork``, and a real ``CrossAgentRecallService``.
The requesting agent is a tiny ``_Holder`` _Fake* stub (NOT a MagicMock) — the
helper reads ONLY ``self.id`` and ``self._runtime``, so a holder carrying those
two plus a ``SimpleNamespace`` runtime of real subsystems exercises the live
code path. The peer roster / callsign registry are minimal ``_Fake*`` lookup
stubs (the spec allows a real-or-minimal registry); the peers themselves are
real-enough crew stubs (``.id`` / ``.agent_type`` / ``.sovereign_id``).

Deterministic weak band: ``EpisodicMemory(relevance_threshold=0.99,
recall_confidence_weak_floor=0.0)`` classifies any owned sub-0.99 candidate
(count > 0) as ``weak`` and identical-text peer recall as ``strong`` — the band
is tallied over the agent-owned distribution BEFORE the relevance cut
(episodic.py ``recall_for_agent_with_confidence``).

ID-space resolution under test: ``REL_SOCIAL`` Hebbian edges key on the LIVE
``agent.id``; episodic shards key on ``sovereign_id or id``. The helper ranks in
live space and passes a singleton shard id to the service, so the service's
internal ranking over a 1-element list is an identity.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.cross_agent_recall import CrossAgentRecallService
from probos.cognitive.episodic import EpisodicMemory
from probos.config import MemoryConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import REL_SOCIAL, HebbianRouter
from probos.types import Episode, MemorySource

# AD-981a-proven strong-recall text: stored verbatim under the peer shard and
# used verbatim as the query -> band "strong" (best_similarity >= 0.99).
QUERY = "The Captain approved the database migration on Tuesday afternoon."
# Topically distant from QUERY -> the requester's own band lands "weak"
# (count == 1, best_similarity well under 0.99) under the deterministic fixture.
UNRELATED = "Photosynthesis converts light energy into sugar inside chloroplasts."

# Live-id space (REL_SOCIAL edges) vs shard space (episodic agent_ids) — kept
# DISTINCT for every agent so the id-space resolution is genuinely exercised.
A_LIVE, A_SHARD = "a_live", "a_shard"
B_LIVE, B_SHARD = "b_live", "b_shard"
C_LIVE, C_SHARD = "c_live", "c_shard"


class _Peer:
    """Real-enough crew peer stub: exposes exactly the three attributes the
    helper reads off a roster agent (``id`` / ``agent_type`` / ``sovereign_id``).
    """

    def __init__(self, agent_id: str, agent_type: str, sovereign_id: str = "") -> None:
        self.id = agent_id
        self.agent_type = agent_type
        self.sovereign_id = sovereign_id


class _FakeRegistry:
    def __init__(self, agents: list) -> None:
        self._agents = list(agents)

    def all(self) -> list:
        return list(self._agents)


class _FakeCallsigns:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._map = dict(mapping)

    def get_callsign(self, agent_type: str) -> str:
        return self._map.get(agent_type, "")


class _Holder:
    """Minimal requesting-agent stand-in. The helper reads ONLY ``.id`` and
    ``._runtime``; ``_confabulation_guard`` is the single extra method needed to
    exercise the real ``_format_memory_section`` render (it is a staticmethod on
    ``CognitiveAgent``, called as ``self._confabulation_guard(...)``).
    """

    def __init__(self, agent_id: str, runtime) -> None:
        self.id = agent_id
        self._runtime = runtime

    @staticmethod
    def _confabulation_guard(authority) -> str:
        return "<guard>"


@pytest.fixture
async def weak_em(tmp_path: Path):
    # relevance_threshold=0.99 + weak_floor=0.0 => any owned sub-0.99 candidate
    # (count > 0) classifies as a weak band; identical-text recall is strong.
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad979d_s2.db"),
        relevance_threshold=0.99,
        recall_confidence_weak_floor=0.0,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


async def _seed(em: EpisodicMemory, shard_id: str, text: str) -> None:
    """Store one episode under a single agent's sovereign shard."""
    await em.store(Episode(user_input=text, agent_ids=[shard_id]))


def _runtime(
    em: EpisodicMemory,
    hebbian: HebbianRouter,
    trust: TrustNetwork,
    *,
    enabled: bool,
    peers: list,
    callsigns: dict[str, str],
):
    """Assemble a SimpleNamespace runtime of REAL subsystems + a real
    MemoryConfig + minimal roster/callsign lookups."""
    mem_cfg = MemoryConfig(cross_agent_recall_enabled=enabled)
    svc = CrossAgentRecallService(
        episodic_memory=em,
        hebbian_router=hebbian,
        trust_network=trust,
        enabled=enabled,
        access_policy="permissive",
    )
    return SimpleNamespace(
        config=SimpleNamespace(memory=mem_cfg),
        episodic_memory=em,
        hebbian_router=hebbian,
        trust_network=trust,
        registry=_FakeRegistry(peers),
        callsign_registry=_FakeCallsigns(callsigns),
        ontology=None,
        _cross_agent_recall_service=svc,
    )


# --------------------------------------------------------------------------
# 1. config default OFF
# --------------------------------------------------------------------------


def test_config_default_off() -> None:
    assert MemoryConfig().cross_agent_recall_enabled is False


# --------------------------------------------------------------------------
# 2. byte-identical OFF (helper) — flag off => [] even with a strong peer + edge
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_helper_off_returns_empty(weak_em) -> None:
    hebbian, trust = HebbianRouter(), TrustNetwork()
    await _seed(weak_em, A_SHARD, UNRELATED)  # requester own ep -> weak band
    await _seed(weak_em, B_SHARD, QUERY)  # a strong corroborating peer IS present
    hebbian.record_interaction(A_LIVE, B_LIVE, True, rel_type=REL_SOCIAL)  # positive edge
    rt = _runtime(
        weak_em, hebbian, trust,
        enabled=False,
        peers=[_Peer(B_LIVE, "counselor", B_SHARD)],
        callsigns={"counselor": "Counselor"},
    )
    holder = _Holder(A_LIVE, rt)
    out = await CognitiveAgent._maybe_cross_agent_recall(
        holder, query=QUERY, mem_id=A_SHARD, k=3
    )
    assert out == []  # ...yet a disabled flag surfaces nothing.


# --------------------------------------------------------------------------
# 3. byte-identical OFF (call-site, structural)
# --------------------------------------------------------------------------


def test_call_site_guard_is_byte_identical_off() -> None:
    src = inspect.getsource(CognitiveAgent._recall_relevant_memories)
    guard = (
        'if mem_cfg is not None and getattr(mem_cfg, '
        '"cross_agent_recall_enabled", False):'
    )
    assert guard in src
    # The flag-gated guard must precede the helper invocation — when the flag is
    # OFF the helper is never reached, so no extra query / no observation change.
    assert src.index(guard) < src.index("_maybe_cross_agent_recall")


# --------------------------------------------------------------------------
# 4. weak fires + [secondhand] render
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weak_band_fires_and_renders_secondhand(weak_em) -> None:
    hebbian, trust = HebbianRouter(), TrustNetwork()
    await _seed(weak_em, A_SHARD, UNRELATED)  # own -> weak
    await _seed(weak_em, B_SHARD, QUERY)  # peer -> strong
    hebbian.record_interaction(A_LIVE, B_LIVE, True, rel_type=REL_SOCIAL)

    # Precondition: the requester's OWN band for QUERY is weak (the slow-gap).
    _eps, own_conf = await weak_em.recall_for_agent_with_confidence(A_SHARD, QUERY)
    assert own_conf.band == "weak"

    rt = _runtime(
        weak_em, hebbian, trust,
        enabled=True,
        peers=[_Peer(B_LIVE, "counselor", B_SHARD)],
        callsigns={"counselor": "Counselor"},
    )
    holder = _Holder(A_LIVE, rt)
    out = await CognitiveAgent._maybe_cross_agent_recall(
        holder, query=QUERY, mem_id=A_SHARD, k=3
    )

    assert len(out) >= 1
    for mem in out:
        assert mem["source"] == MemorySource.SECONDHAND  # str-eq holds for .value
        assert mem["input"].startswith("Counselor recalls:")
        assert QUERY[:40] in mem["input"]  # ends with the peer's recalled text

    # Render: the per-mem header must read "[secondhand | unverified]" — which
    # appears ONLY when source renders as the value string (the static legend
    # never produces that combined form). This is the meaningful guard against
    # the Python 3.12 enum-__format__ repr leaking through.
    rendered = "\n".join(CognitiveAgent._format_memory_section(holder, [out[0]]))
    assert "[secondhand | unverified]" in rendered
    assert "Counselor" in rendered


# --------------------------------------------------------------------------
# 5. strong own band -> []
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strong_own_band_no_fire(weak_em) -> None:
    hebbian, trust = HebbianRouter(), TrustNetwork()
    await _seed(weak_em, A_SHARD, QUERY)  # own ep == QUERY -> strong own band
    await _seed(weak_em, B_SHARD, QUERY)  # peer also present
    hebbian.record_interaction(A_LIVE, B_LIVE, True, rel_type=REL_SOCIAL)

    _eps, own_conf = await weak_em.recall_for_agent_with_confidence(A_SHARD, QUERY)
    assert own_conf.band == "strong"

    rt = _runtime(
        weak_em, hebbian, trust,
        enabled=True,
        peers=[_Peer(B_LIVE, "counselor", B_SHARD)],
        callsigns={"counselor": "Counselor"},
    )
    holder = _Holder(A_LIVE, rt)
    out = await CognitiveAgent._maybe_cross_agent_recall(
        holder, query=QUERY, mem_id=A_SHARD, k=3
    )
    assert out == []  # a confident own recall needs no peer.


# --------------------------------------------------------------------------
# 6. none own band -> []
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_own_band_no_fire(weak_em) -> None:
    hebbian, trust = HebbianRouter(), TrustNetwork()
    # NO requester episode seeded -> the requester owns nothing -> band "none".
    await _seed(weak_em, B_SHARD, QUERY)  # peer present
    hebbian.record_interaction(A_LIVE, B_LIVE, True, rel_type=REL_SOCIAL)

    _eps, own_conf = await weak_em.recall_for_agent_with_confidence(A_SHARD, QUERY)
    assert own_conf.band == "none"

    rt = _runtime(
        weak_em, hebbian, trust,
        enabled=True,
        peers=[_Peer(B_LIVE, "counselor", B_SHARD)],
        callsigns={"counselor": "Counselor"},
    )
    holder = _Holder(A_LIVE, rt)
    out = await CognitiveAgent._maybe_cross_agent_recall(
        holder, query=QUERY, mem_id=A_SHARD, k=3
    )
    assert out == []  # a genuine absence must not be papered over with a guess.


# --------------------------------------------------------------------------
# 7. no social edge (weight 0) -> []
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_social_edge_no_fire(weak_em) -> None:
    hebbian, trust = HebbianRouter(), TrustNetwork()
    await _seed(weak_em, A_SHARD, UNRELATED)  # own -> weak
    await _seed(weak_em, B_SHARD, QUERY)  # strong peer present
    # NO record_interaction -> get_weight(A_LIVE, B_LIVE, REL_SOCIAL) == 0.0.

    _eps, own_conf = await weak_em.recall_for_agent_with_confidence(A_SHARD, QUERY)
    assert own_conf.band == "weak"

    rt = _runtime(
        weak_em, hebbian, trust,
        enabled=True,
        peers=[_Peer(B_LIVE, "counselor", B_SHARD)],
        callsigns={"counselor": "Counselor"},
    )
    holder = _Holder(A_LIVE, rt)
    out = await CognitiveAgent._maybe_cross_agent_recall(
        holder, query=QUERY, mem_id=A_SHARD, k=3
    )
    assert out == []  # only ask a peer this agent is genuinely associated with.


# --------------------------------------------------------------------------
# 8. service None -> []
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_none_no_fire(weak_em) -> None:
    hebbian, trust = HebbianRouter(), TrustNetwork()
    await _seed(weak_em, A_SHARD, UNRELATED)  # own -> weak
    await _seed(weak_em, B_SHARD, QUERY)  # strong peer
    hebbian.record_interaction(A_LIVE, B_LIVE, True, rel_type=REL_SOCIAL)

    rt = _runtime(
        weak_em, hebbian, trust,
        enabled=True,
        peers=[_Peer(B_LIVE, "counselor", B_SHARD)],
        callsigns={"counselor": "Counselor"},
    )
    rt._cross_agent_recall_service = None  # service unavailable
    holder = _Holder(A_LIVE, rt)
    out = await CognitiveAgent._maybe_cross_agent_recall(
        holder, query=QUERY, mem_id=A_SHARD, k=3
    )
    assert out == []


# --------------------------------------------------------------------------
# 9. most-associated peer chosen (two strong peers, only A->B edge)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_most_associated_peer_chosen(weak_em) -> None:
    hebbian, trust = HebbianRouter(), TrustNetwork()
    await _seed(weak_em, A_SHARD, UNRELATED)  # own -> weak
    await _seed(weak_em, B_SHARD, QUERY)  # B: strong recall
    await _seed(weak_em, C_SHARD, QUERY)  # C: equally strong recall
    # ONLY an A->B social edge — C has no association with A.
    hebbian.record_interaction(A_LIVE, B_LIVE, True, rel_type=REL_SOCIAL)

    # C is listed FIRST in the roster: selection must come from the Hebbian
    # ranking (live-id space), not roster order.
    rt = _runtime(
        weak_em, hebbian, trust,
        enabled=True,
        peers=[
            _Peer(C_LIVE, "scout", C_SHARD),
            _Peer(B_LIVE, "counselor", B_SHARD),
        ],
        callsigns={"counselor": "Counselor", "scout": "Scout"},
    )
    holder = _Holder(A_LIVE, rt)
    out = await CognitiveAgent._maybe_cross_agent_recall(
        holder, query=QUERY, mem_id=A_SHARD, k=3
    )

    assert len(out) >= 1
    assert all(m["input"].startswith("Counselor recalls:") for m in out)
    assert not any("Scout" in m["input"] for m in out)  # C was never queried.
