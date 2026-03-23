"""Tests for the shared embedding utility (Phase 14b)."""

from __future__ import annotations

import pytest
from unittest.mock import patch


class TestEmbeddingFunction:
    """Tests for get_embedding_function()."""

    def test_get_embedding_function_returns_callable(self):
        """get_embedding_function() returns a callable."""
        from probos.knowledge.embeddings import get_embedding_function
        ef = get_embedding_function()
        assert ef is not None
        assert callable(ef)

    def test_embed_text_returns_floats(self):
        """embed_text() returns non-empty list of floats."""
        from probos.knowledge.embeddings import embed_text
        vec = embed_text("hello world")
        assert len(vec) > 0
        assert all(isinstance(v, (float, int)) or hasattr(v, '__float__') for v in vec)

    def test_identical_text_similarity_near_one(self):
        """compute_similarity() of identical text is close to 1.0."""
        from probos.knowledge.embeddings import compute_similarity
        score = compute_similarity("deploy the API server", "deploy the API server")
        assert score > 0.95

    def test_different_text_similarity_below_threshold(self):
        """compute_similarity() of very different text is < 0.8."""
        from probos.knowledge.embeddings import compute_similarity
        score = compute_similarity("deploy the API server", "bake a chocolate cake")
        assert score < 0.8

    def test_semantic_similarity_ordering(self):
        """Semantically similar text scores higher than dissimilar text."""
        from probos.knowledge.embeddings import compute_similarity
        sim_related = compute_similarity("deploy the API", "push to production")
        sim_unrelated = compute_similarity("deploy the API", "bake a cake")
        assert sim_related > sim_unrelated

    def test_empty_text_returns_zero(self):
        """compute_similarity() with empty text returns 0.0."""
        from probos.knowledge.embeddings import compute_similarity
        assert compute_similarity("", "hello") == 0.0
        assert compute_similarity("hello", "") == 0.0

    def test_fallback_to_keyword_overlap(self):
        """When embedding function unavailable, falls back to keyword overlap."""
        import probos.knowledge.embeddings as emb_mod

        # Save originals
        orig_fn = emb_mod._embedding_fn
        orig_available = emb_mod._embedding_available

        try:
            # Force unavailable
            emb_mod._embedding_fn = None
            emb_mod._embedding_available = False

            # Should still work via keyword fallback
            score = emb_mod.compute_similarity("read file config.yaml", "read file config.yaml")
            assert score > 0.9  # Same text → high keyword overlap

            score2 = emb_mod.compute_similarity("read file", "bake cake")
            assert score2 < score  # Different → lower
        finally:
            # Restore
            emb_mod._embedding_fn = orig_fn
            emb_mod._embedding_available = orig_available
