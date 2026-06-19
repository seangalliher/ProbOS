"""AD-979d slice 1: CrossAgentRecallService — FOK-gated, Hebbian top-1,
in-process governed cross-agent associative recall with SECONDHAND provenance.

BF-287 discipline: REAL collaborators at every substrate boundary — a real
``EpisodicMemory`` on ``tmp_path`` (real ONNX MiniLM embeddings), a real
``HebbianRouter`` (in-memory weights), a real ``TrustNetwork`` (in-memory Beta
records). NO MagicMock for the injected dependencies, because the whole point of
slice 1 is that the service consumes those live APIs unchanged.

Determinism: the "strong peer recall" cases store text T under the peer's shard
and query with that SAME T — the AD-981a-proven identical-text path that yields
band ``strong`` (best_similarity >= 0.7). ``own_band`` is supplied to the service
directly (it is the requesting agent's already-computed Feeling-of-Knowing band),
so the requester's vocabulary-mismatch weak band is modelled by the parameter,
not by a flaky paraphrase embedding.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from probos.cognitive.cross_agent_recall import CrossAgentRecallService, PeerRecall
from probos.cognitive.episodic import EpisodicMemory
from probos.config import MemoryConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import REL_SOCIAL, HebbianRouter
from probos.types import Episode, MemorySource

# AD-981a-proven strong-recall text: stored verbatim under a peer shard and used
# verbatim as the query -> band "strong", best_similarity >= 0.7.
QUERY = "The Captain approved the database migration on Tuesday afternoon."
UNRELATED = "Photosynthesis converts light energy into sugar inside chloroplasts."

A = "agent_a"
B = "agent_b"
C = "agent_c"


@pytest.fixture
async def episodic(tmp_path: Path):
    em = EpisodicMemory(db_path=str(tmp_path / "ad979d.db"))
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.fixture
def hebbian() -> HebbianRouter:
    return HebbianRouter()


@pytest.fixture
def trust() -> TrustNetwork:
    return TrustNetwork()


async def _seed(em: EpisodicMemory, agent_id: str, text: str) -> None:
    """Store an episode under a single agent's sovereign shard."""
    await em.store(Episode(user_input=text, agent_ids=[agent_id]))


def _service(
    episodic: EpisodicMemory,
    hebbian: HebbianRouter,
    trust: TrustNetwork,
    *,
    enabled: bool = True,
    access_policy: str = "permissive",
) -> CrossAgentRecallService:
    return CrossAgentRecallService(
        episodic_memory=episodic,
        hebbian_router=hebbian,
        trust_network=trust,
        enabled=enabled,
        access_policy=access_policy,
    )


# --------------------------------------------------------------------------
# 1. OFF gate — byte-identical default
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_returns_empty_byte_identical(episodic, hebbian, trust):
    # The config flag is OFF out of the box -> the service is a no-op.
    assert MemoryConfig().cross_agent_recall_enabled is False
    await _seed(episodic, B, QUERY)  # a corroborating peer IS present...
    svc = _service(episodic, hebbian, trust, enabled=False)
    result = await svc.escalate_recall(
        A, QUERY, "weak", peer_candidates=[B], callsigns={B: "Counselor"}
    )
    assert result == []  # ...yet a disabled service surfaces nothing.


# --------------------------------------------------------------------------
# 2/3. FOK gate — only a WEAK own band escalates
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strong_band_no_escalation(episodic, hebbian, trust):
    await _seed(episodic, B, QUERY)
    svc = _service(episodic, hebbian, trust)
    result = await svc.escalate_recall(A, QUERY, "strong", peer_candidates=[B])
    assert result == []


@pytest.mark.asyncio
async def test_none_band_no_escalation(episodic, hebbian, trust):
    await _seed(episodic, B, QUERY)
    svc = _service(episodic, hebbian, trust)
    result = await svc.escalate_recall(A, QUERY, "none", peer_candidates=[B])
    assert result == []


