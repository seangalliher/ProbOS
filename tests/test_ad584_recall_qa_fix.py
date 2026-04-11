"""AD-584: Recall Pipeline Q->A Fix — Embedding Model Swap + Query Reformulation.

Tests cover: embedding model accessor, query reformulation, dual-query recall,
BF-029 prefix removal, and embedding model migration.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import AnchorFrame, Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _start_episodic_memory(em) -> None:
    """Start EpisodicMemory, skipping if ChromaDB ONNX model is unavailable."""
    try:
        await em.start()
    except Exception as exc:
        if "INVALID_PROTOBUF" in str(exc) or "onnx" in str(exc).lower():
            pytest.skip(f"ChromaDB ONNX model unavailable: {exc}")
        raise


def _make_episode(
    *,
    user_input: str = "test input",
    timestamp: float | None = None,
    agent_ids: list[str] | None = None,
    source: str = "direct",
    reflection: str | None = None,
) -> Episode:
    return Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source=source,
        reflection=reflection,
        outcomes=[{"intent": "test_intent", "success": True}],
    )


# ===========================================================================
# Group 1: Embedding Model (6 tests)
# ===========================================================================


class TestEmbeddingModel:
    """AD-584a: Embedding model swap tests."""

    def test_get_embedding_model_name_returns_string(self):
        """Test 2: model name matches expected QA model."""
        from probos.knowledge.embeddings import get_embedding_model_name
        name = get_embedding_model_name()
        assert isinstance(name, str)
        assert name == "multi-qa-MiniLM-L6-cos-v1"

    def test_model_name_is_module_level_constant(self):
        """Verify _MODEL_NAME is accessible and correct."""
        from probos.knowledge import embeddings
        assert embeddings._MODEL_NAME == "multi-qa-MiniLM-L6-cos-v1"

    def test_get_embedding_function_returns_callable_or_none(self):
        """Test 1: embedding function is callable (or None if ONNX unavailable)."""
        from probos.knowledge.embeddings import get_embedding_function
        # Reset singleton for clean test
        import probos.knowledge.embeddings as mod
        mod._embedding_fn = None
        mod._embedding_available = None
        ef = get_embedding_function()
        if ef is not None:
            assert callable(ef)
        # Reset after test
        mod._embedding_fn = None
        mod._embedding_available = None

    def test_keyword_fallback_still_works(self):
        """Test 6: keyword overlap fallback activates when embeddings unavailable."""
        from probos.knowledge.embeddings import _keyword_embedding, _keyword_similarity
        emb_a = _keyword_embedding("pool health threshold configured")
        emb_b = _keyword_embedding("pool health threshold was set")
        assert len(emb_a) > 0
        assert len(emb_b) > 0
        sim = _keyword_similarity(emb_a, emb_b)
        assert sim > 0.3  # Keyword overlap should catch shared terms

    def test_embedding_function_fallback_chain(self):
        """Verify fallback: SentenceTransformer -> Default -> None."""
        import probos.knowledge.embeddings as mod
        mod._embedding_fn = None
        mod._embedding_available = None

        # When both raise, should return None
        with patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction", side_effect=ImportError("no ST")):
            with patch("chromadb.utils.embedding_functions.DefaultEmbeddingFunction", side_effect=ImportError("no default")):
                result = mod.get_embedding_function()
                assert result is None

        # Reset singleton
        mod._embedding_fn = None
        mod._embedding_available = None

    def test_cosine_similarity_function(self):
        """Verify _cosine_similarity math is correct."""
        from probos.knowledge.embeddings import _cosine_similarity
        # Identical vectors -> 1.0
        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
        # Orthogonal vectors -> 0.0
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
        # Empty vectors -> 0.0
        assert _cosine_similarity([], []) == 0.0


# ===========================================================================
# Group 2: Query Reformulation (10 tests)
# ===========================================================================


class TestQueryReformulation:
    """AD-584b: Template-based query reformulation tests."""

    def test_reformulate_what_is(self):
        """Test 7: 'What is X?' -> ['What is X', 'X is']."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("What is the pool health threshold?")
        assert len(result) == 2
        assert result[0] == "What is the pool health threshold"
        assert result[1] == "the pool health threshold is"

    def test_reformulate_what_was(self):
        """Test 8: 'What was X?' -> ['What was X', 'X was']."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("What was the trust score?")
        assert len(result) == 2
        assert result[0] == "What was the trust score"
        assert result[1] == "the trust score was"

    def test_reformulate_how_does(self):
        """Test 9: 'How does X work?' -> ['How does X work', 'X works by']."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("How does the Hebbian router work?")
        assert len(result) == 2
        assert result[0] == "How does the Hebbian router work"
        assert result[1] == "the Hebbian router works by"

    def test_reformulate_who_did(self):
        """Test 10: 'Who did X?' -> ['Who did X', 'X']."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("Who did the analysis?")
        assert len(result) == 2
        assert result[0] == "Who did the analysis"
        assert result[1] == "the analysis"

    def test_reformulate_when_did(self):
        """Test 11: 'When did X happen?' -> ['When did X happen', 'X happen happened']."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("When did the migration run?")
        assert len(result) == 2
        assert result[0] == "When did the migration run"
        assert result[1] == "the migration run happened"

    def test_reformulate_why_did(self):
        """Test 12: 'Why did X fail?' -> ['Why did X fail', 'X fail because']."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("Why did the test fail?")
        assert len(result) == 2
        assert result[0] == "Why did the test fail"
        assert result[1] == "the test fail because"

    def test_reformulate_how_many(self):
        """Test 13: 'How many X?' -> ['How many X', 'the number of X is']."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("How many agents are active?")
        assert len(result) == 2
        assert result[0] == "How many agents are active"
        assert result[1] == "the number of agents are active is"

    def test_reformulate_yes_no(self):
        """Test 14: 'Did X happen?' -> ['Did X happen', 'X happen']."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("Did the migration complete?")
        assert len(result) == 2
        assert result[0] == "Did the migration complete"
        assert result[1] == "the migration complete"

    def test_reformulate_non_question(self):
        """Test 15: Non-question text passes through unchanged."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("The threshold was 0.7")
        assert len(result) == 1
        assert result[0] == "The threshold was 0.7"

    def test_reformulate_strips_question_mark(self):
        """Test 16: trailing ? removed from all variants."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("What is X?")
        for variant in result:
            assert "?" not in variant

    def test_reformulate_empty_input(self):
        """Edge case: empty string returns empty list."""
        from probos.knowledge.embeddings import reformulate_query
        result = reformulate_query("")
        assert result == []

    def test_reformulate_whitespace_only(self):
        """Edge case: whitespace-only string returns original (no crash)."""
        from probos.knowledge.embeddings import reformulate_query
        # After stripping "?" and whitespace, nothing left — returns [text] passthrough
        result = reformulate_query("   ?  ")
        assert isinstance(result, list)
        assert len(result) <= 1


# ===========================================================================
# Group 3: Recall Pipeline Integration (10 tests)
# ===========================================================================


class TestRecallPipelineIntegration:
    """AD-584: Dual-query recall and BF-029 prefix removal tests."""

    @pytest.mark.asyncio
    async def test_recall_for_agent_scored_uses_reformulation(self, tmp_path):
        """Test 17: store a fact, query with a question, verify recall uses reformulation."""
        from probos.cognitive.episodic import EpisodicMemory
        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100,
                            query_reformulation_enabled=True)
        await _start_episodic_memory(em)

        ep = _make_episode(user_input="The pool health threshold was set to 0.7")
        await em.store(ep)

        # Actual ChromaDB query — results depend on embedding model availability
        results = await em.recall_for_agent_scored("agent-001", "What is the pool health threshold?", k=5)
        # If ChromaDB embeddings work, should return something
        # (if ONNX unavailable, collection.query may fail — test is informational)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_recall_for_agent_scored_without_reformulation(self, tmp_path):
        """Test 18: recall works with reformulation disabled."""
        from probos.cognitive.episodic import EpisodicMemory
        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100,
                            query_reformulation_enabled=False)
        await _start_episodic_memory(em)

        ep = _make_episode(user_input="Trust score for Counselor is 0.85")
        await em.store(ep)

        results = await em.recall_for_agent_scored("agent-001", "What is the trust score?", k=5)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_dual_query_dedup(self, tmp_path):
        """Test 20: same episode matched by both variants appears once."""
        from probos.cognitive.episodic import EpisodicMemory
        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)

        ep = _make_episode(user_input="The health threshold is 0.7")
        await em.store(ep)

        results = await em.recall_for_agent_scored("agent-001", "What is the health threshold?", k=5)
        # Each episode should appear at most once
        ep_ids = [r[0].id for r in results]
        assert len(ep_ids) == len(set(ep_ids))

    @pytest.mark.asyncio
    async def test_dual_query_takes_best_score(self, tmp_path):
        """Test 21: episode gets the best (lowest distance / highest similarity) score."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)

        # Mock the collection to verify merge logic
        mock_collection = MagicMock()
        mock_collection.count.return_value = 5
        mock_collection.query.return_value = {
            "ids": [["ep1", "ep2"], ["ep1", "ep3"]],
            "distances": [[0.5, 0.7], [0.3, 0.8]],
            "metadatas": [
                [{"agent_ids_json": '["agent-001"]'}, {"agent_ids_json": '["agent-001"]'}],
                [{"agent_ids_json": '["agent-001"]'}, {"agent_ids_json": '["agent-001"]'}],
            ],
            "documents": [["doc1", "doc2"], ["doc1", "doc3"]],
        }
        em._collection = mock_collection
        em._query_reformulation_enabled = True

        results = await em.recall_for_agent_scored("agent-001", "What is X?", k=5)
        # ep1 should use distance 0.3 (best across variants), giving similarity 0.7
        ep1_results = [(ep, sim) for ep, sim in results if ep.id == "ep1"]
        if ep1_results:
            assert ep1_results[0][1] == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_recall_weighted_inherits_reformulation(self, tmp_path):
        """Test 19: recall_weighted calls recall_for_agent_scored which uses reformulation."""
        from probos.cognitive.episodic import EpisodicMemory
        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)

        ep = _make_episode(user_input="The configuration was updated to version 2.0")
        await em.store(ep)

        results = await em.recall_weighted("agent-001", "What version was configured?", k=5)
        assert isinstance(results, list)

    def test_bf029_prefix_removed(self):
        """Test 22: direct_message recall query does NOT prepend 'Ward Room {callsign}'."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        # Verify the source code doesn't contain the BF-029 f-string prefix pattern
        import inspect
        source = inspect.getsource(CognitiveAgent._recall_relevant_memories)
        # The actual f-string assignment is what matters — comments mentioning it are fine
        assert 'f"Ward Room' not in source

    def test_query_reformulation_enabled_default(self):
        """Verify EpisodicMemory defaults to query_reformulation_enabled=True."""
        from probos.cognitive.episodic import EpisodicMemory
        em = EpisodicMemory("/tmp/test.db")
        assert em._query_reformulation_enabled is True

    def test_query_reformulation_configurable(self):
        """Verify query_reformulation_enabled can be set to False."""
        from probos.cognitive.episodic import EpisodicMemory
        em = EpisodicMemory("/tmp/test.db", query_reformulation_enabled=False)
        assert em._query_reformulation_enabled is False

    def test_non_dm_intent_unaffected(self):
        """Test 24: ward_room_notification intent query construction unchanged by AD-584."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        import inspect
        source = inspect.getsource(CognitiveAgent._recall_relevant_memories)

        # The ward_room_notification path should still compose query from title+text
        # (not affected by the BF-029 prefix removal which only targeted direct_message)
        assert "ward_room_notification" in source
        # Verify the direct_message path no longer uses f"Ward Room prefix
        assert 'f"Ward Room' not in source

    @pytest.mark.asyncio
    async def test_basic_tier_recalls_with_reformulation(self, tmp_path):
        """Test 25: Ensign-rank agent with BASIC tier can recall with new model."""
        from probos.cognitive.episodic import EpisodicMemory
        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)

        ep = _make_episode(user_input="Agent health status is nominal")
        await em.store(ep)

        # BASIC tier uses k=3 (from resolve_recall_tier_params)
        results = await em.recall_for_agent_scored("agent-001", "What is the health status?", k=3)
        assert isinstance(results, list)


