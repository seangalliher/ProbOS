"""AD-871: Provenance-aware memory envelope.

Verifies the graded-belief fields on Episode (source_type / confidence /
verification_count / contradicted_by), the per-source confidence mapping,
the store/recall round-trip through ChromaDB metadata, and the honest-degrade
behavior for legacy (pre-AD-871) episodes that lack the new metadata keys.

Uses a REAL EpisodicMemory fixture (tmp_path SQLite/Chroma) — NOT MagicMock —
because these code paths cross the substrate storage boundary (BF-287 lesson).
"""

import time

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.types import (
    DEFAULT_PROVENANCE_CONFIDENCE,
    DEFAULT_SOURCE_TYPE,
    SOURCE_TO_SOURCE_TYPE,
    SOURCE_TYPE_CONFIDENCE,
    Episode,
    mark_contradicted,
    resolve_provenance,
)


# ---------------------------------------------------------------------------
# Real EpisodicMemory fixture (tmp_path-backed, no MagicMock)
# ---------------------------------------------------------------------------


@pytest.fixture
async def mem(tmp_path):
    m = EpisodicMemory(
        db_path=tmp_path / "episodes.db",
        max_episodes=100,
        relevance_threshold=0.3,
    )
    await m.start()
    yield m
    await m.stop()


# ---------------------------------------------------------------------------
# (a) Field defaults
# ---------------------------------------------------------------------------


def test_episode_provenance_fields_default_to_neutral():
    """A fresh Episode carries neutral provenance: empty source_type, full
    confidence, zero verifications, no contradictions."""
    ep = Episode(user_input="hello")
    assert ep.source_type == ""
    assert ep.confidence == 1.0
    assert ep.verification_count == 0
    assert ep.contradicted_by == []


# ---------------------------------------------------------------------------
# (b) store -> recall round-trip of all four fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_recall_round_trips_all_provenance_fields(mem):
    ep = Episode(
        timestamp=time.time(),
        user_input="round trip provenance",
        outcomes=[{"intent": "list_directory", "success": True}],
        source_type="agent_inference",
        confidence=0.5,
        verification_count=3,
        contradicted_by=["ep-x", "ep-y"],
    )
    await mem.store(ep)

    results = await mem.recall_by_intent("list_directory")
    assert len(results) == 1
    got = results[0]
    assert got.source_type == "agent_inference"
    assert got.confidence == 0.5
    assert got.verification_count == 3
    assert got.contradicted_by == ["ep-x", "ep-y"]


# ---------------------------------------------------------------------------
# (c) source -> source_type back-fill for a legacy "direct" episode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_direct_source_backfills_source_type_on_store(mem):
    """An episode with the default source="direct" and no explicit source_type
    gets source_type back-filled to "observation" at store time, while its
    confidence is preserved at 1.0 (never downgraded)."""
    ep = Episode(
        timestamp=time.time(),
        user_input="legacy direct backfill",
        outcomes=[{"intent": "read_file", "success": True}],
    )
    assert ep.source == "direct"
    assert ep.source_type == ""

    await mem.store(ep)
    results = await mem.recall_by_intent("read_file")
    assert len(results) == 1
    got = results[0]
    assert got.source_type == "observation"
    assert got.confidence == 1.0


# ---------------------------------------------------------------------------
# (d) confidence-by-source-type mapping
# ---------------------------------------------------------------------------


def test_resolve_provenance_derives_confidence_from_graded_source_type():
    """When a graded source_type is supplied and confidence is left at the
    neutral default, confidence is derived from SOURCE_TYPE_CONFIDENCE."""
    assert resolve_provenance("direct", "agent_inference", 1.0) == ("agent_inference", 0.5)
    assert resolve_provenance("direct", "observation", 1.0) == ("observation", 0.8)
    assert resolve_provenance("direct", "user_statement", 1.0) == ("user_statement", 1.0)


def test_resolve_provenance_preserves_caller_confidence_when_non_default():
    """A caller-provided non-default confidence is authoritative and is never
    overwritten by the source_type map."""
    assert resolve_provenance("direct", "user_statement", 0.4) == ("user_statement", 0.4)
    assert resolve_provenance("direct", "observation", 0.9) == ("observation", 0.9)


def test_resolve_provenance_backfills_source_type_and_keeps_legacy_confidence():
    """A legacy episode (empty source_type) is back-filled by source, and its
    confidence is preserved (not derived) — store raw, never downgrade."""
    assert resolve_provenance("direct", "", 1.0) == ("observation", 1.0)
    assert resolve_provenance("secondhand", "", 1.0) == ("agent_inference", 1.0)
    assert resolve_provenance("ship_records", "", 1.0) == ("external", 1.0)
    # Unknown legacy source falls back to the default source_type.
    assert resolve_provenance("mystery", "", 1.0) == (DEFAULT_SOURCE_TYPE, 1.0)


def test_source_type_maps_are_internally_consistent():
    """Every back-fill target source_type is a key in the confidence map, and
    the documented default confidence matches the constant."""
    for source_type in SOURCE_TO_SOURCE_TYPE.values():
        assert source_type in SOURCE_TYPE_CONFIDENCE
    assert DEFAULT_PROVENANCE_CONFIDENCE == 1.0