# --------------------------------------------------------------------------
# 4. THE acceptance case — weak own band surfaces a peer's confident recall
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weak_band_surfaces_peer_recall(episodic, hebbian, trust):
    # Peer B recorded the event verbatim (B's recall of QUERY is strong); the
    # requester A only half-remembers it (own_band="weak", supplied directly).
    await _seed(episodic, B, QUERY)
    svc = _service(episodic, hebbian, trust)
    result = await svc.escalate_recall(
        A, QUERY, "weak", peer_candidates=[B], callsigns={B: "Counselor"}
    )
    assert result, "a weak own band over a confident peer must surface a recall"
    rec = result[0]
    assert isinstance(rec, PeerRecall)
    assert rec.peer_id == B
    assert rec.peer_callsign == "Counselor"
    assert rec.source == MemorySource.SECONDHAND
    assert rec.peer_band == "strong"
    assert rec.peer_similarity >= 0.7
    assert "migration" in rec.episode.user_input


# --------------------------------------------------------------------------
# 5. Hebbian top-1 — the MOST-associated peer is chosen
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hebbian_picks_most_associated_peer(episodic, hebbian, trust):
    # Both peers could answer; A is more associated with B than C (REL_SOCIAL).
    await _seed(episodic, B, QUERY)
    await _seed(episodic, C, QUERY)
    hebbian.record_interaction(A, B, success=True, rel_type=REL_SOCIAL)  # weight > 0
    # A->C left at 0.0; pass candidates C-first to prove weight beats input order.
    svc = _service(episodic, hebbian, trust)
    result = await svc.escalate_recall(
        A, QUERY, "weak", peer_candidates=[C, B], callsigns={B: "Counselor", C: "Yeoman"}
    )
    assert result, "the most-associated peer should answer"
    assert all(r.peer_id == B for r in result)  # only top-1 (B) is queried
    assert result[0].peer_callsign == "Counselor"


# --------------------------------------------------------------------------
# 6. Governance — OWN_SHARD_ONLY refuses cross-agent escalation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_governance_own_shard_only_refuses(episodic, hebbian, trust):
    await _seed(episodic, B, QUERY)
    svc = _service(episodic, hebbian, trust, access_policy="own_shard_only")
    result = await svc.escalate_recall(A, QUERY, "weak", peer_candidates=[B])
    assert result == []


# --------------------------------------------------------------------------
# 7. A peer that is itself NOT confident contributes nothing
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peer_no_strong_recall_returns_empty(episodic, hebbian, trust):
    # B owns only an unrelated memory -> B's recall of QUERY is not "strong".
    await _seed(episodic, B, UNRELATED)
    svc = _service(episodic, hebbian, trust)
    result = await svc.escalate_recall(A, QUERY, "weak", peer_candidates=[B])
    assert result == []


# --------------------------------------------------------------------------
# 8. Self is excluded from the candidate peers
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_excluded_from_candidates(episodic, hebbian, trust):
    await _seed(episodic, A, QUERY)  # A's own shard has it, but A cannot be its own peer
    svc = _service(episodic, hebbian, trust)
    result = await svc.escalate_recall(A, QUERY, "weak", peer_candidates=[A])
    assert result == []


# --------------------------------------------------------------------------
# 9. Raw Beta trust params are attached verbatim (never a derived mean)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_raw_params_attached(episodic, hebbian, trust):
    await _seed(episodic, B, QUERY)
    trust.record_outcome(B, success=True)  # shift B's record off the (2.0, 2.0) prior
    live = trust.get_record(B)
    assert live is not None and live.alpha != 2.0  # proves we read the real record
    svc = _service(episodic, hebbian, trust)
    result = await svc.escalate_recall(A, QUERY, "weak", peer_candidates=[B])
    assert result
    assert result[0].peer_alpha == live.alpha
    assert result[0].peer_beta == live.beta


# --------------------------------------------------------------------------
# 10. A failing peer recall degrades to [] (Tier-2), never propagates
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_failure_degrades(episodic, hebbian, trust, monkeypatch, caplog):
    await _seed(episodic, B, QUERY)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated store failure")

    monkeypatch.setattr(episodic, "recall_for_agent_with_confidence", _boom)
    svc = _service(episodic, hebbian, trust)
    with caplog.at_level(logging.WARNING):
        result = await svc.escalate_recall(A, QUERY, "weak", peer_candidates=[B])
    assert result == []
    assert any("AD-979d" in r.message and "peer recall failed" in r.message for r in caplog.records)
