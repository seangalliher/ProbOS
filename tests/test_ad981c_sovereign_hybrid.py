"""AD-981c (Oracle-recall epic, #974): wire AD-979c hybrid retrieval onto the
SOVEREIGN recall path — shard-aware.

The AD-979c dense+sparse RRF fusion was wired only onto the GLOBAL
``recall_with_confidence``. The crew's live per-message recall goes through the
sovereign ``recall_for_agent_with_confidence`` (agent-scoped, AD-397 isolation),
which ignored the already-enabled ``hybrid_recall_enabled`` flag and stayed
dense-only. So a memory an agent owns but encoded under different vocabulary
than the query (the gold-standard cross-session "schnauzer/dog" miss) was never
surfaced. AD-981c adds the gated fusion tail to the sovereign path.

The load-bearing correctness point: ``keyword_search`` runs over the GLOBAL FTS
index and ``get_by_ids`` is not shard-scoped, so the sovereign fusion MUST
post-filter every fused episode to ones the agent owns
(``agent_id in episode.agent_ids``) — otherwise another agent's keyword-matched
memory leaks into this agent's recall.

BF-287 discipline: a REAL ``EpisodicMemory`` on ``tmp_path`` (real ONNX MiniLM
embeddings + real FTS5 sidecar), NOT MagicMock. Embedding-fragile numbers are
avoided — the gate is asserted as the differential between the flag-on and
flag-off fixtures over the same seeded content.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.types import Episode


# ---------------------------------------------------------------------------
# Seed content. The target is an ENGINEERING report with a distinctive keyword
# ("schnauzer") buried as an aside, so the cosine axis (mean-pooled, dominated
# by engineering vocabulary) ranks it far below the bare-keyword query while the
# lexical axis matches it exactly — the vocabulary-mismatch gap AD-981c closes.
# ---------------------------------------------------------------------------
_TARGET_TEXT = (
    "Engineering night-watch report: the secondary plasma manifold was "
    "recalibrated to within tolerance, coolant pressure held nominal across all "
    "three decks, and the duty technician logged that the workshop's resident "
    "schnauzer dozed quietly beside the diagnostic console."
)
_FILLER_TEXTS = (
    "Engineering night-watch report: the primary EPS conduit passed its pressure "
    "test and the warp plasma flow stayed within the green band all shift.",
    "Maintenance summary: the starboard coolant pump bearings were greased and "
    "the deck-two atmospheric scrubbers cycled clean.",
)
# The gold-standard recall phrasing: a natural "do you remember the …" query
# whose mean-pooled embedding is diluted enough to fall below the sovereign
# relaxed return bar (dense-sub-threshold, ~0.19 < 0.25), yet whose distinctive
# "schnauzer" token the FTS5 lexical axis matches exactly. This is the
# vocabulary-mismatch gap AD-981c closes (the cross-session dog/schnauzer miss).
_KEYWORD_QUERY = "do you remember the schnauzer"
_OWNER = "yeoman"


async def _seed_schnauzer(em: EpisodicMemory, owner: str = _OWNER) -> None:
    """Seed the buried-keyword target plus unrelated owned filler episodes."""
    await em.store(Episode(user_input=_TARGET_TEXT, agent_ids=[owner]))
    for text in _FILLER_TEXTS:
        await em.store(Episode(user_input=text, agent_ids=[owner]))


# ---------------------------------------------------------------------------
# Fixtures — real EpisodicMemory on tmp_path (BF-287).
# ---------------------------------------------------------------------------
@pytest.fixture
async def hybrid_memory(tmp_path: Path):
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad981c_hybrid.db"),
        hybrid_recall_enabled=True,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.fixture
async def dense_memory(tmp_path: Path):
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad981c_dense.db"),
        hybrid_recall_enabled=False,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.fixture
async def hybrid_fok_memory(tmp_path: Path):
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad981c_hybrid_fok.db"),
        hybrid_recall_enabled=True,
        recall_fok_logging_enabled=True,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.fixture
async def dense_fok_memory(tmp_path: Path):
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad981c_dense_fok.db"),
        hybrid_recall_enabled=False,
        recall_fok_logging_enabled=True,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


# ===========================================================================
# Headline: the gate. Owned keyword-shared but dense-sub-threshold episode is
# surfaced when hybrid_recall_enabled=True and NOT when False.
# ===========================================================================
@pytest.mark.asyncio
async def test_hybrid_on_surfaces_owned_keyword_episode(hybrid_memory):
    await _seed_schnauzer(hybrid_memory)
    episodes, _conf = await hybrid_memory.recall_for_agent_with_confidence(
        _OWNER, _KEYWORD_QUERY, k=5
    )
    assert any("schnauzer" in e.user_input for e in episodes), (
        "the sparse axis should surface the agent's own keyword-matched episode "
        "the dense axis missed (the cross-session dog/schnauzer recall)"
    )


@pytest.mark.asyncio
async def test_hybrid_off_does_not_surface_keyword_episode(dense_memory):
    # Same content + query, hybrid OFF: the buried-keyword episode is dense-
    # sub-threshold, so dense-only recall must NOT surface it. Together with the
    # ON case this proves both the fusion AND the gate.
    await _seed_schnauzer(dense_memory)
    episodes, conf = await dense_memory.recall_for_agent_with_confidence(
        _OWNER, _KEYWORD_QUERY, k=5
    )
    assert not any("schnauzer" in e.user_input for e in episodes), (
        "dense-only recall must not surface the vocabulary-mismatch episode"
    )
    # Precondition the headline gate depends on: the target really is below the
    # sovereign relaxed return bar on the dense axis (not merely crowded out).
    agent_threshold = min(
        dense_memory.relevance_threshold, dense_memory._agent_recall_threshold
    )
    assert conf.best_similarity < agent_threshold, (
        f"expected dense-sub-threshold owned best_sim<{agent_threshold}, "
        f"got {conf.best_similarity}"
    )


# ===========================================================================
# SOVEREIGN-LEAK GUARD (load-bearing): a non-owned keyword match must NOT leak
# into the agent's hybrid recall.
# ===========================================================================
@pytest.mark.asyncio
async def test_sovereign_leak_guard_excludes_non_owned_keyword_match(hybrid_memory):
    counselor_text = (
        "Counselor's reflection: the Captain lit up describing his giant "
        "schnauzer, a clear source of comfort during a hard week."
    )
    await hybrid_memory.store(
        Episode(user_input=counselor_text, agent_ids=["counselor"])
    )
    # The yeoman owns an unrelated memory (a populated sovereign shard).
    await hybrid_memory.store(
        Episode(
            user_input=(
                "Yeoman's log: the duty roster for gamma shift was posted and "
                "acknowledged by all stations."
            ),
            agent_ids=[_OWNER],
        )
    )
    # The yeoman queries the keyword the COUNSELOR's episode matches.
    yeoman_eps, _ = await hybrid_memory.recall_for_agent_with_confidence(
        _OWNER, _KEYWORD_QUERY, k=5
    )
    assert not any("schnauzer" in e.user_input for e in yeoman_eps), (
        "sovereign-leak guard: another agent's keyword-matched episode must NOT "
        "appear in this agent's hybrid recall"
    )
    assert all(_OWNER in e.agent_ids for e in yeoman_eps), (
        "every episode in the agent's recall must belong to the agent's shard"
    )
    # Sanity: the counselor (the rightful owner) DOES surface it under hybrid,
    # proving the FTS axis would have matched it absent the ownership guard.
    counselor_eps, _ = await hybrid_memory.recall_for_agent_with_confidence(
        "counselor", _KEYWORD_QUERY, k=5
    )
    assert any("schnauzer" in e.user_input for e in counselor_eps), (
        "the owning agent should still recall its own keyword-matched memory"
    )


# ===========================================================================
# FoK band unchanged: fusion changes WHICH episodes return, not the AD-981a
# agent-scoped Feeling-of-Knowing signal (still the DENSE distribution).
# ===========================================================================
@pytest.mark.asyncio
async def test_fok_band_and_best_sim_unchanged_by_fusion(hybrid_memory, dense_memory):
    await _seed_schnauzer(hybrid_memory)
    await _seed_schnauzer(dense_memory)
    _on_eps, on_conf = await hybrid_memory.recall_for_agent_with_confidence(
        _OWNER, _KEYWORD_QUERY, k=5
    )
    _off_eps, off_conf = await dense_memory.recall_for_agent_with_confidence(
        _OWNER, _KEYWORD_QUERY, k=5
    )
    assert on_conf.band == off_conf.band
    assert on_conf.best_similarity == off_conf.best_similarity
    assert on_conf.candidate_count == off_conf.candidate_count


@pytest.mark.asyncio
async def test_logged_fok_band_equals_dense_value(
    hybrid_fok_memory, dense_fok_memory, caplog
):
    await _seed_schnauzer(hybrid_fok_memory)
    await _seed_schnauzer(dense_fok_memory)
    with caplog.at_level(logging.INFO, logger="probos.cognitive.episodic"):
        await hybrid_fok_memory.recall_for_agent_with_confidence(
            _OWNER, _KEYWORD_QUERY, k=5
        )
        hybrid_logs = [
            r.getMessage() for r in caplog.records if "AD-981a recall FoK" in r.message
        ]
        caplog.clear()
        await dense_fok_memory.recall_for_agent_with_confidence(
            _OWNER, _KEYWORD_QUERY, k=5
        )
        dense_logs = [
            r.getMessage() for r in caplog.records if "AD-981a recall FoK" in r.message
        ]
    assert hybrid_logs and dense_logs, "both fixtures should emit the FoK band line"

    def _band_and_sim(line: str) -> tuple[str, str]:
        band = line.split("band=", 1)[1].split(" ", 1)[0]
        best = line.split("best_sim=", 1)[1].split(" ", 1)[0]
        return band, best

    assert _band_and_sim(hybrid_logs[0]) == _band_and_sim(dense_logs[0]), (
        "the logged AD-981a band/best_sim must be the dense value regardless of "
        "hybrid fusion"
    )


# ===========================================================================
# Default-off byte-identical: hybrid OFF returns exactly the dense-only set.
# ===========================================================================
@pytest.mark.asyncio
async def test_default_off_is_dense_only_and_shim_consistent(dense_memory):
    await _seed_schnauzer(dense_memory)
    # The shim and the confidence method agree (single source of truth).
    shim_eps = await dense_memory.recall_for_agent(_OWNER, _KEYWORD_QUERY, k=5)
    core_eps, _conf = await dense_memory.recall_for_agent_with_confidence(
        _OWNER, _KEYWORD_QUERY, k=5
    )
    assert [e.id for e in shim_eps] == [e.id for e in core_eps]
    # And the keyword-only (dense-sub-threshold) episode is excluded — proof the
    # OFF path is pure dense (byte-identical to pre-AD-981c recall_for_agent).
    assert not any("schnauzer" in e.user_input for e in shim_eps)


@pytest.mark.asyncio
async def test_off_strong_self_query_returns_owned_episode(dense_memory):
    # A positive dense-path control: a strong self-query still returns the owned
    # episode in dense order with the flag off.
    text = "The Captain approved the database migration on Tuesday afternoon."
    await dense_memory.store(Episode(user_input=text, agent_ids=[_OWNER]))
    episodes = await dense_memory.recall_for_agent(_OWNER, text, k=5)
    assert any("migration" in e.user_input for e in episodes)


# ===========================================================================
# Honest-degrade: an empty/failed sparse axis returns the dense list unchanged.
# ===========================================================================
@pytest.mark.asyncio
async def test_honest_degrade_failed_sparse_axis_returns_dense(
    hybrid_memory, dense_memory, monkeypatch
):
    await _seed_schnauzer(hybrid_memory)
    await _seed_schnauzer(dense_memory)

    async def _raising_keyword_search(query: str, k: int = 10):
        raise RuntimeError("FTS sidecar unavailable")

    monkeypatch.setattr(hybrid_memory, "keyword_search", _raising_keyword_search)
    degraded, _ = await hybrid_memory.recall_for_agent_with_confidence(
        _OWNER, _KEYWORD_QUERY, k=5
    )
    dense_ref, _ = await dense_memory.recall_for_agent_with_confidence(
        _OWNER, _KEYWORD_QUERY, k=5
    )
    assert [e.id for e in degraded] == [e.id for e in dense_ref], (
        "a failed sparse axis must fall back to the dense recall unchanged"
    )


@pytest.mark.asyncio
async def test_honest_degrade_empty_sparse_axis_returns_dense(
    hybrid_memory, dense_memory, monkeypatch
):
    await _seed_schnauzer(hybrid_memory)
    await _seed_schnauzer(dense_memory)

    async def _empty_keyword_search(query: str, k: int = 10):
        return []

    monkeypatch.setattr(hybrid_memory, "keyword_search", _empty_keyword_search)
    degraded, _ = await hybrid_memory.recall_for_agent_with_confidence(
        _OWNER, _KEYWORD_QUERY, k=5
    )
    dense_ref, _ = await dense_memory.recall_for_agent_with_confidence(
        _OWNER, _KEYWORD_QUERY, k=5
    )
    assert [e.id for e in degraded] == [e.id for e in dense_ref]


@pytest.mark.asyncio
async def test_honest_degrade_no_usable_query_tokens_returns_dense(
    hybrid_memory, dense_memory
):
    # A query with no FTS-usable tokens (all single-char) -> fts_or_query == ""
    # -> the sparse axis is skipped and the dense list is returned unchanged.
    await _seed_schnauzer(hybrid_memory)
    await _seed_schnauzer(dense_memory)
    degraded, _ = await hybrid_memory.recall_for_agent_with_confidence(
        _OWNER, "a b c", k=5
    )
    dense_ref, _ = await dense_memory.recall_for_agent_with_confidence(
        _OWNER, "a b c", k=5
    )
    assert [e.id for e in degraded] == [e.id for e in dense_ref]
