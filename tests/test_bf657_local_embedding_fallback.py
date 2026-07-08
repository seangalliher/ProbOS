"""BF-657: network-free local embedding fallback for ChromaDB collections.

Verifies that collection creation never passes ``embedding_function=None`` (which
makes Chroma substitute its network-downloaded default ONNX EF that cannot fetch
``onnx.tar.gz`` in CI). The fix adds a fully protocol-compliant, deterministic
``LocalHashEmbeddingFunction`` and never-None helpers, plus a
``PROBOS_EMBEDDINGS=local`` toggle that forces the local path.

The forced-local tests reproduce the exact CI condition (the cached real model is
NOT allowed to satisfy them) and reset/restore the ``embeddings`` module memo so
the process-singleton state does not leak between tests.
"""

from __future__ import annotations

import math
import warnings

import chromadb
import pytest

from probos.knowledge import embeddings
from probos.knowledge.embeddings import (
    LocalHashEmbeddingFunction,
    get_active_embedding_model_name,
    get_collection_embedding_function,
    get_embedding_model_name,
)


def _cosine(vec_a: list[float], vec_b: list[float]) -> float:
    """Plain cosine similarity for test assertions."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


class TestLocalEmbeddingFunction:
    """The local EF is protocol-compliant, deterministic, and lexical."""

    def test_protocol_methods_present(self) -> None:
        ef = LocalHashEmbeddingFunction()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = ef(["probe text tokens"])
            _ = ef.get_config()
            _ = LocalHashEmbeddingFunction.name()
            _ = LocalHashEmbeddingFunction.build_from_config({"dim": 384})
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert not deprecations, [str(w.message) for w in deprecations]

        assert callable(ef)
        assert LocalHashEmbeddingFunction.name() == "probos-local-hash-v1"
        assert ef.get_config() == {"dim": 384}
        rebuilt = LocalHashEmbeddingFunction.build_from_config(ef.get_config())
        assert isinstance(rebuilt, LocalHashEmbeddingFunction)
        assert rebuilt.get_config() == ef.get_config()

    def test_deterministic_and_dimensioned(self) -> None:
        ef1 = LocalHashEmbeddingFunction()
        ef2 = LocalHashEmbeddingFunction()
        # ChromaDB's protocol wrapper normalizes __call__ output to numpy arrays;
        # coerce to plain float lists for unambiguous equality comparison.
        vec1 = [float(x) for x in ef1(["hello world knowledge mesh"])[0]]
        vec2 = [float(x) for x in ef2(["hello world knowledge mesh"])[0]]
        # Stable across independent instances (stable digest, not salted hash()).
        assert vec1 == vec2
        assert len(vec1) == 384

        vec_other = [float(x) for x in ef1(["completely separate distinct vocabulary"])[0]]
        assert vec1 != vec_other

        empty = ef1([""])[0]
        assert len(empty) == 384
        assert all(float(x) == 0.0 for x in empty)

        whitespace = ef1(["    "])[0]
        assert all(float(x) == 0.0 for x in whitespace)

    def test_similar_texts_rank_above_dissimilar(self) -> None:
        ef = LocalHashEmbeddingFunction()
        vec_a, vec_b, vec_c = ef(
            [
                "the cat sat on the mat",
                "a cat on a mat",
                "quarterly financial revenue taxes",
            ]
        )
        # Lexical: the token-sharing pair (cat/mat) ranks above the unrelated text.
        assert _cosine(vec_a, vec_b) > _cosine(vec_a, vec_c)


class TestGetCollectionEmbeddingFunction:
    """The collection helper is never None; the active-name helper tracks backend."""

    def test_never_none_when_get_embedding_function_none(self, monkeypatch) -> None:
        monkeypatch.setattr(embeddings, "get_embedding_function", lambda: None)
        ef = get_collection_embedding_function()
        assert isinstance(ef, LocalHashEmbeddingFunction)
        vectors = ef(["some indexable text"])
        assert len(vectors[0]) == 384

    def test_passthrough_when_real_ef_available(self, monkeypatch) -> None:
        sentinel = object()
        monkeypatch.setattr(embeddings, "get_embedding_function", lambda: sentinel)
        assert get_collection_embedding_function() is sentinel

    def test_active_model_name_reflects_backend(self, monkeypatch) -> None:
        monkeypatch.setattr(embeddings, "get_embedding_function", lambda: None)
        assert get_active_embedding_model_name() == "probos-local-hash-v1"

        sentinel = object()
        monkeypatch.setattr(embeddings, "get_embedding_function", lambda: sentinel)
        assert get_active_embedding_model_name() == get_embedding_model_name()


class TestRealChromaNetworkFree:
    """A real PersistentClient collection works with the local EF, no network."""

    def test_collection_add_query_no_network(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(embeddings, "get_embedding_function", lambda: None)
        # Belt-and-suspenders: prove no HF/transformers network is touched.
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

        ef = get_collection_embedding_function()
        assert isinstance(ef, LocalHashEmbeddingFunction)

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma_nn"))
        collection = client.get_or_create_collection(
            name="bf657docs",
            embedding_function=ef,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": get_active_embedding_model_name(),
            },
        )
        collection.add(
            ids=["a", "b", "c"],
            documents=[
                "cat sat on the mat",
                "the cat on a mat",
                "quarterly revenue taxes budget",
            ],
        )
        result = collection.query(query_texts=["cat mat"], n_results=3)
        assert result["ids"] and len(result["ids"][0]) == 3
        # The two token-sharing docs (a, b) rank above the unrelated doc (c).
        assert result["ids"][0].index("c") == 2

    def test_collection_reopen_preserves_count(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(embeddings, "get_embedding_function", lambda: None)
        ef = get_collection_embedding_function()
        path = str(tmp_path / "chroma_reopen")

        client = chromadb.PersistentClient(path=path)
        collection = client.get_or_create_collection(
            name="bf657reopen",
            embedding_function=ef,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": get_active_embedding_model_name(),
            },
        )
        collection.add(ids=["x", "y"], documents=["alpha beta gamma", "delta epsilon zeta"])
        assert collection.count() == 2

        del collection, client
        # Reopen a fresh client over the same path with the SAME local EF config.
        client2 = chromadb.PersistentClient(path=path)
        collection2 = client2.get_or_create_collection(
            name="bf657reopen", embedding_function=ef
        )
        assert collection2.count() == 2
        result = collection2.query(query_texts=["alpha beta"], n_results=2)
        assert result["ids"] and len(result["ids"][0]) == 2


class TestPreviouslyFailingUnderForcedLocal:
    """Re-run the previously-failing scenarios under the exact CI condition.

    ``PROBOS_EMBEDDINGS=local`` is set AND the module memo is reset (via
    monkeypatch, which also restores it) so the env short-circuit is genuinely
    taken and the cached real model cannot leak in and hide the fix.
    """

    @pytest.mark.asyncio
    async def test_episodic_seed_recent_under_forced_local(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("PROBOS_EMBEDDINGS", "local")
        monkeypatch.setattr(embeddings, "_embedding_available", None)
        monkeypatch.setattr(embeddings, "_embedding_fn", None)
        # The env short-circuit returns None fast, skipping the download probes.
        assert embeddings.get_embedding_function() is None

        from probos.cognitive.episodic import EpisodicMemory
        from probos.types import Episode

        mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
        await mem.start()
        try:
            episode = Episode(
                id="bf657_seed",
                user_input="read config file",
                timestamp=1234567890.0,
                dag_summary={},
                outcomes=[],
                agent_ids=[],
                duration_ms=10.0,
            )
            count = await mem.seed([episode])
            assert count == 1
            recent = await mem.recent(10)
            assert any(e.id == "bf657_seed" for e in recent)
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_semantic_index_agent_under_forced_local(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("PROBOS_EMBEDDINGS", "local")
        monkeypatch.setattr(embeddings, "_embedding_available", None)
        monkeypatch.setattr(embeddings, "_embedding_fn", None)
        assert embeddings.get_embedding_function() is None

        from probos.knowledge.semantic import SemanticKnowledgeLayer

        layer = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await layer.start()
        try:
            await layer.index_agent(
                agent_type="news_fetcher",
                intent_name="fetch_news",
                description="Fetches news from RSS feeds",
                strategy="new_agent",
            )
            assert layer._collections["agents"].count() == 1
            result = layer._collections["agents"].query(query_texts=["news"], n_results=2)
            assert result["ids"] and len(result["ids"][0]) >= 1
        finally:
            await layer.stop()