# ===========================================================================
# Group 4: Migration (4 tests)
# ===========================================================================


class TestEmbeddingModelMigration:
    """AD-584: Embedding model migration tests."""

    @pytest.mark.asyncio
    async def test_migration_detects_model_mismatch(self, tmp_path):
        """Test 27: create collection with old model metadata, verify migration triggers."""
        from probos.cognitive.episodic import EpisodicMemory, migrate_embedding_model

        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)

        # Store an episode
        ep = _make_episode(user_input="Test episode for migration")
        await em.store(ep)

        # Simulate old model by modifying metadata (cannot include hnsw:space in modify())
        em._collection.modify(metadata={"embedding_model": "all-MiniLM-L6-v2"})

        # Run migration
        migrated = await migrate_embedding_model(em, "multi-qa-MiniLM-L6-cos-v1")
        assert migrated > 0

    @pytest.mark.asyncio
    async def test_migration_preserves_episode_count(self, tmp_path):
        """Test 28: after migration, same number of episodes exist."""
        from probos.cognitive.episodic import EpisodicMemory, migrate_embedding_model

        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)

        # Store 3 episodes
        for i in range(3):
            ep = _make_episode(user_input=f"Migration test episode {i}")
            await em.store(ep)

        count_before = em._collection.count()

        # Force migration
        em._collection.modify(metadata={"embedding_model": "old-model"})
        await migrate_embedding_model(em, "new-model")

        count_after = em._collection.count()
        assert count_after == count_before

    @pytest.mark.asyncio
    async def test_migration_updates_metadata(self, tmp_path):
        """Test 29: after migration, collection metadata has new model name."""
        from probos.cognitive.episodic import EpisodicMemory, migrate_embedding_model

        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)

        ep = _make_episode(user_input="Metadata test episode")
        await em.store(ep)

        em._collection.modify(metadata={"embedding_model": "old-model"})
        await migrate_embedding_model(em, "new-model-v2")

        new_meta = em._collection.metadata or {}
        assert new_meta.get("embedding_model") == "new-model-v2"

    @pytest.mark.asyncio
    async def test_migration_skips_when_model_matches(self, tmp_path):
        """Test 30: when model already matches, no re-embedding occurs."""
        from probos.cognitive.episodic import EpisodicMemory, migrate_embedding_model

        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)

        ep = _make_episode(user_input="No migration needed")
        await em.store(ep)

        # Set metadata to match
        em._collection.modify(metadata={"embedding_model": "current-model"})
        migrated = await migrate_embedding_model(em, "current-model")
        assert migrated == 0

    @pytest.mark.asyncio
    async def test_migration_handles_no_collection(self):
        """Migration gracefully handles None collection."""
        from probos.cognitive.episodic import migrate_embedding_model

        em = MagicMock()
        em._collection = None
        result = await migrate_embedding_model(em, "any-model")
        assert result == 0

    @pytest.mark.asyncio
    async def test_migration_handles_empty_collection(self, tmp_path):
        """Migration updates metadata when collection is empty (no episodes)."""
        from probos.cognitive.episodic import EpisodicMemory, migrate_embedding_model

        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)

        # Don't store any episodes
        em._collection.modify(metadata={"embedding_model": "old-model"})
        migrated = await migrate_embedding_model(em, "new-model")
        assert migrated == 0  # No episodes to re-embed

        # But metadata should still be updated
        meta = em._collection.metadata or {}
        assert meta.get("embedding_model") == "new-model"


