"""AD-979a (Oracle recall epic, #903): recall-confidence Feeling-of-Knowing signal.

``EpisodicMemory.recall()`` computed ``similarity = 1.0 - distance`` for every
candidate and then discarded it (a silent ``continue`` below
``relevance_threshold``). So a caller could not tell "I have NOTHING on this"
(fast-absence) from "the best match was 0.65, just under the bar" (the invisible
miss / slow-gap). AD-979a carries that distribution out as a
``RecallConfidence`` signal (Hart 1965 Feeling-of-Knowing; Koriat 1993
accessibility hypothesis — the band is *derived from* the retrieved similarity
distribution, never self-reported).

Two layers, both tested:
  * ``classify_recall_confidence`` — the pure band classifier (no I/O), all
    three bands + the fast-absence / slow-gap split, exhaustively.
  * ``recall_with_confidence`` — the real recall path now returns
    ``(episodes, RecallConfidence)``; ``recall()`` is a thin byte-identical
    shim over it.

BF-287 discipline: a REAL ``EpisodicMemory`` on ``tmp_path`` with real ONNX
MiniLM embeddings (NOT MagicMock). Band assertions on the integration path are
made *consistent with the classifier* rather than hard-coding an
embedding-fragile number, so the test is robust to embedding drift.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from probos.cognitive.episodic import (
    EpisodicMemory,
    RecallConfidence,
    classify_recall_confidence,
)
from probos.types import Episode


# ============================ 1. pure classifier ============================

_REL = 0.7
_WEAK = 0.45


def _band(best: float, count: int) -> str:
    return classify_recall_confidence(
        best, count, relevance_threshold=_REL, weak_floor=_WEAK
    )


def test_classify_fast_absence_zero_candidates_is_none():
    # No candidates at all -> "I have nothing on this".
    assert _band(0.0, 0) == "none"
    # Even a (degenerate) high best with zero count is none — count gates first.
    assert _band(0.99, 0) == "none"


def test_classify_strong_at_and_above_relevance():
    assert _band(0.70, 5) == "strong"
    assert _band(0.95, 3) == "strong"


def test_classify_weak_band_is_the_invisible_miss():
    # Candidates present, best in [weak_floor, relevance) -> the invisible miss.
    assert _band(0.45, 5) == "weak"
    assert _band(0.69, 5) == "weak"
    assert _band(0.60, 1) == "weak"


def test_classify_slow_gap_below_weak_floor_is_none():
    # Candidates present but all too distant to mean anything -> none.
    assert _band(0.44, 5) == "none"
    assert _band(0.10, 9) == "none"


def test_classify_boundaries_are_inclusive_lower():
    # Exactly at the bar = strong; exactly at the floor = weak (>= semantics).
    assert _band(_REL, 1) == "strong"
    assert _band(_WEAK, 1) == "weak"
    # Just under each boundary drops a band.
    assert _band(_REL - 0.001, 1) == "weak"
    assert _band(_WEAK - 0.001, 1) == "none"


def test_classify_respects_custom_thresholds():
    # The classifier is parameterized — different knobs move the bands.
    assert classify_recall_confidence(
        0.5, 3, relevance_threshold=0.4, weak_floor=0.2
    ) == "strong"
    assert classify_recall_confidence(
        0.5, 3, relevance_threshold=0.9, weak_floor=0.6
    ) == "none"


# ===================== 2. recall_with_confidence integration =====================


@pytest.fixture
async def memory(tmp_path: Path):
    em = EpisodicMemory(db_path=str(tmp_path / "ad979a.db"))
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_empty_store_is_fast_absence(memory):
    # No episodes stored -> count==0 -> fast-absence "none", zero candidates,
    # no episodes. This is the honest "I have no memory of this".
    episodes, conf = await memory.recall_with_confidence("anything at all", k=5)
    assert episodes == []
    assert isinstance(conf, RecallConfidence)
    assert conf.band == "none"
    assert conf.candidate_count == 0
    assert conf.best_similarity == 0.0


@pytest.mark.asyncio
async def test_empty_query_returns_none_signal(memory):
    await memory.store(Episode(user_input="The Captain approved the migration."))
    episodes, conf = await memory.recall_with_confidence("   ", k=5)
    assert episodes == []
    assert conf.band == "none"
    assert conf.candidate_count == 0


@pytest.mark.asyncio
async def test_strong_recall_on_self_query(memory):
    # Storing a sentence and querying (almost) the same text yields a high best
    # similarity -> "strong" band, with the episode returned.
    text = "The Captain approved the database migration on Tuesday afternoon."
    await memory.store(Episode(user_input=text))
    episodes, conf = await memory.recall_with_confidence(text, k=5)
    assert conf.band == "strong"
    assert conf.candidate_count >= 1
    assert conf.best_similarity >= 0.7
    assert episodes, "a strong recall should return the matching episode"
    assert any("migration" in e.user_input for e in episodes)


@pytest.mark.asyncio
async def test_signal_is_consistent_with_classifier(memory):
    # Whatever the real embeddings produce, the surfaced band MUST equal the
    # pure classifier applied to the surfaced (best_similarity, candidate_count)
    # at the store's own thresholds. This proves the wiring without hard-coding
    # an embedding-fragile band.
    await memory.store(Episode(user_input="Photosynthesis converts light to sugar."))
    await memory.store(Episode(user_input="The reactor core temperature is nominal."))
    for q in ("quantum entanglement of distant particles", "reactor core temperature"):
        _episodes, conf = await memory.recall_with_confidence(q, k=3)
        expected = classify_recall_confidence(
            conf.best_similarity,
            conf.candidate_count,
            relevance_threshold=memory.relevance_threshold,
            weak_floor=memory._recall_confidence_weak_floor,
        )
        assert conf.band == expected


@pytest.mark.asyncio
async def test_recall_is_byte_identical_shim(memory):
    # recall() must return exactly the episode list recall_with_confidence does.
    for t in (
        "Engineering reported a coolant leak in section seven.",
        "Counselor logged a wellness check for the night shift.",
        "The away team returned with mineral samples.",
    ):
        await memory.store(Episode(user_input=t))
    query = "coolant leak in engineering"
    via_recall = await memory.recall(query, k=3)
    via_conf, _signal = await memory.recall_with_confidence(query, k=3)
    assert [e.id for e in via_recall] == [e.id for e in via_conf]


@pytest.mark.asyncio
async def test_query_is_truncated_in_signal(memory):
    await memory.store(Episode(user_input="A short memory."))
    long_q = "x" * 500
    _episodes, conf = await memory.recall_with_confidence(long_q, k=1)
    assert len(conf.query) <= 200


@pytest.mark.asyncio
async def test_populated_store_unrelated_query_distinguishes_slow_gap(memory):
    # A populated store always returns candidates for any query (slow-gap:
    # candidate_count > 0), so an unrelated query is NOT fast-absence even when
    # the band is "none" — that distinction is the whole point of AD-979a.
    await memory.store(Episode(user_input="The shuttle bay doors are sealed."))
    _episodes, conf = await memory.recall_with_confidence(
        "medieval tapestry weaving techniques", k=3
    )
    assert conf.candidate_count >= 1  # candidates existed (not fast-absence)
    if conf.band == "none":
        # then it's a slow-gap: below the floor despite candidates present
        assert conf.best_similarity < memory._recall_confidence_weak_floor
