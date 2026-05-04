"""AD-686: Oracle absorbs SemanticKnowledgeLayer (Tier 5) tests."""

from __future__ import annotations

import inspect
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.oracle_service import OracleResult, OracleService


class _StubSemanticLayer:
    """Async stub mirroring SemanticKnowledgeLayer.search() shape."""

    def __init__(self, results: list[dict] | None = None) -> None:
        self._results = results or []
        self.calls: list[dict] = []

    async def search(
        self, query: str, types: list[str] | None = None, limit: int = 10,
    ) -> list[dict]:
        self.calls.append({"query": query, "types": types, "limit": limit})
        return list(self._results)


# 1. Method shape ------------------------------------------------------------


def test_query_semantic_method_shape() -> None:
    oracle = OracleService()
    assert hasattr(oracle, "_query_semantic")
    sig = inspect.signature(oracle._query_semantic)
    params = sig.parameters
    assert "query_text" in params
    assert "k" in params
    assert "types" in params
    assert params["k"].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["types"].kind == inspect.Parameter.KEYWORD_ONLY
    # attach_semantic_layer callable, idempotent, accepts None.
    assert callable(oracle.attach_semantic_layer)
    oracle.attach_semantic_layer(None)
    oracle.attach_semantic_layer(None)
    stub = _StubSemanticLayer()
    oracle.attach_semantic_layer(stub)
    oracle.attach_semantic_layer(stub)  # idempotent
    assert oracle._semantic_layer is stub


# 2. Happy path with stub layer ---------------------------------------------


@pytest.mark.asyncio
async def test_query_semantic_happy_path_with_stub_layer() -> None:
    raw = [
        {"type": "agents", "id": "a1", "document": "agent doc",
         "score": 0.9, "metadata": {"extra": "x"}},
        {"type": "skills", "id": "s1", "document": "skill doc",
         "score": 0.7, "metadata": {"k": "v"}},
        {"type": "workflows", "id": "w1", "document": "wf doc",
         "score": 0.5, "metadata": {}},
    ]
    layer = _StubSemanticLayer(raw)
    oracle = OracleService(semantic_layer=layer)
    out = await oracle._query_semantic("anything", k=10)
    assert len(out) == 3
    for r in out:
        assert isinstance(r, OracleResult)
        assert r.source_tier == "semantic"
        assert r.provenance.startswith("[semantic: ")
        assert "id" in r.metadata
        assert "type" in r.metadata
    # Original metadata flattened in
    assert out[0].metadata["extra"] == "x"
    assert out[1].metadata["k"] == "v"


# 3. None layer returns empty + logs ----------------------------------------


@pytest.mark.asyncio
async def test_query_semantic_none_layer_returns_empty_and_logs(caplog) -> None:
    oracle = OracleService(semantic_layer=None)
    with caplog.at_level(logging.DEBUG, logger="probos.cognitive.oracle_service"):
        out = await oracle._query_semantic("q", k=5)
    assert out == []
    assert any("Tier 5" in rec.message for rec in caplog.records)


# 4. types/limit passthrough ------------------------------------------------


@pytest.mark.asyncio
async def test_query_semantic_types_passthrough() -> None:
    layer = _StubSemanticLayer([])
    oracle = OracleService(semantic_layer=layer)
    await oracle._query_semantic("q", k=7, types=["agents", "skills"])
    assert len(layer.calls) == 1
    call = layer.calls[0]
    assert call["types"] == ["agents", "skills"]
    assert call["limit"] == 7


# 5. Score coercion ---------------------------------------------------------


@pytest.mark.asyncio
async def test_query_semantic_score_coercion() -> None:
    raw = [
        {"type": "agents", "id": "x", "document": "d", "score": None, "metadata": {}},
        {"type": "agents", "id": "y", "document": "d", "score": "0.7", "metadata": {}},
    ]
    layer = _StubSemanticLayer(raw)
    oracle = OracleService(semantic_layer=layer)
    out = await oracle._query_semantic("q", k=5)
    assert len(out) == 2
    assert out[0].score == 0.0
    assert out[1].score == pytest.approx(0.7)


# 6. semantic in default active tiers ---------------------------------------


@pytest.mark.asyncio
async def test_semantic_in_default_active_tiers() -> None:
    layer = _StubSemanticLayer([
        {"type": "agents", "id": "a", "document": "doc", "score": 0.5, "metadata": {}},
    ])
    oracle = OracleService(semantic_layer=layer)
    out = await oracle.query("anything")
    assert len(layer.calls) == 1  # invoked exactly once
    assert any(r.source_tier == "semantic" for r in out)


# 7. Late-bind via attach ---------------------------------------------------


