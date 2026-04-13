"""AD-605: Enhanced Embedding — Content + Anchor Metadata Concatenation."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from probos.types import AnchorFrame, Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    user_input: str = "test input",
    anchors: AnchorFrame | None = None,
    episode_id: str = "ep-001",
) -> Episode:
    return Episode(
        id=episode_id,
        user_input=user_input,
        timestamp=time.time(),
        agent_ids=["agent-001"],
        source="direct",
        anchors=anchors,
        outcomes=[{"intent": "test_intent", "success": True}],
    )


def _full_anchor(**overrides) -> AnchorFrame:
    defaults = dict(
        department="science",
        channel="ward_room",
        watch_section="first",
        trigger_type="direct_message",
    )
    defaults.update(overrides)
    return AnchorFrame(**defaults)


# ---------------------------------------------------------------------------
# TestPrepareDocument — 5 tests
# ---------------------------------------------------------------------------

class TestPrepareDocument:
    """Test _prepare_document() static method."""

    def test_full_anchor_prepended(self):
        """Test 1: All anchor fields appear as bracketed prefixes."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(
            user_input="pool threshold analysis",
            anchors=_full_anchor(
                department="science",
                channel="ward_room",
                watch_section="first",
                trigger_type="direct_message",
            ),
        )
        doc = EpisodicMemory._prepare_document(ep)
        assert doc == "[science] [ward_room] [first] [direct_message] pool threshold analysis"

    def test_empty_fields_omitted(self):
        """Test 2: Only non-empty anchor fields appear in document."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(
            user_input="something happened",
            anchors=AnchorFrame(department="science", channel="", watch_section="first", trigger_type=""),
        )
        doc = EpisodicMemory._prepare_document(ep)
        assert doc == "[science] [first] something happened"

    def test_no_anchors_returns_user_input(self):
        """Test 3: Episode with anchors=None returns user_input unchanged."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(user_input="raw text only", anchors=None)
        doc = EpisodicMemory._prepare_document(ep)
        assert doc == "raw text only"

    def test_empty_user_input(self):
        """Test 4: Episode with anchors but empty user_input."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(user_input="", anchors=_full_anchor())
        doc = EpisodicMemory._prepare_document(ep)
        assert doc == "[science] [ward_room] [first] [direct_message] "

    def test_format_consistency(self):
        """Test 5: Idempotent — same input always produces same output."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(user_input="test", anchors=_full_anchor())
        doc1 = EpisodicMemory._prepare_document(ep)
        doc2 = EpisodicMemory._prepare_document(ep)
        assert doc1 == doc2


# ---------------------------------------------------------------------------
# TestStoreUsesEnrichedDocument — 3 tests
# ---------------------------------------------------------------------------

class TestStoreUsesEnrichedDocument:
    """Test that ChromaDB write sites use _prepare_document()."""

    @pytest.mark.asyncio
    async def test_store_uses_prepare_document(self):
        """Test 6: store() passes enriched text to collection.add()."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._activation_tracker = None
        em._query_reformulation_enabled = False
        em.max_episodes = 1000

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_collection.get.return_value = {"ids": []}
        em._collection = mock_collection
        em._fts_db = None
        em._participant_index = None
        em._eviction_audit = None

        ep = _make_episode(
            user_input="pool threshold analysis",
            anchors=_full_anchor(department="engineering"),
        )
        await em.store(ep)

        call_args = mock_collection.add.call_args
        doc = call_args.kwargs.get("documents") or call_args[1].get("documents")
        assert doc is not None
        assert "[engineering]" in doc[0]
        assert "pool threshold analysis" in doc[0]

    @pytest.mark.asyncio
    async def test_seed_uses_prepare_document(self):
        """Test 7: seed() passes enriched text in batch docs."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._activation_tracker = None
        em._query_reformulation_enabled = False

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}
        em._collection = mock_collection
        em._fts_db = None
        em._participant_index = None

        ep = _make_episode(
            user_input="seeded episode",
            anchors=_full_anchor(department="medical"),
            episode_id="seed-001",
        )
        await em.seed([ep])

        call_args = mock_collection.add.call_args
        docs = call_args.kwargs.get("documents") or call_args[1].get("documents")
        assert docs is not None
        assert "[medical]" in docs[0]
        assert "seeded episode" in docs[0]

    def test_force_update_uses_prepare_document(self):
        """Test 8: _force_update() passes enriched text to collection.upsert()."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._activation_tracker = None
        em._query_reformulation_enabled = False
        em._eviction_audit = None

        mock_collection = MagicMock()
        em._collection = mock_collection
        em._fts_db = None
        em._participant_index = None

        ep = _make_episode(
            user_input="updated episode",
            anchors=_full_anchor(department="security", watch_section="second"),
        )
        em._force_update(ep)

        call_args = mock_collection.upsert.call_args
        doc = call_args.kwargs.get("documents") or call_args[1].get("documents")
        assert doc is not None
        assert "[security]" in doc[0]
        assert "[second]" in doc[0]
        assert "updated episode" in doc[0]


# ---------------------------------------------------------------------------
# TestMetadataPreservation — 3 tests
# ---------------------------------------------------------------------------

class TestMetadataPreservation:
    """Test original user_input preservation in metadata."""

    def test_original_user_input_in_metadata(self):
        """Test 9: _episode_to_metadata includes user_input key."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(
            user_input="original text here",
            anchors=_full_anchor(),
        )
        metadata = EpisodicMemory._episode_to_metadata(ep)
        assert "user_input" in metadata
        assert metadata["user_input"] == "original text here"

    def test_metadata_to_episode_uses_stored_user_input(self):
        """Test 10: _metadata_to_episode uses stored user_input over document."""
        from probos.cognitive.episodic import EpisodicMemory

        enriched_doc = "[science] [ward_room] [first] original text"
        metadata = {
            "timestamp": time.time(),
            "user_input": "original text",  # AD-605: stored original
            "intent_type": "",
            "dag_summary_json": "{}",
            "outcomes_json": "[]",
            "reflection": "",
            "agent_ids_json": '["agent-001"]',
            "duration_ms": 0.0,
            "shapley_values_json": "{}",
            "trust_deltas_json": "[]",
            "source": "direct",
            "anchors_json": "",
        }
        ep = EpisodicMemory._metadata_to_episode("ep-001", enriched_doc, metadata)
        assert ep.user_input == "original text"

    def test_metadata_to_episode_fallback_to_document(self):
        """Test 11: _metadata_to_episode falls back to document for pre-migration episodes."""
        from probos.cognitive.episodic import EpisodicMemory

        metadata = {
            "timestamp": time.time(),
            # No "user_input" key — pre-migration episode
            "intent_type": "",
            "dag_summary_json": "{}",
            "outcomes_json": "[]",
            "reflection": "",
            "agent_ids_json": '["agent-001"]',
            "duration_ms": 0.0,
            "shapley_values_json": "{}",
            "trust_deltas_json": "[]",
            "source": "direct",
            "anchors_json": "",
        }
        ep = EpisodicMemory._metadata_to_episode("ep-001", "fallback document text", metadata)
        assert ep.user_input == "fallback document text"