@pytest.mark.asyncio
async def test_graded_source_type_confidence_round_trips_through_store(mem):
    """Storing an episode with an explicit graded source_type (and default
    confidence) persists the derived confidence through recall."""
    ep = Episode(
        timestamp=time.time(),
        user_input="graded source type confidence",
        outcomes=[{"intent": "search_files", "success": True}],
        source_type="observation",
    )
    await mem.store(ep)
    results = await mem.recall_by_intent("search_files")
    assert len(results) == 1
    assert results[0].source_type == "observation"
    assert results[0].confidence == 0.8


# ---------------------------------------------------------------------------
# (e) contradicted_by population via mark_contradicted helper
# ---------------------------------------------------------------------------


def test_mark_contradicted_appends_and_is_idempotent():
    ep = Episode(user_input="contradiction target")
    assert ep.contradicted_by == []

    ep2 = mark_contradicted(ep, "ep-bad")
    assert ep2 is not ep  # frozen-safe copy
    assert ep2.contradicted_by == ["ep-bad"]
    # original is untouched (frozen, immutable)
    assert ep.contradicted_by == []

    ep3 = mark_contradicted(ep2, "ep-worse")
    assert ep3.contradicted_by == ["ep-bad", "ep-worse"]

    # duplicate and empty ids are no-ops (same object returned)
    assert mark_contradicted(ep3, "ep-bad") is ep3
    assert mark_contradicted(ep3, "") is ep3


@pytest.mark.asyncio
async def test_contradicted_by_round_trips_through_store(mem):
    base = Episode(
        timestamp=time.time(),
        user_input="contradicted round trip",
        outcomes=[{"intent": "stat_file", "success": True}],
    )
    contradicted = mark_contradicted(base, "ep-conflict")
    await mem.store(contradicted)

    results = await mem.recall_by_intent("stat_file")
    assert len(results) == 1
    assert results[0].contradicted_by == ["ep-conflict"]


# ---------------------------------------------------------------------------
# (f) malformed / absent metadata -> honest-degrade defaults
# ---------------------------------------------------------------------------


def test_metadata_to_episode_honest_degrades_on_malformed_provenance():
    """Garbage provenance metadata falls back to neutral defaults rather than
    raising."""
    metadata = {
        "timestamp": 1.0,
        "source_type": None,            # not a str
        "confidence": "not-a-float",    # un-coercible
        "verification_count": "NaN",    # un-coercible
        "contradicted_by_json": "{not json",  # malformed
    }
    ep = EpisodicMemory._metadata_to_episode("doc-1", "doc body", metadata)
    assert ep.source_type == ""
    assert ep.confidence == 1.0
    assert ep.verification_count == 0
    assert ep.contradicted_by == []


def test_metadata_to_episode_coerces_non_list_contradicted_by():
    """A contradicted_by_json that decodes to a non-list is coerced to []."""
    metadata = {
        "timestamp": 1.0,
        "contradicted_by_json": '{"a": 1}',  # valid json, but a dict
    }
    ep = EpisodicMemory._metadata_to_episode("doc-2", "doc body", metadata)
    assert ep.contradicted_by == []


# ---------------------------------------------------------------------------
# (g) pre-AD-871 episode (no new metadata keys) recalls with defaults
# ---------------------------------------------------------------------------


def test_metadata_to_episode_pre_ad871_recalls_with_defaults():
    """Metadata written before AD-871 (no provenance keys at all) recalls with
    neutral defaults."""
    metadata = {
        "timestamp": 1.0,
        "user_input": "old episode",
        "source": "direct",
        "importance": 5,
    }
    ep = EpisodicMemory._metadata_to_episode("doc-3", "old episode", metadata)
    assert ep.source_type == ""
    assert ep.confidence == 1.0
    assert ep.verification_count == 0
    assert ep.contradicted_by == []


# ---------------------------------------------------------------------------
# REQUIRED regression: AD-598 importance reconstruction must preserve the
# provenance envelope (dataclasses.replace fix). A failure outcome with the
# default importance=5 triggers compute_importance -> 7 (!= 5), which used to
# rebuild the Episode field-by-field and silently drop confidence back to 1.0.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ad598_importance_reconstruction_preserves_confidence(mem):
    ep = Episode(
        timestamp=time.time(),
        user_input="failure path preserves confidence",
        outcomes=[{"intent": "read_file", "success": False, "response": "Permission denied"}],
        importance=5,        # default -> triggers AD-598 scoring
        confidence=0.4,      # graded belief that must survive reconstruction
        source_type="agent_inference",
        verification_count=2,
        contradicted_by=["ep-z"],
    )
    await mem.store(ep)

    results = await mem.recall_by_intent("read_file")
    assert len(results) == 1
    got = results[0]
    # The whole envelope survived the importance reconstruction.
    assert got.confidence == 0.4
    assert got.source_type == "agent_inference"
    assert got.verification_count == 2
    assert got.contradicted_by == ["ep-z"]
    # And the importance was actually re-scored (failure -> 7), proving the
    # AD-598 reconstruction branch ran.
    assert got.importance == 7