@pytest.mark.asyncio
async def test_attach_semantic_layer_late_bind_works() -> None:
    oracle = OracleService(semantic_layer=None)
    layer = _StubSemanticLayer([
        {"type": "agents", "id": "a", "document": "doc", "score": 0.5, "metadata": {}},
    ])
    oracle.attach_semantic_layer(layer)
    out = await oracle.query("q", tiers=["semantic"])
    assert len(out) == 1
    assert out[0].source_tier == "semantic"


# 8. Introspect agent uses Oracle -------------------------------------------


@pytest.mark.asyncio
async def test_introspect_search_knowledge_uses_oracle() -> None:
    from probos.agents.introspect import IntrospectionAgent

    oracle_results = [
        OracleResult(
            source_tier="semantic",
            content="agent doc",
            score=0.9,
            metadata={"id": "a1", "type": "agents", "extra": "z"},
            provenance="[semantic: agents]",
        ),
    ]
    oracle = SimpleNamespace(query=AsyncMock(return_value=oracle_results))
    rt = SimpleNamespace(
        oracle=oracle,
        _oracle_service=oracle,
        _semantic_layer=None,
        codebase_index=None,
    )
    agent = IntrospectionAgent.__new__(IntrospectionAgent)
    agent._runtime = rt
    out = await agent._search_knowledge(rt, {"query": "foo"})
    oracle.query.assert_awaited_once()
    kwargs = oracle.query.call_args.kwargs
    assert kwargs.get("tiers") == ["semantic"]
    assert out["success"] is True
    results = out["data"]["results"]
    assert len(results) == 1
    found = results[0]
    assert found["type"] == "agents"
    assert found["document"] == "agent doc"
    assert found["score"] == 0.9
    assert found["metadata"]["extra"] == "z"


# 9. Organizer NoteTaker uses Oracle and awaits -----------------------------


@pytest.mark.asyncio
async def test_organizer_note_taker_uses_oracle_and_awaits() -> None:
    from probos.agents.utility.organizer_agents import NoteTakerAgent

    oracle_results = [
        OracleResult(
            source_tier="semantic",
            content="note doc",
            score=0.7,
            metadata={"id": "n1", "type": "notes"},
            provenance="[semantic: notes]",
        ),
    ]
    oracle = SimpleNamespace(query=AsyncMock(return_value=oracle_results))
    rt = SimpleNamespace(oracle=oracle, _oracle_service=oracle)

    agent = NoteTakerAgent.__new__(NoteTakerAgent)
    agent._runtime = rt
    obs = await agent.perceive(
        {"params": {"action": "search", "query": "foo"}},
    )
    oracle.query.assert_awaited_once()
    kwargs = oracle.query.call_args.kwargs
    assert kwargs.get("tiers") == ["semantic"]
    assert "Search results for" in obs.get("fetched_content", "")


# 10. cmd_search uses Oracle, keeps stats panel -----------------------------


@pytest.mark.asyncio
async def test_cmd_search_uses_oracle_and_keeps_stats_panel() -> None:
    from probos.experience.commands.commands_knowledge import cmd_search

    oracle_results = [
        OracleResult(
            source_tier="semantic",
            content="doc",
            score=0.5,
            metadata={"id": "x1", "type": "agents", "extra": "e"},
            provenance="[semantic: agents]",
        ),
    ]
    oracle = SimpleNamespace(query=AsyncMock(return_value=oracle_results))
    layer = MagicMock()
    layer.stats = MagicMock(return_value={"total": 1})

    runtime = SimpleNamespace(oracle=oracle, _oracle_service=oracle, _semantic_layer=layer)
    console = MagicMock()
    await cmd_search(runtime, console, "foo")
    oracle.query.assert_awaited_once()
    kwargs = oracle.query.call_args.kwargs
    assert kwargs.get("tiers") == ["semantic"]
    layer.stats.assert_called_once()
    console.print.assert_called()


# 11. End-to-end normalised merge -------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_query_returns_normalized_oracle_results() -> None:
    layer = _StubSemanticLayer([
        {"type": "agents", "id": "a1", "document": "agent doc",
         "score": 0.95, "metadata": {}},
        {"type": "skills", "id": "s1", "document": "skill doc",
         "score": 0.4, "metadata": {}},
    ])
    oracle = OracleService(semantic_layer=layer)
    out = await oracle.query("foo")
    # Sorted descending by score
    scores = [r.score for r in out]
    assert scores == sorted(scores, reverse=True)
    semantic_hits = [r for r in out if r.source_tier == "semantic"]
    assert len(semantic_hits) == 2
    for r in semantic_hits:
        assert r.provenance.startswith("[semantic:")