# ---------------------------------------------------------------------------
# TestMigration — 4 tests
# ---------------------------------------------------------------------------

class TestMigration:
    """Test migrate_enriched_embedding() migration function."""

    def test_migration_enriches_existing_episodes(self):
        """Test 12: Migration re-embeds episodes with enriched text and populates user_input."""
        from probos.cognitive.episodic import EpisodicMemory, migrate_enriched_embedding

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._activation_tracker = None
        em._query_reformulation_enabled = False

        anchors = _full_anchor(department="engineering", watch_section="second")

        mock_collection = MagicMock()
        mock_collection.metadata = {"hnsw:space": "cosine"}
        mock_collection.get.return_value = {
            "ids": ["ep-001"],
            "documents": ["raw episode text"],
            "metadatas": [{
                "timestamp": time.time(),
                "anchors_json": json.dumps({
                    "department": "engineering",
                    "channel": "ward_room",
                    "watch_section": "second",
                    "trigger_type": "direct_message",
                }),
            }],
        }
        em._collection = mock_collection

        count = migrate_enriched_embedding(em)

        assert count == 1
        # Verify update was called with enriched doc
        update_call = mock_collection.update.call_args
        doc = update_call.kwargs.get("documents") or update_call[1].get("documents")
        assert "[engineering]" in doc[0]
        assert "[second]" in doc[0]
        assert "raw episode text" in doc[0]
        # Verify user_input was populated in metadata
        meta = update_call.kwargs.get("metadatas") or update_call[1].get("metadatas")
        assert meta[0]["user_input"] == "raw episode text"
        # Verify version marker set
        mock_collection.modify.assert_called_once()

    def test_migration_skips_if_already_done(self):
        """Test 13: Migration returns 0 if enriched_embedding_version >= 1."""
        from probos.cognitive.episodic import EpisodicMemory, migrate_enriched_embedding

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._activation_tracker = None
        em._query_reformulation_enabled = False

        mock_collection = MagicMock()
        mock_collection.metadata = {"enriched_embedding_version": 1}
        em._collection = mock_collection

        count = migrate_enriched_embedding(em)
        assert count == 0
        mock_collection.get.assert_not_called()

    def test_migration_handles_empty_collection(self):
        """Test 14: Migration with empty collection updates version and returns 0."""
        from probos.cognitive.episodic import EpisodicMemory, migrate_enriched_embedding

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._activation_tracker = None
        em._query_reformulation_enabled = False

        mock_collection = MagicMock()
        mock_collection.metadata = {}
        mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        em._collection = mock_collection

        count = migrate_enriched_embedding(em)
        assert count == 0
        mock_collection.modify.assert_called_once()
        modify_meta = mock_collection.modify.call_args.kwargs.get("metadata")
        assert modify_meta["enriched_embedding_version"] == 1

    def test_migration_preserves_original_user_input(self):
        """Test 15: After migration, _metadata_to_episode returns original user_input."""
        from probos.cognitive.episodic import EpisodicMemory, migrate_enriched_embedding

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._activation_tracker = None
        em._query_reformulation_enabled = False

        original_text = "original raw user input"
        mock_collection = MagicMock()
        mock_collection.metadata = {}
        mock_collection.get.return_value = {
            "ids": ["ep-002"],
            "documents": [original_text],
            "metadatas": [{
                "timestamp": time.time(),
                "anchors_json": json.dumps({"department": "science", "watch_section": "first"}),
            }],
        }
        em._collection = mock_collection

        migrate_enriched_embedding(em)

        # Get the metadata that was written during migration
        update_call = mock_collection.update.call_args
        meta = (update_call.kwargs.get("metadatas") or update_call[1].get("metadatas"))[0]
        enriched_doc = (update_call.kwargs.get("documents") or update_call[1].get("documents"))[0]

        # Reconstruct episode — should get original user_input back
        ep = EpisodicMemory._metadata_to_episode("ep-002", enriched_doc, meta)
        assert ep.user_input == original_text
        assert ep.user_input != enriched_doc  # enriched doc has prefix brackets
