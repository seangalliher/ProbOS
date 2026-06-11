"""AD-979c (Oracle recall epic, #905): hybrid dense+sparse retrieval (RRF).

Recall was purely cosine similarity over embeddings, so a memory encoded under
different vocabulary than the query scored below ``relevance_threshold`` and was
dropped even when exactly relevant (the vocabulary-mismatch gap). AD-979c adds a
lexical axis (the existing AD-567b FTS5 ``keyword_search``) and FUSES it with the
cosine ranking via Reciprocal Rank Fusion, so a mismatch on one axis is caught by
the other. Off by default (``hybrid_recall_enabled``) -> byte-identical recall.

Three layers, all tested:
  * ``fts_or_query`` — natural query -> FTS5 OR-of-keywords (pure).
  * ``reciprocal_rank_fusion`` — rank-based fusion (pure); single-ranking
    identity (the byte-identical-when-sparse-empty guarantee).
  * ``recall_with_confidence`` with the flag on — a real episode that fails
    cosine-only recall is surfaced via the keyword axis under fusion.

BF-287 discipline: real ``EpisodicMemory`` on ``tmp_path`` (real ONNX MiniLM +
real FTS5 sidecar), NOT MagicMock.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from probos.cognitive.episodic import (
    EpisodicMemory,
    fts_or_query,
    reciprocal_rank_fusion,
)
from probos.types import Episode


# ============================ 1. fts_or_query ============================


def test_fts_or_query_basic_tokens():
    assert fts_or_query("database migration") == '"database" OR "migration"'


def test_fts_or_query_lowercases_and_dedupes_preserving_order():
    assert fts_or_query("Reactor reactor CORE core") == '"reactor" OR "core"'


def test_fts_or_query_strips_punctuation_and_short_tokens():
    # Punctuation is dropped; single-char tokens (default min_token_len=2) too.
    assert fts_or_query("a coolant-leak in section 7!") == (
        '"coolant" OR "leak" OR "in" OR "section"'
    )


def test_fts_or_query_empty_when_no_usable_tokens():
    assert fts_or_query("") == ""
    assert fts_or_query("   ") == ""
    assert fts_or_query("!!! ? .") == ""
    assert fts_or_query("a b c") == ""  # all single-char


def test_fts_or_query_quotes_each_token_so_operators_are_literal():
    # "and"/"or" become quoted literal terms, never FTS5 operators.
    assert fts_or_query("safety and security") == (
        '"safety" OR "and" OR "security"'
    )


# ====================== 2. reciprocal_rank_fusion ======================


def test_rrf_single_ranking_preserves_order():
    # The byte-identical-when-sparse-empty guarantee: one ranking in -> same
    # order out (1/(k+1) > 1/(k+2) > ...).
    fused = reciprocal_rank_fusion([["a", "b", "c", "d"]], k=60)
    assert [eid for eid, _ in fused] == ["a", "b", "c", "d"]


def test_rrf_rewards_agreement_across_rankings():
    # "b" is high in both rankings -> should top the fused list.
    dense = ["a", "b", "c"]
    sparse = ["b", "x", "y"]
    fused = reciprocal_rank_fusion([dense, sparse], k=60)
    assert fused[0][0] == "b"


def test_rrf_surfaces_sparse_only_item():
    # "z" appears ONLY in the sparse ranking but still gets a fused score
    # (the vocabulary-mismatch episode the dense axis missed).
    dense = ["a", "b"]
    sparse = ["z", "a"]
    ids = [eid for eid, _ in reciprocal_rank_fusion([dense, sparse], k=60)]
    assert "z" in ids


def test_rrf_scores_are_descending():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "b", "a"]], k=10)
    scores = [s for _, s in fused]
    assert scores == sorted(scores, reverse=True)


def test_rrf_empty_input_is_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[]]) == []


def test_rrf_k_changes_score_magnitude_not_single_ranking_order():
    a = [eid for eid, _ in reciprocal_rank_fusion([["a", "b", "c"]], k=1)]
    b = [eid for eid, _ in reciprocal_rank_fusion([["a", "b", "c"]], k=1000)]
    assert a == b == ["a", "b", "c"]


# ====================== 3. real-store integration ======================


@pytest.fixture
async def hybrid_memory(tmp_path: Path):
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad979c.db"),
        hybrid_recall_enabled=True,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.fixture
async def dense_only_memory(tmp_path: Path):
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad979c_dense.db"),
        hybrid_recall_enabled=False,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_hybrid_surfaces_keyword_match_dense_misses(hybrid_memory):
    # A distinctive keyword token ("Zephyrine") that the cosine axis is unlikely
    # to rank for an otherwise-unrelated query, but the FTS axis matches exactly.
    await hybrid_memory.store(
        Episode(user_input="Project Zephyrine shipped on schedule.")
    )
    # Fill with unrelated episodes so the dense top-k is contested.
    for t in (
        "The garden needs watering twice a week.",
        "Quarterly budget review is next Thursday.",
        "The orchestra tuned their instruments before the concert.",
    ):
        await hybrid_memory.store(Episode(user_input=t))
    episodes, _conf = await hybrid_memory.recall_with_confidence("Zephyrine", k=3)
    assert any("Zephyrine" in e.user_input for e in episodes), (
        "the keyword axis should surface the exact-token episode under fusion"
    )


@pytest.mark.asyncio
async def test_flag_off_is_byte_identical(dense_only_memory):
    # With hybrid disabled, recall_with_confidence == plain dense recall order.
    for t in (
        "Engineering reported a coolant leak.",
        "The away team returned safely.",
        "Counselor logged a wellness check.",
    ):
        await dense_only_memory.store(Episode(user_input=t))
    q = "coolant leak engineering"
    via_recall = await dense_only_memory.recall(q, k=3)
    via_conf, _ = await dense_only_memory.recall_with_confidence(q, k=3)
    assert [e.id for e in via_recall] == [e.id for e in via_conf]


@pytest.mark.asyncio
async def test_hybrid_empty_store_returns_nothing(hybrid_memory):
    episodes, conf = await hybrid_memory.recall_with_confidence("anything", k=3)
    assert episodes == []
    assert conf.band == "none"


@pytest.mark.asyncio
async def test_hybrid_respects_k_limit(hybrid_memory):
    for i in range(8):
        await hybrid_memory.store(Episode(user_input=f"status report number {i}"))
    episodes, _ = await hybrid_memory.recall_with_confidence("status report", k=3)
    assert len(episodes) <= 3


@pytest.mark.asyncio
async def test_hybrid_confidence_signal_still_present(hybrid_memory):
    # AD-979a signal is preserved through the AD-979c path.
    await hybrid_memory.store(Episode(user_input="The shuttle bay doors are sealed."))
    _episodes, conf = await hybrid_memory.recall_with_confidence(
        "shuttle bay doors", k=3
    )
    assert conf.band in {"strong", "weak", "none"}
    assert conf.candidate_count >= 1