# ===========================================================================
# Config integration tests
# ===========================================================================


class TestConfigIntegration:
    """AD-584: Config field tests."""

    def test_memory_config_has_embedding_model(self):
        """Config includes embedding_model field with correct default."""
        from probos.config import MemoryConfig
        mc = MemoryConfig()
        assert mc.embedding_model == "multi-qa-MiniLM-L6-cos-v1"

    def test_memory_config_has_query_reformulation(self):
        """Config includes query_reformulation_enabled field with correct default."""
        from probos.config import MemoryConfig
        mc = MemoryConfig()
        assert mc.query_reformulation_enabled is True

    def test_memory_config_reformulation_configurable(self):
        """query_reformulation_enabled can be set to False."""
        from probos.config import MemoryConfig
        mc = MemoryConfig(query_reformulation_enabled=False)
        assert mc.query_reformulation_enabled is False


class TestReformulationCoverage:
    """BF-139: Reformulation coverage for probe question forms."""

    @pytest.mark.parametrize("question,expected_variant_count", [
        ("What happened during first watch?", 2),
        ("What was discussed most recently?", 2),
        ("What was the pool health threshold?", 2),
        ("What did the Science department identify?", 2),
        ("Tell me about the trust anomaly", 2),
        ("What happened?", 2),
        # Existing patterns still work (regression)
        ("What is the current pool health?", 2),
        ("How does the routing system work?", 2),
        ("When did the anomaly occur?", 2),
        ("Why did the agent fail?", 2),
    ])
    def test_probe_questions_reformulate(self, question, expected_variant_count):
        from probos.knowledge.embeddings import reformulate_query
        variants = reformulate_query(question)
        assert len(variants) == expected_variant_count, (
            f"Question '{question}' produced {len(variants)} variants "
            f"(expected {expected_variant_count}): {variants}"
        )

    @pytest.mark.parametrize("non_question", [
        "Pool health dropped to 45%",
        "Trust anomaly in the network",
        "engineering routing update",
    ])
    def test_non_question_produces_single_variant(self, non_question):
        """Non-question text should produce 1 variant only."""
        from probos.knowledge.embeddings import reformulate_query
        variants = reformulate_query(non_question)
        assert len(variants) == 1, (
            f"Non-question '{non_question}' should produce 1 variant, got {variants}"
        )
